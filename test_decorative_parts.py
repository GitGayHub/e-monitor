import json, unittest
from pathlib import Path
import monitor

class DecorativePartsTests(unittest.TestCase):
    def cases(self):
        return json.loads((Path(__file__).parent/'qa/fixtures/decorative_parts_oct20.json').read_text(encoding='utf8'))['cases']

    def test_titles_distinguish_parts_and_bundles(self):
        for c in self.cases():
            if c['id'] in ('misleading-title','broken-bundle','no-description','includes-only-tags','device-not-included'):continue
            with self.subTest(id=c['id']):
                self.assertEqual(not c['expected'],monitor._is_category_blocked_title(monitor._normalize(c['title']),c['category']))

    def test_own_purpose_overrides_misleading_mouse_specs_in_every_format(self):
        for c in self.cases():
            for listing,offer in [('buy_now',False),('buy_now',True),('auction',False),('auction',True)]:
                with self.subTest(id=c['id'],listing=listing,offer=offer):
                    details=dict(title=c['title'],description=c['description'],condition='Neu',categoryId='23160' if c['category']=='mice' else '112529',localizedAspects=[dict(name='Produktart',value='Gaming-Maus' if c['category']=='mice' else 'Headset')])
                    search=dict(query=c['query'],filters=dict(category=c['category'],listing_type=listing,best_offer=offer))
                    self.assertEqual(c['expected'],bool(monitor._details_match_contract(dict(item_id=c['id'],title=c['title']),search,details)))
