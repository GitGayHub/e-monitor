"""Genuine empty SERP must not be mistaken for a broken fetch.

eBay.de puts the null-search headline ("Keine exakten Treffer gefunden")
~150–200k into a ~400k document. The parser only scanned body[:12000], so a
truly empty auction market (11S Pro / 4080 PC / Odyssey G6 on 2026-07-26) came
back as the GH soft-empty "parse" — and the auction policy then reported
«⚠️ сбой загрузки» over a market that is honestly «❌ Не найдено».

Measured on the live pages that day:

    4080 (pc, …)   body_len=395177  'keine exakten treffer' @183989  itm=0
    odyssey g6     body_len=451990  'keine exakten treffer' @196973  itm=0
    superlight 2   body_len=905041  'we couldn'             @732829  itm=16

The last row is why "we couldn'…" is not deep-scanned: it also sits in the
footer of pages that DO have listings.
"""

import unittest

import monitor

CONTAINER = '<div class="srp-results srp-list clearfix">'
FILLER = "<!-- inline css/js head that eBay ships on every SERP -->" * 400


def _page(marker_html, *, container=True, items=0, head_filler=True):
    """Build a SERP-shaped document with the marker pushed past the 12k head."""
    parts = ["<html><head><title>eBay</title></head><body>"]
    if container:
        parts.append(CONTAINER)
    for i in range(items):
        parts.append(f'<li class="s-item"><a href="/itm/2860000000{i:02d}">x</a></li>')
    if head_filler:
        parts.append(FILLER)
    parts.append(marker_html)
    parts.append("</body></html>")
    return "".join(parts)


class DeepEmptyMarkerTest(unittest.TestCase):
    def test_german_null_search_deep_in_body_is_honest_empty(self):
        body = _page("<h2>Keine exakten Treffer gefunden</h2>")
        self.assertGreater(body.lower().find("keine exakten treffer"), 12000)
        items, err = monitor._parse_search_body(body, "ebay.de", "4080 pc")
        self.assertEqual(items, [])
        self.assertIsNone(err, "empty auction market must read «Не найдено», not a fetch failure")

    def test_marker_in_head_window_still_works(self):
        body = _page("<h2>Keine exakten Treffer gefunden</h2>", head_filler=False)
        self.assertLess(body.lower().find("keine exakten treffer"), 12000)
        items, err = monitor._parse_search_body(body, "ebay.de", "4080 pc")
        self.assertEqual((items, err), ([], None))

    def test_soft_empty_without_any_marker_stays_parse(self):
        """Container + zero listings + no null-search text = the GH soft-empty."""
        body = _page("<div>Ähnliche Suchen</div>")
        items, err = monitor._parse_search_body(body, "ebay.de", "nubia z80 ultra")
        self.assertEqual(items, [])
        self.assertEqual(err, "parse", "no marker anywhere → still worth a Playwright retry")

    def test_page_with_listings_is_never_deep_scanned(self):
        """'we couldn'…' lives in the footer of pages that have stock — and the
        parser failing on 16 listing links is markup drift, not an empty market."""
        body = _page("<footer>Sorry, we couldn't find what you need</footer>", items=16)
        items, err = monitor._parse_search_body(body, "ebay.de", "logitech superlight 2")
        self.assertEqual(items, [])
        self.assertEqual(err, "parse", "listings present → must retry, never claim empty")

    def test_generic_we_couldnt_is_not_a_deep_marker(self):
        """Footer boilerplate alone must not turn a dead fetch into «Не найдено»."""
        body = _page("<footer>we couldn't process your request</footer>")
        items, err = monitor._parse_search_body(body, "ebay.de", "4080 pc")
        self.assertEqual((items, err), ([], "parse"))

    def test_stealth_shell_without_container_stays_blocked(self):
        body = "<html><body>" + ("x" * 9000) + "</body></html>"
        items, err = monitor._parse_search_body(body, "ebay.de", "4080 pc")
        self.assertEqual(items, [])
        self.assertEqual(err, "blocked")


class AuctionEmptyEndToEndTest(unittest.TestCase):
    """The whole point: honest empty vs dead fetch must reach different labels."""

    def test_honest_empty_gives_no_error_so_bucket_reads_not_found(self):
        body = _page("<h2>Keine exakten Treffer gefunden</h2>")
        _, err = monitor._parse_search_body(body, "ebay.de", "samsung odyssey oled g6 500hz")
        self.assertIsNone(err)

    def test_dead_fetch_keeps_error_so_bucket_reads_load_failure(self):
        body = _page("<div>nothing here</div>")
        _, err = monitor._parse_search_body(body, "ebay.de", "samsung odyssey oled g6 500hz")
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
