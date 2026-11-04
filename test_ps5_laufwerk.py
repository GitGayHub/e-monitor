import copy
import json
import unittest
from pathlib import Path
import monitor
from test_samsung_monitor_sku import Settings


class Ps5LaufwerkTests(unittest.TestCase):
    def test_ps5_pro_rejects_standalone_disc_drive_cover_and_console_excluded_details_across_four_formats(self):
        cases = json.loads((Path(__file__).parent / "qa/fixtures/ps5_laufwerk_nov04.json").read_text(encoding="utf-8"))["cases"]
        for case in cases:
            for listing, offer in [("buy_now", False), ("buy_now", True), ("auction", False), ("auction", True)]:
                with self.subTest(case=case["id"], listing=listing, offer=offer):
                    search = dict(
                        query=case["query"],
                        filters=dict(category="consoles", listing_type=listing, best_offer=offer, limit_price=750, location="worldwide"),
                    )
                    item = dict(
                        item_id=case["id"],
                        title=case["title"],
                        price=400,
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
                        categoryId="139971",
                        condition=case.get("condition") or "Gebraucht",
                        localizedAspects=case.get("aspects") or [],
                    )
                    accepted = bool(
                        monitor.filter_results([copy.deepcopy(item)], search, Settings(), skip_seen=True, is_statistics=True)
                    ) and monitor._details_match_contract(item, search, details)
                    self.assertEqual(case["expected"], accepted)
