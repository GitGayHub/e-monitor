from pathlib import Path
import json, unittest
import monitor

class ImageOnlyOfferTest(unittest.TestCase):
    def test_shared_image_purpose_and_real_console_contract(self):
        rows=json.loads((Path(__file__).parent/'qa/fixtures/image_only_oct24.json').read_text())['cases']
        for row in rows:
            with self.subTest(id=row['id']):
                self.assertEqual(row['imageTitle'],monitor._image_only_title(row['title']))
                self.assertEqual(row['imageBody'],monitor._image_only_body(row['body']))
        for title,body in [(rows[0]['title'],rows[0]['body']),(rows[1]['title'],rows[1]['body'])]:
            with self.subTest(title=title):
                self.assertFalse(monitor._details_match_contract(dict(item_id='image-control',title=title),dict(query='ps5 pro',filters=dict(category='consoles',listing_type='all')),dict(title=title,description=body,categoryId='139971',condition='Neu')))
