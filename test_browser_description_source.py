"""Offline browser-source checks with synthetic pages and item IDs."""
import sys
import unittest
from unittest.mock import Mock, MagicMock, patch

import monitor


class BrowserDescriptionSourceTests(unittest.TestCase):
    item = '123456789012'
    item_url = 'https://www.ebay.de/itm/' + item
    desc_url = 'https://itm.ebaydesc.com/itmdesc/' + item
    body = '<p>Complete working synthetic item.</p>'
    own = '<a href="' + desc_url + '">Own description</a>'

    def run_page(self, page):
        browser = Mock(); browser.new_page.return_value = page
        runtime = Mock(); runtime.chromium.launch.return_value = browser
        context = MagicMock(); context.__enter__.return_value = runtime
        module = Mock(); module.sync_playwright.return_value = context
        with patch.dict(sys.modules, {'playwright.sync_api': module}), \
             patch.dict('os.environ', {'EBAY_HTML_PLAYWRIGHT': '1'}), \
             patch.object(monitor, '_parse_item_details_html', return_value={'description': self.body}):
            result = monitor._fetch_item_details_browser(self.item)
        browser.close.assert_called_once()
        return result

    def linked_page(self, item_final, description_final):
        page = Mock(); page.url = item_final
        page.content.return_value = self.own
        page.locator.return_value.count.return_value = 0
        page.locator.return_value.inner_html.return_value = self.body
        def goto(url, **_kwargs):
            page.url = item_final if '/itm/' in url else description_final
        page.goto.side_effect = goto
        return page

    def test_redirected_item_page_is_not_accepted(self):
        page = self.linked_page('https://www.ebay.de/itm/999999999999', self.desc_url)
        self.assertIsNone(self.run_page(page))

    def test_redirected_linked_description_is_not_accepted(self):
        for target in ('https://evil.invalid/description', 'https://itm.ebaydesc.com/itmdesc/999999999999'):
            with self.subTest(target=target):
                page = self.linked_page(self.item_url, target)
                self.assertIsNone(self.run_page(page))

    def test_correct_linked_description_is_accepted(self):
        page = self.linked_page(self.item_url, self.desc_url)
        self.assertEqual(self.body, self.run_page(page)['description'])

    def test_linked_page_that_changes_address_during_read_is_rejected(self):
        page = self.linked_page(self.item_url, self.desc_url)
        def read_body(**_kwargs):
            page.url = 'https://evil.invalid/description'
            return self.body
        page.locator.return_value.inner_html.side_effect = read_body
        self.assertIsNone(self.run_page(page))

    def iframe_page(self, frame_url):
        page = Mock(); page.url = self.item_url; page.content.return_value = '<iframe id="desc_ifr"></iframe>'
        page.locator.return_value.count.return_value = 1
        frame = page.locator.return_value.element_handle.return_value.content_frame.return_value
        frame.url = frame_url
        frame.locator.return_value.inner_html.return_value = self.body
        return page

    def test_foreign_or_other_item_iframe_is_not_accepted(self):
        for url in ('https://evil.invalid/description', 'https://itm.ebaydesc.com/itmdesc/999999999999'):
            with self.subTest(url=url): self.assertIsNone(self.run_page(self.iframe_page(url)))

    def test_correct_iframe_is_accepted(self):
        self.assertEqual(self.body, self.run_page(self.iframe_page(self.desc_url))['description'])

    def test_iframe_that_changes_address_during_read_is_rejected(self):
        class ChangingFrame:
            def __init__(self, body, initial):
                self.calls = 0; self.body = body; self.initial = initial
            @property
            def url(self):
                self.calls += 1
                return self.initial if self.calls == 1 else 'https://evil.invalid/description'
            def locator(self, _selector):
                return Mock(inner_html=Mock(return_value=self.body))
        page = self.iframe_page(self.desc_url)
        page.locator.return_value.element_handle.return_value.content_frame.return_value = ChangingFrame(self.body, self.desc_url)
        self.assertIsNone(self.run_page(page))
