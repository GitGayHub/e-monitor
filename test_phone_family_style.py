import json,unittest
from pathlib import Path
import monitor
from test_parity import evaluate

class PhoneFamilyStyleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_family_style_oct16.json').read_text(encoding='utf8'))['cases']

    def test_phone_families_and_form_factors_in_all_four_formats(self):
        for c in self.cases:
            with self.subTest(id=c['id']):
                self.assertEqual(c['accessory'],monitor._is_phone_accessory_title(monitor._normalize(c['title'])))
                for auction,offer in [(False,False),(False,True),(True,False),(True,True)]:
                    case={'name':c['id'],'search':{'id':'family-control','query':c['query'],'category':'phones','listingType':'auction' if auction else 'buy_now','bestOffer':offer,'condition':'any','maxPrice':1000,'enabled':True,'notify':True},
                        'item':{'item_id':c['id'],'title':c['title'],'price':400,'shipping_cost':6.19,'seller_name':'fixture','condition':c['condition'],'location':'DE','buy_now':not auction,'auction':auction,'best_offer':offer},'settings':{'warn_non_eu':False}}
                    self.assertEqual(c['titleAccepted'],evaluate(case)[0],(c['id'],auction,offer))
                    d={'title':c['title'],'description':c['description'],'categoryId':'9355','condition':c['condition'],'buyingOptions':['AUCTION' if auction else 'FIXED_PRICE']+(['BEST_OFFER'] if offer else [])}
                    search={'query':c['query'],'filters':{'category':'phones','listing_type':'auction' if auction else 'buy_now','best_offer':offer}}
                    self.assertEqual(c['accepted'],bool(monitor._details_match_contract(case['item'],search,d)),(c['id'],auction,offer))
                    d['estimatedAvailabilities']=[{'estimatedAvailabilityStatus':'UNAVAILABLE'}]
                    self.assertFalse(monitor._details_match_contract(case['item'],search,d))

    def test_phone_brand_inference_does_not_apply_to_other_products(self):
        self.assertFalse(monitor._has_query_word('galaxy s24 ultra oled 500hz','samsung','samsung odyssey oled g6 500hz'))
        self.assertFalse(monitor._has_query_word('iphone 17 pro max','apple','apple studio display'))
