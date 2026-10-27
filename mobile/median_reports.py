"""Opt-in trends of verified purchase quotes, independent of deal notifications.

Observations are unique by listing/day. A partially fetched search may contribute
fully verified listings, but the report never claims to represent the whole market.
The delivery claim is persisted on GitHub before Telegram I/O; uncertain sends
are held, never blindly retried.
"""
import base64
import hashlib
import html
import io
import json
import math
import os
import statistics
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import price_history

STATE_PATH = Path(__file__).with_name('median_delivery.json')
MEDIAN_VERSION = 1
DAY = 86400
MIN_LISTINGS = 5


def preferences(settings):
    raw = settings.get('median_products', [])
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list) or any(not isinstance(x, str) for x in raw):
        raise ValueError('median_products must be an array of search IDs')
    value = settings.get('median_interval_days', 7)
    if isinstance(value, bool) or str(value) != str(int(value)) or not 1 <= int(value) <= 30:
        raise ValueError('median_interval_days must be 1–30')
    return set(raw), int(value)


def init_db():
    price_history.init_db()
    with price_history._DB_LOCK, price_history._connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS median_observations (
            search_id TEXT NOT NULL, signature TEXT NOT NULL, item_id TEXT NOT NULL,
            day TEXT NOT NULL, observed_at REAL NOT NULL, total REAL NOT NULL,
            history_version INTEGER NOT NULL, median_version INTEGER NOT NULL,
            PRIMARY KEY(search_id,signature,item_id,day,history_version,median_version))''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_median_observed ON median_observations(observed_at)')
        columns = {row[1] for row in db.execute('PRAGMA table_info(median_observations)')}
        for name in ('condition_group', 'title'):
            if name not in columns:
                db.execute(f'ALTER TABLE median_observations ADD COLUMN {name} TEXT')


def condition_group(value):
    """Only classify explicitly labelled conditions; old/unknown rows remain unknown."""
    text = str(value or '').strip().casefold()
    if text in ('new', 'neu', 'neu: sonstige', 'neu: sonstige (siehe artikelbeschreibung)', '1000', '1500'):
        return 'new'
    if text in ('used', 'gebraucht', '3000') or text.startswith('gebraucht ') or text.startswith('gebraucht:'):
        return 'used'
    return 'unknown'


def record_verified(search_id, signature, rows, now=None):
    """Only the post-description, post-price, structurally re-filtered projection."""
    now = time.time() if now is None else now
    day = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    values = []
    for row in rows:
        if (row.get('_details_status') != 'verified' or not row.get('_details_verified_at')
                or not row.get('buy_now') or row.get('import_estimated')):
            continue
        # A hybrid without a known BIN side is never represented by its bid.
        value = row.get('bin_total_price') if row.get('auction') else row.get('total_price')
        if value is None and not row.get('auction'):
            value = row.get('bin_total_price')
        if isinstance(value, bool):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or value <= 0 or not row.get('item_id'):
            continue
        values.append((str(search_id), signature, str(row['item_id']), day, now, value,
                       price_history.HISTORY_VERSION, MEDIAN_VERSION,
                       condition_group(row.get('condition')), str(row.get('title') or '')[:120]))
    if not values:
        return 0
    init_db()
    with price_history._DB_LOCK, price_history._connect() as db:
        db.executemany('''INSERT INTO median_observations
            (search_id,signature,item_id,day,observed_at,total,history_version,median_version,condition_group,title)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(search_id,signature,item_id,day,history_version,median_version)
            DO UPDATE SET observed_at=excluded.observed_at, total=excluded.total,
                condition_group=excluded.condition_group, title=excluded.title
            WHERE excluded.observed_at >= median_observations.observed_at''', values)
        db.execute('DELETE FROM median_observations WHERE observed_at < ?', (now - 60 * DAY,))
    return len({row[2] for row in values})


def robust_median(values):
    values = [float(x) for x in values if not isinstance(x, bool) and math.isfinite(x) and x > 0]
    if len(values) < MIN_LISTINGS:
        return dict(median=None, count=len(values), excluded=0)
    center = statistics.median(values)
    mad = statistics.median(abs(x - center) for x in values)
    # MAD alone is zero for identical stock prices. Keep a broad 25% floor:
    # small market moves stay visible; a stray €100 case among €1000 phones does not.
    radius = max(center * .25, 3.5 * 1.4826 * mad)
    kept = [x for x in values if abs(x - center) <= radius]
    return dict(median=statistics.median(kept) if len(kept) >= MIN_LISTINGS else None,
                count=len(kept), excluded=len(values) - len(kept))


