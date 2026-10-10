"""Confirmed 8 Oct DE SERP regressions; captured fields plus synthetic transport controls."""
import unittest
from unittest.mock import patch
import monitor
from query_variants import gpu_pc_aliases, api_query_batches

class CloudSearchRegressions(unittest.TestCase):
    def test_all_hybrid_prices_and_statistics_keep_both_original_formats(self):
        import json,copy
        from pathlib import Path
        from test_search_intent_rules import DummyConfig
        for c in json.loads((Path(__file__).parent/'qa/fixtures/all_hybrid_prices.json').read_text(encoding='utf8')):
            search={'id':'isolated-all','query':'DualSense','filters':{'listing_type':'all','category':'all','limit_price':c['limit'],'min_price':c['minimum'],'max_price':c['hardMaximum']}}
            raw={'item_id':'hybrid','title':'Sony DualSense Controller','seller_name':'seller','price':c['bin'],'bin_price':c['bin'],'auc_price':c['bid'],'shipping_cost':c['shipping'],'buy_now':True,'auction':True,'best_offer':False,'time_left':str(c['auctionHours'])+' Std','condition':'Gebraucht','location':'DE'}
            before=copy.deepcopy(raw)
            with patch.object(monitor,'seen_state',{}):
                notified=monitor.filter_results([raw],search,DummyConfig())
                self.assertEqual(c['eligible'],bool(notified),c['name'])
                if notified:
                    self.assertEqual(c['selected']=='buy_now',notified[0]['buy_now'])
                    self.assertEqual(c['total'],notified[0]['total_price'])
                statistics=monitor.filter_results([raw],search,DummyConfig(),skip_seen=True,is_statistics=True)
                self.assertTrue(statistics[0]['buy_now'] and statistics[0]['auction'])
                self.assertEqual(c['bin']+c['shipping'],statistics[0]['bin_total_price'])
                self.assertEqual(c['bid']+c['shipping'],statistics[0]['auc_total_price'])
            self.assertEqual(before,raw)

    def test_all_hybrid_reselects_purchase_after_live_price_changes(self):
        from test_search_intent_rules import DummyConfig
        search={'id':'isolated-all','query':'DualSense','filters':{'listing_type':'all','category':'all','limit_price':40}}
        raw={'item_id':'hybrid','title':'Sony DualSense Controller','seller_name':'seller','price':350,'bin_price':350,'auc_price':30,'shipping_cost':5,'buy_now':True,'auction':True,'best_offer':False,'time_left':'18 Std','condition':'Gebraucht','location':'DE'}
        with patch.object(monitor,'seen_state',{}):
            item=monitor.filter_results([raw],search,DummyConfig())[0]
            self.assertFalse(item['buy_now'])
            monitor._refresh_candidate_details(item,{'buyingOptions':['FIXED_PRICE','AUCTION'],'price':{'value':'25'},'currentBidPrice':{'value':'30'}},{},search)
            selected=monitor.filter_results([item],search,DummyConfig())[0]
            self.assertTrue(selected['buy_now'] and not selected['auction'])
            self.assertEqual(30,selected['total_price'])

    def test_german_sold_status_from_actual_ps5_page(self):
        import json
        from pathlib import Path
        for c in json.loads((Path(__file__).parent/'qa/fixtures/oct10_sold_status.json').read_text(encoding='utf8')):
            d=monitor._parse_item_details_html(c['html'],description='PS5 Pro, funktioniert einwandfrei')
            self.assertEqual(c['unavailable'],bool(d.get('estimatedAvailabilities')))

    def test_own_pickup_map_resolves_masked_postcode_without_following_it(self):
        import json
        from pathlib import Path
        for c in json.loads((Path(__file__).parent/'qa/fixtures/oct10_pickup_details.json').read_text(encoding='utf8')):
            d=monitor._parse_item_details_html(c['html'],description='Own seller description')
            self.assertEqual(c['location'],d.get('itemLocationText'))
            self.assertEqual(c['pickupOnly'],d.get('htmlPickupOnly'))
            item={'title':'PS5 Pro','price':600,'shipping_cost':0,'location':'13***, DE','is_pickup_only':True}
            monitor._refresh_candidate_details(item,d,{})
            self.assertEqual(c['pickupOnly'],item['is_pickup_only'])
            self.assertEqual(c['location'],item['location'])

    def test_oct10_model_selection_shared_with_android(self):
        import json
        from pathlib import Path
        cases = json.loads((Path(__file__).parent/'qa/fixtures/oct10_listing_rules.json').read_text(encoding='utf8'))
        for case in cases:
            with self.subTest(title=case['title']):
                self.assertEqual(case['expected'], monitor._intent_prelim_matches_title(monitor._normalize(case['title']), {'query':case['query']}))

    def test_pickup_rule_is_80km_or_actual_berlin_not_postal_region(self):
        import plz_distance
        for place, expected in [('Berlin, Deutschland',True),('Potsdam',False),('14532 Kleinmachnow',False),('09648 Mittweida',True),('07743 Jena',False),('Abholung möglich',False),('Chemnitz',False)]:
            self.assertEqual(expected,plz_distance.is_nearby(place)[0],place)
        for distance, expected in [(80,True),(80.01,False)]:
            with patch.object(plz_distance,'get_distance_from_location',return_value=(distance,'99999')):
                self.assertEqual(expected,plz_distance.is_nearby('99999 Ort')[0])

    def test_optional_pickup_does_not_remove_real_shipping_price(self):
        html='''<li class="s-card"><a class="s-card__link" href="https://www.ebay.de/itm/198304841229"></a><span class="su-styled-text primary default">Gaming PC RTX 5070 Ti</span><span class="s-card__price">EUR 2.109,00</span><span>Kostenlose Abholung</span><span>Versand: EUR 10,99</span></li>'''
        row=monitor.parse_ebay_results(html)[0]
        self.assertFalse(row['is_pickup_only'])
        self.assertEqual(10.99,row['shipping_cost'])
    def test_real_pc_primary_survives_broad_alias_results_and_a_later_network_failure(self):
        search={'id':'pc','query':'5070 ti (pc, rechner, computer, desktop, gaming pc)',
                'filters':{'category':'computers','listing_type':'buy_now','location':'worldwide','max_price':2500}}
        calls=[]
        def fetch(child,force=False):
            params=monitor._build_ebay_api_params(child)
            calls.append(params)
            if len(calls)==1:
                return [{'item_id':'198304841229','title':'Silent High End Gaming PC - AMD Ryzen 5 5600 - RTX 5070 Ti - 32GB- 1TB','price':2109,'buy_now':True}],None
            return [],'api_network'
        with patch.object(monitor,'EBAY_SOURCE','api'),patch.object(monitor,'fetch_ebay_api_ex',side_effect=fetch),patch.dict(monitor._ebay_query_cache,{},clear=True):
            rows,error=monitor.fetch_ebay_ex(search,force=True)
        self.assertEqual('5070 ti pc',calls[0]['q'])
        self.assertEqual('179',calls[0]['category_ids'])
        self.assertNotIn('category_ids',calls[1])
        self.assertIn('itemLocationRegion:WORLDWIDE',calls[0]['filter'])
        self.assertEqual('198304841229',rows[0]['item_id'])
        self.assertEqual('api_network',error)

    def test_live_pc_with_single_price_is_pickup_not_variation(self):
        html='''<li class="s-card"><a class="s-card__link" href="https://www.ebay.de/itm/800423940260"></a><div class="s-card__title"><span class="su-styled-text primary default">Gaming PC (Rtx5070TI, Ryzen 7 5800x, 32gb DDR4 Ram)</span></div><span class="s-card__price">EUR 1.450,00</span><span>Sofort-Kaufen</span><span>Kostenlose Abholung</span></li>'''
        row=monitor.parse_ebay_results(html)[0]
        self.assertTrue(row['is_pickup_only'])
        self.assertFalse(row['is_multivariation'])
        self.assertEqual(1450,row['price'])
    def test_pickup_station_delivery_is_not_pickup_only(self):
        html='''<li class="s-card"><a class="s-card__link" href="https://www.ebay.de/itm/123456789012"></a><span class="su-styled-text primary default">Gaming PC RTX 5070 Ti</span><span class="s-card__price">EUR 1.450,00</span><span>Gratis Lieferung</span><span>Lieferung an Abholstation möglich</span></li>'''
        self.assertFalse(monitor.parse_ebay_results(html)[0]['is_pickup_only'])
    def test_pc_aliases_include_compact_and_reverse_order_without_changing_model(self):
        for raw,gpu in [('5070 ti (pc, rechner, computer, desktop, gaming pc)','5070ti'),('RTX4080 rechner','4080')]:
            aliases=gpu_pc_aliases(raw)
            self.assertTrue(any(q==f'RTX{gpu.upper()}' for q in aliases))
            self.assertTrue(any(q.startswith('gaming pc ') for q in aliases))
            self.assertTrue(all(len(q)<=100 for q in api_query_batches(aliases)))
            self.assertEqual('gpu_pc',monitor._search_intent({'query':raw})['kind'])
        self.assertIsNone(gpu_pc_aliases('MSI RTX5070TI graphics card'))
    def test_quota_html_uses_separate_queries_and_merges_duplicate_ids(self):
        search={'id':'pc','query':'5070 ti (pc, rechner, computer, desktop, gaming pc)','filters':{'listing_type':'buy_now'}}
        called=[]
        def fetch(child,force=False):
            called.append(child['_query_override'])
            return [{'item_id':'same','price':1450,'buy_now':True}],None
        with patch.object(monitor,'fetch_ebay_ex',side_effect=fetch),patch.object(monitor,'record_search_run'):
            rows,error=monitor._fetch_quota_html(search,force=True)
        self.assertIsNone(error)
        self.assertEqual(monitor._search_query_variants(search),called)
        self.assertFalse(any('(' in q for q in called))
        self.assertEqual(1,len(rows))
    def test_html_partial_failure_stays_visible_and_stops_requests(self):
        search={'query':'nubia z80 ultra leading','filters':{}}
        # Call the actual dispatcher; child calls are intercepted at the HTTP layer.
        original=monitor.fetch_ebay_ex
        calls=[]
        def child(s,force=False):
            if s.get('_variant_child'):
                calls.append(s['_query_override'])
                return ([{'item_id':'one','price':500,'buy_now':True}],None) if len(calls)==1 else ([], 'blocked')
            return original(s,force)
        with patch.object(monitor,'EBAY_SOURCE','html'),patch.object(monitor,'fetch_ebay_ex',side_effect=child):
            rows,error=original(search,force=True)
        self.assertEqual('blocked',error)
        self.assertEqual(1,len(rows))
        self.assertEqual(2,len(calls))

    def test_phone_aspect_retains_the_ebay_specific_nested_encoding(self):
        from urllib.parse import urlsplit,parse_qs
        with patch.object(monitor.config,'get_settings',return_value={}):
            url=monitor._build_url_with_host('ebay.de',{'query':'iPhone 16 Pro Max','filters':{'category':'phones'}})
        self.assertEqual(['Apple%20iPhone%2016%20Pro%20Max'],parse_qs(urlsplit(url).query)['Modell'])
        self.assertIn('Apple%2520iPhone%252016%2520Pro%2520Max',url)
    def test_hybrid_has_one_bid_bucket_and_its_separate_bin_price(self):
        row={'item_id':'hybrid','buy_now':True,'auction':True,'best_offer':True,'price':100,'total_price':106,'auc_price':100,'auc_total_price':106,'bin_price':1500,'bin_total_price':1506}
        bins,offers,auctions,auc_offers=monitor.split_statistics_buckets([row])
        self.assertFalse(bins);self.assertFalse(auc_offers)
        self.assertEqual(1506,offers[0]['total_price']);self.assertEqual(106,auctions[0]['total_price'])
        self.assertFalse(auctions[0]['best_offer']);self.assertTrue(row['buy_now'])
    def test_offer_auction_never_duplicates_merely_because_it_ends_soon(self):
        row={'item_id':'offer','buy_now':False,'auction':True,'best_offer':True,'bids_count':0,'time_left':'2ч','price':100,'total_price':106}
        split=monitor.split_statistics_buckets([row]);self.assertFalse(split[2]);self.assertEqual(1,len(split[3]))
        row['bids_count']=2
        split=monitor.split_statistics_buckets([row]);self.assertEqual(1,len(split[2]));self.assertFalse(split[3])

    def test_same_complete_live_seller_inputs_as_android(self):
        import json
        from pathlib import Path
        cases=json.loads((Path(__file__).parent/'qa/fixtures/cloud_search_details_2026-10-08.json').read_text(encoding='utf8'))
        for case in cases:
            with self.subTest(item=case['id']):
                details=case['details']
                # Project the current own-price format; do not use a stale SERP price.
                auction='AUCTION' in details['buyingOptions']
                price=float((details.get('currentBidPrice') if auction else details['price'])['value'])
                item={'item_id':case['id'],'title':details['title'],'price':price,'auction':auction,'buy_now':not auction}
                search={'query':case['query'],'filters':{'category':case['category']}}
                # This snapshot asserts model/description at its captured time,
                # rather than becoming a sold-listing test when the clock advances.
                from datetime import datetime
                observed=datetime.fromisoformat(case['observedAtUtc'].replace('Z','+00:00'))
                def remaining(end):
                    return (datetime.fromisoformat(end.replace('Z','+00:00'))-observed).total_seconds() if end else None
                with patch.object(monitor,'_parse_end_date_to_seconds',side_effect=remaining):
                    self.assertEqual(case['expected'],monitor._details_match_contract(item,search,details))

    def test_spaced_fake_sale_declaration_preserves_negations_and_warnings(self):
        for body in ['Ich verkaufe diese ausschließlich als F A K E.', 'Das sind F A K E -- I Phones.', 'This is a fake iPhone.']:
            self.assertTrue(monitor._phone_description_declares_fake(body),body)
        for body in ['Das ist kein Fake iPhone.', 'This is not a fake iPhone.', 'Vorsicht vor Fake Angeboten. Mein iPhone ist original.', 'Ich verkaufe es nicht als Fake.']:
            self.assertFalse(monitor._phone_description_declares_fake(body),body)

    def test_iframe_head_cannot_make_a_placeholder_or_prefix_a_wrong_mouse_model(self):
        self.assertEqual('',monitor._clean_description('<html><head><title>eBay</title></head><body>N/a</body></html>'))
        self.assertEqual('Logitech G PRO 2 LIGHTSPEED',monitor._clean_description('<html><head><title>eBay</title></head><body>Logitech G PRO 2 LIGHTSPEED</body></html>').strip())
    def test_nubia_model_aspect_can_omit_brand_but_not_generation_or_variant(self):
        self.assertTrue(monitor._phone_model_aspect_matches('Z80 Ultra','Nubia Z80 Ultra'))
        for other in ['Z70 Ultra','Z80 Ultra Leading','Z70S Ultra']:
            self.assertFalse(monitor._phone_model_aspect_matches(other,'Nubia Z80 Ultra'))

    def test_pc_design_lines_are_not_display_defects_but_actual_panel_lines_remain(self):
        style='Minimalistisches Design – Hochwertige Materialien, klare Linien.'
        self.assertFalse(monitor._is_description_blocked(style,'computers'))
        self.assertTrue(monitor._is_description_blocked(style+' Das Display hat Linien.','computers'))
        self.assertTrue(monitor._is_description_blocked('Das Display hat klare Linien.','computers'))

    def test_conflicting_nubia_z17mini_model_is_not_an_unknown_aspect(self):
        self.assertFalse(monitor._phone_model_aspect_matches('Nubia Z17mini','Nubia Z70 Ultra'))
        self.assertFalse(monitor._phone_model_aspect_matches('Nubia Z17 mini','Nubia Z70 Ultra'))
        self.assertFalse(monitor._phone_model_aspect_matches('Nubia Z17lite','Nubia Z70 Ultra'))
        self.assertTrue(monitor._phone_model_aspect_matches('Z70 Ultra','Nubia Z70 Ultra'))
