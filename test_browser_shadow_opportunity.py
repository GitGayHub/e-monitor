"""Synthetic, offline checks of a measurement-only browser experiment."""
import sys
import unittest
from unittest.mock import Mock, MagicMock, patch

import monitor


class BrowserShadowOpportunityTests(unittest.TestCase):
    item = '123456789012'
    source = 'https://itm.ebaydesc.com/itmdesc/' + item
    body = '<p>Complete working synthetic phone.</p>'
    quote = ('<h1>Samsung Galaxy S24 Ultra</h1><div class="x-price-primary">EUR 380,00</div>'
             '<div class="ux-labels-values--shipping">Versand: EUR 6,19</div>')

    def run_browser(self, html=None, source=None, iframe=False, parse_error=False):
        page = Mock(); page.url = 'https://www.ebay.de/itm/' + self.item
        page.content.return_value = self.quote if html is None else html
        page.locator.return_value.count.return_value = int(iframe)
        page.locator.return_value.scroll_into_view_if_needed.side_effect = TimeoutError('offline')
        browser = Mock(); browser.new_page.return_value = page
        runtime = Mock(); runtime.chromium.launch.return_value = browser
        context = MagicMock(); context.__enter__.return_value = runtime
        module = Mock(); module.sync_playwright.return_value = context
        monitor._item_details_events.pop(self.item, None)
        with patch.dict(sys.modules, {'playwright.sync_api': module}), \
             patch.dict('os.environ', {'EBAY_HTML_PLAYWRIGHT': '1'}), \
             patch.object(monitor, '_get_ebay_session') as network, \
             patch.object(monitor, '_parse_item_details_html', side_effect=ValueError('offline') if parse_error else None,
                          wraps=None if parse_error else monitor._parse_item_details_html):
            result = monitor._fetch_item_details_browser(self.item, shadow_description=self.body,
                shadow_source=self.source if source is None else source)
        network.assert_not_called(); browser.close.assert_called_once()
        events = [x['reason'] for x in monitor.item_details_diagnostics(self.item)['events']]
        return result, events, page

    def test_eligible_case_is_measured_and_original_fallback_still_runs(self):
        result, events, page = self.run_browser()
        self.assertIsNone(result); self.assertIn('browser_shadow_fresh_eligible', events)
        page.locator.return_value.scroll_into_view_if_needed.assert_called_once()

    def test_incomplete_quote_or_existing_iframe_does_not_count(self):
        for iframe, html in ((True, self.quote), (False, '<h1>No price</h1>')):
            with self.subTest(iframe=iframe):
                result, events, page = self.run_browser(html=html, iframe=iframe)
                self.assertIsNone(result); self.assertNotIn('browser_shadow_fresh_eligible', events)
                page.locator.return_value.scroll_into_view_if_needed.assert_called_once()

    def test_missing_or_untrusted_source_does_not_count(self):
        for source in ('', 'https://evil.invalid/description', 'https://itm.ebaydesc.com/itmdesc/999999999999'):
            with self.subTest(source=source):
                result, events, page = self.run_browser(source=source)
                self.assertIsNone(result); self.assertNotIn('browser_shadow_fresh_eligible', events)
                page.locator.return_value.scroll_into_view_if_needed.assert_called_once()

    def test_shadow_parser_failure_is_reported_without_skipping_fallback(self):
        result, events, page = self.run_browser(parse_error=True)
        self.assertIsNone(result); self.assertIn('browser_shadow_check_failed', events)
        page.locator.return_value.scroll_into_view_if_needed.assert_called_once()

    def test_html_supplies_only_a_trusted_matching_source(self):
        html = f'<title>synthetic</title><iframe id="desc_ifr" src="{self.source}"></iframe>'
        response = Mock(status_code=200, text=html, url='https://www.ebay.de/itm/'+self.item)
        session = Mock(); session.get.return_value = response
        partial = {'description': self.body, 'htmlMoneyIncomplete': True}
        with patch.object(monitor, '_ebay_active_host', 'ebay.de'), \
             patch.object(monitor, '_get_ebay_session', return_value=session), \
             patch.object(monitor, '_parse_item_details_html', return_value=partial), \
             patch.object(monitor, '_fetch_item_details_browser', return_value=None) as browser:
            self.assertEqual(partial, monitor._fetch_item_details_html(self.item))
        browser.assert_called_once_with(self.item, shadow_description=self.body, shadow_source=self.source)
