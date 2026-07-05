import json
import os
import copy
import logging

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "searches": [],
    "global_banned_sellers": [],
    "banned_item_ids": [],
    "item_hashes": [],
    "settings": {
        "user_zip": "",
        "user_country": "de",
        "non_eu_tax_rate": 0.19,
        "warn_non_eu": True,
    },
}

DEFAULT_SEARCH = {
    "id": "",
    "query": "",
    "filters": {
        "max_price": None,
        "condition": "any",
        "listing_type": "all",
        "seller_type": "any",
        "location": "de",
        "category": "all",
    },
    "exclude_words": [],
    "include_words": [],
    "exclude_sellers": [],
    "notify": True,
}


def _normalize_config_text(value):
    return str(value or "").casefold().replace("_", " ")


def _is_sony_headphone_search(search):
    text = " ".join(
        _normalize_config_text(search.get(key))
        for key in ("id", "query", "display_name")
    )
    return any(
        marker in text
        for marker in (
            "sony wh",
            "wh-1000xm",
            "wh 1000xm",
            "sony ult wear",
            "wh-ult900n",
            "wh ult900n",
        )
    )


def _migrate_searches(data):
    """Apply safe config migrations after loading decrypted config.json.

    Sony WH / ULT Wear searches must be fetched without eBay's strict headphone
    category parameter. eBay often indexes fresh headphone auctions in a parent or
    neighbouring electronics category first, so `_sacat=112529` can return zero
    cards even when a matching auction exists. The monitor still validates these
    searches as headphones later via `_effective_category()` and title filters.
    """
    changed = False
    for search in data.get("searches", []):
        if not isinstance(search, dict):
            continue
        filters = search.setdefault("filters", {})
        if _is_sony_headphone_search(search) and filters.get("category") != "all":
            filters["category"] = "all"
            changed = True
    return changed


class ConfigManager:
    def __init__(self, path=None):
        self._path = path or CONFIG_PATH
        self._data = {}
        self.load()

    def load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error("config load error: %s", e)
                self._data = {}
        for k, v in DEFAULT_CONFIG.items():
            if k not in self._data:
                self._data[k] = copy.deepcopy(v)
        if "settings" in self._data:
            for k, v in DEFAULT_CONFIG["settings"].items():
                if k not in self._data["settings"]:
                    self._data["settings"][k] = v
        if _migrate_searches(self._data):
            self.save()
            logger.info("Migrated Sony headphone searches to all-category eBay fetch")

    def save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error("config save error: %s", e)

    @property
    def raw(self):
        return self._data

    def get_searches(self):
        return self._data.get("searches", [])

    def get_search_by_id(self, search_id):
        for s in self.get_searches():
            if s.get("id") == search_id:
                return s
        return None

    def add_search(self, search_dict):
        s = copy.deepcopy(DEFAULT_SEARCH)
        s.update(search_dict)
        if not s["id"]:
            base = s["query"].lower().replace(" ", "_")[:30]
            existing = {x["id"] for x in self.get_searches()}
            sid = base
            n = 1
            while sid in existing:
                n += 1
                sid = f"{base}_{n}"
            s["id"] = sid
        self._data.setdefault("searches", []).append(s)
        self.save()
        return s

    def update_search(self, search_id, updates):
        for s in self.get_searches():
            if s.get("id") == search_id:
                for k, v in updates.items():
                    if k == "filters" and isinstance(v, dict):
                        s.setdefault("filters", {}).update(v)
                    else:
                        s[k] = v
                self.save()
                return s
        return None

    def delete_search(self, search_id):
        searches = self.get_searches()
        before = len(searches)
        self._data["searches"] = [s for s in searches if s.get("id") != search_id]
        self.save()
        return len(self._data["searches"]) < before

    def get_global_banned_sellers(self):
        return self._data.get("global_banned_sellers", [])

    def ban_seller_global(self, seller_name):
        sellers = self._data.setdefault("global_banned_sellers", [])
        if seller_name not in sellers:
            sellers.append(seller_name)
            self.save()

    def unban_seller_global(self, seller_name):
        sellers = self._data.get("global_banned_sellers", [])
        if seller_name in sellers:
            sellers.remove(seller_name)
            self.save()

    def get_banned_item_ids(self):
        return set(self._data.get("banned_item_ids", []))

    def ban_item(self, item_id):
        items = self._data.setdefault("banned_item_ids", [])
        if item_id not in items:
            items.append(item_id)
            self.save()

    def get_item_hashes(self):
        return set(self._data.get("item_hashes", []))

    def add_item_hash(self, h):
        hashes = self._data.setdefault("item_hashes", [])
        if h not in hashes:
            hashes.append(h)
            if len(hashes) > 15000:
                self._data["item_hashes"] = hashes[-10000:]
            self.save()

    def get_settings(self):
        return self._data.get("settings", {})

    def update_settings(self, updates):
        self._data.setdefault("settings", {}).update(updates)
        self.save()
