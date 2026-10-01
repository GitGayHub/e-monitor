"""Confirmed Telegram deliveries and a durable publication outbox for Android."""
import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "mobile" / "feed.json"
PENDING_PATH = ROOT / "mobile" / "feed_pending.json"
MAX_ITEMS = 200


def _load(path):
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != 1 or not isinstance(document.get("items"), list):
        raise ValueError("Invalid mobile feed document")
    return document["items"]


def _write(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"schema": 1, "source": os.environ.get("GITHUB_REPOSITORY", "GitGayHub/e-monitor"),
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), "items": items}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as handle:
        try:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            handle.close()
            os.unlink(handle.name)
            raise
    try:
        os.replace(handle.name, path)
    except BaseException:
        os.unlink(handle.name)
        raise


def build_entry(item, search, seller_trust="", is_outlier=False, price_drop_percent=None,
                spotted_time=None, telegram_message_id=None, notify_stage="initial", logic_version=None):
    price = round(float(item.get("price") or 0), 2)
    shipping = round(float(item.get("shipping_cost") or 0), 2)
    return {
        "itemId": str(item.get("item_id") or ""), "searchId": str(search.get("id") or ""),
        "searchQuery": search.get("display_name") or search.get("query") or "",
        "title": item.get("title") or "", "price": price, "shipping": shipping,
        "totalPrice": round(float(item.get("total_price", price + shipping)), 2), "currency": "EUR",
        "url": item.get("url") or f"https://www.ebay.de/itm/{item.get('item_id', '')}",
        "imageUrl": item.get("image_url") or None, "sellerName": item.get("seller_name") or "unknown",
        "sellerTrust": seller_trust, "condition": item.get("condition") or "",
        "location": item.get("location") or "", "distanceKm": item.get("distance_km"),
        "buyNow": bool(item.get("buy_now")), "bestOffer": bool(item.get("best_offer")),
        "auction": bool(item.get("auction")), "isOutlier": bool(is_outlier),
        "priceDropPercent": price_drop_percent, "spottedTime": int(spotted_time or time.time() * 1000),
        "source": "github", "telegramMessageId": telegram_message_id,
        "notifyStage": notify_stage, "logicVersion": logic_version,
    }


def enqueue(item, search, **kwargs):
    entry = build_entry(item, search, **kwargs)
    if not entry["itemId"]:
        raise ValueError("Cannot publish a delivery without an item ID")
    pending = _load(PENDING_PATH)
    key = (entry["itemId"], entry["notifyStage"])
    pending = [row for row in pending if (row["itemId"], row.get("notifyStage", "initial")) != key]
    _write(PENDING_PATH, pending + [entry])
    flush_pending()
    return True


def flush_pending():
    pending = _load(PENDING_PATH)
    if not pending:
        if not FEED_PATH.exists():
            _write(FEED_PATH, [])
        return 0
    rows = {row["itemId"]: row for row in _load(FEED_PATH)}
    for entry in pending:
        if entry["spottedTime"] >= rows.get(entry["itemId"], {}).get("spottedTime", 0):
            rows[entry["itemId"]] = entry
    _write(FEED_PATH, sorted(rows.values(), key=lambda row: row["spottedTime"], reverse=True)[:MAX_ITEMS])
    _write(PENDING_PATH, [])
    return len(pending)


record_item = enqueue
