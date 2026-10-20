import json,unittest
from pathlib import Path
import monitor

class MobileSearchStatusTests(unittest.TestCase):
    def test_mobile_count_heading_and_service_cards_preserve_response_status(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/mobile_search_status_oct20.json').read_text(encoding='utf8'))
        for case in cases:
            with self.subTest(case=case['id']):
                items,error=monitor._parse_search_body(case['html'],'ebay.de','LS27FG604 500Hz')
                self.assertEqual(case['items'],len(items))
                self.assertEqual(case['error'],error)
