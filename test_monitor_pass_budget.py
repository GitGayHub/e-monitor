"""Runner deadlines preserve verification and rotate the persisted queue."""
import asyncio,copy,os,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch,Mock,AsyncMock
import monitor,price_history
from ebay_access import MonitorPassBudget,BrowseAccess
import test_verified_history as history_fixtures


class MonitorPassBudgetTests(unittest.TestCase):
    def setUp(self):
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
        self.assertTrue(any('проверка не завершена по времени' in e for e in monitor._runtime_errors))
        self.assertTrue(all(r['_details_status']=='verified' for r in verified))
        self.assertNotIn('expensive',[r['item_id'] for r in verified])

    def test_expired_transport_is_deferred_even_when_forced(self):
        self.clock[0]=40
        with patch.object(monitor,'_do_fetch_one') as request:
            self.assertEqual(([],'pass_deferred'),monitor.fetch_ebay_ex(self.search,force=True))
        request.assert_not_called()

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
