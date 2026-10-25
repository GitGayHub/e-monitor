import json
import unittest
from pathlib import Path
import monitor

class MouseReplacementConditionTests(unittest.TestCase):
    def test_prior_fault_is_not_current_device_fault(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/mouse_replacement_condition.json').read_text(encoding='utf8'))
        search=dict(query='logitech superlight 2 dex',filters=dict(category='mice',limit_price=1000))
        item=dict(item_id='fixture',title='Logitech PRO X Superlight 2 DEX Gaming Maus',price=500,shipping_cost=0,currency='EUR')
        for row in cases:
            with self.subTest(case=row['id']):
                details=dict(title=item['title'],condition='Neu',description=row['description'])
                self.assertEqual(row['expected'],bool(monitor._details_match_contract(item,search,details)))
