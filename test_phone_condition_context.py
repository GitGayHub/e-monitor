import json,unittest
from pathlib import Path
import monitor

class PhoneConditionContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_condition_context_oct18.json').read_text(encoding='utf8'))['cases']

    def test_seller_denials_and_completed_repair_have_independent_reasons(self):
        for c in self.cases:
            with self.subTest(id=c['id']):
                self.assertEqual(c['blocked'],monitor._is_description_blocked(c['description'],'phones'))
                self.assertEqual(c['repair'],monitor._phone_repair_label(c['description']) is not None)

    def test_same_clauses_in_four_formats(self):
        for c in self.cases:
            title=c.get('title','Samsung Galaxy S24 Ultra 256GB Smartphone')
            for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
                with self.subTest(id=c['id'],listing=listing,offer=offer):
                    d=dict(title=title,description=c['description'],categoryId='9355',condition='Gebraucht')
                    search=dict(query='samsung s24 ultra',filters=dict(category='phones',listing_type=listing,best_offer=offer))
                    self.assertEqual(c.get('contractAccepted',not c['blocked']),bool(monitor._details_match_contract(dict(item_id=c['id'],title=title),search,d)))
