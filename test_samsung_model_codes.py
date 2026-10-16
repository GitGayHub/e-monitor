import json,unittest
from pathlib import Path
import monitor

class SamsungModelCodeTest(unittest.TestCase):
    def test_every_asserted_device_code_in_all_four_formats(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/samsung_model_codes_oct16.json').read_text(encoding='utf8'))['cases']
        for c in cases:
            for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
                d={'title':c['title'],'description':c['description'],'categoryId':'9355','condition':'Gebraucht','localizedAspects':c['aspects']}
                cfg={'query':c['query'],'filters':{'category':'phones','listing_type':listing,'best_offer':offer}}
                with self.subTest(id=c['id'],listing=listing,offer=offer):
                    self.assertEqual(c['accepted'],bool(monitor._details_match_contract({'item_id':c['id'],'title':c['title']},cfg,d)))

