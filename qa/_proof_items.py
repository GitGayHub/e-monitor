#!/usr/bin/env python3
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "qa" / "inbox" / "manual_item_proofs_final.json"

# IDs taken from LIVE LH_Auction=1 search HTML (local Chromium) for products
# where GH stats reported Auktion = eBay block.
ITEMS = [
    ("LG UltraGear OLED (stats: Auktion block)", "https://www.ebay.de/itm/800354758653"),
    ("Superstrike from auction SERP", "https://www.ebay.de/itm/307054017770"),
    ("4050 OLED from auction SERP", "https://www.ebay.de/itm/366544657962"),
    ("4080 PC from auction SERP", "https://www.ebay.de/itm/318574863266"),
    ("extra Superstrike #2", "https://www.ebay.de/itm/198501672356"),
    ("extra 4050 #2", "https://www.ebay.de/itm/188651788125"),
    ("extra 4080 #2", "https://www.ebay.de/itm/188632270709"),
    # G6 SERP ids (need title check — earlier one was G7 false positive)
    ("G6 SERP id 147434459090", "https://www.ebay.de/itm/147434459090"),
    ("G6 SERP id 307058840033", "https://www.ebay.de/itm/307058840033"),
]


def main():
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for name, url in ITEMS:
            ctx = browser.new_context(
                locale="de-DE",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()
            rec = {"name": name, "url": url}
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                data = page.evaluate(
                    """() => {
                  const t = (document.querySelector('h1') || {}).innerText || document.title || '';
                  const p = (document.querySelector('[data-testid=\"x-price-primary\"], .x-price-primary, #prcIsum') || {}).innerText || '';
                  const body = document.body.innerText || '';
                  return {
                    title: t.trim().slice(0, 180),
                    price: p.trim().slice(0, 80),
                    auction: /Auktion|Gebot ab|Anzahl der Gebote|Place bid/i.test(body),
                    bin: /Sofort-Kaufen|Buy It Now/i.test(body),
                  };
                }"""
                )
                rec.update(data)
                print(
                    f"OK {name}\n   {rec.get('price')} | auction={rec.get('auction')} bin={rec.get('bin')}\n   {rec.get('title')}\n   {url}",
                    flush=True,
                )
            except Exception as e:
                rec["error"] = str(e)
                print(f"ERR {name}: {e}", flush=True)
            out.append(rec)
            ctx.close()
            time.sleep(0.6)
        browser.close()
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
