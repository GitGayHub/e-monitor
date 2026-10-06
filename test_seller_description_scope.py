"""Actual merchant template 206565005609 contains a product_crosssell block."""
import unittest
import json
from pathlib import Path
import monitor


class SellerDescriptionScopeTest(unittest.TestCase):
    def test_actual_samsung_negation_legal_tab_and_ips_model(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/samsung_manual_details.json').read_text(encoding='utf-8'))
        search={'query':'samsung odyssey oled g6 500hz','filters':{'category':'monitors'}}
        for case in cases:
            self.assertEqual(case['expected'],monitor._details_match_contract({'title':case['title']},search,case),case['id'])

    def test_explicit_negation_in_title_metadata_and_description_preserves_later_faults(self):
        search={'query':'lg ultragear oled 480hz','filters':{'category':'monitors'}}
        title='LG UltraGear OLED 27GX790A-B 480Hz'
        cases=(
            ('ohne Kratzer oder Pixelfehler','pixelfehler',False),
            ('Keine Kratzer am Display und keine Pixelfehler','pixelfehler',False),
            ('kein Burn-in und keine Pixelfehler','burn-in',False),
            ('ohne sichtbare Pixelfehler','pixelfehler',False),
            ('keine Kratzer, keine Burn ins oder sonst andere Mängel','burn in',False),
            ('Burn ins vorhanden, sonst keine Mängel','burn ins',True),
            ('Burn-Ins vermieden werden können','burn ins',False),
            ('Burn-in vorhanden. Burn-Ins vermieden werden können','burn in',True),
            ('ohne Pixelfehler, Display defekt','defekt',True),
            ('nicht defekt, aber Pixelfehler vorhanden','pixelfehler',True),
            ('nicht nicht defekt','defekt',True),
        )
        for phrase,word,expected in cases:
            with self.subTest(phrase=phrase):
                self.assertEqual(expected,monitor._is_details_blocked({'title':title,'shortDescription':phrase},search))
                self.assertEqual(expected,monitor._is_description_blocked(phrase,'monitors'))
                self.assertEqual(expected,monitor._is_category_blocked_title(monitor._normalize(title+' '+phrase),'monitors'))
                self.assertEqual(expected,monitor._exclude_word_hits(monitor._normalize(title+' '+phrase),word))

    def test_missing_description_placeholders_are_not_product_evidence(self):
        for value in ('N/a','<p>N/a</p>','N.A.','No description available','Keine Beschreibung vorhanden','Beschreibung folgt','...'):
            self.assertEqual('',monitor._clean_description(value).strip())
        self.assertTrue(monitor._clean_description('LG UltraGear 27GX790A-B OLED Gaming Monitor 480Hz.').strip())

    def test_actual_samsung_legal_tab_is_not_an_item_defect(self):
        case=json.loads((Path(__file__).parent/'qa/fixtures/samsung_seller_legal_tab.json').read_text(encoding='utf-8'))
        text=monitor._clean_description(case['description'])
        self.assertIn('500 Hz',text)
        self.assertNotIn('Bring-in-Garantie muss',text)
        self.assertFalse(monitor._is_description_blocked(case['description'],'monitors'))
        own_fault='<div>Der angebotene Monitor ist defekt.</div>'+case['description']
        self.assertTrue(monitor._is_description_blocked(own_fault,'monitors'))

    def test_actual_mouse_template_excludes_testimonials_for_a_headset(self):
        case = json.loads((Path(__file__).parent/'qa/fixtures/merchant_manual_description.json').read_text(encoding='utf-8'))
        text = monitor._clean_description(case['description'])
        self.assertNotIn('Das sagen unsere Kunden',text)
        self.assertNotIn('Habe das Headset',text)
        self.assertIn('HERO 2',text)
        self.assertIn('LIGHTFORCE',text)
        html = '<section>Maus voll funktionsfähig.</section><div class="testimonials"><h2>DAS SAGEN UNSERE KUNDEN</h2>Mein Display ist defekt, OLED funktioniert nicht.</div>'
        self.assertFalse(monitor._is_description_blocked(html,'mice'))

    def test_other_products_cannot_supply_missing_oled_or_device_damage(self):
        html = '<section>ASUS Notebook RTX 4050. Funktioniert einwandfrei.</section><div class="product_crosssell">Das könnte Ihnen auch gefallen: Garmin OLED-Display; Samsung Display defekt.</div>'
        text = monitor._clean_description(html)
        self.assertNotIn("Garmin", text)
        self.assertNotIn("defekt", text)
        self.assertFalse(monitor._is_description_blocked(html, "laptops"))
        search = {"query": "4050 oled", "filters": {"category": "laptops"}}
        self.assertFalse(monitor._intent_details_match(search, {"title": "ASUS Notebook RTX 4050"}, {"description": html}))

    def test_own_description_fault_survives_cleanup(self):
        html = '<section>Samsung Galaxy S24 Ultra. Display defekt.</section><div class="product_crosssell">Sony Kopfhörer funktionieren einwandfrei.</div>'
        self.assertTrue(monitor._is_description_blocked(html, "phones"))


if __name__ == "__main__":
    unittest.main()
