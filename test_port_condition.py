import json,unittest
from pathlib import Path
import monitor

class PortConditionTests(unittest.TestCase):
    def test_independent_packaging_and_connector_controls(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/port_condition_oct14.json').read_text(encoding='utf8'))
        for case in cases:
            for category in ['consoles','phones','monitors','computers','all']:
                with self.subTest(text=case['text'],category=category):
                    self.assertEqual(case['blocked'],monitor._is_description_blocked(case['text'],category))
