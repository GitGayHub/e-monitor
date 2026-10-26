"""A slow alias must not permanently hide stock found under another spelling."""
import asyncio, copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock, Mock
import monitor, price_history
from ebay_access import BrowseAccess, MonitorPassBudget
from test_search_intent_rules import item
from test_verified_history import HistoryConfig


class LiveAliasQueueTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        p=patch.object(price_history,'DB_PATH',str(Path(folder.name)/'history.db'));p.start();self.addCleanup(p.stop)
        self.clock=[0.0];self.access=BrowseAccess()
        for name,value in (('_runtime_errors',[]),('_runtime_pending',[]),('_runtime_progress',{}),
                           ('_runtime_html_fallback',False),('_runtime_api_fallback',False),
                           ('_allowed_api_targets_this_run',set())):
            p=patch.object(monitor,name,value);p.start();self.addCleanup(p.stop)
        self.source=dict(id='qa-alias',query='(iphone 17 pro max, apple iphone 17 pro max, iphone17 pro max)',notify=True,
                         filters=dict(category='phones',listing_type='buy_now',limit_price=910,max_price=2500))
        self.search=monitor._normal_discovery_search(self.source)
        self.aliases=monitor._search_query_variants(self.search)
        self.assertEqual(3,len(self.aliases))
        self.calls=[]

    def fetch(self,provider,search=None,force=True):
        token=MonitorPassBudget.current.set(MonitorPassBudget(20,clock=lambda:self.clock[0]))
        try:
            # A new access object models the next runner/process loading its DB.
            with patch.object(monitor,'browse_access',BrowseAccess()),patch.object(monitor,'fetch_ebay_ex',side_effect=provider),patch.object(monitor,'_ebay_api_configured',return_value=False):
                return monitor._fetch_html_primary(search or self.search,force=force,allow_api=False)
        finally:MonitorPassBudget.current.reset(token)

    def provider(self,child,force=False):
        self.assertTrue(child['_variant_child']);self.assertTrue(child['_html_fallback'])
        self.calls.append((child['filters']['listing_type'],child['_query_override']))
        self.clock[0]+=20
        if child['_query_override']==self.aliases[0]:return [],'pass_deferred'
        return [dict(item_id=child['_query_override'],title='Apple iPhone 17 Pro Max 256GB',price=800)],None

    def test_three_new_runners_reach_all_aliases_after_first_timeout(self):
        outputs=[self.fetch(self.provider) for _ in range(3)]
        self.assertEqual(self.aliases,[query for _,query in self.calls])
        self.assertEqual([0,1,1],[len(rows) for rows,error in outputs])
        self.assertTrue(all(error=='pass_deferred' for rows,error in outputs))

    def test_short_tail_deadline_retries_alias_with_a_fresh_budget(self):
        # Real Pixel03:03: third task received only the remainder of20s.
        # Advancing it makes the same tail alias lose its turn every pass.
        completed=[]
        def provider(child,force=False):
            budget=MonitorPassBudget.current.get()
            query=child['_query_override']
            self.calls.append((query,budget.seconds))
            if budget.seconds<9:
                self.clock[0]+=budget.seconds
                return [],'pass_deferred'
            self.clock[0]+=9
            completed.append(query)
            return [dict(item_id=query,price=800)],None
        with patch.object(monitor,'record_search_run') as complete:
            for _ in range(3):
                _,error=self.fetch(provider)
                self.assertEqual('pass_deferred',error)
        complete.assert_not_called()
        self.assertEqual(set(self.aliases),set(completed))
        self.assertEqual(self.aliases[2],self.calls[3][0])

    def test_short_tail_retries_both_formats_across_process_restarts(self):
        search=copy.deepcopy(self.source);search['filters']['listing_type']='all'
        search=monitor._normal_discovery_search(search)
        completed=[]
        def provider(child,force=False):
            budget=MonitorPassBudget.current.get()
            if budget.seconds<9:
                self.clock[0]+=budget.seconds
                return [],'pass_deferred'
            self.clock[0]+=9
            completed.append((child['filters']['listing_type'],child['_query_override']))
            return [dict(item_id=str(completed[-1]),price=800)],None
        for _ in range(3):self.fetch(provider,search)
        self.assertEqual([(kind,q) for q in self.aliases for kind in ('buy_now','auction')],completed)

    def test_all_formats_resume_the_alias_and_format_not_only_purchase_pages(self):
        search=copy.deepcopy(self.source);search['filters']['listing_type']='all'
        search=monitor._normal_discovery_search(search)
        for _ in range(6):self.fetch(self.provider,search)
        self.assertEqual([(kind,query) for query in self.aliases for kind in ('buy_now','auction')],self.calls)

    def test_statistics_retains_whole_union_and_original_fixed_order(self):
        # Even a diagnostic built from a prepared live request remains exhaustive.
        search=monitor._statistics_search_variant(self.search,'all')
        def fast(child,force=False):
            self.calls.append((child['filters']['listing_type'],child['_query_override']))
            return [dict(item_id=str(len(self.calls)),price=800)],None
        rows,error=self.fetch(fast,search)
        self.assertIsNone(error);self.assertEqual(6,len(rows))
        self.assertEqual([(kind,query) for kind in ('buy_now','auction') for query in self.aliases],self.calls)
        self.assertNotIn('normal_aliases',self.access.state())

    def test_pacing_deferral_does_not_consume_an_alias_or_make_a_request(self):
        self.fetch(self.provider)
        before=self.access.state()
        with patch.object(monitor,'_allowed_api_targets_this_run',set()):
            self.assertEqual(([],'api_deferred'),self.fetch(self.provider,force=False))
        self.assertEqual(before,self.access.state());self.assertEqual(1,len(self.calls))

    def test_deadline_before_next_request_does_not_skip_its_alias(self):
        self.fetch(self.provider)
        before=self.access.state()
        token=MonitorPassBudget.current.set(MonitorPassBudget(0,clock=lambda:self.clock[0]))
        try:
            with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'fetch_ebay_ex') as provider:
                self.assertEqual(([],'pass_deferred'),monitor._fetch_html_primary(self.search,force=True,allow_api=False))
            provider.assert_not_called();self.assertEqual(before,self.access.state())
        finally:MonitorPassBudget.current.reset(token)

    def test_settings_or_market_change_resets_cursor_and_scopes_are_independent(self):
        self.fetch(self.provider)
        changed=copy.deepcopy(self.search);changed['filters']['limit_price']=900
        self.fetch(self.provider,changed)
        with patch.object(monitor,'EBAY_MARKETPLACE_ID','EBAY_FR'):self.fetch(self.provider)
        self.assertEqual([self.aliases[0]]*3,[query for _,query in self.calls])

    def test_killed_provider_advances_before_io_and_stale_quotes_are_not_saved(self):
        def killed(child,force=False):raise RuntimeError('worker terminated')
        with self.assertRaisesRegex(RuntimeError,'terminated'):self.fetch(killed)
        self.fetch(self.provider)
        self.assertEqual(self.aliases[1],self.calls[0][1])
        saved=json.dumps(self.access.state())
        self.assertNotIn('price',saved);self.assertNotIn('description',saved)
        self.assertNotIn(self.aliases[0],saved)

    def test_partial_alias_union_cannot_be_recorded_as_a_complete_search(self):
        with patch.object(monitor,'record_search_run') as complete:
            self.fetch(self.provider)
        complete.assert_not_called()

    def test_api_pause_does_not_prevent_html_alias_rotation_or_spend_api_quota(self):
        self.access.save({'remaining':0,'reset':10**12})
        original=monitor.fetch_ebay_ex
        def delegated(search,force=False):
            return self.provider(search,force) if search.get('_variant_child') else original(search,force)
        for _ in range(2):
            token=MonitorPassBudget.current.set(MonitorPassBudget(20,clock=lambda:self.clock[0]))
            try:
                with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'fetch_ebay_ex',side_effect=delegated),patch.object(monitor,'_ebay_api_configured',return_value=True),patch.object(monitor,'EBAY_SOURCE','auto'),patch.object(monitor,'fetch_ebay_api_ex') as api,patch.object(monitor,'_get_ebay_api_token') as oauth:
                    original(self.search,force=True)
                api.assert_not_called();oauth.assert_not_called()
            finally:MonitorPassBudget.current.reset(token)
        api.assert_not_called();oauth.assert_not_called()
        self.assertEqual(self.aliases[:2],[query for _,query in self.calls])
        self.assertEqual(0,price_history.get_api_calls_count_24h())
        self.assertEqual(0,self.access.state()['remaining'])

    def test_clean_empty_is_only_success_after_every_current_alias_was_read(self):
        def empty(child,force=False):
            self.calls.append(child['_query_override']);return [],None
        with patch.object(monitor,'record_search_run') as complete:
            self.assertEqual(([],None),self.fetch(empty))
        self.assertEqual(self.aliases,self.calls);complete.assert_called_once()

    def test_api_zero_after_html_block_does_not_confirm_empty_or_repeat_first_alias(self):
        def blocked(child,force=False):
            self.calls.append(child['_query_override']);return [],'blocked'
        for _ in range(3):
            token=MonitorPassBudget.current.set(MonitorPassBudget(20,clock=lambda:self.clock[0]))
            try:
                with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'fetch_ebay_ex',side_effect=blocked),patch.object(monitor,'_ebay_api_configured',return_value=True),patch.object(monitor,'_ebay_api_circuit_open',False),patch.object(self.access,'is_paused',return_value=False),patch.object(monitor,'fetch_ebay_api_ex',return_value=([],None)) as api:
                    self.assertEqual(([],'blocked'),monitor._fetch_html_primary(self.search,force=True,allow_api=True))
                    api.assert_called_once()
            finally:MonitorPassBudget.current.reset(token)
        self.assertEqual(self.aliases,self.calls)

    def test_actual_normal_loop_validates_new_alias_stock_before_notify_callback(self):
        config=HistoryConfig();config.raw={'mobile_managed':True};config.get_searches=lambda:[self.source];config.save=Mock()
        config.get_item_hashes=lambda:set()
        title='Apple iPhone 17 Pro Max 256GB'
        row=item(title,item_id='new-under-second-alias',price=800,shipping_cost=6.19,total_price=806.19,seller_name='seller')
        details=dict(title=title,description='Verkaufe mein Apple iPhone 17 Pro Max 256GB. Funktioniert einwandfrei.',price={'value':'800'},buyingOptions=['FIXED_PRICE'])
        original=monitor.fetch_ebay_ex
        def discovery(search,force=False):
            if not search.get('_variant_child'):return original(search,force=force)
            query=search['_query_override'];self.calls.append((search['filters']['listing_type'],query))
            if query==self.aliases[0]:self.clock[0]+=20;return [],'pass_deferred'
            self.clock[0]+=1;return [copy.deepcopy(row)],None
        seen=[]
        async def sent(bot,candidate,*args):
            self.assertEqual('verified',candidate['_details_status']);seen.append(candidate['item_id']);return True
        for _ in range(2):
            token=MonitorPassBudget.current.set(MonitorPassBudget(390,clock=lambda:self.clock[0]))
            try:
                with patch.object(monitor,'config',config),patch.object(monitor,'browse_access',BrowseAccess()),patch.object(monitor,'_is_statistics_mode',return_value=False),patch.object(monitor,'_ebay_api_configured',return_value=False),patch.object(monitor,'EBAY_SOURCE','auto'),patch.object(monitor,'_ebay_query_cache',{}),patch.object(monitor,'initialize_api_budget_and_queue',side_effect=lambda rows:setattr(monitor,'_allowed_api_targets_this_run',{('qa-alias',monitor.EBAY_MARKETPLACE_ID)})),patch.object(monitor,'fetch_ebay_ex',side_effect=discovery),patch.object(monitor,'_fetch_item_details',return_value=copy.deepcopy(details)),patch.object(monitor,'_process_notify_candidate',side_effect=sent),patch.object(monitor,'seen_ids',set()),patch.object(monitor,'seen_state',{}),patch.object(monitor,'save_seen_ids'),patch('mobile.feed_writer.flush_pending'),patch.object(monitor.asyncio,'sleep',new=AsyncMock()):
                    asyncio.run(monitor._process_searches_in_pass(None,once=True))
            finally:MonitorPassBudget.current.reset(token)
        self.assertEqual(['new-under-second-alias'],seen)
        self.assertIsNone(price_history.get_stats_7d('qa-alias',monitor._history_filter_signature(self.source,config)))
