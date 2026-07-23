#!/usr/bin/env python3
"""Full honest 1:1 audit: stats_paste buckets vs live eBay (local Chromium).

No soft lies:
- PRICE rows: open item link, check title/price still live
- EMPTY / BLOCK / RL rows: live search for that listing type; report if stock exists
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PASTE = ROOT / "qa" / "inbox" / "stats_paste.txt"
OUT_JSON = ROOT / "qa" / "results" / "HONEST_AUDIT.json"
OUT_MD = ROOT / "qa" / "results" / "HONEST_AUDIT.md"

# Search queries for empty-bucket live checks (intent, not config noise)
SEARCH_Q = {
    "redmagic 11 pro": "redmagic 11 pro",
    "redmagic 11s pro": "redmagic 11s pro",
    "nubia z80 ultra": "nubia z80 ultra",
    "nubia z80 lv": "nubia z80 leading version",
    "nubia z70 ultra": "nubia z70 ultra",
    "nubia z70s ultra": "nubia z70s ultra",
    "iphone 16 pro max": "iphone 16 pro max",
    "playstation 5 pro": "ps5 pro",
    "pixel 5": "google pixel 5",
    "sony wh-1000xm6": "sony wh-1000xm6",
    "5070 ti": "rtx 5070 ti gaming pc",
    "4080": "rtx 4080 gaming pc",
    "iphone 15 pro max": "iphone 15 pro max",
    "samsung s24 ultra": "samsung s24 ultra",
    "4050 oled": "rtx 4050 oled laptop",
    "4060 oled": "rtx 4060 oled laptop",
    "asus vivobook 14x oled": "asus vivobook 14x oled",
    "pro x 2 superstrike": "logitech superstrike",
    "logitech superlight 2": "logitech g pro x superlight 2",
    "logitech superlight 2 dex": "logitech superlight 2 dex",
    "sony ult wear": "sony ult wear",
    "lg ultragear oled": "lg ultragear oled 480hz",
    "samsung odyssey oled g6": "samsung odyssey oled g6 500hz",
}

BUCKET_AUCTION = {"Auktion", "Auktion+"}
BUCKET_BIN = {"Sofort", "Sofort+"}


def parse_paste(text: str):
    # split on product headers
    parts = re.split(r"\n(?=(?:📦|📱|🎮|🖥️|💻|🖱️|🎧)\s)", text.strip())
    products = []
    for part in parts:
        if not part.strip():
            continue
        lines = part.strip().splitlines()
        title = re.sub(r"^[^\w]+", "", lines[0]).strip()
        title = re.sub(r"\s*[🌍🇩🇪🇪🇺⚙️♾️]+.*$", "", title).strip()
        buckets = []
        cur = None
        for ln in lines[1:]:
            m = re.match(
                r"^[🛒🤝🔨⏳]\s+(Sofort\+|Sofort|Auktion\+|Auktion)\s+([0-9]+€|---)\s*│\s*(.+)$",
                ln.strip(),
            )
            if m:
                if cur:
                    buckets.append(cur)
                cur = {
                    "bucket": m.group(1),
                    "price_str": m.group(2),
                    "verdict": m.group(3).strip(),
                    "url": None,
                }
                continue
            if cur and "ebay.de/itm/" in ln:
                um = re.search(r"https://www\.ebay\.de/itm/\d+", ln)
                if um:
                    cur["url"] = um.group(0)
        if cur:
            buckets.append(cur)
        if buckets:
            products.append({"title": title, "buckets": buckets})
    return products


def query_for(title: str) -> str:
    t = title.lower()
    for k, q in SEARCH_Q.items():
        if k in t:
            return q
    # fallback first words
    return re.sub(r"[^\w\s]", " ", title).strip()[:60]


def open_item(page, url: str) -> dict:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1800)
    return page.evaluate(
        """() => {
      const t = (document.querySelector('h1') || {}).innerText || document.title || '';
      const p = (document.querySelector('[data-testid=\"x-price-primary\"], .x-price-primary, #prcIsum') || {}).innerText || '';
      const body = document.body.innerText || '';
      const err = /Error Page|Something went wrong|Zugriff verweigert|captcha/i.test(t + body.slice(0,500));
      return {
        title: (t||'').trim().slice(0,160),
        price: (p||'').trim().slice(0,60),
        error_page: err,
        auction: /Auktion|Gebot ab|Anzahl der Gebote/i.test(body),
        bin: /Sofort-Kaufen|Buy It Now/i.test(body),
      };
    }"""
    )


def search_live(page, query: str, auction: bool, min_price: float = 0) -> list:
    nkw = query.replace(" ", "+")
    lt = "LH_Auction=1" if auction else "LH_BIN=1"
    url = (
        f"https://www.ebay.de/sch/i.html?_nkw={nkw}&{lt}&_sop=15"
        f"&_udlo={int(min_price)}&rt=nc&_ipg=40"
    )
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    title = page.title()
    body_head = page.evaluate("() => (document.body.innerText||'').slice(0,400)")
    if re.search(r"Error Page|Something went wrong|captcha|Zugriff", title + body_head, re.I):
        return [{"error": "ebay_error_page", "search_url": url, "page_title": title}]
    cards = page.evaluate(
        """() => {
      const out = [];
      const nodes = document.querySelectorAll('li.s-card, li.s-item, .srp-results li');
      for (const n of nodes) {
        const a = n.querySelector('a[href*=\"/itm/\"]');
        if (!a) continue;
        const m = (a.href||'').match(/\\/itm\\/(\\d{9,15})/);
        if (!m) continue;
        let t = '';
        const te = n.querySelector('.s-card__title, .s-item__title, [role=\"heading\"], h3');
        if (te) t = te.innerText || '';
        if (!t) t = a.getAttribute('aria-label') || a.innerText || '';
        if (/shop on ebay/i.test(t)) continue;
        let p = '';
        const pe = n.querySelector('.s-card__price, .s-item__price');
        if (pe) p = pe.innerText || '';
        out.push({id:m[1], title:(t||'').replace(/\\s+/g,' ').trim().slice(0,120),
                  price:(p||'').replace(/\\s+/g,' ').trim().slice(0,40),
                  url:'https://www.ebay.de/itm/'+m[1]});
      }
      const seen=new Set();
      return out.filter(x=>{if(seen.has(x.id))return false;seen.add(x.id);return true;}).slice(0,8);
    }"""
    )
    # fallback ids from html
    if not cards:
        html = page.content()
        ids = []
        for m in re.finditer(r"/itm/(\d{9,15})", html):
            if m.group(1) not in ids:
                ids.append(m.group(1))
        cards = [
            {"id": i, "title": "(unparsed)", "price": "?", "url": f"https://www.ebay.de/itm/{i}"}
            for i in ids[:6]
        ]
    for c in cards:
        c["search_url"] = url
    return cards


def classify_bot(bucket: dict) -> str:
    p, v = bucket["price_str"], bucket["verdict"]
    if p.endswith("€"):
        return "HAS_PRICE"
    if "Rate limit" in v:
        return "RATE_LIMIT"
    if "eBay block" in v or "block" in v:
        return "BLOCK"
    if "Не найдено" in v:
        return "EMPTY"
    return "OTHER_EMPTY"


def main():
    text = PASTE.read_text(encoding="utf-8", errors="replace")
    products = parse_paste(text)
    print(f"parsed {len(products)} products", flush=True)

    audit = []
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

        for pi, prod in enumerate(products):
            title = prod["title"]
            q = query_for(title)
            print(f"\n[{pi+1}/{len(products)}] {title}", flush=True)
            prow = {"product": title, "query": q, "buckets": []}

            for b in prod["buckets"]:
                bot = classify_bot(b)
                row = {
                    "bucket": b["bucket"],
                    "bot_price": b["price_str"],
                    "bot_verdict": b["verdict"],
                    "bot_url": b.get("url"),
                    "bot_class": bot,
                    "live": None,
                    "honest": None,
                    "note": "",
                }
                try:
                    if bot == "HAS_PRICE" and b.get("url"):
                        live = open_item(page, b["url"])
                        row["live"] = live
                        if live.get("error_page"):
                            row["honest"] = "BOT_LINK_DEAD_OR_BLOCKED"
                            row["note"] = "item link from bot opens Error Page now"
                        else:
                            # price digit compare loosely
                            bot_n = re.search(r"(\d+)", b["price_str"])
                            live_n = re.search(r"(\d+)", live.get("price") or "")
                            if live.get("title") and not live_n:
                                row["honest"] = "BOT_LINK_LIVE_NO_PRICE_PARSED"
                            elif bot_n and live_n:
                                diff = abs(int(bot_n.group(1)) - int(live_n.group(1)))
                                row["honest"] = "OK_LINK_LIVE" if diff < 80 else "PRICE_DRIFT"
                                row["note"] = f"live={live.get('price')} title={live.get('title','')[:60]}"
                            else:
                                row["honest"] = "OK_LINK_LIVE"
                                row["note"] = (live.get("title") or "")[:80]
                        print(f"  {b['bucket']} PRICE {b['price_str']} -> {row['honest']}", flush=True)

                    else:
                        # empty / block / rl — live search
                        auction = b["bucket"] in BUCKET_AUCTION
                        # floor rough
                        floor = 40
                        if any(x in title.lower() for x in ("iphone", "oled", "ultragear", "odyssey", "4080", "5070", "ps5")):
                            floor = 100
                        hits = search_live(page, q, auction=auction, min_price=floor)
                        row["live"] = {"hits": hits[:4], "n": 0 if (hits and hits[0].get("error")) else len(hits)}
                        if hits and hits[0].get("error"):
                            row["honest"] = "LIVE_CHECK_BLOCKED"
                            row["note"] = "local browser also got eBay error — cannot verify"
                        elif not hits:
                            row["honest"] = "LIKELY_TRUE_EMPTY"
                            row["note"] = "live search returned 0 cards"
                        else:
                            # bot said empty/block but live has results
                            if bot in ("BLOCK", "RATE_LIMIT"):
                                row["honest"] = "BOT_LIED_STOCK_EXISTS"
                            else:
                                row["honest"] = "BOT_EMPTY_BUT_STOCK_EXISTS"
                            top = hits[0]
                            row["note"] = f"live top {top.get('price')} {top.get('url')} | {top.get('title','')[:50]}"
                            row["proof_url"] = top.get("url")
                            row["search_url"] = top.get("search_url")
                        print(
                            f"  {b['bucket']} {bot} -> {row['honest']} ({row['note'][:70]})",
                            flush=True,
                        )
                except Exception as e:
                    row["honest"] = "CHECK_ERROR"
                    row["note"] = str(e)[:120]
                    print(f"  {b['bucket']} ERR {e}", flush=True)

                prow["buckets"].append(row)
                time.sleep(1.2)  # be gentle

            audit.append(prow)
            time.sleep(0.8)

        browser.close()

    # summary counts
    counts = {}
    for p in audit:
        for b in p["buckets"]:
            h = b.get("honest") or "?"
            counts[h] = counts.get(h, 0) + 1

    OUT_JSON.write_text(json.dumps({"counts": counts, "products": audit}, indent=2, ensure_ascii=False), encoding="utf-8")

    # markdown
    lines = [
        "# Полный честный аудит stats vs live eBay",
        "",
        f"Source: `qa/inbox/stats_paste.txt` (GH run mixed-fetch).",
        f"Method: local Chromium — open bot item links; for empty/block/RL do live BIN/Auction search.",
        "",
        "## Сводка",
        "",
        "| Honest verdict | Count |",
        "|----------------|------:|",
    ]
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        "### Что значит",
        "",
        "- `OK_LINK_LIVE` — бот дал цену, ссылка живая",
        "- `BOT_LIED_STOCK_EXISTS` — бот сказал block/rate limit, live search нашёл лоты",
        "- `BOT_EMPTY_BUT_STOCK_EXISTS` — бот «Не найдено», live search нашёл лоты",
        "- `LIKELY_TRUE_EMPTY` — live тоже 0",
        "- `LIVE_CHECK_BLOCKED` — и локальный браузер упёрся в eBay error (проверка невозможна)",
        "- `BOT_LINK_DEAD_OR_BLOCKED` — ссылка бота сейчас Error Page",
        "",
        "## По продуктам",
        "",
    ]
    for p in audit:
        lines.append(f"### {p['product']}")
        lines.append(f"_query:_ `{p['query']}`")
        lines.append("")
        lines.append("| Bucket | Bot | Honest | Note / proof |")
        lines.append("|--------|-----|--------|--------------|")
        for b in p["buckets"]:
            bot_s = f"{b['bot_price']} {b['bot_verdict'][:20]}"
            note = (b.get("note") or "").replace("|", "/")[:100]
            if b.get("proof_url"):
                note = f"{b['proof_url']} — {note}"
            lines.append(f"| {b['bucket']} | {bot_s} | **{b.get('honest')}** | {note} |")
        lines.append("")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\nCOUNTS", json.dumps(counts, indent=2))
    print("WROTE", OUT_MD)


if __name__ == "__main__":
    main()
