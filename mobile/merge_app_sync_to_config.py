import json
import os
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
MANIFEST_PATH = ROOT / "mobile" / "app_sync.json"


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def as_number(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return None


def as_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def app_search_to_config(search):
    filters = {
        "min_price": as_number(search.get("minPrice")),
        "limit_price": as_number(search.get("maxPrice")),
        "max_price": as_number(search.get("hardMaxPrice")) if "hardMaxPrice" in search else 2500,
        "condition": search.get("condition") or "any",
        "listing_type": search.get("listingType") or "all",
        "best_offer": as_bool(search.get("bestOffer"), False),
        "seller_type": search.get("sellerType") or "any",
        "location": search.get("location") or "de",
        "category": search.get("category") or "all",
    }
    if search.get("plzCenter"):
        filters["plz_center"] = str(search.get("plzCenter"))
    if search.get("maxDistanceKm") is not None:
        filters["max_distance_km"] = int(search["maxDistanceKm"])
    if 'auctionNotifyMinutes' in search:
        value = search['auctionNotifyMinutes']
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1440):
            raise ValueError('auctionNotifyMinutes must be null or integer 1–1440')
        filters['auction_notify_minutes'] = value
    res = {
        "id": search.get("id") or "",
        "query": search.get("query") or "",
        "filters": filters,
        "exclude_words": search.get("excludeWords") or [],
        "include_words": search.get("includeWords") or [],
        "exclude_sellers": search.get("excludeSellers") or [],
        "notify": as_bool(search.get("notify"), True),
        "enabled": as_bool(search.get("enabled"), True),
    }
    if search.get("displayName"):
        res["display_name"] = search["displayName"]
    if as_number(search.get("priority")):
        res["priority"] = int(as_number(search.get("priority")))
    return res


def main():
    manifest = load_json(MANIFEST_PATH, {})
    if manifest.get("schema") != 1:
        raise SystemExit("Unsupported or missing app sync schema")
    if not isinstance(manifest.get("searches"), list):
        raise SystemExit("Invalid manifest searches; refusing to replace config")

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    if not isinstance(config, dict) or (CONFIG_PATH.exists() and not isinstance(config.get("searches"), list)):
        raise SystemExit("Invalid existing config; refusing to replace it")
    config.setdefault("settings", {})
    config.setdefault("item_hashes", [])
    # Legacy migrations must not overwrite explicit settings from the phone.
    config["mobile_managed"] = True
    config["mobile_manifest_revision"] = str(manifest.get("updatedAt", ""))
    config["mobile_settings_revision"] = manifest.get("settingsRevision")

    previous_searches = {s['id']: s for s in config.get('searches', [])}
    searches = [
        app_search_to_config(search)
        for search in manifest.get("searches", [])
        if search.get("query")
    ]
    # An older APK omits this optional field; that must not erase a newer rule.
    for converted, original in zip(searches, [s for s in manifest['searches'] if s.get('query')]):
        if 'auctionNotifyMinutes' not in original:
            old = previous_searches.get(converted['id'], {}).get('filters', {})
            if 'auction_notify_minutes' in old:
                converted['filters']['auction_notify_minutes'] = old['auction_notify_minutes']
    config["searches"] = searches
    config["global_banned_sellers"] = sorted(set(manifest.get("bannedSellers", [])))
    config["banned_item_ids"] = sorted(set(manifest.get("hiddenItems", [])))

    app_config = manifest.get("config") or {}
    if "user_zip" in app_config:
        config["settings"]["user_zip"] = str(app_config.get("user_zip") or "")
    if "user_country" in app_config:
        config["settings"]["user_country"] = str(app_config.get("user_country") or "de")
    if "non_eu_tax_rate" in app_config:
        rate = as_number(app_config.get("non_eu_tax_rate"))
        config["settings"]["non_eu_tax_rate"] = rate if rate is not None else 0.19
    if "warn_non_eu" in app_config:
        config["settings"]["warn_non_eu"] = as_bool(app_config.get("warn_non_eu"), True)
    # Optional schema-1 settings: older clients omitting them preserve subscriptions.
    from mobile.median_reports import preferences
    median_settings = dict(config["settings"])
    for key in ("median_products", "median_interval_days"):
        if key in app_config:
            median_settings[key] = app_config[key]
    selected, days = preferences(median_settings)
    if "median_products" in app_config:
        config["settings"]["median_products"] = sorted(selected & {s['id'] for s in searches})
    if "median_interval_days" in app_config:
        config["settings"]["median_interval_days"] = days

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=CONFIG_PATH.parent, prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, CONFIG_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    print(
        "Merged Android manifest into config: "
        f"{len(searches)} searches, "
        f"{len(config['global_banned_sellers'])} banned sellers, "
        f"{len(config['banned_item_ids'])} hidden items"
    )


if __name__ == "__main__":
    main()
