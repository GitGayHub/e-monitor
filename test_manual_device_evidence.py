"""Real details captured after independent browser inspection on 2026-10-05."""
import json
import unittest
from pathlib import Path
import monitor


class ManualDeviceEvidenceTests(unittest.TestCase):
    def test_s25_edge_does_not_accept_base_plus_or_ultra(self):
        for title,expected in [('Samsung Galaxy S25 Edge 256GB',True),('Samsung S25Edge 512GB',True),('Samsung Galaxy S25 256GB',False),('Samsung Galaxy S25 Ultra 256GB',False),('Samsung Galaxy S25 Plus 256GB',False)]:
            with self.subTest(title=title):
                self.assertEqual(expected,monitor._matches_phone_query_model(monitor._normalize(title),'samsung galaxy s25 edge'))
    def test_headphone_seller_model_and_actual_case_bundle(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/headphone_manual_details.json').read_text(encoding='utf8'))
        for category in ('all','headphones'):
            search={'query':'sony wh-1000xm6','filters':{'category':category}}
            for case in cases:
                with self.subTest(category=category,item=case['id']):
                    title=monitor._normalize(case['title'])
                    result=not monitor._is_category_blocked_title(title,'headphones') and monitor._details_match_contract({'title':case['title']},search,case)
                    self.assertEqual(case['expected'],result)
        self.assertFalse(monitor._headphone_details_match('sony wh1000xm5','Sony WH1000XM6','Sony WH1000XM6 Headphones',[]))
        self.assertFalse(monitor._headphone_details_match('sony wh1000xm6','Sony WF1000XM6','Sony WF1000XM6 earphones',[]))
        self.assertTrue(monitor._headphone_details_match('sony wh1000xm6','Sony WH1000XM6','Selling Sony WH1000XM6 headphones. Upgrading to WH1000XM7.',[]))
        self.assertFalse(monitor._headphone_details_match('sony wh1000xm6','Sony WH1000XM6 | Original Case','Original case for Sony WH1000XM6 headphones. Headphones not included.',[]))
        self.assertFalse(monitor._headphone_details_match('sony wh1000xm6','Sony WH1000XM6 Bluetooth Headphones Case Inc','Original case for Sony WH1000XM6 headphones. Headphones not included.',[]))

    def test_actual_monitor_category_placeholder_and_panel_conflict(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/monitor_manual_details.json').read_text(encoding='utf-8'))
        for category in ('monitors','all'):
            search={'query':'lg ultragear oled 480hz','filters':{'category':category}}
            for case in cases:
                with self.subTest(category=category,item=case['id']):
                    self.assertEqual(case['expected'],monitor._details_match_contract({'title':case['title']},search,case))
            good=next(c for c in cases if c['expected'])
            bundle={**good,'title':'LG 32GS95UE OLED Monitor mit Stand Base und Kabel','description':'Voll funktionsfähiger LG 32GS95UE Monitor mit Stand Base und Kabel.'}
            self.assertTrue(monitor._details_match_contract({'title':bundle['title']},search,bundle))
            for value in ('IPS','TN','VA','LCD'):
                details={**good,'localizedAspects':[{'name':'Paneltyp','value':value}]}
                self.assertFalse(monitor._details_match_contract({'title':good['title']},search,details))
            self.assertTrue(monitor._details_match_contract({'title':good['title']},search,{**good,'localizedAspects':[{'name':'Paneltyp','value':'OLED'}]}))

    def test_nubia_and_redmagic_generation_and_variant_are_part_of_the_model(self):
        # Browser inspection: 318797834345 is Z70 Ultra; 198669347531 is Z70S.
        # The numbered family must agree even when a title has both search words.
        cases = (
            ('nubia z70 ultra', 'Nubia Z70 Ultra 512GB', True),
            ('nubia z70 ultra', 'Nubia Z70S Ultra Classic Black 256GB', False),
            ('nubia z70 ultra', 'Nubia Z80 Ultra, Upgrade vom Z70 Ultra', False),
            ('nubia z70s ultra', 'Nubia Z70S Ultra Classic Black 256GB', True),
            ('nubia z70s ultra', 'Nubia Z70 Ultra 512GB', False),
            ('nubia z80 ultra', 'Nubia Z80 Ultra Leading 512GB', False),
            ('nubia z80 ultra leading', 'Nubia Z80 Ultra Leading 512GB', True),
            ('nubia z80 ultra leading', 'Nubia Z80 Ultra 512GB', False),
            ('redmagic 11 pro', 'Nubia Red Magic 11 Pro 512GB', True),
            ('redmagic 11 pro', 'Nubia Red Magic 11S Pro, Upgrade vom 11 Pro', False),
            ('redmagic 11s pro', 'Nubia Red Magic 11 S Pro 512GB', True),
            ('redmagic 11 pro', 'Nubia Redmagic 11 Air', False),
        )
        for query, title, expected in cases:
            with self.subTest(query=query, title=title):
                self.assertEqual(expected, monitor._matches_phone_query_model(monitor._normalize(title), query))
                self.assertEqual(expected, monitor._phone_model_aspect_matches(title, query))

    def test_mouse_generation_and_editions_follow_independent_seller_evidence(self):
        cases = json.loads((Path(__file__).parent/'qa/fixtures/mouse_manual_models.json').read_text(encoding='utf-8'))
        search = {'query':'logitech superlight 2','filters':{'category':'mice'}}
        for case in cases:
            with self.subTest(item=case['id']):
                title = monitor._normalize(case['title'])
                eligible = monitor._matches_superlight_2_mouse(title) and not monitor._is_category_blocked_title(title,'mice') and monitor._details_match_contract({'title':case['title']},search,case)
                self.assertEqual(case['expected'], eligible)
                if case['id'] == '406063677998':
                    self.assertFalse(monitor._is_category_blocked_title(title,'mice'))
                    self.assertTrue(monitor._details_match_contract({'title':case['title']},search,{**case,'description':'Logitech G PRO X Superlight 2, voll funktionsfähig, ohne OVP.'}))
        for edition in ('', ' dex', ' se', 'c', 'c se'):
            requested = 'logitech superlight 2' + edition
            edited = {'query':requested,'filters':{'category':'mice'}}
            self.assertEqual(requested,monitor._intent_query(edited))
            self.assertTrue(monitor._intent_prelim_matches_title(monitor._normalize('Logitech G PRO X Superlight 2'+edition+' Gaming-Maus'),edited))
            if edition:
                self.assertFalse(monitor._intent_prelim_matches_title(monitor._normalize('Logitech G PRO X Superlight 2 Gaming-Maus'),edited))

    def test_whole_mouse_includes_receiver_but_receiver_or_pcb_is_not_mouse(self):
        cases = json.loads((Path(__file__).parent/'qa/fixtures/mouse_manual_bundle.json').read_text(encoding='utf-8'))
        search = {'query': 'logitech superlight 2', 'filters': {'category': 'mice'}}
        for case in cases:
            with self.subTest(item=case['id']):
                title = monitor._normalize(case['title'])
                eligible = monitor._matches_superlight_2_mouse(title) and not monitor._is_category_blocked_title(title, 'mice') and monitor._details_match_contract({'title':case['title']},search,case)
                self.assertEqual(case['expected'], eligible)
        self.assertTrue(monitor._is_category_blocked_title('logitech superlight 2 maus receiver + kabel', 'mice'))

    def test_console_description_and_model_must_agree_with_ps5_pro(self):
        case = json.loads((Path(__file__).parent/'qa/fixtures/console_manual_model.json').read_text(encoding='utf-8'))
        search = {'query': 'playstation 5 pro', 'filters': {'category': 'consoles'}}
        candidate = {'title': case['title']}
        base = {'title': case['title'], 'description': case['description']}
        self.assertFalse(monitor._details_match_contract(candidate, search, base))
        good = {**base, 'description': 'PS5 Pro Konsole mit Controller. Modellnummer CFI-7121.'}
        self.assertTrue(monitor._details_match_contract(candidate, search, good))
        for value in ('CUH-7216B', 'PlayStation 4 Pro', 'CFI-1216A'):
            self.assertFalse(monitor._details_match_contract(candidate, search, {**good, 'localizedAspects': [{'name': 'Modell', 'value': value}]}))

    def test_console_bundle_with_faulty_controller_swipes_is_rejected(self):
        case = json.loads((Path(__file__).parent/'qa/fixtures/console_manual_description.json').read_text(encoding='utf-8'))
        self.assertTrue(monitor._is_description_blocked(case['description'],'consoles'))
        self.assertFalse(monitor._is_description_blocked('Die Konsole und der Controller funktionieren einwandfrei. Das Touchpad wurde nicht benutzt.','consoles'))
    def test_completed_description_cannot_make_an_ended_or_sold_lot_eligible(self):
        search = {'query': 'sony ult wear', 'filters': {'category': 'headphones'}}
        item = {'title': 'Sony ULT Wear Bluetooth Kopfhörer'}
        base = {'title': item['title'], 'description': 'Voll funktionsfähige Sony ULT Wear Kopfhörer mit Tasche.'}
        self.assertTrue(monitor._details_match_contract(item, search, base))
        for unavailable in ({'itemEndDate': '2000-01-01T00:00:00Z'},
                            {'estimatedAvailabilities': [{'estimatedAvailabilityStatus': 'OUT_OF_STOCK'}]}):
            with self.subTest(unavailable=unavailable):
                self.assertFalse(monitor._details_match_contract(item, search, {**base, **unavailable}))

    def test_s24_full_descriptions_and_explicit_ram_conflicts(self):
        document = json.loads((Path(__file__).parent / 'qa/fixtures/s24_manual_details.json').read_text(encoding='utf-8'))
        search = {'query': 'samsung s24 ultra', 'filters': {'category': 'phones'}}
        for item_id, details in document.items():
            with self.subTest(item=item_id):
                # Official Samsung specification: every S24 Ultra has 12GB RAM.
                # 407261189770 additionally supplies its own notebook specs.
                consistent = item_id not in {'407266105568', '407261189770'}
                self.assertEqual(consistent, monitor._details_match_contract({'title': details['title']}, search, details))


if __name__ == '__main__':
    unittest.main()
