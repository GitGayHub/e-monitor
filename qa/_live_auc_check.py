#!/usr/bin/env python3
"""Live auction existence check for products empty on Auktion in stats."""
from __future__ import annotations

import re
import urllib.parse

from curl_cffi import requests as cr

QUERIES = [
    ("4050 oled", "rtx 4050 oled notebook"),
    ("4080 pc", "rtx 4080 gaming pc"),
    ("LG UltraGear", "lg ultragear oled 480"),
    ("G6 500", "samsung odyssey oled g6 500"),
    ("DEX", "g pro x superlight 2 dex"),
    ("Z70S", "nubia z70s ultra"),
    ("Pixel5", "google pixel 5"),
    ("ULT Wear", "sony ult wear"),
    ("Superstrike", "logitech superstrike"),
    ("VivoBook", "asus vivobook 14x oled"),
    ("Z80 LV", "nubia z80 ultra leading version"),
    ("4060 oled", "rtx 4060 oled notebook"),
]


def main():
    s = cr.Session(impersonate="chrome131")
    for name, q in QUERIES:
        params = {
            "_nkw": q,
            "LH_Auction": "1",
            "_sop": "15",
            "_ipg": "60",
            "rt": "nc",
        }
        url = "https://www.ebay.de/sch/i.html?" + urllib.parse.urlencode(params)
        try:
            r = s.get(url, timeout=25)
            body = r.text or ""
            ids = re.findall(r"/itm/(\d{9,15})", body)
            uniq = sorted(set(ids))
            # crude price scrape
            prices = re.findall(r"(?:EUR|€)\s*([\d]+[.,]\d{2})|([\d]+[.,]\d{2})\s*(?:EUR|€)", body)
            flat = [a or b for a, b in prices][:6]
            nores = any(
                x in body.lower()
                for x in ("kein ergebnis", "keine treffer", "0 ergebnisse", "no exact matches")
            )
            print(
                f"{name:14} sc={r.status_code} len={len(body):6d} "
                f"itm_uniq={len(uniq):3d} nores={nores} prices={flat[:4]} ids={uniq[:3]}"
            )
        except Exception as e:
            print(f"{name:14} ERR {e}")


if __name__ == "__main__":
    main()
