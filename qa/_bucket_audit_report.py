#!/usr/bin/env python3
"""Per-product × 4-bucket audit of a stats log vs live HTML cheapest valid.

Output format (markdown) for each product:
  Sofort / Sofort+ / Auktion / Auktion+:
    bot said X€ or ---
    verdict: OK cheapest | OK empty | FAIL cheaper exists | FAIL false empty
    details + fix note
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
        m = re.search(r"\r?\n\d{4}-\d{2}-\d{2} ", body)
        if m:
            body = body[: m.start()]
        # limit line
        limit = None
        lm = re.search(r"Лимит:[^\n]+", body)
        if lm:
            limit = re.sub(r"<[^>]+>", "", lm.group(0)).strip()
        buckets = {}
        # order matters: longer labels first
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
        # display name from body header
        dm = re.search(r"<b>([^<]+)</b>", body)
        display = re.sub(r"[🌍🇩🇪🇪🇺⚙️♾️📦📱🎮🎧🖥️🖱️]+", "", dm.group(1)).strip() if dm else name
        out.append({"query": name, "display": display, "limit": limit, "buckets": buckets, "raw": body[:500]})
        i += 2
    return out


def find_config_search(cm: ConfigManager, query: str):
    qn = m._normalize(query)
    best = None
    for s in cm.get_searches():
        if s.get("filters", {}).get("listing_type") != "buy_now_offer":
            # prefer buy row as base template
            pass
        sq = m._normalize(s.get("query") or "")
        if sq == qn or qn in sq or sq in qn:
            if s.get("filters", {}).get("listing_type") == "buy_now_offer":
                return s
            best = best or s
    # intent-based
    for s in cm.get_searches():
        if m._search_intent(s) and m._search_intent({"query": query}):
            if m._search_intent(s).get("kind") == m._search_intent({"query": query}).get("kind"):
                if s.get("filters", {}).get("listing_type") == "buy_now_offer":
                    return s
    return best


def total(it):
    try:
        return float(it.get("total_price") or it.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0


def live_cheapest(search_template: dict, listing: str, best_offer: bool):
    """listing: buy_now_offer | auction"""
    base = search_template or {
        "id": "audit",
        "query": "",
        "filters": {"location": "worldwide", "category": "all", "max_price": 2500},
        "enabled": True,
        "notify": True,
    }
    s = m._statistics_search_variant(base, listing, base.get("filters", {}).get("min_price"), best_offer)
    items, err = m.fetch_ebay_ex(s, force=True)
    filt = m.filter_results(
        items or [],
        # keep bucket filter flags for listing type
        s,
        ConfigManager(),
        skip_seen=True,
        is_statistics=True,
    )
    # If _stats_bucket_filter empty due to BO split, also try stats filter without bucket
    if not filt and items:
        fs = m._statistics_filter_search(base)
        fs["filters"]["listing_type"] = listing
        if best_offer:
            fs["filters"]["best_offer"] = True
        filt = m.filter_results(items or [], fs, ConfigManager(), skip_seen=True, is_statistics=True)
        # manual BO filter
        if best_offer:
            filt = [x for x in filt if x.get("best_offer")]
        else:
            if listing == "buy_now_offer":
                filt = [x for x in filt if x.get("buy_now") and not x.get("best_offer")]
            elif listing == "auction":
                filt = [x for x in filt if x.get("auction") and not x.get("best_offer")]

    ranked = sorted(filt or [], key=total)
    if not ranked:
        return None, err, len(items or []), 0
    best = ranked[0]
    return (
        {
            "total": round(total(best), 2),
            "item_id": str(best.get("item_id") or ""),
            "title": (best.get("title") or "")[:90],
            "url": f"https://www.ebay.de/itm/{best.get('item_id')}",
        },
        err,
        len(items or []),
        len(ranked),
    )


FIX_NOTES = {
    "odyssey": "query (G60SF,...) zeroed HTML; samsung≠phone; matchers LS27FG604; fetch category=all",
    "ultragear": "query parentheses + model-only match → empty; broadened LG 480 match + clean query",
    "dex": "no DEX intent; challenge/empty; superlight_2_dex matcher + variants",
    "superlight": "DEX mixed into plain SL2; split intents",
    "ult": "parts flood on price_asc; ULT matcher + floor 80 + variants",
    "phone_samsung": "samsung alone no longer phone floor for monitors",
    "api_fallback": "EBAY_SOURCE=html no Browse API spam; 429 multi-market circuit-breaker",
}


def fix_note_for(query: str) -> str:
    q = m._normalize(query)
    notes = []
    if "odyssey" in q or "g60sf" in q:
        notes.append(FIX_NOTES["odyssey"])
    if "ultragear" in q or "27gx790" in q or "32gs95" in q:
        notes.append(FIX_NOTES["ultragear"])
    if "dex" in q:
        notes.append(FIX_NOTES["dex"])
    if "superlight" in q and "dex" not in q:
        notes.append(FIX_NOTES["superlight"])
    if "ult" in q and "ultra" not in q.replace("ult wear", "X"):
        notes.append(FIX_NOTES["ult"])
    if "ult wear" in q or "ult900" in q:
        notes.append(FIX_NOTES["ult"])
    if not notes:
        notes.append("общий HTML pipeline / cheapest-valid selection; API fallback не долбит")
    return "; ".join(notes)


def audit_bucket(product, key, search_tpl):
    bot = product["buckets"][key]
    bot_price = bot.get("price")
    bot_id = bot.get("item_id")
    listing = "auction" if "auktion" in key else "buy_now_offer"
    bo = key.endswith("_plus") or key in ("sofort_plus", "auktion_plus")
    # map: sofort_plus / auktion_plus => best_offer True; sofort/auktion => False
    bo = key in ("sofort_plus", "auktion_plus")

    # ensure template query
    tpl = dict(search_tpl) if search_tpl else {"id": "a", "query": product["query"], "filters": {}}
    if not tpl.get("query"):
        tpl["query"] = product["query"]
    tpl.setdefault("filters", {})

    time.sleep(0.5)
    live, err, n_raw, n_filt = live_cheapest(tpl, listing, bo)

    label = {
        "sofort": "Sofort",
        "sofort_plus": "Sofort+",
        "auktion": "Auktion",
        "auktion_plus": "Auktion+",
    }[key]

    if bot_price is None:
        # bot said empty
        if live is None:
            return {
                "bucket": label,
                "bot": "--- Не найдено",
                "verdict": "OK_EMPTY",
                "msg": "Да — реально не найдено (live filter 0 valid).",
                "live": None,
                "fix": None,
                "raw_n": n_raw,
                "filt_n": n_filt,
                "err": err,
            }
        return {
            "bucket": label,
            "bot": "--- Не найдено",
            "verdict": "FAIL_FALSE_EMPTY",
            "msg": (
                f"Нет — скрипт врал. Есть валид ~{live['total']}€ "
                f"[{live['item_id']}] {live['title']}"
            ),
            "live": live,
            "fix": fix_note_for(product["query"]),
            "raw_n": n_raw,
            "filt_n": n_filt,
            "err": err,
        }

    # bot has price
    if live is None:
        return {
            "bucket": label,
            "bot": f"{bot_price}€ id={bot_id}",
            "verdict": "STALE_OR_MOVED",
            "msg": (
                f"Бот: {bot_price}€. Live сейчас 0 valid (лот ушёл / soft-block / рынок). "
                f"Не доказывает что тогда врал."
            ),
            "live": None,
            "fix": None,
            "raw_n": n_raw,
            "filt_n": n_filt,
            "err": err,
        }

    # compare
    # allow 15€ slack for shipping drift
    if live["total"] + 15 < float(bot_price) and live["item_id"] != str(bot_id or ""):
        return {
            "bucket": label,
            "bot": f"{bot_price}€ id={bot_id}",
            "verdict": "FAIL_NOT_CHEAPEST",
            "msg": (
                f"Нет — не самый дешёвый. Бот {bot_price}€, live cheaper "
                f"{live['total']}€ [{live['item_id']}] {live['title']}"
            ),
            "live": live,
            "fix": fix_note_for(product["query"]) + "; stats cheapest selection / window",
            "raw_n": n_raw,
            "filt_n": n_filt,
            "err": err,
        }

    same = str(bot_id or "") == live["item_id"]
    delta = abs(live["total"] - float(bot_price))
    if same:
        id_note = ", same id"
    else:
        id_note = f", live id {live['item_id']}"
    return {
        "bucket": label,
        "bot": f"{bot_price}€ id={bot_id}",
        "verdict": "OK_CHEAPEST",
        "msg": (
            f"Да — реально среди валидных (~{live['total']}€{id_note} Δ={delta:.0f}€)."
        ),
        "live": live,
        "fix": None,
        "raw_n": n_raw,
        "filt_n": n_filt,
        "err": err,
    }


def main():
    m.reset_ebay_session(rotate=True)
    cm = ConfigManager()
    text = read_log(LOG)
    products = parse_blocks(text)
    print(f"Parsed {len(products)} products from {LOG}", flush=True)

    results = []
    for i, p in enumerate(products):
        print(f"\n[{i+1}/{len(products)}] {p['query']}", flush=True)
        tpl = find_config_search(cm, p["query"])
        if tpl:
            # use product query for intent
            tpl = dict(tpl)
            tpl["query"] = p["query"]
        else:
            tpl = {
                "id": "adhoc",
                "query": p["query"],
                "filters": {"location": "worldwide", "category": "all", "max_price": 2500},
                "enabled": True,
            }
        bucket_results = []
        for key in ("sofort", "sofort_plus", "auktion", "auktion_plus"):
            try:
                r = audit_bucket(p, key, tpl)
            except Exception as e:
                r = {
                    "bucket": key,
                    "bot": p["buckets"][key],
                    "verdict": "ERROR",
                    "msg": str(e),
                    "live": None,
                    "fix": None,
                }
            bucket_results.append(r)
            print(f"  {r['bucket']}: {r['verdict']} — {r['msg'][:100]}", flush=True)
        results.append({"product": p, "buckets": bucket_results})

    # markdown
    lines = [
        "# Полный bucket-аудит (бот stats vs live HTML)",
        "",
        f"Лог бота: `{LOG.as_posix()}`",
        f"Продуктов: **{len(results)}** × 4 корзины",
        "",
        "Легенда: **OK_CHEAPEST** / **OK_EMPTY** / **FAIL_NOT_CHEAPEST** / **FAIL_FALSE_EMPTY** / **STALE_OR_MOVED**",
        "",
    ]
    counts = {}
    for block in results:
        p = block["product"]
        lines.append(f"## {p['display'] or p['query']}")
        lines.append("")
        if p.get("limit"):
            lines.append(f"Лимит: {p['limit']}")
            lines.append("")
        for r in block["buckets"]:
            lines.append(f"### {r['bucket']}")
            lines.append(f"- **Бот:** {r.get('bot')}")
            lines.append(f"- **Вердикт:** `{r.get('verdict')}`")
            lines.append(f"- **Ответ:** {r.get('msg')}")
            if r.get("live"):
                lv = r["live"]
                lines.append(
                    f"- **Live cheapest valid:** {lv['total']}€ — [{lv['item_id']}]({lv['url']}) — {lv['title']}"
                )
            if r.get("fix"):
                lines.append(f"- **Фикс / почему:** {r['fix']}")
            lines.append(f"- raw/filt: {r.get('raw_n')}/{r.get('filt_n')} err={r.get('err')}")
            lines.append("")
            counts[r.get("verdict")] = counts.get(r.get("verdict"), 0) + 1
        lines.append("---")
        lines.append("")

    lines.append("## Итог по вердиктам")
    lines.append("")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"- `{k}`: **{v}**")
    lines.append("")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nCOUNTS", counts)
    print("Wrote", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
