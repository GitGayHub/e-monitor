import json
import unittest
from pathlib import Path
import monitor
from test_parity import evaluate


class PhoneBundleDefectTests(unittest.TestCase):
    def test_purpose_and_selection_in_all_formats(self):
        cases = json.loads((Path(__file__).parent / 'qa/fixtures/phone_bundle_defect_oct15.json').read_text(encoding='utf8'))
        for case in cases:
            title = case['title']
            self.assertEqual(case['accessory'], monitor._is_phone_accessory_title(monitor._normalize(title)), title)
            for listing, offer in [('buy_now', False), ('buy_now', True), ('auction', False), ('auction', True)]:
                fixture = {'name':case['id'], 'search':{'id':'phone-fixture','query':'google pixel 9 pro xl','category':'phones','listingType':listing,'bestOffer':offer,'condition':'any','maxPrice':1000,'enabled':True,'notify':True},
                           'item':{'item_id':case['id'],'title':title,'price':400,'shipping_cost':6.19,'seller_name':'fixture','condition':case['condition'],'location':'DE','buy_now':listing=='buy_now','auction':listing=='auction','best_offer':offer},
                           'settings':{'warn_non_eu':False}}
                self.assertEqual(case['accepted'], evaluate(fixture)[0], (title, listing, offer))

    def test_full_description_accepts_handset_bundle_and_rejects_burn_in(self):
        cases = json.loads((Path(__file__).parent / 'qa/fixtures/phone_bundle_defect_oct15.json').read_text(encoding='utf8'))
        for case in cases[:2]:
            search = {'query':'google pixel 9 pro xl','filters':{'category':'phones'}}
            item = {'title':case['title'],'item_id':case['id']}
            details = {'title':case['title'],'description':case['description'],'condition':case['condition'],'categoryPath':'Handys & Smartphones'}
            self.assertEqual(case['accepted'], monitor._details_match_contract(item, search, details), case['id'])
