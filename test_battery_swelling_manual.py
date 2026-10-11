import json
import unittest
from pathlib import Path
import monitor

class BatterySwellingManualTests(unittest.TestCase):
    def test_own_seller_battery_fault_and_explicit_denials(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/battery_swelling_manual_oct11.json').read_text(encoding='utf8'))
        for case in cases:
            with self.subTest(case=case['id']):
                self.assertEqual(case['blocked'],monitor._has_battery_swelling(monitor._normalize(case['text'])))
                self.assertEqual(case['blocked'],monitor._is_description_blocked(case['text'],'phones'))
    def test_confirmed_pixel_fault_never_passes_complete_validation(self):
        details={'title':'Google Pixel 5 128GB Schwarz ohne Simlock','description':'Das Gerät funktioniert. Der Akku des Gerätes beginnt sich aufzublähen.'}
        self.assertFalse(monitor._details_match_contract({'title':details['title']},{'query':'Google Pixel 5','filters':{'category':'phones'}},details))
