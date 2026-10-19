import json,unittest
from pathlib import Path
import monitor
class PhoneSalesObjectTests(unittest.TestCase):
    def test_whole_handset_sales_and_accessory_objects_in_four_formats(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_sales_object_oct18.json').read_text(encoding='utf8'))['cases']
        for c in cases:
            for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
                with self.subTest(id=c['id'],listing=listing,offer=offer):
                    details=dict(title=c['title'],description=c['description'],categoryId='9355',condition='Gebraucht')
                    search=dict(query=c['query'],filters=dict(category='phones',listing_type=listing,best_offer=offer))
                    self.assertEqual(c['accepted'],bool(monitor._details_match_contract(dict(item_id=c['id'],title=c['title']),search,details)))
