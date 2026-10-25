import copy
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import monitor
from mobile import build_app_sync as build, merge_app_sync_to_config as merge


class AuctionWindowTest(unittest.TestCase):
    def test_older_client_preserves_window_and_explicit_default_resets_it(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder)/'config.json'; manifest = Path(folder)/'app_sync.json'
            cfg.write_text(json.dumps(dict(searches=[dict(id='x',query='iphone',filters=dict(auction_notify_minutes=20))])),encoding='utf8')
            doc = dict(schema=1,searches=[dict(id='x',query='iphone')])
            manifest.write_text(json.dumps(doc),encoding='utf8')
            with patch.object(merge,'CONFIG_PATH',cfg), patch.object(merge,'MANIFEST_PATH',manifest):
                merge.main()
                self.assertEqual(20,json.loads(cfg.read_text(encoding='utf8'))['searches'][0]['filters']['auction_notify_minutes'])
                doc['searches'][0]['auctionNotifyMinutes'] = None
                manifest.write_text(json.dumps(doc),encoding='utf8')
                merge.main()
                self.assertIsNone(json.loads(cfg.read_text(encoding='utf8'))['searches'][0]['filters']['auction_notify_minutes'])

    def test_invalid_window_never_overwrites_working_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder)/'config.json'; manifest = Path(folder)/'app_sync.json'
            cfg.write_text('{"searches":[],"settings":{}}',encoding='utf8')
            original = cfg.read_bytes()
            manifest.write_text(json.dumps(dict(schema=1,searches=[dict(id='x',query='phone',auctionNotifyMinutes=0)])),encoding='utf8')
            with patch.object(merge,'CONFIG_PATH',cfg), patch.object(merge,'MANIFEST_PATH',manifest), self.assertRaises(ValueError):
                merge.main()
            self.assertEqual(original,cfg.read_bytes())
    def test_default_and_custom_windows_on_both_auction_types(self):
        search = dict(id='test', query='iphone 17 pro max', filters=dict(limit_price=910, max_price=2500))
        row = dict(price=600, total_price=606, auction=True, buy_now=False, title='Apple iPhone 17 Pro Max')
        for offer in (False, True):
            row['best_offer'] = offer
            for window in (None, 1, 20, 30, 1440):
                s = copy.deepcopy(search)
                s['filters']['auction_notify_minutes'] = window
                for left in (1, 19, 20, 21, 29, 30, 31, 1440, 1441, None):
                    row['time_left'] = f'{left} min' if left is not None else ''
                    expected = (window is None and offer) or (left is not None and left <= (window or 1440))
                    with self.subTest(offer=offer, window=window, left=left):
                        self.assertEqual(expected, monitor._notify_eligibility(row, s)[0])
                row['total_price'] = 1000
                self.assertEqual((False, 'over_limit'), monitor._notify_eligibility(row, s))
                row['total_price'] = 606
        row.update(auction=False, buy_now=True, time_left='')
        search['filters']['auction_notify_minutes'] = 20
        self.assertTrue(monitor._notify_eligibility(row, search)[0])

    def test_schema_one_round_trip_and_invalid_input(self):
        for value in (None, 1, 20, 30, 1440):
            original = dict(id='x', query='iphone 17 pro max', auctionNotifyMinutes=value)
            self.assertEqual(value, build.convert_search(merge.app_search_to_config(original))['auctionNotifyMinutes'])
        for value in (True, False, 0, -1, 1441, '20', 20.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                merge.app_search_to_config(dict(query='test', auctionNotifyMinutes=value))

    def test_time_window_does_not_invalidate_purchase_history(self):
        s = dict(id='x', query='iphone 17 pro max', filters={})
        before = monitor._history_filter_signature(s)
        s['filters']['auction_notify_minutes'] = 20
        self.assertEqual(before, monitor._history_filter_signature(s))

    def test_queue_uses_custom_entry_time_for_best_offer_too(self):
        row = dict(auction=True, buy_now=False, best_offer=True)
        s = dict(filters=dict(auction_notify_minutes=20))
        self.assertEqual((0, 1800), monitor._live_validation_tier(row, s, True, dict(ends=3000, checked_at=1700), 2000))
        self.assertEqual((2, 1800), monitor._live_validation_tier(row, s, True, dict(ends=3000, checked_at=1900), 2000))
