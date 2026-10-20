import unittest
import monitor

class MouseOffer126Tests(unittest.TestCase):
    def test_own_mpn_excludes_se_even_when_title_omits_it(self):
        for code in ('007555','007556','007646','007651'):
          for part in ('910-'+code,'910 '+code):
            d=dict(title='Logitech G PRO X Superlight 2 Gaming Maus',description='Complete working mouse.',localizedAspects=[dict(name='Herstellernummer',value=part)])
            self.assertFalse(monitor._mouse_part_number_matches(d,'superlight 2'))
            self.assertFalse(monitor._mouse_part_number_matches(d,'superlight 2c'))
            self.assertFalse(monitor._mouse_part_number_matches(d,'superlight 2 dex'))
            self.assertTrue(monitor._mouse_part_number_matches(d,'superlight 2 se'))

    def test_legacy_required_compact_words_are_an_intent_not_a_new_standard_mouse(self):
        search=dict(query='logitech superlight 2',include_words=['2c','2 c','compact'],filters=dict(category='mice'))
        self.assertEqual('logitech superlight 2c',monitor._intent_query(search))
        self.assertTrue(all('2c' in q for q in monitor._search_query_variants(search)))
        self.assertEqual('logitech superlight 2',monitor._intent_query(dict(query=search['query'],include_words=['black'],filters=dict(category='mice'))))
        self.assertEqual('logitech superlight 2',monitor._intent_query(dict(query=search['query'],include_words=['2c','wireless'],filters=dict(category='mice'))))
        for model,expected in [('Logitech Superlight 2c',True),('Logitech Superlight 2',False),('Logitech Superlight 2 DEX',False)]:
            details=dict(title=model,description='Complete working '+model+' mouse.')
            self.assertEqual(expected,bool(monitor._details_match_contract(dict(title=model,item_id='fixture'),search,details)))

    def test_shipping_and_import_eur_quotes_stay_in_their_own_field(self):
        prefix='<h1 class="x-item-title">Logitech Superlight 2</h1><div class="x-price-primary">EUR 14,11</div>'
        for modules in (True,False):
            shipping='<span>Versand:</span><span>£12,16</span><span>(ca. EUR 14,42)</span>'
            imports='<span>Einfuhrgebühren:</span><span>Ca. EUR 3,57</span>'
            html=prefix+(f'<div class="ux-labels-values--shipping">{shipping}</div><div class="ux-labels-values--importCharges">{imports}</div>' if modules else shipping+imports)
            d=monitor._parse_item_details_html(html,description='Complete working mouse.')
            self.assertAlmostEqual(14.42,float(d['htmlShippingCost']['value']))
            self.assertAlmostEqual(3.57,float(d['htmlImportCharges']['value']))

    def test_unknown_paid_shipping_cannot_borrow_imports(self):
        html='<div class="x-price-primary">EUR 14,11</div><div class="ux-labels-values--shipping">Versand: Kostenpflichtig, Preis beim Verkäufer erfragen.</div><div class="ux-labels-values--importCharges">Einfuhrgebühren: EUR 3,57</div>'
        d=monitor._parse_item_details_html(html,description='Complete working mouse.')
        self.assertIsNone(d.get('htmlShippingCost'))
        self.assertFalse(monitor._provider_details_complete(d))
