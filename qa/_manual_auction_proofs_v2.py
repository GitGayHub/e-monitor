#!/usr/bin/env python3
"""Prove: stats said Auktion eBay block, live browser finds real auctions."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa" / "inbox" / "manual_auction_proofs_v2.json"

# Product label from stats (Auktion was eBay block) + search + title must-match tokens
CASES = [
    {
        "stats_name": "LG UltraGear OLED",
        "query": "lg ultragear oled 480",
        "must_any": ["ultragear", "480", "gx790", "32gs95", "27gx790"],
        "must_not": ["hülle", "folie", "schutz"],
        "min_price": 150,
    },
    {
        "stats_name": "Samsung Odyssey OLED G6 500Hz",
        "query": "samsung odyssey oled g6 500",
        "must_any": ["g6", "g60sf", "ls27fg602", "ls27fg604", "500"],
        "must_not": ["g7", "g5", "360", "g60sd"],
        "min_price": 150,
    },
    {
        "stats_name": "PRO X 2 SUPERSTRIKE",
        "query": "logitech superstrike",
        "must_any": ["superstrike", "pro x 2"],
        "must_not": ["hülle", "case"],
        "min_price": 40,
    },
    {
        "stats_name": "4050 oled",
        "query": "rtx 4050 oled notebook",
        "must_any": ["4050", "oled"],
        "must_not": ["hülle", "tasche"],
        "min_price": 300,
    },
    {
        "stats_name": "4080 (pc)",
        "query": "rtx 4080 gaming pc",
        "must_any": ["4080"],
        "must_not": ["laptop", "notebook", "mobil"],
        "min_price": 400,
    },
    {
        "stats_name": "logitech superlight 2 dex",
        "query": "g pro x superlight 2 dex",
        "must_any": ["dex", "superlight"],
        "must_not": ["dongle only", "hülle"],
        "min_price": 40,
    },
]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower())


def title_ok(title: str, case: dict) -> bool:
    t = norm(title)
    if not t or "shop on ebay" in t:
        return False
    if any(x in t for x in case["must_not"]):
        return False
    return any(x in t for x in case["must_any"])


def extract_cards(page):
    return page.evaluate(
        """() => {
      const out = [];
      const nodes = document.querySelectorAll('li.s-card, li.s-item, .srp-results li');
      for (const n of nodes) {
        const a = n.querySelector('a[href*=\"/itm/\"]');
        if (!a) continue;
        const m = (a.href || '').match(/\\/itm\\/(\\d{9,15})/);
        if (!m) continue;
        let title = '';
        const t1 = n.querySelector('.s-card__title, .s-item__title, [role=\"heading\"], h3');
        if (t1) title = t1.innerText || '';
        if (!title) title = a.getAttribute('aria-label') || a.innerText || '';
        let price = '';
        const p1 = n.querySelector('.s-card__price, .s-item__price, .su-styled-text.primary');
        if (p1) price = p1.innerText || '';
        // auction hint
        const txt = n.innerText || '';
        const auction = /Gebot|Auktion|bids?/i.test(txt);
        out.push({
          id: m[1],
          title: title.replace(/\\s+/g,' ').trim().slice(0,160),
          price: price.replace(/\\s+/g,' ').trim().slice(0,40),
          auctionish: auction,
          url: 'https://www.ebay.de/itm/' + m[1],
        });
      }
      // unique by id
      const seen = new Set();
      return out.filter(x => {
        if (seen.has(x.id)) return false;
        seen.add(x.id);
        return true;
      }).slice(0, 30);
    }"""
    )


def main():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for case in CASES:
            ctx = browser.new_context(
                locale="de-DE",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()
            nkw = case["query"].replace(" ", "+")
            url = (
                f"https://www.ebay.de/sch/i.html?_nkw={nkw}"
                f"&LH_Auction=1&_sop=15&_udlo={case['min_price']}&rt=nc&_ipg=60"
            )
            rec = {
                "stats_name": case["stats_name"],
                "stats_said": "Auktion = eBay block",
                "search_url": url,
                "matches": [],
                "error": None,
            }
            print("\n===", case["stats_name"], flush=True)
            print(url, flush=True)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                cards = extract_cards(page)
                print(f"  cards parsed: {len(cards)}", flush=True)
                for c in cards:
                    if title_ok(c.get("title") or "", case):
                        rec["matches"].append(c)
                # if titles empty, still take first few with ids and open item page
                if not rec["matches"] and cards:
                    for c in cards[:8]:
                        try:
                            ip = ctx.new_page()
                            ip.goto(c["url"], wait_until="domcontentloaded", timeout=30000)
                            ip.wait_for_timeout(1500)
                            meta = ip.evaluate(
                                """() => {
                              const t=(document.querySelector('h1')||{}).innerText||document.title||'';
                              const p=(document.querySelector('[data-testid=\"x-price-primary\"], .x-price-primary')||{}).innerText||'';
                              const body=document.body.innerText||'';
                              return {
                                title: t.trim().slice(0,160),
                                price: p.trim().slice(0,60),
                                auction: /Auktion|Gebot ab|Anzahl der Gebote/i.test(body),
                              };
                            }"""
                            )
                            ip.close()
                            c2 = {
                                **c,
                                "title": meta.get("title") or c.get("title"),
                                "price": meta.get("price") or c.get("price"),
                                "auctionish": meta.get("auction"),
                            }
                            if title_ok(c2.get("title") or "", case):
                                rec["matches"].append(c2)
                                if len(rec["matches"]) >= 2:
                                    break
                        except Exception as e:
                            print("  item open err", e, flush=True)
                print(f"  matched: {len(rec['matches'])}", flush=True)
                for m in rec["matches"][:3]:
                    print(f"  PROOF {m.get('price')} {m['url']}", flush=True)
                    print(f"       {m.get('title','')[:100]}", flush=True)
            except Exception as e:
                rec["error"] = str(e)
                print("ERR", e, flush=True)
            results.append(rec)
            ctx.close()
            time.sleep(1.0)
        browser.close()

    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n\n===== FINAL (min 4 proofs) =====")
    n = 0
    for r in results:
        if r.get("matches"):
            m = r["matches"][0]
            n += 1
            print(f"{n}. stats product: {r['stats_name']} — said Auktion eBay block")
            print(f"   live auction search found: {m.get('price')} — {m['url']}")
            print(f"   title: {m.get('title')}")
            print(f"   search: {r['search_url']}")
    print(f"\ntotal products with live stock while stats said block: {n}")


if __name__ == "__main__":
    main()
