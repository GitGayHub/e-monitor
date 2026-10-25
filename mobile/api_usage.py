"""Read-only eBay Analytics snapshots. No Browse calls and no credentials persisted."""
import base64
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def identity(key):
    return hashlib.sha256(key['client_id'].encode()).hexdigest()[:16]


def parse(payload, checked_at):
    for group in payload.get('rateLimits', []):
        if group.get('apiContext', '').lower() != 'buy' or group.get('apiName', '').lower() != 'browse':
            continue
        for resource in group.get('resources', []):
            if resource.get('name') != 'buy.browse':
                continue  # Bulk getItems has a separate quota; do not add it to search capacity.
            rates = resource.get('rates', [])
            rates = [r for r in rates if isinstance(r.get('timeWindow'), int) and r['timeWindow'] > 0]
            if not rates:
                continue
            rate = max(rates, key=lambda r:r['timeWindow'])
            for field in ('limit', 'remaining', 'count'):
                if isinstance(rate.get(field), bool) or not isinstance(rate.get(field), int):
                    raise ValueError('Invalid quota counter')
            if rate['limit'] <= 0 or rate['remaining'] < 0 or rate['count'] < 0 or rate['remaining'] > rate['limit']:
                raise ValueError('Invalid quota range')
            reset = datetime.fromisoformat(rate['reset'].replace('Z','+00:00'))
            if reset.tzinfo is None:
                raise ValueError('Quota reset lacks timezone')
            return dict(used=rate['count'], remaining=rate['remaining'], limit=rate['limit'],
                windowSeconds=rate['timeWindow'], resetAt=reset.isoformat(timespec='seconds'),
                checkedAt=datetime.fromtimestamp(checked_at, timezone.utc).isoformat(timespec='seconds'))
    raise ValueError('Browse search quota not returned')


def fetch(key, now, opener=urllib.request.urlopen, timeout=5):
    auth = base64.b64encode((key['client_id']+':'+key['client_secret']).encode()).decode()
    request = urllib.request.Request('https://api.ebay.com/identity/v1/oauth2/token',
        data=urllib.parse.urlencode(dict(grant_type='client_credentials',scope='https://api.ebay.com/oauth/api_scope')).encode(),
        headers={'Authorization':'Basic '+auth,'Content-Type':'application/x-www-form-urlencoded'})
    with opener(request, timeout=timeout) as response:
        token = json.loads(response.read())['access_token']
    request = urllib.request.Request('https://api.ebay.com/developer/analytics/v1_beta/rate_limit?api_name=browse&api_context=buy',
        headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
    with opener(request, timeout=timeout) as response:
        return parse(json.loads(response.read()), now)


def refresh(access, keys, now, fetcher=fetch):
    """One least-recently-attempted key per pass, at most once/15min per key.

    Analytics has its own quota. A drained Browse key must still be measurable.
    Failed checks retain the last successful snapshot and never manufacture 0%.
    """
    if not keys:
        return False
    state = access.state()
    attempts = state.get('api_usage_attempts', {})
    due = [k for k in keys if now - attempts.get(identity(k), 0) >= 900]
    if not due:
        return False
    key = min(due, key=lambda k:attempts.get(identity(k), 0))
    kid = identity(key)
    try:
        snapshot, error = fetcher(key, now), None
    except Exception as exc:
        snapshot, error = None, 'HTTP '+str(exc.code) if hasattr(exc,'code') else type(exc).__name__
    with access.lock:
        state = access.state()
        state.setdefault('api_usage_attempts', {})[kid] = now
        state.setdefault('api_usage_errors', {})[kid] = error
        if snapshot is not None:
            state.setdefault('api_usage_snapshots', {})[kid] = snapshot
        access.save(state)
    return snapshot is not None
