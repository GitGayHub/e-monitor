import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import monitor
import price_history
from ebay_access import BrowseAccess
from mobile import api_usage as usage


class ApiUsageTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        patcher=patch.object(price_history,'DB_PATH',str(Path(self.temp.name)/'qa.db'))
        patcher.start();self.addCleanup(patcher.stop)
        price_history.init_db()
        self.access=BrowseAccess()
        self.key=dict(client_id='qa-client-one',client_secret='qa-secret-one',key_id='one',label='Key 1')
        self.payload=dict(rateLimits=[dict(apiContext='buy',apiName='Browse',resources=[
            dict(name='buy.browse.item.bulk',rates=[dict(count=0,limit=5000,remaining=5000,reset='2026-10-25T07:00:00Z',timeWindow=86400)]),
            dict(name='buy.browse',rates=[dict(count=4980,limit=5000,remaining=20,reset='2026-10-25T07:00:00Z',timeWindow=86400)])])])
        self.now=1792889100

    def test_official_daily_counter_never_uses_separate_bulk_allowance(self):
        data=usage.parse(self.payload,self.now)
        self.assertEqual((4980,20,5000,86400),(data['used'],data['remaining'],data['limit'],data['windowSeconds']))
        self.assertEqual('2026-10-25T07:00:00+00:00',data['resetAt'])
        bad=copy.deepcopy(self.payload);bad['rateLimits'][0]['resources']=bad['rateLimits'][0]['resources'][:1]
        with self.assertRaises(ValueError):usage.parse(bad,self.now)

    def test_invalid_counters_cannot_become_zero_percent(self):
        for field,value in [('count',False),('remaining',-1),('limit',0),('remaining',5001),('reset','not-a-date')]:
            bad=copy.deepcopy(self.payload);bad['rateLimits'][0]['resources'][1]['rates'][0][field]=value
            with self.subTest(field=field,value=value),self.assertRaises((ValueError,TypeError)):
                usage.parse(bad,self.now)

    def test_analytics_is_readable_even_while_browse_is_paused_without_spending_browse(self):
        self.access.save(dict(remaining=0,reset=self.now+4000,normal_next_search='keep'))
        seen=[]
        def opener(req,timeout):
            seen.append(req.full_url)
            return io.BytesIO(json.dumps({'access_token':'qa-only'} if 'oauth2/token' in req.full_url else self.payload).encode())
        fetcher=lambda key,now:usage.fetch(key,now,opener=opener)
        self.assertTrue(usage.refresh(self.access,[self.key],self.now,fetcher))
        self.assertEqual(2,len(seen))
        self.assertFalse(any('/buy/browse/' in url for url in seen))
        state=self.access.state()
        self.assertEqual(0,state['remaining']);self.assertEqual('keep',state['normal_next_search'])
        self.assertEqual({},price_history.get_api_calls_by_key_24h())
        self.assertNotIn(self.key['client_secret'],json.dumps(state));self.assertNotIn(self.key['client_id'],json.dumps(state))
        self.assertFalse(usage.refresh(self.access,[self.key],self.now+899,fetcher))

    def test_failed_refresh_preserves_last_official_measurement_and_other_keys(self):
        good=usage.parse(self.payload,self.now)
        self.assertTrue(usage.refresh(self.access,[self.key],self.now,lambda *_:good))
        def fail(*_):raise OSError('do not publish credentials or response body')
        self.assertFalse(usage.refresh(self.access,[self.key],self.now+901,fail))
        state=self.access.state()
        self.assertEqual(good,state['api_usage_snapshots'][usage.identity(self.key)])
        self.assertEqual('OSError',state['api_usage_errors'][usage.identity(self.key)])
        other=dict(self.key,client_id='other-application')
        self.assertTrue(usage.refresh(self.access,[self.key,other],self.now+902,lambda *_:dict(good,remaining=100)))
        self.assertEqual(2,len(self.access.state()['api_usage_snapshots']))

    def test_runtime_prefers_official_measurement_over_incomplete_local_attempt_counter(self):
        self.access.save(dict(api_usage_snapshots={usage.identity(self.key):usage.parse(self.payload,self.now)}))
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_configured_ebay_api_keys',return_value=[self.key]),patch.object(price_history,'get_api_calls_by_key_24h',return_value={'':5072}):
            row=monitor._runtime_api_keys()[0]
        self.assertEqual((4980,20,'ebay_analytics'),(row['used24h'],row['remaining'],row['usageSource']))
        self.assertIsNotNone(row['usageUpdatedAt']);self.assertIsNotNone(row['quotaResetAt'])

    def test_missing_official_snapshot_labels_counter_as_estimate(self):
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_configured_ebay_api_keys',return_value=[self.key]):
            row=monitor._runtime_api_keys()[0]
        self.assertEqual('monitor_log_estimate',row['usageSource'])
        self.assertNotIn('quotaResetAt',row)
