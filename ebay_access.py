"""Persistent Browse quota and pacing shared by searches and item details.

Store in the existing checkpointed database; no credentials are persisted.
"""
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import price_history


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

    def interval(self, searches):
        value = self.state()
        now = time.time()
        if value.get("reset", 0) > now:
            # Reserve 20% for description checks and manual phone requests.
            available = max(1, value.get("remaining", 0) * .8)
            return max(900, searches * (value["reset"] - now) / available)
        return 900


access = BrowseAccess()
