import json,unittest
from pathlib import Path
import monitor

class PhonePackagingTest(unittest.TestCase):
    def test_seller_declared_refurbished_does_not_require_header_agreement(self):
        for body,expected in [('Zustand: Hervorragend - Refurbished',True),('Artikelzustand: Sehr gut - Refurbished',True),('Condition: Excellent - Refurbished',True),('Neues Gerät. Professionell geprüft und aufbereitet. Zubehör wird bei Bedarf ersetzt.',False),('Zustand: Neu. Kein Refurbished Gerät.',False)]:
            self.assertEqual(expected,monitor._phone_description_refurbished(body),body)

    def test_photographic_camera_is_not_the_sold_phone(self):
        title='Samsung Galaxy S25 Edge 256 GB ca. 26 ultra gute Fotos mit Xiaomi 17 max gemacht'
        self.assertTrue(monitor._matches_phone_query_model(monitor._normalize(title),'samsung galaxy s25 edge'))
        self.assertFalse(monitor._matches_phone_query_model('xiaomi 17 max fotos mit samsung galaxy s25 edge gemacht','samsung galaxy s25 edge'))

    def test_independent_box_and_complete_handset_controls(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_packaging_oct15.json').read_text(encoding='utf8'))['cases']
        for c in cases:
            with self.subTest(id=c['id']):
                self.assertEqual(c['accessory'],monitor._is_phone_accessory_title(monitor._normalize(c['title'])))
                for auction,offer in [(False,False),(False,True),(True,False),(True,True)]:
                    d={'title':c['title'],'description':c['description'],'categoryId':'9355','condition':'Gebraucht','buyingOptions':['AUCTION' if auction else 'FIXED_PRICE']+(['BEST_OFFER'] if offer else [])}
                    search={'query':'samsung galaxy s25 edge','filters':{'category':'phones','listing_type':'auction' if auction else 'buy_now','best_offer':offer}}
                    item={'item_id':c['id'],'title':c['title']}
                    self.assertEqual(c['accepted'],bool(monitor._details_match_contract(item,search,d)),(c['id'],auction,offer))
                    d['estimatedAvailabilities']=[{'estimatedAvailabilityStatus':'UNAVAILABLE'}]
                    self.assertFalse(monitor._details_match_contract(item,search,d))
