import unittest

import monitor


class DetailsFilterTest(unittest.TestCase):
    def test_description_noise_does_not_block_valid_phone_metadata(self):
        search = {"query": "iPhone 15 Pro Max", "filters": {"category": "phones"}}
        details = {
            "title": "Apple iPhone 15 Pro Max Schwarz 256GB",
            "categoryName": "Handys & Smartphones",
            "itemLocationText": "Deutschland",
            "description": "<div>Andere kauften auch: iPhone 15 Pro Max Display Schaden</div>",
        }

        self.assertFalse(monitor._is_details_blocked(details, search))

    def test_phone_part_title_still_blocks(self):
        search = {"query": "iPhone 15 Pro Max", "filters": {"category": "phones"}}
        details = {
            "title": "iPhone 15 Pro Max Bildschirm",
            "categoryName": "Handys & Smartphones",
            "itemLocationText": "Deutschland",
        }

        self.assertTrue(monitor._is_details_blocked(details, search))


if __name__ == "__main__":
    unittest.main()
