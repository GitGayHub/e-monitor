#!/usr/bin/env python3
import re
import sys
import urllib.parse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from monitor import parse_ebay_results, _normalize  # noqa: E402

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
}
ACC = ("hulle", "huelle", "case", "cover", "folie", "ersatz", "back cover", "schutz", "skin")


def check(label, query, listing, udlo=50):
    p = {
        "_nkw": query,
        "_sop": "15",
        "_ipg": "60",
        "rt": "nc",
        "_udlo": str(udlo),
    }
    if listing == "auction":
        p["LH_Auction"] = "1"
    else:
        p["LH_BIN"] = "1"
    url = "https://www.ebay.de/sch/i.html?" + urllib.parse.urlencode(p)
    s = requests.Session()
    s.headers.update(H)
    try:
        r = s.get(url, timeout=30)
    except Exception as e:
        print(f"{label:30} ERR {e}")
        return
    items = parse_ebay_results(r.text or "") if r.status_code == 200 else []
    good = []
    for it in items:
        tn = _normalize(it.get("title") or "")
        if any(x in tn for x in ACC):
            continue
        good.append(it)
    prices = sorted(
        float(it.get("total_price") or it.get("price") or 0)
        for it in good
        if (it.get("total_price") or it.get("price"))
    )
    sample = (good[0].get("title") if good else "")[:60]
    print(
        f"{label:30} sc={r.status_code:3} raw={len(items):3} keep={len(good):3} "
        f"cheapest={prices[0] if prices else None} id={good[0].get('item_id') if good else None}"
    )
    if sample:
        print(f"    {sample}")


def main():
    for row in (
        ("Z80 Ultra BIN", "Nubia Z80 Ultra", "bin", 100),
        ("Z80 Ultra AUC", "Nubia Z80 Ultra", "auction", 100),
        ("Z80 LV BIN", "Nubia Z80 Ultra Leading", "bin", 100),
        ("Z80 LV AUC", "Nubia Z80 Ultra Leading", "auction", 100),
        ("Z80 LV BIN alt", "nubia z80 ultra leading version", "bin", 100),
        ("RM11S AUC", "redmagic 11s pro", "auction", 50),
        ("LG AUC", "lg ultragear oled 480", "auction", 150),
        ("G6 AUC", "samsung odyssey oled g6 500", "auction", 150),
        ("4080 AUC", "rtx 4080 gaming pc", "auction", 400),
        ("Superlight AUC", "g pro x superlight 2", "auction", 40),
        ("DEX AUC", "g pro x superlight 2 dex", "auction", 40),
        ("ULT AUC", "sony ult wear", "auction", 20),
    ):
        check(*row)


if __name__ == "__main__":
    main()
