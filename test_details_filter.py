import unittest

import monitor


class DetailsFilterTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
