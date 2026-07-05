import os
import sys

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import monitor

def test_params():
    print("=== TEST PARAMS ===")
    session = monitor._get_ebay_session()
    monitor._warmup_session(session, "ebay.de")
    headers = {
        "Referer": "https://www.ebay.de/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    base_nkw = "Sony WH-1000XM6"
    neg_nkw = "Sony WH-1000XM6 -defekt -teildefekt -ersatzteil -reparatur -broken -cracked -damage -damaged -defect -defective -repair -spares -parts -wasserschaden"
    
    tests = [
        ("Base", "https://www.ebay.de/sch/i.html?_nkw=Sony+WH-1000XM6&_sacat=293"),
        ("With Negatives", f"https://www.ebay.de/sch/i.html?_nkw={monitor.requests.utils.quote(neg_nkw)}&_sacat=293"),
        ("With Condition", f"https://www.ebay.de/sch/i.html?_nkw=Sony+WH-1000XM6&_sacat=293&LH_ItemCondition=1500%7C1000%7C2010%7C2020%7C2030%7C3000"),
        ("With Location (Worldwide)", "https://www.ebay.de/sch/i.html?_nkw=Sony+WH-1000XM6&_sacat=293&LH_PrefLoc=3"),
        ("With Location (DE)", "https://www.ebay.de/sch/i.html?_nkw=Sony+WH-1000XM6&_sacat=293&LH_PrefLoc=1"),
        ("With Auction", "https://www.ebay.de/sch/i.html?_nkw=Sony+WH-1000XM6&_sacat=293&LH_Auction=1"),
        ("With BIN", "https://www.ebay.de/sch/i.html?_nkw=Sony+WH-1000XM6&_sacat=293&LH_BIN=1"),
        ("Full Auction (negatives + cond + loc + auc)", f"https://www.ebay.de/sch/i.html?_nkw={monitor.requests.utils.quote(neg_nkw)}&_sacat=293&LH_ItemCondition=1500%7C1000%7C2010%7C2020%7C2030%7C3000&LH_PrefLoc=3&LH_Auction=1")
    ]
    
    for label, url in tests:
        try:
            resp = session.get(url, timeout=15, headers=headers)
            items = monitor.parse_ebay_results(resp.text or "")
            print(f"Test '{label}': parsed {len(items)} items")
            if items:
                # Find if plako_plak is in the results
                plako = [it for it in items if "plako" in it.get("seller_name", "").lower()]
                print(f"  - plako_plak present: {len(plako) > 0}")
                if plako:
                    print(f"    * plako item price: {plako[0].get('price')}")
        except Exception as e:
            print(f"Test '{label}' failed: {e}")

if __name__ == "__main__":
    test_params()
