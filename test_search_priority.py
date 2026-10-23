"""Owner priority order from the app decides how often each search is checked."""
import collections
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import price_history
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


if __name__ == '__main__':
    unittest.main()
