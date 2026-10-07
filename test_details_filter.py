import unittest
import copy
import json
from pathlib import Path

import monitor


class DetailsFilterTest(unittest.TestCase):
    def test_phone_chip_declaration_belongs_to_the_requested_generation(self):
        for generation, correct in (('15','17'),('16','18'),('17','19')):
            query = f'iPhone {generation} Pro Max'
            with self.subTest(generation=generation):
                self.assertTrue(monitor._phone_specifications_match(query+' 256GB',f'Apple A{correct} Pro Chipsatz.',query))
                self.assertFalse(monitor._phone_specifications_match(query+' 256GB',f'Apple A{int(correct)-1} Pro Chipsatz.',query))
                self.assertTrue(monitor._phone_specifications_match(query+' 256GB',f'Apple A{correct} Pro Chip schneller als Apple A{int(correct)-1} Pro Chip.',query))
                self.assertFalse(monitor._phone_chipset_matches(f'Apple A{int(correct)-1} Pro',query))
                self.assertTrue(monitor._phone_specifications_match(query+' 256GB','iOS17. Bildschirm17cm. 6-Core GPU.',query))

    def test_separate_phone_model_number_cannot_conflict_with_title(self):
        search={'query':'iPhone 16 Pro Max','filters':{'category':'phones'}}
        for code, accepted in (('A3296',True),('A2221 (CDMA + GSM)',False)):
            detail={'title':'Apple iPhone 16 Pro Max 256GB','description':'Voll funktionsfaehig.',
                    'localizedAspects':[{'name':'Modellnummer','value':code}]}
            self.assertEqual(accepted,monitor._details_match_contract({'title':detail['title']},search,detail))
        self.assertTrue(monitor._phone_model_number_matches('S25','Samsung Galaxy S25 Edge'))
        self.assertFalse(monitor._phone_model_number_matches('S24','Samsung Galaxy S25 Edge'))
        self.assertFalse(monitor._phone_model_number_matches('S25 Ultra','Samsung Galaxy S25 Edge'))

    def test_recurring_sim_errors_reject_the_phone_without_rejecting_explicit_denials(self):
        for description, expected in (
            ('Manchmal auftauchende Fehlermeldung "SIM-Fehler". Neue SIM-Karte ausprobiert, Fehler bleibt.',True),
            ('Intermittent SIM error. Phone needs SIM PIN again.',True),
            ('Keine SIM-Fehler. Frei fuer alle Netze.',False),
            ('No SIM errors, all functions work.',False),
            ('Keine SIM-Fehler. Aber dann SIM error beim Telefonieren.',True)):
            with self.subTest(description=description):
                self.assertEqual(expected,monitor._is_description_blocked(description,'phones'))

    def test_battery_health_titles_do_not_turn_whole_phones_into_parts(self):
        for title, accessory in (
            ('Apple iPhone 16 Pro Max - Geprueft - 89% Batterie - Guter Zustand',False),
            ('iPhone 16 Pro Max 256GB Titan Schwarz /battrietustand 89%',False),
            ('Apple iPhone 16 Pro Max 256GB Batteriezustand 89%',False),
            ('Batterie 100% iPhone 16 Pro Max 256GB',True),
            ('iPhone 16 Pro Max 89% Batterie nur OVP',True),
            ('Handystand fuer iPhone 16 Pro Max',True)):
            with self.subTest(title=title):
                self.assertEqual(accessory,monitor._is_phone_accessory_title(monitor._normalize(title)))

    def test_html_purchase_actions_ignore_mentions_of_other_formats(self):
        from bs4 import BeautifulSoup
        for actions, expected in ((['Bieten'], ['AUCTION']),
                                  (['Sofort-Kaufen','Preisvorschlag senden'], ['FIXED_PRICE','BEST_OFFER']),
                                  (['Bieten','Sofort-Kaufen'], ['FIXED_PRICE','AUCTION']),
                                  ([], [])):
            with self.subTest(actions=actions):
                html = '<div>Andere Artikel Sofort-Kaufen, Bieten, Preisvorschlag senden</div>' + ''.join(
                    f'<a class="ux-call-to-action" role="button"><span>{label}</span></a>' for label in actions)
                self.assertEqual(expected, monitor._html_buying_options(BeautifulSoup(html, 'html.parser')))

    def test_shared_format_transitions_use_current_buying_options(self):
        cases = json.loads((Path(__file__).parent/'qa/fixtures/hybrid_refresh_cases.json').read_text(encoding='utf8'))['cases']
        for case in cases:
            with self.subTest(case=case['name']):
                refreshed = monitor._calculate_total(copy.deepcopy(case['item']), {'warn_non_eu': False}, case['details'])
                for field, value in case['expected'].items():
                    self.assertEqual(value, refreshed[field], field)
                if refreshed['buy_now']:
                    self.assertAlmostEqual(refreshed['price']+6.19, refreshed['bin_total_price'])

    def test_disappeared_purchase_is_rejected_before_notification(self):
        from test_search_intent_rules import DummyConfig, item
        row = item('Apple iPhone 16 Pro Max 256GB', price=510, shipping_cost=6.19,
                   bin_price=510, _was_hybrid=True, time_left='2 Tage')
        monitor._refresh_candidate_details(row, {'buyingOptions':['AUCTION'],
            'price':{'value':'351','currency':'EUR'},'currentBidPrice':{'value':'351','currency':'EUR'}}, {})
        buy_search = {'query':'iPhone 16 Pro Max','filters':{'category':'phones','listing_type':'buy_now','limit_price':610}}
        self.assertEqual([], monitor.filter_results([row], buy_search, DummyConfig(), skip_seen=True, is_statistics=True))
        # The remaining auction must wait for its normal ending-time rule.
        auc_search = {'query':'iPhone 16 Pro Max','filters':{'category':'phones','listing_type':'auction','limit_price':610}}
        self.assertEqual([], monitor.filter_results([row], auc_search, DummyConfig(), skip_seen=True))

    def test_description_noise_does_not_block_valid_phone_metadata(self):
        search = {"query": "iPhone 15 Pro Max", "filters": {"category": "phones"}}
        details = {
            "title": "Apple iPhone 15 Pro Max Schwarz 256GB",
            "shortDescription": "6,7 Zoll Super Retina XDR Display",
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

    def test_html_shipping_and_import_are_included_in_total(self):
        item = {
            "price": 545.54,
            "shipping_cost": 1.0,
            "location": "",
        }
        details = {
            "price": {"value": "545.54", "currency": "EUR"},
            "htmlShippingCost": {"value": "28.46", "currency": "EUR"},
            "htmlImportCharges": {"value": "126.71", "currency": "EUR"},
            "itemLocationText": "Brough, Vereinigtes Koenigreich",
        }

        monitor._calculate_total(item, {"warn_non_eu": True}, details)

        self.assertEqual(item["shipping_cost"], 28.46)
        self.assertEqual(item["import_charges"], 126.71)
        self.assertAlmostEqual(item["total_price"], 700.71, places=2)

    def test_zero_detail_shipping_does_not_overwrite_search_shipping(self):
        item = {
            "price": 450.0,
            "shipping_cost": 6.19,
            "location": "",
        }
        details = {
            "price": {"value": "450.0", "currency": "EUR"},
            "htmlShippingCost": {"value": "0.00", "currency": "EUR"},
            "itemLocationText": "Schwaikheim, Deutschland",
        }

        monitor._calculate_total(item, {"warn_non_eu": True}, details)

        self.assertEqual(item["shipping_cost"], 6.19)
        self.assertAlmostEqual(item["total_price"], 456.19, places=2)

    def test_detail_page_labeled_money_parses_gbp_shipping_and_import(self):
        lines = [
            "Versand:",
            "£24,52",
            "(ca. EUR 28,46)",
            "International Priority Shipping",
            "Standort: Brough, Vereinigtes Koenigreich",
            "Einfuhrabgaben:",
            "£107.37",
        ]

        shipping = monitor._parse_labeled_money(lines, (r"^versand\b",))
        import_charges = monitor._parse_labeled_money(lines, (r"^einfuhrabgaben\b",))

        self.assertGreater(shipping, 20)
        self.assertGreater(import_charges, 100)

    def test_auction_detection_uses_full_card_text(self):
        html = """
        <ul>
          <li class="s-item" data-listingid="206367308958">
            <a class="s-item__link" href="https://www.ebay.de/itm/206367308958"></a>
            <div class="s-item__title">Nubia Z70 Ultra 24Gb Ram 1Tb Speicher Gebraucht</div>
            <span class="s-item__price">EUR 525,00</span>
            <span>0 Gebote</span>
            <span>Endet in 3 T 3 Std</span>
            <span>+ EUR 6,19 Lieferung</span>
          </li>
        </ul>
        """

        items = monitor.parse_ebay_results(html)

        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["auction"])
        self.assertFalse(items[0]["buy_now"])
        self.assertEqual(items[0]["bids_count"], 0)
        self.assertTrue(items[0]["time_left"])

    def test_ps5_pro_rejects_vr_only_but_allows_console_bundle(self):
        query = monitor._normalize("(playstation 5 pro, ps5 pro)")

        vr_only = monitor._normalize("SONY PLAYSTATION PS VR2 PS5 / PS5 PRO VIRTUAL REALITY VIEWER + 2 SENS Controller")
        console = monitor._normalize("Sony PlayStation 5 Pro Konsole 2TB mit PSVR2 Brille")
        digital = monitor._normalize("Sony Playstation 5 PRO, 2TB, Modell CFI-7021 ohne Disk Laufwerk")
        game = monitor._normalize("Dragon Ball Fighter z Collector's Edition PS4 PS5 Pro 30th PAL Neu")
        fightstick = monitor._normalize("Fightstick Arcade PDP Victrix PS5 Pro Purple Neu Sealed")

        self.assertFalse(monitor._matches_category_query(vr_only, "consoles", query))
        self.assertFalse(monitor._matches_category_query(game, "consoles", query))
        self.assertFalse(monitor._matches_category_query(fightstick, "consoles", query))
        self.assertTrue(monitor._matches_category_query(console, "consoles", query))
        self.assertTrue(monitor._matches_category_query(digital, "consoles", query))

    def test_statistics_filter_keeps_auction_from_buy_search_row(self):
        search = {
            "query": "Redmagic 11 Pro",
            "filters": {
                "category": "all",
                "listing_type": "buy_now_offer",
                "max_price": 400,
            },
            "exclude_words": [],
            "include_words": [],
            "exclude_sellers": [],
        }
        item = {
            "item_id": "398120564552",
            "title": "RedMagic 11 Pro 24GB RAM 1TB Speicher Gaming Phone",
            "price": 859.0,
            "shipping_cost": 6.19,
            "seller_name": "seller",
            "seller_feedback": "100%",
            "item_url": "https://www.ebay.de/itm/398120564552",
            "location": "",
            "condition": "Gebraucht",
            "auction": True,
            "buy_now": False,
            "best_offer": False,
            "bids_count": 0,
            "time_left": "9 Std",
        }

        filtered = monitor.filter_results(
            [item],
            monitor._statistics_filter_search(search),
            monitor.config,
            skip_seen=True,
            is_statistics=True,
        )

        self.assertEqual([x["item_id"] for x in filtered], ["398120564552"])

    def test_redmagic_mojibake_case_is_blocked(self):
        query = monitor._normalize("Redmagic 11 Pro")
        title = monitor._normalize("RedMagic 11 Pro Magnetische Hülle mit Displayschutz Stoßfest Hardcover")

        self.assertTrue(monitor._is_category_blocked_title(title, "phones", query))

    def test_shipping_cost_not_confused_with_delivery_speed(self):
        html = """
        <ul>
          <li class="s-item" data-listingid="178259719449">
            <a class="s-item__link" href="https://www.ebay.de/itm/178259719449"></a>
            <div class="s-item__title">iPhone 16 Pro Max 255GB Titan Black</div>
            <span class="s-item__price">EUR 650,00</span>
            <span>2-3 Tage Lieferung</span>
            <span>+ EUR 6,19 Lieferung</span>
          </li>
        </ul>
        """
        items = monitor.parse_ebay_results(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["shipping_cost"], 6.19)

    def test_description_blocked_on_broken_backcover(self):
        desc = "Das Handy funktioniert einwandfrei jedoch ist das Backcover gebrochen"
        self.assertTrue(monitor._is_description_blocked(desc, "phones"))

    def test_description_not_blocked_on_clean_backcover(self):
        desc = "Das Backcover ist nicht gebrochen, keine Risse."
        self.assertFalse(monitor._is_description_blocked(desc, "phones"))

    def test_review_stickdrift_does_not_block(self):
        html = """
        <div class="x-item-description-child">DualSense wie neu. Keine Mängel.</div>
        <section id="rwid">
          <h2>Produktbewertungen</h2>
          <p>18. Feb. 2025</p>
          <p>Stickdrift musste es selber aufschrauben</p>
        </section>
        """
        self.assertFalse(monitor._is_description_blocked(html, "consoles"))

    def test_seller_stickdrift_still_blocks(self):
        desc = "Der linke Stick hat einen leichten Stickdrift"
        self.assertTrue(monitor._is_description_blocked(desc, "consoles"))

    def test_dualsense_gamepad_matches_controller_query(self):
        title = monitor._normalize("Sony DualSense Wireless Gamepad - Weiß")
        self.assertTrue(monitor._has_query_word(title, "controller"))
        self.assertTrue(monitor._query_matches_title(title, "dualsense controller"))

    def test_iphone_display_parts_are_accessories(self):
        titles = [
            "iPhone 15 14 13 13pro 12 11 Pro Pro Max Display Touch LCD Glas ReparaturService",
            "Original iPhone 15 Pro Max Refurbed Display Bildschirm Touchscreen",
            "Apple iPhone 15 Pro Max Super Retina Pro OLED LCD Display Pulled",
            "Original Genuine Display für iPhone 15 Pro Max Bildschirm von Apple geliefert",
            "Ori Displayeinheit für Apple iPhone 15 Pro Max Serviceware",
        ]
        for raw in titles:
            self.assertTrue(
                monitor._is_phone_accessory_title(monitor._normalize(raw)),
                raw,
            )
        phone = monitor._normalize("Apple iPhone 15 Pro Max 256GB Titan Natur")
        self.assertFalse(monitor._is_phone_accessory_title(phone))

    def test_dualsense_plus_dock_and_hall_sticks_ignore_stop_words(self):
        pad_dock = monitor._normalize(
            "Sony PlayStation 5 DualSense Wireless-Controller Camouflage + ISY Ladestation"
        )
        hall = monitor._normalize(
            "Sony DualSense Wireless Ps5 Controller Galactic Purple (Hall Effect Sticks)"
        )
        dock_only = monitor._normalize("PS5 DualSense Ladestation Charging Station")
        stick_parts = monitor._normalize("PS5 DualSense Analog Sticks Ersatzteile")
        self.assertFalse(monitor._exclude_word_hits(pad_dock, "ladestation"))
        self.assertTrue(monitor._exclude_word_hits(dock_only, "ladestation"))
        self.assertFalse(monitor._exclude_word_hits(hall, "sticks"))
        self.assertFalse(monitor._exclude_word_hits(hall, "hall"))
        self.assertTrue(monitor._exclude_word_hits(stick_parts, "sticks"))

    def test_plain_text_reviews_heading_is_stripped(self):
        text = (
            "DualSense Midnight Black, alles ok.\n"
            "Produktbewertungen\n"
            "18. Feb. 2025\n"
            "Stickdrift musste es selber aufschrauben"
        )
        cleaned = monitor._strip_review_sections(text)
        self.assertIn("alles ok", cleaned)
        self.assertNotIn("Stickdrift", cleaned)

    def test_hybrid_listing_prices_and_grouping(self):
        # 1. HTML search result parsing of a hybrid listing
        html = """
        <ul>
          <li class="s-item" data-listingid="168498547437">
            <a class="s-item__link" href="https://www.ebay.de/itm/168498547437"></a>
            <div class="s-item__title">5070 Ti PC Gaming computer</div>
            <span class="s-item__price">EUR 2.720,00</span>
            <span class="s-item__price">oder Sofort-Kaufen: EUR 3.808,00</span>
            <span>0 Gebote</span>
            <span class="s-item__time-left">Endet in 1 Std</span>
            <span>+ EUR 24,00 Lieferung</span>
          </li>
        </ul>
        """
        items = monitor.parse_ebay_results(html)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertTrue(item["auction"])
        self.assertTrue(item["buy_now"])
        self.assertEqual(item["auc_price"], 2720.0)
        self.assertEqual(item["bin_price"], 3808.0)
        self.assertTrue(item["_was_hybrid"])

        # 2. _calculate_total on general/unseparated item computes correct totals
        settings = {"warn_non_eu": False}
        monitor._calculate_total(item, settings)
        self.assertEqual(item["bin_total_price"], 3832.0)
        self.assertEqual(item["auc_total_price"], 2744.0)

        # 3. filter_results uses bin_price for buy_now search
        search_buy = {
            "query": "5070 Ti PC",
            "filters": {
                "listing_type": "buy_now_offer",
                "limit_price": 3000,
            }
        }
        filtered_buy = monitor.filter_results([item], search_buy, monitor.config, skip_seen=False)
        # 3832.0 is > 3000 -> should be filtered out!
        self.assertEqual(len(filtered_buy), 0)

        # 4. filter_results uses auc_price for auction search
        search_auc = {
            "query": "5070 Ti PC",
            "filters": {
                "listing_type": "auction",
                "limit_price": 3000,
            }
        }
        filtered_auc = monitor.filter_results([item], search_auc, monitor.config, skip_seen=False)
        # 2744.0 is <= 3000 -> should pass!
        self.assertEqual(len(filtered_auc), 1)

        # 5. Detail refresh updates prices correctly
        details = {
            "buyingOptions": ["AUCTION", "FIXED_PRICE"],
            "price": {"value": "3900.00", "currency": "EUR"},
            "currentBidPrice": {"value": "2800.00", "currency": "EUR"},
            "itemLocationText": "Deutschland",
        }
        monitor._calculate_total(item, settings, details)
        self.assertEqual(item["bin_price"], 3900.0)
        self.assertEqual(item["auc_price"], 2800.0)
        self.assertEqual(item["bin_total_price"], 3924.0)
        self.assertEqual(item["auc_total_price"], 2824.0)


if __name__ == "__main__":
    unittest.main()
