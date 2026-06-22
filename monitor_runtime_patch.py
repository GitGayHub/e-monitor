import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MONITOR = ROOT / 'monitor.py'
CONFIG = ROOT / 'config.json'


def patch_monitor():
    s = MONITOR.read_text(encoding='utf-8')
    orig = s

    # Treat EU searches exactly like worldwide searches.
    s = s.replace('    loc = filters.get("location", "de")\n', '    loc = filters.get("location", "de")\n    if loc == "eu":\n        loc = "worldwide"\n')
    s = s.replace('    loc = (search.get("filters") or {}).get("location", "de")\n    \n    if loc in ("eu", "worldwide"):', '    loc = (search.get("filters") or {}).get("location", "de")\n    if loc == "eu":\n        loc = "worldwide"\n    \n    if loc in ("eu", "worldwide"):')
    s = s.replace('        extra_markets = ["EBAY_GB", "EBAY_ES", "EBAY_FR", "EBAY_IT"]', '        extra_markets = ["EBAY_US", "EBAY_GB", "EBAY_CA", "EBAY_AU", "EBAY_ES", "EBAY_FR", "EBAY_IT"]')
    s = s.replace('    "EBAY_US": "USD",\n    "EBAY_GB": "GBP",\n}', '    "EBAY_US": "USD",\n    "EBAY_GB": "GBP",\n    "EBAY_CA": "CAD",\n    "EBAY_AU": "AUD",\n}')
    s = s.replace('    "EBAY_US": "US",\n    "EBAY_GB": "GB",\n}', '    "EBAY_US": "US",\n    "EBAY_GB": "GB",\n    "EBAY_CA": "CA",\n    "EBAY_AU": "AU",\n}')

    # API/statistics should scan deeper, not only the first small page.
    s = s.replace('        "limit": "100",', '        "limit": "200",')

    # Browse API does not handle the HTML smart query syntax well. Use a clean API query.
    if 'def _build_ebay_api_query(search):' not in s:
        s = s.replace(
            '\ndef _build_ebay_api_params(search, market=None):',
            '''\ndef _build_ebay_api_query(search):
    q = (search.get("query") or "").strip()
    if not q:
        q = _build_smart_search_query(search)
    q = re.sub(r"[()\"']", " ", q)
    q = re.sub(r"\\bredmagic\\b", "red magic", q, flags=re.IGNORECASE)
    q = re.sub(r"\\s+", " ", q).strip()
    return q


def _build_ebay_api_params(search, market=None):'''
        )
    s = s.replace('        "q": _build_smart_search_query(search),', '        "q": _build_ebay_api_query(search),')

    # Fix statistics UI when a slot is empty.
    s = s.replace('v_emoji, v_text = "❌", "Не"', 'v_emoji, v_text = "❌", "Не найдено"')
    s = s.replace('v_text = "Не"', 'v_text = "Не найдено"')
    s = re.sub(r'v_text\s*=\s*["\']Не["\']', 'v_text = "Не найдено"', s)
    s = re.sub(
        r'                    else:\n                        padded_dashes = dashes\.rjust\(max_len\)\n                        v_emoji, v_text = "❌", "Не найдено"\n                        v_text_padded = v_text\.ljust\(10\)\n                        verdict_info = f"\{v_emoji\} \{v_text_padded\}"\n                        row_lines\.append\(f"<code>\{emoji\} \{label\} \{padded_dashes\}  │ \{verdict_info\}</code>"\)',
        '                    else:\n                        row_lines.append(f"{emoji} {label.strip()} ----  │ ❌ Не найдено")',
        s,
    )

    # Statistics mode must be generic: every normal search filter gets a deep sweep.
    s = s.replace('                    for item in items[:5]:', '                    for item in items:')
    s = s.replace('                    for item in items[:30]:', '                    for item in items:')
    s = s.replace('                auc_search["filters"]["location"] = "worldwide"\n', '')
    s = s.replace(
        '                bin_search["filters"]["max_price"] = None\n',
        '                bin_search["filters"]["max_price"] = None\n'
        '                bin_search["filters"]["_ipg"] = 240\n'
    )
    s = s.replace(
        '                auc_search["filters"]["max_price"] = None\n',
        '                auc_search["filters"]["max_price"] = None\n'
        '                auc_search["filters"]["_ipg"] = 240\n'
    )

    stats_fetch_block = '''                # Fetch BIN and Auctions with the same normal user query/filter, but merge several sort modes.
                async def fetch_stats_deep(base_search, label):
                    batches = []
                    first_err = None
                    sort_modes = [("newest", "10"), ("price_asc", "15"), ("price_desc", "12")]

                    query_variants = [copy.deepcopy(base_search)]
                    raw_q = (base_search.get("query") or "").strip()
                    clean_q = re.sub(r"[()\"']", " ", raw_q)
                    clean_q = re.sub(r"\\s+", " ", clean_q).strip()
                    if clean_q and clean_q.lower() != raw_q.lower():
                        qv = copy.deepcopy(base_search)
                        qv["query"] = clean_q
                        query_variants.append(qv)
                    if "redmagic" in raw_q.lower():
                        qv = copy.deepcopy(base_search)
                        qv["query"] = re.sub(r"\\bredmagic\\b", "red magic", raw_q, flags=re.IGNORECASE)
                        query_variants.append(qv)

                    for base_variant in query_variants:
                        for sort_name, sort_code in sort_modes:
                            variant = copy.deepcopy(base_variant)
                            variant.setdefault("filters", {})["sort"] = sort_name
                            variant["filters"]["sort_code"] = sort_code
                            variant["filters"]["_ipg"] = 240
                            one_results, one_err = await asyncio.to_thread(fetch_ebay_ex, variant, force=True)
                            if one_results:
                                batches.append(one_results)
                            if one_err and first_err is None:
                                first_err = one_err
                            if (one_err in ("blocked", "rate_limit", "cooldown") or not one_results) and _ebay_api_configured():
                                logger.info("  %s: using API fallback for %s stats (%s)", variant["query"], label, sort_name)
                                api_results, api_err = await asyncio.to_thread(fetch_ebay_api_ex, variant, force=True)
                                if not api_err and api_results:
                                    batches.append(api_results)
                                    first_err = None
                    return _merge_items_by_id(*batches), first_err

                bin_results, bin_err = await fetch_stats_deep(bin_search, "BIN")
                auc_results, auc_err = await fetch_stats_deep(auc_search, "Auction")
                results = _merge_items_by_id(bin_results, auc_results)'''
    s = re.sub(
        r'                # Fetch BIN\n.*?                results = _merge_items_by_id\(bin_results, auc_results\)',
        stats_fetch_block,
        s,
        count=1,
        flags=re.S,
    )

    s = s.replace(
        '                auc_bo = [item for item in filtered if item.get("auction") and item.get("best_offer")]',
        '                auc_bo = [item for item in filtered if item.get("auction") and item.get("best_offer") and item.get("bids_count") in (0, None)]'
    )

    # Unknown auction time must not be interpreted as 0 minutes left.
    parser = '''def _parse_time_left_to_minutes(time_left_str):
    t = (time_left_str or "").lower().strip()
    if not t:
        return None
    days = hours = minutes = 0
    matched = False
    m_days = re.search(r"(\d+)\s*(?:tag|t\b|d\b|day)", t)
    if m_days:
        days = int(m_days.group(1)); matched = True
    m_hours = re.search(r"(\d+)\s*(?:std|h\b|hour)", t)
    if m_hours:
        hours = int(m_hours.group(1)); matched = True
    m_minutes = re.search(r"(\d+)\s*(?:min|m\b|minute)", t)
    if m_minutes:
        minutes = int(m_minutes.group(1)); matched = True
    if not matched:
        if re.search(r"\b\d+\s*(?:sek|sec|second|seconds|s)\b", t):
            return 1
        return None
    return days * 1440 + hours * 60 + minutes


def _passes_notification_price_and_auction_rules(item, search):
    filters = search.get("filters", {}) or {}
    limit_or_max = filters.get("limit_price") or filters.get("max_price")
    if limit_or_max is not None and item.get("total_price", 0) > limit_or_max:
        return False
    if item.get("auction") and not item.get("buy_now"):
        is_new_best_offer = bool(item.get("best_offer")) and item.get("bids_count") == 0
        minutes = _parse_time_left_to_minutes(item.get("time_left", ""))
        is_ending_soon = minutes is not None and minutes <= 1440
        return is_new_best_offer or is_ending_soon
    return True


def _format_time_left_from_seconds'''
    s = re.sub(r'def _parse_time_left_to_minutes\(time_left_str\):\n.*?\n\ndef _format_time_left_from_seconds', parser, s, count=1, flags=re.S)
    s = s.replace('        if minutes > 0:\n            return _format_time_left_from_seconds(minutes * 60)', '        if minutes is not None and minutes > 0:\n            return _format_time_left_from_seconds(minutes * 60)')

    old = '''                if details:
                    _calculate_total(item, config.get_settings(), details)
                    h = _item_hash(item["seller_name"], item["title"], item["price"])

                sent = await send_notification(bot, item, search, stats_7d)'''
    new = '''                if details:
                    _calculate_total(item, config.get_settings(), details)
                    h = _item_hash(item["seller_name"], item["title"], item["price"])

                if not _passes_notification_price_and_auction_rules(item, search):
                    logger.info("Skipping notification for item %s: price/auction rules failed after details refresh", item["item_id"])
                    seen_ids.add(item["item_id"])
                    continue

                sent = await send_notification(bot, item, search, stats_7d)'''
    s = s.replace(old, new)

    if s != orig:
        MONITOR.write_text(s, encoding='utf-8')
        print('monitor.py patched')
    else:
        print('monitor.py already patched')


def migrate_config():
    if not CONFIG.exists():
        print('config.json not present yet')
        return
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    changed = 0
    searches = data.setdefault('searches', [])

    before_len = len(searches)
    searches[:] = [s for s in searches if s.get('id') != 'redmagic_11_pro_golden_auc_stats']
    if len(searches) != before_len:
        changed += 1

    for search in searches:
        filters = search.setdefault('filters', {})
        if filters.get('location') == 'eu':
            filters['location'] = 'worldwide'
            changed += 1

    if changed:
        CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'config migrated generically for worldwide stats: {changed}')


if __name__ == '__main__':
    patch_monitor()
    migrate_config()