def _trend_rows(signatures, now):
    init_db()
    rows = []
    with price_history._DB_LOCK, price_history._connect() as db:
        for search_id, signature in signatures.items():
            rows.extend(db.execute('''SELECT item_id, observed_at, total, condition_group, title FROM median_observations
                WHERE search_id=? AND signature=? AND history_version=? AND median_version=?
                  AND observed_at>=? AND observed_at<=?''',
                (search_id, signature, price_history.HISTORY_VERSION, MEDIAN_VERSION, now-60*DAY, now)).fetchall())
    return sorted(rows, key=lambda row: row['observed_at'])


def trend(signatures, now=None, condition=None, window_days=7, include_items=False, _rows=None):
    now = time.time() if now is None else now
    rows = _trend_rows(signatures, now) if _rows is None else _rows
    def window(end, with_items=False):
        # The same listing in several aliases/formats and 200 repeated sweeps
        # still gets one vote, using its most recent verified quote in the window.
        latest = {}
        for row in rows:
            if end-window_days*DAY < row['observed_at'] <= end:
                latest[row['item_id']] = row
        if with_items and condition is not None:
            condition_excluded_unknown = sum(row['condition_group'] not in ('used', 'new') for row in latest.values())
            condition_excluded_other = sum(row['condition_group'] in ('used', 'new') and row['condition_group'] != condition
                                           for row in latest.values())
        if condition is not None:
            latest = {key: row for key, row in latest.items() if row['condition_group'] == condition}
        result = robust_median(row['total'] for row in latest.values())
        if with_items:
            if condition is not None:
                result['conditionExcludedUnknown'] = condition_excluded_unknown
                result['conditionExcludedOther'] = condition_excluded_other
            prices = [row['total'] for row in latest.values()]
            if len(prices) >= MIN_LISTINGS:
                center = statistics.median(prices)
                mad = statistics.median(abs(x-center) for x in prices)
                radius = max(center*.25, 3.5*1.4826*mad)
                kept = [row for row in latest.values() if abs(row['total']-center) <= radius]
            else:
                kept = list(latest.values())
            result['items'] = [dict(itemId=row['item_id'], title=row['title'] or '', price=row['total'],
                                    observedAt=datetime.fromtimestamp(row['observed_at'],timezone.utc).isoformat(timespec='seconds'),
                                    condition=row['condition_group'] or 'unknown')
                               for row in sorted(kept,key=lambda r:r['observed_at'],reverse=True)[:10]]
            result['itemsTruncated'] = len(kept) > 10
        return result
    today = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    points = []
    for offset in range(29, -1, -1):
        day = today - timedelta(days=offset)
        end = min(now, (day + timedelta(days=1)).timestamp() - .001)
        point = window(end)
        point.pop('items', None); point.pop('itemsTruncated', None)
        points.append(dict(day=day.date().isoformat(), **point))
    return dict(**window(now, include_items), points=points, windowDays=window_days, minimum=MIN_LISTINGS)


def groups(config, signature_for, all_products=False):
    selected, interval = preferences(config.get('settings', {}))
    grouped = {}
    for search in config.get('searches', []):
        if not all_products and search.get('id') not in selected:
            continue
        f = search.get('filters', {})
        key = json.dumps([search.get('query', '').strip().casefold(),
            [f.get(k) for k in ('category','condition','seller_type','location','plz_center','max_distance_km')],
            [search.get(k, []) for k in ('include_words','exclude_words','exclude_sellers')]], sort_keys=True)
        grouped.setdefault(key, []).append(search)
    result = []
    for searches in grouped.values():
        if not any(s.get('enabled', True) for s in searches):
            continue
        ids = sorted(s['id'] for s in searches)
        signatures = {s['id']: signature_for(s) for s in searches}
        result.append(dict(key=hashlib.sha256(json.dumps(ids).encode()).hexdigest(), signatures=signatures,
                           title=searches[0].get('display_name') or searches[0]['query'], interval=interval))
    return result


def _compact_points(points):
    """Reduce graph density without drawing across an unobserved day."""
    indices = list(range(0, len(points), 2))
    if indices and indices[-1] != len(points) - 1:
        indices.append(len(points) - 1)
    reduced = []
    for pos, index in enumerate(indices):
        point = dict(points[index])
        if pos and any(p.get('median') is None for p in points[indices[pos-1]+1:index+1]):
            point['median'] = None
        reduced.append(point)
    return reduced


