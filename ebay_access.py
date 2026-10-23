"""Persistent Browse quota and pacing shared by searches and item details.

Store in the existing checkpointed database; no credentials are persisted.
"""
import json
import sqlite3
import threading
import time
import os
import math
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import price_history


class MonitorPassBudget:
    """Cooperative runner deadline; never cancels an in-flight Telegram send."""
    current = ContextVar('emonitor_pass_budget', default=None)

    def __init__(self, seconds, clock=None):
        self.clock = clock or time.monotonic
        self.seconds = max(0, float(seconds))
        self.deadline = self.clock() + self.seconds
        # Retain the checkpoint reserve and, for normal sized passes, a small
        # window to deliver candidates that have already been fully checked.
        self.validation_reserve = 30 + min(15, max(0, self.seconds - 40))

    @classmethod
    def from_environment(cls):
        value = os.environ.get('EMONITOR_PASS_SECONDS')
        return cls(value) if value is not None else None

    def should_yield(self, reserve=0):
        return self.clock() + reserve >= self.deadline

    @classmethod
    def exhausted(cls, reserve=0):
        budget = cls.current.get()
        return budget is not None and budget.should_yield(reserve)

    @classmethod
    @contextmanager
    def slice(cls, seconds, reserve=0):
        """A synchronous child deadline propagated into awaited worker threads."""
        parent = cls.current.get()
        if parent is None:
            yield None
            return
        child = cls(min(seconds, max(0, parent.deadline-parent.clock()-reserve)),clock=parent.clock)
        token = cls.current.set(child)
        try:
            yield child
        finally:
            cls.current.reset(token)

    @classmethod
    def timeout(cls, seconds):
        """Clip each eBay I/O stage; no cancellation of Telegram or worker threads."""
        budget = cls.current.get()
        if budget is None:
            return seconds
        remaining = max(.001,budget.deadline-budget.clock())
        if isinstance(seconds,tuple):
            return tuple(min(value,remaining/len(seconds)) for value in seconds)
        return min(seconds,remaining)

    @classmethod
    def milliseconds(cls, value):
        return max(1,int(cls.timeout(value/1000)*1000))


# The last place in the app's priority order is checked this many times less
# often than the first. Android shows the same estimate (SearchPriority.kt).
PRIORITY_MAX_WEIGHT = 8.0


def priority_weights(searches):
    """{search id: weight >= 1} from the app's places; {} keeps plain rotation."""
    ranks = sorted({int(s.get('priority') or 0) for s in searches if int(s.get('priority') or 0) > 0})
    if not ranks:
        return {}
    place = {rank: index for index, rank in enumerate(ranks)}
    span = max(1, len(ranks)-1)
    # An unranked search (added on an old app) waits as long as the last place.
    return {str(s['id']): 1+(PRIORITY_MAX_WEIGHT-1)*(place[int(s.get('priority') or 0)]/span if int(s.get('priority') or 0) > 0 else 1)
            for s in searches}


def priority_intervals(searches, searches_per_minute, pass_minutes):
    """Expected minutes between checks; never faster than one pass."""
    weights = priority_weights(searches) or {str(s['id']): 1.0 for s in searches}
    if not weights or not searches_per_minute:
        return {}
    scale = sum(1/w for w in weights.values())/searches_per_minute
    return {search_id: round(max(pass_minutes, w*scale), 1) for search_id, w in weights.items()}


