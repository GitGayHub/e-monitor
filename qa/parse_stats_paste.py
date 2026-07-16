#!/usr/bin/env python3
"""Parse a pasted Telegram statistics report into structured JSON for QA audit.

Usage:
  python qa/parse_stats_paste.py
  python qa/parse_stats_paste.py path/to/paste.txt
  python qa/parse_stats_paste.py path/to/paste.txt -o qa/inbox/stats_parsed.json

Paste source: Telegram stats message(s) into qa/inbox/stats_paste.txt
(MCP cannot read e-monitor bot history.)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = Path(__file__).resolve().parent / "inbox" / "stats_paste.txt"
DEFAULT_OUT = Path(__file__).resolve().parent / "inbox" / "stats_parsed.json"

# Product header: emoji + bold-ish name (after paste, HTML often stripped)
RE_PRODUCT = re.compile(
    r"^(?P<emoji>\S+)\s+(?P<title>.+?)\s*$",
    re.UNICODE,
)
RE_LIMIT = re.compile(r"Лимит|Limit", re.I)
RE_BUCKET = re.compile(
    r"(?P<em>🛒|🤝|🔨|⏳)\s*"
    r"(?P<label>Sofort\+|Sofort|Auktion\+|Auktion)\s*"
    r"(?P<price>---|\d+[.,]?\d*)\s*€?\s*"
    r"(?:│|\|)?\s*"
    r"(?P<verdict>.*)$",
    re.I,
)
RE_URL = re.compile(r"https?://\S+", re.I)
RE_ITEM_ID = re.compile(r"/itm/(?:[^/\s]+/)?(\d{9,15})", re.I)

BUCKET_KEYS = {
    "sofort": "sofort",
    "sofort+": "sofort_plus",
    "auktion": "auktion",
    "auktion+": "auktion_plus",
}


def _norm_label(label: str) -> str:
    l = re.sub(r"\s+", "", label.strip().lower())
    l = l.replace("ä", "a").replace("ü", "u")
    if l.startswith("sofort+"):
        return "sofort+"
    if l.startswith("sofort"):
        return "sofort"
    if l.startswith("auktion+"):
        return "auktion+"
    if l.startswith("auktion"):
        return "auktion"
    return l


def _parse_price(raw: str):
    raw = (raw or "").strip().replace("€", "").replace(",", ".")
    if raw in ("", "---", "–", "-"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _slug(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^\w\s+-]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", "_", s.strip())
    return (s[:80] or "item").strip("_")


def parse_paste(text: str) -> dict:
    lines = [ln.rstrip() for ln in text.splitlines()]
    products = []
    current = None
    pending_bucket = None
    footer = {}

    def flush():
        nonlocal current
        if current:
            products.append(current)
            current = None

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Footer
        if re.search(r"Автомониторинг|Версия|Version", line, re.I):
            footer.setdefault("raw_footer", []).append(line)
            i += 1
            continue

        # Limit line belongs to current product
        if RE_LIMIT.search(line) and current:
            current["limit_line"] = line
            i += 1
            continue

        m_b = RE_BUCKET.search(line)
        if m_b and current:
            label = _norm_label(m_b.group("label"))
            key = BUCKET_KEYS.get(label, label)
            price = _parse_price(m_b.group("price"))
            verdict = (m_b.group("verdict") or "").strip()
            # strip leading pipes leftovers
            verdict = re.sub(r"^[│\|\s]+", "", verdict)
            bucket = {
                "label": label,
                "price_eur": price,
                "verdict": verdict,
                "url": None,
                "item_id": None,
            }
            current["buckets"][key] = bucket
            pending_bucket = key
            i += 1
            continue

        # Link line after bucket
        urls = RE_URL.findall(line)
        if urls and current and pending_bucket:
            url = urls[0].rstrip(").,>]")
            b = current["buckets"].get(pending_bucket)
            if b:
                b["url"] = url
                mid = RE_ITEM_ID.search(url)
                if mid:
                    b["item_id"] = mid.group(1)
            pending_bucket = None
            i += 1
            continue

        # Heuristic: new product = line with emoji + name, not a bucket
        if (
            not RE_BUCKET.search(line)
            and not line.startswith("🔗")
            and not line.startswith("http")
            and len(line) > 2
            and not RE_LIMIT.search(line)
        ):
            # skip pure separators
            if set(line) <= set("─-_= "):
                i += 1
                continue
            # likely product title line
            flush()
            # strip trailing flag/gear symbols for slug but keep display
            title = line
            # drop leading single emoji token for cleaner title optional
            parts = title.split(maxsplit=1)
            display = title
            if len(parts) == 2 and len(parts[0]) <= 2:
                display = parts[1]
            current = {
                "index": len(products),
                "display": display.strip(),
                "raw_header": line,
                "slug": _slug(display),
                "limit_line": None,
                "buckets": {
                    "sofort": None,
                    "sofort_plus": None,
                    "auktion": None,
                    "auktion_plus": None,
                },
            }
            pending_bucket = None
            i += 1
            continue

        i += 1

    flush()

    # Drop empty false products (no buckets filled)
    cleaned = []
    for p in products:
        if any(p["buckets"].get(k) for k in p["buckets"]):
            cleaned.append(p)
    for idx, p in enumerate(cleaned):
        p["index"] = idx

    return {
        "source": "telegram_stats_paste",
        "product_count": len(cleaned),
        "products": cleaned,
        "footer": footer,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Parse stats Telegram paste for QA")
    ap.add_argument("input", nargs="?", default=str(DEFAULT_IN), help="paste file path")
    ap.add_argument("-o", "--output", default=str(DEFAULT_OUT), help="JSON output path")
    args = ap.parse_args(argv)

    in_path = Path(args.input)
    out_path = Path(args.output)

    if not in_path.is_file():
        print(f"Missing paste file: {in_path}", file=sys.stderr)
        print("Copy Telegram stats into qa/inbox/stats_paste.txt then re-run.", file=sys.stderr)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        sample = out_path.parent / "stats_paste.EXAMPLE.txt"
        if not sample.exists():
            sample.write_text(
                "📱 iPhone 16 Pro Max 🇩🇪 ⚙️\n"
                "💸 Лимит: 🎯 700€ ⬆️ 900€ ⬇️ 50€\n"
                "🛒 Sofort   612€ │ 🟢 Подходит\n"
                "🔗 https://www.ebay.de/itm/123456789012\n"
                "🤝 Sofort+  590€ │ 🟢 Подходит\n"
                "🔗 https://www.ebay.de/itm/123456789013\n"
                "🔨 Auktion  540€ │ 🟡 Ждёт 24ч\n"
                "🔗 https://www.ebay.de/itm/123456789014\n"
                "⏳ Auktion+ ---  │ ❌ Не найдено\n",
                encoding="utf-8",
            )
            print(f"Wrote example paste skeleton: {sample}")
        return 2

    text = in_path.read_text(encoding="utf-8", errors="replace")
    data = parse_paste(text)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Parsed {data['product_count']} products → {out_path}")
    for p in data["products"][:15]:
        filled = sum(1 for v in p["buckets"].values() if v)
        print(f"  [{p['index']}] {p['display'][:60]}  buckets={filled}")
    if data["product_count"] > 15:
        print(f"  ... +{data['product_count'] - 15} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
