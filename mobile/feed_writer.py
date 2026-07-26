"""Публикация найденных лотов в mobile/feed.json для Android-приложения.

Мониторинг отправляет находки в Telegram, но приложению читать оттуда нечего.
Манифест app_sync.json для этого не подходит: его пишет и телефон тоже, а лента
обновляется на каждом прогоне — в одном файле они бы дрались за запись. Поэтому
лента лежит отдельно и пишется только отсюда.

Формат совпадает с FeedEntry в приложении
(app/src/main/java/com/emonitor/app/core/feed/FeedClient.kt).
"""

import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "mobile" / "feed.json"

# Кольцевой буфер: лента — витрина последних находок, а не архив.
MAX_ITEMS = 200

SCHEMA = 1


def _load_items():
    try:
        with open(FEED_PATH, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except Exception:
        return []
    if not isinstance(document, dict):
        return []
    items = document.get("items")
    return items if isinstance(items, list) else []


def _write(items):
    document = {
        "schema": SCHEMA,
        "source": os.environ.get("GITHUB_REPOSITORY", "GitGayHub/e-monitor"),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "items": items,
    }
    FEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Пишем через временный файл: прогон могут прервать, а половинчатый JSON
    # приложение потом не разберёт.
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(FEED_PATH.parent), delete=False, suffix=".tmp"
    )
    try:
        with handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(handle.name, FEED_PATH)
    except Exception:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def _number(value, default=0.0):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def build_entry(
    item,
    search,
    seller_trust="",
    is_outlier=False,
    price_drop_percent=None,
    spotted_time=None,
):
    """Собирает запись ленты из внутреннего словаря лота."""
    item_id = str(item.get("item_id") or "")
    price = _number(item.get("price"))
    shipping = _number(item.get("shipping_cost"))
    total = _number(item.get("total_price"), price + shipping)
    search_id = str(search.get("id") or "")
    return {
        "itemId": item_id,
        "searchId": search_id,
        "searchQuery": search.get("display_name") or search.get("query") or search_id,
        "title": item.get("title") or "",
        "price": price,
        "shipping": shipping,
        "totalPrice": total,
        # Все цены приводятся к евро ещё на разборе выдачи.
        "currency": "EUR",
        "url": item.get("url") or (f"https://www.ebay.de/itm/{item_id}" if item_id else ""),
        "imageUrl": item.get("image_url") or None,
        "sellerName": item.get("seller_name") or "unknown",
        "sellerTrust": seller_trust,
        "condition": item.get("condition") or "",
        "location": item.get("location") or "",
        "distanceKm": None,
        "buyNow": bool(item.get("buy_now")),
        "bestOffer": bool(item.get("best_offer")),
        "auction": bool(item.get("auction")),
        "isOutlier": bool(is_outlier),
        "priceDropPercent": price_drop_percent,
        "spottedTime": int(spotted_time if spotted_time is not None else time.time() * 1000),
        "source": "github",
    }


def record_item(item, search, **kwargs):
    """Дописывает лот в ленту. Возвращает True, если файл обновлён."""
    entry = build_entry(item, search, **kwargs)
    if not entry["itemId"]:
        return False
    items = [row for row in _load_items() if row.get("itemId") != entry["itemId"]]
    items.append(entry)
    items.sort(key=lambda row: row.get("spottedTime") or 0, reverse=True)
    _write(items[:MAX_ITEMS])
    return True


if __name__ == "__main__":
    # Ручная проверка: python mobile/feed_writer.py
    sample_item = {
        "item_id": "demo-1",
        "title": "Demo listing",
        "price": 100.0,
        "shipping_cost": 4.99,
        "seller_name": "demo_seller",
        "location": "10115 Berlin",
        "buy_now": True,
    }
    sample_search = {"id": "demo", "query": "demo"}
    record_item(sample_item, sample_search, seller_trust="✅ trusted")
    print(f"Wrote {FEED_PATH} with {len(_load_items())} items")
