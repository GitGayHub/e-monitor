"""Issue e-monitor-android#2: honest statuses and the item's own country.

Fixtures are shared byte-for-byte with the Android JVM tests.
"""
import json,unittest
from pathlib import Path
import monitor
from mobile import runtime_status

FIXTURES=Path(__file__).parent/'qa/fixtures'


class StatusCountryTests(unittest.TestCase):
    def test_known_item_country_is_never_shown_as_unspecified(self):
        for case in json.loads((FIXTURES/'country_location_oct22.json').read_text(encoding='utf-8')):
            with self.subTest(location=case['location']):
                self.assertEqual(case['code'],monitor._country_code_from_location(case['location']))
                shown=monitor._format_country_for_notification(case['location'])
                self.assertEqual(case['code'] is None,shown=='Не указано')
        self.assertEqual('🇧🇬 Болгария',monitor._format_country_for_notification('Sofia, Bulgarien'))

    def test_new_country_codes_keep_existing_region_decisions(self):
        # EU membership and the DE filter agreed before through name fallbacks.
        for location,eu in [('Sofia, Bulgarien',True),('Zagreb, Kroatien',True),('Hongkong',False),('Istanbul, Türkei',False),('Stäbelow, Deutschland',True)]:
            with self.subTest(location=location):
                self.assertEqual(eu,monitor._is_eu(location))
        self.assertTrue(monitor._is_clearly_non_germany_location('Sofia, Bulgarien'))
        self.assertFalse(monitor._is_clearly_non_germany_location('71332 Waiblingen'))
        self.assertFalse(monitor._is_clearly_non_germany_location(''))

    def test_challenge_truncated_and_zero_pages_are_distinct(self):
        for case in json.loads((FIXTURES/'search_challenge_oct22.json').read_text(encoding='utf-8')):
            with self.subTest(case=case['id']):
                rows,error=monitor._parse_search_body(case['html'],'ebay.de','sony ult wear')
                self.assertEqual((case['error'],case['count']),(error,len(rows)))

    def test_http_and_api_refusals_are_not_reported_as_description_problems(self):
        searches={'searches':[{'id':'a','query':'Sony ULT Wear'}]}
        cases=[('a: http_403','blocked','403'),('a: http_429','rate_limit','429'),('a: http_500','http','500'),
               ('a: api_auth','api_auth','API'),('a: auction site_error','site_error','временной'),
               ('a: ending soon blocked','blocked','доступ'),('a: network','network','ответ'),
               ('a: описания или цены недоступны (2); история неполная','details_unavailable','описание'),
               ('a: something new','unknown','повторится')]
        for text,code,word in cases:
            with self.subTest(text=text):
                issue=runtime_status.search_issues(searches,[text])[0]
                self.assertEqual((code,'Sony ULT Wear'),(issue['code'],issue['searchName']))
                self.assertIn(word,issue['message'])
                if code!='details_unavailable':self.assertNotIn('описание',issue['message'])


if __name__=='__main__':
    unittest.main()
