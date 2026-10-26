"""Live recovery uses the reserve before slow HTML starves the catalogue."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import monitor
import price_history
from ebay_access import BrowseAccess, MonitorPassBudget


class LiveCoverageRecoveryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        p=patch.object(price_history,'DB_PATH',str(Path(folder.name)/'history.db'))
        p.start();self.addCleanup(p.stop)
        self.access=BrowseAccess();self.clock=[0.0]
        self.search=monitor._normal_discovery_search(dict(id='qa-recovery',
            query='(iphone 17 pro max, apple iphone 17 pro max, iphone17 pro max)',
            filters=dict(listing_type='buy_now',category='phones',limit_price=910)))

    def test_two_live_turns_recover_all_three_aliases_after_html_timeouts(self):
        recovered=set();budgets=[]
        def html(child,**kwargs):
            budget=MonitorPassBudget.current.get();budgets.append(budget.seconds)
            self.clock[0]+=budget.seconds
            return [],'pass_deferred'
        def api(child,**kwargs):
            if MonitorPassBudget.exhausted():return [],'pass_deferred'
            self.clock[0]+=1
            recovered.add(child['_query_override'])
            return [dict(item_id=child['_query_override'])],None
        for _ in range(2):
            token=MonitorPassBudget.current.set(MonitorPassBudget(20,clock=lambda:self.clock[0]))
            try:
                with patch.object(monitor,'browse_access',BrowseAccess()),patch.object(monitor,'fetch_ebay_ex',side_effect=html),patch.object(monitor,'fetch_ebay_api_ex',side_effect=api),patch.object(monitor,'_ebay_api_configured',return_value=True),patch.object(monitor,'_ebay_api_paused',return_value=False),patch.object(monitor,'_ebay_api_circuit_open',False):
                    monitor._fetch_html_primary(self.search,force=True,allow_api=True)
            finally:MonitorPassBudget.current.reset(token)
        self.assertEqual(set(monitor._search_query_variants(self.search)),recovered)
        self.assertLessEqual(max(budgets),6)
        self.assertEqual(0,price_history.get_api_calls_count_24h())

    def test_old_search_cannot_wait_behind_recent_high_priority_attempt(self):
        rows=[{'id':'first','priority':1},{'id':'pixel','priority':18}]
        self.access.save({'html_attempts':{'first|DE':1700,'pixel|DE':100}})
        self.assertEqual('pixel',self.access.normal_queue(rows,'DE',now=2000)[0]['id'])
        self.assertEqual([1,18],[r['priority'] for r in rows])

    def test_fast_html_stays_primary_and_exhausted_quota_retains_html_time(self):
        for paused, expected in ((False,6),(True,20)):
            token=MonitorPassBudget.current.set(MonitorPassBudget(20,clock=lambda:self.clock[0]))
            budgets=[]
            def html(child,**kwargs):
                budgets.append(MonitorPassBudget.current.get().seconds)
                self.clock[0]+=.25
                return [dict(item_id=child['_query_override'])],None
            try:
                with patch.object(monitor,'browse_access',self.access),patch.object(monitor,'fetch_ebay_ex',side_effect=html),patch.object(monitor,'fetch_ebay_api_ex') as api,patch.object(monitor,'record_search_run'),patch.object(monitor,'_ebay_api_configured',return_value=True),patch.object(monitor,'_ebay_api_paused',return_value=paused),patch.object(monitor,'_ebay_api_circuit_open',False):
                    rows,error=monitor._fetch_html_primary(self.search,force=True,allow_api=True)
                self.assertIsNone(error);self.assertEqual(3,len(rows));api.assert_not_called()
                self.assertEqual(expected,budgets[0])
                self.assertTrue(all(0 < value <= expected for value in budgets))
            finally:MonitorPassBudget.current.reset(token)

    def test_pacing_and_worker_shutdown_do_not_erase_last_search_outcome(self):
        self.access.note_normal_outcome('phone','DE',None,4,1,now=1000)
        before=self.access.state()['normal_search_outcomes']
        for error in ('api_deferred','pass_deferred'):
            self.access.note_normal_outcome('phone','DE',error,0,0,now=1100)
        self.assertEqual(before,self.access.state()['normal_search_outcomes'])

    def test_success_freshness_retains_last_good_data_after_failed_retry(self):
        self.access.note_normal_outcome('phone','DE',None,4,2.5,now=1000)
        self.access.note_normal_outcome('phone','DE','blocked',0,6,now=1100)
        # A different process sees the same evidence, without prices/text/secrets.
        report=BrowseAccess().search_coverage([{'id':'phone'}],'DE',now=1200)
        self.assertEqual(1,report['successfulWithin15Minutes'])
        row=report['searches'][0]
        self.assertEqual('blocked',row['lastError'])
        self.assertEqual(200,row['lastSuccessAgeSeconds'])
        self.assertEqual(100,row['lastAttemptAgeSeconds'])
        self.assertNotIn('price',str(row));self.assertNotIn('seller',str(row))

    def test_partial_results_and_clean_zero_have_different_success_evidence(self):
        self.access.note_normal_outcome('partial','DE','search_deferred',7,20,now=1000)
        self.access.note_normal_outcome('empty','DE',None,0,1,now=1000)
        report=self.access.search_coverage([{'id':'partial'},{'id':'empty'}],'DE',now=1010)
        self.assertEqual(1,report['successfulSearches'])
        self.assertEqual(2,report['withResultsSearches']+report['cleanEmptySearches'])
        by_id={x['searchId']:x for x in report['searches']}
        self.assertIsNone(by_id['partial']['lastSuccessAgeSeconds'])
        self.assertEqual(7,by_id['partial']['lastReceived'])
        self.assertEqual(0,by_id['empty']['lastReceived'])


if __name__=='__main__':unittest.main()
