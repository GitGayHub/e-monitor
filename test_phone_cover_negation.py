import json,unittest
from pathlib import Path
import monitor


class PhoneCoverNegationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_cover_negation_oct20.json').read_text(encoding='utf8'))

    def test_denied_display_fault_lists_preserve_real_faults_and_trade_only(self):
        for case in self.cases['descriptions']:
            with self.subTest(text=case['text']):
                self.assertEqual(case['blocked'],monitor._is_description_blocked(case['text'],'phones'))

    def test_phone_with_cover_is_not_a_cover_for_phone(self):
        for case in self.cases['titles']:
            with self.subTest(text=case['text']):
                self.assertEqual(case['blocked'],monitor._is_category_blocked_title(monitor._normalize(case['text']),'phones'))


if __name__=='__main__':unittest.main()