def app_snapshots(config, signature_for, now=None, logic_version=None):
    """The APK consumes the exact same deduplicated/MAD-filtered data as Telegram."""
    now = time.time() if now is None else now
    result = []
    for group in groups(config, signature_for, all_products=True):
        rows = _trend_rows(group['signatures'], now)
        result.append(dict(searchIds=list(group['signatures']), title=group['title'],
            settingsRevision=config.get('mobile_settings_revision'), logicVersion=logic_version,
            historyVersion=price_history.HISTORY_VERSION,
            generatedAt=datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='seconds'),
            **trend(group['signatures'], now, _rows=rows),
            conditionViews={condition + str(days): trend(group['signatures'], now, None if condition == 'all' else condition,
                                                         window_days=days, include_items=True, _rows=rows)
                            for condition in ('all','used','new') for days in (7,30)}))
    # GitHub's contents API stops returning inline data over 1 MiB. Keep room
    # for the rest of runtime_status.json; never remove medians or counts.
    def size():
        return len(json.dumps(result, ensure_ascii=False, indent=2).encode('utf8'))
    # Keep useful listing evidence before spending the budget on six dense
    # graphs per product. Missing days remain gaps after downsampling.
    if size() > 600_000:
        for snapshot in result:
            for view in snapshot['conditionViews'].values():
                if len(view['points']) > 2:
                    view['points'] = _compact_points(view['points'])
    if size() > 600_000:
        for snapshot in result:
            for view in snapshot['conditionViews'].values():
                if len(view['items']) > 3:
                    view['items'] = view['items'][:3]
                    view['itemsTruncated'] = True
    while size() > 600_000 and any(len(view['points']) > 2 for snapshot in result for view in snapshot['conditionViews'].values()):
        for snapshot in result:
            for view in snapshot['conditionViews'].values():
                if len(view['points']) > 2:
                    view['points'] = _compact_points(view['points'])
    for limit in (1, 0):
        if size() <= 600_000:
            break
        for snapshot in result:
            for view in snapshot['conditionViews'].values():
                if len(view['items']) > limit:
                    view['items'] = view['items'][:limit]
                    view['itemsTruncated'] = True
    return result


def delivery_status(path=None):
    path=Path(path or STATE_PATH)
    if not path.exists():
        return dict(confirmed=0,held=0,lastConfirmedAt=None)
    entries=json.loads(path.read_text(encoding='utf8'))['entries'].values()
    entries=list(entries)
    stamps=[x['confirmedAt'] for x in entries if x.get('status')=='confirmed' and x.get('confirmedAt')]
    return dict(confirmed=sum(x.get('status')=='confirmed' for x in entries),
                held=sum(x.get('status') in ('claimed','uncertain') for x in entries),
                lastConfirmedAt=datetime.fromtimestamp(max(stamps),timezone.utc).isoformat(timespec='seconds') if stamps else None)


class DeliveryStore:
    """Small non-sensitive ledger: hashed routes/IDs, timestamps and message IDs."""
    def __init__(self, path=None, remote=None):
        self.path = Path(path or STATE_PATH)
        self.remote = bool(os.environ.get('GITHUB_ACTIONS')) if remote is None else remote
        self.sha = None

    def _request(self, method, payload=None):
        import requests
        repository = os.environ['GITHUB_REPOSITORY']
        response = requests.request(method, f'https://api.github.com/repos/{repository}/contents/mobile/median_delivery.json',
            params={'ref':'main'} if method == 'GET' else None,
            headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json'},
            json=payload, timeout=20)
        if method == 'GET' and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def load(self):
        if self.remote:
            file = self._request('GET')
            self.sha = file['sha'] if file else None
            data = json.loads(base64.b64decode(file['content'])) if file else dict(schema=1, entries={})
        else:
            data = json.loads(self.path.read_text(encoding='utf8')) if self.path.exists() else dict(schema=1, entries={})
        if data.get('schema') != 1 or not isinstance(data.get('entries'), dict):
            raise ValueError('Invalid median delivery ledger')
        return data

    def save(self, data):
        content = (json.dumps(data, sort_keys=True, indent=2)+'\n').encode()
        if self.remote:
            payload = dict(branch='main',message='Checkpoint median report delivery [skip ci]',content=base64.b64encode(content).decode())
            if self.sha:
                payload['sha'] = self.sha
            # Never retry an ambiguous write: the remote claim may have succeeded.
            result = self._request('PUT', payload)
            self.sha = result['content']['sha']
            # The workflow fetches this committed file at its checkpoint.
            # Writing it as an untracked local file would obstruct that fetch.
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as f:
                name=f.name; f.write(content); f.flush(); os.fsync(f.fileno())
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)


