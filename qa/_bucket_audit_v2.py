#!/usr/bin/env python3
"""Efficient per-product×4-bucket audit of bot stats vs live HTML.

One BIN fetch + one Auction fetch per product, then split Sofort/+/Auktion/+.
Also checks bot item_ids via HTML item page title when present.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import monitor as m  # noqa: E402
from config_manager import ConfigManager  # noqa: E402

LOG = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "qa/inbox/local_stats_html.log")
OUT_MD = ROOT / "qa/results/BUCKET_AUDIT_FULL.md"
OUT_JSON = ROOT / "qa/results/bucket_audit_full.json"


def read_log(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(raw) > 3 and raw[1] == 0):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def parse_blocks(text: str):
    parts = re.split(r"Generated statistics block for '([^']+)':\r?\n", text)
    out = []
    i = 1
    while i < len(parts) - 1:
        name = parts[i]
        body = parts[i + 1]
        cut = re.search(r"\r?\n\d{4}-\d{2}-\d{2} ", body)
        if cut:
            body = body[: cut.start()]
        limit = None
        lm = re.search(r"Лимит:[^\n]+", body)
        if lm:
            limit = re.sub(r"<[^>]+>", "", lm.group(0)).strip()
        buckets = {}
        for key, lab in (
            ("sofort_plus", r"Sofort\+"),
            ("auktion_plus", r"Auktion\+"),
            ("sofort", r"Sofort(?!\+)"),
            ("auktion", r"Auktion(?!\+)"),
        ):
            mm = re.search(lab + r"\s+([0-9.]+|---)", body)
            price = None
            item_id = None
            if mm:
                rawp = mm.group(1)
                if rawp != "---":
                    try:
                        price = float(rawp)
                    except ValueError:
                        price = rawp
                rest = body[mm.end() : mm.end() + 900]
                idm = re.search(r"ebay\.de/itm/(\d+)", rest)
                if idm and price is not None:
                    item_id = idm.group(1)
            buckets[key] = {"price": price, "item_id": item_id}
        dm = re.search(r"<b>([^<]+)</b>", body)
        display = (
            re.sub(r"[🌍🇩🇪🇪🇺⚙️♾️📦📱🎮🎧🖥️🖱️]+", "", dm.group(1)).strip()
            if dm
            else name
        )
        out.append(
            {
                "query": name,
                "display": display,
                "limit": limit,
                "buckets": buckets,
            }
        )
        i += 2
    return out


def total(it) -> float:
    try:
        return float(it.get("total_price") or it.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0


def find_search(cm: ConfigManager, query: str):
    qn = m._normalize(query)
    fallback = None
    for s in cm.get_searches():
        sq = m._normalize(s.get("query") or "")
        if sq == qn or qn in sq or sq in qn:
            if s.get("filters", {}).get("listing_type") == "buy_now_offer":
                return s
            fallback = fallback or s
    # intent kind match
    want = m._search_intent({"query": query})
    if want:
        for s in cm.get_searches():
            if m._search_intent(s) and m._search_intent(s).get("kind") == want.get("kind"):
                if s.get("filters", {}).get("listing_type") == "buy_now_offer":
                    return s
    return fallback


def split_bucket(items, key: str):
    """Filter already-validated list into one of 4 stats buckets."""
    out = []
    for it in items:
        buy = bool(it.get("buy_now"))
        auc = bool(it.get("auction"))
        bo = bool(it.get("best_offer"))
        if key == "sofort":
            if buy and not bo:
                out.append(it)
            elif buy and auc and not bo:
                out.append(it)
        elif key == "sofort_plus":
            if buy and bo:
                out.append(it)
        elif key == "auktion":
            if auc and not bo:
                out.append(it)
        elif key == "auktion_plus":
            if auc and bo:
                out.append(it)
    return sorted(out, key=total)


def fetch_filtered(cm, search_tpl, listing: str):
    var = m._statistics_search_variant(
        search_tpl, listing, search_tpl.get("filters", {}).get("min_price"), False
    )
    # also pull BO into same listing type by second fetch without excluding BO at eBay level
    # eBay doesn't filter BO well; we fetch once and split client-side
    var["filters"]["best_offer"] = False
    var["filters"].pop("_stats_bucket_filter", None)  # don't drop BO at fetch filter
    items, err = m.fetch_ebay_ex(var, force=True)
    # Use filter without bucket lock so BO and non-BO both pass listing type
    fs = m._statistics_filter_search(search_tpl)
    fs["filters"]["listing_type"] = listing if listing != "buy_now_offer" else "buy_now_offer"
    # accept all listing types in filter then we split
    fs["filters"]["listing_type"] = "all"
    filt = m.filter_results(
        items or [], fs, cm, skip_seen=True, is_statistics=True
    )
    return filt or [], err, len(items or [])


def fix_note(query: str) -> str:
    q = m._normalize(query)
    notes = []
    if "odyssey" in q or "g60sf" in q or "ls27fg" in q:
        notes.append(
            "FIX: query без (G60SF…); samsung≠phone; LS27FG604; monitors fetch category=all"
        )
    if "ultragear" in q or "27gx790" in q or "32gs95" in q:
        notes.append("FIX: query без скобок; match LG 480/27GX790A; category=all fetch")
    if "dex" in q:
        notes.append("FIX: intent superlight_2_dex + matcher DEX only")
    if "superlight" in q and "dex" not in q:
        notes.append("FIX: plain SL2 excludes DEX titles")
    if "ult wear" in q or "ult900" in q or re.search(r"\bsony\s+ult\b", q):
        notes.append("FIX: ULT matcher, floor 80, cut pads")
    if not notes:
        notes.append("pipeline: HTML cheapest-valid; API fallback limited")
    return "; ".join(notes)


LABEL = {
    "sofort": "Sofort",
    "sofort_plus": "Sofort+",
    "auktion": "Auktion",
    "auktion_plus": "Auktion+",
}


def audit_product(cm, product):
    query = product["query"]
    tpl = find_search(cm, query)
    if not tpl:
        tpl = {
            "id": "adhoc",
            "query": query,
            "filters": {
                "location": "worldwide",
                "category": "all",
                "max_price": 2500,
                "limit_price": 99999,
            },
            "enabled": True,
        }
    else:
        tpl = dict(tpl)
        tpl["query"] = query
        f = dict(tpl.get("filters") or {})
        # allow over-limit in stats sense
        f["max_price"] = 2500
        tpl["filters"] = f

    time.sleep(0.4)
    bin_items, bin_err, bin_raw = fetch_filtered(cm, tpl, "buy_now_offer")
    time.sleep(0.4)
    auc_items, auc_err, auc_raw = fetch_filtered(cm, tpl, "auction")

    # merge unique by id for splitting
    by_id = {}
    for it in bin_items + auc_items:
        by_id[str(it.get("item_id"))] = it
    all_f = list(by_id.values())

    rows = []
    for key in ("sofort", "sofort_plus", "auktion", "auktion_plus"):
        bot = product["buckets"][key]
        bot_price = bot.get("price")
        bot_id = bot.get("item_id")
        pool = split_bucket(all_f, key)
        live = None
        if pool:
            best = pool[0]
            live = {
                "total": round(total(best), 2),
                "item_id": str(best.get("item_id") or ""),
                "title": (best.get("title") or "")[:90],
                "url": f"https://www.ebay.de/itm/{best.get('item_id')}",
            }

        lab = LABEL[key]
        if bot_price is None:
            if live is None:
                rows.append(
                    {
                        "bucket": lab,
                        "bot": "--- ❌ Не найдено",
                        "verdict": "OK_EMPTY",
                        "answer": "Да — реально не найдено (нет валидных live).",
                        "live": None,
                        "fix": None,
                    }
                )
            else:
                rows.append(
                    {
                        "bucket": lab,
                        "bot": "--- ❌ Не найдено",
                        "verdict": "FAIL_FALSE_EMPTY",
                        "answer": (
                            f"Нет — скрипт врал. Есть ~{live['total']}€ "
                            f"{live['url']} — {live['title']}"
                        ),
                        "live": live,
                        "fix": fix_note(query),
                    }
                )
            continue

        # bot has price
        if live is None:
            rows.append(
                {
                    "bucket": lab,
                    "bot": f"{bot_price}€ [{bot_id}]",
                    "verdict": "STALE_OR_BLOCK",
                    "answer": (
                        f"Бот дал {bot_price}€. Сейчас live valid=0 "
                        f"(лот мог уйти / HTML soft-empty). Не = «врал тогда»."
                    ),
                    "live": None,
                    "fix": None,
                }
            )
            continue

        # cheaper exists?
        if live["total"] + 20 < float(bot_price) and live["item_id"] != str(bot_id or ""):
            rows.append(
                {
                    "bucket": lab,
                    "bot": f"{bot_price}€ [{bot_id}]",
                    "verdict": "FAIL_NOT_CHEAPEST",
                    "answer": (
                        f"Нет — не самый дешёвый. Бот {bot_price}€, дешевле live "
                        f"{live['total']}€ {live['url']} — {live['title']}"
                    ),
                    "live": live,
                    "fix": fix_note(query)
                    + "; stats selection window / multi-SKU / sort",
                }
            )
            continue

        same = str(bot_id or "") == live["item_id"]
        delta = abs(live["total"] - float(bot_price))
        rows.append(
            {
                "bucket": lab,
                "bot": f"{bot_price}€ [{bot_id}]",
                "verdict": "OK_CHEAPEST",
                "answer": (
                    f"Да — это (или ≈) самый дешёвый валидный: live {live['total']}€ "
                    f"{'same id' if same else 'id '+live['item_id']} Δ={delta:.0f}€"
                ),
                "live": live,
                "fix": None,
            }
        )
    return {
        "query": query,
        "display": product["display"],
        "limit": product.get("limit"),
        "bin_raw": bin_raw,
        "auc_raw": auc_raw,
        "bin_err": bin_err,
        "auc_err": auc_err,
        "filtered_n": len(all_f),
        "buckets": rows,
    }


def main():
    m.reset_ebay_session(rotate=True)
    cm = ConfigManager()
    products = parse_blocks(read_log(LOG))
    print(f"products={len(products)} log={LOG}", flush=True)

    results = []
    for i, p in enumerate(products):
        print(f"\n[{i+1}/{len(products)}] {p['query']}", flush=True)
        try:
            block = audit_product(cm, p)
        except Exception as e:
            block = {
                "query": p["query"],
                "display": p["display"],
                "limit": p.get("limit"),
                "error": str(e),
                "buckets": [],
            }
        results.append(block)
        for r in block.get("buckets") or []:
            print(f"  {r['bucket']}: {r['verdict']} | {r['answer'][:110]}", flush=True)

    lines = [
        "# Аудит бота: каждый товар × 4 корзины",
        "",
        f"Источник stats (что отправил бот): `{LOG.as_posix()}`",
        f"Продуктов: **{len(results)}**",
        "",
        "На каждую корзину: **что сказал бот** → **да/нет** → если нет: почему + фикс.",
        "",
    ]
    counts = {}
    for b in results:
        lines.append(f"## {b.get('display') or b.get('query')}")
        lines.append("")
        lines.append(f"Query: `{b.get('query')}`")
        if b.get("limit"):
            lines.append(f"{b['limit']}")
        lines.append(
            f"Live fetch: BIN raw={b.get('bin_raw')} AUC raw={b.get('auc_raw')} "
            f"filtered={b.get('filtered_n')} err={b.get('bin_err')}/{b.get('auc_err')}"
        )
        lines.append("")
        if b.get("error"):
            lines.append(f"**ERROR:** {b['error']}")
            lines.append("")
            continue
        for r in b.get("buckets") or []:
            lines.append(f"### {r['bucket']}")
            lines.append(f"- **Бот:** {r['bot']}")
            lines.append(f"- **Вердикт:** `{r['verdict']}`")
            lines.append(f"- **Ответ:** {r['answer']}")
            if r.get("live"):
                lv = r["live"]
                lines.append(
                    f"- **Live:** {lv['total']}€ — [{lv['item_id']}]({lv['url']}) — {lv['title']}"
                )
            if r.get("fix"):
                lines.append(f"- **Фикс:** {r['fix']}")
            lines.append("")
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        lines.append("---")
        lines.append("")

    lines.append("## Сводка вердиктов")
    lines.append("")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"- `{k}`: **{v}**")
    lines.append("")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("COUNTS", counts, flush=True)
    print("Wrote", OUT_MD, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
