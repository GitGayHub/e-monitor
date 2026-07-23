#!/usr/bin/env python3
"""Verify previously-empty products now return cheapest valid via HTML pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import monitor as m  # noqa: E402
from config_manager import ConfigManager  # noqa: E402


def cheapest_filtered(query_substr: str):
    cm = ConfigManager()
    search = None
    for s in cm.get_searches():
        q = (s.get("query") or "").lower()
        if query_substr.lower() in q and s.get("filters", {}).get("listing_type") == "buy_now_offer":
            # Prefer exact dex over plain superlight
            if query_substr.lower() == "superlight 2" and "dex" in q:
                continue
            if "dex" in query_substr.lower() and "dex" not in q:
                continue
            search = s
            break
    if not search:
        print("NO_SEARCH", query_substr)
        return
    print("===", search.get("id"), search.get("query"))
    var = m._statistics_search_variant(search, "buy_now_offer", None, False)
    print(
        "  floor=",
        var["filters"].get("min_price"),
        "cat=",
        var["filters"].get("category"),
        "smart=",
        m._build_smart_search_query(var)[:100],
    )
    print("  url=", m._build_url_with_host("ebay.de", var)[:180])
    items, err = m.fetch_ebay_ex(var, force=True)
    print("  fetch", len(items or []), "err", err)
    filt = m.filter_results(
        items or [],
        m._statistics_filter_search(search),
        cm,
        skip_seen=True,
        is_statistics=True,
    )
    # also apply intent prelim for ranking check
    ranked = sorted(filt, key=lambda x: float(x.get("total_price") or x.get("price") or 99999))
    print("  filtered", len(ranked))
    for it in ranked[:5]:
        print(
            "   ",
            round(float(it.get("total_price") or it.get("price") or 0), 2),
            (it.get("title") or "")[:75],
            "id=",
            it.get("item_id"),
        )
    if ranked:
        best = ranked[0]
        print(
            "  CHEAPEST",
            round(float(best.get("total_price") or best.get("price") or 0), 2),
            best.get("item_id"),
        )
    else:
        print("  STILL_EMPTY")


def main():
    m.reset_ebay_session(rotate=True)
    for q in (
        "odyssey",
        "ultragear",
        "superlight 2 dex",
        "superlight 2",
        "ULT",
        "Redmagic 11 Pro",
        "Sony WH-1000XM6",
    ):
        cheapest_filtered(q)
        print()


if __name__ == "__main__":
    main()
