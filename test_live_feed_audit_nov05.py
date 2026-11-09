import asyncio
import contextlib
import copy
import json
import unittest
from pathlib import Path
from unittest import mock
import monitor
from test_samsung_monitor_sku import Settings


class LiveFeedAuditNov05Tests(unittest.TestCase):
    def test_live_feed_audit_nov05_rejects_fake_checkout_refusal_and_refurbished_phone_across_four_formats(self):
        cases = json.loads((Path(__file__).parent / "qa/fixtures/live_feed_audit_nov05.json").read_text(encoding="utf-8"))["cases"]
        self.assertEqual(104, len(cases))
        cat_map = {
            "computers": "179",
            "consoles": "139971",
            "video_games": "139973",
            "laptops": "177",
            "glasses": "179247",
            "headphones": "112529",
            "mice": "23160",
            "monitors": "80053",
        }
        for case in cases:
            cat = case["category"]
            cat_id = cat_map.get(cat, "9355")
            for listing, offer in [("buy_now", False), ("buy_now", True), ("auction", False), ("auction", True)]:
                with self.subTest(case=case["id"], listing=listing, offer=offer):
                    search = dict(
                        query=case["query"],
                        filters=dict(category=cat, listing_type=listing, best_offer=offer, limit_price=950, location="worldwide"),
                    )
                    item = dict(
                        item_id=case["id"],
                        title=case["title"],
                        price=450,
                        shipping_cost=0,
                        currency="EUR",
                        condition=case.get("condition") or "Gebraucht",
                        location="DE",
                        seller_name="fixture",
                        buy_now=listing == "buy_now",
                        auction=listing == "auction",
                        best_offer=offer,
                        time_left="1h",
                    )
                    details = dict(
                        title=case["title"],
                        description=case["description"],
                        categoryId=cat_id,
                        condition=case.get("condition") or "Gebraucht",
                        localizedAspects=case.get("aspects") or [],
                    )
                    accepted = bool(
                        monitor.filter_results([copy.deepcopy(item)], search, Settings(), skip_seen=True, is_statistics=True)
                    ) and monitor._details_match_contract(item, search, details)
                    self.assertEqual(case["expected"], accepted)
        for repair_id in (
            "840075295375",
            "800855961434",
            "168826607496",
            "366766338960",
            "168815326073",
            "subordinate_neues_display_eingebaut_wurde",
            "subordinate_display_einbauen_lassen_habe",
            "oled_nachbau_display_verbaut",
        ):
            desc = next(c["description"] for c in cases if c["id"] == repair_id)
            self.assertEqual("замена дисплея в описании", monitor._phone_repair_label(desc), repair_id)
        for pos_id in ("pos_protector_einbauen_lassen", "pos_oled_display_schutzglas_einbauen_lassen", "pos_panzerglas_bekommen_wie_neues_display"):
            desc = next(c["description"] for c in cases if c["id"] == pos_id)
            self.assertIsNone(monitor._phone_repair_label(desc), pos_id)
        for dmg_id in ("880059658047", "336858997585", "366636708868", "genitive_glases_noch_beschaedigung", "einwandfrei_beschaedigung_rueckseitenglases"):
            desc = next(c["description"] for c in cases if c["id"] == dmg_id)
            self.assertTrue(monitor._is_description_blocked(desc, "phones"), dmg_id)
        for bastel_id in ("920032562655", "neg_bastelware_als_bastler"):
            desc = next(c["description"] for c in cases if c["id"] == bastel_id)
            self.assertTrue(monitor._is_description_blocked(desc, "laptops"), bastel_id)
        clean_bastel_desc = next(c["description"] for c in cases if c["id"] == "pos_keine_bastelware_control")
        self.assertFalse(monitor._is_description_blocked(clean_bastel_desc, "laptops"))
        for clean_id in (
            "pos_117485140188_gehaeuserand_no_abplatzungen",
            "pos_gehaeuserand_keine_kratzer_oder_abplatzungen",
            "pos_gehaeuserand_keine_risse_oder_abplatzungen",
            "pos_sentence_boundary_karton_beschaedigt_gehaeuserand",
        ):
            desc = next(c["description"] for c in cases if c["id"] == clean_id)
            self.assertFalse(monitor._is_description_blocked(desc, "phones"), clean_id)
        for ps5_neg_id in (
            "366766647537",
            "neg_umstieg_auf_ps5_pro_1tb",
            "neg_keine_ps5_pro_sondern_1tb",
            "neg_umstieg_ps5_pro_slim_cfi2016",
            "neg_aspect_1tb_with_umstieg_ps5_pro",
        ):
            case = next(c for c in cases if c["id"] == ps5_neg_id)
            self.assertTrue(monitor._console_pro_details_conflict(case["description"], case.get("aspects") or []), ps5_neg_id)
        for ps5_pos_id in ("pos_307249528143_ps5_pro_2tb", "pos_206653329869_ps5_pro_2tb", "pos_ps5_pro_with_1tb_m2_nvme_ssd"):
            case = next(c for c in cases if c["id"] == ps5_pos_id)
            self.assertFalse(monitor._console_pro_details_conflict(case["description"], case.get("aspects") or []), ps5_pos_id)
        dummy_desc = next(c["description"] for c in cases if c["id"] == "168767384103")
        self.assertTrue(monitor._is_description_blocked(dummy_desc, "glasses"))
        clean_dummy_desc = next(c["description"] for c in cases if c["id"] == "pos_kein_dummy_keine_attrappe_control")
        self.assertFalse(monitor._is_description_blocked(clean_dummy_desc, "glasses"))
        buegel_desc = next(c["description"] for c in cases if c["id"] == "358980147281")
        self.assertTrue(monitor._is_description_blocked(buegel_desc, "headphones"))
        clean_buegel_desc = next(c["description"] for c in cases if c["id"] == "pos_buegel_nicht_gebrochen_control")
        self.assertFalse(monitor._is_description_blocked(clean_buegel_desc, "headphones"))
        for pc_neg_id in ("820297407765", "820289201652", "314609424430", "314313513318", "197189667857", "neg_pc_ohne_ssd_optional_aufpreis"):
            case = next(c for c in cases if c["id"] == pc_neg_id)
            self.assertTrue(monitor._pc_details_blocked(case["title"], case["description"], case.get("aspects") or []), pc_neg_id)
        for pc_pos_id in ("pos_pc_1tb_nvme_ssd_ohne_hdd_with_32gb_ram", "pos_pc_ryzen_7500f_ohne_igpu_with_1tb_ssd"):
            case = next(c for c in cases if c["id"] == pc_pos_id)
            self.assertFalse(monitor._pc_details_blocked(case["title"], case["description"], case.get("aspects") or []), pc_pos_id)
        for ref_neg_id in ("287601433129", "287614268217", "neg_iphone_heading_generalueberholtes_smartphone"):
            case = next(c for c in cases if c["id"] == ref_neg_id)
            self.assertTrue(monitor._phone_description_refurbished(case["description"]), ref_neg_id)
        for ref_pos_id in ("pos_168834686569_s25_edge_used_clean", "pos_phone_heading_nicht_refurbished_control"):
            case = next(c for c in cases if c["id"] == ref_pos_id)
            self.assertFalse(monitor._phone_description_refurbished(case["description"]), ref_pos_id)
        sony_pos = next(c for c in cases if c["id"] == "146970168537")
        self.assertFalse(monitor._is_category_blocked_title(monitor._normalize(sony_pos["title"]), "headphones"))
        sony_neg = next(c for c in cases if c["id"] == "neg_sony_ersatz_kopf_hoerer_kopfbuegel_over_ear")
        self.assertTrue(monitor._is_category_blocked_title(monitor._normalize(sony_neg["title"]), "headphones"))
        for it_neg_id in ("880046283886", "neg_mouse_plural_non_funzionano_tasti_laterali"):
            case = next(c for c in cases if c["id"] == it_neg_id)
            self.assertTrue(monitor._is_description_blocked(case["description"], "mice"), it_neg_id)
        it_pos = next(c for c in cases if c["id"] == "pos_mouse_italian_funziona_perfettamente_non_ha_difetti")
        self.assertFalse(monitor._is_description_blocked(it_pos["description"], "mice"))
        for gap_neg_id in ("237153823130", "neg_phone_spalt_zwischen_backcover_und_gehaeuse"):
            case = next(c for c in cases if c["id"] == gap_neg_id)
            self.assertTrue(monitor._is_description_blocked(case["description"], "phones"), gap_neg_id)
        for gap_pos_id in ("pos_237153442701_iphone17pm_same_seller_no_gap", "pos_phone_kein_spalt_zwischen_display_und_rahmen"):
            case = next(c for c in cases if c["id"] == gap_pos_id)
            self.assertFalse(monitor._is_description_blocked(case["description"], "phones"), gap_pos_id)
        for px_neg_id in ("128166358435", "neg_phone_french_pixel_mort_sur_ecran"):
            case = next(c for c in cases if c["id"] == px_neg_id)
            self.assertTrue(monitor._is_description_blocked(case["description"], "phones"), px_neg_id)
        px_pos = next(c for c in cases if c["id"] == "pos_phone_no_dead_pixels_aucun_pixel_mort")
        self.assertFalse(monitor._is_description_blocked(px_pos["description"], "phones"))
        for app_neg_id in ("198752283128", "198751852883"):
            case = next(c for c in cases if c["id"] == app_neg_id)
            self.assertTrue(monitor._is_description_blocked(case["description"], "headphones"), app_neg_id)
        app_pos = next(c for c in cases if c["id"] == "pos_headphone_sony_app_verbindet_sich_problemlos")
        self.assertFalse(monitor._is_description_blocked(app_pos["description"], "headphones"))
        rb_117 = next(c for c in cases if c["id"] == "117510764552")
        self.assertTrue(monitor._rayban_meta_gen2_accessory_or_part(monitor._normalize(rb_117["title"])))
        self.assertTrue(monitor._rayban_meta_gen2_details_blocked(rb_117["description"], rb_117.get("aspects") or []))
        rb_desc_only = next(c for c in cases if c["id"] == "neg_rayban_desc_ohne_glaeser_only")
        self.assertFalse(monitor._rayban_meta_gen2_accessory_or_part(monitor._normalize(rb_desc_only["title"])))
        self.assertTrue(monitor._rayban_meta_gen2_details_blocked(rb_desc_only["description"], rb_desc_only.get("aspects") or []))
        rb_pos = next(c for c in cases if c["id"] == "pos_rayban_glaeser_ohne_sehstaerke")
        self.assertFalse(monitor._rayban_meta_gen2_details_blocked(rb_pos["description"], rb_pos.get("aspects") or []))

    def test_fetch_normal_slice_scales_budget_for_multi_alias_searches(self):
        recorded_slices = []

        @contextlib.contextmanager
        def fake_slice(seconds, reserve=0):
            recorded_slices.append((seconds, reserve))
            yield mock.MagicMock(exhausted=lambda margin=0: True, html_task_started=False)

        with mock.patch.object(monitor.MonitorPassBudget, "slice", side_effect=fake_slice), \
             mock.patch.object(monitor, "fetch_ebay_ex", return_value=([], None)), \
             mock.patch.object(monitor.browse_access, "note_normal_outcome"):
            # 6 aliases x 2 formats = 12 tasks -> min(35, 12*8) = 35s
            asyncio.run(monitor._fetch_normal_slice(
                {"id": "ray_ban_meta_gen_2", "query": "Ray-Ban Meta Gen 2", "filters": {"category": "all", "listing_type": "all"}},
                force=True,
            ))
            # 8 aliases x 1 format = 8 tasks -> min(35, 8*8) = 35s
            asyncio.run(monitor._fetch_normal_slice(
                {"id": "4080_pc_auc", "query": "4080 (pc, rechner, computer, desktop, gaming pc)", "filters": {"category": "computers", "listing_type": "auction"}},
                force=True,
            ))
            # 4 aliases x 1 format = 4 tasks (>= 3) -> min(35, 4*8) = 32s (fits all 4 tasks + reserve=8)
            asyncio.run(monitor._fetch_normal_slice(
                {"id": "iphone_17_pro_buy", "query": "iphone 17 pro", "filters": {"category": "phones", "listing_type": "buy_now"}},
                force=True,
            ))
            # 1 alias x 1 format = 1 task (< 3) -> 20s default
            asyncio.run(monitor._fetch_normal_slice(
                {"id": "meta_quest_3_buy", "query": "meta quest 3", "filters": {"category": "vr_headsets", "listing_type": "buy_now"}},
                force=True,
            ))

        self.assertEqual([(35, 30), (35, 30), (32, 30), (20, 30)], recorded_slices)
