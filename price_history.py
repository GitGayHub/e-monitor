import os
import sqlite3
import threading
import statistics
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "price_history.db")
_DB_LOCK = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


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


def record_snapshot(search_id, sofort_prices, pv_prices, auction_prices, total_results=0):
    init_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    min_s = min(sofort_prices) if sofort_prices else None
    min_p = min(pv_prices) if pv_prices else None
    min_a = min(auction_prices) if auction_prices else None
    med_s = statistics.median(sofort_prices) if sofort_prices else None
    med_a = statistics.median(auction_prices) if auction_prices else None

    with _DB_LOCK:
        with _connect() as conn:
            # Add median_auction column if not exists
            try:
                conn.execute("ALTER TABLE price_snapshots ADD COLUMN median_auction REAL")
            except Exception:
                pass
            conn.execute(
                """INSERT INTO price_snapshots
                   (search_id, recorded_at, min_sofort, min_pv, min_auction, median_sofort, median_auction, total_results)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (search_id, now, min_s, min_p, min_a, med_s, med_a, total_results),
            )
    cleanup_old_data()


def cleanup_old_data():
    cutoff_snapshots = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
    cutoff_sellers = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    with _DB_LOCK:
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM price_snapshots WHERE recorded_at < ?", (cutoff_snapshots,))
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


def get_median_7d(search_id):
    init_db()
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT median_sofort FROM price_snapshots WHERE search_id = ? AND recorded_at >= ? AND median_sofort IS NOT NULL",
                (search_id, cutoff),
            ).fetchall()
    if not rows:
        return None
    values = [r["median_sofort"] for r in rows]
    return statistics.median(values)


def get_stats_7d(search_id):
    init_db()
    now = datetime.now()
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M")
    with _DB_LOCK:
        with _connect() as conn:
            rows = conn.execute(
                """SELECT recorded_at, min_sofort, min_pv, min_auction, median_sofort
                   FROM price_snapshots
                   WHERE search_id = ? AND recorded_at >= ?
                   ORDER BY recorded_at ASC""",
                (search_id, cutoff),
            ).fetchall()
            # Try to get auction medians (column may not exist in old DBs)
            try:
                auc_rows = conn.execute(
                    """SELECT median_auction FROM price_snapshots
                       WHERE search_id = ? AND recorded_at >= ? AND median_auction IS NOT NULL""",
                    (search_id, cutoff),
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
    }


def get_trend(search_id):
    init_db()
    now = datetime.now()
    cutoff_30d = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M")
    with _DB_LOCK:
        with _connect() as conn:
            first = conn.execute(
                "SELECT min_sofort FROM price_snapshots WHERE search_id = ? AND recorded_at >= ? AND min_sofort IS NOT NULL ORDER BY recorded_at ASC LIMIT 1",
                (search_id, cutoff_30d),
            ).fetchone()
            last = conn.execute(
                "SELECT min_sofort FROM price_snapshots WHERE search_id = ? AND min_sofort IS NOT NULL ORDER BY recorded_at DESC LIMIT 1",
                (search_id,),
            ).fetchone()
    if not first or not last:
        return None
    return {"price_30d_ago": first["min_sofort"], "price_now": last["min_sofort"]}


def is_outlier(price, search_id):
    """Detect suspiciously low prices that are likely errors or scams.
    
    Uses a dynamic threshold based on the 7-day median:
    - If price < 40% of median → outlier (likely scam/error/wrong item)
    - Requires at least 3 snapshots to have confidence in the median
    """
    median = get_median_7d(search_id)
    if median is None or median == 0:
        return False
    # Need enough data points for a reliable median
    stats = get_stats_7d(search_id)
    if not stats or stats.get("snapshots", 0) < 3:
        return False
    return price < median * 0.4
