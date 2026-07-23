#!/usr/bin/env python3
"""Open script-reported item IDs via HTML and compare total vs stats price."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import monitor as m  # noqa: E402

PARSED = ROOT / "qa" / "inbox" / "stats_local_parsed.json"
OUT = ROOT / "qa" / "results" / "item_id_verify.json"


def main():
    products = json.loads(PARSED.read_text(encoding="utf-8"))
    rows = []
    for p in products:
        for k in ("sofort", "sofort_plus", "auktion", "auktion_plus"):
            b = p["buckets"][k]
            if b.get("item_id") and b.get("price") is not None:
                rows.append(
                    {
                        "query": p["query"],
                        "bucket": k,
                        "item_id": str(b["item_id"]),
                        "script_price": b["price"],
                    }
                )
    # unique by item_id keep first
    seen = set()
    uniq = []
    for r in rows:
        if r["item_id"] in seen:
            continue
        seen.add(r["item_id"])
        uniq.append(r)

    print(f"Verifying {len(uniq)} unique item ids (of {len(rows)} bucket refs)")
    results = []
    for i, r in enumerate(uniq):
        iid = r["item_id"]
        print(f"[{i+1}/{len(uniq)}] {iid} {r['query'][:30]} {r['bucket']} script={r['script_price']}", flush=True)
        try:
            d = m._fetch_item_details_html(iid)
        except Exception as e:
            d = None
            err = str(e)
        else:
            err = None
        title = ""
        live_price = None
        live_ship = None
        if isinstance(d, dict):
            title = (d.get("title") or "")[:100]
            live_price = d.get("price")
            live_ship = d.get("shipping")
            if live_price is None and d.get("current_bid") is not None:
                live_price = d.get("current_bid")
        total = None
        try:
            if live_price is not None:
                total = float(live_price) + float(live_ship or 0)
        except (TypeError, ValueError):
            total = None
        delta = None
        if total is not None:
            delta = round(total - float(r["script_price"]), 2)
        status = "ok"
        if d is None:
            status = "fetch_fail"
        elif total is None:
            status = "no_price"
        elif abs(delta) <= 15:
            status = "match"
        elif abs(delta) <= 40:
            status = "close"
        else:
            status = "mismatch"
        rec = {
            **r,
            "status": status,
            "live_total": total,
            "live_price": live_price,
            "live_ship": live_ship,
            "delta": delta,
            "title": title,
            "err": err,
        }
        results.append(rec)
        print(f"  -> {status} live={total} delta={delta} {title[:50]}", flush=True)
        time.sleep(0.4)

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("SUMMARY", counts)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
