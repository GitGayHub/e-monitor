import unittest

import monitor


class DummyConfig:
    def __init__(self, banned=None, sellers=None):
        self._banned = set(banned or [])
        self._sellers = list(sellers or [])

    def get_global_banned_sellers(self):
        return list(self._sellers)

    def get_banned_item_ids(self):
        return set(self._banned)

    def get_item_hashes(self):
        return set()

    def get_settings(self):
        return {"warn_non_eu": False}


def item(title, item_id="100", price=100, **overrides):
    base = {
        "item_id": item_id,
        "title": title,
        "price": price,
        "shipping_cost": 0,
        "total_price": price,
        "buy_now": True,
        "best_offer": False,
        "auction": False,
        "bids_count": 0,
        "is_pickup_only": False,
        "is_multivariation": False,
        "condition": "Gebraucht",
        "seller_name": "seller",
        "seller_rating_count": 10,
        "seller_rating_percent": 99.0,
        "top_rated": False,
        "location": "Berlin, DE",
        "time_left": "",
    }
    base.update(overrides)
    return base


class SearchIntentRuleTests(unittest.TestCase):
    def test_vivobook_requires_3050_in_details(self):
        search = {
            "query": "asus vivobook 14x oled",
            "filters": {"category": "laptops", "listing_type": "buy_now_offer", "location": "worldwide"},
        }
        self.assertIn("_nkw=asus%20vivobook%2014x%20oled", monitor._build_url_with_host("ebay.de", search))
        candidate = item("ASUS Vivobook Pro 14X OLED M7400QC")
        details = {
            "title": "ASUS Vivobook Pro 14X OLED M7400QC",
            "description": "Ryzen 7 5800H RTX 3050 16 GB RAM OLED 2.8K",
        }
        self.assertTrue(monitor._intent_prelim_matches_title(monitor._normalize(candidate["title"]), search))
        self.assertTrue(monitor._intent_details_match(search, candidate, details))

        bad_details = {"title": "ASUS Vivobook Pro 14X OLED", "description": "Ryzen 7 5800H 16 GB RAM OLED"}
        self.assertFalse(monitor._intent_details_match(search, candidate, bad_details))

    def test_rtx_oled_laptop_rules(self):
        search = {"query": "4050 oled", "filters": {"category": "laptops", "listing_type": "auction"}}
        good = item("Lenovo Legion Laptop RTX 4050 OLED", auction=True, buy_now=False, time_left="4h")
        bad = item("RTX 4050 Grafikkarte OLED Mod", auction=True, buy_now=False, time_left="4h")
        cfg = DummyConfig()
        self.assertEqual([x["item_id"] for x in monitor.filter_results([good], search, cfg, skip_seen=True, is_statistics=True)], ["100"])
        self.assertEqual(monitor.filter_results([bad], search, cfg, skip_seen=True, is_statistics=True), [])

    def test_5070_ti_pc_rejects_plain_5070(self):
        search = {"query": "5070 Ti PC", "filters": {"category": "computers", "listing_type": "buy_now_offer"}}
        good = item("Gaming PC RTX 5070 Ti Ryzen 7 32GB RAM")
        bad = item("Gaming PC RTX 5070 Ryzen 7 32GB RAM")
        cfg = DummyConfig()
        self.assertEqual(len(monitor.filter_results([good], search, cfg, skip_seen=True, is_statistics=True)), 1)
        self.assertEqual(monitor.filter_results([bad], search, cfg, skip_seen=True, is_statistics=True), [])

    def test_ps5_pro_cover_and_vr_only_rejected_console_bundle_allowed(self):
        search = {"query": "(playstation 5 pro, ps5 pro)", "filters": {"category": "consoles", "listing_type": "buy_now_offer"}}
        cfg = DummyConfig()
        cover = item("Sony PlayStation 5 PRO Konsole Cover Ghost of Yotei Gold")
        vr_only = item("Sony PlayStation 5 PS5 PRO VR2 Brille inkl. Sense Controller")
        bundle = item("Sony PlayStation 5 Pro Konsole 2TB mit Controller")
        self.assertEqual(monitor.filter_results([cover, vr_only], search, cfg, skip_seen=True, is_statistics=True), [])
        self.assertEqual(len(monitor.filter_results([bundle], search, cfg, skip_seen=True, is_statistics=True)), 1)

    def test_bad_ids_and_germany_location(self):
        search = {"query": "iPhone 15 Pro Max", "filters": {"category": "phones", "listing_type": "buy_now_offer", "location": "de"}}
        banned = item("Apple iPhone 15 Pro Max 256GB", item_id="326775074774", price=300)
        foreign = item("Apple iPhone 15 Pro Max 256GB", item_id="200", price=300, location="Paris, FR")
        good = item("Apple iPhone 15 Pro Max 256GB", item_id="201", price=300, location="Berlin, DE")
        cfg = DummyConfig()
        result = monitor.filter_results([banned, foreign, good], search, cfg, skip_seen=True, is_statistics=True)
        self.assertEqual([x["item_id"] for x in result], ["201"])

    def test_samsung_s24_ultra_blocks_refurbished_and_known_seller(self):
        search = {"query": "samsung s24 ultra", "filters": {"category": "phones", "listing_type": "auction"}}
        cfg = DummyConfig()
        known_bad_seller = item(
            "Samsung Galaxy S24 Ultra 1TB Titanium Gray Android Smartphone sehr gut",
            item_id="206385453282",
            auction=True,
            buy_now=False,
            seller_name="Talk-Point GmbH",
            condition="Sehr gut",
            time_left="6d 16h",
        )
        refurbished = item(
            "Samsung Galaxy S24 Ultra 1TB Titanium Blue Android Smartphone sehr gut",
            item_id="206385453277",
            auction=True,
            buy_now=False,
            seller_name="ordinary-seller",
            condition="Sehr gut - Refurbished",
            time_left="6d 16h",
        )
        good = item(
            "Samsung Galaxy S24 Ultra 256GB Titanium Gray",
            item_id="200",
            auction=True,
            buy_now=False,
            seller_name="private-seller",
            condition="Gebraucht",
            time_left="6d 16h",
        )
        result = monitor.filter_results([known_bad_seller, refurbished, good], search, cfg, skip_seen=True, is_statistics=True)
        self.assertEqual([x["item_id"] for x in result], ["200"])

    def test_superstrike_search_is_wide_but_rejects_accessories(self):
        search = {"query": "PRO X 2 SUPERSTRIKE", "filters": {"category": "mice", "listing_type": "buy_now_offer"}}
        url = monitor._build_url_with_host("ebay.de", search)
        self.assertIn("logitech%20superstrike", url)
        self.assertNotIn("_sacat=", url)

        cfg = DummyConfig()
        mouse = item("Logitech G PRO X 2 SUPERSTRIKE Gaming-Maus Lunar Eclipse")
        skates = item("Corepad Skatez PRO Logitech G PRO X2 SUPERSTRIKE Mausfüße Hyperglide")
        mouseskates = item("EspTiger ICE V2 Mouseskates Logitech GPX Superlight 2 / Superstrike / SE")
        result = monitor.filter_results([mouse, skates, mouseskates], search, cfg, skip_seen=True, is_statistics=True)
        self.assertEqual([x["title"] for x in result], [mouse["title"]])

    def test_hybrid_bucket_prices(self):
        cfg = DummyConfig()
        hybrid = item(
            "Gaming PC RTX 5070 Ti Ryzen 7 32GB RAM",
            buy_now=True,
            auction=True,
            best_offer=False,
            price=3200,
            bin_price=3200,
            auc_price=2200,
            bin_total_price=3200,
            auc_total_price=2200,
        )
        buy_search = {"query": "5070 Ti PC", "filters": {"category": "computers", "listing_type": "buy_now_offer"}}
        auc_search = {"query": "5070 Ti PC", "filters": {"category": "computers", "listing_type": "auction"}}
        self.assertEqual(monitor.filter_results([hybrid.copy()], buy_search, cfg, skip_seen=True, is_statistics=True)[0]["total_price"], 3200)
        self.assertEqual(monitor.filter_results([hybrid.copy()], auc_search, cfg, skip_seen=True, is_statistics=True)[0]["total_price"], 2200)

    def test_ebay_de_location_param_stays_germany(self):
        url = monitor._build_url_with_host("ebay.de", {
            "query": "iPhone 15 Pro Max",
            "filters": {"category": "phones", "listing_type": "buy_now_offer", "location": "de"},
        })
        self.assertIn("LH_PrefLoc=1", url)


if __name__ == "__main__":
    unittest.main()
