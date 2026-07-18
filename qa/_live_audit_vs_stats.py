#!/usr/bin/env python3
"""Compare stats_paste cheapest prices vs live eBay SERP (requests).

Does not use product hardcodes for filters — reuses monitor parse + simple
title token check. Writes qa/results/LIVE_AUDIT_VS_STATS.md
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from monitor import parse_ebay_results, _normalize  # noqa: E402

PASTE = ROOT / "qa" / "inbox" / "stats_paste.txt"
OUT_MD = ROOT / "qa" / "results" / "LIVE_AUDIT_VS_STATS.md"
OUT_JSON = ROOT / "qa" / "results" / "LIVE_AUDIT_VS_STATS.json"

# Products to re-check live when empty or expensive / auction-empty.
FOCUS = [
    ("Redmagic 11 Pro", "redmagic 11 pro", 50),
    ("Nubia Z80 Ultra", "nubia z80 ultra", 50),
    ("Nubia Z80 LV", "nubia z80 ultra leading", 50),
    ("Pixel 5", "google pixel 5", 30),
    ("Sony WH-1000XM6", "sony wh-1000xm6", 80),
    ("sony ult wear", "sony ult wear", 20),
    ("lg ultragear", "lg ultragear oled 480", 150),
    ("odyssey g6", "samsung odyssey oled g6 500", 150),
    ("superlight 2 dex", "g pro x superlight 2 dex", 40),
    ("superstrike", "logitech superstrike", 40),
    ("iphone 16 pro max", "iphone 16 pro max", 50),
    ("ps5 pro", "playstation 5 pro", 200),
]


def parse_stats(text: str) -> list[dict]:
    blocks = re.split(r"(?=^[📦📱🎮💻🖥️🖱️🎧])", text, flags=re.M)
    out = []
    for b in blocks:
        if not b.strip():
            continue
        title = b.strip().splitlines()[0]
        # strip emoji/noise for display
        name = re.sub(r"^[^\w]+", "", title).split("🌍")[0].split("🇩🇪")[0].strip()
        buckets = {}
        for emoji, key in (
            ("🛒", "sofort"),
            ("🤝", "sofort_plus"),
            ("🔨", "auktion"),
            ("⏳", "auktion_plus"),
        ):
            m = re.search(
                rf"{emoji}.+?(?:(\d+)€|---).+?│\s*(.+)$",
                b,
                re.M,
            )
            if not m:
                continue
            price = int(m.group(1)) if m.group(1) else None
            label = (m.group(2) or "").strip()
            link_m = re.search(
                rf"{emoji}[\s\S]{{0,200}}https://www\.ebay\.de/itm/(\d+)", b
            )
            buckets[key] = {
                "price": price,
                "label": label,
                "item_id": link_m.group(1) if link_m else None,
            }
        out.append({"name": name, "raw_title": title, "buckets": buckets})
    return out


def live_search(session, query: str, listing: str, udlo: int) -> list[dict]:
    params = {
        "_nkw": query,
        "_sop": "15",
        "_ipg": "60",
        "rt": "nc",
        "_udlo": str(udlo),
    }
    if listing == "auction":
        params["LH_Auction"] = "1"
    else:
        params["LH_BIN"] = "1"
    url = "https://www.ebay.de/sch/i.html?" + urllib.parse.urlencode(params)
    r = session.get(url, timeout=35)
    body = r.text or ""
    items = parse_ebay_results(body) if r.status_code == 200 else []
    return items, r.status_code, len(body), url


def title_ok(title: str, tokens: list[str]) -> bool:
    n = _normalize(title)
    return all(t in n for t in tokens if len(t) > 1)


def main():
    text = PASTE.read_text(encoding="utf-8", errors="replace")
    stats = parse_stats(text)
    H = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9",
    }
    s = requests.Session()
    s.headers.update(H)
    findings = []
    lines = ["# Live eBay audit vs stats_paste\n"]

    for focus_name, q, udlo in FOCUS:
        # match stats product
        st = next(
            (p for p in stats if focus_name.lower() in p["name"].lower()
             or any(t in p["name"].lower() for t in focus_name.lower().split()[:2])),
            None,
        )
        lines.append(f"\n## {focus_name}\n")
        if st:
            lines.append(f"stats: `{st['name']}`\n")
            for k, v in (st.get("buckets") or {}).items():
                lines.append(
                    f"- stats {k}: {v.get('price')}€ | {v.get('label')} | {v.get('item_id')}\n"
                )
        else:
            lines.append("stats: (product not in paste)\n")

        tokens = [t for t in _normalize(q).split() if t not in ("google", "logitech")]
        for listing in ("bin", "auction"):
            try:
                items, sc, blen, url = live_search(s, q, listing, udlo)
            except Exception as e:
                lines.append(f"- LIVE {listing}: ERR {e}\n")
                continue
            matched = [
                it
                for it in items
                if title_ok(it.get("title") or "", tokens[:3] if len(tokens) > 3 else tokens)
            ]
            # if too strict, fall back to first with any strong token
            if not matched and items:
                matched = items[:5]
            prices = sorted(
                float(it.get("total_price") or it.get("price") or 0)
                for it in matched
                if (it.get("total_price") or it.get("price"))
            )
            cheapest = prices[0] if prices else None
            sample = matched[0] if matched else None
            lines.append(
                f"- LIVE {listing}: sc={sc} parsed={len(items)} matched~{len(matched)} "
                f"cheapest={cheapest} id={sample.get('item_id') if sample else None}\n"
            )
            lines.append(f"  url: {url}\n")
            if sample:
                lines.append(f"  title: {(sample.get('title') or '')[:90]}\n")

            # compare
            if st:
                key = "auktion" if listing == "auction" else "sofort"
                sb = (st.get("buckets") or {}).get(key) or {}
                sp = sb.get("price")
                gap = None
                note = "ok"
                if cheapest is not None and sp is not None and cheapest + 5 < sp:
                    note = "CHEAPER_ON_EBAY"
                    gap = sp - cheapest
                elif cheapest is not None and sp is None:
                    note = "STATS_EMPTY_BUT_LIVE_HAS"
                    gap = cheapest
                elif cheapest is None and sp is not None:
                    note = "LIVE_EMPTY_STATS_HAS"
                findings.append(
                    {
                        "product": focus_name,
                        "listing": listing,
                        "stats_price": sp,
                        "live_cheapest": cheapest,
                        "note": note,
                        "gap": gap,
                        "live_id": sample.get("item_id") if sample else None,
                        "stats_id": sb.get("item_id"),
                    }
                )
                if note != "ok":
                    lines.append(f"  **⚠ {note}** gap={gap}\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    OUT_JSON.write_text(json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")
    print("".join(lines)[:6000])
    print("--- findings ---")
    for f in findings:
        if f["note"] != "ok":
            print(f)


if __name__ == "__main__":
    main()
