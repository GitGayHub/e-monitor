#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa" / "inbox" / "manual_ebay_item_proofs.json"

# Item IDs found on live auction search pages for products whose stats
# report said Auktion = eBay block (run 2e765b45).
ITEMS = [
    ("LG UltraGear OLED 480", "https://www.ebay.de/itm/800354758653"),
    ("Odyssey G6 500Hz", "https://www.ebay.de/itm/158089021557"),
    ("Superstrike", "https://www.ebay.de/itm/307054017770"),
    ("4050 OLED laptop", "https://www.ebay.de/itm/366544657962"),
    ("4080 gaming PC", "https://www.ebay.de/itm/318574863266"),
    # secondary G6 / Superstrike for extra proof
    ("Odyssey G6 #2", "https://www.ebay.de/itm/147434459090"),
    ("Superstrike #2", "https://www.ebay.de/itm/198501672356"),
]


def main():
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(locale="de-DE").new_page()

        # DEX: re-search broader
        dex_url = (
            "https://www.ebay.de/sch/i.html?_nkw=superlight+2+dex"
            "&LH_Auction=1&_sop=15&rt=nc&_ipg=60"
        )
        print("DEX search", dex_url, flush=True)
        page.goto(dex_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        html = page.content()
        ids = []
        for m in re.finditer(r"/itm/(\d{9,15})", html):
            if m.group(1) not in ids:
                ids.append(m.group(1))
        print("DEX ids", ids[:10], flush=True)
        if ids:
            ITEMS.insert(0, ("DEX Superlight 2", f"https://www.ebay.de/itm/{ids[0]}"))

        for name, url in ITEMS:
            print("ITEM", name, url, flush=True)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2000)
                data = page.evaluate(
                    """() => {
                  const h1 = document.querySelector('h1');
                  const title = (h1 && h1.innerText) || document.title || '';
                  const priceEl = document.querySelector(
                    '[data-testid=\"x-price-primary\"], .x-price-primary, #prcIsum, .x-bin-price__content, .x-price-approx__price'
                  );
                  const price = (priceEl && priceEl.innerText) || '';
                  const body = document.body.innerText || '';
                  const isAuction = /Auktion|Gebot ab|Anzahl der Gebote|Place bid/i.test(body);
                  const isBin = /Sofort-Kaufen|Buy It Now/i.test(body);
                  return {
                    title: title.trim().slice(0, 180),
                    price: price.trim().slice(0, 80),
                    isAuction,
                    isBin,
                    href: location.href,
                  };
                }"""
                )
                data["name"] = name
                data["url"] = url
                out.append(data)
                print(
                    f"  title={data.get('title','')[:80]} | price={data.get('price')} | auction={data.get('isAuction')}",
                    flush=True,
                )
            except Exception as e:
                out.append({"name": name, "url": url, "error": str(e)})
                print("  ERR", e, flush=True)
            time.sleep(0.8)
        browser.close()

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n=== PROOF LINKS ===")
    for r in out:
        if r.get("error"):
            print(f"- {r['name']}: ERROR {r['error']}")
            continue
        print(f"- {r['name']}: {r.get('price') or '?'} | {r['url']}")
        print(f"  {r.get('title','')[:120]}")


if __name__ == "__main__":
    main()
