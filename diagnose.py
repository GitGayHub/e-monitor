import os
import sys
import json
import copy

# Add current dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config_crypt
from config_manager import ConfigManager
import monitor

def run_diagnostics():
    print("=== START DIAGNOSTICS ===")
    
    # Get passphrase
    passphrase = os.environ.get("CONFIG_PASSPHRASE")
    if not passphrase:
        print("ERROR: CONFIG_PASSPHRASE is not set!")
        return

    # Decrypt config if not already present
    enc_path = "config.json.enc"
    dec_path = "config.json"
    if os.path.exists(enc_path) and not os.path.exists(dec_path):
        try:
            with open(enc_path, "rb") as f:
                enc_bytes = f.read()
            dec_bytes = config_crypt.decrypt(enc_bytes, passphrase)
            with open(dec_path, "w", encoding="utf-8") as f:
                f.write(dec_bytes.decode("utf-8", errors="replace"))
            print("Decrypted config.json for diagnostics.")
        except Exception as e:
            print(f"Failed to decrypt config.json: {e}")
            return

    # Initialize monitor state
    monitor.load_seen_ids()
    config_obj = ConfigManager()

    for search in config_obj.get_searches():
        query = search.get("query", "")
        if not any(k in query.lower() for k in ("sony", "ult", "900n", "xm", "headphone", "kopfhoerer", "kopfhörer")):
            continue
            
        print(f"\n==========================================")
        print(f"SEARCH: {query} (ID: {search.get('id')})")
        print(f"Filters: {search.get('filters')}")
        print(f"Exclude words: {search.get('exclude_words')}")
        print(f"Include words: {search.get('include_words')}")
        print(f"==========================================")
        
        # 1. Fetch with configured filters
        items, err = monitor.fetch_ebay_ex(search)
        print(f"Fetched {len(items)} items WITH filters (Error: {err})")
        
        # 2. Fetch WITHOUT filters (raw search)
        raw_search = copy.deepcopy(search)
        raw_search["filters"] = {}
        raw_items, raw_err = monitor.fetch_ebay_ex(raw_search)
        print(f"Fetched {len(raw_items)} items WITHOUT filters (Error: {raw_err})")
        if raw_items:
            print(f"Sample raw items found (first 3):")
            for item in raw_items[:3]:
                print(f"  - Title: {item.get('title')} | Price: {item.get('price')} | Auction: {item.get('auction')} | BuyNow: {item.get('buy_now')} | TimeLeft: {item.get('time_left')}")

    print("=== END DIAGNOSTICS ===")

if __name__ == "__main__":
    run_diagnostics()
