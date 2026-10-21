import json,unittest
from pathlib import Path
import monitor

class ManufacturerWarrantyTests(unittest.TestCase):
    def test_service_policy_and_real_faults_in_every_format(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/manufacturer_warranty_oct21.json').read_text(encoding='utf8'))
        for c in cases:
            for auction in (False,True):
                for offer in (False,True):
                    with self.subTest(case=c['id'],auction=auction,offer=offer):
                        d=dict(title=c['title'],description=c['description'],categoryId='80053',condition='Neu',price=dict(value='350',currency='EUR'),buyingOptions=(['AUCTION'] if auction else ['FIXED_PRICE'])+(['BEST_OFFER'] if offer else []),itemEndDate='2099-01-01T00:00:00Z')
                        if auction:d['currentBidPrice']=dict(value='350',currency='EUR')
                        result=monitor._details_match_contract(dict(item_id='123456789001',title=c['title']),dict(query=c['query'],filters=dict(category='monitors',listing_type='all')),d)
                        self.assertEqual(c['expected'],bool(result))
