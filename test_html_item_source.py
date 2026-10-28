"""Offline checks for the listing-page identity before accepting its contents."""
import unittest
from unittest.mock import Mock, patch

import monitor


class HtmlItemSourceTests(unittest.TestCase):
    item = '123456789012'
    html = '<title>synthetic listing</title>'
    complete = {'description': 'Synthetic seller description', 'price': {'value': '100', 'currency': 'EUR'}}

    def run_case(self, final_url):
        response = Mock(status_code=200, text=self.html, url=final_url)
        session = Mock(); session.get.return_value = response
        with patch.object(monitor, '_ebay_active_host', 'ebay.de'), \
             patch.object(monitor, '_get_ebay_session', return_value=session), \
             patch.object(monitor, '_parse_item_details_html', return_value=self.complete) as parse, \
             patch.object(monitor, '_fetch_item_details_browser', return_value=None) as browser:
            result = monitor._fetch_item_details_html(self.item)
        return result, parse, browser

    def test_other_item_or_foreign_host_cannot_supply_listing_contents(self):
        for url in ('https://www.ebay.de/itm/999999999999',
                    'https://foreign.invalid/itm/'+self.item,
                    'https://www.ebay.de.evil.invalid/itm/'+self.item,
                    'https://user@www.ebay.de/itm/'+self.item,
                    'https://www.ebay.de/sch/i.html?item='+self.item):
            with self.subTest(url=url):
                result, parse, browser = self.run_case(url)
                self.assertIsNone(result); parse.assert_not_called(); browser.assert_called_once_with(self.item)

    def test_known_ebay_hosts_and_same_item_keep_working(self):
        for url in ('https://www.ebay.de/itm/'+self.item+'?x=1',
                    'https://m.ebay.de/itm/phone-name/'+self.item,
                    'https://www.ebay.com/itm/'+self.item):
            with self.subTest(url=url):
                result, parse, browser = self.run_case(url)
                self.assertEqual(self.complete, result); parse.assert_called_once(); browser.assert_not_called()
