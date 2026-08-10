import unittest
from unittest.mock import Mock, patch
import asyncio

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

    def test_laptop_screen_assembly_blocked_not_only_blacklist(self):
        """Zenbook + LCD-Schirm Komplett Baugruppe/Montage = spare, not a laptop."""
        search = {
            "query": "4050 OLED",
            "filters": {"category": "laptops", "listing_type": "buy_now", "location": "de"},
        }
        cfg = DummyConfig()
        spare = item(
            "Black ASUS Zenbook Pro 14 OLED UX6404VV-P4050W 3K LCD-Schirm Komplett Baugruppe",
            item_id="spare1",
            price=161,
        )
        montage = item(
            "Black ASUS Zenbook Pro 14 OLED UX6404VV-P4050W 3K LCD-Schirm Komplett Montage",
            item_id="spare2",
            price=161,
        )
        kept = monitor.filter_results([spare, montage], search, cfg, skip_seen=True, is_statistics=True)
        self.assertEqual(kept, [])

    def test_galaxybook_prelim_soft_when_details_can_satisfy(self):
        """Title without 4050/OLED still prelim-matches so details can accept or reject."""
        search = {
            "query": "4050 OLED",
            "filters": {"category": "laptops", "listing_type": "buy_now"},
        }
        title = "Samsung GalaxyBook4 Ultra 16 Intel Core Ultra 7 155H 512GB SSD 16GB RAM NVIDIA"
        tnorm = monitor._normalize(title)
        self.assertTrue(monitor._intent_prelim_matches_title(tnorm, search))
        # Details with GPU ok, cracked screen blocked by description check
        self.assertTrue(
            monitor._intent_details_match(
                search,
                item(title),
                {"description": "NVIDIA GeForce RTX 4050 6GB GDDR6 OLED"},
            )
        )
        self.assertTrue(
            monitor._is_description_blocked(
                "NVIDIA RTX 4050. Display Glas ist gesprungen, Touchscreen.",
                "laptops",
            )
        )

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
        self.assertEqual(
            monitor._search_query_variants(search),
            [
                "logitech superstrike",
                "logitech g pro x 2 superstrike",
                "logitech pro x2 superstrike",
                "superstrike lunar eclipse",
                "pro x 2 superstrike lunar eclipse",
            ],
        )

        cfg = DummyConfig()
        mouse = item("Logitech G PRO X 2 SUPERSTRIKE Gaming-Maus Lunar Eclipse")
        skates = item("Corepad Skatez PRO Logitech G PRO X2 SUPERSTRIKE Mausfüße Hyperglide")
        mouseskates = item("EspTiger ICE V2 Mouseskates Logitech GPX Superlight 2 / Superstrike / SE")
        plush = item(
            "Logitech G Superstrike Pro X2 Mouse Plushie Plush PAX EAST 2026 Exclusive",
            item_id="157860216770",
            price=32,
            total_price=32,
        )
        result = monitor.filter_results(
            [mouse, skates, mouseskates, plush], search, cfg, skip_seen=True, is_statistics=True
        )
        self.assertEqual([x["title"] for x in result], [mouse["title"]])

        noisy_details = {
            "title": "Logitech G PRO X 2 SUPERSTRIKE Gaming-Maus Lunar Eclipse",
            "description": "Recommended items mention mouse skates, but this listing is the actual Superstrike mouse.",
        }
        self.assertTrue(monitor._intent_details_match(search, mouse, noisy_details))
        self.assertFalse(monitor._matches_superstrike_mouse(monitor._normalize(plush["title"])))

    def test_redmagic_11_pro_rejects_9s_with_loose_11_in_title(self):
        """eBay title can list other devices in parentheses; model is next to brand."""
        query = monitor._normalize("Redmagic 11 Pro")
        # Live listing: RedMagic 9S Pro ... (8 Gen 3 10 11 GPD Ayn)
        wrong = monitor._normalize(
            "ZTE RedMagic 9S Pro 16/512GB Gaming Phone (8 Gen 3 10 11 GPD Ayn)"
        )
        good = monitor._normalize("ZTE Nubia RedMagic 11 Pro 16/512GB Gaming Phone")
        eleven_s = monitor._normalize("RedMagic 11S Pro 16/512GB")
        self.assertFalse(monitor._matches_redmagic_query(wrong, query))
        self.assertFalse(monitor._matches_phone_query_model(wrong, query))
        self.assertFalse(monitor._query_matches_title(wrong, "Redmagic 11 Pro"))
        self.assertTrue(monitor._matches_redmagic_query(good, query))
        self.assertTrue(monitor._matches_phone_query_model(good, query))
        self.assertFalse(monitor._matches_redmagic_query(eleven_s, query))

        cfg = DummyConfig()
        search = {
            "query": "Redmagic 11 Pro",
            "filters": {"category": "all", "listing_type": "buy_now_offer", "limit_price": 400},
        }
        bad_item = item(
            "ZTE RedMagic 9S Pro 16/512GB Gaming Phone (8 Gen 3 10 11 GPD Ayn)",
            item_id="117302336230",
            price=259,
            total_price=259,
        )
        good_item = item(
            "ZTE Nubia RedMagic 11 Pro 16/512GB Gaming Phone",
            item_id="200",
            price=350,
            total_price=350,
        )
        result = monitor.filter_results(
            [bad_item, good_item], search, cfg, skip_seen=True, is_statistics=True
        )
        self.assertEqual([x["item_id"] for x in result], ["200"])

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
        buy_result = monitor.filter_results([hybrid.copy()], buy_search, cfg, skip_seen=True, is_statistics=True)[0]
        auc_result = monitor.filter_results([hybrid.copy()], auc_search, cfg, skip_seen=True, is_statistics=True)[0]
        self.assertEqual(buy_result["total_price"], 3200)
        self.assertTrue(buy_result["buy_now"])
        self.assertFalse(buy_result["auction"])
        self.assertEqual(auc_result["total_price"], 2200)
        self.assertFalse(auc_result["buy_now"])
        self.assertTrue(auc_result["auction"])

    def test_merge_preserves_hybrid_auction_price_from_later_bucket(self):
        bin_seen_first = item(
            "Gaming PC RTX 5070 Ti Ryzen 7 32GB RAM",
            item_id="5070",
            buy_now=True,
            auction=True,
            price=3832,
            bin_price=3832,
            auc_price=3832,
            bin_total_price=3832,
            auc_total_price=3832,
        )
        auction_seen_later = item(
            "Gaming PC RTX 5070 Ti Ryzen 7 32GB RAM",
            item_id="5070",
            buy_now=False,
            auction=True,
            price=2200,
            bin_price=None,
            auc_price=2200,
            bin_total_price=None,
            auc_total_price=2200,
            bids_count=3,
            time_left="3d 18h",
        )
        merged = monitor._merge_items_by_id([bin_seen_first], [auction_seen_later])[0]
        self.assertEqual(merged["bin_price"], 3832)
        self.assertEqual(merged["auc_price"], 2200)
        self.assertEqual(merged["bin_total_price"], 3832)
        self.assertEqual(merged["auc_total_price"], 2200)
        self.assertTrue(merged["buy_now"])
        self.assertTrue(merged["auction"])

    def test_hybrid_auction_details_price_mismatch_ignores_bin_price(self):
        auction_item = item(
            "Gaming PC RTX 5070 Ti Ryzen 7 32GB RAM",
            buy_now=False,
            auction=True,
            price=2200,
            auc_price=2200,
            _was_hybrid=True,
        )
        details_with_only_bin_price = {"price": {"value": "3832", "currency": "EUR"}}
        mismatch, _, _ = monitor._details_price_mismatch(auction_item, details_with_only_bin_price)
        self.assertFalse(mismatch)

        details_with_wrong_bid = {
            "price": {"value": "3832", "currency": "EUR"},
            "currentBidPrice": {"value": "3832", "currency": "EUR"},
        }
        mismatch, scraped, api = monitor._details_price_mismatch(auction_item, details_with_wrong_bid)
        self.assertTrue(mismatch)
        self.assertEqual(scraped, 2200)
        self.assertEqual(api, 3832)

    def test_html_current_bid_price_is_extracted_from_hybrid_listing(self):
        html = """
        <html><body>
        <script>
        window.__ITEM__ = {
          "price":{"value":"3808.00","currency":"EUR"},
          "currentBidPrice":{"value":2720,"currency":"EUR"}
        };
        </script>
        <div class="x-bid-price">EUR 2.720,00</div>
        <button>Sofort-Kaufen</button>
        </body></html>
        """
        self.assertEqual(monitor._extract_html_current_bid_price(html), 2720)

    def test_hybrid_auction_recalculates_from_html_current_bid_not_bin_price(self):
        auction_item = item(
            "Gaming PC RTX 5070 Ti Ryzen 7 32GB RAM",
            buy_now=False,
            auction=True,
            price=3832,
            auc_price=3832,
            _was_hybrid=True,
        )
        details = {
            "price": {"value": "3808", "currency": "EUR"},
            "currentBidPrice": {"value": "2720", "currency": "EUR"},
            "buyingOptions": ["AUCTION", "FIXED_PRICE"],
        }
        monitor._calculate_total(auction_item, {"warn_non_eu": False}, details)
        self.assertEqual(auction_item["price"], 2720)
        self.assertEqual(auction_item["total_price"], 2720)
        self.assertEqual(auction_item["auc_total_price"], 2720)

    def test_validate_accepts_lower_details_price_for_buy_now(self):
        search = {"query": "samsung s24 ultra", "filters": {"category": "phones", "listing_type": "buy_now_offer"}}
        candidate = item(
            "Samsung Galaxy S24 Ultra - 256 GB - Titan Schwarz Graphite",
            item_id="117236309864",
            price=672,
            total_price=672,
            buy_now=True,
            auction=False,
            location="Erkner, Deutschland",
        )
        details = {
            "title": "Samsung Galaxy S24 Ultra - 256 GB - Titan Schwarz Graphite",
            "price": {"value": "430.0", "currency": "EUR"},
            "htmlShippingCost": {"value": "6.19", "currency": "EUR"},
            "itemLocationText": "Erkner, Deutschland",
        }
        with patch.object(monitor, "_fetch_item_details", return_value=details):
            ok, _ = asyncio.run(monitor._validate_candidate(candidate, search))
        self.assertTrue(ok)
        self.assertEqual(candidate["price"], 430.0)
        self.assertEqual(candidate["total_price"], 436.19)

    def test_cheapest_selection_uses_price_after_live_validation(self):
        search = {"query": "samsung s24 ultra", "filters": {"category": "phones", "listing_type": "buy_now_offer"}}
        first_by_card = item(
            "Samsung Galaxy S24 Ultra 256 GB Grau",
            item_id="236905989506",
            price=450,
            total_price=456.19,
            buy_now=True,
            auction=False,
        )
        cheaper_after_details = item(
            "Samsung Galaxy S24 Ultra - 256 GB - Titan Schwarz Graphite",
            item_id="117236309864",
            price=672,
            total_price=672,
            buy_now=True,
            auction=False,
        )
        details_by_id = {
            "236905989506": {
                "title": first_by_card["title"],
                "price": {"value": "450.0", "currency": "EUR"},
                "htmlShippingCost": {"value": "6.19", "currency": "EUR"},
            },
            "117236309864": {
                "title": cheaper_after_details["title"],
                "price": {"value": "430.0", "currency": "EUR"},
                "htmlShippingCost": {"value": "6.19", "currency": "EUR"},
            },
        }

        with patch.object(monitor, "_fetch_item_details", side_effect=lambda item_id: details_by_id[item_id]):
            selected = asyncio.run(monitor._select_cheapest_valid_candidate([first_by_card, cheaper_after_details], search))
        self.assertEqual(selected["item_id"], "117236309864")
        self.assertEqual(selected["total_price"], 436.19)

    def test_german_item_ignores_geo_inflated_shipping_from_details(self):
        search = {"query": "samsung s24 ultra", "filters": {"category": "phones", "listing_type": "buy_now_offer"}}
        candidate = item(
            "Samsung Galaxy S24 Ultra - 256 GB - Titan Schwarz Graphite",
            item_id="117236309864",
            price=672,
            total_price=672,
            buy_now=True,
            auction=False,
            location="Erkner, Deutschland",
        )
        details = {
            "title": candidate["title"],
            "price": {"value": "430.0", "currency": "EUR"},
            "htmlShippingCost": {"value": "242.40", "currency": "EUR"},
            "itemLocationText": "Erkner, Deutschland",
        }
        with patch.object(monitor, "_fetch_item_details", return_value=details):
            ok, _ = asyncio.run(monitor._validate_candidate(candidate, search))
        self.assertTrue(ok)
        self.assertEqual(candidate["price"], 430.0)
        self.assertEqual(candidate["shipping_cost"], 0)
        self.assertEqual(candidate["total_price"], 430.0)

    def test_cheapest_selection_stops_when_card_price_is_too_far(self):
        search = {"query": "samsung s24 ultra", "filters": {"category": "phones", "listing_type": "buy_now_offer"}}
        cheap = item("Samsung Galaxy S24 Ultra 256 GB Grau", item_id="1", price=450, total_price=450)
        far = item("Samsung Galaxy S24 Ultra 1TB", item_id="2", price=900, total_price=900)
        with patch.object(monitor, "_fetch_item_details", return_value={"title": cheap["title"], "price": {"value": "450", "currency": "EUR"}}) as fetch:
            selected = asyncio.run(monitor._select_cheapest_valid_candidate([cheap, far], search))
        self.assertEqual(selected["item_id"], "1")
        self.assertEqual(fetch.call_count, 1)

    def test_stable_version_reads_logic_version_file(self):
        """Version is the stamp in logic_version.txt, not git HEAD / run time."""
        import tempfile
        from pathlib import Path

        monitor._STABLE_VERSION_CACHE = None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                Path(tmp, "logic_version.txt").write_text(
                    "1980000000\n# comment\n", encoding="utf-8"
                )
                with patch.object(monitor, "_logic_version_path", return_value=str(Path(tmp, "logic_version.txt"))):
                    # re-bind reader path via open of our temp file
                    with patch.object(
                        monitor,
                        "_read_logic_version_timestamp",
                        return_value=1980000000,
                    ):
                        self.assertEqual(
                            monitor._get_stable_version_string(),
                            monitor._format_version_timestamp(1980000000),
                        )
            # Second call uses cache even if reader would fail
            self.assertEqual(
                monitor._get_stable_version_string(),
                monitor._format_version_timestamp(1980000000),
            )
        finally:
            monitor._STABLE_VERSION_CACHE = None

    def test_stable_version_stable_across_state_commit_times(self):
        """State commit times must not move the version stamp."""
        monitor._STABLE_VERSION_CACHE = None
        try:
            with patch.object(monitor, "_read_logic_version_timestamp", return_value=1980000000):
                v1 = monitor._get_stable_version_string()
            monitor._STABLE_VERSION_CACHE = None
            with patch.object(monitor, "_read_logic_version_timestamp", return_value=1980000000):
                v2 = monitor._get_stable_version_string()
            self.assertEqual(v1, v2)
            self.assertEqual(v1, monitor._format_version_timestamp(1980000000))
            # Simulated later state commit epoch must not appear
            self.assertNotEqual(v1, monitor._format_version_timestamp(2000000000))
        finally:
            monitor._STABLE_VERSION_CACHE = None

    def test_stable_version_never_uses_wall_clock_live(self):
        """Missing file -> unknown; never '(live)' and never time.time()."""
        monitor._STABLE_VERSION_CACHE = None
        try:
            with patch.object(
                monitor,
                "_read_logic_version_timestamp",
                side_effect=FileNotFoundError("missing"),
            ):
                ver = monitor._get_stable_version_string()
            self.assertEqual(ver, "unknown")
            self.assertNotIn("live", ver.lower())
        finally:
            monitor._STABLE_VERSION_CACHE = None

    def test_repo_logic_version_file_is_parseable(self):
        """Committed logic_version.txt must parse and format cleanly."""
        monitor._STABLE_VERSION_CACHE = None
        try:
            ts = monitor._read_logic_version_timestamp()
            self.assertIsInstance(ts, int)
            self.assertGreater(ts, 1_700_000_000)
            ver = monitor._get_stable_version_string()
            self.assertNotIn("live", ver.lower())
            self.assertNotEqual(ver, "unknown")
            self.assertRegex(ver, r"^\d{2}:\d{2} \d{1,2} ")
        finally:
            monitor._STABLE_VERSION_CACHE = None

    def test_ebay_de_location_param_stays_germany(self):
        url = monitor._build_url_with_host("ebay.de", {
            "query": "iPhone 15 Pro Max",
            "filters": {"category": "phones", "listing_type": "buy_now_offer", "location": "de"},
        })
        self.assertIn("LH_PrefLoc=1", url)

    def test_seen_state_migrates_list_and_stages(self):
        legacy = monitor._normalize_seen_payload(["111", "222"])
        self.assertTrue(legacy["111"]["initial"])
        self.assertFalse(legacy["111"]["final_hour"])
        staged = monitor._normalize_seen_payload({
            "111": {"initial": True, "final_hour": True},
            "333": {"initial": True, "final_hour": False},
        })
        self.assertTrue(staged["111"]["final_hour"])
        self.assertFalse(staged["333"]["final_hour"])

    def test_notify_candidates_initial_and_final_hour(self):
        monitor.seen_state.clear()
        fresh = item(
            "Apple iPhone 16 Pro Max 256GB",
            item_id="9001",
            price=600,
            total_price=600,
            buy_now=False,
            auction=True,
            best_offer=True,
            time_left="6д 23ч",
        )
        already = item(
            "Apple iPhone 16 Pro Max 256GB",
            item_id="9002",
            price=600,
            total_price=600,
            buy_now=False,
            auction=True,
            best_offer=False,
            time_left="45мин",
        )
        too_early = item(
            "Apple iPhone 16 Pro Max 256GB",
            item_id="9003",
            price=600,
            total_price=600,
            buy_now=False,
            auction=True,
            best_offer=False,
            time_left="5ч",
        )
        monitor.seen_state["9002"] = {"initial": True, "final_hour": False}
        monitor.seen_state["9003"] = {"initial": True, "final_hour": False}
        cands = monitor._notify_candidates_from_filtered([fresh, already, too_early])
        by_id = {c[0]["item_id"]: c[1] for c in cands}
        self.assertEqual(by_id.get("9001"), "initial")
        self.assertEqual(by_id.get("9002"), "final_hour")
        self.assertNotIn("9003", by_id)

    def test_samsung_odyssey_g6_500hz_intent_match(self):
        search = {
            "query": "samsung odyssey oled g6 500hz (G60SF, LS27FG602)",
            "filters": {"category": "monitors", "listing_type": "auction"},
        }
        intent = monitor._search_intent(search)
        self.assertEqual(intent["kind"], "samsung_odyssey_oled_g6")
        good = monitor._normalize("Samsung Odyssey OLED G6 G60SF 27 500Hz QHD")
        g60sd = monitor._normalize("Samsung Odyssey OLED G6 G60SD 360Hz")
        self.assertTrue(monitor._matches_samsung_odyssey_g6_500hz(good))
        self.assertFalse(monitor._matches_samsung_odyssey_g6_500hz(g60sd))
        self.assertTrue(monitor._intent_prelim_matches_title(good, search))
        self.assertFalse(monitor._intent_prelim_matches_title(g60sd, search))

    def test_notify_eligibility_matches_stats_green_rules(self):
        search = {
            "query": "Sony WH-1000XM6",
            "filters": {"limit_price": 200, "listing_type": "auction", "category": "all"},
        }
        # Regular auction under limit but 9 days left → NOT alertable (not green)
        long_auc = item(
            "Sony WH-1000XM6 Kopfhörer",
            item_id="1",
            price=120,
            total_price=120,
            buy_now=False,
            auction=True,
            best_offer=False,
            time_left="9д 12ч",
        )
        ok, reason = monitor._notify_eligibility(long_auc, search)
        self.assertFalse(ok)
        self.assertEqual(reason, "wait_24h")
        # Absurd 6€ floor is bait, not a real XM6
        bait_auc = item(
            "Sony WH-1000XM6",
            item_id="1b",
            price=6,
            total_price=6,
            buy_now=False,
            auction=True,
            best_offer=False,
            time_left="9д 12ч",
        )
        ok, reason = monitor._notify_eligibility(bait_auc, search)
        self.assertFalse(ok)
        self.assertEqual(reason, "too_cheap")

        # Auktion+ under limit → alertable (green)
        bo = item(
            "Sony WH-1000XM6",
            item_id="2",
            price=150,
            total_price=150,
            buy_now=False,
            auction=True,
            best_offer=True,
            time_left="4д 4ч",
        )
        ok, reason = monitor._notify_eligibility(bo, search)
        self.assertTrue(ok)
        self.assertEqual(reason, "notify")

        # Ending within 24h under limit → alertable
        soon = item(
            "Sony WH-1000XM6 Kopfhörer",
            item_id="3",
            price=120,
            total_price=120,
            buy_now=False,
            auction=True,
            best_offer=False,
            time_left="5ч",
        )
        ok, reason = monitor._notify_eligibility(soon, search)
        self.assertTrue(ok)

        # Over limit BIN → over_limit
        buy = item("Sony WH-1000XM6", item_id="4", price=246, total_price=246, buy_now=True)
        ok, reason = monitor._notify_eligibility(buy, search)
        self.assertFalse(ok)
        self.assertEqual(reason, "over_limit")

    def test_filter_blocks_multivariation_in_statistics(self):
        cfg = DummyConfig()
        search = {
            "query": "Sony WH-1000XM6",
            "filters": {"limit_price": 200, "listing_type": "all", "category": "all"},
        }
        bait = item(
            "Sony WH-1000XM6",
            item_id="mv1",
            price=4,
            total_price=4,
            buy_now=True,
            is_multivariation=True,
        )
        real = item(
            "Sony WH-1000XM6 Kopfhörer",
            item_id="real1",
            price=246,
            total_price=246,
            buy_now=True,
        )
        result = monitor.filter_results(
            [bait, real], search, cfg, skip_seen=True, is_statistics=True
        )
        ids = [x["item_id"] for x in result]
        self.assertNotIn("mv1", ids)
        self.assertIn("real1", ids)

    def test_prepare_monitor_fetch_uses_price_asc(self):
        search = {
            "id": "sony_wh_1000xm6_buy",
            "query": "Sony WH-1000XM6",
            "filters": {"listing_type": "buy_now_offer", "limit_price": 200, "max_price": 2500},
        }
        prepared = monitor._prepare_monitor_fetch_search(search)
        self.assertEqual(prepared["filters"]["sort"], "price_asc")
        self.assertGreaterEqual(prepared["filters"]["_ipg"], 240)

    def test_xm6_rejects_implausible_4_euro_floor(self):
        search = {
            "query": "Sony WH-1000XM6",
            "filters": {"limit_price": 200, "listing_type": "buy_now_offer", "category": "all"},
        }
        bait = item(
            "Sony WH-1000XM6",
            item_id="fake4",
            price=4,
            total_price=4,
            buy_now=True,
        )
        real = item(
            "Sony WH-1000XM6 – Premium Noise Cancelling Over-Ear Kopfhörer",
            item_id="real246",
            price=246,
            total_price=246,
            buy_now=True,
        )
        self.assertTrue(monitor._is_implausibly_cheap_device(bait, search))
        self.assertFalse(monitor._is_implausibly_cheap_device(real, search))
        ok, reason = monitor._notify_eligibility(bait, search)
        self.assertFalse(ok)
        self.assertEqual(reason, "too_cheap")
        cfg = DummyConfig()
        result = monitor.filter_results(
            [bait, real], search, cfg, skip_seen=True, is_statistics=True
        )
        self.assertEqual([x["item_id"] for x in result], ["real246"])


if __name__ == "__main__":
    unittest.main()
