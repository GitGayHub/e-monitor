import os
import sys

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import monitor

def check_seller():
    print("=== CHECK SELLER ===")
    session = monitor._get_ebay_session()
    monitor._warmup_session(session, "ebay.de")
    headers = {
        "Referer": "https://www.ebay.de/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    # 1. Active items
    try:
        url = "https://www.ebay.de/sch/i.html?_ssn=plako_plak"
        resp = session.get(url, timeout=15, headers=headers)
        body = resp.text or ""
        items = monitor.parse_ebay_results(body)
        print(f"Active items for plako_plak: {len(items)}")
        for item in items:
            print(f"  - [Active] Title: {item.get('title')} | Price: {item.get('price')}")
    except Exception as e:
        print(f"Error fetching active: {e}")
        
    # 2. Completed / Sold items
    try:
        url_completed = "https://www.ebay.de/sch/i.html?_ssn=plako_plak&LH_Complete=1"
        resp = session.get(url_completed, timeout=15, headers=headers)
        body = resp.text or ""
        items = monitor.parse_ebay_results(body)
        print(f"Completed/Sold items for plako_plak: {len(items)}")
        for item in items:
            print(f"  - [Completed] Title: {item.get('title')} | Price: {item.get('price')}")
    except Exception as e:
        print(f"Error fetching completed: {e}")

if __name__ == "__main__":
    check_seller()
