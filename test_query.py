import os
import sys

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import monitor

def test_query():
    print("=== TEST QUERY ===")
    
    # Define the search config for Sony WH-1000XM6 auction
    search = {
        "id": "sony_wh_1000xm6_auc",
        "query": "Sony WH-1000XM6",
        "filters": {
            "min_price": None,
            "limit_price": 200,
            "max_price": 2500,
            "condition": "any",
            "listing_type": "auction",
            "seller_type": "any",
            "location": "worldwide",
            "category": "headphones"
        }
    }
    
    # 1. Fetch with standard fetch_ebay_ex (which uses negative keywords)
    items, err = monitor.fetch_ebay_ex(search)
    print(f"fetch_ebay_ex standard count: {len(items)} (Error: {err})")
    for it in items[:5]:
        print(f"  - Title: {it.get('title')} | Seller: {it.get('seller_name')}")
        
    # 2. Fetch with raw query (no negative keywords) by temporarily mocking _build_smart_search_query
    old_smart = monitor._build_smart_search_query
    monitor._build_smart_search_query = lambda s: s.get("query")
    
    items_raw, err_raw = monitor.fetch_ebay_ex(search)
    print(f"fetch_ebay_ex raw (no negative keywords) count: {len(items_raw)} (Error: {err_raw})")
    for it in items_raw[:5]:
        print(f"  - Title: {it.get('title')} | Seller: {it.get('seller_name')}")
        
    # Restore mock
    monitor._build_smart_search_query = old_smart

if __name__ == "__main__":
    test_query()
