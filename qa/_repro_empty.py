#!/usr/bin/env python3
"""Reproduce fetch+filter for products that stats showed empty."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import monitor as m  # noqa: E402
from config_manager import ConfigManager  # noqa: E402


def repro(query_substr: str):
    cm = ConfigManager()
    search = None
    for s in cm.get_searches():
        q = (s.get("query") or "").lower()
        if query_substr in q and s.get("filters", {}).get("listing_type") == "buy_now_offer":
            search = s
            break
    if not search:
        print("no search for", query_substr)
        return
    print("===", search.get("query"), "id=", search.get("id"))
    var = m._statistics_search_variant(
        search, "buy_now_offer", search.get("filters", {}).get("min_price"), False
    )
    print(
        "variant",
        {
            k: var["filters"].get(k)
            for k in ("min_price", "max_price", "category", "listing_type", "sort", "_ipg")
        },
    )
    print("smart_q", m._build_smart_search_query(var)[:180])
    print("url", m._build_url_with_host("ebay.de", var)[:220])
    items, err = m.fetch_ebay_ex(var, force=True)
    print("fetch n=", len(items or []), "err=", err)
    for it in sorted(items or [], key=lambda x: float(x.get("total_price") or x.get("price") or 0))[:8]:
        tn = m._normalize(it.get("title") or "")
        prelim = m._intent_prelim_matches_title(tn, search)
        qn = m._normalize(search.get("query") or "")
        cat = m._effective_category(search.get("filters", {}).get("category", "all"), qn)
        blocked = m._is_category_blocked_title(tn, cat, qn)
        qm = m._query_matches_title(tn, search.get("query") or "")
        print(
            " ",
            it.get("total_price") or it.get("price"),
            "prelim=",
            prelim,
            "block=",
            blocked,
            "qmatch=",
            qm,
            "|",
            (it.get("title") or "")[:75],
        )
    cfg = cm._data
    filt = m.filter_results(
        items or [],
        m._statistics_filter_search(search),
        cfg,
        skip_seen=True,
        is_statistics=True,
    )
    print("filtered n=", len(filt))
    for it in sorted(filt, key=lambda x: float(x.get("total_price") or x.get("price") or 0))[:5]:
        print("  KEEP", it.get("total_price") or it.get("price"), (it.get("title") or "")[:75])


def main():
    for q in (
        "odyssey",
        "ultragear",
        "superlight 2 dex",
        "superlight 2",
        "ult (",
    ):
        repro(q)
        print()


if __name__ == "__main__":
    main()
