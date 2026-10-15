import copy,json,unittest
from pathlib import Path
from bs4 import BeautifulSoup
import monitor,selected_variant

class SelectedPhoneVariantTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=json.loads((Path(__file__).parent/'qa/fixtures/selected_phone_variant_oct15.json').read_text())

    def details(self,html=None,description=None):
        return monitor._parse_item_details_html(html or self.fixture['html'],description=description or self.fixture['description'])

    def contract(self,data,query='Nubia Z70 Ultra'):
        return monitor._details_match_contract({'item_id':self.fixture['id'],'title':data.get('title','')},{'query':query,'filters':{'category':'phones'}},data)

    def test_real_selected_capacity_price_and_own_purchase_action_are_bound(self):
        data=self.details()
        self.assertEqual(self.fixture['selectedId'],data.get('selectedVariant',{}).get('id'))
        self.assertTrue(self.contract(data))
        self.assertTrue(self.contract(data,'Nubia Z70 Ultra 512GB'))
        self.assertFalse(self.contract(data,'Nubia Z70 Ultra 1TB'))
        self.assertIn('512GB',data['title']);self.assertNotIn('1TB',data['title'])
        self.assertEqual('567540570817',data['selectedVariant']['url'].split('var=')[1])
        item={'item_id':self.fixture['id'],'title':self.fixture['description'],'price':777,'shipping_cost':25,'buy_now':True,'auction':False,'is_multivariation':False,'location':'CN','seller_name':'qa'}
        monitor._refresh_candidate_details(item,data,{'warn_non_eu':True,'non_eu_tax_rate':.19})
        self.assertFalse(item['is_multivariation'])
        self.assertIn('?var=567540570817',item['url'])
        self.assertAlmostEqual(991.46,item['total_price'])
        self.assertTrue(item['import_estimated'])
        self.assertFalse(self.contract({**data,'estimatedAvailabilities':[{'estimatedAvailabilityStatus':'UNAVAILABLE'}]}))
        self.assertFalse(self.contract(self.details(description='Box only. No smartphone included.')))
        self.assertFalse(self.contract(self.details(description='Das Display ist gebrochen.')))

    def test_google_play_is_a_service_but_other_sold_models_still_conflict(self):
        for title,expected in [('ZTE nubia Z70 Ultra Global Google play',True),('Nubia Z70 Ultra Google Play Store',True),('Nubia Z70 Ultra Google Pixel 5',False),('Google Pixel 5 Google Play',False),('Nubia Z70 Ultra Google Play Google Pixel 5',False),('Nubia Z70 Ultra Google Play Xiaomi 17 Max',False)]:
            self.assertEqual(expected,monitor._matches_phone_query_model(monitor._normalize(title),'nubia z70 ultra'),title)

    def test_live_spaced_samsung_model_survives_preliminary_filter_without_approving_other_generations(self):
        from test_search_intent_rules import DummyConfig
        fixture=json.loads((Path(__file__).parent/'qa/fixtures/samsung_spacing_oct15.json').read_text())
        for title,expected in fixture['controls']:
            self.assertEqual(expected,monitor._matches_phone_query_model(monitor._normalize(title),fixture['query']),title)
        item=monitor.parse_ebay_results(fixture['html'])[0]
        search={'query':fixture['query'],'filters':{'category':'phones','listing_type':'all','limit_price':350,'location':'worldwide'}}
        self.assertTrue(monitor.filter_results([item],search,DummyConfig(),skip_seen=True,is_statistics=True))

    def test_unbound_incomplete_wrong_item_or_unknown_dimensions_never_unlock_variation(self):
        for case in self.fixture['controls']:
            with self.subTest(name=case['name']):
                data=self.details(case['html'])
                self.assertNotIn('selectedVariant',data)
                self.assertFalse(self.contract(data))
