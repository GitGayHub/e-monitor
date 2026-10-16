import json,unittest
from pathlib import Path
import monitor

class PhoneRefurbishedHistoryTests(unittest.TestCase):
    def test_own_purchase_and_comparison_controls_in_all_formats(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_refurbished_history_oct16.json').read_text(encoding='utf8'))
        title='Samsung Galaxy S25 Edge 512GB Smartphone'
        for c in cases:
            self.assertEqual(c['refurbished'],monitor._phone_description_refurbished(c['description']),c['id'])
            for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
                search={'query':'samsung galaxy s25 edge','filters':{'category':'phones','listing_type':listing,'best_offer':offer}}
                d={'title':title,'description':c['description'],'condition':'Gebraucht','categoryId':'9355'}
                self.assertEqual(not c['refurbished'],monitor._details_match_contract({'title':title,'item_id':c['id']},search,d),(c['id'],listing,offer))
