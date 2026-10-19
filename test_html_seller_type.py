import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import monitor


class HtmlSellerTypeTest(unittest.TestCase):
    def test_pixel_pro_xl_aspect_keeps_both_modifiers(self):
        for query, expected in (("google pixel 9 pro xl", "Google Pixel 9 Pro XL"),
                                ("pixel 10 pro xl", "Google Pixel 10 Pro XL"),
                                ("pixel 9 pro", "Google Pixel 9 Pro"),
                                ("pixel 4 xl", "Google Pixel 4 XL"),
                                ("pixel 5", "Google Pixel 5")):
            with self.subTest(query=query):
                from urllib.parse import unquote
                self.assertEqual(expected, unquote(monitor._phone_model_aspect_params(query)["Modell"]))

    def test_actual_html_requests_keep_the_selected_seller_type(self):
        # ebay.de's seller controls produced LH_SellerType=2 for
        # "Gewerblicher Verkäufer" on 2026-10-19.
        for seller, expected in (("any", None), ("private", "1"), ("commercial", "2")):
            for listing in ("all", "buy_now", "auction"):
                search = {"id": "isolated", "query": "samsung s24 ultra", "filters": {
                    "seller_type": seller, "listing_type": listing, "location": "de",
                    "category": "phones", "condition": "any", "max_price": 2500,
                }}
                with self.subTest(seller=seller, listing=listing), patch.object(
                    monitor.config, "get_settings", return_value={"user_zip": "09648"}
                ):
                    urls = [monitor.build_ebay_url(search)]
                    urls.extend(monitor._build_url_with_host(host, search, sub=sub)
                                for host in ("ebay.de", "ebay.com") for sub in ("www", "m"))
                    for url in urls:
                        query = parse_qs(urlsplit(url).query)
                        self.assertEqual(None if expected is None else [expected], query.get("LH_SellerType"), url)
                        self.assertEqual([search["query"]], query["_nkw"])
                        self.assertEqual(["2500"], query["_udhi"])


if __name__ == "__main__":
    unittest.main()
