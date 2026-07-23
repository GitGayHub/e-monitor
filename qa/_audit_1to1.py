#!/usr/bin/env python3
"""1:1 audit: local stats prices vs live eBay HTML (same stack as bot) + item page check.

For each product:
  - load script bucket prices/ids from stats_local_parsed.json
  - fetch BIN price_asc HTML via monitor.fetch_ebay_ex
  - apply filter_results / notify-ish validity loosely via filter_results is_statistics
  - compare cheapest valid device-ish candidates vs script Sofort
  - for empties: flag gap if HTML has plausible devices under high ceiling

Does NOT use Browse API search. Item detail may use HTML.

Usage:
  python qa/_parse_local_stats.py
  python qa/_audit_1to1.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import monitor  # noqa: E402

INBOX = Path(__file__).resolve().parent / "inbox"
RESULTS = Path(__file__).resolve().parent / "results"
PARSED = INBOX / "stats_local_parsed.json"
OUT = RESULTS / "AUDIT_1TO1_LIVE.md"
OUT_JSON = RESULTS / "audit_1to1_live.json"


def _total(item):
    try:
        p = float(item.get("price") or 0)
    except (TypeError, ValueError):
        p = 0.0
    try:
        s = float(item.get("shipping") or 0)
    except (TypeError, ValueError):
        s = 0.0
    return p + s


def _search_cfg(query: str, listing: str, min_price=None):
    return {
        "id": f"audit_{listing}",
        "query": query,
        "filters": {
            "listing_type": "buy_now_offer" if listing == "bin" else "auction",
            "best_offer": listing in ("bin_bo", "auc_bo"),
            "location": "worldwide",
            "category": "all",
            "sort": "price_asc",
            "min_price": min_price,
            "_ipg": 60,
        },
    }


def _fetch_bin(query: str, min_price=None):
    search = _search_cfg(query, "bin", min_price=min_price)
    items, err = monitor.fetch_ebay_ex(search, force=True)
    return items or [], err


def _fetch_auction(query: str, min_price=None):
    search = _search_cfg(query, "auction", min_price=min_price)
    items, err = monitor.fetch_ebay_ex(search, force=True)
    return items or [], err


def _filter_stats(query: str, items, listing="bin"):
    """Run bot filter_results in statistics mode."""
    search = {
        "id": "audit",
        "query": query,
        "enabled": True,
        "filters": {
            "listing_type": "buy_now_offer" if listing == "bin" else "auction",
            "location": "worldwide",
            "category": "all",
            "max_price": 99999,
            "min_price": None,
        },
    }
    # Use a high max so we see what filter keeps, not limit
    try:
        from config_manager import ConfigManager

        cm = ConfigManager()
        cfg = getattr(cm, "_data", None) or getattr(cm, "data", None) or {
            "searches": cm.get_searches(),
            "settings": {},
        }
    except Exception:
        cfg = {"searches": [], "settings": {}}
    # Prefer real search row from config if query matches
    for s in cfg.get("searches") or []:
        if monitor._normalize(s.get("query") or "") == monitor._normalize(query):
            search = dict(s)
            search["filters"] = dict(s.get("filters") or {})
            search["filters"]["max_price"] = 99999  # show candidates regardless of alert limit
            break
    filtered = monitor.filter_results(
        items, search, cfg, skip_seen=True, is_statistics=True
    )
    return filtered or []


def _top_valid(items, n=5):
    ranked = sorted(items, key=_total)
    out = []
    for it in ranked[: n * 3]:
        out.append(
            {
                "total": round(_total(it), 2),
                "price": it.get("price"),
                "shipping": it.get("shipping"),
                "title": (it.get("title") or "")[:90],
                "item_id": str(it.get("item_id") or ""),
                "url": it.get("url") or f"https://www.ebay.de/itm/{it.get('item_id')}",
            }
        )
        if len(out) >= n:
            break
    return out


def audit_one(product: dict) -> dict:
    q = product["query"]
    # strip odd grouping for display
    q_clean = re.sub(r"[()]", " ", q)
    q_clean = re.sub(r"\s+", " ", q_clean).strip()
    b = product["buckets"]
    script_sofort = b.get("sofort", {}).get("price")
    script_splus = b.get("sofort_plus", {}).get("price")
    script_auc = b.get("auktion", {}).get("price")
    script_aplus = b.get("auktion_plus", {}).get("price")

    # min floor for phones/headphones-ish to skip pure trash
    min_p = 50.0
    if any(x in q.lower() for x in ("superlight", "superstrike", "ult", "xm6", "mouse")):
        min_p = 30.0
    if any(x in q.lower() for x in ("odyssey", "ultragear", "oled g6", "480hz", "500hz")):
        min_p = 100.0
    if any(x in q.lower() for x in ("5070", "4080", "4050", "4060", "pc", "rechner")):
        min_p = 200.0

    time.sleep(0.8)
    raw_bin, err_bin = _fetch_bin(q_clean if q_clean else q, min_price=min_p)
    filt_bin = _filter_stats(q, raw_bin, "bin") if raw_bin else []
    top_raw = _top_valid(raw_bin, 5)
    top_filt = _top_valid(filt_bin, 5)

    time.sleep(0.6)
    raw_auc, err_auc = _fetch_auction(q_clean if q_clean else q, min_price=min_p)
    filt_auc = _filter_stats(q, raw_auc, "auction") if raw_auc else []
    top_auc_filt = _top_valid(filt_auc, 3)

    cheapest_filt = top_filt[0]["total"] if top_filt else None
    cheapest_raw_device = None
    # pick first raw that is not obvious accessory via monitor helpers
    for it in sorted(raw_bin, key=_total)[:40]:
        tn = monitor._normalize(it.get("title") or "")
        if monitor._is_phone_accessory_title(tn) or monitor._is_plush_or_toy_title(tn):
            continue
        if monitor._is_console_game_only_title(tn):
            continue
        cheapest_raw_device = {
            "total": round(_total(it), 2),
            "title": (it.get("title") or "")[:90],
            "item_id": str(it.get("item_id") or ""),
        }
        break

    verdict = "ok"
    notes = []
    empty_all = all(
        x is None for x in (script_sofort, script_splus, script_auc, script_aplus)
    )

    if empty_all:
        if cheapest_filt is not None:
            verdict = "gap_missed"
            notes.append(
                f"script ALL empty but filter keeps BIN total={cheapest_filt}€: {top_filt[0]['title'][:60]}"
            )
        elif cheapest_raw_device and cheapest_raw_device["total"] < 2500:
            verdict = "gap_or_filter"
            notes.append(
                f"script empty; raw non-acc from {cheapest_raw_device['total']}€ — check filters: {cheapest_raw_device['title'][:60]}"
            )
        elif err_bin in ("blocked", "rate_limit", "cooldown") or not raw_bin:
            verdict = "fetch_empty"
            notes.append(f"HTML fetch empty/block err={err_bin} n={len(raw_bin)}")
        else:
            verdict = "ok_empty"
            notes.append(f"empty script; raw n={len(raw_bin)} but no filter pass")
    else:
        # compare Sofort
        if script_sofort is not None and cheapest_filt is not None:
            if cheapest_filt + 1 < script_sofort * 0.85 or (
                script_sofort - cheapest_filt >= 20 and cheapest_filt < script_sofort
            ):
                verdict = "price_gap"
                notes.append(
                    f"Sofort script={script_sofort}€ vs filtered cheapest={cheapest_filt}€ "
                    f"({top_filt[0]['title'][:50]})"
                )
            elif abs(cheapest_filt - script_sofort) <= 15 or cheapest_filt >= script_sofort * 0.9:
                notes.append(
                    f"Sofort close: script={script_sofort} live_filt={cheapest_filt}"
                )
            else:
                notes.append(
                    f"Sofort script={script_sofort} live_filt={cheapest_filt}"
                )
        elif script_sofort is not None and cheapest_filt is None:
            notes.append(
                f"script Sofort={script_sofort} but live filter empty (market moved or strict)"
            )
            if verdict == "ok":
                verdict = "stale_or_strict"
        # verify item id still exists roughly via presence in raw
        for key in ("sofort", "sofort_plus", "auktion", "auktion_plus"):
            iid = b.get(key, {}).get("item_id")
            pr = b.get(key, {}).get("price")
            if not iid or pr is None:
                continue
            found = any(str(it.get("item_id")) == str(iid) for it in raw_bin + raw_auc)
            if not found:
                notes.append(f"{key} item {iid} not in current search page (may sold/ended)")

    return {
        "query": q,
        "script": {
            "sofort": script_sofort,
            "sofort_plus": script_splus,
            "auktion": script_auc,
            "auktion_plus": script_aplus,
            "ids": {
                k: b.get(k, {}).get("item_id")
                for k in ("sofort", "sofort_plus", "auktion", "auktion_plus")
            },
        },
        "live": {
            "bin_raw_n": len(raw_bin),
            "bin_filt_n": len(filt_bin),
            "bin_err": err_bin,
            "auc_raw_n": len(raw_auc),
            "auc_filt_n": len(filt_auc),
            "auc_err": err_auc,
            "top_filt_bin": top_filt,
            "top_raw_bin": top_raw[:3],
            "top_filt_auc": top_auc_filt,
            "cheapest_raw_device": cheapest_raw_device,
        },
        "verdict": verdict,
        "notes": notes,
    }


def main():
    if not PARSED.exists():
        print("Run qa/_parse_local_stats.py first")
        return 1
    products = json.loads(PARSED.read_text(encoding="utf-8"))
    print(f"Auditing {len(products)} products HTML 1:1 ...")
    results = []
    for i, p in enumerate(products):
        print(f"\n[{i+1}/{len(products)}] {p['query']}", flush=True)
        try:
            r = audit_one(p)
        except Exception as e:
            r = {"query": p["query"], "verdict": "error", "notes": [str(e)], "script": p.get("buckets"), "live": {}}
        results.append(r)
        print(f"  -> {r['verdict']}: {'; '.join(r.get('notes') or [])[:160]}", flush=True)

    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# Audit 1:1 live HTML — {datetime.now(timezone.utc).isoformat()}",
        "",
        "Source: `qa/inbox/local_stats_html.log` (stats run) vs live `fetch_ebay_ex` + `filter_results(is_statistics=True)`.",
        "",
        "| # | Product | Script S/S+/A/A+ | Live filt BIN min | Verdict | Notes |",
        "|---|---------|------------------|-------------------|---------|-------|",
    ]
    for i, r in enumerate(results):
        s = r.get("script") or {}
        def f(x):
            return "---" if x is None else str(x)
        script_s = f"{f(s.get('sofort'))}/{f(s.get('sofort_plus'))}/{f(s.get('auktion'))}/{f(s.get('auktion_plus'))}"
        live = r.get("live") or {}
        top = (live.get("top_filt_bin") or [{}])
        live_min = top[0].get("total", "---") if top else "---"
        notes = "; ".join(r.get("notes") or [])[:120].replace("|", "/")
        lines.append(
            f"| {i+1} | {r.get('query','')[:40]} | {script_s} | {live_min} | **{r.get('verdict')}** | {notes} |"
        )

    summary = {}
    for r in results:
        summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
    lines += ["", "## Summary counts", ""]
    for k, v in sorted(summary.items(), key=lambda x: -x[1]):
        lines.append(f"- `{k}`: **{v}**")
    lines += ["", f"JSON: `{OUT_JSON.as_posix()}`", ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n=== SUMMARY ===")
    for k, v in sorted(summary.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
