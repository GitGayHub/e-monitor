import unittest,json
from pathlib import Path
import monitor

class Settings:
    def get_global_banned_sellers(self):return []
    def get_banned_item_ids(self):return set()
    def get_item_hashes(self):return set()
    def get_settings(self):return dict(warn_non_eu=False,user_zip='09648')

class MouseFeatureContextTests(unittest.TestCase):
    def test_whole_device_features_do_not_hide_actual_parts(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/mouse_feature_context.json').read_text(encoding='utf8'))
        for row in cases:
            with self.subTest(case=row['id']):
                search=dict(query=row['query'],exclude_words=row.get('excludeWords',[]),filters=dict(category='mice',limit_price=1000))
                item=dict(item_id='fixture',title=row['title'],price=500,shipping_cost=0,currency='EUR',condition='Gebraucht',location='DE',seller_name='fixture',buy_now=True,auction=False,best_offer=False)
                self.assertEqual(row['expected'],bool(monitor.filter_results([item],search,Settings(),skip_seen=True,is_statistics=True)))
