import json
import unittest
from pathlib import Path
import monitor
from test_search_intent_rules import item, DummyConfig

class Ps5ContentsTests(unittest.TestCase):
    def test_whole_consoles_and_spare_controls(self):
        fixture=json.loads((Path(__file__).parent/'qa/fixtures/ps5_contents_oct21.json').read_text(encoding='utf8'))
        for case in fixture['cases']:
            with self.subTest(id=case['id']):
                search=dict(query=fixture['query'],filters=dict(category='consoles',listing_type='all'))
                accepted=monitor.filter_results([item(case['title'],price=1000)],search,DummyConfig(),skip_seen=True,is_statistics=True)
                self.assertEqual(case['keep'],bool(accepted))
