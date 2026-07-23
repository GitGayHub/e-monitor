#!/usr/bin/env python3
"""Honest full audit with resilient browser (new context per product)."""
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

SEARCH_Q = {
    "redmagic 11 pro": "redmagic 11 pro",
    "redmagic 11s pro": "redmagic 11s pro",
    "nubia z80 ultra": "nubia z80 ultra",
    "nubia z80 lv": "nubia z80 leading",
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
    "logitech superlight 2 dex": "logitech superlight 2 dex",
    "logitech superlight 2": "logitech g pro x superlight 2 -dex",
    "sony ult wear": "sony ult wear WH-ULT900N",
    "lg ultragear oled": "lg ultragear oled 480hz",
    "samsung odyssey oled g6": "samsung odyssey oled g6 500hz",
}


def parse_paste(text: str):
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
    # longer keys first
    for k, q in sorted(SEARCH_Q.items(), key=lambda x: -len(x[0])):
        if k in t:
            return q
    return re.sub(r"[^\w\s]", " ", title).strip()[:60]


def bot_class(b):
    if b["price_str"].endswith("€"):
        return "HAS_PRICE"
    v = b["verdict"]
    if "Rate limit" in v:
        return "RATE_LIMIT"
    if "eBay block" in v or "block" in v:
        return "BLOCK"
    if "Не найдено" in v:
        return "EMPTY"
    return "OTHER"


