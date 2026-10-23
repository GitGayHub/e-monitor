"""Owner priority order from the app decides how often each search is checked."""
import collections
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import price_history
import monitor
from ebay_access import BrowseAccess, PRIORITY_MAX_WEIGHT, priority_intervals, priority_weights
from mobile.build_app_sync import convert_search
from mobile.merge_app_sync_to_config import app_search_to_config


def searches(n, ranked=True):
    return [{'id': f's{i:02d}', 'query': f'q{i}', 'enabled': True, **({'priority': i+1} if ranked else {})}
            for i in range(n)]


class SearchPriorityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        db = patch.object(price_history, 'DB_PATH', str(Path(self.folder.name)/'h.db')); db.start(); self.addCleanup(db.stop)
        price_history.init_db()
        self.access = BrowseAccess()

    def test_weights_follow_places_and_unranked_waits_like_the_last(self):
        self.assertEqual({}, priority_weights(searches(5, ranked=False)))
        rows = searches(4) + [{'id': 'new', 'query': 'n'}]
        weights = priority_weights(rows)
        self.assertEqual(1.0, weights['s00']); self.assertEqual(PRIORITY_MAX_WEIGHT, weights['s03'])
        self.assertEqual(PRIORITY_MAX_WEIGHT, weights['new'])
        self.assertLess(weights['s01'], weights['s02'])
        # A product's buy and auction searches share one place.
        pair = [{'id': 'a', 'priority': 1}, {'id': 'b', 'priority': 1}, {'id': 'c', 'priority': 2}]
        self.assertEqual(priority_weights(pair)['a'], priority_weights(pair)['b'])

    def test_without_places_the_old_rotation_is_unchanged(self):
        rows = searches(4, ranked=False)
        self.access.start_normal_search('s01', 's02', 'EBAY_DE')
        self.assertEqual(['s02', 's03', 's00', 's01'], [r['id'] for r in self.access.normal_queue(rows, 'EBAY_DE')])

    def test_validation_resume_still_goes_first(self):
        rows = searches(4)
        self.access.defer_normal_validation('s03', 'EBAY_DE')
        self.assertEqual('s03', self.access.normal_queue(rows, 'EBAY_DE')[0]['id'])

    def test_two_hundred_passes_follow_the_order_without_starving_the_last(self):
        rows, capacity, now = searches(48), 15, 1_000_000.0
        last, gaps = {}, collections.defaultdict(list)
        for index in range(200):
            state = self.access.state()
            state['html_attempts'] = {r['id']+'|EBAY_DE': last[r['id']] for r in rows if r['id'] in last}
            self.access.save(state)
            for row in self.access.normal_queue(rows, 'EBAY_DE', now=now)[:capacity]:
                if row['id'] in last and index > 40:  # after the first full rotation
                    gaps[row['id']].append(now-last[row['id']])
                last[row['id']] = now
            now += 390
        mean = {k: sum(v)/len(v) for k, v in gaps.items()}
        self.assertEqual(390, max(gaps['s00']))  # first place: every pass
        self.assertLess(mean['s00'], mean['s10']); self.assertLess(mean['s10'], mean['s47'])
        self.assertLessEqual(max(gaps['s47']), 390*PRIORITY_MAX_WEIGHT*2)
        self.assertEqual(48, len(gaps))

    def test_expected_intervals_match_capacity_and_never_beat_one_pass(self):
        rows = searches(48)
        plan = priority_intervals(rows, 15/6.5, 6.5)
        self.assertEqual(6.5, plan['s00'])
        self.assertGreater(plan['s47'], plan['s24'])
        self.assertEqual({}, priority_intervals(rows, 0, 6.5))

    def test_priority_survives_app_sync_round_trip(self):
        app = {'id': 'x', 'query': 'iphone 17 pro max', 'maxPrice': 910, 'priority': 3}
        server = app_search_to_config(app)
        self.assertEqual(3, server['priority'])
        self.assertEqual(3, convert_search(server)['priority'])
        self.assertNotIn('priority', app_search_to_config({'id': 'y', 'query': 'q'}))
        self.assertNotIn('priority', convert_search(app_search_to_config({'id': 'y', 'query': 'q'})))

    def test_multiple_ebay_api_keys_rotate_evenly_and_skip_paused_key(self):
        keys = [
            {'key_id': 'k1', 'label': 'Ключ 1', 'client_id': 'cid_one_1111', 'client_secret': 'sec1'},
            {'key_id': 'k2', 'label': 'Ключ 2', 'client_id': 'cid_two_2222', 'client_secret': 'sec2'},
            {'key_id': 'k3', 'label': 'Ключ 3', 'client_id': 'cid_thr_3333', 'client_secret': 'sec3'},
        ]
        chosen = []
        with patch('ebay_access.time.sleep'):
            for _ in range(9):
                picked = self.access.select_key(keys)
                self.assertIsNotNone(picked)
                self.assertTrue(self.access.acquire(picked['key_id']))
                chosen.append(picked['key_id'])
        # 9 requests across 3 keys -> 3 calls per key in round-robin order
        self.assertEqual(['k1', 'k2', 'k3'] * 3, chosen)
        counts = price_history.get_api_calls_by_key_24h()
        self.assertEqual({'k1': 3, 'k2': 3, 'k3': 3}, counts)

        # Pause k2 on HTTP 429 -> remaining keys k1 and k3 continue alternating
        self.access.pause(900, key_id='k2')
        self.assertFalse(self.access.is_paused())
        self.assertTrue(self.access.is_key_paused('k2'))
        next_two = []
        with patch('ebay_access.time.sleep'):
            for _ in range(2):
                picked = self.access.select_key(keys)
                self.assertTrue(self.access.acquire(picked['key_id']))
                next_two.append(picked['key_id'])
        self.assertEqual(['k1', 'k3'], next_two)

    def test_old_single_key_usage_is_not_lost_when_a_second_key_is_added(self):
        price_history.record_api_call()  # legacy single-key calls were untagged
        keys = [{'key_id': 'primary'}, {'key_id': 'new'}]
        self.assertEqual('new', self.access.select_key(keys)['key_id'])

    def test_remaining_second_key_is_available_despite_legacy_first_key_quota(self):
        self.access.save({'remaining': 0, 'reset': 4_000_000_000,
                          'pause_until': 4_000_000_000,
                          'key_pauses': {'first': 4_000_000_000}})
        keys = [{'key_id': 'first'}, {'key_id': 'second'}]
        with patch.object(monitor, 'browse_access', self.access), \
             patch.object(monitor, '_configured_ebay_api_keys', return_value=keys):
            self.assertFalse(monitor._ebay_api_paused())
            self.assertEqual('second', self.access.select_key(keys)['key_id'])
            self.assertTrue(self.access.acquire('second'))
            self.assertFalse(self.access.acquire('first'))
            self.access.pause(60, key_id='second')
            self.assertLess(self.access.state()['key_pauses']['second'], 4_000_000_000)

    def test_all_paused_keys_do_not_fetch_an_oauth_token(self):
        keys = [{'key_id': 'first'}, {'key_id': 'second'}]
        for key in keys:
            self.access.pause(600, key_id=key['key_id'])
        with patch.object(monitor, 'browse_access', self.access), \
             patch.object(monitor, '_configured_ebay_api_keys', return_value=keys), \
             patch.object(monitor.urllib.request, 'urlopen') as request:
            self.assertEqual((None, 'api_rate_limit'), monitor._get_ebay_api_token())
            request.assert_not_called()

    def test_second_key_request_does_not_spend_first_keys_remaining_quota(self):
        self.access.save({'remaining': 5, 'reset': 4_000_000_000})
        keys = [{'key_id': 'first'}, {'key_id': 'second'}]
        self.access.select_key(keys)  # bind the pre-existing single-key quota
        self.assertTrue(self.access.acquire('second'))
        self.assertEqual(5, self.access.state()['remaining'])
        with patch('ebay_access.time.sleep'):
            self.assertTrue(self.access.acquire('first'))
        self.assertEqual(4, self.access.state()['remaining'])


if __name__ == '__main__':
    unittest.main()
