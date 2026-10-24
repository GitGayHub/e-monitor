import unittest
import json
from pathlib import Path
import monitor

class CountryLocationTests(unittest.TestCase):
    def test_pickup_map_code_between_city_and_postal_code(self):
        for location,expected in [('Brand-Erbisdorf DE 09618','DE'),('Brand-Erbisdorf DE09618','DE'),('London GB SW1A','GB'),('London UK SW1A','GB'),('Brand-Erbisdorf, Deutschland','DE'),('Berlin, DE','DE'),('de','DE'),('Val de Loire, France','FR'),('Val de Loire',None),('Denver',None),('',None)]:
            with self.subTest(location=location):self.assertEqual(expected,monitor._country_code_from_location(location))
        self.assertEqual('🇩🇪 Германия',monitor._format_country_for_notification('Brand-Erbisdorf DE 09618'))

    def test_country_region_preserves_unknowns_and_explicit_codes(self):
        rows=json.loads((Path(__file__).parent/'qa/fixtures/country_region_oct24.json').read_text(encoding='utf8'))
        for row in rows:
            with self.subTest(case=row['id']):
                self.assertEqual(row['code'],monitor._country_code_from_location(row['location']))
                self.assertEqual(row['eu'],monitor._is_eu(row['location']))
                self.assertEqual(row['code'] is None,monitor._format_country_for_notification(row['location'])=='Не указано')

    def test_refreshed_country_controls_import_estimate_and_region(self):
        class Settings:
            def get_global_banned_sellers(self):return []
            def get_banned_item_ids(self):return set()
            def get_item_hashes(self):return set()
            def get_settings(self):return dict(warn_non_eu=True,non_eu_tax_rate=0.19,user_zip='09648')
        rows=json.loads((Path(__file__).parent/'qa/fixtures/country_region_oct24.json').read_text(encoding='utf8'))
        for row in rows:
            with self.subTest(case=row['id']):
                title='Apple iPhone 17 Pro Max 256GB'
                item=dict(item_id=row['id'],title=title,price=100.0,shipping_cost=6.19,currency='EUR',condition='Gebraucht',location='',seller_name='fixture',buy_now=True,auction=False,best_offer=False)
                details=dict(title=title,description='Voll funktionsfähig.',itemLocationText=row['location'],htmlShippingCost=6.19,price=dict(value=100.0,currency='EUR'))
                monitor._calculate_total(item,Settings().get_settings(),details)
                self.assertEqual(106.19 if row['eu'] or not row['location'] else 135.61,item['total_price'])
                self.assertEqual(row['code'],monitor._country_code_from_location(item['location']))
                search=dict(query='iphone 17 pro max',filters=dict(category='phones',location='de',limit_price=1000))
                self.assertEqual(row['code'] in (None,'DE'),bool(monitor.filter_results([item],search,Settings(),skip_seen=True,is_statistics=True)))
                search['filters']['location']='eu'
                self.assertEqual(row['eu'],bool(monitor.filter_results([item],search,Settings(),skip_seen=True,is_statistics=True)))

