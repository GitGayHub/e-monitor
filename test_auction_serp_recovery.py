"""Auction SERP recovery — pure-Auktion buckets must never fake «Не найдено».

GH runners lose every auction SERP the same way: curl soft-empties, Chromium
dies with "Page crashed", then Browse API answers 0 items because
buyingOptions:{AUCTION} barely covers the auction market. That last 0 used to
be reported as a clean empty, which is what painted 11S / LG / G6 / 4080 /
Superlight pure Auktion as «Не найдено» while lots were live.
"""

import re
import unittest
from unittest import mock

import monitor


def _glob_matches(glob, url):
    """Playwright URL-glob semantics: ** spans /, * does not, {a,b} alternates."""
    out = []
    i = 0
    while i < len(glob):
        if glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "{":
            j = glob.index("}", i)
            opts = glob[i + 1:j].split(",")
            out.append("(?:" + "|".join(re.escape(o) for o in opts) + ")")
            i = j + 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.fullmatch("".join(out), url) is not None


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
    """Thumbnails are what blow the renderer up; we never parse them.

    The handler is attached to asset URL globs only — routing "**/*" also
    intercepts the navigation, and continue_()-ing the document through eBay's
    redirect chain turned every GH crash into "Page.goto: net::ERR_ABORTED"
    (run 20:07 UTC: 3 crashes, 92 aborts, 0 pages). So anything that reaches
    this handler is an asset and gets aborted; a document that somehow
    over-matched a glob is let through.
    """

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

    def test_document_is_never_aborted(self):
        route = self._route("document")
        route.continue_.assert_called_once()
        route.abort.assert_not_called()

    def test_globs_never_match_a_serp_document(self):
        serp = "https://www.ebay.de/sch/i.html?_nkw=x&LH_Auction=1"
        for glob in monitor._PW_BLOCKED_URL_GLOBS:
            self.assertFalse(
                _glob_matches(glob, serp),
                f"{glob!r} would intercept the SERP navigation itself",
            )

    def test_globs_match_ebay_thumbnails(self):
        thumb = "https://i.ebayimg.com/images/g/abcAAOSw/s-l500.webp"
        self.assertTrue(
            any(_glob_matches(g, thumb) for g in monitor._PW_BLOCKED_URL_GLOBS),
            "eBay thumbnails must still be blocked",
        )


class EscalateOnFailureTest(unittest.TestCase):
    """The chain must not end on the first failure it has an answer for."""

    def test_page_crash_escalates(self):
        self.assertTrue(_escalates("Page.goto: Page crashed", 0))
        self.assertTrue(_escalates("Page.wait_for_timeout: Page crashed", 1))

    def test_net_aborted_escalates(self):
        # The GH failure mode after request interception was added.
        msg = "Page.goto: net::ERR_ABORTED at https://www.ebay.de/sch/i.html?_nkw=x"
        self.assertTrue(_escalates(msg, 0))
        self.assertTrue(_escalates(msg, 1))

    def test_timeout_escalates_once_only(self):
        msg = "Page.goto: Timeout 35000ms exceeded"
        self.assertTrue(_escalates(msg, 0))
        self.assertFalse(_escalates(msg, 1), "one timeout retry is the whole budget")

    def test_unknown_error_does_not_burn_attempts(self):
        self.assertFalse(_escalates("Executable doesn't exist", 0))


def _escalates(msg, attempt):
    return monitor._pw_should_escalate(msg, attempt)


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
