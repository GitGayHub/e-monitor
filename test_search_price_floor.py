"""A price floor may guard against bait, never hide the find.

Measured on 2026-07-27: the mouse searches asked eBay for ≥40€ under a 45€
limit, so a live «Logitech Gaming Mouse PRO X SUPERLIGHT 2» at 30.50€ + 6.19
shipping (item 267731690074) was never fetched — the exact kind of lot this bot
exists for. Pixel 5 was worse: floor 120€ under a 70€ limit, a band where no
match can exist at all.

The floor is now capped at a quarter of the limit, which still throws out the
«XM6 ab 4€» multi-SKU bait that test_search_intent_rules pins down.
"""

import unittest

import monitor


def _search(query, limit, category="all", listing_type="auction"):
    return {
        "id": f"{query}_auc",
        "query": query,
        "filters": {
            "limit_price": limit,
            "max_price": 2500,
            "category": category,
            "listing_type": listing_type,
            "condition": "any",
            "location": "worldwide",
        },
    }


def _udlo(search):
    return (monitor._prepare_monitor_fetch_search(search).get("filters") or {}).get("min_price")


class FloorStaysOutOfTheDealBandTest(unittest.TestCase):
    def test_actual_statistics_request_does_not_hide_s24_low_opening_bid(self):
        # 960017889636: seller claims working S24, 51 + 6.99, 7 days left.
        # It must reach checks (its actual 8GB aspect then rejects it).
        s = _search("samsung s24 ultra",350,category="phones")
        variant=monitor._statistics_search_variant(s,"auction",min_price=50)
        self.assertIsNone(variant['filters']['min_price'])
        mixed=monitor._statistics_search_variant(s,"all",min_price=50)
        self.assertTrue(monitor._statistics_needs_auction_fetch(mixed['filters']['min_price'],True))
        self.assertTrue(monitor._statistics_needs_auction_fetch(None,False))
        self.assertFalse(monitor._statistics_needs_auction_fetch(None,True))
        purchase=monitor._statistics_search_variant(s,'buy_now',min_price=50)
        self.assertGreaterEqual(purchase['filters']['min_price'],50)

    def test_mouse_lot_just_under_the_limit_is_fetchable(self):
        s = _search("logitech superlight 2", 45, category="mice", listing_type="buy_now")
        self.assertLess(float(_udlo(s)), 36.69,
                        "the 36.69€ SUPERLIGHT 2 has to be inside the fetched band")

    def test_pixel_5_band_is_not_inverted(self):
        s = _search("Pixel 5", 70, category="phones", listing_type="buy_now")
        self.assertLess(float(_udlo(s)), 70, "asking for ≥120€ under a 70€ limit matches nothing")

    def test_low_limit_is_a_bet_not_a_misconfiguration(self):
        s = _search("sony ult wear", 30, category="headphones", listing_type="buy_now")
        self.assertLess(float(_udlo(s)), 30)

    def test_bait_floor_survives_on_a_high_limit(self):
        """A quarter of 200€ still rejects the 4-6€ «XM6» bait listings."""
        s = _search("Sony WH-1000XM6", 200, category="headphones")
        floor = monitor._min_plausible_device_price(s)
        self.assertGreaterEqual(floor, 50.0)
        for bait in (4.0, 6.0, 19.99):
            self.assertTrue(
                monitor._is_implausibly_cheap_device({"total_price": bait}, s),
                f"{bait}€ XM6 is bait, not a deal",
            )

    def test_a_real_steal_still_passes_on_a_high_limit(self):
        s = _search("Sony WH-1000XM6", 200, category="headphones")
        self.assertFalse(monitor._is_implausibly_cheap_device({"total_price": 65.0}, s))

    def test_big_market_keeps_a_usable_page_one(self):
        """iPhone: the floor still skips most accessory noise (≈112€ of 450€)."""
        s = _search("iPhone 15 Pro Max", 450, category="phones", listing_type="buy_now")
        self.assertGreater(float(_udlo(s)), 100)
        self.assertLessEqual(float(_udlo(s)), 450 * monitor._BAIT_FLOOR_SHARE_OF_LIMIT)

    def test_searches_without_a_limit_keep_the_old_floor(self):
        s = _search("samsung odyssey oled g6 500hz", None, category="monitors", listing_type="buy_now")
        self.assertEqual(float(_udlo(s)), 150.0)

    def test_real_s24_opening_bid_is_fetchable_and_waits_for_notification_time(self):
        # Browser audit 2026-10-05, 168761406827: original working SM-S928B/DS,
        # 1.50 EUR + 6.19 delivery; opening bid is not a fixed purchase price.
        s = _search("samsung s24 ultra", 350, category="phones")
        s["filters"]["min_price"] = 50
        self.assertIsNone(_udlo(s))
        row = {"auction": True, "buy_now": False, "price": 1.5,
               "total_price": 7.69, "time_left": "6T 22Std"}
        self.assertFalse(monitor._is_implausibly_cheap_device(row, s))
        self.assertEqual((False, "wait_24h"), monitor._notify_eligibility(row, s))
        row["time_left"] = "23Std"
        self.assertEqual((True, "notify"), monitor._notify_eligibility(row, s))

    def test_mixed_search_cannot_hide_auction_opening_bids(self):
        s = _search("sony ult wear", 30, category="headphones", listing_type="all")
        self.assertIsNone(_udlo(s))


if __name__ == "__main__":
    unittest.main(verbosity=2)
