import json
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

    searches = [
        app_search_to_config(search)
        for search in manifest.get("searches", [])
        if search.get("query")
    ]
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

    with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(
        "Merged Android manifest into config: "
        f"{len(searches)} searches, "
        f"{len(config['global_banned_sellers'])} banned sellers, "
        f"{len(config['banned_item_ids'])} hidden items"
    )


if __name__ == "__main__":
    main()
