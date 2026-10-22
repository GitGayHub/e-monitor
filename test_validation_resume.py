"""Regression for real PS5 discovery18:04 -> description18:23 on18Oct2026."""
import asyncio, copy, unittest
from unittest.mock import patch, Mock, AsyncMock
import monitor
from ebay_access import MonitorPassBudget, BrowseAccess
import test_monitor_pass_budget as pass_fixtures
import test_verified_history as history_fixtures

class ValidationResumeTests(unittest.TestCase):
    setUp = pass_fixtures.MonitorPassBudgetTests.setUp

    def fixture(self):
        searches=[dict(copy.deepcopy(self.search),id=k) for k in ('a','b')]
        self.config.raw={'mobile_managed':True};self.config.save=Mock()
        self.config.get_searches=lambda:searches;self.config.get_item_hashes=lambda:set()
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        return searches,rows[0],details['seen']

    def run_loop(self,fetch,details,send):
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_is_statistics_mode',return_value=False),patch.object(monitor,'initialize_api_budget_and_queue'),patch.object(monitor,'fetch_ebay_ex',side_effect=fetch),patch.object(monitor,'_fetch_item_details',side_effect=details),patch.object(monitor,'_process_notify_candidate',send),patch.object(monitor,'seen_ids',set()),patch.object(monitor,'seen_state',{}),patch.object(monitor,'save_seen_ids'),patch('mobile.feed_writer.flush_pending'),patch.object(monitor.asyncio,'sleep',new=AsyncMock()):
            asyncio.run(monitor._process_searches_in_pass(None,once=True))

    def test_deadline_after_discovery_resumes_before_other_products_with_fresh_price(self):
        searches,row,body=self.fixture();original=copy.deepcopy(searches);fetched=[]
        parent=MonitorPassBudget(120,clock=lambda:self.clock[0]);token=MonitorPassBudget.current.set(parent)
        def fetch(s,**kw):
            self.assertFalse(kw.get('force',False));fetched.append(s['id'])
            return ([copy.deepcopy(row)] if s['id']=='a' else []),None
        send=AsyncMock(return_value=True)
        try:
            self.clock[0]=85  # 35s left: discovery allowed, description reserve reached.
            # Fresh ready lots normally use this window; resume still covers overflow.
            with patch.object(monitor,'PRIORITY_VALIDATION_MIN_SECONDS',45):
                self.run_loop(fetch,Mock(side_effect=AssertionError('must not read after description deadline')),send)
            self.assertEqual(['a'],fetched);send.assert_not_awaited()
            self.assertIn('a|'+monitor.EBAY_MARKETPLACE_ID,self.access.state()['normal_validation_resume'])
            self.access=BrowseAccess()  # The priority survives a runner restart.
            self.assertEqual(['a','b'],[s['id'] for s in self.access.normal_queue(searches,monitor.EBAY_MARKETPLACE_ID)])
            self.clock[0]=0
            changed=copy.deepcopy(body);changed['price']['value']='80'
            self.run_loop(fetch,lambda i:copy.deepcopy(changed),send)
            self.assertEqual(['a','a','b'],fetched)
            send.assert_not_awaited()  # A stale45EUR offer cannot send after becoming85EUR.
            self.assertFalse(self.access.state().get('normal_validation_resume'))
            self.assertEqual(original,searches)
        finally:MonitorPassBudget.current.reset(token)

    def test_pacing_deferral_retains_priority_but_allows_other_searches(self):
        searches,row,body=self.fixture();self.access.defer_normal_validation('a',monitor.EBAY_MARKETPLACE_ID)
        paced=[True];attempts=[];requests=[]
        def fetch(s,**kw):
            self.assertFalse(kw.get('force',False));attempts.append(s['id'])
            if s['id']=='a' and paced[0]:return [],'api_deferred'
            requests.append(s['id']);return ([copy.deepcopy(row)] if s['id']=='a' else []),None
        token=MonitorPassBudget.current.set(MonitorPassBudget(120,clock=lambda:self.clock[0]))
        try:
            send=AsyncMock(return_value=True)
            self.run_loop(fetch,lambda i:copy.deepcopy(body),send)
            self.assertEqual(['b'],requests);send.assert_not_awaited()
            self.assertIn('a|'+monitor.EBAY_MARKETPLACE_ID,self.access.state()['normal_validation_resume'])
            paced[0]=False;self.access=BrowseAccess()
            self.run_loop(fetch,lambda i:copy.deepcopy(body),send)
            self.assertEqual(['a','b','a','b'],attempts)
            self.assertEqual(1,send.await_count)
            self.assertFalse(self.access.state().get('normal_validation_resume'))
        finally:MonitorPassBudget.current.reset(token)

    def test_fair_two_candidate_limit_does_not_priority_pin_one_product(self):
        _,row,body=self.fixture();rows=[dict(copy.deepcopy(row),item_id=str(i)) for i in range(4)]
        token=MonitorPassBudget.current.set(MonitorPassBudget(65,clock=lambda:self.clock[0]))
        def details(i):self.clock[0]+=10;return copy.deepcopy(body)
        deferred=Mock()
        try:
            with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_fetch_item_details',side_effect=details),patch.object(monitor,'seen_ids',set()),patch.object(monitor,'seen_state',{}):
                verified=asyncio.run(monitor._verified_history(rows,self.search,on_verified=AsyncMock(),max_candidates=2,on_budget_deferred=deferred))
            self.assertEqual(2,len(verified));deferred.assert_not_called()
            self.assertFalse(self.access.state().get('normal_validation_resume'))
        finally:MonitorPassBudget.current.reset(token)

    def test_fresh_ready_lot_found_near_deadline_is_sent_in_the_same_pass(self):
        # 377573264218: ready at19:11 near the pass end, sent only at19:18.
        searches,row,body=self.fixture();fetched=[]
        token=MonitorPassBudget.current.set(MonitorPassBudget(120,clock=lambda:self.clock[0]))
        def fetch(s,**kw):
            fetched.append(s['id']);return ([copy.deepcopy(row)] if s['id']=='a' else []),None
        send=AsyncMock(return_value=True)
        try:
            self.clock[0]=85  # 35s left: inside the old45s description reserve.
            self.run_loop(fetch,lambda i:copy.deepcopy(body),send)
            self.assertEqual('a',fetched[0]);send.assert_awaited_once()
            self.assertFalse(self.access.state().get('normal_validation_resume'))
        finally:MonitorPassBudget.current.reset(token)

    def test_disabled_notifications_and_over_limit_stock_do_not_pin_priority(self):
        for notify,price in ((False,40),(True,90)):
            with self.subTest(notify=notify,price=price):
                searches,row,body=self.fixture();searches[0]['notify']=notify;row['price']=price;row['total_price']=price+5
                token=MonitorPassBudget.current.set(MonitorPassBudget(120,clock=lambda:self.clock[0]))
                self.clock[0]+=85
                try:
                    self.run_loop(lambda s,**kw:([copy.deepcopy(row)] if s['id']=='a' else [],None),Mock(side_effect=AssertionError('expired')),AsyncMock())
                    self.assertFalse(self.access.state().get('normal_validation_resume'))
                finally:
                    MonitorPassBudget.current.reset(token);self.clock[0]=0
