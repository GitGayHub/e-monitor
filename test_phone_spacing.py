import unittest
import monitor
from test_search_intent_rules import item, DummyConfig


class PhoneSpacingTest(unittest.TestCase):
    def test_live_split_iphone_brand_is_not_a_missing_model(self):
        # Browser-read 960092888408: full handset, Model=iPhone17ProMax,
        # own says warranty/receipt, case and screen protector, no scratches.
        title = 'I Phone 17 Pro Max 512 GB Silber Garantie'
        query = 'iphone 17 pro max'
        for auction, offer in [(False, False), (False, True), (True, False), (True, True)]:
            row = item(title, price=555.55, auction=auction, buy_now=not auction, best_offer=offer)
            search = {'query': query, 'filters': {'category': 'phones', 'listing_type': 'all'}}
            self.assertTrue(monitor.filter_results([row], search, DummyConfig(), skip_seen=True, is_statistics=True))
        self.assertTrue(monitor._phone_model_aspect_matches(title, query))

    def test_spacing_preserves_wrong_generation_conversion_and_accessories(self):
        for title in ['I Phone 15 Pro Max 256GB iOS 17',
                      'I Phone XS Max in I Phone 17 Pro Max Style',
                      'I Phone 17 Pro 512GB',
                      'I Phone 17 Pro Max 512GB Converter',
                      'Display für I Phone 17 Pro Max']:
            row = item(title)
            search = {'query': 'iphone 17 pro max', 'filters': {'category': 'phones', 'listing_type': 'all'}}
            self.assertFalse(monitor.filter_results([row], search, DummyConfig(), skip_seen=True, is_statistics=True), title)

    def test_split_brand_preserves_complete_bundle_purpose(self):
        self.assertFalse(monitor._is_phone_accessory_title(monitor._normalize('I Phone 17 Pro Max 512GB mit Case und Schutzfolie')))
        self.assertTrue(monitor._is_phone_accessory_title(monitor._normalize('Case für I Phone 17 Pro Max 512GB')))
        self.assertEqual('i phone my mother',monitor._normalize('I phone my mother'))
        self.assertFalse(monitor._is_phone_accessory_title(monitor._normalize('Apple iPhone 17 Pro Max 1TB Orange ohne Risse im Display')))

    def test_split_brand_in_own_description_does_not_hide_wrong_model(self):
        self.assertIsNotNone(monitor._phone_own_model_conflict('Ich verkaufe mein I Phone 15 Pro Max.', 'iphone 17 pro max'))
        self.assertIsNone(monitor._phone_own_model_conflict('Ich verkaufe mein I Phone 17 Pro Max.', 'iphone 17 pro max'))
