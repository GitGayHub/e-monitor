"""Persistent Browse quota and pacing shared by searches and item details.

Store in the existing checkpointed database; no credentials are persisted.
"""
import json
import sqlite3
import threading
import time
import os
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


class BrowseAccess:
    def __init__(self):
        self.lock = threading.RLock()
        self.last_request = 0.0

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

    def pause(self, retry_after=None):
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
            value["pause_until"] = now + delay
            self.save(value)

    def acquire(self):
        with self.lock:
            value = self.state()
            now = time.time()
            if now < value.get("pause_until", 0):
                return False
            if now < value.get("reset", 0) and value.get("remaining", 1) <= 0:
                return False
            wait = 0.5 - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            if now < value.get("reset", 0):
                value["remaining"] = max(0, value.get("remaining", 1) - 1)
                self.save(value)
            price_history.record_api_call()  # count attempts, including errors/details
            self.last_request = time.monotonic()
            return True

    def is_paused(self):
        """Inspect persisted quota without spending a request or changing state."""
        value = self.state()
        now = time.time()
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

    def normal_queue(self, searches, market):
        """Resume the next active search after a checkpoint or forced shutdown."""
        rows = [s for s in searches if s.get('enabled', True)]
        next_id = self.state().get('normal_next_search', {}).get(market)
        offset = next((i for i, s in enumerate(rows) if s.get('id') == next_id), 0)
        return rows[offset:] + rows[:offset]

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

    def finish_normal_candidates(self, search_id, context, market):
        with self.lock:
            state = self.state(); entries = state.get('normal_candidates', {})
            key = str(search_id)+'|'+market
            if entries.get(key, {}).get('context') == context:
                entries.pop(key, None); self.save(state)


access = BrowseAccess()
