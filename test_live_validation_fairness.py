"""Issue #2: a lot that becomes notify-eligible must not starve in the live queue.

Real case 327409314879: already discovered, it moved exactly two places per
pass (30->28->26->24) and jumped to the front only when an API card with a
clock arrived. Order changes only; notification rules stay as they were.
"""
import asyncio,copy,json,tempfile,time,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch,AsyncMock
import monitor,price_history
from ebay_access import MonitorPassBudget,BrowseAccess
import test_verified_history as history_fixtures


class LiveValidationFairnessTests(unittest.TestCase):
    def setUp(self):
        pending=patch.object(monitor,'_runtime_pending',[]);pending.start();self.addCleanup(pending.stop)
        errors=patch.object(monitor,'_runtime_errors',[]);errors.start();self.addCleanup(errors.stop)
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        db=patch.object(price_history,'DB_PATH',str(Path(self.folder.name)/'history.db'));db.start();self.addCleanup(db.stop)
        price_history.init_db()
        self.config=history_fixtures.HistoryConfig();self.config.get_item_hashes=lambda:set()
        cfg=patch.object(monitor,'config',self.config);cfg.start();self.addCleanup(cfg.stop)
        token=MonitorPassBudget.current.set(MonitorPassBudget(600,clock=lambda:0.0))
        self.addCleanup(MonitorPassBudget.current.reset,token)
        self.now=[time.time()]
        clock=patch.object(monitor.time,'time',side_effect=lambda:self.now[0]);clock.start();self.addCleanup(clock.stop)
        self.search={'id':'qa','query':'logitech superlight 2','filters':{'category':'mice','listing_type':'auction','limit_price':45,'max_price':250},
                     'exclude_words':[],'include_words':[],'exclude_sellers':[]}
        rows,details=history_fixtures.VerifiedHistoryTests.data(self)
        self.base=dict(rows[0],auction=True,buy_now=False,best_offer=False,source='html',seller_name='private-seller')
        self.detail=details[rows[0]['item_id']]

    def lot(self,item_id,clock):
        return dict(copy.deepcopy(self.base),item_id=item_id,time_left=clock)

    def details_for(self,hours):
        end=(datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat().replace('+00:00','Z')
        return dict(copy.deepcopy(self.detail),buyingOptions=['AUCTION'],itemEndDate=end)

    def run_pass(self,rows,fetch,access=None,deliver=None):
        self.now[0]+=900  # one GitHub runner pass, every 15 minutes
        with patch.object(monitor,'browse_access',access or self.access),patch.object(monitor,'_fetch_item_details',side_effect=fetch), \
             patch.object(monitor,'seen_state',{}),patch.object(monitor,'seen_ids',set()):
            return asyncio.run(monitor._verified_history(copy.deepcopy(rows),self.search,on_verified=deliver or AsyncMock(),max_candidates=2))

    def passes_until(self,target,rows,fetch,limit=30,access=None):
        calls=[]
        def tracked(item_id):
            calls.append(item_id);return fetch(item_id)
        for n in range(1,limit+1):
            self.run_pass(rows,tracked,access=access)
            if target in calls:return n
        return None

    def test_lot_entering_24h_window_precedes_rejected_ready_lots_and_survives_restart(self):
        self.access=BrowseAccess()
        blockers=[self.lot(f'b{n}','23h 59min') for n in range(8)]
        waiting=self.lot('target','2d 1h')
        # Blocked/incomplete descriptions keep these unseen ready lots in the queue.
        fetch=lambda i:self.details_for(23) if i=='target' else None
        for _ in range(4):self.run_pass(blockers+[waiting],fetch)
        # The lot crosses into its 24 hour window; a new runner process starts.
        ready=self.lot('target','23h 30min')
        self.assertEqual(1,self.passes_until('target',blockers+[ready],fetch,access=BrowseAccess()))

    def test_html_card_without_clock_is_checked_before_known_waiting_auctions(self):
        self.access=BrowseAccess()
        waiting=[self.lot(f'w{n}','3d 4h') for n in range(20)]
        unknown=self.lot('target','')
        fetch=lambda i:self.details_for(22)
        delivered=[]
        async def deliver(row):delivered.append(row['item_id'])
        self.now[0]+=900
        with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_fetch_item_details',side_effect=fetch), \
             patch.object(monitor,'seen_state',{}),patch.object(monitor,'seen_ids',set()),patch.object(monitor.logger,'info') as log:
            asyncio.run(monitor._verified_history(copy.deepcopy(waiting+[unknown]),self.search,on_verified=deliver,max_candidates=2))
        self.assertEqual('target',delivered[0])
        audit=json.loads(next(c for c in log.call_args_list if c.args[0].startswith('Live validation queue')).args[-1])
        self.assertEqual(('target','auction_time_unknown',1),(audit[0]['id'],audit[0]['gate'],audit[0]['tier']))
        fairness=next(c for c in log.call_args_list if c.args[0].startswith('Live validation fairness'))
        self.assertEqual(('qa',0,1,0,20),fairness.args[1:6])
        deferred=next(c for c in log.call_args_list if c.args[0].startswith('Live validation deferred'))
        self.assertEqual(('qa','fair_slice',0),deferred.args[1:])

    def test_page_clock_from_earlier_description_orders_waiting_and_due_lots(self):
        self.access=BrowseAccess()
        others=[self.lot(f'w{n}','3d 4h') for n in range(10)]
        early=self.lot('target','')
        # The lot was described while it still had 40 hours: it then waits.
        self.run_pass([early]+others,lambda i:self.details_for(40))
        with patch.object(monitor,'browse_access',self.access):
            facts=self.access.normal_candidate_facts('qa',self.context(),monitor.EBAY_MARKETPLACE_ID)
        self.assertIn('ends',facts['target'])
        tier,_=monitor._live_validation_tier(early,self.search,False,facts['target'],self.now[0])
        self.assertEqual(3,tier)
        self.assertEqual((False,'wait_24h'),monitor._notify_eligibility(early,self.search))
        # 17 hours later the saved page clock is inside 24h: priority again,
        # although it was described before and its card still has no clock.
        tier,_=monitor._live_validation_tier(early,self.search,False,facts['target'],self.now[0]+17*3600)
        self.assertEqual(1,tier)

    def test_repeated_incomplete_ready_lot_retries_after_fresh_ready_lots(self):
        self.access=BrowseAccess()
        broken=self.lot('broken','20h')
        fresh=[self.lot(f'f{n}','20h') for n in range(3)]
        calls=[]
        def fetch(i):calls.append(i);return None
        self.run_pass([broken],fetch)
        self.run_pass([broken]+fresh,fetch)
        self.run_pass([broken]+fresh,fetch)
        self.assertEqual(['broken','f0','f1','f2','broken'],calls)

    def test_regular_auction_still_waits_and_facts_hold_no_seller_or_title(self):
        self.access=BrowseAccess()
        rows=[self.lot('target','')]+[self.lot(str(n),'2d') for n in range(200)]
        delivered=[]
        async def deliver(row):delivered.append(row['item_id'])
        for _ in range(3):self.run_pass(rows,lambda i:self.details_for(30),deliver=deliver)
        # on_verified still receives verified rows; its own filter decides alerts.
        self.assertEqual([],monitor.filter_results([dict(rows[1])],self.search,self.config))
        state=json.dumps(self.access.state())
        self.assertNotIn('private-seller',state);self.assertNotIn(self.base['title'],state)
        facts=self.access.normal_candidate_facts('qa',self.context(),monitor.EBAY_MARKETPLACE_ID)
        self.assertLessEqual(len(facts),160)
        self.assertTrue(all(set(v)<={'ready_at','checked_at','ends','updated'} for v in facts.values()))

    def test_deadline_keeps_cursor_and_reports_deferred_priority(self):
        self.access=BrowseAccess()
        rows=[self.lot(f'r{n}','20h') for n in range(4)]
        runner=[0.0];budget=MonitorPassBudget(40,clock=lambda:runner[0]);runner[0]=20.0
        token=MonitorPassBudget.current.set(budget)
        try:
            with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'_fetch_item_details',return_value=None), \
                 patch.object(monitor,'seen_state',{}),patch.object(monitor,'seen_ids',set()),patch.object(monitor.logger,'info') as log:
                asyncio.run(monitor._verified_history(copy.deepcopy(rows),self.search,on_verified=AsyncMock(),max_candidates=2))
        finally:MonitorPassBudget.current.reset(token)
        deferred=next(c for c in log.call_args_list if c.args[0].startswith('Live validation deferred'))
        self.assertEqual(('qa','deadline',4),deferred.args[1:])
        self.assertTrue(any('проверка не завершена по времени' in e for e in monitor._runtime_pending))
        # Next runner resumes the same four lots, all still first priority.
        calls=[]
        self.run_pass(rows,lambda i:calls.append(i))
        self.assertEqual(['r0','r1'],calls)

    def test_known_ready_retry_gets_one_slot_before_new_unknown_clocks(self):
        # Live840048433110 was ready but tier2 behind8 unknown-clock auctions.
        self.access=BrowseAccess()
        self.search['filters']['listing_type']='all'
        ready=dict(self.lot('ready',''),auction=False,buy_now=True)
        self.run_pass([ready],lambda i:None)
        unknown=[self.lot(f'u{n}','') for n in range(8)]
        calls=[]
        deliver=AsyncMock()
        self.run_pass(unknown+[ready],lambda i:calls.append(i),deliver=deliver)
        deliver.assert_not_awaited()
        self.assertEqual('ready',calls[0])
        self.assertTrue(calls[1].startswith('u'))

    def test_ready_retries_rotate_without_taking_both_unknown_clock_slots(self):
        self.access=BrowseAccess()
        self.search['filters']['listing_type']='all'
        ready=[dict(self.lot(f'r{n}',''),auction=False,buy_now=True) for n in range(2)]
        self.run_pass(ready,lambda i:None)
        unknown=[self.lot(f'u{n}','') for n in range(6)]
        rounds=[]
        for _ in range(2):
            calls=[]
            self.run_pass(unknown+ready,lambda i:calls.append(i))
            self.assertEqual(1,sum(i.startswith('r') for i in calls))
            self.assertEqual(1,sum(i.startswith('u') for i in calls))
            rounds.append(calls[0])
        self.assertEqual({'r0','r1'},set(rounds))

    def context(self):
        return f"{monitor._read_logic_version_timestamp()}:{monitor._history_filter_signature(self.search)}:{monitor._search_limit_price(self.search)}"


if __name__=='__main__':
    unittest.main()
