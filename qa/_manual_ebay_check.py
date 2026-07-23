#!/usr/bin/env python3
"""Live browser check: products that stats marked Auktion=eBay block."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa" / "inbox" / "manual_ebay_block_check.json"

# From last stats (2e765b45): Auktion showed ⚠️ eBay block while Sofort had prices.
QUERIES = [
    ("DEX", "logitech superlight 2 dex", 40),
    ("LG UltraGear OLED 480", "lg ultragear oled 480hz", 150),
    ("Odyssey G6 500Hz", "samsung odyssey oled g6 500hz", 150),
    ("Superstrike", "logitech superstrike", 40),
    ("4050 OLED", "rtx 4050 oled", 300),
    ("4080 PC", "rtx 4080 gaming pc", 400),
]


def main():
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="de-DE",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()
        for name, q, minp in QUERIES:
            nkw = q.replace(" ", "+")
            url = (
                f"https://www.ebay.de/sch/i.html?_nkw={nkw}"
                f"&LH_Auction=1&_sop=15&_udlo={minp}&rt=nc&_ipg=60"
            )
            print("OPEN", name, url, flush=True)
            rec = {"name": name, "query": q, "search_url": url, "top": [], "error": None}
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3000)
                rec["page_title"] = page.title()
                rec["final_url"] = page.url
                items = page.evaluate(
                    """() => {
                  const out = [];
                  const cards = document.querySelectorAll(
                    '.s-item, li.s-card, .srp-results li, ul.srp-results > li'
                  );
                  for (const c of cards) {
                    const a = c.querySelector('a[href*="/itm/"]');
                    if (!a) continue;
                    const m = a.href.match(/\\/itm\\/(\\d+)/);
                    if (!m) continue;
                    const tEl = c.querySelector('.s-item__title, .s-card__title, h3, .su-styled-text');
                    const pEl = c.querySelector('.s-item__price, .s-card__price, .s-card__attribute-row span');
                    const t = (tEl && tEl.innerText) || a.innerText || '';
                    const pr = (pEl && pEl.innerText) || '';
                    if (/shop on ebay/i.test(t)) continue;
                    out.push({
                      id: m[1],
                      title: t.trim().slice(0, 140),
                      price: pr.trim().slice(0, 50),
                      url: 'https://www.ebay.de/itm/' + m[1],
                    });
                    if (out.length >= 6) break;
                  }
                  return out;
                }"""
                )
                # fallback from raw html
                if not items:
                    html = page.content()
                    ids = []
                    seen = set()
                    for m in re.finditer(r"/itm/(\d{9,15})", html):
                        if m.group(1) not in seen:
                            seen.add(m.group(1))
                            ids.append(m.group(1))
                    items = [
                        {
                            "id": i,
                            "title": "(title not parsed)",
                            "price": "?",
                            "url": f"https://www.ebay.de/itm/{i}",
                        }
                        for i in ids[:6]
                    ]
                    rec["fallback_html_ids"] = len(ids)
                rec["top"] = items
                rec["n"] = len(items)
                print(
                    f"  -> {len(items)} listings; first={items[0]['url'] if items else None}",
                    flush=True,
                )
            except Exception as e:
                rec["error"] = str(e)
                print("  ERR", e, flush=True)
            out.append(rec)
            time.sleep(1.2)
        browser.close()

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("WROTE", OUT)
    # print human summary
    print("\n=== SUMMARY ===")
    for r in out:
        print(f"\n{r['name']} | stats said Auktion eBay block")
        print(f"  search: {r['search_url']}")
        if r.get("error"):
            print(f"  browser error: {r['error']}")
            continue
        if not r.get("top"):
            print("  browser: 0 auction listings parsed (may be empty or challenge)")
            continue
        for it in r["top"][:3]:
            print(f"  FOUND {it['price']:>12}  {it['url']}")
            print(f"         {it['title'][:100]}")


if __name__ == "__main__":
    main()
