import os
import sys
import copy
import asyncio

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

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
        
    print(f"Loaded search: {search}")
    
    # 2. Fetch standard items using the actual eBay scraping function
    items, err = monitor.fetch_ebay_ex(search, force=True)
    print(f"Fetched standard items count: {len(items)} (Error: {err})")
    if not items:
        print("No items found to test filters on.")
        return
        
    # 3. Simulate filter_results
    print("\n--- Running filter_results ---")
    filtered = monitor.filter_results(items, search, config)
    print(f"Filtered items count: {len(filtered)}")
    
    # Show difference
    filtered_ids = {it["item_id"] for it in filtered}
    for it in items:
        if it["item_id"] not in filtered_ids:
            print(f"  - Item '{it['title']}' (ID: {it['item_id']}, Price: {it['price']}) was REMOVED by filter_results")
            # Let's see why by running checks inside filter_results manually on it
            # We can check:
            # - _is_category_blocked_title
            # - seller banned
            # - price limits
            title_norm = monitor._normalize(it["title"])
            category = search.get("filters", {}).get("category", "all")
            query_norm = monitor._normalize(monitor._intent_query(search))
            
            is_cat_blocked = monitor._is_category_blocked_title(title_norm, category, query_norm)
            is_seller_banned = monitor._normalize(it["seller_name"]) in {monitor._normalize(s) for s in config.get_global_banned_sellers()}
            price_limit_failed = False
            min_p = search.get("filters", {}).get("min_price")
            max_p = search.get("filters", {}).get("limit_price") or search.get("filters", {}).get("max_price")
            if min_p and it["total_price"] < min_p:
                price_limit_failed = True
            if max_p and it["total_price"] > max_p:
                price_limit_failed = True
                
            print(f"    * Category blocked: {is_cat_blocked}")
            print(f"    * Seller banned: {is_seller_banned}")
            print(f"    * Price limit failed: {price_limit_failed} (Price: {it['total_price']}, limits: {min_p} - {max_p})")

    # 4. Simulate process_searches item checks
    print("\n--- Running process_searches item checks ---")
    for item in filtered:
        print(f"\nItem: '{item['title']}' (ID: {item['item_id']}, Price: {item['price']})")
        
        # Details check
        print("  - Fetching details...")
        details = await asyncio.to_thread(monitor._fetch_item_details, item["item_id"])
        if not details:
            print("    * Failed to fetch details!")
            continue
            
        # Allowed subcategories
        cat_id = details.get("categoryId")
        search_cat = search.get("filters", {}).get("category", "all")
        cat_allowed = True
        if search_cat in monitor.ALLOWED_SUBCATEGORIES:
            allowed_set = monitor.ALLOWED_SUBCATEGORIES[search_cat]
            if cat_id and cat_id not in allowed_set:
                cat_path_ids = details.get("categoryIdPath", "").split("|")
                if not any(cid in allowed_set for cid in cat_path_ids):
                    cat_allowed = False
        print(f"    * Category allowed: {cat_allowed} (Cat ID: {cat_id})")
        
        # itemGroupType
        group_type_ok = details.get("itemGroupType") != "SELLER_DEFINED_VARIATIONS"
        print(f"    * Group Type OK: {group_type_ok} ({details.get('itemGroupType')})")
        
        # _details_price_mismatch
        mismatch, scraped_p, api_p = monitor._details_price_mismatch(item, details)
        print(f"    * Price mismatch: {mismatch} (scraped: {scraped_p}, api: {api_p})")
        
        # _is_details_blocked
        details_blocked = monitor._is_details_blocked(details, search)
        print(f"    * Details blocked: {details_blocked}")
        
        # _is_description_blocked
        desc = details.get("description", "")
        desc_blocked = monitor._is_description_blocked(desc, search_cat) if desc else False
        print(f"    * Description blocked: {desc_blocked}")
        
        # _intent_details_match
        intent_match = monitor._intent_details_match(search, item, details)
        print(f"    * Intent match: {intent_match}")
        
        # _passes_notification_price_and_auction_rules
        passes_rules = monitor._passes_notification_price_and_auction_rules(item, search)
        print(f"    * Passes notification rules: {passes_rules}")

def test_filters():
    asyncio.run(test_filters_async())

if __name__ == "__main__":
    test_filters()
