#!/usr/bin/env python3
"""Fetch auction SERP titles for products empty in latest stats."""
from __future__ import annotations

import re
import sys
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# reuse monitor parse if possible
try:
    from monitor import parse_ebay_results, filter_results, _statistics_search_variant
    import json
    HAS_MON = True
except Exception as e:
    print("monitor import failed", e)
    HAS_MON = False

QUERIES = [
    ("LG UltraGear", "lg ultragear oled 480", 150),
    ("G6 500", "samsung odyssey oled g6 500", 150),
    ("DEX", "g pro x superlight 2 dex", 40),
    ("4080 pc", "rtx 4080 gaming pc", 400),
    ("Pixel5", "google pixel 5", 30),
    ("Z70S", "nubia z70s ultra", 150),
    ("Strike", "logitech superstrike", 40),
    ("ULT", "sony ult wear", 20),
    ("Vivo", "asus vivobook 14x oled", 200),
    ("4060", "rtx 4060 oled notebook", 300),
]


def main():
    H = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9",
    }
    s = requests.Session()
    s.headers.update(H)
    for name, q, udlo in QUERIES:
        params = {
            "_nkw": q,
            "LH_Auction": "1",
            "_sop": "15",
            "_ipg": "60",
            "rt": "nc",
            "_udlo": str(udlo),
        }
        url = "https://www.ebay.de/sch/i.html?" + urllib.parse.urlencode(params)
        r = s.get(url, timeout=30)
        body = r.text or ""
        print(f"\n=== {name} sc={r.status_code} len={len(body)} udlo={udlo} ===")
        if HAS_MON:
            items = parse_ebay_results(body)
            print(f"parsed={len(items)}")
            for it in items[:8]:
                print(
                    f"  {it.get('item_id')} €{it.get('total_price')} "
                    f"auc={it.get('auction')} bin={it.get('buy_now')} "
                    f"| {(it.get('title') or '')[:70]}"
                )
            if not items:
                # show raw card titles
                soup = BeautifulSoup(body, "html.parser")
                cards = soup.select("li.s-card, li.s-item")[:5]
                print(f"raw cards={len(soup.select('li.s-card, li.s-item'))}")
                for c in cards:
                    t = c.get_text(" ", strip=True)[:120]
                    print("  raw:", t)
        else:
            soup = BeautifulSoup(body, "html.parser")
            for c in soup.select("li.s-card, li.s-item")[:6]:
                print(" ", c.get_text(" ", strip=True)[:100])


if __name__ == "__main__":
    main()
