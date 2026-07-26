"""Auction SERP recovery — pure-Auktion buckets must never fake «Не найдено».

GH runners lose every auction SERP the same way: curl soft-empties, Chromium
dies with "Page crashed", then Browse API answers 0 items because
buyingOptions:{AUCTION} barely covers the auction market. That last 0 used to
be reported as a clean empty, which is what painted 11S / LG / G6 / 4080 /
Superlight pure Auktion as «Не найдено» while lots were live.
"""

import unittest
from unittest import mock

import monitor


def _search(listing_type, query="nubia z80 ultra"):
    return {
        "query": query,
        "filters": {
            "listing_type": listing_type,
            "location": "worldwide",
            "condition": "any",
            "max_price": 2500,
        },
    }


class LightSerpUrlTest(unittest.TestCase):
    """Last Chromium retry drops to a 25-card page — fewer cards, live renderer."""

    def test_rewrites_existing_ipg(self):
        self.assertEqual(
            monitor._pw_light_serp_url(
                "https://www.ebay.de/sch/i.html?_nkw=x&_ipg=60&LH_Auction=1"
            ),
            "https://www.ebay.de/sch/i.html?_nkw=x&_ipg=25&LH_Auction=1",
        )

    def test_appends_when_missing(self):
        self.assertEqual(
            monitor._pw_light_serp_url("https://www.ebay.de/sch/i.html?_nkw=x"),
            "https://www.ebay.de/sch/i.html?_nkw=x&_ipg=25",
        )

    def test_only_touches_the_real_param(self):
        self.assertEqual(
            monitor._pw_light_serp_url(
                "https://www.ebay.de/sch/i.html?_nkw=a_ipg=60&_ipg=60"
            ),
            "https://www.ebay.de/sch/i.html?_nkw=a_ipg=60&_ipg=25",
        )

    def test_keeps_auction_and_location_params(self):
        light = monitor._pw_light_serp_url(
            "https://www.ebay.de/sch/i.html?_nkw=x&_ipg=60&LH_Auction=1&LH_PrefLoc=3"
        )
        self.assertIn("LH_Auction=1", light)
        self.assertIn("LH_PrefLoc=3", light)


class BlockHeavyResourcesTest(unittest.TestCase):
    """Thumbnails are what blow the renderer up; we never parse them."""

    def _route(self, resource_type):
        route = mock.Mock()
        route.request.resource_type = resource_type
        monitor._pw_block_heavy(route)
        return route

    def test_images_media_fonts_aborted(self):
        for kind in ("image", "media", "font"):
            route = self._route(kind)
            route.abort.assert_called_once()
            route.continue_.assert_not_called()

    def test_document_and_script_pass(self):
        for kind in ("document", "script", "xhr", "stylesheet"):
            route = self._route(kind)
            route.continue_.assert_called_once()
            route.abort.assert_not_called()


class AuctionApiZeroTest(unittest.TestCase):
    """HTML transport-failed + Browse API 0 items: honest only for BIN."""

    def setUp(self):
        monitor._ebay_query_cache.clear()
        self._patches = [
            mock.patch.object(monitor, "EBAY_SOURCE", "auto"),
            mock.patch.object(monitor, "_ebay_api_circuit_open", False),
            mock.patch.object(monitor, "_ebay_block_until", 0),
            mock.patch.object(monitor, "_ebay_consecutive_blocks", 0),
            mock.patch.object(monitor, "_ebay_api_configured", return_value=True),
            mock.patch.object(monitor, "_search_query_variants", side_effect=lambda s: [s]),
            # curl chain soft-empties (container, itm=0) -> "parse", never a
            # confirmed empty SERP.
            mock.patch.object(monitor, "_do_fetch_one", return_value=([], "parse")),
            # Chromium: "Page.goto: Page crashed" on every attempt.
            mock.patch.object(monitor, "_do_fetch_playwright", return_value=([], "network")),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_auction_zero_is_transport_fail_not_empty(self):
        with mock.patch.object(monitor, "fetch_ebay_api_ex", return_value=([], None)):
            items, err = monitor.fetch_ebay_ex(_search("auction"), force=True)
        self.assertEqual(items, [])
        self.assertIn(
            err, ("network", "parse"),
            "auction API 0 after a dead HTML chain must stay a transport fail, "
            "otherwise the bucket prints «Не найдено» over a live auction",
        )

    def test_auction_zero_does_not_arm_cooldown(self):
        """One thin auction bucket is not an eBay outage."""
        with mock.patch.object(monitor, "fetch_ebay_api_ex", return_value=([], None)):
            monitor.fetch_ebay_ex(_search("auction"), force=True)
        self.assertEqual(monitor._ebay_consecutive_blocks, 0)
        self.assertLessEqual(monitor._ebay_block_until, 0)

    def test_buy_now_zero_stays_clean_empty(self):
        """Browse API covers fixed price properly — don't regress that."""
        monitor._ebay_query_cache.clear()
        with mock.patch.object(monitor, "fetch_ebay_api_ex", return_value=([], None)):
            items, err = monitor.fetch_ebay_ex(_search("buy_now_offer"), force=True)
        self.assertEqual((items, err), ([], None))

    def test_auction_items_from_api_still_win(self):
        """When the API does return auction lots, they're used as before."""
        api_items = [{"item_id": "1", "auction": True, "price": 60.0}]
        with mock.patch.object(monitor, "fetch_ebay_api_ex", return_value=(api_items, None)):
            items, err = monitor.fetch_ebay_ex(_search("auction"), force=True)
        self.assertEqual((items, err), (api_items, None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
