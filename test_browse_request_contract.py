"""Regressions from independent S24 browser/API audit, 2026-10-05."""
import io
import json
import unittest
from unittest.mock import patch

import monitor


class BrowseRequestContractTest(unittest.TestCase):
    def test_any_condition_omits_the_invalid_enum_that_discarded_real_nubia_results(self):
        # Live response 2026-10-05: 54 listings plus warning 12002 for
        # conditions:{NEW|USED|REFURBISHED}. Documentation permits NEW, USED,
        # UNSPECIFIED; "any" should not narrow the request at all.
        for condition, expected in (('any',None),('new','conditions:{NEW}'),('used','conditions:{USED}')):
            search = {'query':'Nubia Z70 Ultra','filters':{'condition':condition,'listing_type':'buy_now_offer','location':'worldwide'}}
            value = monitor._build_ebay_api_params(search)['filter']
            self.assertNotIn('REFURBISHED',value)
            if expected:
                self.assertIn(expected,value)
            else:
                self.assertNotIn('conditions:',value)

    def test_verified_destination_can_replace_a_stale_fee_with_free_or_expensive_delivery(self):
        settings = {'user_zip': '09648', 'user_country': 'de', 'warn_non_eu': False}
        for cost, postcode, expected in ((0, '09648', 0), (242.40, '09648', 242.40), (0, '10115', 6.19), (242.40, '10115', 6.19)):
            with self.subTest(cost=cost, postcode=postcode):
                item = {'item_id': 'shipping', 'price': 30, 'shipping_cost': 6.19, 'location': 'DE', 'buy_now': True}
                details = {'shippingOptions': [{'shippingCost': {'value': str(cost), 'currency': 'EUR'},
                    'shippingCostType': 'FIXED', 'shipToLocationUsedForEstimate': {'country': 'DE', 'postalCode': postcode}}]}
                monitor._calculate_total(item, settings, details)
                self.assertAlmostEqual(expected, item['shipping_cost'])
                self.assertAlmostEqual(30 + expected, item['total_price'])

    def test_details_cache_cannot_reuse_delivery_for_another_postal_code(self):
        received = []
        def response(request, **kwargs):
            context = next(value for key, value in request.header_items() if key.lower() == 'x-ebay-c-enduserctx')
            received.append(context)
            body = {'description': 'Complete functional controller.', 'shippingOptions': [
                {'shippingCost': {'value': '0' if '10115' in context else '6.19', 'currency': 'EUR'}, 'shippingCostType': 'FIXED'}]}
            return io.BytesIO(json.dumps(body).encode())
        with patch.object(monitor, '_item_details_cache', {}), patch.object(monitor, 'EBAY_SOURCE', 'api'), \
             patch.object(monitor, '_ebay_api_configured', return_value=True), \
             patch.object(monitor, '_get_ebay_api_token', return_value=('qa', None)), \
             patch.object(monitor.browse_access, 'acquire', return_value=True), \
             patch.object(monitor.urllib.request, 'urlopen', side_effect=response), \
             patch.object(monitor.config, 'get_settings') as settings:
            settings.return_value = {'user_zip': '09648'}
            first = monitor._fetch_item_details('qa')
            settings.return_value = {'user_zip': '10115'}
            second = monitor._fetch_item_details('qa')
            self.assertEqual(second, monitor._fetch_item_details('qa'))
            self.assertNotEqual(first, second)
            self.assertEqual(2, len(received))

    def test_open_ended_zero_and_marketplace_currency(self):
        for market, currency in (("EBAY_DE", "EUR"), ("EBAY_GB", "GBP"), ("EBAY_US", "USD")):
            for lower, upper in ((150, None), (None, 0), (0, 2500)):
                with self.subTest(market=market, lower=lower, upper=upper):
                    search = {"query": "samsung s24 ultra", "filters": {
                        "min_price": lower, "max_price": upper, "category": "phones",
                        "listing_type": "buy_now", "location": "worldwide"}}
                    actual = monitor._build_ebay_api_params(search, market)["filter"]
                    self.assertIn(f"price:[{lower if lower is not None else ''}..{upper if upper is not None else ''}]", actual)
                    self.assertIn(f"priceCurrency:{currency}", actual)
                    self.assertIn("itemLocationRegion:WORLDWIDE", actual)

    def test_zip_is_encoded_for_search_and_details(self):
        with patch.object(monitor.config, "get_settings", return_value={"user_zip": "09648"}):
            self.assertEqual("contextualLocation=country%3DDE%2Czip%3D09648",
                             monitor._ebay_end_user_context("EBAY_DE"))

    def test_filter_warning_does_not_become_success_or_touch_live_state(self):
        payload = {"itemSummaries": [], "warnings": [{"errorId": 12012, "message": "priceCurrency required"}]}
        with patch.object(monitor, "_get_ebay_api_token", return_value=("qa", None)), \
             patch.object(monitor.browse_access, "acquire", return_value=True), \
             patch.object(monitor.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())), \
             patch.object(monitor, "record_search_run") as record:
            self.assertEqual(([], "api_filters_ignored"), monitor.fetch_ebay_api_ex({"id": "qa", "query": "samsung s24 ultra"}, force=True))
            record.assert_not_called()
