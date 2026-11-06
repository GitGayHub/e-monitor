import copy
import json
import unittest
from pathlib import Path
import monitor
from test_samsung_monitor_sku import Settings


class LiveFeedAuditNov05Tests(unittest.TestCase):
    def test_live_feed_audit_nov05_rejects_fake_checkout_refusal_and_refurbished_phone_across_four_formats(self):
        cases = json.loads((Path(__file__).parent / "qa/fixtures/live_feed_audit_nov05.json").read_text(encoding="utf-8"))["cases"]
        self.assertEqual(42, len(cases))
        for case in cases:
            cat = case["category"]
            cat_id = {"computers": "179", "consoles": "139971"}.get(cat, "9355")
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
            "subordinate_neues_display_eingebaut_wurde",
            "subordinate_display_einbauen_lassen_habe",
            "oled_nachbau_display_verbaut",
        ):
            desc = next(c["description"] for c in cases if c["id"] == repair_id)
            self.assertEqual("замена дисплея в описании", monitor._phone_repair_label(desc), repair_id)
        for pos_id in ("pos_protector_einbauen_lassen", "pos_oled_display_schutzglas_einbauen_lassen", "pos_panzerglas_bekommen_wie_neues_display"):
            desc = next(c["description"] for c in cases if c["id"] == pos_id)
            self.assertIsNone(monitor._phone_repair_label(desc), pos_id)
        for dmg_id in ("880059658047", "336858997585", "genitive_glases_noch_beschaedigung", "einwandfrei_beschaedigung_rueckseitenglases"):
            desc = next(c["description"] for c in cases if c["id"] == dmg_id)
            self.assertTrue(monitor._is_description_blocked(desc, "phones"), dmg_id)
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

