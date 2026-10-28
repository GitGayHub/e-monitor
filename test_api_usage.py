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

    def test_log_summary_labels_each_official_snapshot_and_never_exposes_credentials(self):
        from datetime import datetime,timezone
        second=dict(self.key,client_id='qa-client-two',client_secret='qa-secret-two')
        third=dict(self.key,client_id='qa-client-three',client_secret='qa-secret-three')
        fresh=usage.parse(self.payload,self.now)
        stale=dict(fresh,checkedAt=datetime.fromtimestamp(self.now-3600,timezone.utc).isoformat())
        state={'remaining':0,'reset':1,'api_usage_snapshots':{usage.identity(self.key):fresh,usage.identity(second):stale}}
        result=usage.summarize_for_log(state,[self.key,second,third],self.now)
        self.assertEqual(['measured','stale','unknown'],[x['status'] for x in result])
        self.assertEqual([20,20,None],[x.get('remaining') for x in result])
        self.assertEqual(fresh['checkedAt'],result[0]['checkedAt'])
        for key in (self.key,second,third):
            self.assertNotIn(key['client_id'],str(result));self.assertNotIn(key['client_secret'],str(result))

    def test_log_summary_marks_expired_or_malformed_data_without_fabricating_zero(self):
        good=usage.parse(self.payload,self.now)
        for field,value in [('checkedAt','bad'),('resetAt','bad'),('remaining',False),('remaining',5001)]:
            snapshot=dict(good,**{field:value})
            rows=usage.summarize_for_log({'api_usage_snapshots':{usage.identity(self.key):snapshot}},[self.key],self.now)
            self.assertEqual([{'key':1,'status':'unknown'}],rows)
        from datetime import datetime
        reset=datetime.fromisoformat(good['resetAt']).timestamp()
        rows=usage.summarize_for_log({'api_usage_snapshots':{usage.identity(self.key):good}},[self.key],reset)
        self.assertEqual('stale',rows[0]['status'])

    def test_queue_log_does_not_call_legacy_counter_a_current_all_key_quota(self):
        from datetime import datetime,timezone
        now=datetime.now(timezone.utc).timestamp()
        measured=usage.parse(self.payload,self.now)
        measured.update(checkedAt=datetime.fromtimestamp(now,timezone.utc).isoformat(),
                        resetAt=datetime.fromtimestamp(now+3600,timezone.utc).isoformat())
        state={'remaining':0,'reset':1,'api_usage_snapshots':{usage.identity(self.key):measured}}
        self.access.save(state)
        search={'id':'qa','query':'phone','enabled':True,'filters':{}}
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_configured_ebay_api_keys',return_value=[self.key]), \
             patch.object(monitor,'_ebay_api_paused',return_value=False),patch.object(monitor,'get_last_run',return_value=None), \
             patch.object(monitor,'EBAY_SOURCE','auto'),patch.object(usage,'refresh') as refresh,patch.object(monitor.logger,'info') as log:
            monitor.initialize_api_budget_and_queue([search])
        self.assertEqual(state,self.access.state())
        refresh.assert_called_once()
        messages=[call.args for call in log.call_args_list]
        summary=next(args for args in messages if 'per-key Analytics snapshots' in args[0])
        self.assertEqual(20,summary[-1][0]['remaining'])
        self.assertNotIn(self.key['client_id'],str(messages));self.assertNotIn(self.key['client_secret'],str(messages))
        self.assertFalse(any('real quota remaining' in args[0] for args in messages))

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

    def two_key_state(self, second_remaining=4810):
        second=dict(self.key,client_id='qa-client-two',key_id='two',label='Key 2')
        first=usage.parse(self.payload,self.now)
        first.update(used=5010,remaining=0)
        second_snapshot=dict(first,used=5000-second_remaining,remaining=second_remaining)
        self.access.save(dict(remaining=second_remaining,reset=self.now+4000,
            legacy_primary_key_id='one',last_key_id='two',normal_next_search='preserve',
            api_usage_snapshots={usage.identity(self.key):first,usage.identity(second):second_snapshot}))
        return [self.key,second]

    def test_exhausted_official_key_cannot_reopen_from_other_keys_legacy_counter(self):
        keys=self.two_key_state()
        with patch('ebay_access.time.time',return_value=self.now):
            self.assertFalse(self.access.is_paused(keys))
            chosen=self.access.select_key(keys)
            self.assertEqual('two',chosen['key_id'])
            self.assertFalse(self.access.acquire('one'))
        self.assertEqual({},price_history.get_api_calls_by_key_24h())
        self.assertEqual('preserve',self.access.state()['normal_next_search'])

    def test_cold_runtime_marks_only_the_exhausted_official_key_paused(self):
        keys=self.two_key_state()
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_configured_ebay_api_keys',return_value=keys),patch('ebay_access.time.time',return_value=self.now):
            rows=monitor._runtime_api_keys()
        self.assertEqual([True,False],[row['paused'] for row in rows])
        self.assertEqual([0,4810],[row['remaining'] for row in rows])

    def test_expired_official_window_does_not_hold_the_new_daily_window(self):
        keys=self.two_key_state()
        from datetime import datetime
        reset=datetime.fromisoformat(self.access.state()['api_usage_snapshots'][usage.identity(self.key)]['resetAt']).timestamp()
        with patch('ebay_access.time.time',return_value=reset):
            self.assertEqual('one',self.access.select_key(keys)['key_id'])
            self.assertTrue(self.access.acquire('one'))

    def test_official_availability_never_clears_a_distinct_network_cooldown(self):
        keys=self.two_key_state()
        value=self.access.state();value['key_pauses']={'two':self.now+30};self.access.save(value)
        with patch('ebay_access.time.time',return_value=self.now):
            self.assertTrue(self.access.is_paused(keys))
            self.assertIsNone(self.access.select_key(keys))
        with patch('ebay_access.time.time',return_value=self.now+31):
            self.assertEqual('two',self.access.select_key(keys)['key_id'])
