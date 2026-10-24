import json
import unittest
from pathlib import Path
import monitor

class Settings:
    def get_global_banned_sellers(self):return []
    def get_banned_item_ids(self):return set()
    def get_item_hashes(self):return set()
    def get_settings(self):return dict(user_zip='09648',warn_non_eu=False)

class MouseOfferTests(unittest.TestCase):
    def test_common_complete_mouse_and_conflicting_own_models(self):
        rows=json.loads((Path(__file__).parent/'qa/fixtures/mouse_offer_oct24.json').read_text(encoding='utf8'))
        for row in rows:
            for category,auction,best_offer in ((c,a,b) for c in ('all','mice') for a,b in ((False,False),(False,True),(True,False),(True,True))):
                with self.subTest(case=row['id'],category=category,auction=auction,best_offer=best_offer):
                    search=dict(query=row['query'],exclude_words=row.get('excludeWords',[]),filters=dict(category=category,listing_type='auction' if auction else 'buy_now',best_offer=best_offer,limit_price=1000))
                    item=dict(item_id=row['id'],title=row['title'],price=500.0,shipping_cost=0.0,currency='EUR',condition='Gebraucht',seller_name='fixture',location='DE',buy_now=not auction,auction=auction,best_offer=best_offer,time_left='1 Std')
                    details=dict(title=row['title'],description=row['description'],condition='Gebraucht',price=dict(value=500,currency='EUR'))
                    kept=bool(monitor.filter_results([item],search,Settings(),skip_seen=True,is_statistics=True))
                    actual=kept and monitor._details_match_contract(item,search,details)
                    self.assertEqual(row['expected'],bool(actual))
