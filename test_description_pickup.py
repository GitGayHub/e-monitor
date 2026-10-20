import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
import monitor

class DescriptionPickupTest(unittest.TestCase):
    def test_destination_warning_is_not_global_pickup_and_retains_known_delivery(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/shipping_destination_oct15.json').read_text(encoding='utf8'))
        for case in cases:
            for auction,offer in [(False,False),(False,True),(True,False),(True,True)]:
                html='<div class="ux-labels-values--shipping">'+case['text']+'</div>'
                d=monitor._parse_item_details_html(html,description='Whole working device.')
                if not case['pickupOnly']:
                    self.assertIsNot(True,d.get('htmlPickupOnly'),case['id'])
                item={'item_id':case['id'],'title':'Apple iPhone 17 Pro Max','price':732,'shipping_cost':8.99,
                      'buy_now':not auction,'auction':auction,'best_offer':offer,'is_pickup_only':False,'location':'DE'}
                monitor._refresh_candidate_details(item,d,{'warn_non_eu':False})
                with self.subTest(id=case['id'],auction=auction,offer=offer):
                    self.assertEqual(case['pickupOnly'],item['is_pickup_only'])
                    # An explicit own delivery quote refreshes the stale SERP fee;
                    # an unpriced destination warning must keep the known fee.
                    expected = 0 if case['pickupOnly'] else case.get('shippingCost',8.99)
                    self.assertAlmostEqual(expected,item['shipping_cost'])
                    self.assertAlmostEqual(732+expected,item['total_price'])

    def test_own_seller_delivery_overrides_header_in_all_baskets(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/description_pickup_oct15.json').read_text(encoding='utf8'))['cases']
        for c in cases:
            for auction,offer in [(False,False),(False,True),(True,False),(True,True)]:
                options=['AUCTION' if auction else 'FIXED_PRICE']+(['BEST_OFFER'] if offer else [])
                d={'title':'Google Pixel 9 Pro XL 256GB','description':c['description'],'price':{'value':'432','currency':'EUR'},'currentBidPrice':{'value':'432','currency':'EUR'},'htmlShippingCost':{'value':'6.19','currency':'EUR'},'htmlPickupOnly':False,'buyingOptions':options,'itemLocation':{'city':'Berlin','country':'DE'},'condition':'Gebraucht'}
                item={'item_id':c['id'],'title':d['title'],'price':432,'shipping_cost':6.19,'location':'DE','buy_now':not auction,'auction':auction,'best_offer':offer,'is_pickup_only':False}
                monitor._refresh_candidate_details(item,d,{'warn_non_eu':False})
                with self.subTest(id=c['id'],auction=auction,offer=offer):
                    self.assertEqual(c['pickupOnly'],item['is_pickup_only'])
                    self.assertAlmostEqual(0 if c['pickupOnly'] else 6.19,item['shipping_cost'])
                    self.assertAlmostEqual(432 if c['pickupOnly'] else 438.19,item['total_price'])
    def test_refresh_runs_pickup_distance_guard_without_shipping_escape(self):
        description='Google Pixel 9 Pro XL 256GB, voll funktionsfähig. Nur an Selbstabholer.'
        for location,nearby in [('Berlin, DE',True),('99999 Entfernt, DE',False),('Frankfurt am Main, DE',False)]:
            item={'item_id':'qa-pickup','title':'Google Pixel 9 Pro XL 256GB','price':432,'shipping_cost':6.19,'location':location,'buy_now':True,'auction':False,'best_offer':False,'seller_name':'fixture','condition':'Gebraucht'}
            d={'description':description,'htmlPickupOnly':False,'htmlShippingCost':{'value':'6.19','currency':'EUR'}}
            monitor._refresh_candidate_details(item,d,{'warn_non_eu':False})
            search={'query':'google pixel 9 pro xl','filters':{'category':'phones','listing_type':'buy_now','limit_price':1000}}
            with patch('plz_distance.is_nearby',return_value=(nearby,None if nearby else 100.0)) as distance:
                kept=monitor.filter_results([copy.deepcopy(item)],search,monitor.config,skip_seen=True,is_statistics=True)
                self.assertEqual(nearby,bool(kept),location)
                distance.assert_called_once()
