import json
import unittest
from pathlib import Path
import monitor
from test_parity import evaluate


class SimTrayPurposeTests(unittest.TestCase):
    def test_manual_parts_in_every_controlled_bucket(self):
        document = json.loads((Path(__file__).parent / 'qa/fixtures/z70_parts_manual_oct14.json').read_text(encoding='utf8'))
        self.assertEqual(120, len(document['cases']))
        for case in document['cases']:
            with self.subTest(case=case['name']):
                accepted, reason, total = evaluate(case)
                self.assertEqual((False, 'filtered', 100), (accepted, reason, total))

    def test_sim_part_pairs_are_not_handset_bundles(self):
        negative = [
            'ZTE nubia Z70 Ultra NX733J NX736J SIM + SIM-Kartenhalter (Schwarz)',
            'Samsung Galaxy S25 Edge SIM + SIM Card Tray',
            'Apple iPhone 17 Pro Max SIM-Kartenhalter',
            'Nubia Z80 Ultra SIM Kartenschublade',
            'SIM Card Holder for Google Pixel 5',
        ]
        positive = [
            'Nubia Z70 Ultra 256GB Dual SIM',
            'Nubia Z70 Ultra 256GB SIM + SIM-Kartenhalter',
            'Nubia Z70 Ultra Dual SIM + SIM Card Tray',
            'Samsung Galaxy S25 Edge Smartphone mit SIM-Kartenhalter',
            'Apple iPhone 17 Pro Max 512GB mit SIM Card Tray',
        ]
        for title in negative:
            self.assertTrue(monitor._is_phone_accessory_title(monitor._normalize(title)), title)
        for title in positive:
            self.assertFalse(monitor._is_phone_accessory_title(monitor._normalize(title)), title)
