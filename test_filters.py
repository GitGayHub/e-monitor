import os
import sys
import asyncio

# Add current dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import monitor


async def test_filters_async():
    print("=== TEST FILTERS ===")

    # 1. Load config and find the search config
    config = monitor.ConfigManager()
    searches = config.get_searches()
    search = None
    for s in searches:
        if s.get("id") == "sony_wh_1000xm6_auc":
            search = s
            break

    if not search:
        print("Search sony_wh_1000xm6_auc not found in config!")
        return

    print(f"Search: {search['query']}")
    print(f"Filters: {search['filters']}")

    # 2. Clear cache so we get fresh results
    monitor._ebay_query_cache.clear()

    # 3. Fetch items
    items, err = monitor.fetch_ebay_ex(search, force=True)
    print(f"\nFetched items: {len(items)} (Error: {err})")

    if not items:
        print("No items found to test filters on.")
        return

    # 4. Show all fetched items with prices and auction status
    print("\n--- All fetched items ---")
    settings = config.get_settings()
    for it in items:
        monitor._calculate_total(it, settings)
        print(f"  [{it.get('item_id')}] auction={it.get('auction')} buy_now={it.get('buy_now')} "
              f"price={it.get('price')} total={it.get('total_price')} "
              f"time_left={it.get('time_left', '-')} title={it.get('title', '')[:60]}")

    # 5. Simulate filter_results step by step
    print("\n--- Filter reasons ---")
    limit_or_max = search['filters'].get('limit_price') or search['filters'].get('max_price')
    listing_type = search['filters'].get('listing_type', 'all')
    for it in items:
        monitor._calculate_total(it, settings)
        reasons = []

        # Price check
        if limit_or_max is not None and it.get('total_price', 0) > limit_or_max:
            reasons.append(f"PRICE_OVER_LIMIT ({it['total_price']} > {limit_or_max})")

        # listing_type check
        if listing_type == "auction" and not it.get("auction"):
            reasons.append("NOT_AUCTION")

        # Ending soon check (auction items only)
        if it.get("auction") and not it.get("buy_now"):
            time_left_str = it.get("time_left", "")
            if time_left_str:
                minutes = monitor._parse_time_left_to_minutes(time_left_str)
                if minutes is None or minutes > 1440:
                    reasons.append(f"NOT_ENDING_SOON (time_left={time_left_str}, minutes={minutes})")
            else:
                reasons.append("NO_TIME_LEFT (would be filtered out)")

        # Title match
        title_norm = monitor._normalize(it.get("title", ""))
        query_text = monitor._intent_query(search)
        query_norm = monitor._normalize(query_text)
        category = search['filters'].get('category', 'all')
        effective_category = monitor._effective_category(category, query_norm)
        if not monitor._matches_category_query(title_norm, effective_category, query_norm):
            reasons.append("TITLE_MISMATCH")
        if monitor._is_category_blocked_title(title_norm, effective_category, query_norm):
            reasons.append("CATEGORY_BLOCKED_TITLE")

        status = "PASS" if not reasons else "BLOCKED: " + ", ".join(reasons)
        print(f"  [{it.get('item_id')}] {status} | total={it.get('total_price')} | {it.get('title', '')[:50]}")

    # 6. Run full filter
    filtered = monitor.filter_results(items, search, config)
    print(f"\nFull filter_results: {len(filtered)} pass out of {len(items)}")


async def test_filters():
    await test_filters_async()


if __name__ == "__main__":
    asyncio.run(test_filters_async())
