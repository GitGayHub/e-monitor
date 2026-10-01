import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock

import monitor
from mobile.merge_app_sync_to_config import app_search_to_config


def evaluate(case):
    search = app_search_to_config(case["search"])
    settings = case.get("settings", {})
    state = case.get("state", {})
    config = Mock()
    config.get_global_banned_sellers.return_value = state.get("bannedSellers", [])
    config.get_banned_item_ids.return_value = set(state.get("hiddenItems", []))
    config.get_item_hashes.return_value = set()
    config.get_settings.return_value = settings
    raw = copy.deepcopy(case["item"])
    monitor._calculate_total(raw, settings)
    if raw.get("auction") and raw.get("buy_now"):
        if search["filters"]["listing_type"] == "auction":
            raw.update(price=raw.get("auc_price", raw["price"]), total_price=raw.get("auc_total_price", raw["total_price"]), buy_now=False)
        elif search["filters"]["listing_type"] in ("buy_now", "buy_now_offer"):
            raw.update(price=raw.get("bin_price", raw["price"]), total_price=raw.get("bin_total_price", raw["total_price"]), auction=False)
    rows = monitor.filter_results([copy.deepcopy(case["item"])], search, config, skip_seen=True, is_statistics=True)
    if not search["enabled"]:
        return False, "disabled", raw["total_price"]
    if not rows:
        minimum = search["filters"].get("min_price")
        cheap = monitor._is_implausibly_cheap_device(raw, search) or (not raw.get("auction") and minimum is not None and raw["total_price"] < minimum)
        return False, "too_cheap" if cheap else "filtered", raw["total_price"]
    raw = rows[0]
    details = case.get("details")
    if details:
        if not monitor._details_match_contract(raw, search, details):
            return False, "filtered", raw["total_price"]
        monitor._refresh_candidate_details(raw, details, settings)
        rows = monitor.filter_results([copy.deepcopy(raw)], search, config, skip_seen=True, is_statistics=True)
        if not rows:
            minimum = search["filters"].get("min_price")
            cheap = monitor._is_implausibly_cheap_device(raw, search) or (not raw.get("auction") and minimum is not None and raw["total_price"] < minimum)
            over = not monitor._price_within_limit(raw, search) or (search["filters"].get("max_price") is not None and raw["price"] > search["filters"]["max_price"])
            return False, "too_cheap" if cheap else "over_limit" if over else "filtered", raw["total_price"]
        raw = rows[0]
    hard = search["filters"].get("max_price")
    if (hard is not None and raw["price"] > hard) or not monitor._price_within_limit(raw, search):
        return False, "over_limit", raw["total_price"]
    reason = monitor._notify_eligibility(raw, search)[1]
    if not search["notify"]:
        reason = "notifications_disabled"
    elif state.get("alreadySent"):
        reason = "already_sent"
    return True, reason, raw["total_price"]


class SharedParityTests(unittest.TestCase):
    def test_captured_live_cases(self):
        document = json.loads((Path(__file__).parent / "qa/fixtures/live_cases.json").read_text(encoding="utf-8"))
        for case in document["cases"]:
            with self.subTest(case=case["name"]):
                a, r, t = evaluate(case)
                self.assertEqual(case["expected"], {"accepted": a, "reason": r, "totalPrice": t})

    def test_same_cases_as_android(self):
        document = json.loads((Path(__file__).parent / "qa/fixtures/parity_cases.json").read_text(encoding="utf-8"))
        for case in document["cases"]:
            with self.subTest(case=case["name"]):
                accepted, reason, total = evaluate(case)
                expected = case["expected"]
                self.assertEqual(expected["accepted"], accepted)
                self.assertEqual(expected["reason"], reason)
                self.assertAlmostEqual(expected["totalPrice"], total, places=2)


if __name__ == "__main__":
    unittest.main()
