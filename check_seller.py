import os
import sys

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import monitor

def check_seller():
    print("=== CHECK SELLER ===")
    session = monitor._get_ebay_session()
    # Warm up session
    monitor._warmup_session(session, "ebay.de")
    
    url = "https://www.ebay.de/sch/i.html?_ssn=plako_plak"
    headers = {
        "Referer": "https://www.ebay.de/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    try:
        resp = session.get(url, timeout=15, headers=headers)
        print(f"Status Code: {resp.status_code}")
        body = resp.text or ""
        
        # Check challenge
        low = body[:8000].lower()
        if "pardon our interruption" in low or "/splashui/" in getattr(resp, "url", "").lower():
            print("Blocked by challenge page!")
            return
            
        items = monitor.parse_ebay_results(body)
        print(f"Parsed {len(items)} items from seller:")
        for item in items:
            print(f"  - Title: {item.get('title')} | Price: {item.get('price')} | Item ID: {item.get('item_id')}")
            
    except Exception as e:
        print(f"Error fetching: {e}")

if __name__ == "__main__":
    check_seller()
