import json,unittest
from pathlib import Path
import monitor
class PhoneSalesObjectTests(unittest.TestCase):
    def test_battery_health_purpose_and_own_handset_confirmation(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_battery_health_oct19.json').read_text(encoding='utf8'))['cases']
        for c in cases:
            for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
                with self.subTest(id=c['id'],listing=listing,offer=offer):
                    title=monitor._normalize(c['title'])
                    self.assertEqual(c['accessory'],monitor._is_phone_accessory_title(title))
                    self.assertEqual(c['confirmed'],monitor._phone_implicit_bundle_confirmed(title,c['description']))
                    details=dict(title=c['title'],description=c['description'],categoryId='9355',condition='Gebraucht')
                    if c['ram']:
                        details['localizedAspects']=[dict(name='RAM',value=c['ram'])]
                    search=dict(query=c['query'],filters=dict(category='phones',listing_type=listing,best_offer=offer))
                    # The title filter is a separate gate before own details.
                    accepted=not c['accessory'] and monitor._details_match_contract(dict(item_id=c['id'],title=c['title']),search,details)
                    self.assertEqual(c['accepted'],bool(accepted))
    def test_whole_handset_sales_and_accessory_objects_in_four_formats(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_sales_object_oct18.json').read_text(encoding='utf8'))['cases']
        for c in cases:
            for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
                with self.subTest(id=c['id'],listing=listing,offer=offer):
                    details=dict(title=c['title'],description=c['description'],categoryId='9355',condition='Gebraucht')
                    search=dict(query=c['query'],filters=dict(category='phones',listing_type=listing,best_offer=offer))
                    self.assertEqual(c['accepted'],bool(monitor._details_match_contract(dict(item_id=c['id'],title=c['title']),search,details)))
