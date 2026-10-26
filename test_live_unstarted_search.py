"""A depleted tail must not refresh Pixel's real search-attempt evidence."""
import asyncio,copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import monitor,price_history
from ebay_access import BrowseAccess,MonitorPassBudget


class UnstartedLiveSearchTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        p=patch.object(price_history,'DB_PATH',str(Path(folder.name)/'history.db'));p.start();self.addCleanup(p.stop)
        self.access=BrowseAccess();self.clock=[0.0]
        self.search=monitor._normal_discovery_search(dict(id='pixel_9_pro_xl',
            query='(pixel 9 pro xl, google pixel 9 pro xl)',
            filters=dict(listing_type='buy_now',category='phones',limit_price=310)))
        for name,value in [('browse_access',self.access),('_ebay_api_configured',lambda:True),
                           ('_ebay_api_paused',lambda:False),('_ebay_api_circuit_open',False),
                           ('_allowed_api_targets_this_run',{('pixel_9_pro_xl',monitor.EBAY_MARKETPLACE_ID)}),
                           ('_ebay_query_cache',{}),('EBAY_SOURCE','auto')]:
            p=patch.object(monitor,name,value);p.start();self.addCleanup(p.stop)

    def test_short_parent_tail_does_not_reset_outcome_attempt_or_due_permission(self):
        self.access.record_html_attempt('pixel_9_pro_xl',monitor.EBAY_MARKETPLACE_ID)
        self.access.note_normal_outcome('pixel_9_pro_xl',monitor.EBAY_MARKETPLACE_ID,None,4,1)
        before=copy.deepcopy(self.access.state())
        token=MonitorPassBudget.current.set(MonitorPassBudget(35,clock=lambda:self.clock[0]))
        try:
            with patch.object(monitor,'fetch_ebay_api_ex') as api,patch.object(monitor,'_do_fetch_one') as html:
                result=asyncio.run(monitor._fetch_normal_slice(self.search))
            self.assertEqual(([],'pass_deferred'),result)
            html.assert_not_called();api.assert_not_called()
            self.assertEqual(before,self.access.state())
            self.assertIn(('pixel_9_pro_xl',monitor.EBAY_MARKETPLACE_ID),monitor._allowed_api_targets_this_run)
        finally:MonitorPassBudget.current.reset(token)

    def test_direct_html_tail_without_io_is_not_a_recorded_attempt(self):
        token=MonitorPassBudget.current.set(MonitorPassBudget(5,clock=lambda:self.clock[0]))
        try:
            with patch.object(monitor,'fetch_ebay_ex') as html,patch.object(monitor,'fetch_ebay_api_ex') as api:
                self.assertEqual(([],'pass_deferred'),monitor._fetch_html_primary(self.search,allow_api=True))
            html.assert_not_called();api.assert_not_called()
            self.assertNotIn('pixel_9_pro_xl|'+monitor.EBAY_MARKETPLACE_ID,self.access.state().get('html_attempts',{}))
        finally:MonitorPassBudget.current.reset(token)

    def test_failed_real_html_attempt_still_counts_and_remains_due_for_other_alias(self):
        token=MonitorPassBudget.current.set(MonitorPassBudget(20,clock=lambda:self.clock[0]))
        try:
            with patch.object(monitor,'fetch_ebay_ex',return_value=([],'blocked')) as html,patch.object(monitor,'fetch_ebay_api_ex',return_value=([],'network')):
                rows,error=monitor._fetch_html_primary(self.search,allow_api=True)
            html.assert_called_once();self.assertEqual(([],'blocked'),(rows,error))
            self.assertIn('pixel_9_pro_xl|'+monitor.EBAY_MARKETPLACE_ID,self.access.state()['html_attempts'])
        finally:MonitorPassBudget.current.reset(token)


if __name__=='__main__':unittest.main()
