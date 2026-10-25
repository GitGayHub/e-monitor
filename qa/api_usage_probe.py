"""Read-only acceptance of the explicitly configured second Production key."""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mobile.api_usage import parse


def main():
    key_id=os.environ.get('EBAY_CLIENT_ID_2','').strip()
    secret=os.environ.get('EBAY_CLIENT_SECRET_2','').strip()
    proof=dict(keySlot=2,credentialsPresent=bool(key_id and secret),readOnly=True,telegramSent=False)
    try:
        if not proof['credentialsPresent']:
            raise ValueError('Missing key pair')
        request=urllib.request.Request('https://api.ebay.com/identity/v1/oauth2/token',
            data=urllib.parse.urlencode(dict(grant_type='client_credentials',scope='https://api.ebay.com/oauth/api_scope')).encode(),
            headers={'Authorization':'Basic '+base64.b64encode((key_id+':'+secret).encode()).decode(),
                     'Content-Type':'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(request,timeout=15) as response:
            token=json.loads(response.read())['access_token']
        proof['oauthAccepted']=True
        request=urllib.request.Request('https://api.ebay.com/developer/analytics/v1_beta/rate_limit?api_name=browse&api_context=buy',
            headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
        with urllib.request.urlopen(request,timeout=15) as response:
            proof['quota']=parse(json.loads(response.read()),time.time())
        if proof['quota']['remaining']>0:
            request=urllib.request.Request('https://api.ebay.com/buy/browse/v1/item_summary/search?q=iphone%2017%20pro%20max&limit=1',
                headers={'Authorization':'Bearer '+token,'X-EBAY-C-MARKETPLACE-ID':'EBAY_DE','Accept':'application/json'})
            with urllib.request.urlopen(request,timeout=15) as response:
                payload=json.loads(response.read())
                proof['browseHttp']=response.status
                proof['itemsReturned']=len(payload.get('itemSummaries',[]))
        proof['success']=proof.get('browseHttp')==200
    except Exception as error:
        proof.update(success=False,error='HTTP '+str(error.code) if hasattr(error,'code') else type(error).__name__)
    Path('api-usage-proof.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf8')
    print(json.dumps(proof))
    return 0 if proof.get('success') else 1

if __name__=='__main__':
    raise SystemExit(main())
