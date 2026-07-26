"""The price floor we send to eBay must not sit above the price we alert at.

`_prepare_monitor_fetch_search` raises the eBay `_udlo` above the plausibility
floor so a price-ascending page 1 is not all Hüllen und Folien. That raise was
applied without looking at `limit_price`, and on 2026-07-26 it produced searches
that could not match anything:

    Pixel 5        limit  70€   asked eBay for ≥120€
    sony ult wear  limit  30€   asked eBay for ≥ 80€

Live Pixel 5 lots at 9.40€ and 30.49€ were never even fetched.
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


def _floor(search):
    return (monitor._prepare_monitor_fetch_search(search).get("filters") or {}).get("min_price")


class FloorNeverAboveLimitTest(unittest.TestCase):
    def test_pixel_5_can_see_lots_under_its_limit(self):
        s = _search("Pixel 5", 70, category="phones")
        floor = _floor(s)
        self.assertIsNotNone(floor)
        self.assertLessEqual(
            float(floor), 70,
            "asking eBay for ≥120€ under a 70€ limit can only ever return «Дорого»",
        )
        # Still guarded against 5€ bait listings.
        self.assertGreaterEqual(float(floor), monitor._min_plausible_device_price(s))

    def test_normal_search_keeps_the_cosmetic_raise(self):
        """A limit well above the raise is untouched — page 1 stays clean."""
        s = _search("iPhone 15 Pro Max", 450, category="phones")
        self.assertEqual(float(_floor(s)), 120.0)

    def test_floor_equal_to_limit_is_left_alone(self):
        s = _search("logitech superlight 2", 45, category="mice")
        self.assertLessEqual(float(_floor(s)), 45)

    def test_impossible_search_is_reported_not_silently_empty(self):
        """ULT Wear at a 30€ limit: 80€ is what counts as a real unit, so the
        search cannot match — the log has to say so."""
        s = _search("sony ult wear", 30, category="headphones")
        with self.assertLogs(monitor.logger, level="WARNING") as logs:
            floor = _floor(s)
        self.assertTrue(
            any("cannot match anything" in line for line in logs.output),
            logs.output,
        )
        self.assertEqual(float(floor), monitor._min_plausible_device_price(s))

    def test_searches_without_a_limit_are_untouched(self):
        s = _search("samsung odyssey oled g6 500hz", None, category="monitors")
        self.assertEqual(float(_floor(s)), 150.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
