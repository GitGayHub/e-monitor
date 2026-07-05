import os
import sys
import json

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

    print(f"Loaded {len(config_obj.get_searches())} searches.")

    for search in config_obj.get_searches():
        query = search.get("query", "")
        # Only run for headphone searches to keep output concise, or all if user wants
        if not any(k in query.lower() for k in ("sony", "ult", "900n", "xm", "headphone", "kopfhoerer", "kopfhörer")):
            continue
            
        print(f"\n==========================================")
        print(f"SEARCH: {query}")
        print(f"==========================================")
        
        items = monitor.fetch_ebay(search)
        print(f"Fetched {len(items)} items from eBay.")
        
        global_banned = config_obj.get_global_banned_sellers()
        global_banned_norm = {monitor._normalize(s) for s in global_banned}
        banned_ids = config_obj.get_banned_item_ids() | monitor.KNOWN_BAD_ITEM_IDS
        item_hashes = config_obj.get_item_hashes()
        filters = search.get("filters", {})
        category = filters.get("category", "all")
        query_text = monitor._intent_query(search)
        exclude_words = [monitor._normalize(w) for w in search.get("exclude_words", [])]
        include_words = [monitor._normalize(w) for w in search.get("include_words", [])]
        exclude_sellers = [s.lower() for s in search.get("exclude_sellers", [])]
        exclude_sellers_norm = {monitor._normalize(s) for s in exclude_sellers}
        settings = config_obj.get_settings()
        
        for item in items:
            title = item.get("title", "")
            item_id = item.get("item_id", "")
            print(f"\nItem: {title} (ID: {item_id})")
            print(f"  Price: {item.get('price')} | Auction: {item.get('auction')} | Buy Now: {item.get('buy_now')} | Time Left: {item.get('time_left')}")
            
            if item.get("is_multivariation"):
                print("  -> FILTERED: multivariation")
                continue
                
            if item_id in banned_ids:
                print("  -> FILTERED: banned ID")
                continue
                
            if filters.get("location", "de") == "de" and item.get("location"):
                if monitor._is_clearly_non_germany_location(item["location"]):
                    print(f"  -> FILTERED: non-Germany location ({item['location']})")
                    continue
                    
            min_price = filters.get("min_price")
            item = monitor._calculate_total(item, settings)
            listing_type = filters.get("listing_type", "all")
            if item.get("buy_now") and item.get("auction"):
                if listing_type == "auction":
                    item["price"] = item.get("auc_price") or item["price"]
                    item["total_price"] = item.get("auc_total_price") or item["total_price"]
                    item["buy_now"] = False
                elif listing_type in ("buy_now", "buy_now_offer"):
                    item["price"] = item.get("bin_price") or item["price"]
                    item["total_price"] = item.get("bin_total_price") or item["total_price"]
                    item["auction"] = False

            if min_price is not None and not item.get("auction") and item.get("total_price", 0) < min_price:
                print(f"  -> FILTERED: price ({item.get('total_price')}) < min_price ({min_price})")
                continue
                
            limit_or_max = filters.get("limit_price") or filters.get("max_price")
            if limit_or_max is not None and item.get("total_price", 0) > limit_or_max:
                print(f"  -> FILTERED: price ({item.get('total_price')}) > max/limit ({limit_or_max})")
                continue
                
            if listing_type == "auction" and not item.get("auction"):
                print("  -> FILTERED: not an auction")
                continue
            if listing_type in ("buy_now", "buy_now_offer") and not item.get("buy_now"):
                print("  -> FILTERED: not buy now")
                continue
                
            # Check 24 hour auction rule
            if item.get("auction") and not item.get("buy_now"):
                is_best_offer = item.get("best_offer")
                is_ending_soon = False
                time_left_str = item.get("time_left", "")
                if time_left_str:
                    minutes = monitor._parse_time_left_to_minutes(time_left_str)
                    if minutes is not None and minutes <= 1440:
                        is_ending_soon = True
                if not (is_best_offer or is_ending_soon):
                    print(f"  -> FILTERED: auction ending time too far ({time_left_str})")
                    continue
                    
            cond_norm = monitor._normalize(item.get("condition", ""))
            if cond_norm:
                if cond_norm in monitor.BAD_CONDITIONS or any(w in cond_norm for w in ("defekt", "ersatzteil", "parts", "not working", "salvage", "reparatur", "broken")):
                    print(f"  -> FILTERED: bad condition ({item.get('condition')})")
                    continue
                    
            title_norm = monitor._normalize(title)
            if not monitor._intent_prelim_matches_title(title_norm, search):
                print("  -> FILTERED: intent preliminary title match failed")
                continue
                
            query_norm = monitor._normalize(query_text)
            effective_category = monitor._effective_category(category, query_norm)
            if not monitor._matches_category_query(title_norm, effective_category, query_norm):
                print(f"  -> FILTERED: category matching failed (category: {effective_category}, query: {query_norm})")
                continue
                
            if monitor._is_category_blocked_title(title_norm, effective_category, query_norm):
                print("  -> FILTERED: category blocked title")
                continue
                
            exclude_matched = [w for w in exclude_words if monitor._has_term(title_norm, w)]
            if exclude_matched:
                print(f"  -> FILTERED: exclude words matched ({exclude_matched})")
                continue
                
            if include_words and not any(w in title_norm for w in include_words):
                print(f"  -> FILTERED: include words not matched (title: {title_norm}, include: {include_words})")
                continue
                
            print("  ✅ PASSED!")

    print("=== END DIAGNOSTICS ===")

if __name__ == "__main__":
    run_diagnostics()