def caption(title, data, interval):
    lines = [f'📈 <b>{html.escape(title[:140])}</b>', 'Медиана проверенных цен покупки с доставкой, €',
             'Общая выборка без дополнительного отбора по состоянию.',
             'Скользящее окно: 7 дней · даты графика: UTC']
    if data['median'] is None:
        lines.append(f"Пока недостаточно данных: {data['count']} лотов после отсева, нужно минимум {MIN_LISTINGS}.")
    else:
        lines.append(f"Медиана сейчас: <b>{data['median']:.2f} €</b> · разных лотов: {data['count']}")
        earlier = next((p for p in data['points'][:-1] if p['median'] is not None), None)
        if earlier:
            change=(data['median']/earlier['median']-1)*100
            direction='⬆️' if change > .05 else '⬇️' if change < -.05 else '➡️'
            lines.append(f"{direction} С {earlier['day']}: {change:+.1f}%")
        else:
            lines.append('Для направления тренда нужны данные хотя бы за два дня.')
    lines.extend([f"Ценовых выбросов исключено: {data['excluded']}.",
        'Текущие ставки и оценки импортных сборов не учитываются. Sofort+ — выставленная цена, не согласованная скидка.',
        'Это выборка проверенных объявлений, а не все продажи eBay.', f'Следующий отчёт — через {interval} дн.'])
    return '\n'.join(lines)


def chart(title, data):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import DateFormatter, AutoDateLocator
    fig=Figure(figsize=(9,4.8), dpi=130, layout='constrained')
    FigureCanvasAgg(fig)
    ax=fig.subplots()
    dates=[datetime.fromisoformat(p['day']) for p in data['points']]
    values=[p['median'] for p in data['points']]
    ax.plot(dates, values, color='#1976d2', marker='o', markersize=3, linewidth=2)
    ax.set_title(title[:90]+'\nМедиана проверенных цен за 7 дней')
    ax.set_ylabel('Цена покупки с доставкой, €')
    ax.set_xlabel('Дата (UTC) · пропуски означают недостаток данных')
    ax.xaxis.set_major_locator(AutoDateLocator(minticks=3,maxticks=7))
    ax.xaxis.set_major_formatter(DateFormatter('%d.%m'))
    ax.grid(alpha=.2)
    buffer=io.BytesIO();fig.savefig(buffer,format='png');buffer.seek(0);buffer.name='median.png'
    return buffer


async def send_due(bot, chat_id, config, signature_for, store=None, now=None):
    """At most one report per pass; never adds eBay traffic or delays a fresh alert."""
    now=time.time() if now is None else now
    subscriptions=groups(config,signature_for)
    if not subscriptions:
        return None
    store=store or DeliveryStore()
    ledger=store.load()
    route=hashlib.sha256((bot.token+':'+str(chat_id)).encode()).hexdigest()
    for group in subscriptions:
        key=hashlib.sha256((route+group['key']).encode()).hexdigest()
        previous=ledger['entries'].get(key,{})
        if now < previous.get('notBefore',0) or (previous and now-previous.get('at',0) < group['interval']*DAY):
            continue
        data=trend(group['signatures'],now)
        text=caption(group['title'],data,group['interval'])
        photo=chart(group['title'],data) if data['median'] is not None else None
        # CAS claim is durable before any Telegram request. A crashed/ambiguous
        # send remains claimed/uncertain until the next interval, without duplicates.
        entry=dict(at=now,status='claimed',intervalDays=group['interval'])
        ledger['entries'][key]=entry
        store.save(ledger)
        try:
            kwargs=dict(chat_id=chat_id,parse_mode='HTML',read_timeout=20,write_timeout=20,connect_timeout=10,pool_timeout=10)
            message=await bot.send_photo(photo=photo,caption=text,**kwargs) if photo is not None else await bot.send_message(text=text,**kwargs)
        except Exception as error:
            from telegram.error import RetryAfter
            if isinstance(error, RetryAfter):
                delay=error.retry_after
                seconds=delay.total_seconds() if hasattr(delay,'total_seconds') else float(delay)
                entry.update(status='retry',at=now-group['interval']*DAY,notBefore=now+max(1,seconds))
                store.save(ledger)
                return None
            entry.update(status='uncertain',error=type(error).__name__)
            store.save(ledger)
            raise
        entry.update(status='confirmed',messageId=message.message_id,confirmedAt=time.time())
        store.save(ledger)
        return dict(messageId=message.message_id,median=data['median'],count=data['count'],excluded=data['excluded'])
    return None
