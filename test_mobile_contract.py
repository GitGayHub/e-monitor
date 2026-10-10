import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from mobile import build_app_sync as build, merge_app_sync_to_config as merge, feed_writer as feed
import monitor
import asyncio
from unittest.mock import Mock


class MobileContractTests(unittest.TestCase):
    def test_long_notification_keeps_photo_and_never_duplicates_after_partial_delivery(self):
        bot=Mock(); photo=Mock(message_id=51)
        bot.send_photo=AsyncMock(return_value=photo)
        bot.send_message=AsyncMock(side_effect=RuntimeError('text unavailable'))
        text='<b>Фото и цена 225€</b>\n'+'😀'*1200
        result=asyncio.run(monitor.safe_send_telegram(bot,1,text,img='https://i.ebayimg.com/images/g/example/s-l800.jpg'))
        self.assertIs(photo,result)
        bot.send_photo.assert_awaited_once()
        args=bot.send_photo.await_args.kwargs
        self.assertLessEqual(len(args['caption'].encode('utf-16-le'))//2,1024)
        self.assertIsNone(args['parse_mode'])
        self.assertEqual(text,bot.send_message.await_args.kwargs['text'])

    def test_live_api_string_seller_rating_reaches_real_notification_formatter_once(self):
        item = {"item_id": "800366377085", "title": 'LG UltraGear 27GX790A-B OLED Gaming Monitor 27" 480Hz 0,03ms',
                "price": 405, "shipping_cost": 18.99, "total_price": 423.99, "seller_name": "tobiahellwi-0",
                "seller_rating_count": 16, "seller_rating_percent": 100.0, "buy_now": True, "auction": False,
                "best_offer": True, "location": "DE", "condition": "Gebraucht", "source": "api",
                "url": "https://www.ebay.de/itm/800366377085"}
        search = {"id": "isolated-lg", "query": "lg ultragear oled 480hz", "filters": {"category": "monitors", "limit_price": 430}}
        details = {"title": item["title"], "description": 'LG UltraGear 27GX790A-B OLED Gaming Monitor 27" 480Hz 0,03ms. Montior ist 10 Monate alt.',
                   "price": {"value": "405", "currency": "EUR"}, "seller": {"username": "tobiahellwi-0", "feedbackScore": "16", "feedbackPercentage": "100.0"}}
        cfg = Mock(); cfg.get_settings.return_value = {}
        cfg.get_global_banned_sellers.return_value = []; cfg.get_banned_item_ids.return_value = set(); cfg.get_item_hashes.return_value = set()
        bot = Mock(); bot.get_me = AsyncMock(return_value=Mock(username="isolated_test_bot"))
        with patch.object(monitor, "config", cfg), patch.object(monitor, "seen_state", {}), \
             patch.object(monitor, "save_seen_ids"), patch.object(monitor, "is_outlier", return_value=False), \
             patch.object(monitor, "_fetch_item_details", return_value=details), patch.object(feed, "enqueue"), \
             patch.object(monitor, "safe_send_telegram", new=AsyncMock(return_value=Mock(message_id=4048))) as sender:
            self.assertTrue(asyncio.run(monitor._process_notify_candidate(bot, item, search, None, "initial")))
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(bot, item, search, None, "initial")))
            sender.assert_awaited_once()
            caption = sender.await_args.args[2]
            self.assertIn("423.99€", caption)
            self.assertIn("16 отзывов", caption)
            self.assertEqual(item["_telegram_message_id"], 4048)
            self.assertEqual(monitor._seller_trust(item["seller_rating_count"], item["seller_rating_percent"]), "trusted")

    def test_missing_or_malformed_seller_rating_is_unknown_not_a_send_exception(self):
        for score, percent in [(None, None), ("unknown", "---"), ("NaN", "inf"), (-1, 105)]:
            self.assertEqual("risky", monitor._seller_trust(score, percent))
    def test_price_and_metadata_without_seller_description_cannot_send(self):
        item = {"item_id": "unverified", "title": "Sony DualSense Wireless Controller", "price": 30,
                "shipping_cost": 0, "seller_name": "seller", "buy_now": True, "auction": False}
        search = {"query": "DualSense", "filters": {"category": "all", "limit_price": 40}}
        for description in (None, "", '<div class="product_crosssell">Other working products</div>'):
            details = {"title": item["title"], "price": {"value": "30"}}
            if description is not None:
                details["description"] = description
            with patch.object(monitor, "seen_state", {}), patch.object(monitor, "_fetch_item_details", return_value=details), \
                 patch.object(monitor, "send_notification", new=AsyncMock()) as sender:
                self.assertFalse(asyncio.run(monitor._process_notify_candidate(Mock(), copy.deepcopy(item), search, None, "initial")))
                sender.assert_not_awaited()

    def test_refreshed_foreign_country_cannot_bypass_germany_filter(self):
        item = {"item_id":"foreign","title":"Sony DualSense Wireless Controller", "price":30,"shipping_cost":0,"total_price":30,"seller_name":"seller","condition":"Gebraucht","location":"","buy_now":True,"auction":False,"best_offer":False}
        search = {"id":"pad","query":"DualSense", "filters":{"location":"de", "category":"all", "listing_type":"buy_now", "limit_price":40}}
        details = {"title":item["title"],"itemLocationText":"Niederlande","price":{"value":"30"}}
        with patch.object(monitor, "seen_state", {}), patch.object(monitor, "_fetch_item_details", return_value=details), patch.object(monitor, "send_notification", new=AsyncMock()) as sender:
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(Mock(),item,search,None,"initial")))
            sender.assert_not_awaited()

    def test_confirmed_stage_is_not_sent_again(self):
        with patch.object(monitor, "seen_state", {"delivered": {"initial": True}}), patch.object(monitor, "_fetch_item_details") as details:
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(Mock(), {"item_id": "delivered"}, {}, None, "initial")))
            details.assert_not_called()

    def test_checkpoint_preserves_concurrent_phone_and_runtime_changes(self):
        from mobile.checkpoint_push import merge_config
        base = {"settings": {"user_zip": "09648"}, "item_hashes": []}
        local = {"settings": {"user_zip": "09648"}, "item_hashes": ["delivered"]}
        remote = {"settings": {"user_zip": "10115"}, "item_hashes": [], "mobile_managed": True}
        self.assertEqual(merge_config(base, local, remote), {"settings": {"user_zip": "10115"}, "item_hashes": ["delivered"], "mobile_managed": True})
        with self.assertRaises(ValueError):
            merge_config({"a": 1}, {"a": 2}, {"a": 3})

    def test_auction_fetch_does_not_apply_buy_now_minimum(self):
        search = {"query": "DualSense", "filters": {"min_price": 25, "limit_price": 40, "listing_type": "auction"}}
        self.assertIsNone(monitor._prepare_monitor_fetch_search(search)["filters"]["min_price"])
        search["filters"]["listing_type"] = "buy_now"
        self.assertEqual(monitor._prepare_monitor_fetch_search(search)["filters"]["min_price"], 25)

    def test_hard_max_also_applies_to_statistics_eligibility(self):
        item = {"price": 51, "total_price": 51, "buy_now": True}
        self.assertEqual(monitor._notify_eligibility(item, {"query": "DualSense", "filters": {"max_price": 50}}), (False, "over_limit"))

    def test_invalid_config_cannot_be_overwritten_by_phone(self):
        with tempfile.TemporaryDirectory() as folder:
            c = Path(folder) / "config.json"; m = Path(folder) / "app_sync.json"
            c.write_text("{broken", encoding="utf-8")
            m.write_text(json.dumps({"schema": 1, "searches": []}), encoding="utf-8")
            with patch.object(merge, "CONFIG_PATH", c), patch.object(merge, "MANIFEST_PATH", m):
                with self.assertRaises(json.JSONDecodeError):
                    merge.main()
            self.assertEqual(c.read_text(encoding="utf-8"), "{broken")

    def test_failed_final_send_restores_all_previous_stages(self):
        for stage in ("final_hour", "final_15m"):
            before = {"initial": True, "final_hour": False, "final_15m": False}
            item = {"item_id": "retry", "title": "DualSense", "seller_name": "seller", "price": 30,
                    "total_price": 30, "auction": True, "buy_now": False, "time_left": "5 Min"}
            search = {"query": "DualSense", "filters": {"category": "all", "limit_price": 40}}
            with patch.object(monitor, "seen_state", {"retry": before.copy()}), patch.object(monitor, "save_seen_ids"), \
                 patch.object(monitor, "_fetch_item_details", return_value={"title": "DualSense", "description": "Sony DualSense, fully functional controller.", "price": {"value": "30"}}), \
                 patch.object(monitor, "send_notification", new=AsyncMock(return_value=False)) as sender:
                self.assertFalse(asyncio.run(monitor._process_notify_candidate(Mock(), item, search, None, stage)))
                sender.assert_awaited_once()
                self.assertEqual(monitor.get_seen_entry("retry"), before)

    def test_unknown_seller_and_waiting_auction_are_not_marked_delivered(self):
        for seller in ("unknown", "seller"):
            item = {"item_id": "retry", "title": "DualSense", "seller_name": seller, "price": 30,
                    "total_price": 30, "auction": True, "buy_now": False, "time_left": "3 T"}
            search = {"query": "DualSense", "filters": {"category": "all", "limit_price": 40}}
            with patch.object(monitor, "seen_state", {}), patch.object(monitor, "save_seen_ids"), \
                 patch.object(monitor, "_fetch_item_details", return_value=None), \
                 patch.object(monitor, "send_notification", new=AsyncMock()) as sender:
                self.assertFalse(asyncio.run(monitor._process_notify_candidate(Mock(), item, search, None, "initial")))
                self.assertFalse(monitor.get_seen_entry("retry")["initial"])
                sender.assert_not_awaited()

    def test_rejected_photo_falls_back_to_same_bot_text_and_returns_receipt(self):
        from telegram.error import BadRequest
        bot = Mock()
        bot.send_photo = AsyncMock(side_effect=BadRequest("Wrong file identifier"))
        receipt = Mock(message_id=42)
        bot.send_message = AsyncMock(return_value=receipt)
        result = asyncio.run(monitor.safe_send_telegram(bot, 1, "<b>message</b>", img="https://example.com/photo.jpg"))
        self.assertIs(result, receipt)
        bot.send_message.assert_awaited_once()

    def test_superlight_generation_cannot_come_from_a_stock_number(self):
        self.assertFalse(monitor._matches_superlight_2_mouse(monitor._normalize("Logitech Superlight Wireless 2#1907443")))
        self.assertTrue(monitor._matches_superlight_2_mouse(monitor._normalize("Logitech Superlight II Wireless")))

    def test_all_filter_fields_round_trip_including_zero_false(self):
        original = {"id": "roundtrip", "query": "DualSense", "display_name": "Gamepad",
                    "filters": {"min_price": 0, "limit_price": 0, "max_price": 0, "best_offer": True,
                                "listing_type": "auction", "condition": "used", "seller_type": "private",
                                "location": "worldwide", "category": "consoles", "plz_center": "09648", "max_distance_km": 0},
                    "include_words": ["sony"], "exclude_words": ["defekt"], "exclude_sellers": ["blocked"],
                    "enabled": False, "notify": False}
        result = merge.app_search_to_config(build.convert_search(original))
        self.assertEqual(original, result)

    def test_null_limits_remain_null(self):
        data = {"query": "test", "maxPrice": None, "hardMaxPrice": None, "bestOffer": False}
        result = merge.app_search_to_config(data)
        self.assertIsNone(result["filters"]["limit_price"])
        self.assertIsNone(result["filters"]["max_price"])
        exported = build.convert_search(result)
        self.assertIsNone(exported["hardMaxPrice"])
        self.assertIsNone(exported["maxPrice"])

    def test_invalid_config_never_replaces_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            c = Path(folder) / "config.json"; m = Path(folder) / "app_sync.json"
            c.write_text("{broken", encoding="utf-8")
            m.write_text('{"searches": []}', encoding="utf-8")
            with patch.object(build, "CONFIG_PATH", c), patch.object(build, "OUTPUT_PATH", m):
                with self.assertRaises(ValueError):
                    build.main()
            self.assertEqual(m.read_text(), '{"searches": []}')

    def test_empty_config_does_not_resurrect_deleted_searches(self):
        with tempfile.TemporaryDirectory() as folder:
            c = Path(folder) / "config.json"; m = Path(folder) / "app_sync.json"
            c.write_text(json.dumps({"searches": []}), encoding="utf-8")
            m.write_text(json.dumps({"searches": [{"query": "deleted"}]}), encoding="utf-8")
            with patch.object(build, "CONFIG_PATH", c), patch.object(build, "OUTPUT_PATH", m):
                build.main()
            self.assertEqual(json.loads(m.read_text())["searches"], [])

    def test_pending_phone_edits_not_overwritten_by_old_config(self):
        with tempfile.TemporaryDirectory() as folder:
            c = Path(folder) / "config.json"; m = Path(folder) / "app_sync.json"
            c.write_text(json.dumps({"searches": [{"query": "old"}]}), encoding="utf-8")
            pending = {"writer": "android", "updatedAt": "new", "searches": []}
            m.write_text(json.dumps(pending), encoding="utf-8")
            with patch.object(build, "CONFIG_PATH", c), patch.object(build, "OUTPUT_PATH", m):
                build.main()
            self.assertEqual(json.loads(m.read_text()), pending)

    def test_feed_failure_retries_without_another_telegram_send(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "feed.json"; pending = Path(folder) / "pending.json"
            item = {"item_id": "123", "title": "valid", "price": 100, "total_price": 105, "shipping_cost": 5}
            with patch.object(feed, "FEED_PATH", path), patch.object(feed, "PENDING_PATH", pending):
                with patch.object(feed, "flush_pending", side_effect=OSError("publication offline")):
                    with self.assertRaises(OSError):
                        feed.enqueue(item, {"id": "s", "query": "test"}, telegram_message_id=42)
                self.assertEqual(len(json.loads(pending.read_text())["items"]), 1)
                self.assertEqual(feed.flush_pending(), 1)
                self.assertEqual(feed.flush_pending(), 0)
                rows = json.loads(path.read_text())["items"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["telegramMessageId"], 42)
                self.assertEqual(json.loads(pending.read_text())["items"], [])

    def test_feed_records_latest_stage_without_duplicate_cards(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "feed.json"; pending = Path(folder) / "pending.json"
            with patch.object(feed, "FEED_PATH", path), patch.object(feed, "PENDING_PATH", pending):
                for n, stage in enumerate(["initial", "final_hour", "final_15m"]):
                    feed.enqueue({"item_id": "123", "price": 50}, {"id": "s"}, spotted_time=100+n, notify_stage=stage)
                rows = json.loads(path.read_text())["items"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["notifyStage"], "final_15m")

    def test_phone_managed_filters_skip_legacy_migrations(self):
        from config_manager import _migrate_searches
        config = {"mobile_managed": True, "searches": [{"query": "Sony WH-1000XM6", "filters": {"category": "headphones"}}]}
        before = copy.deepcopy(config)
        self.assertFalse(_migrate_searches(config))
        self.assertEqual(config, before)

    def test_normal_uses_authoritative_lower_price_like_statistics(self):
        document=json.loads((Path(__file__).parent/"qa/fixtures/parity_cases.json").read_text(encoding="utf-8"))
        c=next(x for x in document["cases"] if x["name"]=="details contract: lower BIN authoritative")
        item=copy.deepcopy(c["item"]);search=merge.app_search_to_config(c["search"])
        cfg=Mock();cfg.get_settings.return_value=c["settings"];cfg.get_global_banned_sellers.return_value=[]
        cfg.get_banned_item_ids.return_value=set();cfg.get_item_hashes.return_value=set()
        details = dict(c["details"], description="Fully functional Logitech Superlight 2 mouse.")
        with patch.object(monitor,"config",cfg),patch.object(monitor,"seen_state",{}),patch.object(monitor,"save_seen_ids"),patch.object(monitor,"_fetch_item_details",return_value=details),patch.object(monitor,"send_notification",new=AsyncMock(return_value=True)),patch.object(feed,"enqueue"):
            self.assertTrue(asyncio.run(monitor._process_notify_candidate(Mock(),item,search,None,"initial")))
            self.assertEqual(item["total_price"],30)
            self.assertTrue(monitor.get_seen_entry(item["item_id"])["initial"])

    def test_unavailable_details_wait_for_retry_then_send_once(self):
        document = json.loads((Path(__file__).parent / "qa/fixtures/parity_cases.json").read_text(encoding="utf-8"))
        case = next(x for x in document["cases"] if x["name"] == "details contract: lower BIN authoritative")
        item = copy.deepcopy(case["item"])
        search = merge.app_search_to_config(case["search"])
        cfg = Mock()
        cfg.get_settings.return_value = case["settings"]
        cfg.get_global_banned_sellers.return_value = []
        cfg.get_banned_item_ids.return_value = set()
        cfg.get_item_hashes.return_value = set()
        with patch.object(monitor, "config", cfg), patch.object(monitor, "seen_state", {}), \
             patch.object(monitor, "save_seen_ids"), \
             patch.object(monitor, "_fetch_item_details", side_effect=[None, {}, dict(case["details"], description="Fully functional Logitech Superlight 2 mouse.")]) as fetch, \
             patch.object(monitor, "send_notification", new=AsyncMock(return_value=True)) as sender, \
             patch.object(feed, "enqueue") as enqueue:
            for _ in range(2):
                self.assertFalse(asyncio.run(monitor._process_notify_candidate(Mock(), item, search, None, "initial")))
                self.assertFalse(monitor.get_seen_entry(item["item_id"])["initial"])
                sender.assert_not_awaited()
                enqueue.assert_not_called()
            self.assertTrue(asyncio.run(monitor._process_notify_candidate(Mock(), item, search, None, "initial")))
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(Mock(), item, search, None, "initial")))
            sender.assert_awaited_once()
            enqueue.assert_called_once()
            self.assertEqual(fetch.call_count, 3)

    def test_rejected_details_never_claim_successful_delivery(self):
        item={"item_id":"retry-rejected","title":"Logitech Superlight 2","price":30,"shipping_cost":5,"seller_name":"seller","buy_now":True,"auction":False,"location":"DE","condition":"Gebraucht"}
        search={"id":"s","query":"logitech superlight 2","filters":{"category":"mice","limit_price":45}}
        with patch.object(monitor,"seen_state",{}),patch.object(monitor,"save_seen_ids"),patch.object(monitor,"_fetch_item_details",return_value={"categoryId":"177"}),patch.object(monitor,"send_notification",new=AsyncMock()) as sender:
            self.assertFalse(asyncio.run(monitor._process_notify_candidate(Mock(),item,search,None,"initial")))
            self.assertFalse(monitor.get_seen_entry(item["item_id"])["initial"])
            sender.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
