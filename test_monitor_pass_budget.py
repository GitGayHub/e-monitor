"""Runner deadlines preserve verification and rotate the persisted queue."""
import asyncio,copy,json,os,sqlite3,tempfile,unittest
from contextlib import closing,nullcontext
from pathlib import Path
from unittest.mock import patch,Mock,AsyncMock
import monitor,price_history
from ebay_access import MonitorPassBudget,BrowseAccess
import test_verified_history as history_fixtures


class MonitorPassBudgetTests(unittest.TestCase):
    def test_priority_is_reconsidered_after_slow_search_without_repeating_a_product(self):
        searches=[dict(copy.deepcopy(self.search),id=k,priority=rank,notify=False)
                  for k,rank in [('first',1),('second',2),('third',3)]]
        self.config.raw={'mobile_managed':True};self.config.get_searches=lambda:searches;self.config.save=Mock()
        self.access.save({'html_attempts':{'first|EBAY_DE':995,'second|EBAY_DE':970,'third|EBAY_DE':950}})
        fetched=[]
        parent=MonitorPassBudget(180,clock=lambda:self.clock[0]);token=MonitorPassBudget.current.set(parent)
        def fetch(search,**kwargs):
            fetched.append(search['id']);self.clock[0]+=20
            return [],None
        try:
            with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_is_statistics_mode',return_value=False),patch.object(monitor,'initialize_api_budget_and_queue'),patch.object(monitor,'fetch_ebay_ex',side_effect=fetch),patch.object(monitor,'save_seen_ids'),patch('mobile.feed_writer.flush_pending'),patch('ebay_access.time.time',side_effect=lambda:1000+self.clock[0]):
                asyncio.run(monitor._process_searches_in_pass(None,once=True))
            self.assertEqual(['second','first','third'],fetched)
            self.assertEqual(3,len(set(fetched)))
            self.assertEqual([1,2,3],[s['priority'] for s in searches])
            self.assertEqual(0,price_history.get_api_calls_count_24h())
        finally:MonitorPassBudget.current.reset(token)

    def test_queue_audit_distinguishes_unknown_clock_wait_and_ready_without_seller_text(self):
        self.search['filters']['listing_type']='auction'
        self.config.get_item_hashes=lambda:set()
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        base=rows[0]
        lots=[dict(copy.deepcopy(base),item_id=i,auction=True,buy_now=False,time_left=clock,
                   seller_name='private-seller',source='html')
              for i,clock in [('unknown',''),('waiting','2d 1h'),('ready','23h 59min')]]
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'seen_state',{}),patch.object(monitor,'seen_ids',set()),patch.object(monitor.logger,'info') as log:
            asyncio.run(monitor._verified_history(lots,self.search,on_verified=AsyncMock(),max_candidates=0))
        call=next(c for c in log.call_args_list if c.args[0].startswith('Live validation queue'))
        audit=json.loads(call.args[-1])
        self.assertEqual(['ready','unknown','waiting'],[row['id'] for row in audit])
        self.assertEqual(['notify','auction_time_unknown','wait_24h'],[row['gate'] for row in audit])
        self.assertEqual([True,False,False],[row['ready'] for row in audit])
        self.assertNotIn('private-seller',call.args[-1])
        self.assertNotIn(base['title'],call.args[-1])
        self.assertEqual(['unknown','waiting','ready'],[row['item_id'] for row in lots])

    def test_queue_audit_bounds_rows_and_records_actual_unavailable_validation(self):
        self.config.get_item_hashes=lambda:set()
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        lots=[dict(copy.deepcopy(rows[0]),item_id=str(n)) for n in range(90)]
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'seen_state',{}),patch.object(monitor,'seen_ids',set()),patch.object(monitor,'_fetch_item_details',return_value=None),patch.object(monitor.logger,'info') as log:
            values=asyncio.run(monitor._verified_history(lots,self.search,on_verified=AsyncMock(),max_candidates=1))
        queue=next(c for c in log.call_args_list if c.args[0].startswith('Live validation queue'))
        self.assertEqual((90,10),queue.args[2:4])
        self.assertEqual(80,len(json.loads(queue.args[-1])))
        result=next(c for c in log.call_args_list if c.args[0].startswith('Live validation result'))
        self.assertEqual(('qa','0','unavailable',False),result.args[1:])
        self.assertEqual([],values)

    def test_real_budgeted_normal_loop_searches_all_forty_eight_when_they_fit(self):
        searches=[dict(copy.deepcopy(self.search),id=f'p{i:02d}',query=f'QA Device {i}',notify=False) for i in range(48)]
        self.config.raw={'mobile_managed':True};self.config.get_searches=lambda:searches;self.config.save=Mock()
        fetched=[]
        def html(host,search,**kwargs):
            fetched.append(search['id']);self.clock[0]+=4;return [],None
        parent=MonitorPassBudget(390,clock=lambda:self.clock[0]);token=MonitorPassBudget.current.set(parent)
        try:
            with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'EBAY_SOURCE','auto'),patch.object(monitor,'_ebay_api_configured',return_value=False),patch.object(monitor,'_is_statistics_mode',return_value=False),patch.object(monitor,'_ebay_query_cache',{}),patch.object(monitor,'_ebay_block_until',0),patch.object(monitor,'_ebay_active_host',None),patch.object(monitor,'_host_chain_for_search',return_value=['ebay.de']),patch.object(monitor,'_search_query_variants',side_effect=lambda s:[s['query']]),patch.object(monitor,'_do_fetch_one',side_effect=html),patch.object(monitor,'save_seen_ids'),patch('mobile.feed_writer.flush_pending'):
                asyncio.run(monitor._process_searches_in_pass(None,once=True))
            self.assertEqual([s['id'] for s in searches],fetched)
            self.assertEqual(48,len(self.access.state()['html_attempts']))
            self.assertEqual(192,self.clock[0]);self.assertEqual(0,price_history.get_api_calls_count_24h())
        finally:MonitorPassBudget.current.reset(token)

    def test_rejected_own_descriptions_count_as_read_but_unavailable_does_not(self):
        rows,details=history_fixtures.VerifiedHistoryTests.data(self,unavailable=True)
        progress={'descriptionsVerified':0}
        token=MonitorPassBudget.current.set(MonitorPassBudget(390,clock=lambda:self.clock[0]))
        try:
            with patch.object(monitor,'_runtime_progress',progress),patch.object(monitor,'_fetch_item_details',side_effect=lambda i:details[i]):
                verified=asyncio.run(monitor._verified_history(rows,self.search))
            self.assertEqual({'seen','expensive'},{r['item_id'] for r in verified})
            self.assertEqual(4,progress['descriptionsVerified'])
            self.assertIsNone(price_history.get_stats_7d('qa',monitor._history_filter_signature(self.search)))
        finally:MonitorPassBudget.current.reset(token)
    def test_full_seller_details_keep_eight_seconds_for_api_after_html_timeout(self):
        data={'description':'Own fully working device, with original box.','price':{'value':'400'}}
        def html(*a,**k):self.assertEqual(12,MonitorPassBudget.current.get().seconds);self.clock[0]=12;return None
        def api(*a,**k):
            self.assertEqual(8,k['timeout']);return nullcontext(Mock(read=lambda:json.dumps(data).encode()))
        parent=MonitorPassBudget(20,clock=lambda:self.clock[0]);token=MonitorPassBudget.current.set(parent)
        try:
            with patch.object(monitor,'EBAY_SOURCE','auto'),patch.object(monitor,'_item_details_cache',{}),patch.object(monitor,'_ebay_api_circuit_open',False),patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_ebay_api_configured',return_value=True),patch.object(monitor,'_fetch_item_details_html',side_effect=html),patch.object(monitor,'_get_ebay_api_token',return_value=('isolated-token',None)),patch.object(monitor.urllib.request,'urlopen',side_effect=api):
                self.assertEqual(data,monitor._fetch_item_details('description-control'))
        finally:MonitorPassBudget.current.reset(token)

    def test_overshooting_html_details_cannot_spend_api_quota_after_parent_deadline(self):
        def html(*a,**k):self.clock[0]=21;return None
        parent=MonitorPassBudget(20,clock=lambda:self.clock[0]);token=MonitorPassBudget.current.set(parent)
        try:
            with patch.object(monitor,'EBAY_SOURCE','auto'),patch.object(monitor,'_item_details_cache',{}),patch.object(monitor,'_ebay_api_circuit_open',False),patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_ebay_api_configured',return_value=True),patch.object(monitor,'_fetch_item_details_html',side_effect=html),patch.object(monitor,'_get_ebay_api_token') as oauth:
                self.assertIsNone(monitor._fetch_item_details('expired-description-control'))
            oauth.assert_not_called()
        finally:MonitorPassBudget.current.reset(token)
    def test_html_deadline_retains_time_for_one_quota_checked_api_reserve(self):
        seen=[]
        parent=MonitorPassBudget(20,clock=lambda:self.clock[0]);token=MonitorPassBudget.current.set(parent)
        def html(*args,**kwargs):
            seen.append(('html',MonitorPassBudget.current.get().deadline))
            self.clock[0]=12
            return [],'pass_deferred'
        def api(*args,**kwargs):
            seen.append(('api',MonitorPassBudget.current.get().deadline-self.clock[0]))
            return [{'item_id':'verified-later'}],None
        try:
            with patch.object(monitor,'fetch_ebay_ex',side_effect=html),patch.object(monitor,'fetch_ebay_api_ex',side_effect=api) as reserve,patch.object(monitor,'_search_query_variants',return_value=['qa']),patch.object(monitor,'_ebay_api_configured',return_value=True),patch.object(monitor,'_ebay_api_circuit_open',False),patch.object(monitor,'record_search_run'),patch.object(monitor,'browse_access',self.access):
                rows,error=monitor._fetch_html_primary(self.search,force=True,allow_api=True)
            self.assertIsNone(error);self.assertEqual('verified-later',rows[0]['item_id'])
            self.assertEqual([('html',12),('api',8)],seen);reserve.assert_called_once()
            self.assertIs(parent,MonitorPassBudget.current.get())
        finally:MonitorPassBudget.current.reset(token)

    def test_live_slice_does_not_spend_search_deadline_on_homepage_warmup(self):
        session=Mock()
        with MonitorPassBudget.slice(20):
            with patch.object(monitor.time,'sleep') as sleep:
                monitor._warmup_session(session,'ebay.de')
        session.get.assert_not_called();sleep.assert_not_called()

    def test_expired_html_never_ignores_a_real_api_quota_pause(self):
        import time
        self.access.save({'remaining':0,'reset':time.time()+60})
        parent=MonitorPassBudget(20,clock=lambda:self.clock[0]);token=MonitorPassBudget.current.set(parent)
        def html(*args,**kwargs):
            self.assertEqual(20,MonitorPassBudget.current.get().seconds)
            return [],'pass_deferred'
        try:
            with patch.object(monitor,'fetch_ebay_ex',side_effect=html),patch.object(monitor,'fetch_ebay_api_ex') as api,patch.object(monitor,'_search_query_variants',return_value=['qa']),patch.object(monitor,'_ebay_api_configured',return_value=True),patch.object(monitor,'_ebay_api_circuit_open',False),patch.object(monitor,'browse_access',self.access):
                rows,error=monitor._fetch_html_primary(self.search,force=True,allow_api=True)
            self.assertEqual(([],'pass_deferred'),(rows,error));api.assert_not_called()
        finally:MonitorPassBudget.current.reset(token)

    def test_child_deadline_clips_io_and_restores_parent_on_exception(self):
        parent=MonitorPassBudget(90,clock=lambda:self.clock[0]);token=MonitorPassBudget.current.set(parent)
        try:
            with self.assertRaisesRegex(RuntimeError,'qa'):
                with MonitorPassBudget.slice(20,reserve=30) as child:
                    self.assertEqual(20,child.deadline)
                    self.assertEqual((10,10),MonitorPassBudget.timeout((10,20)))
                    self.clock[0]=19
                    self.assertEqual((.5,.5),MonitorPassBudget.timeout((10,20)))
                    self.assertEqual(1000,MonitorPassBudget.milliseconds(25000))
                    raise RuntimeError('qa')
            self.assertIs(parent,MonitorPassBudget.current.get())
            self.assertFalse(MonitorPassBudget.exhausted(reserve=30))
        finally:MonitorPassBudget.current.reset(token)

    def test_slow_first_query_does_not_block_next_product_or_discard_valid_partial_rows(self):
        parent=MonitorPassBudget(200,clock=lambda:self.clock[0]);token=MonitorPassBudget.current.set(parent)
        self.config.get_item_hashes=lambda:set();self.config.save=Mock();self.config.raw={'mobile_managed':True}
        searches=[dict(copy.deepcopy(self.search),id=s) for s in ('a','b')];self.config.get_searches=lambda:searches
        rows,details=history_fixtures.VerifiedHistoryTests.data(self);base=rows[0];body=details[base['item_id']];fetched=[]
        def fetch(search,*args,**kwargs):
            fetched.append(search['id'])
            if search['id']=='a':self.clock[0]+=21
            return [dict(copy.deepcopy(base),item_id=search['id'])], 'pass_deferred' if search['id']=='a' else None
        try:
            with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_is_statistics_mode',return_value=False),patch.object(monitor,'initialize_api_budget_and_queue'),patch.object(monitor,'fetch_ebay_ex',side_effect=fetch),patch.object(monitor,'_fetch_item_details',return_value=body),patch.object(monitor,'_process_notify_candidate',new=AsyncMock(return_value=True)) as send,patch.object(monitor,'seen_ids',set()),patch.object(monitor,'seen_state',{}),patch.object(monitor,'save_seen_ids'),patch('mobile.feed_writer.flush_pending'),patch.object(monitor.asyncio,'sleep',new=AsyncMock()):
                asyncio.run(monitor._process_searches_in_pass(None,once=True))
            self.assertEqual(['a','b'],fetched)
            self.assertEqual(['a','b'],[call.args[1]['item_id'] for call in send.await_args_list])
            self.assertTrue(all(call.args[1]['_details_status']=='verified' for call in send.await_args_list))
            self.assertIsNone(price_history.get_stats_7d('a',monitor._history_filter_signature(searches[0])))
            self.assertTrue(any('search_deferred' in value for value in monitor._runtime_pending))
        finally:MonitorPassBudget.current.reset(token)

    def test_expired_live_description_yields_without_becoming_a_fake_filter_rejection(self):
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        self.config.get_item_hashes=lambda:set()
        def fetch(item_id):self.clock[0]+=21;return None
        parent=MonitorPassBudget(200,clock=lambda:self.clock[0]);token=MonitorPassBudget.current.set(parent)
        try:
            callback=AsyncMock()
            with patch.object(monitor,'_fetch_item_details',side_effect=fetch),patch.object(monitor,'seen_ids',set()),patch.object(monitor,'seen_state',{}):
                values=asyncio.run(monitor._verified_history(rows[:1],self.search,on_verified=callback,max_candidates=2))
            self.assertFalse(values);callback.assert_not_awaited()
            self.assertFalse(monitor._runtime_errors)
            self.assertTrue(any('истекло время проверки' in value for value in monitor._runtime_pending))
        finally:MonitorPassBudget.current.reset(token)
    def test_live_slice_delivers_before_next_description_then_resumes_remainder(self):
        self.config.get_item_hashes=lambda:set()
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        base=rows[0];detail=details[base['item_id']]
        rows=[dict(copy.deepcopy(base),item_id=str(n)) for n in range(5)]
        events=[]
        def fetch(i):events.append('fetch:'+i);return copy.deepcopy(detail)
        async def deliver(row):events.append('deliver:'+row['item_id'])
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_fetch_item_details',side_effect=fetch),patch.object(monitor,'seen_state',{}),patch.object(monitor,'seen_ids',set()):
            first=asyncio.run(monitor._verified_history(rows,self.search,on_verified=deliver,max_candidates=2))
            second=asyncio.run(monitor._verified_history(rows,self.search,on_verified=deliver,max_candidates=2))
        self.assertEqual(['0','1'],[x['item_id'] for x in first])
        self.assertEqual(['2','3'],[x['item_id'] for x in second])
        self.assertEqual(['fetch:0','deliver:0','fetch:1','deliver:1','fetch:2','deliver:2','fetch:3','deliver:3'],events)
        self.assertIsNone(price_history.get_stats_7d('qa',monitor._history_filter_signature(self.search)))

    def test_unseen_affordable_lot_precedes_old_expensive_history(self):
        self.config.get_item_hashes=lambda:set()
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        expensive=rows[1];cheap=rows[0]
        calls=[]
        def fetch(i):calls.append(i);return details[i]
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_fetch_item_details',side_effect=fetch),patch.object(monitor,'seen_state',{}),patch.object(monitor,'seen_ids',set()):
            asyncio.run(monitor._verified_history([expensive,cheap],self.search,on_verified=AsyncMock(),max_candidates=1))
        self.assertEqual([cheap['item_id']],calls)

    def test_newest_live_discovery_does_not_change_stats_or_original_settings(self):
        original=copy.deepcopy(self.search)
        live=monitor._normal_discovery_search(self.search)
        self.assertEqual('newest',live['filters']['sort'])
        self.assertEqual(self.search['id'],live['id'])
        self.assertEqual('price_asc',monitor._statistics_search_variant(self.search,'buy_now')['filters']['sort'])
        self.assertEqual(original,self.search)

    def test_first_discovery_survives_restart_and_is_not_listing_creation(self):
        rows=[{'item_id':'a'}]
        with patch('ebay_access.time.time',return_value=100):self.access.note_normal_discovery(rows,'s','DE')
        with patch('ebay_access.time.time',return_value=200):later=BrowseAccess().note_normal_discovery([{'item_id':'a'},{'item_id':'b'}],'s','DE')
        self.assertEqual([100,200],[r['_first_discovered_at'] for r in later])
        from mobile.feed_writer import build_entry
        entry=build_entry(dict(later[0],_details_verified_at=201,_telegram_confirmed_at=202),{'id':'s'})
        self.assertEqual((100000,201000,202000),(entry['firstDiscoveredTime'],entry['detailsVerifiedTime'],entry['telegramConfirmedTime']))
        self.assertNotIn('listingCreatedAt',entry)

    def test_long_first_product_yields_to_next_product_and_sends_each_immediately(self):
        searches=[dict(copy.deepcopy(self.search),id=s) for s in ('a','b')]
        self.config.raw={'mobile_managed':True};self.config.get_searches=lambda:searches;self.config.save=Mock();self.config.get_item_hashes=lambda:set()
        rows,details=history_fixtures.VerifiedHistoryTests.data(self);base=rows[0];detail=details[base['item_id']]
        events=[]
        def fetch(s,*args,**kwargs):
            events.append('search:'+s['id']);self.assertEqual('newest',s['filters']['sort'])
            return [dict(copy.deepcopy(base),item_id=s['id']+str(n)) for n in range(6)],None
        def fetch_details(i):events.append('details:'+i);return copy.deepcopy(detail)
        async def send(bot,row,*args):events.append('send:'+row['item_id']);return True
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_is_statistics_mode',return_value=False),patch.object(monitor,'initialize_api_budget_and_queue'),patch.object(monitor,'fetch_ebay_ex',side_effect=fetch),patch.object(monitor,'_fetch_item_details',side_effect=fetch_details),patch.object(monitor,'_process_notify_candidate',side_effect=send),patch.object(monitor,'seen_ids',set()),patch.object(monitor,'seen_state',{}),patch.object(monitor,'save_seen_ids'),patch('mobile.feed_writer.flush_pending'),patch.object(monitor.asyncio,'sleep',new=AsyncMock()):
            asyncio.run(monitor._process_searches_in_pass(None,once=True))
        self.assertEqual(['search:a','details:a0','send:a0','details:a1','send:a1','search:b','details:b0','send:b0','details:b1','send:b1'],events)

    def test_html_refresh_uses_three_minute_pacing_without_consuming_api_quota(self):
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'EBAY_SOURCE','auto'),patch.object(monitor,'get_last_run',return_value=None),patch.object(monitor,'_get_ebay_api_token') as token:
            with patch('ebay_access.time.time',return_value=1000):self.access.record_html_attempt('qa',monitor.EBAY_MARKETPLACE_ID)
            with patch('ebay_access.time.time',return_value=1179):monitor.initialize_api_budget_and_queue([self.search]);self.assertFalse(monitor._allowed_api_targets_this_run)
            with patch('ebay_access.time.time',return_value=1180):monitor.initialize_api_budget_and_queue([self.search]);self.assertIn(('qa',monitor.EBAY_MARKETPLACE_ID),monitor._allowed_api_targets_this_run)
        token.assert_not_called()

    def test_ending_sweep_uses_own_cursor_after_fresh_delivery_and_is_not_quota_deferred(self):
        self.search['filters']['listing_type']='auction'
        self.config.raw={'mobile_managed':True};self.config.get_searches=lambda:[self.search];self.config.save=Mock();self.config.get_item_hashes=lambda:set()
        rows,details=history_fixtures.VerifiedHistoryTests.data(self);base=rows[0]
        events=[]
        def fetch(s,*args,**kwargs):
            ending=s['id'].endswith('__ending_soon');events.append('fetch-ending' if ending else 'fetch-newest')
            if ending:self.assertTrue(kwargs.get('force'));self.assertEqual('ending_soon',s['filters']['sort'])
            return [dict(copy.deepcopy(base),item_id='ending' if ending else 'fresh'+str(n),auction=True,buy_now=False,best_offer=True,time_left='10 min') for n in range(1 if ending else 60)],None
        async def verify(items,search,on_verified=None,**kwargs):
            events.append('verify'+kwargs.get('cursor_suffix',''))
            if on_verified:await on_verified(items[0])
            return items[:1]
        async def send(bot,row,*args):events.append('send:'+row['item_id']);return True
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_on_github_actions',return_value=True),patch.object(monitor,'_is_statistics_mode',return_value=False),patch.object(monitor,'initialize_api_budget_and_queue'),patch.object(monitor,'fetch_ebay_ex',side_effect=fetch),patch.object(monitor,'_verified_history',side_effect=verify),patch.object(monitor,'_process_notify_candidate',side_effect=send),patch.object(monitor,'seen_ids',set()),patch.object(monitor,'seen_state',{}),patch.object(monitor,'save_seen_ids'),patch('mobile.feed_writer.flush_pending'),patch.object(monitor.asyncio,'sleep',new=AsyncMock()):
            asyncio.run(monitor._process_searches_in_pass(None,once=True))
        self.assertEqual(['fetch-newest','verify','send:fresh0','fetch-ending','verify__ending','send:ending'],events)

    def test_html_first_pass_does_not_repeat_its_api_reserve_at_the_end(self):
        self.config.raw={'mobile_managed':True};self.config.get_searches=lambda:[self.search];self.config.save=Mock()
        token=MonitorPassBudget.current.set(MonitorPassBudget(90,clock=lambda:0.0))
        try:
            with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_is_statistics_mode',return_value=False), \
                 patch.object(monitor,'EBAY_SOURCE','auto'),patch.object(monitor,'_ebay_api_configured',return_value=True), \
                 patch.object(monitor,'_ebay_api_circuit_open',False),patch.object(monitor,'_ebay_block_until',0), \
                 patch.object(monitor,'_search_query_variants',return_value=['qa']),patch.object(monitor,'_do_fetch_one',return_value=([],'blocked')), \
                 patch.object(monitor,'_do_fetch_playwright',return_value=([],'blocked')),patch.object(monitor,'_ebay_query_cache',{}), \
                 patch.object(monitor,'fetch_ebay_api_ex',return_value=([],None)) as reserve, \
                 patch.object(monitor,'save_seen_ids'),patch('mobile.feed_writer.flush_pending'),patch.object(monitor.asyncio,'sleep',new=AsyncMock()):
                asyncio.run(monitor._process_searches_in_pass(None,once=True))
            reserve.assert_called_once()
        finally:
            MonitorPassBudget.current.reset(token)

    def setUp(self):
        pending=patch.object(monitor,'_runtime_pending',[]);pending.start();self.addCleanup(pending.stop)
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.db=patch.object(price_history,'DB_PATH',str(Path(self.folder.name)/'history.db'))
        self.db.start();self.addCleanup(self.db.stop);price_history.init_db()
        self.access=BrowseAccess();self.clock=[0.0]
        self.budget=MonitorPassBudget(40,clock=lambda:self.clock[0])
        self.token=MonitorPassBudget.current.set(self.budget)
        self.addCleanup(MonitorPassBudget.current.reset,self.token)
        self.config=history_fixtures.HistoryConfig();self.cfg=patch.object(monitor,'config',self.config)
        self.cfg.start();self.addCleanup(self.cfg.stop)
        self.search={'id':'qa','query':'logitech superlight 2','filters':{'category':'mice','listing_type':'buy_now','limit_price':45,'max_price':250},'exclude_words':[],'include_words':[],'exclude_sellers':[]}

    def test_deadline_is_monotonic_and_context_reaches_worker_thread(self):
        self.clock[0]=39.9;self.assertFalse(self.budget.should_yield())
        self.assertTrue(self.budget.should_yield(reserve=1))
        self.clock[0]=40
        self.assertTrue(asyncio.run(asyncio.to_thread(MonitorPassBudget.exhausted)))

    def test_unfinished_descriptions_never_confirm_history_or_enter_notifications(self):
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        calls=[]
        def fetch(i):
            calls.append(i);self.clock[0]=11;return details[i]
        with patch.object(monitor,'_fetch_item_details',side_effect=fetch),patch.object(monitor,'seen_ids',set()),patch.object(monitor,'seen_state',{}):
            verified=asyncio.run(monitor._verified_history(rows,self.search))
        self.assertEqual(1,len(calls));self.assertEqual(['seen'],[r['item_id'] for r in verified])
        self.assertIsNone(price_history.get_stats_7d('qa',monitor._history_filter_signature(self.search)))
        with closing(sqlite3.connect(price_history.DB_PATH)) as db:
            self.assertEqual(0,db.execute('select validation_complete from price_snapshots').fetchone()[0])
        self.assertTrue(any('проверка не завершена по времени' in e for e in monitor._runtime_pending))
        self.assertTrue(all(r['_details_status']=='verified' for r in verified))
        self.assertNotIn('expensive',[r['item_id'] for r in verified])

    def test_fresh_ready_lot_uses_soft_window_that_defers_other_reads(self):
        # 377573264218 was ready at the end of a pass and waited ~7 min for the next one.
        self.config.get_item_hashes=lambda:set()
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        rows=[r for r in rows if r['item_id'] in ('expensive','seen')]
        # Normal pass reserve is 45s: 35s left now reads the ready lot; 25s left keeps the checkpoint reserve.
        self.budget.validation_reserve=45
        for now,expected in ((5,['seen']),(15,[])):
            self.clock[0]=now;calls=[];sent=AsyncMock()
            with self.subTest(now=now),patch.object(monitor,'_fetch_item_details',side_effect=lambda i:(calls.append(i),details[i])[1]),patch.object(monitor,'browse_access',self.access),patch.object(monitor,'seen_ids',set()),patch.object(monitor,'seen_state',{}):
                asyncio.run(monitor._verified_history(copy.deepcopy(rows),self.search,on_verified=sent))
                self.assertEqual(expected,calls)
                self.assertEqual(expected,[c.args[0]['item_id'] for c in sent.await_args_list])

    def test_expired_transport_is_deferred_even_when_forced(self):
        self.clock[0]=40
        with patch.object(monitor,'_do_fetch_one') as request:
            self.assertEqual(([],'pass_deferred'),monitor.fetch_ebay_ex(self.search,force=True))
        request.assert_not_called()

    def test_remaining_lot_is_checked_after_restart_with_a_fresh_price(self):
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        def first_fetch(item_id):
            self.clock[0]=11
            return details[item_id]
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_fetch_item_details',side_effect=first_fetch):
            first=asyncio.run(monitor._verified_history(copy.deepcopy(rows),self.search))
        self.assertEqual(['seen'],[row['item_id'] for row in first])
        self.clock[0]=0
        details['expensive']['price']['value']='180'
        calls=[]
        def resumed_fetch(item_id):
            calls.append(item_id);self.clock[0]=11
            return details[item_id]
        with patch.object(monitor,'browse_access',BrowseAccess()),patch.object(monitor,'_fetch_item_details',side_effect=resumed_fetch):
            resumed=asyncio.run(monitor._verified_history(copy.deepcopy(rows),self.search))
        self.assertEqual(['expensive'],calls)
        self.assertEqual(185,resumed[0]['total_price'])
        self.assertIsNone(price_history.get_stats_7d('qa',monitor._history_filter_signature(self.search)))

    def test_partial_normal_pass_keeps_time_to_notify_its_verified_lot(self):
        budget=MonitorPassBudget(90,clock=lambda:self.clock[0])
        token=MonitorPassBudget.current.set(budget)
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        self.config.raw={'mobile_managed':True};self.config.get_searches=lambda:[self.search];self.config.save=Mock()
        self.config.get_item_hashes=lambda:set()
        def fetch_details(item_id):self.clock[0]=45;return details[item_id]
        try:
            with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_is_statistics_mode',return_value=False),patch.object(monitor,'initialize_api_budget_and_queue'),patch.object(monitor,'fetch_ebay_ex',return_value=(copy.deepcopy(rows),None)),patch.object(monitor,'_fetch_item_details',side_effect=fetch_details),patch.object(monitor,'_process_notify_candidate',new=AsyncMock(return_value=True)) as send,patch.object(monitor,'seen_ids',set()),patch.object(monitor,'seen_state',{}),patch.object(monitor,'save_seen_ids'),patch('mobile.feed_writer.flush_pending'),patch.object(monitor.asyncio,'sleep',new=AsyncMock()):
                asyncio.run(monitor._process_searches_in_pass(Mock(),once=True))
            self.assertEqual(1,send.await_count)
            self.assertEqual('seen',send.await_args.args[1]['item_id'])
            self.assertEqual('verified',send.await_args.args[1]['_details_status'])
            self.assertIsNone(price_history.get_stats_7d('qa',monitor._history_filter_signature(self.search)))
        finally:
            MonitorPassBudget.current.reset(token)

    def test_expired_api_attempt_does_not_request_token_or_consume_quota(self):
        self.clock[0]=40
        with patch.object(monitor,'_get_ebay_api_token') as token:
            self.assertEqual(([],'pass_deferred'),monitor.fetch_ebay_api_ex(self.search,force=True))
        token.assert_not_called()
        self.assertEqual(0,price_history.get_api_calls_count_24h())

    def test_previous_pass_deferred_cache_does_not_block_a_fresh_pass(self):
        key=monitor._query_cache_key(self.search)
        with patch.dict(monitor._ebay_query_cache,{key:(monitor.time.time(),[],'pass_deferred')},clear=True),patch.object(monitor,'EBAY_SOURCE','html'),patch.object(monitor,'_ebay_block_until',0),patch.object(monitor,'_ebay_active_host',None),patch.object(monitor,'_host_chain_for_search',return_value=['ebay.de']),patch.object(monitor,'_do_fetch_one',return_value=([{'item_id':'qa'}],None)) as fetch:
            rows,error=monitor.fetch_ebay_ex(self.search)
            self.assertIsNone(error)
            self.assertEqual(['qa'],[row['item_id'] for row in rows])
        self.assertTrue(fetch.called)

    def test_host_retries_stop_before_another_request_and_keep_incomplete_error(self):
        def request(*a,**kw):self.clock[0]+=20;return [],'network'
        with patch.object(monitor,'EBAY_SOURCE','html'),patch.object(monitor,'_ebay_block_until',0),patch.object(monitor,'_ebay_active_host',None),patch.object(monitor,'_host_chain_for_search',return_value=['ebay.de','ebay.com','ebay.co.uk']),patch.object(monitor,'reset_ebay_session'),patch.object(monitor,'_do_fetch_one',side_effect=request) as http,patch.object(monitor,'_do_fetch_playwright') as browser:
            self.assertEqual(([],'pass_deferred'),monitor.fetch_ebay_ex(self.search,force=True))
        self.assertEqual(2,http.call_count);browser.assert_not_called()

    def test_saved_cursor_survives_runner_and_removal_without_changing_quota(self):
        searches=[{'id':'a'},{'id':'b'},{'id':'disabled','enabled':False},{'id':'c'}]
        self.access.save({'remaining':0,'reset':123,'html_attempts':{'a|EBAY_DE':12}})
        self.access.start_normal_search('a','b','EBAY_DE')
        later=BrowseAccess()
        self.assertEqual(['b','c','a'],[s['id'] for s in later.normal_queue(searches,'EBAY_DE')])
        self.assertEqual(['a','c'],[s['id'] for s in later.normal_queue([searches[0],searches[-1]],'EBAY_DE')])
        self.assertEqual(0,later.state()['remaining']);self.assertEqual({'a|EBAY_DE':12},later.state()['html_attempts'])

    def test_real_normal_loop_continues_next_search_after_cooperative_yield(self):
        searches=[dict(copy.deepcopy(self.search),id=s,notify=False) for s in ['a','b','c']]
        self.config.raw={'mobile_managed':True};self.config.get_searches=lambda:searches;self.config.save=Mock()
        fetched=[]
        def fetch(s,*a,**kw):fetched.append(s['id']);self.clock[0]=11;return [],None
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_is_statistics_mode',return_value=False),patch.object(monitor,'initialize_api_budget_and_queue'),patch.object(monitor,'fetch_ebay_ex',side_effect=fetch),patch.object(monitor,'save_seen_ids'),patch('mobile.feed_writer.flush_pending'):
            asyncio.run(monitor._process_searches_in_pass(None,once=True))
            self.assertEqual(['a'],fetched)
            self.clock[0]=0
            asyncio.run(monitor._process_searches_in_pass(None,once=True))
        self.assertEqual(['a','b'],fetched)
        self.assertEqual('c',BrowseAccess().state()['normal_next_search']['EBAY_DE'])
        self.assertEqual(2,self.config.save.call_count)

    def test_context_is_restored_after_failure_and_statistics_ignores_normal_budget(self):
        async def fail(*a,**kw):
            self.assertIsNotNone(MonitorPassBudget.current.get());raise RuntimeError('qa')
        with patch.dict(os.environ,{'EMONITOR_PASS_SECONDS':'60'}),patch.object(monitor,'_is_statistics_mode',return_value=False),patch.object(monitor,'_process_searches_in_pass',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'qa'):asyncio.run(monitor.process_searches(None,once=True))
        self.assertIs(self.budget,MonitorPassBudget.current.get())
        async def stats(*a,**kw):self.assertIsNone(MonitorPassBudget.current.get())
        with patch.dict(os.environ,{'EMONITOR_PASS_SECONDS':'invalid'}),patch.object(monitor,'_is_statistics_mode',return_value=True),patch.object(monitor,'_process_searches_in_pass',side_effect=stats):
            asyncio.run(monitor.process_searches(None,once=True))
        self.assertIs(self.budget,MonitorPassBudget.current.get())

    def tearDown(self):monitor._runtime_errors.clear()


if __name__=='__main__':unittest.main()
