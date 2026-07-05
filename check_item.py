import os
import sys
import re
from bs4 import BeautifulSoup

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import monitor

def check_item():
    print("=== CHECK ITEM ===")
    session = monitor._get_ebay_session()
    monitor._warmup_session(session, "ebay.de")
    headers = {
        "Referer": "https://www.ebay.de/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    url = "https://www.ebay.de/itm/127957438007"
    try:
        resp = session.get(url, timeout=15, headers=headers)
        print(f"Status Code: {resp.status_code}")
        body = resp.text or ""
        
        soup = BeautifulSoup(body, "html.parser")
        
        # Look for category breadcrumbs
        breadcrumbs = soup.select("nav.breadcrumbs ul li a")
        print("Breadcrumbs found:")
        for bc in breadcrumbs:
            print(f"  - {bc.get_text(strip=True)} ({bc.get('href')})")
            
        # Try to find category ID (often in meta tags or script tag window._spConfig)
        cat_id_match = re.search(r'"categoryId"\s*:\s*"?(\d+)"?', body)
        if cat_id_match:
            print(f"Category ID from JSON: {cat_id_match.group(1)}")
        else:
            cat_id_match2 = re.search(r'/_sacat=(\d+)', body)
            if cat_id_match2:
                print(f"Category ID from URL: {cat_id_match2.group(1)}")
                
    except Exception as e:
        print(f"Error fetching item: {e}")

if __name__ == "__main__":
    check_item()
