import os
import sqlite3
import threading
import statistics
from contextlib import contextmanager
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "price_history.db")
HISTORY_VERSION = 54  # Revalidate observations after the touchpad defect rule.
_DB_LOCK = threading.Lock()


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    with _DB_LOCK:
        with _connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    search_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    min_sofort REAL,
                    min_pv REAL,
                    min_auction REAL,
                    median_sofort REAL,
                    total_results INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snap_search ON price_snapshots(search_id, recorded_at DESC)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seller_prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    search_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    seller_name TEXT NOT NULL,
                    price REAL NOT NULL,
                    item_id TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_seller_prices ON seller_prices(seller_name)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS search_runs (
                    search_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    last_run_at TEXT NOT NULL,
                    PRIMARY KEY (search_id, market)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_calls_log (
                    called_at TEXT NOT NULL,
                    key_id TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_api_calls_log_time ON api_calls_log(called_at)"
            )
            api_cols = {r[1] for r in conn.execute("PRAGMA table_info(api_calls_log)")}
            if "key_id" not in api_cols:
                conn.execute("ALTER TABLE api_calls_log ADD COLUMN key_id TEXT NOT NULL DEFAULT ''")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(price_snapshots)")}
            for name, definition in (("median_auction", "REAL"),
                                     ("history_version", "INTEGER NOT NULL DEFAULT 0"),
                                     ("validation_complete", "INTEGER NOT NULL DEFAULT 0"),
                                     ("filter_signature", "TEXT NOT NULL DEFAULT ''")):
                if name not in columns:
                    conn.execute(f"ALTER TABLE price_snapshots ADD COLUMN {name} {definition}")



def record_snapshot(search_id, sofort_prices, pv_prices, auction_prices, total_results=0,
                    *, verified=False, validation_complete=False, filter_signature=""):
    init_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    min_s = min(sofort_prices) if sofort_prices else None
    min_p = min(pv_prices) if pv_prices else None
    min_a = min(auction_prices) if auction_prices else None
    med_s = statistics.median(sofort_prices) if sofort_prices else None
    med_a = statistics.median(auction_prices) if auction_prices else None

    with _DB_LOCK:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO price_snapshots
                   (search_id, recorded_at, min_sofort, min_pv, min_auction, median_sofort, median_auction, total_results,
                    history_version, validation_complete, filter_signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (search_id, now, min_s, min_p, min_a, med_s, med_a, total_results,
                 HISTORY_VERSION if verified else 0, bool(validation_complete and verified), filter_signature),
            )
    cleanup_old_data()


def cleanup_old_data():
    cutoff_snapshots = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
    cutoff_sellers = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    with _DB_LOCK:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM price_snapshots WHERE recorded_at < ? AND history_version > 0", (cutoff_snapshots,))
            conn.execute("DELETE FROM seller_prices WHERE recorded_at < ?", (cutoff_sellers,))
            conn.commit()
            
            conn.isolation_level = None
            conn.execute("VACUUM")
            conn.close()
        except Exception:
            pass


def record_seller_price(search_id, seller_name, price, item_id=None):
    init_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with _DB_LOCK:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO seller_prices (search_id, recorded_at, seller_name, price, item_id) VALUES (?,?,?,?,?)",
                (search_id, now, seller_name, price, item_id),
            )


def delete_seller_data(seller_name):
    init_db()
    with _DB_LOCK:
        with _connect() as conn:
            conn.execute("DELETE FROM seller_prices WHERE seller_name = ?", (seller_name,))


def get_median_7d(search_id, filter_signature=None):
    stats = get_stats_7d(search_id, filter_signature)
    return stats["median"] if stats else None


def get_stats_7d(search_id, filter_signature=None):
    init_db()
    now = datetime.now()
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                """SELECT recorded_at, min_sofort, min_pv, min_auction, median_sofort
                   FROM price_snapshots
                   WHERE search_id = ? AND recorded_at >= ? AND history_version = ?
                     AND validation_complete = 1 AND (? IS NULL OR filter_signature = ?)
                   ORDER BY recorded_at ASC""",
                (search_id, cutoff, HISTORY_VERSION, filter_signature, filter_signature),
            ).fetchall()
            # Try to get auction medians (column may not exist in old DBs)
            try:
                auc_rows = conn.execute(
                    """SELECT median_auction FROM price_snapshots
                       WHERE search_id = ? AND recorded_at >= ? AND median_auction IS NOT NULL
                         AND history_version = ? AND validation_complete = 1 AND (? IS NULL OR filter_signature = ?)""",
                    (search_id, cutoff, HISTORY_VERSION, filter_signature, filter_signature),
                ).fetchall()
            except Exception:
                auc_rows = []
    if not rows:
        return None
    first_date = rows[0]["recorded_at"][:10]
    last_date = rows[-1]["recorded_at"][:10]
    days = (now - datetime.strptime(first_date, "%Y-%m-%d")).days + 1
    medians = [r["median_sofort"] for r in rows if r["median_sofort"] is not None]
    median_val = statistics.median(medians) if medians else None
    min_sofort_all = [r["min_sofort"] for r in rows if r["min_sofort"] is not None]
    min_sofort_val = min(min_sofort_all) if min_sofort_all else None
    min_auction_all = [r["min_auction"] for r in rows if r["min_auction"] is not None]
    min_auction_val = min(min_auction_all) if min_auction_all else None
    auc_medians = [r["median_auction"] for r in auc_rows] if auc_rows else []
    median_auction_val = statistics.median(auc_medians) if auc_medians else None
    return {
        "median": median_val,
        "min_sofort": min_sofort_val,
        "min_auction": min_auction_val,
        "median_auction": median_auction_val,
        "first_date": first_date,
        "last_date": last_date,
        "days": min(days, 7),
        "snapshots": len(rows),
        "purchase_snapshots": len(medians),
    }


