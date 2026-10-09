"""Real details captured after independent browser inspection on 2026-10-05."""
import json
import unittest
from pathlib import Path
import monitor


class ManualDeviceEvidenceTests(unittest.TestCase):
    def test_live_italian_model_fields_cannot_hide_incompatible_iphone(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/cloud_live_model_cases_2026-10-08.json').read_text(encoding='utf8'))
        for case in cases:
            with self.subTest(item=case['id']):
                search={'query':case['query'],'filters':{'category':case.get('category','phones')}}
                self.assertEqual(case['expected'],monitor._details_match_contract({'title':case['title']},search,case))

    def test_html_seller_identity_refreshes_blacklists_without_using_reviewers(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/html_seller.json').read_text(encoding='utf8'))
        for case in cases:
            details=monitor._parse_item_details_html(case['html'],description='Full working phone')
            self.assertEqual(case['expected'],details.get('seller'))
            if case['expected']:
                item={'title':'iPhone 16 Pro Max 512GB','price':297.13,'shipping':6.19,'location':'DE','seller_name':'unknown'}
                monitor._refresh_candidate_details(item,details,{})
                self.assertEqual('marclemmor',item['seller_name'])
                self.assertEqual('private',item['seller_type'])
                search={'query':'iPhone 16 Pro Max','exclude_sellers':['marclemmor'],'filters':{'category':'phones'}}
                self.assertFalse(monitor.filter_results([dict(item,item_id='128121409205')],search,monitor.config,skip_seen=True,is_statistics=True))
    def test_html_auction_time_requires_own_countdown_and_exact_display(self):
        from bs4 import BeautifulSoup
        from datetime import datetime
        cases=json.loads((Path(__file__).parent/'qa/fixtures/html_auction_time.json').read_text(encoding='utf8'))
        for case in cases:
            self.assertEqual(case['expected'],monitor._html_auction_end(BeautifulSoup(case['html'],'html.parser'),datetime.fromisoformat(case['now'].replace('Z','+00:00'))))
    def test_sold_status_is_own_listing_state_not_recommendations(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/html_listing_status.json').read_text(encoding='utf8'))
        for case in cases:
            details=monitor._parse_item_details_html(case['html'],description='')
            self.assertEqual(case['unavailable'],bool(details.get('estimatedAvailabilities')))
    def test_rendered_html_characteristics_use_the_same_model_contract(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/html_item_details.json').read_text(encoding='utf8'))
        for case in cases:
            details=monitor._parse_item_details_html(case['html'],description=case['description'])
            with self.subTest(item=case['id']):
                self.assertEqual(case['categoryId'],details['categoryId'])
                self.assertTrue(details['localizedAspects'])
                self.assertEqual('Gebraucht',details['condition'])
                self.assertEqual(case['expected'],monitor._details_match_contract({'title':details['title']},{'query':case['query'],'filters':{'category':'phones'}},details))
                self.assertEqual('',monitor._parse_item_details_html(case['html'],description='')['description'])
                if case['id']=='128121409205':
                    self.assertAlmostEqual(297.13,float(details['currentBidPrice']['value']))
                    self.assertAlmostEqual(6.19,float(details['htmlShippingCost']['value']))
                    self.assertEqual(['AUCTION','BEST_OFFER'],details['buyingOptions'])
    def test_charging_failure_remains_a_fault_when_wireless_works(self):
        for body in ('Der Akku lädt nicht mehr mit der Ladebuchse sondern nur mit einem MagSafe charger.', 'Ladebuchse funktioniert nicht. MagSafe funktioniert.', 'The phone does not charge via USB; wireless charging works.', 'Battery won’t charge.'):
            self.assertTrue(monitor._is_description_blocked(body, 'phones'), body)
        for body in ('Akku lädt ohne Probleme. MagSafe funktioniert.', 'Der Akku lädt nicht langsam, sondern schnell.', 'The phone does not charge slowly.', 'Ladegerät ist nicht dabei; USB-C und MagSafe funktionieren.'):
            self.assertFalse(monitor._is_description_blocked(body, 'phones'), body)

    def test_repaired_back_glass_is_not_negated_by_no_exchange_policy(self):
        self.assertTrue(monitor._is_description_blocked('Das Rückseitenglas habe ich vor einem Jahr wegen Bruch tauschen lassen. Kein Umtausch. Voll funktionsfähig.', 'phones'))
        self.assertTrue(monitor._is_description_blocked('Das Rückglas wurde nicht getauscht. Das Display ist gebrochen.', 'phones'))
        for body in ('Das Rückseitenglas wurde nie getauscht.', 'Das Rückglas wurde nicht getauscht.', 'Das back glass wurde ohne Reparatur genutzt.'):
            self.assertFalse(monitor._is_description_blocked(body, 'phones'), body)

    def test_actual_nuc_mini_pc_survives_preliminary_selection(self):
        query = '5070 ti (pc, rechner, computer, desktop, gaming pc)'
        title = 'ASUS ROG NUC 2025 Gaming Mini PC Intel Core Ultra 9 275HX RTX 5070TI 32GB 2TB'
        for name in (title, 'Gaming Mini-PC RTX5070Ti', 'Gaming MiniPC RTX5070Ti'):
            normalized = monitor._normalize(name)
            self.assertTrue(monitor._intent_prelim_matches_title(normalized, {'query':query}), name)
            self.assertTrue(monitor._matches_category_query(normalized, 'computers', monitor._normalize(query)), name)
        self.assertFalse(monitor._intent_prelim_matches_title(monitor._normalize('ASUS ROG Zephyrus G14 RTX5070Ti'), {'query':query}))
        self.assertTrue(monitor._is_category_blocked_title(monitor._normalize('Grafikkarte RTX5070Ti for Mini PC'), 'computers', monitor._normalize(query)))

    def test_actual_pc_details_match_independent_purpose_and_gpu_verdicts(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/pc_manual_details.json').read_text(encoding='utf8'))
        for case in cases:
            details={k:v for k,v in case.items() if k not in ('itemEndDate','estimatedAvailabilities')}
            with self.subTest(item=case['id']):
                self.assertEqual(case['expected'],monitor._details_match_contract({'title':case['title']},{'query':case['query'],'filters':{'category':'computers'}},details))
    def test_actual_rtx4080s_shorthand_survives_preliminary_selection(self):
        title=monitor._normalize('High End Gaming PC intel i9 13900KS NVIDIA RTX4080S 16GB')
        self.assertTrue(monitor._intent_prelim_matches_title(title,{'query':'4080 (pc, rechner)'}))
        self.assertFalse(monitor._has_rtx_gpu(monitor._normalize('Gaming PC RTX4080S, actual GPU RTX5050'),'4080'))
        self.assertFalse(monitor._has_rtx_gpu(monitor._normalize('Gaming PC 4080ST RTX5050'),'4080'))
    def test_gpu_trademark_does_not_hide_generation_or_wrong_actual_gpu(self):
        self.assertTrue(monitor._has_rtx_gpu(monitor._normalize('Current GPU RTX™ 4080 SUPER. New PC RTX5090.'),'4080'))
        self.assertFalse(monitor._has_rtx_gpu(monitor._normalize('Captiva PC 10-4080 RTX™5050'),'4080'))
        self.assertTrue(monitor._has_rtx_5070_ti(monitor._normalize('GPU RTX®5070 Ti')))
        self.assertFalse(monitor._has_rtx_5070_ti(monitor._normalize('PC 5070Ti GPU RTX™5070')))
    def test_explicit_battery_health_does_not_require_storage_in_phone_title(self):
        for title in ('Apple iPhone 17 Pro Max Blau OVP 93% Batteriekapazität','Samsung Galaxy S25 Edge battery health: 96%'):
            self.assertFalse(monitor._is_phone_accessory_title(monitor._normalize(title)),title)
        for title in ('Akku 93% Batteriekapazität für iPhone 17 Pro Max','Battery health:93% replacement for iPhone 17 Pro Max','Apple iPhone 17 Pro Max 93% Batteriekapazität nur OVP','Apple iPhone 17 Pro Max 93% Batteriekapazität Ersatzteile'):
            self.assertTrue(monitor._is_phone_accessory_title(monitor._normalize(title)),title)
    def test_german_screen_replacement_verb_includes_prefix_and_negation(self):
        for body in ('Display-(Original ausgetauscht) Drittanbieter Soft Oled 120Hz','Das Display wurde ausgetauscht.','Ausgetauschtes Display, voll funktionstüchtig.'):
            self.assertTrue(monitor._is_description_blocked(body,'phones'),body)
        for body in ('Das Display wurde nie ausgetauscht.','Das Display wurde nicht ausgetauscht.','Nie ausgetauschtes Display.'):
            self.assertFalse(monitor._is_description_blocked(body,'phones'),body)
    def test_laptop_battery_health_is_metadata_not_a_spare_battery(self):
        title=monitor._normalize('DELL XPS 16 9640 64GB 4TB Intel Ultra 9 RTX4060 Super Zustand Akku ca.99%')
        self.assertFalse(monitor._is_category_blocked_title(title,'laptops','4060 oled'))
        self.assertTrue(monitor._is_category_blocked_title('battery 99% for dell xps16 rtx4060','laptops','4060 oled'))
        self.assertTrue(monitor._is_category_blocked_title(title+' display defekt','laptops','4060 oled'))
    def test_factory_asus_panel_requires_matching_own_model_and_resolution(self):
        for title,panel in [('asus proart px13hn7306w rtx4060 laptop','2880x1800'),('asus vivobook pro15 n6506cu-ma029x rtx4050 laptop','2880x1620')]:
            self.assertTrue(monitor._known_oled_configuration(title,'display: '+panel))
            self.assertFalse(monitor._known_oled_configuration(title,'display: 1920x1200'))
            self.assertFalse(monitor._known_oled_configuration(title,'external display: '+panel))
    def test_xps_oled_resolution_is_scoped_to_own_model_and_screen(self):
        title='Dell XPS 15 9530 RTX4060 Laptop'
        search={'query':'4060 oled','filters':{'category':'laptops'}}
        details={'title':title,'categoryId':'177','description':'Displayauflösung: 3456x2160. Fully working laptop.'}
        self.assertTrue(monitor._details_match_contract({'title':title},search,details))
        for wrong in ('Display: 1920x1200.','Supports external display: 3456x2160.','Display: 3456x2160. Paneltyp: IPS.'):
            self.assertFalse(monitor._details_match_contract({'title':title},search,{**details,'description':wrong}))
        self.assertFalse(monitor._known_oled_configuration('dell xps 16 9640','display: 3456x2160'))
        self.assertFalse(monitor._known_oled_configuration('dell xps 15 9520','display: 3456x2160'))
    def test_panel_blemish_is_not_a_cosmetic_lid_dent_or_its_negation(self):
        for body,expected in [('Kleine Macke mittig auf dem Display, nicht fotografierbar.',True),('Das Display hat eine kleine Macke.',True),('Keine Macke auf dem Display.',False),('Keine sichtbaren Macken auf dem Display.',False),('Leichte Delle auf dem Deckel, kein Funktionseinfluss.',False),('Eine Macke am Gehäuse. Das Display ist einwandfrei.',False),('Keine Macke auf dem Display. Das Display hat eine kleine Druckstelle.',True)]:
            self.assertEqual(expected,monitor._is_description_blocked(body,'laptops'))
    def test_actual_oled_laptops_and_hidden_body_damage(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/laptop_manual_details.json').read_text(encoding='utf8'))
        for case in cases:
            search={'query':case.get('query','4050 oled'),'filters':{'category':'laptops'}}
            details={k:v for k,v in case.items() if k not in ('itemEndDate','estimatedAvailabilities')}
            with self.subTest(item=case['id']):
                self.assertEqual(case['expected'],monitor._details_match_contract({'title':case['title']},search,details))
    def test_oled_missing_from_title_requires_confirmed_model_panel_configuration(self):
        title='Lenovo Yoga 7 Pro 14IMH9 Core Ultra 7 RTX4050 32GB 1TB'
        search={'query':'4050 oled','filters':{'category':'laptops'}}
        details={'title':title,'categoryId':'177','description':'Display: 2880 x 1800. Original power supply. Used, working laptop.'}
        self.assertTrue(monitor._details_match_contract({'title':title},search,details))
        for wrong in ('Display: 2560x1600.','Display: 3072x1920.','Display: 2880x1800. Paneltyp: IPS.'):
            self.assertFalse(monitor._details_match_contract({'title':title},search,{**details,'description':wrong}))
        self.assertFalse(monitor._known_oled_configuration(monitor._normalize(title.replace('14IMH9','14IRH8')),'display: 2880x1800'))
        self.assertFalse(monitor._known_oled_configuration(monitor._normalize(title),'supports external display: 2880x1800'))
        self.assertFalse(monitor._details_match_contract({'title':'Lenovo Yoga RTX4050'},search,{**details,'title':'Lenovo Yoga RTX4050','description':'Previous laptop was14IMH9. Display: 2880x1800.'}))
        for category in ('laptops','all'):
            search['filters']['category']=category
            self.assertTrue(monitor._details_match_contract({'title':title},search,details))
            self.assertFalse(monitor._details_match_contract({'title':title},search,{**details,'localizedAspects':[{'name':'Paneltyp','value':'IPS'}]}))
        for gpu in ('4050','4060'):
            variants=monitor._search_query_variants({'query':f'(rtx {gpu} oled notebook, laptop {gpu} oled, rtx {gpu} oled laptop)'})
            self.assertEqual(4,len(variants))
            self.assertIn(f'rtx {gpu} (aero,vivobook,spectre,yoga,xps,legion,proart)',variants)
    def test_spare_parts_inventory_needs_explicit_whole_phone_supply(self):
        body='zahlung nur durch paypul oder uberweisung! akku in guten zustand; ersatzteile alle parat und in original; keine beschadigungen oder sonstiges'
        self.assertFalse(monitor._phone_description_purpose_confirmed(body))
        self.assertTrue(monitor._phone_description_purpose_confirmed('Das Smartphone ist voll funktionsfähig. '+body))
        self.assertTrue(monitor._phone_description_purpose_confirmed('Lieferumfang: iPhone 17 Pro Max und Ladekabel. '+body))
        self.assertTrue(monitor._phone_description_purpose_confirmed('Akku in gutem Zustand, keine Beschädigungen.'))
    def test_only_whole_headphones_without_box_is_not_only_a_part(self):
        search={'query':'sony wh-1000xm6','filters':{'category':'headphones'}}
        for suffix,expected in [('NUR KOPFHÖRER',True),('ONLY HEADPHONES',True),('Only Case',False),('Nur Ohrpolster',False),('Left Ear Only',False),('Only Headphones Replacement Earpads',False)]:
            title=monitor._normalize('Sony WH-1000XM6 Wireless Noise Cancelling '+suffix)
            self.assertEqual(expected,monitor._matches_category_query(title,'headphones',monitor._normalize(search['query'])))
    def test_real_seller_phone_purpose_chipset_and_privacy_terms(self):
        cases=json.loads((Path(__file__).parent/'qa/fixtures/phone_manual_purpose.json').read_text(encoding='utf8'))
        for case in cases:
            for category in ('phones','all'):
                search={'query':case['query'],'filters':{'category':category}}
                with self.subTest(item=case['id'],category=category):
                    # Purpose/specification snapshots are independent of today's
                    # auction clock. Availability is covered by a separate test.
                    details={k:v for k,v in case.items() if k not in ('itemEndDate','estimatedAvailabilities')}
                    self.assertEqual(case['expected'],monitor._details_match_contract({'title':case['title']},search,details))
    def test_all_categories_still_rejects_phone_parts_from_its_real_category(self):
        title='ZTE Nubia Z80 Ultra NX741J Marco Intermedio Placa Bisel (Negro)'
        self.assertTrue(monitor._is_phone_accessory_title(monitor._normalize(title)))
        for category in ('all','phones'):
            search={'query':'nubia z80 ultra','filters':{'category':category}}
            # Even a part renamed to a phone must fail its real part category.
            details={'title':'Nubia Z80 Ultra 512GB','categoryId':'43304','categoryIdPath':'15032|43304','description':'New middle frame for Nubia Z80 Ultra.'}
            self.assertFalse(monitor._details_match_contract({'title':details['title']},search,details))
            details={'title':'Nubia Z80 Ultra 512GB','categoryId':'9355','description':'Nubia Z80 Ultra smartphone, fully working.'}
            self.assertTrue(monitor._details_match_contract({'title':details['title']},search,details))
    def test_gpu_model_number_cannot_override_declared_graphics_card(self):
        bad='Captiva Business PC 10-4080 R5 9600X 16GB DDR5 RTX 5050 1TB Win11'
        self.assertFalse(monitor._intent_prelim_matches_title(monitor._normalize(bad),{'query':'4080 (pc, rechner)','filters':{'category':'computers'}}))
        self.assertFalse(monitor._has_rtx_gpu('business pc 20 4060 rtx 4050 oled laptop','4060'))
        self.assertFalse(monitor._has_rtx_5070_ti('gaming pc model 5070 ti rtx 5070'))
        self.assertTrue(monitor._has_rtx_gpu('gaming pc rtx4080 super','4080'))
        self.assertTrue(monitor._has_rtx_5070_ti('gaming pc rtx5070ti'))
        search={'query':'4080 (pc, rechner)','filters':{'category':'computers'}}
        details={'title':'Gaming PC RTX4080 Ryzen 7','categoryId':'179','description':'Gaming PC. Grafikkarte: NVIDIA GeForce RTX5050 8GB.'}
        self.assertFalse(monitor._details_match_contract({'title':details['title']},search,details))
    def test_ult_repair_slider_is_a_part_even_in_wrong_headphone_category(self):
        title='Sony ULT Wear WH-ULT900N Original Slider Außenpanel Rechts Schwarz Reparaturteil'
        self.assertTrue(monitor._is_category_blocked_title(monitor._normalize(title),'headphones','sony ult wear'))
    def test_customer_data_restriction_does_not_erase_real_phone_lock(self):
        privacy='Nach vollständiger Vertragsabwicklung werden Ihre Daten für die weitere Verwendung gesperrt.'
        self.assertFalse(monitor._is_description_blocked(privacy,'phones'))
        self.assertTrue(monitor._is_description_blocked(privacy+' Das Telefon ist gesperrt.','phones'))
        self.assertTrue(monitor._is_description_blocked('Der Bildschirm ist defekt. '+privacy,'phones'))
    def test_s25_edge_rejects_explicit_wrong_chip_without_requiring_missing_specs(self):
        query='samsung galaxy s25 edge'
        self.assertFalse(monitor._phone_specifications_match('Samsung S25 Edge','Der leistungsfähige Exynos 990 Prozessor sorgt für Multitasking.',query))
        self.assertFalse(monitor._phone_specifications_match('Samsung S25 Edge','Processor: Snapdragon 8 Gen 3.',query))
        self.assertFalse(monitor._phone_specifications_match('Samsung S25 Edge 16GB RAM','',query))
        for body in ('', 'Processor: Octa-Core.', 'Processor: Snapdragon 8 Elite for Galaxy.', 'Compared to the old Exynos 990, this phone is faster. Processor: Snapdragon 8 Elite.'):
            self.assertTrue(monitor._phone_specifications_match('Samsung S25 Edge',body,query))
        for value,expected in [('Exynos 990',False),('Snapdragon 8 Gen 3',False),('Snapdragon 8 Elite',True),('Qualcomm Snapdragon 8',True),('Octa Core',True)]:
            self.assertEqual(expected,monitor._phone_chipset_matches(value,query))
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
