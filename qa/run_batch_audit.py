#!/usr/bin/env python3
"""Batch-list stats catalog + run lightweight eBay HTML search audit (no browser UI).

Uses curl_cffi / requests stack already in monitor for eBay search pages.
Does not open user's Telegram.

Usage:
  python qa/fetch_stats_from_github.py
  python qa/parse_stats_paste.py
  python qa/run_batch_audit.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import monitor  # noqa: E402

INBOX = Path(__file__).resolve().parent / "inbox"
RESULTS = Path(__file__).resolve().parent / "results"
PARSED = INBOX / "stats_parsed.json"
FINDINGS = RESULTS / "findings.csv"


def _price_from_text(t: str):
    if not t:
        return None
    m = re.search(r"(\d+[.,]\d+|\d+)", t.replace("\xa0", " "))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _ebay_search(query: str, listing: str, min_price: float | None = 120.0, max_items: int = 40):
    """listing: bin | auction"""
    params = {
        "_nkw": query,
        "_sop": "15",  # price+shipping asc
        "_ipg": "60",
        "rt": "nc",
        "LH_PrefLoc": "3",
    }
    if listing == "bin":
        params["LH_BIN"] = "1"
    elif listing == "auction":
        params["LH_Auction"] = "1"
    if min_price:
        params["_udlo"] = str(int(min_price))
    q = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    url = f"https://www.ebay.de/sch/i.html?{q}"
    search = {
        "query": query,
        "filters": {
            "listing_type": "buy_now_offer" if listing == "bin" else "auction",
            "location": "worldwide",
            "category": "all",
            "min_price": min_price,
            "sort": "price_asc",
            "_ipg": 60,
        },
    }
    items, err = monitor.fetch_ebay_ex(search, force=True)
    if err and not items:
        return [], err, url
    return items or [], err, url


def _is_valid_for_product(item: dict, product: dict) -> bool:
    title = item.get("title") or ""
    tn = monitor._normalize(title)
    q_raw = re.sub(r"[🌍🇩🇪🇪🇺⚙️♾️]+", "", product.get("display") or "")
    q_raw = re.sub(r"\s+", " ", q_raw).strip()
    # Prefer query without emoji noise
    for key in ("query", "display"):
        if product.get(key):
            q_raw = re.sub(r"[🌍🇩🇪🇪🇺⚙️♾️📦📱🎮🎧🖥️]+", "", str(product[key]))
            q_raw = re.sub(r"\s+", " ", q_raw).strip()
            break
    # Use slug-ish base from display
    display = product.get("display") or product.get("slug") or ""
    qn = monitor._normalize(re.sub(r"[🌍🇩🇪🇪🇺⚙️♾️📦📱🎮🎧🖥️]+", "", display))
    if not qn:
        qn = monitor._normalize(product.get("slug", "").replace("_", " "))

    search = {
        "query": display.split("🌍")[0].split("🇩🇪")[0].strip()
        if display
        else qn,
        "filters": {"category": "all", "limit_price": _limit_from_product(product)},
    }
    # Rebuild cleaner query from slug
    query_guess = product.get("slug", "").replace("_", " ")
    # Prefer known names from display without flags
    query_guess = re.sub(r"[^\w\s\+\(\),\.\-]", " ", display, flags=re.UNICODE)
    query_guess = re.sub(r"\s+", " ", query_guess).strip()
    # remove trailing location words
    query_guess = re.sub(r"\s+(de|eu|worldwide)\s*$", "", query_guess, flags=re.I)
    search["query"] = query_guess or qn

    qn = monitor._normalize(search["query"])
    cat = monitor._effective_category("all", qn)

    if cat == "phones" or monitor._is_phone_search_query(qn):
        if not monitor._matches_phone_query_model(tn, qn):
            return False
        if monitor._is_phone_accessory_title(tn):
            return False
        if not monitor._is_phone_device_title(tn):
            return False
        return True

    if "sony wh" in qn or "1000xm" in qn or "ult wear" in qn:
        if monitor._is_category_blocked_title(tn, "headphones", qn):
            return False
        # reject pure pads
        if any(w in tn for w in ("ohrpolster", "earpad", "ear pad", "case only", "nur hulle")):
            return False
        return monitor._query_matches_title(tn, search["query"]) or "xm6" in tn or "xm5" in tn

    if "superstrike" in qn or "superlight" in qn:
        if "superstrike" in qn:
            return monitor._matches_superstrike_mouse(tn)
        return monitor._query_matches_title(tn, search["query"]) and not monitor._is_category_blocked_title(
            tn, "mice", qn
        )

    if monitor._is_ps5_pro_search_query(qn):
        return monitor._has_ps5_pro_console_hint(tn) and not monitor._is_ps5_vr_only_title(tn)

    if "5070" in qn or "4080" in qn:
        return monitor._matches_category_query(tn, "computers", qn)

    if "odyssey" in qn or "ultragear" in qn or "oled" in qn and ("480" in qn or "g6" in qn or "4050" in qn or "4060" in qn):
        return monitor._matches_category_query(tn, "monitors" if "monitor" in qn or "odyssey" in qn or "ultragear" in qn else "laptops", qn) or monitor._query_matches_title(tn, search["query"])

    # default: query match + not blocked if category known
    if not monitor._query_matches_title(tn, search["query"]):
        # loose: all query words of length > 2 present?
        words = [w for w in re.findall(r"[a-z0-9]+", qn) if len(w) > 2 and w not in ("the", "and", "pro")]
        if words and not all(w in tn for w in words[:4]):
            return False
    if cat and cat != "all" and monitor._is_category_blocked_title(tn, cat, qn):
        return False
    return True


def _limit_from_product(product: dict):
    line = product.get("limit_line") or ""
    m = re.search(r"🎯\s*(\d+)", line)
    if m:
        return float(m.group(1))
    return None


def _best_manual(items: list, product: dict):
    limit = _limit_from_product(product)
    floor = monitor._min_plausible_device_price(
        {"query": product.get("slug", "").replace("_", " "), "filters": {"limit_price": limit}}
    )
    # better query from display
    disp = re.sub(r"[🌍🇩🇪🇪🇺⚙️♾️📦📱🎮🎧🖥️]+", "", product.get("display") or "")
    disp = re.sub(r"\s+", " ", disp).strip()
    search = {"query": disp, "filters": {"limit_price": limit, "category": "all"}}
    floor = max(floor, monitor._min_plausible_device_price(search))

    best = None
    best_over = None
    for it in items:
        try:
            total = float(it.get("total_price") or it.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if total <= 0:
            continue
        if not _is_valid_for_product(it, product):
            continue
        # use floor from product query
        if floor and total < floor:
            continue
        entry = {
            "price_eur": total,
            "total_eur": total,
            "title": it.get("title"),
            "url": it.get("url") or f"https://www.ebay.de/itm/{it.get('item_id')}",
            "item_id": str(it.get("item_id")),
        }
        if limit is not None and total > limit:
            if best_over is None or total < best_over["total_eur"]:
                best_over = entry
            continue
        if best is None or total < best["total_eur"]:
            best = entry
    return best, best_over


def audit_product(product: dict) -> dict:
    disp = re.sub(r"[🌍🇩🇪🇪🇺⚙️♾️📦📱🎮🎧🖥️]+", "", product.get("display") or product.get("slug", ""))
    disp = re.sub(r"\s+", " ", disp).strip()
    queries = [disp]
    # compact aliases
    if "iphone" in disp.lower():
        queries += [re.sub(r"(?i)apple\s+", "", disp), re.sub(r"(?i)iphone\s+", "", disp)]
    if "redmagic" in disp.lower() or "red magic" in disp.lower():
        queries += [disp.replace("Redmagic", "red magic"), "nubia " + disp]
    if "playstation" in disp.lower() or "ps5" in disp.lower():
        queries += ["ps5 pro", "playstation 5 pro"]
    # dedupe
    seen = set()
    qlist = []
    for q in queries:
        q = q.strip()
        k = q.lower()
        if q and k not in seen:
            seen.add(k)
            qlist.append(q)
    qlist = qlist[:4]

    limit = _limit_from_product(product)
    min_p = 120.0 if any(x in disp.lower() for x in ("iphone", "redmagic", "nubia", "pixel", "samsung", "s24")) else 50.0
    if "sony" in disp.lower() or "xm6" in disp.lower() or "ult" in disp.lower():
        min_p = 80.0
    if "superlight" in disp.lower() or "superstrike" in disp.lower():
        min_p = 35.0

    buckets_out = {}
    overall = "ok"
    findings = []

    for bkey, listing in (
        ("sofort", "bin"),
        ("sofort_plus", "bin"),
        ("auktion", "auction"),
        ("auktion_plus", "auction"),
    ):
        script = product.get("buckets", {}).get(bkey) or {}
        script_price = script.get("price_eur")
        script_verdict = script.get("verdict") or ""

        all_items = []
        err = None
        used_q = None
        for q in qlist:
            items, e, url = _ebay_search(q, "bin" if "sofort" in bkey else "auction", min_price=min_p)
            err = e or err
            if items:
                all_items.extend(items)
                used_q = q
            time.sleep(0.4)

        # de-dupe by id
        by_id = {}
        for it in all_items:
            by_id[str(it.get("item_id"))] = it
        items = list(by_id.values())

        best, best_over = _best_manual(items, product)
        manual = best or best_over
        # verdict
        if err and not items:
            verdict = "blocked_ebay"
            sev = "P2"
            notes = f"fetch err={err}"
        elif script_price is None and manual is None:
            verdict = "ok"
            sev = None
            notes = "both empty (or only invalid/accessories)"
        elif script_price is None and best is not None:
            # script empty, manual under limit valid
            verdict = "gap_missed"
            sev = "P0"
            notes = "script --- but valid under-limit on eBay"
            overall = "gap_missed"
        elif script_price is None and best_over is not None:
            # should show as expensive, not empty
            verdict = "gap_missed"
            sev = "P0"
            notes = f"script --- but valid phone/device exists at {best_over['total_eur']}€ (over limit → should be purple)"
            overall = "gap_missed"
        elif script_price is not None and best is not None and best["total_eur"] + 1 < float(script_price):
            verdict = "gap_cheaper"
            sev = "P1" if float(script_price) - best["total_eur"] >= 20 else "P2"
            notes = "manual cheaper valid"
            overall = "gap_missed" if overall == "ok" else overall
        else:
            verdict = "ok"
            sev = None
            notes = "aligned or manual not cheaper"

        buckets_out[bkey] = {
            "script": {
                "price_eur": script_price,
                "verdict": script_verdict,
                "url": script.get("url"),
                "item_id": script.get("item_id"),
            },
            "manual_best": manual,
            "manual_under_limit": best,
            "manual_over_limit": best_over,
            "verdict": verdict,
            "severity": sev,
            "notes": notes,
            "query_used": used_q,
            "fetched": len(items),
            "fetch_err": err,
        }
        if sev:
            findings.append(
                {
                    "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "product_slug": product.get("slug"),
                    "bucket": bkey,
                    "severity": sev,
                    "verdict": verdict,
                    "script_eur": script_price or "",
                    "manual_eur": (manual or {}).get("total_eur") or "",
                    "delta_eur": "",
                    "script_url": script.get("url") or "",
                    "manual_url": (manual or {}).get("url") or "",
                    "query_used": used_q or "",
                    "notes": notes,
                }
            )

    slug = product.get("slug") or f"item_{product.get('index')}"
    result = {
        "schema": "e-monitor-qa-result/v1",
        "slug": slug,
        "display": product.get("display"),
        "stats_index": product.get("index"),
        "audited_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "auditor": "agent-batch",
        "limit_line": product.get("limit_line"),
        "aliases_tried": qlist,
        "buckets": buckets_out,
        "overall": overall,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS / f"{slug}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result, findings


def main():
    if not PARSED.exists():
        print("Missing stats_parsed.json — run fetch + parse first", file=sys.stderr)
        sys.exit(1)
    data = json.loads(PARSED.read_text(encoding="utf-8"))
    products = data.get("products") or []
    print(f"Auditing {len(products)} products…")
    all_findings = []
    summary = []
    for p in products:
        print(f"\n=== [{p.get('index')}] {p.get('display')} ===")
        try:
            res, finds = audit_product(p)
        except Exception as e:
            print("  ERROR", e)
            summary.append((p.get("index"), p.get("slug"), "error", str(e)))
            continue
        all_findings.extend(finds)
        gaps = [b for b, v in res["buckets"].items() if v["verdict"] in ("gap_missed", "gap_cheaper")]
        print(f"  overall={res['overall']} gaps={gaps or '-'}")
        for b, v in res["buckets"].items():
            sp = v["script"].get("price_eur")
            mb = v.get("manual_best") or {}
            print(
                f"  {b:12s} script={sp or '---':>8}  manual={mb.get('total_eur') or '---':>8}  {v['verdict']}"
            )
        summary.append((p.get("index"), p.get("slug"), res["overall"], ",".join(gaps)))

    # write findings
    fieldnames = [
        "date_utc",
        "product_slug",
        "bucket",
        "severity",
        "verdict",
        "script_eur",
        "manual_eur",
        "delta_eur",
        "script_url",
        "manual_url",
        "query_used",
        "notes",
    ]
    with FINDINGS.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in all_findings:
            w.writerow(row)

    report_path = RESULTS / "BATCH_REPORT.md"
    lines = [
        f"# Batch QA report {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Products: **{len(products)}** · Findings rows: **{len(all_findings)}**",
        "",
        "| # | Product | Overall | Gap buckets |",
        "|---|---------|---------|-------------|",
    ]
    for idx, slug, overall, gaps in summary:
        lines.append(f"| {idx} | {slug} | {overall} | {gaps or '—'} |")
    lines.append("")
    lines.append("## P0/P1 details")
    lines.append("")
    for row in all_findings:
        if row.get("severity") in ("P0", "P1"):
            lines.append(
                f"- **{row['severity']}** `{row['product_slug']}` / {row['bucket']}: "
                f"script={row['script_eur'] or '—'} manual={row['manual_eur'] or '—'} — {row['notes']}"
            )
            if row.get("manual_url"):
                lines.append(f"  - {row['manual_url']}")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nWrote", report_path)
    print("Findings", len(all_findings), "->", FINDINGS)


if __name__ == "__main__":
    main()
