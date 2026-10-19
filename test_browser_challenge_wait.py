"""A recognised challenge cannot produce SERP cards; do not wait for them."""
import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,MagicMock,patch
import monitor,price_history
from ebay_access import BrowseAccess,MonitorPassBudget


class BrowserChallengeWaitTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        p=patch.object(price_history,'DB_PATH',str(Path(folder.name)/'history.db'));p.start();self.addCleanup(p.stop)
        self.token=MonitorPassBudget.current.set(None);self.addCleanup(MonitorPassBudget.current.reset,self.token)
        for name,value in [('browse_access',BrowseAccess()),('_ebay_query_cache',{}),('_runtime_html_fallback',False),
                           ('_runtime_api_fallback',False),('_ebay_block_until',0),('_ebay_active_host',None),
                           ('_ebay_consecutive_blocks',0),('_ebay_api_circuit_open',False),('EBAY_SOURCE','auto')]:
            p=patch.object(monitor,name,value);p.start();self.addCleanup(p.stop)
        self.url='https://www.ebay.de/sch/i.html?_nkw=qa'
        self.page=Mock();self.page.url=self.url
        self.searchNavigated=False;self.settlingAfterNavigation=[]
        def navigated(url,**kwargs):
            if url==self.url:self.searchNavigated=True
        self.page.goto.side_effect=navigated
        self.page.wait_for_timeout.side_effect=lambda milliseconds:self.settlingAfterNavigation.append(milliseconds) if self.searchNavigated else None
        self.rendered=False
        self.page.wait_for_selector.side_effect=lambda *args,**kwargs:setattr(self,'rendered',True)
        self.browser=Mock();self.browser.new_context.return_value.new_page.return_value=self.page
        runtime=Mock();runtime.chromium.launch.return_value=self.browser
        context=MagicMock();context.__enter__.return_value=runtime
        module=Mock();module.sync_playwright.return_value=context
        p=patch.dict(sys.modules,{'playwright.sync_api':module});p.start();self.addCleanup(p.stop)
        p=patch.dict('os.environ',{'EBAY_HTML_PLAYWRIGHT':'1'});p.start();self.addCleanup(p.stop)

    def test_initial_challenge_does_not_wait_for_cards_or_try_cookie_buttons(self):
        self.page.content.return_value='<html><title>Pardon Our Interruption</title></html>'
        self.assertEqual(([],'blocked'),monitor._do_fetch_playwright(self.url,'qa'))
        self.page.wait_for_selector.assert_not_called()
        self.page.locator.assert_not_called()
        self.assertEqual([],self.settlingAfterNavigation)
        self.browser.close.assert_called_once()

    def test_splash_redirect_is_detected_before_waiting_even_without_body_markers(self):
        self.page.url='https://www.ebay.de/splashui/captcha'
        self.page.content.return_value='<html><body></body></html>'
        self.assertEqual(([],'blocked'),monitor._do_fetch_playwright(self.url,'qa'))
        self.page.wait_for_selector.assert_not_called()
        self.browser.close.assert_called_once()

    def test_loading_document_still_waits_for_rendered_cards(self):
        self.page.content.side_effect=lambda: '<html><li class="s-card">Rendered</li></html>' if self.rendered else '<html><body>Loading</body></html>'
        item=dict(item_id='123456789012',title='QA',price=10)
        with patch.object(monitor,'_parse_search_body',return_value=([item],None)) as parse:
            rows,error=monitor._do_fetch_playwright(self.url,'qa')
        self.assertIsNone(error);self.assertEqual('123456789012',rows[0]['item_id'])
        self.page.wait_for_selector.assert_called_once()
        self.assertIn('Rendered',parse.call_args.args[0])
        self.browser.close.assert_called_once()

    def test_challenge_that_arrives_after_loading_still_is_not_empty(self):
        self.page.content.side_effect=lambda: '<title>Pardon Our Interruption</title>' if self.rendered else '<html>Loading</html>'
        self.assertEqual(([],'blocked'),monitor._do_fetch_playwright(self.url,'qa'))
        self.page.wait_for_selector.assert_called_once()
        self.browser.close.assert_called_once()

    def test_complete_no_results_page_remains_successful_empty(self):
        self.page.content.return_value='<html><h1>Keine exakten Treffer gefunden</h1></html>'
        self.assertEqual(([],None),monitor._do_fetch_playwright(self.url,'qa'))
        self.page.wait_for_selector.assert_called_once()
        self.browser.close.assert_called_once()

    def test_absent_cookie_banner_does_not_wait_for_three_nonexistent_buttons(self):
        self.page.content.return_value='<html><h1>Keine exakten Treffer gefunden</h1></html>'
        button=self.page.locator.return_value.first
        button.is_visible.return_value=False
        self.assertEqual(([],None),monitor._do_fetch_playwright(self.url,'qa'))
        button.click.assert_not_called()
        self.page.wait_for_selector.assert_called_once()

    def test_one_visible_cookie_banner_is_accepted_once_without_other_selectors(self):
        self.page.content.return_value='<html><h1>Keine exakten Treffer gefunden</h1></html>'
        button=self.page.locator.return_value.first
        button.is_visible.return_value=True
        self.assertEqual(([],None),monitor._do_fetch_playwright(self.url,'qa'))
        self.page.locator.assert_called_once_with('button#gdpr-banner-accept')
        button.click.assert_called_once()
        self.page.wait_for_selector.assert_called_once()

    def test_real_outer_html_first_path_retains_api_reserve_without_fake_zero(self):
        self.page.content.return_value='<title>Pardon Our Interruption</title>'
        search=dict(id='qa-challenge',query='phone',filters=dict(listing_type='buy_now'))
        for reserve in [([],None),([dict(item_id='123456789012',title='QA',price=10,source='api')],None)]:
            with self.subTest(reserve=bool(reserve[0])),patch.object(monitor,'_do_fetch_one',return_value=([],'network')), \
                 patch.object(monitor,'_ebay_api_configured',return_value=True), \
                 patch.object(monitor.browse_access,'is_paused',return_value=False), \
                 patch.object(monitor,'fetch_ebay_api_ex',return_value=reserve) as api:
                self.page.wait_for_selector.reset_mock()
                rows,error=monitor.fetch_ebay_ex(search,force=True)
                self.assertEqual(bool(reserve[0]),bool(rows))
                self.assertEqual(bool(reserve[0]),error is None)
                api.assert_called_once()
                self.page.wait_for_selector.assert_not_called()


if __name__=='__main__':unittest.main()
