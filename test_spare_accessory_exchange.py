import json, unittest
from pathlib import Path
import monitor


class SpareAccessoryExchangeTests(unittest.TestCase):
    def test_included_accessories_are_not_a_device_swap_or_repair(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/spare_accessory_exchange_oct19.json').read_text(encoding='utf8'))['cases']
        for case in cases:
            with self.subTest(id=case['id']):
                self.assertEqual(case['blocked'],monitor._is_description_blocked(case['description'],'all'))

    def test_whole_glasses_keep_spare_lenses_in_all_four_formats(self):
        title='Ray-Ban Meta Gen 2 Smart Glasses'
        text='Die Ray-Ban Meta Gen 2 wird vollständig und funktionsfähig verkauft. 3 Paar Gläser sind noch dabei zum Tauschen oder als Ersatz!'
        for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
            search=dict(query='Ray-Ban Meta Gen 2',filters=dict(category='all',listing_type=listing,best_offer=offer))
            for fault in ('',' Die Brille ist defekt.'):
                with self.subTest(listing=listing,offer=offer,fault=bool(fault)):
                    details=dict(title=title,description=text+fault,categoryId='79720',condition='Gebraucht - Hervorragend')
                    self.assertEqual(not fault,bool(monitor._details_match_contract(dict(item_id='327406280485',title=title),search,details)))
