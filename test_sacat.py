import os
import sys

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import monitor

def test_sacat():
    print("=== TEST SACAT ===")
    session = monitor._get_ebay_session()
    monitor._warmup_session(session, "ebay.de")
    headers = {
        "Referer": "https://www.ebay.de/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    # 1. Search WITH _sacat=293 (Headphones/Electronics)
    try:
        url_with_cat = "https://www.ebay.de/sch/i.html?_nkw=Sony+WH-1000XM6&_sacat=293"
        resp = session.get(url_with_cat, timeout=15, headers=headers)
        items = monitor.parse_ebay_results(resp.text or "")
        print(f"Results WITH _sacat=293: {len(items)}")
        for item in items:
            print(f"  - Title: {item.get('title')} | Price: {item.get('price')} | Seller: {item.get('seller_name')}")
    except Exception as e:
        print(f"Error WITH _sacat=293: {e}")
        
    # 2. Search WITHOUT category restriction (all categories)
    try:
        url_no_cat = "https://www.ebay.de/sch/i.html?_nkw=Sony+WH-1000XM6"
        resp = session.get(url_no_cat, timeout=15, headers=headers)
        items = monitor.parse_ebay_results(resp.text or "")
        print(f"Results WITHOUT category restriction: {len(items)}")
        for item in items:
            print(f"  - Title: {item.get('title')} | Price: {item.get('price')} | Seller: {item.get('seller_name')}")
    except Exception as e:
        print(f"Error WITHOUT category restriction: {e}")

if __name__ == "__main__":
    test_sacat()
