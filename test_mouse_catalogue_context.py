import json,unittest
from pathlib import Path
import monitor,mouse_offer

class MouseCatalogueContextTests(unittest.TestCase):
    def test_independent_catalogue_contexts(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/mouse_catalogue_context.json').read_text(encoding='utf8'))
        for case in cases:
            with self.subTest(case=case['id']):
                details={**case,'condition':'Gebraucht'}
                search=dict(query='logitech superlight 2 dex',filters=dict(category='mice'))
                self.assertEqual(case['expected'],monitor._details_match_contract({'title':case['title']},search,details))

    def test_contents_window_does_not_cut_model_suffix(self):
        prefix='lieferumfang '+('a '*69)+'logitech '
        # The DEX suffix straddles the old fixed 160-character window.
        text=prefix+'superlight 2 dex maus und usb empfaenger'
        self.assertIsNone(mouse_offer.own_model_conflict(text,'logitech superlight 2 dex'))
        self.assertIsNotNone(mouse_offer.own_model_conflict(text.replace('2 dex','2 se'),'logitech superlight 2 dex'))
