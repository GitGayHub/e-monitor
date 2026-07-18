#!/usr/bin/env python3
"""Full 4-bucket audit: stats_paste vs live eBay for every product.

Buckets: Sofort / Sofort+ / Auktion / Auktion+
Uses monitor parse + filter_results(is_statistics=True) when config present.
Writes qa/results/AUDIT_4BUCKETS.md + .json
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from monitor import (  # noqa: E402
    parse_ebay_results,
    filter_results,
    _normalize,
    _tag_items_for_search,
    _statistics_search_variant,
    _is_implausibly_cheap_device,
)

PASTE = ROOT / "qa" / "inbox" / "stats_paste.txt"
OUT_MD = ROOT / "qa" / "results" / "AUDIT_4BUCKETS.md"
OUT_JSON = ROOT / "qa" / "results" / "AUDIT_4BUCKETS.json"


def parse_stats(text: str) -> list[dict]:
    blocks = re.split(r"(?=^[📦📱🎮💻🖥️🖱️🎧🥽])", text, flags=re.M)
    out = []
    for b in blocks:
        if not b.strip():
            continue
        title_line = b.strip().splitlines()[0]
        name = re.sub(r"^[^\w(]+", "", title_line)
        name = re.split(r"[🌍🇩🇪]", name)[0].strip()
        buckets = {}
        for emoji, key in (
            ("🛒", "sofort"),
            ("🤝", "sofort_plus"),
            ("🔨", "auktion"),
            ("⏳", "auktion_plus"),
        ):
            m = re.search(rf"{re.escape(emoji)}.+?(?:(\d+)€|---).+?│\s*(.+)$", b, re.M)
            if not m:
                buckets[key] = {"price": None, "label": "?", "item_id": None}
                continue
            price = int(m.group(1)) if m.group(1) else None
            label = (m.group(2) or "").strip()
            # link after this emoji block
            chunk = b[m.start() : m.start() + 350]
            lm = re.search(r"ebay\.de/itm/(\d+)", chunk)
            buckets[key] = {
                "price": price,
                "label": label,
                "item_id": lm.group(1) if lm else None,
            }
        out.append({"name": name, "buckets": buckets, "raw": title_line})
    return out


def load_config_searches():
    cfg_path = ROOT / "config.json"
    if not cfg_path.exists():
        return {}
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    by_q = {}
    for s in cfg.get("searches") or []:
        q = (s.get("query") or s.get("display_name") or "").strip()
        if not q:
            continue
        key = _normalize(q)
        # prefer buy_now as base for stats-like mixed
        by_q.setdefault(key, s)
        if "buy" in (s.get("id") or "") or s.get("filters", {}).get("listing_type") in (
            "buy_now",
            "buy_now_offer",
        ):
            by_q[key] = s
    return cfg, by_q


def match_search(product_name: str, by_q: dict):
    pn = _normalize(product_name)
    # exact / substring
    for k, s in by_q.items():
        if k in pn or pn in k:
            return s
    # token overlap
    best, score = None, 0
    ptoks = set(pn.split())
    for k, s in by_q.items():
        st = set(k.split())
        sc = len(ptoks & st)
        if sc > score and sc >= 2:
            best, score = s, sc
    return best


def live_fetch(session, query: str, listing: str, udlo, udhi=2500):
    params = {
        "_nkw": query,
        "_sop": "15",
        "_ipg": "60",
        "rt": "nc",
        "_udlo": str(int(udlo or 0)),
        "_udhi": str(int(udhi or 2500)),
    }
    if listing == "auction":
        params["LH_Auction"] = "1"
    else:
        params["LH_BIN"] = "1"
    url = "https://www.ebay.de/sch/i.html?" + urllib.parse.urlencode(params)
    r = session.get(url, timeout=35)
    items = parse_ebay_results(r.text or "") if r.status_code == 200 else []
    return items, r.status_code, url


def split_buckets(items):
    bin_no, bin_bo, auc_no, auc_bo = [], [], [], []
    for it in items:
        if it.get("buy_now"):
            (bin_bo if it.get("best_offer") else bin_no).append(it)
        if it.get("auction"):
            if it.get("best_offer") and it.get("bids_count") in (0, None):
                auc_bo.append(it)
            elif not it.get("best_offer"):
                auc_no.append(it)
            elif it.get("buy_now") and it.get("auction"):
                # hybrid pure auc side already handled
                pass
    return bin_no, bin_bo, auc_no, auc_bo


def cheapest(items):
    if not items:
        return None, None
    items = sorted(items, key=lambda x: float(x.get("total_price") or x.get("price") or 9e9))
    it = items[0]
    return float(it.get("total_price") or it.get("price") or 0), it.get("item_id")


def main():
    text = PASTE.read_text(encoding="utf-8", errors="replace")
    stats = parse_stats(text)
    cfg, by_q = load_config_searches()
    H = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9",
    }
    session = requests.Session()
    session.headers.update(H)

    findings = []
    lines = ["# Full 4-bucket audit (stats vs live)\n"]

    for prod in stats:
        name = prod["name"]
        search = match_search(name, by_q)
        q = (search.get("query") if search else name) or name
        # strip paren alternatives for live nkw
        q_live = re.sub(r"\([^)]*\)", " ", q)
        q_live = re.sub(r"\s+", " ", q_live).strip()
        filters = (search.get("filters") if search else {}) or {}
        udlo = filters.get("min_price") or 20
        udhi = filters.get("max_price") or 2500

        lines.append(f"\n## {name}\n")
        lines.append(f"query=`{q_live}` min={udlo}\n\n")
        lines.append("| Bucket | Stats € | Live € | Note |\n|---|---:|---:|---|\n")

        # fetch live BIN + auction once each
        try:
            bin_items, bsc, burl = live_fetch(session, q_live, "bin", udlo, udhi)
        except Exception as e:
            bin_items, bsc, burl = [], 0, str(e)
        try:
            auc_items, asc, aurl = live_fetch(session, q_live, "auction", udlo, udhi)
        except Exception as e:
            auc_items, asc, aurl = [], 0, str(e)

        # tag + filter if we have search
        if search:
            bin_s = _statistics_search_variant(search, "buy_now_offer", udlo, False)
            auc_s = _statistics_search_variant(search, "auction", udlo, False)
            bin_items = _tag_items_for_search(bin_items, bin_s)
            auc_items = _tag_items_for_search(auc_items, auc_s)
            try:
                bin_items = filter_results(bin_items, bin_s, cfg, skip_seen=True, is_statistics=True)
                auc_items = filter_results(auc_items, auc_s, cfg, skip_seen=True, is_statistics=True)
            except Exception as e:
                lines.append(f"filter err: {e}\n")
            # drop implausible
            bin_items = [x for x in bin_items if not _is_implausibly_cheap_device(x, search)]
            auc_items = [x for x in auc_items if not _is_implausibly_cheap_device(x, search)]

        b_no, b_bo, _, _ = split_buckets(bin_items)
        # auctions from auction SERP
        _, _, a_no, a_bo = split_buckets(auc_items)
        # also hybrids from bin SERP
        for it in bin_items:
            if it.get("auction") and not it.get("best_offer"):
                a_no.append(it)
            if it.get("auction") and it.get("best_offer") and it.get("bids_count") in (0, None):
                a_bo.append(it)

        live_map = {
            "sofort": cheapest(b_no),
            "sofort_plus": cheapest(b_bo),
            "auktion": cheapest(a_no),
            "auktion_plus": cheapest(a_bo),
        }

        for key, label in (
            ("sofort", "Sofort"),
            ("sofort_plus", "Sofort+"),
            ("auktion", "Auktion"),
            ("auktion_plus", "Auktion+"),
        ):
            sb = prod["buckets"].get(key) or {}
            sp = sb.get("price")
            lp, lid = live_map[key]
            note = "ok"
            if lp is not None and sp is not None and lp + 15 < sp:
                note = "CHEAPER_LIVE"
            elif lp is not None and sp is None:
                note = "STATS_MISS"
            elif lp is None and sp is not None:
                note = "LIVE_MISS_OR_FILTER"
            elif bsc == 403 and key.startswith("sofort"):
                note = "LIVE_403"
            elif asc == 403 and key.startswith("auktion"):
                note = "LIVE_403"
            lines.append(
                f"| {label} | {sp if sp is not None else '—'} | "
                f"{int(lp) if lp is not None else '—'} | {note} |\n"
            )
            findings.append(
                {
                    "product": name,
                    "bucket": key,
                    "stats_price": sp,
                    "live_price": lp,
                    "live_id": lid,
                    "stats_id": sb.get("item_id"),
                    "note": note,
                    "query": q_live,
                }
            )

        lines.append(f"\n_live BIN sc={bsc} n={len(bin_items)}; AUC sc={asc} n={len(auc_items)}_\n")

    # summary
    miss = [f for f in findings if f["note"] == "STATS_MISS"]
    cheap = [f for f in findings if f["note"] == "CHEAPER_LIVE"]
    lines.insert(
        1,
        f"\n**STATS_MISS={len(miss)} CHEAPER_LIVE={len(cheap)} total_rows={len(findings)}**\n",
    )
    lines.append("\n## STATS_MISS detail\n")
    for f in miss:
        lines.append(
            f"- **{f['product']}** {f['bucket']}: live {f['live_price']:.0f}€ "
            f"id={f['live_id']} q=`{f['query']}`\n"
        )
    lines.append("\n## CHEAPER_LIVE detail\n")
    for f in cheap:
        lines.append(
            f"- **{f['product']}** {f['bucket']}: stats {f['stats_price']} → live "
            f"{f['live_price']:.0f}€ (Δ{f['stats_price']-f['live_price']:.0f}) "
            f"id={f['live_id']}\n"
        )

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    OUT_JSON.write_text(json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"STATS_MISS={len(miss)} CHEAPER_LIVE={len(cheap)}")
    for f in miss[:40]:
        print("MISS", f["product"], f["bucket"], f["live_price"], f["live_id"])
    for f in cheap[:30]:
        print(
            "CHEAP",
            f["product"],
            f["bucket"],
            f["stats_price"],
            "->",
            f["live_price"],
            f["live_id"],
        )


if __name__ == "__main__":
    main()
