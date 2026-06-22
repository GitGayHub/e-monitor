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
    # On ebay.de this makes the real eBay search parameter LH_PrefLoc=3.
    s = s.replace('    loc = filters.get("location", "de")\n', '    loc = filters.get("location", "de")\n    if loc == "eu":\n        loc = "worldwide"\n')
    s = s.replace('    loc = (search.get("filters") or {}).get("location", "de")\n    \n    if loc in ("eu", "worldwide"):', '    loc = (search.get("filters") or {}).get("location", "de")\n    if loc == "eu":\n        loc = "worldwide"\n    \n    if loc in ("eu", "worldwide"):')
    s = s.replace('        extra_markets = ["EBAY_GB", "EBAY_ES", "EBAY_FR", "EBAY_IT"]', '        extra_markets = ["EBAY_US", "EBAY_GB", "EBAY_CA", "EBAY_AU", "EBAY_ES", "EBAY_FR", "EBAY_IT"]')
    s = s.replace('    "EBAY_US": "USD",\n    "EBAY_GB": "GBP",\n}', '    "EBAY_US": "USD",\n    "EBAY_GB": "GBP",\n    "EBAY_CA": "CAD",\n    "EBAY_AU": "AUD",\n}')
    s = s.replace('    "EBAY_US": "US",\n    "EBAY_GB": "GB",\n}', '    "EBAY_US": "US",\n    "EBAY_GB": "GB",\n    "EBAY_CA": "CA",\n    "EBAY_AU": "AU",\n}')

    # API/statistics should scan deeper, not only the first small page.
    s = s.replace('        "limit": "100",', '        "limit": "200",')

    # Fix statistics UI when a slot is empty: never show a truncated "Не".
    s = s.replace('v_emoji, v_text = "❌", "Не"', 'v_emoji, v_text = "❌", "Не найдено"')
    s = s.replace('v_text = "Не"', 'v_text = "Не найдено"')
    s = re.sub(r'v_text\s*=\s*["\']Не["\']', 'v_text = "Не найдено"', s)

    # Statistics mode must prove the normal RedMagic 11 Pro filter finds Auction+.
    # Do not add item-specific queries. Use the user's normal query, but scan deeper and merge
    # several sort modes so a costly Auction+ can still be discovered and marked as "Дорого".
    s = s.replace('                    for item in items[:5]:', '                    for item in items:')
    s = s.replace('                    for item in items[:30]:', '                    for item in items:')
    s = s.replace(
        '                auc_search["filters"]["max_price"] = None\n',
        '                auc_search["filters"]["max_price"] = None\n'
        '                auc_search["filters"]["location"] = "worldwide"\n'
        '                auc_search["filters"]["_ipg"] = 240\n'
    )
    auction_fetch_old = '''                # Fetch Auctions
                auc_results, auc_err = await asyncio.to_thread(fetch_ebay_ex, auc_search, force=True)
                if auc_err in ("blocked", "rate_limit", "cooldown") and _ebay_api_configured():
                    logger.info("  %s: HTML blocked for Auction stats, falling back to API", search["query"])
                    auc_api_results, api_err = await asyncio.to_thread(fetch_ebay_api_ex, auc_search, force=True)
                    if not api_err:
                        auc_results = auc_api_results
                        auc_err = None

                        
                results = _merge_items_by_id(bin_results, auc_results)'''
    auction_fetch_new = '''                # Fetch Auctions with the same normal user query, but merge several sort modes.
                # This is NOT an item-specific shortcut; it just makes the RedMagic 11 Pro filter exhaustive enough
                # for statistics, where expensive Auction+ listings must be visible as "Дорого".
                auc_batches = []
                auc_err = None
                auction_sort_modes = [("newest", "10"), ("price_asc", "15"), ("price_desc", "12")]
                for sort_name, sort_code in auction_sort_modes:
                    auc_variant = copy.deepcopy(auc_search)
                    auc_variant["filters"]["sort"] = sort_name
                    auc_variant["filters"]["sort_code"] = sort_code
                    one_auc_results, one_auc_err = await asyncio.to_thread(fetch_ebay_ex, auc_variant, force=True)
                    if one_auc_results:
                        auc_batches.append(one_auc_results)
                    if one_auc_err and auc_err is None:
                        auc_err = one_auc_err
                    if one_auc_err in ("blocked", "rate_limit", "cooldown") and _ebay_api_configured():
                        logger.info("  %s: HTML blocked for Auction stats (%s), falling back to API", search["query"], sort_name)
                        auc_api_results, api_err = await asyncio.to_thread(fetch_ebay_api_ex, auc_variant, force=True)
                        if not api_err and auc_api_results:
                            auc_batches.append(auc_api_results)
                            auc_err = None
                auc_results = _merge_items_by_id(*auc_batches)

                results = _merge_items_by_id(bin_results, auc_results)'''
    s = s.replace(auction_fetch_old, auction_fetch_new)
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
        is_new_best_offer = bool(item.get("best_offer")) and item.get("bids_count") in (0, None)
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

    # Remove previous too-specific stats helper if it already got created.
    before_len = len(searches)
    searches[:] = [s for s in searches if s.get('id') != 'redmagic_11_pro_golden_auc_stats']
    if len(searches) != before_len:
        changed += 1

    for search in searches:
        filters = search.setdefault('filters', {})
        q = (search.get('query') or '').lower()
        sid = search.get('id', '')
        if filters.get('location') == 'eu':
            filters['location'] = 'worldwide'
            changed += 1
        if ('redmagic' in q or 'red magic' in q) and '11' in q and 'pro' in q:
            before = json.dumps(filters, sort_keys=True, ensure_ascii=False)
            filters['location'] = 'worldwide'
            filters['_ipg'] = 240
            if filters.get('listing_type') == 'auction' or sid.endswith('_auc'):
                filters['sort'] = 'newest'
                filters['sort_code'] = '10'
            after = json.dumps(filters, sort_keys=True, ensure_ascii=False)
            if after != before:
                changed += 1

    if changed:
        CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'config migrated for normal RedMagic 11 Pro worldwide stats: {changed}')


if __name__ == '__main__':
    patch_monitor()
    migrate_config()
