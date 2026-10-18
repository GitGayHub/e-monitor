import json,unittest
from pathlib import Path
import monitor
from test_parity import evaluate

class PhoneStorageTest(unittest.TestCase):
    def test_observed_unsupported_storage_and_controls_in_all_baskets(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_storage_oct18.json').read_text(encoding='utf8'))['cases']
        for c in cases:
            for auction,offer in ((False,False),(False,True),(True,False),(True,True)):
                with self.subTest(id=c['id'],auction=auction,offer=offer):
                    search={'id':'storage-test','query':c['query'],'category':'phones','listingType':'auction' if auction else 'buy_now','bestOffer':offer,'condition':'any','maxPrice':2000,'enabled':True,'notify':True}
                    item={'item_id':c['id'],'title':c['title'],'price':700,'shipping_cost':6.19,'seller_name':'fixture','condition':'Gebraucht','location':'DE','buy_now':not auction,'auction':auction,'best_offer':offer}
                    self.assertEqual(c['titleAccepted'],evaluate({'search':search,'item':item,'settings':{'warn_non_eu':False}})[0])
                    details={'title':c['title'],'description':c['description'],'localizedAspects':c['aspects'],'categoryId':'9355','condition':'Gebraucht'}
                    config={'query':c['query'],'filters':{'category':'phones','listing_type':search['listingType'],'best_offer':offer}}
                    self.assertEqual(c['accepted'],bool(monitor._details_match_contract(item,config,details)))

    def test_bundled_storage_is_not_the_handset_capacity(self):
        self.assertTrue(monitor._phone_specifications_match('Apple iPhone 17 Pro Max 256GB mit 128GB USB Stick','','iphone 17 pro max'))