def main():
    products = parse_paste(PASTE.read_text(encoding="utf-8", errors="replace"))
    print(f"products={len(products)}", flush=True)
    audit = []
    counts = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        def fresh_page():
            nonlocal browser
            try:
                return browser.new_context(
                    locale="de-DE",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                    ),
                )
            except Exception as e:
                print("ctx fail, relaunch browser", e, flush=True)
                try:
                    browser.close()
                except Exception:
                    pass
                browser = p.chromium.launch(headless=True)
                return browser.new_context(locale="de-DE")

        for pi, prod in enumerate(products):
            title = prod["title"]
            q = query_for(title)
            print(f"\n=== [{pi+1}/{len(products)}] {title} ===", flush=True)
            prow = {"product": title, "query": q, "buckets": []}

            # fresh context per product
            try:
                ctx = fresh_page()
                page = ctx.new_page()
            except Exception as e:
                print("skip product, browser dead", e, flush=True)
                for b in prod["buckets"]:
                    h = "CHECK_ERROR"
                    prow["buckets"].append({
                        "bucket": b["bucket"], "bot_price": b["price_str"],
                        "bot_verdict": b["verdict"], "bot_class": bot_class(b),
                        "honest": h, "note": str(e)[:80],
                    })
                    counts[h] = counts.get(h, 0) + 1
                audit.append(prow)
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception:
                    pass
                continue

            # Group: check all HAS_PRICE first, then one search per side for empties
            price_buckets = [b for b in prod["buckets"] if bot_class(b) == "HAS_PRICE"]
            empty_buckets = [b for b in prod["buckets"] if bot_class(b) != "HAS_PRICE"]

            for b in price_buckets:
                row = {
                    "bucket": b["bucket"],
                    "bot_price": b["price_str"],
                    "bot_verdict": b["verdict"],
                    "bot_url": b.get("url"),
                    "bot_class": "HAS_PRICE",
                    "honest": None,
                    "note": "",
                    "proof_url": b.get("url"),
                }
                try:
                    page.goto(b["url"], wait_until="domcontentloaded", timeout=40000)
                    page.wait_for_timeout(1500)
                    live = page.evaluate(
                        """() => {
                      const t=(document.querySelector('h1')||{}).innerText||document.title||'';
                      const p=(document.querySelector('[data-testid=\"x-price-primary\"], .x-price-primary, #prcIsum')||{}).innerText||'';
                      const err=/Error Page|Something went wrong/i.test(t);
                      return {title:t.trim().slice(0,140), price:p.trim().slice(0,50), error:err};
                    }"""
                    )
                    row["live"] = live
                    if live.get("error"):
                        row["honest"] = "BOT_LINK_ERROR_PAGE"
                        row["note"] = "item Error Page"
                    else:
                        bn = re.search(r"(\d+)", b["price_str"] or "")
                        ln = re.search(r"(\d+)", live.get("price") or "")
                        if bn and ln and abs(int(bn.group(1)) - int(ln.group(1))) >= 100:
                            row["honest"] = "PRICE_DRIFT"
                        else:
                            row["honest"] = "OK_PRICE_LIVE"
                        row["note"] = f"live {live.get('price')} | {live.get('title','')[:70]}"
                    print(f"  {b['bucket']} {b['price_str']} -> {row['honest']}", flush=True)
                except Exception as e:
                    row["honest"] = "CHECK_ERROR"
                    row["note"] = str(e)[:100]
                    print(f"  {b['bucket']} ERR {e}", flush=True)
                    try:
                        ctx.close()
                    except Exception:
                        pass
                    ctx = fresh_page()
                    page = ctx.new_page()
                prow["buckets"].append(row)
                counts[row["honest"]] = counts.get(row["honest"], 0) + 1
                time.sleep(1.5)

            # For empty buckets: one BIN search + one Auction search max
            need_bin = any(b["bucket"] in ("Sofort", "Sofort+") for b in empty_buckets)
            need_auc = any(b["bucket"] in ("Auktion", "Auktion+") for b in empty_buckets)
            live_bin = None
            live_auc = None

            def do_search(auction: bool):
                nkw = q.replace(" ", "+")
                lt = "LH_Auction=1" if auction else "LH_BIN=1"
                floor = 50
                if any(x in title.lower() for x in ("oled", "ultragear", "odyssey", "iphone", "4080", "5070", "ps5")):
                    floor = 120
                url = f"https://www.ebay.de/sch/i.html?_nkw={nkw}&{lt}&_sop=15&_udlo={floor}&rt=nc&_ipg=40"
                page.goto(url, wait_until="domcontentloaded", timeout=40000)
                page.wait_for_timeout(2200)
                pt = page.title()
                if re.search(r"Error Page|Something went wrong", pt, re.I):
                    return {"error": "error_page", "search_url": url, "hits": []}
                hits = page.evaluate(
                    """() => {
                  const out=[]; const seen=new Set();
                  for (const n of document.querySelectorAll('li.s-card, li.s-item, .srp-results li')) {
                    const a=n.querySelector('a[href*=\"/itm/\"]');
                    if(!a) continue;
                    const m=(a.href||'').match(/\\/itm\\/(\\d{9,15})/);
                    if(!m||seen.has(m[1])) continue; seen.add(m[1]);
                    let t='';
                    const te=n.querySelector('.s-card__title,.s-item__title,[role=\"heading\"],h3');
                    if(te) t=te.innerText||'';
                    if(!t) t=a.getAttribute('aria-label')||a.innerText||'';
                    if(/shop on ebay/i.test(t)) continue;
                    let pr='';
                    const pe=n.querySelector('.s-card__price,.s-item__price');
                    if(pe) pr=pe.innerText||'';
                    out.push({id:m[1], title:(t||'').replace(/\\s+/g,' ').trim().slice(0,100),
                              price:(pr||'').replace(/\\s+/g,' ').trim().slice(0,40),
                              url:'https://www.ebay.de/itm/'+m[1]});
                    if(out.length>=5) break;
                  }
                  return out;
                }"""
                )
                if not hits:
                    html = page.content()
                    ids = []
                    for m in re.finditer(r"/itm/(\d{9,15})", html):
                        if m.group(1) not in ids:
                            ids.append(m.group(1))
                    hits = [
                        {"id": i, "title": "(html-id)", "price": "?", "url": f"https://www.ebay.de/itm/{i}"}
                        for i in ids[:5]
                    ]
                return {"error": None, "search_url": url, "hits": hits}

            if need_bin:
                try:
                    live_bin = do_search(False)
                    print(f"  live BIN hits={len(live_bin.get('hits') or [])} err={live_bin.get('error')}", flush=True)
                except Exception as e:
                    live_bin = {"error": str(e), "hits": [], "search_url": ""}
                    print(f"  live BIN ERR {e}", flush=True)
                    try:
                        ctx.close()
                    except Exception:
                        pass
                    ctx = fresh_page()
                    page = ctx.new_page()
                time.sleep(2.0)

            if need_auc:
                try:
                    live_auc = do_search(True)
                    print(f"  live AUC hits={len(live_auc.get('hits') or [])} err={live_auc.get('error')}", flush=True)
                except Exception as e:
                    live_auc = {"error": str(e), "hits": [], "search_url": ""}
                    print(f"  live AUC ERR {e}", flush=True)
                time.sleep(2.0)

            for b in empty_buckets:
                side = live_auc if b["bucket"] in ("Auktion", "Auktion+") else live_bin
                bc = bot_class(b)
                row = {
                    "bucket": b["bucket"],
                    "bot_price": b["price_str"],
                    "bot_verdict": b["verdict"],
                    "bot_url": None,
                    "bot_class": bc,
                    "honest": None,
                    "note": "",
                    "proof_url": None,
                    "search_url": (side or {}).get("search_url"),
                }
                if not side:
                    row["honest"] = "NO_CHECK"
                elif side.get("error") and not side.get("hits"):
                    row["honest"] = "LIVE_ALSO_BLOCKED"
                    row["note"] = f"local also failed: {side.get('error')}"
                elif not side.get("hits"):
                    row["honest"] = "LIKELY_TRUE_EMPTY"
                    row["note"] = "live 0 results"
                else:
                    top = side["hits"][0]
                    row["proof_url"] = top.get("url")
                    row["note"] = f"{top.get('price')} {top.get('url')} | {top.get('title','')[:60]}"
                    if bc in ("BLOCK", "RATE_LIMIT"):
                        row["honest"] = "BOT_LIED_LABEL"  # said transport fail but stock exists
                    else:
                        row["honest"] = "BOT_EMPTY_STOCK_EXISTS"
                print(f"  {b['bucket']} {bc} -> {row['honest']}", flush=True)
                prow["buckets"].append(row)
                counts[row["honest"]] = counts.get(row["honest"], 0) + 1

            # keep original bucket order
            order = {"Sofort": 0, "Sofort+": 1, "Auktion": 2, "Auktion+": 3}
            prow["buckets"].sort(key=lambda x: order.get(x["bucket"], 9))
            audit.append(prow)
            try:
                ctx.close()
            except Exception:
                pass
            time.sleep(1.5)

        browser.close()

    OUT_JSON.write_text(
        json.dumps({"counts": counts, "products": audit}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        "# Полный честный аудит: bot stats vs live eBay",
        "",
        "Источник stats: последний GH mixed-fetch report (`stats_paste.txt`).",
        "Метод: локальный Chromium — проверка item-ссылок бота + live BIN/Auction search на пустые/block/RL.",
        "",
        "## Сводка (честные вердикты)",
        "",
        "| Вердикт | Смысл | N |",
        "|---------|-------|--:|",
    ]
    meaning = {
        "OK_PRICE_LIVE": "бот дал цену, ссылка живая",
        "PRICE_DRIFT": "ссылка живая, цена уехала",
        "BOT_LINK_ERROR_PAGE": "ссылка бота сейчас Error Page",
        "BOT_LIED_LABEL": "бот сказал block/RL, live search нашёл лоты",
        "BOT_EMPTY_STOCK_EXISTS": "бот «Не найдено», live search нашёл лоты",
        "LIKELY_TRUE_EMPTY": "live тоже 0",
        "LIVE_ALSO_BLOCKED": "и локальный браузер упёрся — проверить нельзя",
        "CHECK_ERROR": "ошибка проверки",
        "NO_CHECK": "не проверялось",
    }
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"| `{k}` | {meaning.get(k, k)} | {v} |")

    lines += ["", "## По каждому продукту", ""]
    for p in audit:
        lines.append(f"### {p['product']}")
        lines.append(f"query: `{p['query']}`")
        lines.append("")
        lines.append("| Bucket | Bot | Honest | Proof / note |")
        lines.append("|--------|-----|--------|--------------|")
        for b in p["buckets"]:
            bot = f"{b['bot_price']} / {b['bot_verdict'][:24]}"
            note = (b.get("note") or "").replace("|", "/")
            if b.get("proof_url"):
                note = f"{b['proof_url']} — {note}"
            lines.append(f"| {b['bucket']} | {bot} | **{b.get('honest')}** | {note[:120]} |")
        lines.append("")

    # lie list
    lies = []
    for p in audit:
        for b in p["buckets"]:
            if b.get("honest") in ("BOT_LIED_LABEL", "BOT_EMPTY_STOCK_EXISTS"):
                lies.append((p["product"], b["bucket"], b["bot_verdict"], b.get("proof_url"), b.get("note")))
    lines += ["## Где бот соврал / не добрал (stock есть)", ""]
    if not lies:
        lines.append("_нет таких (или live check тоже заблочен)_")
    else:
        for prod, buck, verd, url, note in lies:
            lines.append(f"- **{prod}** / {buck}: bot=`{verd[:30]}` → live `{url}`")
            if note:
                lines.append(f"  - {note[:140]}")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\nCOUNTS", json.dumps(counts, indent=2, ensure_ascii=False))
    print("LIES", len(lies))
    print("WROTE", OUT_MD)


if __name__ == "__main__":
    main()
