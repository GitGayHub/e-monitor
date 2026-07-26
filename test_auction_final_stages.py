"""Auction alerts: initial → 1 hour → 15 minutes, and the sweeps that feed them.

Being first is the point of the bot, so two things have to hold:

* the lot has to be *visible* in its last minutes — the monitoring profile sorts
  by price, where an ending lot can sit on page 3, so an "ending soonest" sweep
  runs for every auction-capable search;
* a lot that was already announced gets a last call ~15 min before the hammer,
  but only while the price still fits (every bid moves it).
"""

import unittest
from unittest import mock

import monitor


def _auction(item_id, time_left, price=100.0, best_offer=False):
    return {
        "item_id": item_id,
        "title": "Logitech G Pro X Superlight 2",
        "price": price,
        "total_price": price,
        "auction": True,
        "buy_now": False,
        "best_offer": best_offer,
        "bids_count": 0,
        "time_left": time_left,
        "seller_name": "seller",
    }


def _bin(item_id, price=100.0):
    it = _auction(item_id, "", price)
    it.update(auction=False, buy_now=True, time_left="")
    return it


class NotifyStageSelectionTest(unittest.TestCase):
    def setUp(self):
        self._saved = monitor.seen_state
        monitor.seen_state = {}
        patcher = mock.patch.object(monitor, "save_seen_ids", lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        monitor.seen_state = self._saved

    def _stages(self, items):
        return {i["item_id"]: s for i, s in monitor._notify_candidates_from_filtered(items)}

    def test_unseen_item_is_an_initial_notify(self):
        self.assertEqual(self._stages([_auction("1", "2д 3ч")]), {"1": "initial"})

    def test_seen_auction_inside_the_hour_is_a_final_hour_notify(self):
        monitor.mark_seen_item("1", stage="initial")
        self.assertEqual(self._stages([_auction("1", "45мин")]), {"1": "final_hour"})

    def test_seen_auction_inside_the_last_minutes_is_a_15m_notify(self):
        monitor.mark_seen_item("1", stage="initial")
        self.assertEqual(self._stages([_auction("1", "12мин")]), {"1": "final_15m"})

    def test_15m_notify_fires_even_when_the_final_hour_one_already_did(self):
        monitor.mark_seen_item("1", stage="final_hour")
        self.assertEqual(self._stages([_auction("1", "9мин")]), {"1": "final_15m"})

    def test_nothing_is_sent_twice(self):
        monitor.mark_seen_item("1", stage="final_15m")
        self.assertEqual(self._stages([_auction("1", "3мин")]), {})

    def test_a_lot_that_skipped_the_hour_does_not_get_it_afterwards(self):
        """A pass can jump from "2 h left" straight past the final hour."""
        monitor.mark_seen_item("1", stage="initial")
        self._stages([_auction("1", "11мин")])
        monitor.mark_seen_item("1", stage="final_15m")
        self.assertEqual(self._stages([_auction("1", "40мин")]), {})

    def test_buy_now_is_never_re_notified(self):
        monitor.mark_seen_item("2", stage="initial")
        self.assertEqual(self._stages([_bin("2")]), {})

    def test_far_out_auction_waits(self):
        monitor.mark_seen_item("1", stage="initial")
        self.assertEqual(self._stages([_auction("1", "5ч")]), {})

    def test_legacy_seen_entries_still_get_their_last_call(self):
        """seen_ids.json written before this stage existed has no flag at all."""
        monitor.seen_state = monitor._normalize_seen_payload({"1": {"initial": True}})
        self.assertEqual(self._stages([_auction("1", "8мин")]), {"1": "final_15m"})

    def test_state_round_trip_keeps_the_new_flag(self):
        monitor.mark_seen_item("1", stage="final_15m")
        again = monitor._normalize_seen_payload(
            {k: dict(v) for k, v in monitor.seen_state.items()}
        )
        self.assertTrue(again["1"]["final_15m"])
        self.assertTrue(again["1"]["final_hour"])


class SweepSearchTest(unittest.TestCase):
    BASE = {
        "id": "lg_auc",
        "query": "lg ultragear oled 480hz",
        "filters": {"listing_type": "all", "category": "monitors", "_ipg": 60,
                    "sort": "price_asc", "max_price": 2500},
    }

    def test_ending_soon_sweep_sorts_by_hammer_time(self):
        sweep = monitor._ending_soon_auction_search(self.BASE)
        self.assertEqual(sweep["filters"]["sort"], "ending_soon")
        self.assertEqual(sweep["filters"]["listing_type"], "auction")
        self.assertEqual(monitor._sort_code(sweep["filters"]), "1")
        self.assertEqual(sweep["filters"]["_ipg"], monitor._SWEEP_PAGE_SIZE)

    def test_ending_soon_sweep_skips_buy_now_only_searches(self):
        bin_only = {**self.BASE, "filters": {**self.BASE["filters"], "listing_type": "buy_now_offer"}}
        self.assertIsNone(monitor._ending_soon_auction_search(bin_only))

    def test_ending_soon_sweep_runs_for_auction_only_searches(self):
        auc = {**self.BASE, "filters": {**self.BASE["filters"], "listing_type": "auction"}}
        self.assertIsNotNone(monitor._ending_soon_auction_search(auc))

    def test_newly_listed_sweep_sorts_newest_first(self):
        sweep = monitor._newly_listed_search(self.BASE)
        self.assertEqual(sweep["filters"]["sort"], "newest")
        self.assertEqual(monitor._sort_code(sweep["filters"]), "10")
        self.assertEqual(sweep["filters"]["listing_type"], "all",
                         "the fresh-listings sweep must not narrow the search")

    def test_sweeps_do_not_mutate_the_original_search(self):
        before = dict(self.BASE["filters"])
        monitor._ending_soon_auction_search(self.BASE)
        monitor._newly_listed_search(self.BASE)
        self.assertEqual(self.BASE["filters"], before)

    def test_ending_soon_url_carries_the_sort(self):
        sweep = monitor._ending_soon_auction_search(self.BASE)
        url = monitor._build_url_with_host("ebay.de", sweep)
        self.assertIn("_sop=1&", url + "&")
        self.assertIn("LH_Auction=1", url)


class PriceGateTest(unittest.TestCase):
    """«если цена все еще подходит» — the re-notify must re-check the limit."""

    search = {"id": "s", "query": "x", "filters": {"limit_price": 100, "max_price": 2500,
                                                  "listing_type": "auction"}}

    def test_price_within_limit_is_the_gate(self):
        cheap = _auction("1", "10мин", price=80.0)
        dear = _auction("2", "10мин", price=140.0)
        self.assertTrue(monitor._price_within_limit(cheap, self.search))
        self.assertFalse(monitor._price_within_limit(dear, self.search))


if __name__ == "__main__":
    unittest.main(verbosity=2)