class BrowseAccess:
    def __init__(self):
        self.lock = threading.RLock()
        self.last_request = 0.0
        self.last_key_id = ""

    def state(self):
        conn = sqlite3.connect(price_history.DB_PATH)
        try:
            with conn:
                conn.execute("CREATE TABLE IF NOT EXISTS ebay_access (id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
                row = conn.execute("SELECT state FROM ebay_access WHERE id=1").fetchone()
                return json.loads(row[0]) if row else {}
        finally:
            conn.close()

    def save(self, value):
        conn = sqlite3.connect(price_history.DB_PATH)
        try:
            with conn:
                conn.execute("CREATE TABLE IF NOT EXISTS ebay_access (id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
                conn.execute("INSERT OR REPLACE INTO ebay_access VALUES (1,?)", (json.dumps(value),))
        finally:
            conn.close()

    def update_quota(self, payload):
        for group in payload.get("rateLimits", []):
            for resource in group.get("resources", []):
                if resource.get("name") != "buy.browse":
                    continue
                rates = resource.get("rates", [])
                if not rates:
                    continue
                rate = min(rates, key=lambda r: int(r.get("remaining", 0)))
                reset = datetime.fromisoformat(rate["reset"].replace("Z", "+00:00")).timestamp()
                with self.lock:
                    value = self.state()
                    value.update(remaining=int(rate["remaining"]), limit=int(rate["limit"]),
                                 reset=reset, checked=time.time())
                    self.save(value)
                return True
        return False

    def pause(self, retry_after=None, key_id=None):
        now = time.time()
        try:
            delay = max(1, float(retry_after))
        except (TypeError, ValueError):
            try:
                delay = max(1, parsedate_to_datetime(retry_after).timestamp() - now)
            except (TypeError, ValueError, AttributeError):
                delay = 900
        with self.lock:
            value = self.state()
            if value.get("remaining", 1) <= 0:
                delay = max(delay, value.get("reset", now) - now)
            if key_id:
                pauses = {k: v for k, v in value.get("key_pauses", {}).items() if v > now}
                pauses[str(key_id)] = now + delay
                value["key_pauses"] = pauses
            else:
                value["pause_until"] = now + delay
            self.save(value)

    def is_key_paused(self, key_id=None, value=None, now=None):
        value = value if value is not None else self.state()
        now = time.time() if now is None else now
        if now < value.get("pause_until", 0):
            return True
        if key_id and now < value.get("key_pauses", {}).get(str(key_id), 0):
            return True
        if not key_id and now < value.get("reset", 0) and value.get("remaining", 1) <= 0:
            return True
        return False

    def select_key(self, keys):
        """Pick the next active API key in round-robin / least-used order so no single key is drained first."""
        if not keys:
            return None
        with self.lock:
            value = self.state()
            now = time.time()
            available = [k for k in keys if not self.is_key_paused(k.get("key_id"), value=value, now=now)]
            if not available:
                return None
            if len(available) == 1:
                chosen = available[0]
                self.last_key_id = str(chosen.get("key_id") or "")
                return chosen
            counts = price_history.get_api_calls_by_key_24h()
            untagged = counts.get("", 0)
            primary_id = str(keys[0].get("key_id") or "")
            last_id = self.last_key_id or str(value.get("last_key_id") or "")
            ids = [str(k.get("key_id") or "") for k in available]
            start_idx = (ids.index(last_id) + 1) % len(available) if last_id in ids else 0

            def key_score(idx):
                k = available[idx]
                kid = str(k.get("key_id") or "")
                used = counts.get(kid, 0) + (untagged if kid == primary_id and len(keys) == 1 else 0)
                rr_order = (idx - start_idx) % len(available)
                return (used, rr_order)

            best_idx = min(range(len(available)), key=key_score)
            chosen = available[best_idx]
            chosen_id = str(chosen.get("key_id") or "")
            self.last_key_id = chosen_id
            if value.get("last_key_id") != chosen_id:
                value["last_key_id"] = chosen_id
                self.save(value)
            return chosen

    def acquire(self, key_id=""):
        with self.lock:
            value = self.state()
            now = time.time()
            if self.is_key_paused(key_id or None, value=value, now=now):
                return False
            if not key_id and now < value.get("reset", 0) and value.get("remaining", 1) <= 0:
                return False
            wait = 0.5 - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            if now < value.get("reset", 0):
                value["remaining"] = max(0, value.get("remaining", 1) - 1)
                self.save(value)
            price_history.record_api_call(key_id=key_id)  # count attempts per key, including errors/details
            self.last_request = time.monotonic()
            return True

    def is_paused(self, keys=None):
        """Inspect persisted quota without spending a request or changing state."""
        value = self.state()
        now = time.time()
        if keys:
            return all(self.is_key_paused(k.get("key_id"), value=value, now=now) for k in keys)
        return now < value.get("pause_until", 0) or (
            now < value.get("reset", 0) and value.get("remaining", 1) <= 0
        )

    def record_html_attempt(self, search_id, market):
        """Give failed HTML searches a cooldown without starving later products."""
        with self.lock:
            value = self.state()
            now = time.time()
            attempts = {key: stamp for key, stamp in value.get("html_attempts", {}).items() if now-stamp < 86400}
            attempts[str(search_id)+"|"+market] = now
            value["html_attempts"] = attempts
            self.save(value)

    def interval(self, searches):
        value = self.state()
        now = time.time()
        if value.get("reset", 0) > now:
            # Reserve 20% for description checks and manual phone requests.
            available = max(1, value.get("remaining", 0) * .8)
            return max(900, searches * (value["reset"] - now) / available)
        return 900

    def normal_queue(self, searches, market, now=None):
        """Resume the next active search after a checkpoint or forced shutdown."""
        rows = [s for s in searches if s.get('enabled', True)]
        state = self.state()
        weights = priority_weights(rows)
        if weights:
            # Owner order from the app: the most overdue search relative to its
            # place goes first, so a higher place is checked more often and the
            # last one still runs at least every PRIORITY_MAX_WEIGHT intervals.
            now = time.time() if now is None else now
            attempts = state.get('html_attempts', {})
            def overdue(row):
                stamp = attempts.get(str(row['id'])+'|'+market)
                age = now-stamp if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) else math.inf
                return age/weights[str(row['id'])]
            rotated = sorted(rows, key=lambda row: (-overdue(row), weights[str(row['id'])]))
        else:
            next_id = state.get('normal_next_search', {}).get(market)
            offset = next((i for i, s in enumerate(rows) if s.get('id') == next_id), 0)
            rotated = rows[offset:] + rows[:offset]
        # A page received just before the runner deadline must not wait for a
        # whole catalogue rotation before its first description is checked.
        # Only search IDs are retained: the next attempt fetches fresh data.
        pending = state.get('normal_validation_resume', {})
        priority = sorted((s for s in rows if str(s['id'])+'|'+market in pending),
                          key=lambda s: pending[str(s['id'])+'|'+market])
        urgent = {s['id'] for s in priority}
        return priority + [s for s in rotated if s['id'] not in urgent]

    def defer_normal_validation(self, search_id, market):
        with self.lock:
            state = self.state(); now = time.time()
            pending = {key:stamp for key,stamp in state.get('normal_validation_resume', {}).items()
                       if now-stamp < 86400}
            pending.setdefault(str(search_id)+'|'+market, now)
            state['normal_validation_resume'] = dict(sorted(pending.items(),key=lambda x:x[1])[-128:])
            self.save(state)

    def finish_normal_validation(self, search_id, market):
        with self.lock:
            state = self.state(); pending = state.get('normal_validation_resume', {})
            if pending.pop(str(search_id)+'|'+market, None) is not None:
                state['normal_validation_resume'] = pending
                self.save(state)

    def search_coverage(self, searches, market, now=None):
        """Freshness of attempts, never a claim of successful search/delivery."""
        now = time.time() if now is None else now
        attempts = self.state().get('html_attempts', {})
        active = {str(row['id']) for row in searches if row.get('enabled', True)}
        ages = []
        for search_id in active:
            stamp = attempts.get(search_id+'|'+market)
            if isinstance(stamp, bool) or not isinstance(stamp, (float, int)):
                continue
            if not math.isfinite(stamp) or stamp <= 0 or stamp > now + 5:
                continue
            ages.append(max(0, now-stamp))
        oldest = max(ages, default=None)
        return dict(activeSearches=len(active), attemptedSearches=len(ages),
                    within15Minutes=sum(age <= 900 for age in ages),
                    neverAttempted=len(active)-len(ages),
                    oldestAttemptAt=datetime.fromtimestamp(now-oldest, timezone.utc).isoformat(timespec='seconds') if oldest is not None else None,
                    oldestAttemptAgeSeconds=int(oldest) if oldest is not None else None)

    def note_normal_discovery(self, items, search_id, market):
        """First observed time is evidence, never an inferred listing start."""
        now = time.time()
        with self.lock:
            state = self.state()
            observed = {k:v for k,v in state.get('normal_observed', {}).items() if now-v < 7*86400}
            for item in items:
                key = str(search_id)+'|'+market+'|'+str(item.get('item_id'))
                item['_first_discovered_at'] = observed.setdefault(key,now)
            state['normal_observed'] = dict(sorted(observed.items(),key=lambda x:x[1])[-10000:])
            self.save(state)
        return items

    def start_normal_search(self, search_id, next_id, market):
        # Save before network I/O: a hung request must not monopolize every job.
        # This only rotates the queue. It does not mark any item sent or checked.
        with self.lock:
            state = self.state()
            state.setdefault('normal_next_search', {})[market] = next_id
            self.save(state)

    def normal_alias_offset(self, search_id, context, market, count):
        """Resume query/format attempts, never cached listings or seller text."""
        saved = self.state().get('normal_aliases', {}).get(str(search_id)+'|'+market, {})
        value = saved.get('next')
        if saved.get('context') != context or isinstance(value, bool) or not isinstance(value, int):
            return 0
        return value if 0 <= value < count else 0

    def start_normal_alias(self, search_id, context, market, next_index):
        """Checkpoint before I/O so a failed first spelling cannot starve others."""
        with self.lock:
            state = self.state(); now = time.time()
            entries = {key:value for key,value in state.get('normal_aliases', {}).items()
                       if now-value.get('updated', 0) < 86400}
            entries[str(search_id)+'|'+market] = {'context':context,'next':next_index,'updated':now}
            # IDs, a context hash, and an index only. Do not persist queries,
            # prices or an old success as proof of a complete current union.
            state['normal_aliases'] = dict(sorted(entries.items(),key=lambda row:row[1]['updated'])[-256:])
            self.save(state)

    def normal_candidate_order(self, search_id, context, market, item_ids):
        """Only reorder fresh IDs; no old price, description or verdict is reused."""
        ids = list(dict.fromkeys(str(value) for value in item_ids))
        saved = self.state().get('normal_candidates', {}).get(str(search_id)+'|'+market, {})
        if saved.get('context') != context or not ids:
            return ids
        previous = set(saved.get('ids', []))
        new = [value for value in ids if value not in previous]
        known = [value for value in ids if value in previous]
        old_order = saved.get('ids', [])
        next_id = saved.get('next')
        # If the exact next item disappeared, use the following surviving item.
        if next_id not in known and next_id in old_order:
            at = old_order.index(next_id)
            next_id = next((value for value in old_order[at:]+old_order[:at] if value in known), None)
        offset = known.index(next_id) if next_id in known else 0
        return new + known[offset:] + known[:offset]

    def start_normal_candidate(self, search_id, context, market, ids, next_id):
        """Checkpoint before I/O so a hung description cannot starve the tail."""
        with self.lock:
            state = self.state()
            now = time.time()
            entries = {key:value for key,value in state.get('normal_candidates', {}).items()
                       if now-value.get('updated', 0) < 86400}
            key = str(search_id)+'|'+market
            entries[key] = {'context':context,'ids':list(dict.fromkeys(str(value) for value in ids)),
                            'next':str(next_id),'updated':now}
            # Bound abandoned searches without storing any production secrets.
            state['normal_candidates'] = dict(sorted(entries.items(),key=lambda row:row[1]['updated'])[-128:])
            self.save(state)

    def normal_candidate_facts(self, search_id, context, market):
        """Per-ID timing facts for live ordering; never prices, sellers or text."""
        saved = self.state().get('normal_candidate_facts', {}).get(str(search_id)+'|'+market, {})
        return dict(saved.get('ids', {})) if saved.get('context') == context else {}

    def note_normal_candidate_facts(self, search_id, context, market, updates, now):
        """Merge ready/checked/end timestamps; a None value removes that fact.

        Losing a fact only promotes an ID back to an unchecked tier, so the
        bound can never starve a lot; it can only cost one extra description.
        """
        with self.lock:
            state = self.state()
            key = str(search_id)+'|'+market
            entries = {k:v for k,v in state.get('normal_candidate_facts', {}).items()
                       if now-v.get('updated', 0) < 2*86400}
            entry = entries.get(key, {})
            ids = dict(entry.get('ids', {})) if entry.get('context') == context else {}
            for item_id, fact in updates.items():
                merged = {k:v for k,v in {**ids.get(str(item_id), {}), **fact}.items() if v is not None}
                merged['updated'] = now
                ids[str(item_id)] = merged
            ids = {k:v for k,v in ids.items() if now-v.get('updated', 0) < 2*86400}
            entries[key] = {'context':context,'updated':now,
                            'ids':dict(sorted(ids.items(),key=lambda row:row[1]['updated'])[-160:])}
            state['normal_candidate_facts'] = dict(sorted(entries.items(),key=lambda row:row[1]['updated'])[-128:])
            self.save(state)

    def finish_normal_candidates(self, search_id, context, market):
        with self.lock:
            state = self.state(); entries = state.get('normal_candidates', {})
            key = str(search_id)+'|'+market
            if entries.get(key, {}).get('context') == context:
                entries.pop(key, None); self.save(state)


access = BrowseAccess()
