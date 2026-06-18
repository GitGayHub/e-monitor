import sys
import json
import os
import time
import requests
import re
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8')

# Ensure we can import monitor
import monitor

def test_live_details():
    session = monitor._get_ebay_session()
    
    # 1. Fetch active auctions directly
    search_url = "https://www.ebay.de/sch/i.html?_nkw=iphone&LH_Auction=1"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.ebay.de/",
    }
    print(f"Fetching search: {search_url}")
    try:
        resp = session.get(search_url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"Error: {e}")
        soup = None
        
    item_ids = []
    if soup:
        links = soup.find_all("a", href=re.compile(r"/itm/\d+"))
        for l in links:
            href = l.get("href", "")
            m = re.search(r"/itm/(\d+)", href)
            if m:
                iid = m.group(1)
                if iid not in item_ids:
                    item_ids.append(iid)
                    
    targets = item_ids[:3]
    print(f"Targets: {targets}")
    
    results = {}
    for item_id in targets:
        url = f"https://www.ebay.de/itm/{item_id}"
        print(f"Fetching item details page: {url}")
        try:
            resp = session.get(url, headers=headers, timeout=15)
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")
            
            # Find all JSON-LD schemas
            ld_jsons = []
            for s in soup.find_all("script", type="application/ld+json"):
                try:
                    ld_jsons.append(json.loads(s.string or ""))
                except:
                    pass
                    
            # Let's search all scripts for keywords like validThrough, endTime, priceValidUntil
            matching_script_lines = []
            for script in soup.find_all("script"):
                content = script.string or ""
                if not content:
                    continue
                for line in content.split("\n"):
                    if any(w in line for w in ("validThrough", "priceValidUntil", "endTime", "endDate", "endDateTime")):
                        matching_script_lines.append(line.strip()[:150])
            
            results[item_id] = {
                "title": soup.find("title").get_text(strip=True) if soup.find("title") else "No Title",
                "ld_json_schemas": ld_jsons,
                "matching_script_lines": matching_script_lines[:15]
            }
        except Exception as e:
            results[item_id] = {"error": str(e)}
        time.sleep(2)
        
    # Save results to json
    output_path = os.path.join(os.path.dirname(__file__), "details_test_output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved test results to {output_path}")

if __name__ == "__main__":
    test_live_details()
