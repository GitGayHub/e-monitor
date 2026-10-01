"""One explicitly labelled real delivery; config, dedup and outbox stay isolated."""
import asyncio
import copy
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    evidence = Path(sys.argv[1])
    candidates = json.loads((evidence / "live/selected-candidates.json").read_text(encoding="utf-8"))
    case = next(row for row in candidates if row["item"]["item_id"] == "800366377085")
    with tempfile.TemporaryDirectory(prefix="emonitor-delivery-probe-") as folder:
        import price_history, config_manager
        price_history.DB_PATH = str(Path(folder) / "history.db")
        config_manager.CONFIG_PATH = str(Path(folder) / "config.json")
        source = json.loads((evidence / "server-snapshot.json").read_text(encoding="utf-8"))
        Path(config_manager.CONFIG_PATH).write_text(json.dumps(source), encoding="utf-8")
        import monitor
        from mobile import feed_writer
        from mobile.merge_app_sync_to_config import app_search_to_config
        from telegram import Bot
        logging.disable(logging.CRITICAL)
        monitor.SEEN_IDS_FILE = str(Path(folder) / "seen_ids.json")
        feed_writer.FEED_PATH = evidence / "probe-feed.json"
        feed_writer.PENDING_PATH = evidence / "probe-feed-pending.json"
        receipt_path = evidence / "delivery-probe.json"
        if receipt_path.exists() and json.loads(receipt_path.read_text(encoding="utf-8")).get("delivered"):
            raise RuntimeError("Probe already delivered; refusing duplicate")
        item = copy.deepcopy(case["item"])
        details = await asyncio.to_thread(monitor._fetch_item_details, item["item_id"])
        if not details or monitor._is_details_blocked(details, app_search_to_config(case["search"])):
            raise RuntimeError("Live item details unavailable or rejected; nothing sent")
        price = details.get("price") or details.get("htmlPrice")
        if isinstance(price, dict) and price.get("value"):
            item["price"] = float(price["value"])
        shipping = details.get("htmlShippingCost")
        if isinstance(shipping, dict) and shipping.get("value"):
            item["shipping_cost"] = float(shipping["value"])
        monitor._calculate_total(item, source.get("settings", {}), details)
        item["_audit_test"] = True
        search = app_search_to_config(case["search"])
        search["display_name"] = "🧪 ТЕСТ · LG UltraGear OLED"
        async with Bot(os.environ["TELEGRAM_BOT_TOKEN"]) as bot:
            me = await bot.get_me()
            with patch.object(monitor, "_fetch_item_details", return_value=details):
                delivered = await monitor._process_notify_candidate(bot, item, search, None, "initial")
                repeat_sent = await monitor._process_notify_candidate(bot, item, search, None, "initial")
            result = {"delivered": delivered, "repeatSent": repeat_sent,
                      "botUsername": me.username, "messageId": item.get("_telegram_message_id"),
                      "itemId": item["item_id"], "searchId": search["id"], "title": item["title"],
                      "price": item["price"], "shipping": item["shipping_cost"],
                      "totalPrice": item["total_price"], "stage": "initial",
                      "logicVersion": monitor._read_logic_version_timestamp(), "url": item["url"]}
            receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False))
            if not delivered or repeat_sent:
                raise RuntimeError("Delivery or repeat check failed")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(main())
    except Exception as error:
        print("Probe failed:", type(error).__name__)
        raise SystemExit(1)
