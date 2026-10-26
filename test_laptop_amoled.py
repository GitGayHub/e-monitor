import copy,json,unittest
from pathlib import Path
import monitor
from test_samsung_monitor_sku import Settings

class LaptopAmoledTests(unittest.TestCase):
    def test_oled_search_accepts_amoled_without_accepting_parts_wrong_gpu_or_defects(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/laptop_amoled_oct26.json').read_text(encoding='utf8'))['cases']
        for case in cases:
            for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
                with self.subTest(case=case['id'],listing=listing,offer=offer):
                    search=dict(query=case['query'],filters=dict(category='laptops',listing_type=listing,best_offer=offer,limit_price=1000,location='de'))
                    item=dict(item_id=case['id'],title=case['title'],price=500,shipping_cost=0,currency='EUR',condition='Gebraucht',location='DE',seller_name='fixture',buy_now=listing=='buy_now',auction=listing=='auction',best_offer=offer,time_left='1h')
                    details=dict(title=case['title'],description=case['description'],categoryId='177',condition='Gebraucht')
                    accepted=bool(monitor.filter_results([copy.deepcopy(item)],search,Settings(),skip_seen=True,is_statistics=True)) and monitor._details_match_contract(item,search,details)
                    self.assertEqual(case['expected'],accepted)
