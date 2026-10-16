import json, unittest
from pathlib import Path
import monitor
from test_parity import evaluate

class ImplicitPhoneBundleTest(unittest.TestCase):
    def test_independent_purpose_damage_and_ram_in_four_formats(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_implicit_bundle_oct16.json').read_text(encoding='utf8'))['cases']
        for c in cases:
            for auction,offer in [(False,False),(False,True),(True,False),(True,True)]:
                with self.subTest(id=c['id'],auction=auction,offer=offer):
                    search={'id':'purpose-control','query':'samsung s24 ultra','category':'phones','listingType':'auction' if auction else 'buy_now','bestOffer':offer,'condition':'any','maxPrice':1000,'enabled':True,'notify':True}
                    item={'item_id':c['id'],'title':c['title'],'price':400,'shipping_cost':6.19,'seller_name':'fixture','condition':'Gebraucht','location':'DE','buy_now':not auction,'auction':auction,'best_offer':offer}
                    self.assertEqual(c['titleAccepted'],evaluate({'search':search,'item':item,'settings':{'warn_non_eu':False}})[0])
                    d={'title':c['title'],'description':c['description'],'categoryId':'9355','condition':'Gebraucht','localizedAspects':c['aspects']}
                    cfg={'query':'samsung s24 ultra','filters':{'category':'phones','listing_type':'auction' if auction else 'buy_now','best_offer':offer}}
                    self.assertEqual(c['accepted'],bool(monitor._details_match_contract(item,cfg,d)))

