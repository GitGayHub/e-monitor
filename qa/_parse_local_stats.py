#!/usr/bin/env python3
"""Parse local_stats_html.log into structured JSON with prices + item ids."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "qa" / "inbox" / "local_stats_html.log"
OUT = ROOT / "qa" / "inbox" / "stats_local_parsed.json"


def _read_log(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    # UTF-16 LE without BOM heuristic: many NULs in first 200 bytes
    sample = raw[:200]
    if sample and sample[1:2] == b"\x00" and b"\x00" in sample[::2]:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def main():
    log = _read_log(LOG)
    parts = re.split(r"Generated statistics block for '([^']+)':\r?\n", log)
    out = []
    i = 1
    while i < len(parts) - 1:
        name = parts[i]
        body = parts[i + 1]
        m = re.search(r"\r?\n2026-\d{2}-\d{2} ", body)
        if m:
            body = body[: m.start()]
        buckets = {
            "sofort": {"price": None, "item_id": None, "url": None},
            "sofort_plus": {"price": None, "item_id": None, "url": None},
            "auktion": {"price": None, "item_id": None, "url": None},
            "auktion_plus": {"price": None, "item_id": None, "url": None},
        }
        # Parse each bucket line with following link
        # Example: Sofort     1505€ │ ... then later <a href="https://www.ebay.de/itm/ID"
        bucket_order = [
            ("sofort_plus", r"Sofort\+"),
            ("auktion_plus", r"Auktion\+"),
            ("sofort", r"Sofort(?!\+)"),
            ("auktion", r"Auktion(?!\+)"),
        ]
        for key, lab in bucket_order:
            # find label with price
            mm = re.search(lab + r"\s+([0-9.]+|---)", body)
            if not mm:
                continue
            raw = mm.group(1)
            if raw != "---":
                try:
                    buckets[key]["price"] = float(raw)
                except ValueError:
                    buckets[key]["price"] = raw
            # next itm link after this match
            rest = body[mm.end() : mm.end() + 800]
            lid = re.search(r"ebay\.de/itm/(\d+)", rest)
            if lid and buckets[key]["price"] is not None:
                buckets[key]["item_id"] = lid.group(1)
                buckets[key]["url"] = f"https://www.ebay.de/itm/{lid.group(1)}"

        out.append({"query": name, "buckets": buckets, "body_preview": body[:400]})
        i += 2

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"products={len(out)} -> {OUT}")
    for p in out:
        b = p["buckets"]

        def fmt(k):
            x = b[k]
            pr = x["price"]
            iid = x["item_id"] or ""
            return f"{pr if pr is not None else '---':>7} {iid}"

        print(
            f"{p['query'][:42]:42} "
            f"S={fmt('sofort'):18} "
            f"S+={fmt('sofort_plus'):18} "
            f"A={fmt('auktion'):18} "
            f"A+={fmt('auktion_plus'):18}"
        )


if __name__ == "__main__":
    main()
