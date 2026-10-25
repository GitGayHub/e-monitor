import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, generateKeyPairSync, sign } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import worker, { handle } from './worker.mjs';

const endpoint = 'https://unit.invalid/ebay/account-deletion';
const pair = generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
const publicKey = pair.publicKey.export({ format: 'pem', type: 'spki' });
let nextClient = 0;
function setup() {
  const sql = new DatabaseSync(':memory:');
  sql.exec(readFileSync(new URL('./migrations/0001_inbox.sql', import.meta.url), 'utf8'));
  sql.exec(readFileSync(new URL('./migrations/0002_receiver_health.sql', import.meta.url), 'utf8'));
  const DB = {
    prepare(query) {
      let args = [];
      return { bind(...values) { args = values; return this; },
        async first() { return sql.prepare(query).get(...args); },
        async all() { return { results: sql.prepare(query).all(...args) }; },
        async run() { return { meta: { changes: Number(sql.prepare(query).run(...args).changes) } }; } };
    },
    async batch(statements) { return Promise.all(statements.map(statement => statement.run())); },
  };
  const env = { DB, ENDPOINT_URL: endpoint, VERIFICATION_TOKEN: 'v'.repeat(40),
    QUEUE_TOKEN: 'q'.repeat(40), EBAY_CLIENT_ID: 'fixture-' + nextClient++, EBAY_CLIENT_SECRET: 'not-a-real-secret' };
  let calls = 0;
  const upstream = async url => {
    calls++;
    if (url.endsWith('/token')) return Response.json({ access_token: 'test-token', expires_in: 3600 });
    assert.match(url, /^https:\/\/api\.ebay\.com\/commerce\/notification\/v1\/public_key\/unit-key$/);
    return Response.json({ algorithm: 'ECC', digest: 'SHA1', key: publicKey });
  };
  return { env, sql, upstream, calls: () => calls };
}
function body(id = 'unit-event') {
  return { metadata: { topic: 'MARKETPLACE_ACCOUNT_DELETION', schemaVersion: '1.0' },
    notification: { notificationId: id, eventDate: '2026-10-25T01:00:00Z', data: { username: 'synthetic-seller' } } };
}
function signed(value = body(), override = {}) {
  const signature = sign('sha1', Buffer.from(JSON.stringify(value)), pair.privateKey).toString('base64');
  return new Request(endpoint, { method: 'POST', body: JSON.stringify(value, null, 2),
    headers: { 'x-ebay-signature': Buffer.from(JSON.stringify({ kid: 'unit-key', signature })).toString('base64') }, ...override });
}
const hash = x => createHash('sha256').update(x).digest('hex');

test('eBay challenge uses exact configured endpoint, order and SHA256; no storage or OAuth required', async () => {
  const { env, calls } = setup();
  const response = await worker.fetch(new Request(endpoint + '?challenge_code=123'), env, {});
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { challengeResponse: hash('123' + env.VERIFICATION_TOKEN + endpoint) });
  assert.equal(calls(), 0);
});
test('missing/duplicate challenge, wrong origin/path and invalid token do not validate', async () => {
  const { env } = setup();
  for (const url of [endpoint, endpoint + '?challenge_code=', endpoint + '?challenge_code=a&challenge_code=b']) {
    assert.equal((await handle(new Request(url), env)).status, 400);
  }
  assert.equal((await handle(new Request(endpoint.replace('unit.invalid', 'attacker.invalid') + '?challenge_code=123'), env)).status, 404);
  assert.equal((await handle(new Request(endpoint + '?challenge_code=123'), { ...env, VERIFICATION_TOKEN: 'short' })).status, 503);
});
test('unsigned or modified events cannot enter the inbox', async () => {
  const { env, sql, upstream } = setup();
  assert.equal((await handle(new Request(endpoint, { method: 'POST', body: JSON.stringify(body()) }), env, upstream)).status, 412);
  const request = signed();
  const changed = JSON.stringify(body('changed'));
  assert.equal((await handle(new Request(endpoint, { method: 'POST', body: changed, headers: request.headers }), env, upstream)).status, 412);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM deletion_events').get().n, 0);
});
test('verified event is durably stored before 204; repeats deduplicate and keys cache', async () => {
  const { env, sql, upstream, calls } = setup();
  assert.equal((await handle(signed(), env, upstream)).status, 204);
  assert.equal((await handle(signed(), env, upstream)).status, 204);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM deletion_events').get().n, 1);
  assert.equal(calls(), 2);
  assert.deepEqual(JSON.parse(sql.prepare('SELECT body FROM deletion_events').get().body), body());
});
test('upstream failure and durable storage failure are retryable, never falsely acknowledged', async () => {
  const { env, upstream } = setup();
  assert.equal((await handle(signed(), env, async () => new Response('', { status: 429 }))).status, 503);
  const broken = { ...env, DB: { prepare() { throw new Error('offline'); } } };
  assert.equal((await handle(signed(), broken, upstream)).status, 503);
});
test('public key without PEM line breaks matches eBay reference SDK formatting', async () => {
  const { env, upstream } = setup();
  const compact = publicKey.replace(/\r?\n/g, '');
  const fetcher = async (url, options) => url.endsWith('/token') ? upstream(url, options) :
    Response.json({ algorithm: 'ECC', digest: 'SHA1', key: compact });
  assert.equal((await handle(signed(body('compact-key')), env, fetcher)).status, 204);
});
test('live eBay public-key algorithm ECDSA is verified as an EC key', async () => {
  const { env, upstream } = setup();
  const fetcher = async (url, options) => url.endsWith('/token') ? upstream(url, options) :
    Response.json({ algorithm: 'ECDSA', digest: 'SHA1', key: publicKey.replace(/\r?\n/g, '') });
  assert.equal((await handle(signed(body('ecdsa-key')), env, fetcher)).status, 204);
});
test('queue is private; explicit acknowledgement removes only selected receipt', async () => {
  const { env, sql, upstream } = setup();
  await handle(signed(), env, upstream);
  await handle(signed(body('second')), env, upstream);
  const privateUrl = 'https://unit.invalid/internal/events';
  assert.equal((await handle(new Request(privateUrl), env)).status, 401);
  const headers = { Authorization: 'Bearer ' + env.QUEUE_TOKEN };
  const result = await (await handle(new Request(privateUrl, { headers }), env)).json();
  assert.equal(result.events.length, 2);
  const receipt = result.events[0].receipt;
  assert.equal((await handle(new Request('https://unit.invalid/internal/ack', { method: 'POST', headers, body: JSON.stringify({ receipts: [receipt] }) }), env)).status, 200);
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM deletion_events').get().n, 1);
});
test('oversized signed body is rejected; no unexpected event topic is accepted', async () => {
  const { env, upstream } = setup();
  const request = signed();
  assert.equal((await handle(new Request(endpoint, { method: 'POST', headers: request.headers, body: 'x'.repeat(32769) }), env, upstream)).status, 413);
  const value = body(); value.metadata.topic = 'OTHER';
  assert.equal((await handle(signed(value), env, upstream)).status, 400);
});
