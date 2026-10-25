import { createHash, createPublicKey, verify, timingSafeEqual } from 'node:crypto';

// No OAuth keys or event bodies are logged. Only this dedicated callback is public.
const MAX_BODY = 32768;
const MAX_QUEUE = 10000;
const tokenCache = new Map();
const publicKeys = new Map();
const json = (value, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
});
const sha = value => createHash('sha256').update(value).digest('hex');

async function boundedText(request) {
  const reader = request.body?.getReader();
  if (!reader) throw new Error('body');
  let length = 0;
  const chunks = [];
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.length;
    if (length > MAX_BODY) { await reader.cancel(); throw new Error('size'); }
    chunks.push(value);
  }
  return Buffer.concat(chunks).toString('utf8');
}

function signatureHeader(raw) {
  if (!raw || raw.length > 4096 || !/^[A-Za-z0-9+/=]+$/.test(raw)) throw new Error('signature');
  const value = JSON.parse(Buffer.from(raw, 'base64').toString('utf8'));
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(value.kid || '') ||
      typeof value.signature !== 'string' || !/^[A-Za-z0-9+/=]{8,2048}$/.test(value.signature)) {
    throw new Error('signature');
  }
  return value;
}

async function ebayKey(env, kid, fetcher) {
  const keyId = sha(env.EBAY_CLIENT_ID || '');
  const cacheId = keyId + ':' + kid;
  const now = Date.now();
  if (publicKeys.get(cacheId)?.expires > now) return publicKeys.get(cacheId).key;
  let auth = tokenCache.get(keyId);
  if (!auth || auth.expires <= now) {
    if (!env.EBAY_CLIENT_ID || !env.EBAY_CLIENT_SECRET) throw new Error('oauth_not_configured');
    const response = await fetcher('https://api.ebay.com/identity/v1/oauth2/token', {
      method: 'POST', signal: AbortSignal.timeout(8000),
      headers: { Authorization: 'Basic ' + Buffer.from(env.EBAY_CLIENT_ID + ':' + env.EBAY_CLIENT_SECRET).toString('base64'),
        'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'grant_type=client_credentials&scope=https%3A%2F%2Fapi.ebay.com%2Foauth%2Fapi_scope',
    });
    if (!response.ok) throw new Error('oauth_http_' + response.status);
    const data = await response.json();
    if (!data.access_token || !Number.isFinite(data.expires_in) || data.expires_in < 60) throw new Error('oauth_schema');
    auth = { token: data.access_token, expires: now + (data.expires_in - 60) * 1000 };
    tokenCache.set(keyId, auth);
  }
  const response = await fetcher('https://api.ebay.com/commerce/notification/v1/public_key/' + encodeURIComponent(kid), {
    signal: AbortSignal.timeout(8000), headers: { Authorization: 'Bearer ' + auth.token },
  });
  if (response.status === 404) throw new Error('signature');
  if (!response.ok) throw new Error('public_key_http_' + response.status);
  const value = await response.json();
  const digest = String(value.digest || '').replace('-', '').toUpperCase();
  if (!['ECC', 'ECDSA'].includes(value.algorithm) || !['SHA1', 'SHA256'].includes(digest) || !value.key) {
    const detail = [value.algorithm, digest, typeof value.key].map(x => String(x).replace(/[^A-Za-z0-9]/g,'').slice(0,20)).join('_');
    throw new Error('public_key_schema_' + detail);
  }
  // eBay can return PEM as one line; normalize as its reference SDK does.
  const encoded = value.key.replace('-----BEGIN PUBLIC KEY-----', '')
    .replace('-----END PUBLIC KEY-----', '').replace(/\s/g, '');
  if (!/^[A-Za-z0-9+/=]+$/.test(encoded)) throw new Error('upstream');
  const pem = '-----BEGIN PUBLIC KEY-----\n' + encoded + '\n-----END PUBLIC KEY-----\n';
  const key = { publicKey: createPublicKey(pem), digest: digest.toLowerCase() };
  if (key.publicKey.asymmetricKeyType !== 'ec') throw new Error('public_key_schema_wrong_key_type');
  if (publicKeys.size >= 128) publicKeys.delete(publicKeys.keys().next().value);
  publicKeys.set(cacheId, { key, expires: now + 3600000 });
  return key;
}

function validEvent(value) {
  const note = value?.notification;
  if (value?.metadata?.topic !== 'MARKETPLACE_ACCOUNT_DELETION' ||
      typeof note?.notificationId !== 'string' || note.notificationId.length > 256 || !note.notificationId ||
      !note.data || typeof note.data !== 'object') return false;
  return ['username', 'userId', 'eiasToken'].some(name =>
    typeof note.data[name] === 'string' && note.data[name].length > 0 && note.data[name].length <= 1024);
}

function authorized(request, env) {
  if (!env.QUEUE_TOKEN || env.QUEUE_TOKEN.length < 32) return false;
  return timingSafeEqual(Buffer.from(sha(request.headers.get('Authorization') || '')),
    Buffer.from(sha('Bearer ' + env.QUEUE_TOKEN)));
}

export async function handle(request, env, fetcher = fetch) {
  const url = new URL(request.url);
  if (url.pathname === '/healthz' && request.method === 'GET') return json({ service: 'ebay-deletion', ready: !!env.DB && !!env.ENDPOINT_URL });
  if (url.pathname.startsWith('/internal/')) {
    if (!authorized(request, env)) return json({ error: 'unauthorized' }, 401);
    if (url.pathname === '/internal/status' && request.method === 'GET') {
      const result = await env.DB.prepare('SELECT name, value, recorded_at FROM receiver_health').all();
      return json({ status: result.results });
    }
    if (url.pathname === '/internal/events' && request.method === 'GET') {
      const rows = await env.DB.prepare('SELECT receipt, received_at, body FROM deletion_events ORDER BY received_at, receipt LIMIT 100').all();
      return json({ events: rows.results });
    }
    if (url.pathname === '/internal/ack' && request.method === 'POST') {
      let receipts;
      try { receipts = JSON.parse(await boundedText(request)).receipts; } catch { return json({ error: 'invalid request' }, 400); }
      if (!Array.isArray(receipts) || receipts.length > 100 || receipts.some(x => typeof x !== 'string' || !/^[a-f0-9]{64}$/.test(x))) return json({ error: 'invalid receipts' }, 400);
      if (receipts.length) await env.DB.batch(receipts.map(x => env.DB.prepare('DELETE FROM deletion_events WHERE receipt = ?').bind(x)));
      return json({ acknowledged: receipts.length });
    }
    return json({ error: 'not found' }, 404);
  }
  let endpoint;
  try {
    endpoint = new URL(env.ENDPOINT_URL);
    if (endpoint.protocol !== 'https:' || endpoint.search || endpoint.hash || endpoint.username || endpoint.password ||
        !/^[A-Za-z0-9_-]{32,80}$/.test(env.VERIFICATION_TOKEN || '')) throw new Error('config');
  } catch { return json({ error: 'not configured' }, 503); }
  if (url.origin + url.pathname !== endpoint.href) return json({ error: 'not found' }, 404);
  if (request.method === 'GET') {
    const codes = url.searchParams.getAll('challenge_code');
    if (codes.length !== 1 || !codes[0] || codes[0].length > 1024) return json({ error: 'invalid challenge' }, 400);
    return json({ challengeResponse: sha(codes[0] + env.VERIFICATION_TOKEN + env.ENDPOINT_URL) });
  }
  if (request.method !== 'POST') return json({ error: 'method not allowed' }, 405);
  let raw, value, signature;
  try {
    signature = signatureHeader(request.headers.get('x-ebay-signature'));
    raw = await boundedText(request);
    value = JSON.parse(raw);
    if (!validEvent(value)) return json({ error: 'invalid notification' }, 400);
  } catch (error) { return json({ error: error.message === 'size' ? 'body too large' : 'invalid notification' }, error.message === 'size' ? 413 : 412); }
  try {
    const key = await ebayKey(env, signature.kid, fetcher);
    // Match eBay's reference SDK: verify JSON.stringify(parsed message), not transport whitespace.
    if (!verify(key.digest, Buffer.from(JSON.stringify(value)), key.publicKey, Buffer.from(signature.signature, 'base64'))) return json({ error: 'invalid signature' }, 412);
  } catch (error) {
    // Operational diagnosis only: never save keys, signatures, subjects or raw responses here.
    const reason = /^(oauth_not_configured|oauth_http_\d{3}|oauth_schema|public_key_http_\d{3}|public_key_schema_[A-Za-z0-9_]{1,65}|signature)$/.test(error.message)
      ? error.message : 'crypto_or_network_' + (String(error.code || error.name).replace(/[^A-Za-z0-9_]/g, '').slice(0,80));
    try { await env.DB.prepare('INSERT OR REPLACE INTO receiver_health(name, value, recorded_at) VALUES (?, ?, ?)')
      .bind('verification_error', reason, new Date().toISOString()).run(); } catch { /* primary response remains retryable */ }
    return json({ error: error.message === 'signature' ? 'invalid signature' : 'verification temporarily unavailable' }, error.message === 'signature' ? 412 : 503);
  }
  try {
    const receipt = sha(value.notification.notificationId);
    const existing = await env.DB.prepare('SELECT receipt FROM deletion_events WHERE receipt = ?').bind(receipt).first();
    if (existing) return new Response(null, { status: 204 });
    // Bounded inbox. Overflow is a retryable failure; never acknowledge dropped notifications.
    const result = await env.DB.prepare('INSERT OR IGNORE INTO deletion_events(receipt, received_at, body) SELECT ?, ?, ? WHERE (SELECT COUNT(*) FROM deletion_events) < ?')
      .bind(receipt, new Date().toISOString(), JSON.stringify(value), MAX_QUEUE).run();
    if (!result.meta?.changes) return json({ error: 'queue full' }, 503);
    return new Response(null, { status: 204 });
  } catch { return json({ error: 'storage temporarily unavailable' }, 503); }
}

export default { fetch(request, env) { return handle(request, env); } };
