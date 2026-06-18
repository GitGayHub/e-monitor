import sys
import sqlite3
import json
import os
import time
import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8')

# Ensure we can import monitor
import monitor

def send_telegram_msg(msg):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram token or chat_id not set in env!")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        print(f"Telegram send status: {resp.status_code}")
    except Exception as e:
        print(f"Telegram send error: {e}")

def test_live_details():
    # 1. Warm up the session
    session = monitor._get_ebay_session()
    monitor._warmup_session(session, "ebay.de")
    
    # 2. Get 3 active item IDs from the local database
    db_path = os.path.join(os.path.dirname(__file__), "price_history.db")
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}!")
        send_telegram_msg("<b>Details Scraper Test</b>: DB not found!")
        return
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT item_id FROM seller_prices ORDER BY recorded_at DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    
    item_ids = []
    seen = set()
    for row in rows:
        iid = row[0]
        if iid and iid not in seen:
            seen.add(iid)
            item_ids.append(iid)
            
    print(f"Found {len(item_ids)} unique item IDs in database.")
    targets = item_ids[:3]
    print(f"Testing HTML details fetching on: {targets}")
    
    results = {}
    for item_id in targets:
        print(f"\nFetching HTML details for item {item_id}...")
        try:
            details = monitor._fetch_item_details_html(item_id)
            if details:
                desc_snippet = details.get("description", "")
                if len(desc_snippet) > 150:
                    desc_snippet = desc_snippet[:150] + "... [TRUNCATED]"
                
                results[item_id] = {
                    "status": "success",
                    "title": details.get("title"),
                    "itemEndDate": details.get("itemEndDate"),
                    "price": details.get("price"),
                    "itemGroupType": details.get("itemGroupType"),
                    "description_length": len(details.get("description", "")),
                    "description_snippet": desc_snippet
                }
                print(f"Success! Title: {details.get('title')}, EndDate: {details.get('itemEndDate')}")
            else:
                results[item_id] = {
                    "status": "failed",
                    "reason": "Returned None (likely challenge page or HTTP error)"
                }
                print("Failed (returned None)")
        except Exception as e:
            results[item_id] = {
                "status": "error",
                "error": str(e)
            }
            print(f"Error: {e}")
        time.sleep(2)
        
    # Save results to json
    output_path = os.path.join(os.path.dirname(__file__), "details_test_output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved test results to {output_path}")

    # Format Telegram Message
    msg_lines = ["<b>🚨 Details Scraper Test Results (HTML-first)</b>\n"]
    for iid, res in results.items():
        msg_lines.append(f"<b>Item {iid}:</b>")
        if res["status"] == "success":
            msg_lines.append(f"• Title: {res['title']}")
            msg_lines.append(f"• EndDate: <code>{res['itemEndDate']}</code>")
            msg_lines.append(f"• Price: {res['price']}")
            msg_lines.append(f"• GroupType: {res['itemGroupType']}")
            msg_lines.append(f"• Description length: {res['description_length']}")
            msg_lines.append(f"• Desc snippet: <i>{res['description_snippet']}</i>")
        else:
            msg_lines.append(f"• Status: {res['status']}")
            msg_lines.append(f"• Reason/Error: {res.get('reason') or res.get('error')}")
        msg_lines.append("")
        
    send_telegram_msg("\n".join(msg_lines))

if __name__ == "__main__":
    test_live_details()
