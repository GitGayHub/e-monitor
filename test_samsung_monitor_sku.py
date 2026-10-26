import copy,json,unittest
from pathlib import Path
import monitor

class Settings:
    def get_global_banned_sellers(self):return []
    def get_banned_item_ids(self):return set()
    def get_item_hashes(self):return set()
    def get_settings(self):return {'warn_non_eu':False,'user_zip':'09648'}

class SamsungMonitorSkuTests(unittest.TestCase):
    def test_short_and_full_codes_preserve_whole_device_rules_in_four_formats(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/samsung_monitor_sku_oct26.json').read_text(encoding='utf8'))['cases']
        for case in cases:
            for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
                with self.subTest(case=case['id'],listing=listing,offer=offer):
                    search={'query':'samsung odyssey oled g6 500hz','filters':{'category':'monitors','listing_type':listing,'best_offer':offer,'limit_price':1000,'location':'de'}}
                    item={'item_id':case['id'],'title':case['title'],'price':500,'shipping_cost':0,'currency':'EUR','condition':'Gebraucht','location':'DE','seller_name':'fixture','buy_now':listing=='buy_now','auction':listing=='auction','best_offer':offer,'time_left':'1h'}
                    details={'title':case['title'],'description':case['description'],'categoryId':'80053','condition':'Gebraucht'}
                    accepted=bool(monitor.filter_results([copy.deepcopy(item)],search,Settings(),skip_seen=True,is_statistics=True)) and monitor._details_match_contract(item,search,details)
                    self.assertEqual(case['expected'],accepted)
