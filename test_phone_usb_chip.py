import json
from pathlib import Path
import unittest

import monitor
from test_search_intent_rules import item


class PhoneUsbChipTests(unittest.TestCase):
    def test_browser_derived_phone_purpose_and_chip_controls(self):
        cases = json.loads((Path(__file__).parent/'qa/fixtures/phone_usb_chip_oct23.json').read_text(encoding='utf8'))['cases']
        for c in cases:
            with self.subTest(c['id']):
                if c['kind'] == 'purpose':
                    actual = monitor._is_phone_accessory_title(monitor._normalize(c['title']))
                else:
                    row = item(c['title'], price=500)
                    details = dict(title=c['title'], description=c['description'], categoryId='9355', localizedAspects=c['aspects'])
                    actual = bool(monitor._details_match_contract(row, dict(query=c['query'], filters=dict(category='phones')), details))
                self.assertEqual(c['expected'], actual, c['id'])


if __name__ == '__main__':
    unittest.main()
