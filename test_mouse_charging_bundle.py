import unittest,json
from pathlib import Path
import monitor
from test_mouse_feature_context import Settings

class MouseChargingBundleTests(unittest.TestCase):
    def test_charging_mat_with_whole_mouse_not_separate_parts(self):
        rows=json.loads((Path(__file__).parent/'qa/fixtures/mouse_charging_bundle.json').read_text(encoding='utf8'))
        for row in rows:
            with self.subTest(case=row['id']):
                search=dict(query=row['query'],exclude_words=['charging'],filters=dict(category='mice',limit_price=1000))
                item=dict(item_id='fixture',title=row['title'],price=500,shipping_cost=0,currency='EUR',condition='Gebraucht',location='DE',seller_name='fixture',buy_now=True,auction=False,best_offer=False)
                self.assertEqual(row['expected'],bool(monitor.filter_results([item],search,Settings(),skip_seen=True,is_statistics=True)))
