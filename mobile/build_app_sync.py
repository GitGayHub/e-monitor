import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
OUTPUT_PATH = ROOT / "mobile" / "app_sync.json"


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def convert_search(search):
    filters = search.get("filters") or {}
    return {
        "id": search.get("id") or "",
        "query": search.get("query") or "",
        "minPrice": filters.get("min_price"),
        "maxPrice": filters.get("max_price"),
        "condition": filters.get("condition") or "any",
        "listingType": filters.get("listing_type") or "all",
        "sellerType": filters.get("seller_type") or "any",
        "location": filters.get("location") or "de",
        "category": filters.get("category") or "all",
        "plzCenter": filters.get("plz_center") or search.get("plz_center") or "",
        "maxDistanceKm": filters.get("max_distance_km") or search.get("max_distance_km"),
        "includeWords": search.get("include_words") or [],
        "excludeWords": search.get("exclude_words") or [],
        "excludeSellers": search.get("exclude_sellers") or [],
        "notify": bool(search.get("notify", True)),
        "enabled": bool(search.get("enabled", True)),
    }


def main():
    config = load_json(CONFIG_PATH, {})
    existing = load_json(OUTPUT_PATH, {})
    settings = config.get("settings") or {}
    searches = [
        convert_search(search)
        for search in config.get("searches", [])
        if search.get("query")
    ] or existing.get("searches", [])
    document = {
        "schema": 1,
        "source": os.environ.get("GITHUB_REPOSITORY", "GitGayHub/e-monitor"),
        "commit": os.environ.get("GITHUB_SHA", ""),
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "ebay_marketplace_id": os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_DE"),
            "ebay_source": os.environ.get("EBAY_SOURCE", "api_first"),
            "user_zip": str(settings.get("user_zip") or ""),
            "user_country": str(settings.get("user_country") or "de"),
            "non_eu_tax_rate": str(settings.get("non_eu_tax_rate", 0.19)),
            "warn_non_eu": str(settings.get("warn_non_eu", True)).lower(),
        },
        "searches": searches,
        "items": existing.get("items", []),
        "bannedSellers": config.get("global_banned_sellers", existing.get("bannedSellers", [])),
        "hiddenItems": config.get("banned_item_ids", existing.get("hiddenItems", [])),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"Wrote {OUTPUT_PATH} with {len(document['searches'])} searches")


if __name__ == "__main__":
    main()
