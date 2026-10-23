import json
from pathlib import Path
import unittest

import monitor
from test_search_intent_rules import item, DummyConfig


class PhoneUsbChipTests(unittest.TestCase):
    def test_browser_derived_phone_purpose_and_chip_controls(self):
        self.check_cases('phone_usb_chip_oct23.json')

    def test_own_processor_prose_and_scope_controls(self):
        self.check_cases('phone_own_processor_oct23.json')

    def test_pixel_model_word_order_controls(self):
        self.check_cases('phone_model_word_order_oct23.json')

    def test_sold_pixel_spacing_and_referential_repair(self):
        self.check_cases('phone_sold_pixel_oct23.json')

    def check_cases(self, resource):
        cases = json.loads((Path(__file__).parent/'qa/fixtures'/resource).read_text(encoding='utf8'))['cases']
        for c in cases:
            with self.subTest(c['id']):
                if c['kind'] == 'purpose':
                    actual = monitor._is_phone_accessory_title(monitor._normalize(c['title']))
                elif c['kind'] == 'repair':
                    actual = monitor._phone_repair_label(c['description']) is not None
                elif c['kind'] == 'listing':
                    actual = bool(monitor.filter_results([item(c['title'], price=500)], dict(query=c['query'], filters=dict(category='phones', listing_type='buy_now', limit_price=910)), DummyConfig(), skip_seen=True, is_statistics=True))
                elif c['kind'] == 'model':
                    actual = monitor._matches_phone_query_model(monitor._normalize(c['title']), monitor._normalize(c['query']))
                else:
                    row = item(c['title'], price=500)
                    details = dict(title=c['title'], description=c['description'], categoryId='9355', localizedAspects=c['aspects'])
                    actual = bool(monitor._details_match_contract(row, dict(query=c['query'], filters=dict(category='phones')), details))
                self.assertEqual(c['expected'], actual, c['id'])


if __name__ == '__main__':
    unittest.main()
