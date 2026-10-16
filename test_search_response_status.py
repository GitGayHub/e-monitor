import json,unittest
from pathlib import Path
from unittest.mock import patch
import monitor

class SearchResponseStatusTests(unittest.TestCase):
    def test_browser_observed_empty_recommendations_and_real_error_are_distinct(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/search_response_oct16.json').read_text())
        for case in cases:
            with self.subTest(case=case['id']):
                rows,error=monitor._parse_search_body(case['html'],'ebay.de','lg ultragear oled 480hz')
                self.assertEqual(case['error'],error)
                self.assertEqual(case['count'],len(rows))

