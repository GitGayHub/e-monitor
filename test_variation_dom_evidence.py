"""Shared HTML evidence: styles/scripts do not make a single item a variant."""
import copy
import json
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import monitor
from test_search_intent_rules import item


class VariationDomEvidenceTests(unittest.TestCase):
    def cases(self):
        return json.loads((Path(__file__).parent / 'qa/fixtures/variation_dom_evidence.json').read_text())

    def parse(self, fragment):
        return monitor._parse_item_details_html(
            '<h1 class="x-item-title">Sony ULT Wear Kopfhörer</h1>'
            '<div class="x-price-primary">EUR 79,50</div>' + fragment,
            description='Complete, fully working Sony ULT Wear headphones with case.')

    def test_only_actual_dom_markers_indicate_variations(self):
        for case in self.cases():
            with self.subTest(case['name']):
                d = self.parse(case['html'])
                self.assertEqual(case['variation'], d.get('itemGroupType') == 'SELLER_DEFINED_VARIATIONS')

    def test_single_device_and_true_variants_follow_all_four_formats(self):
        for case in self.cases():
            for listing, offer in [('buy_now', False), ('buy_now_offer', True), ('auction', False), ('auction', True)]:
                with self.subTest(case['name'], listing=listing, offer=offer):
                    d = self.parse(case['html'])
                    d['buyingOptions'] = ['AUCTION' if listing == 'auction' else 'FIXED_PRICE'] + (['BEST_OFFER'] if offer else [])
                    s = {'id': 'qa', 'query': 'sony ult wear', 'filters': {'category': 'headphones', 'listing_type': listing}}
                    row = item(d['title'], price=79.5, auction=listing == 'auction', buy_now=listing != 'auction', best_offer=offer)
                    self.assertEqual(not case['variation'], monitor._details_match_contract(row, s, d))

    def test_css_does_not_bypass_missing_description_or_wrong_device(self):
        s = {'id': 'qa', 'query': 'sony ult wear', 'filters': {'category': 'headphones'}}
        d = self.parse('<style>.vim.rx-msku-evo {display:flex}</style>')
        for body in ['', 'Sony ULT Wear. The hinge is broken.', 'Sony WH-1000XM6 headphones, fully working.']:
            changed = copy.deepcopy(d)
            changed['description'] = body
            self.assertFalse(monitor._details_match_contract(item(d['title'], price=79.5), s, changed), body)

    def test_legacy_probe_also_ignores_css_and_retains_real_selectors(self):
        for case in self.cases():
            session = Mock()
            session.get.return_value = Mock(status_code=200, text=case['html'])
            with patch.object(monitor, '_get_ebay_session', return_value=session):
                self.assertEqual(case['variation'], monitor._is_item_page_multivariation('123456789001'), case['name'])

    def test_private_original_html_when_provided(self):
        path = os.environ.get('EMONITOR_QA_VARIATION_INPUTS')
        if not path:
            return  # Private originals never become public fixtures/artifacts.
        for case in json.loads(Path(path).read_text()):
            html = Path(case['htmlPath']).read_text()
            own = Path(case['descriptionPath']).read_text()
            d = monitor._parse_item_details_html(html, description=own, item_id=case['itemId'])
            self.assertNotEqual('SELLER_DEFINED_VARIATIONS', d.get('itemGroupType'), case['itemId'])
            s = {'id': 'qa', 'query': 'sony ult wear', 'filters': {'category': 'headphones'}}
            row = item(d['title'], item_id=case['itemId'], price=float(d['price']['value']))
            self.assertTrue(monitor._details_match_contract(row, s, d, now=datetime.fromisoformat(case['observedAtUtc'])), case['itemId'])