def get_trend(search_id, filter_signature=None):
    init_db()
    now = datetime.now()
    cutoff_30d = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
    with _DB_LOCK:
        with _connect() as conn:
            first = conn.execute(
                "SELECT min_sofort FROM price_snapshots WHERE search_id = ? AND recorded_at >= ? AND min_sofort IS NOT NULL AND history_version = ? AND validation_complete = 1 AND (? IS NULL OR filter_signature = ?) ORDER BY recorded_at ASC LIMIT 1",
                (search_id, cutoff_30d, HISTORY_VERSION, filter_signature, filter_signature),
            ).fetchone()
            last = conn.execute(
                "SELECT min_sofort FROM price_snapshots WHERE search_id = ? AND min_sofort IS NOT NULL AND history_version = ? AND validation_complete = 1 AND (? IS NULL OR filter_signature = ?) ORDER BY recorded_at DESC LIMIT 1",
                (search_id, HISTORY_VERSION, filter_signature, filter_signature),
            ).fetchone()
    if not first or not last:
        return None
    return {"price_30d_ago": first["min_sofort"], "price_now": last["min_sofort"]}


def is_outlier(price, search_id, filter_signature=None):
    """Detect suspiciously low prices that are likely errors or scams.
    
    Uses a dynamic threshold based on the 7-day median:
    - If price < 40% of median Р Р†РІР‚В РІР‚в„ў outlier (likely scam/error/wrong item)
    - Requires at least 3 snapshots to have confidence in the median
    """
    median = get_median_7d(search_id, filter_signature)
    if median is None or median == 0:
        return False
    # Need enough data points for a reliable median
    stats = get_stats_7d(search_id, filter_signature)
    if not stats or stats.get("purchase_snapshots", 0) < 3:
        return False
    return price < median * 0.4


def get_last_run(search_id, market):
    init_db()
    with _DB_LOCK:
        with _connect() as conn:
            row = conn.execute(
                "SELECT last_run_at FROM search_runs WHERE search_id = ? AND market = ?",
                (search_id, market)
            ).fetchone()
            if row:
                return row["last_run_at"]
            return None


def record_search_run(search_id, market):
    init_db()
    now = datetime.now().isoformat()
    with _DB_LOCK:
        with _connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO search_runs (search_id, market, last_run_at) VALUES (?, ?, ?)",
                (search_id, market, now)
            )


def record_api_call(key_id=""):
    init_db()
    now = datetime.now()
    now_iso = now.isoformat()
    cutoff = (now - timedelta(hours=24)).isoformat()
    with _DB_LOCK:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO api_calls_log (called_at, key_id) VALUES (?, ?)",
                (now_iso, str(key_id or "")),
            )
            conn.execute("DELETE FROM api_calls_log WHERE called_at < ?", (cutoff,))


def get_api_calls_count_24h(key_id=None, include_untagged=False):
    init_db()
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    with _DB_LOCK:
        with _connect() as conn:
            if key_id is None:
                row = conn.execute(
                    "SELECT COUNT(*) FROM api_calls_log WHERE called_at >= ?",
                    (cutoff,)
                ).fetchone()
            elif include_untagged:
                row = conn.execute(
                    "SELECT COUNT(*) FROM api_calls_log WHERE called_at >= ? AND (key_id = ? OR key_id = '')",
                    (cutoff, str(key_id)),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM api_calls_log WHERE called_at >= ? AND key_id = ?",
                    (cutoff, str(key_id)),
                ).fetchone()
            return row[0] if row else 0


def get_api_calls_by_key_24h():
    init_db()
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT key_id, COUNT(*) AS cnt FROM api_calls_log WHERE called_at >= ? GROUP BY key_id",
                (cutoff,),
            ).fetchall()
            return {str(r["key_id"] or ""): int(r["cnt"]) for r in rows}


