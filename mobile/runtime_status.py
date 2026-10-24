"""Publish acknowledgement of the configuration held by the running monitor."""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATUS_PATH = Path(__file__).resolve().parent / "runtime_status.json"


def application_failure(message, path=None):
    """A failed load must never acknowledge the revision it was trying to load."""
    path = Path(path or STATUS_PATH)
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {"schema": 1, "settingsRevision": None, "appliedAt": None}
    previous.update(state="error", error=str(message)[:1000], updatedAt=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".error.tmp")
    temporary.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return previous


def search_issues(active_config, errors):
    searches={str(row.get('id')):row for row in active_config.get('searches',[])}
    issues=[]
    for text in errors or []:
        search_id,_,detail=str(text).partition(':')
        row=searches.get(search_id,{})
        issues.append(dict(searchId=search_id,searchName=row.get('display_name') or row.get('query') or search_id,**_issue(detail)))
    return issues


def _issue(detail):
    """HTTP/API refusals are search failures, never a description verdict."""
    status=re.search(r'\bhttp_(\d{3})\b',detail)
    if status and status.group(1)=='403':
        return dict(code='blocked',message='eBay отклонил запрос (403)')
    if status and status.group(1)=='429':
        return dict(code='rate_limit',message='eBay ограничил частоту запросов (429)')
    if status:
        return dict(code='http',message=f'Ошибка сайта eBay ({status.group(1)})')
    if 'api_auth' in detail:
        return dict(code='api_auth',message='eBay API отклонил ключи; используется HTML')
    code=next((c for c in ('site_error','blocked','rate_limit','cooldown','network','parse') if c in detail),None)
    if code is None and 'описания или цены недоступны' in detail:
        code='details_unavailable'
    message={'site_error':'eBay вернул страницу временной ошибки','blocked':'eBay ограничил доступ к выдаче','rate_limit':'eBay ограничил частоту запросов','cooldown':'Ожидается повторная проверка','network':'Не удалось получить ответ eBay','parse':'Не удалось прочитать ответ eBay','details_unavailable':'Не удалось полностью проверить описание или цену'}.get(code)
    return dict(code=code or 'unknown',message=message or 'Проверка поиска не завершена; повторится')


def publish(active_config, logic_version, state, error=None, path=None, data_source=None, warning=None, source_policy=None,pending=None,search_errors=None,last_pass=None,coverage=None,schedule=None,api_keys=None):
    path = Path(path or STATUS_PATH)
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {key: active_config.get(key) for key in (
        "searches", "settings", "global_banned_sellers", "banned_item_ids"
    )}
    fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
    revision = active_config.get("mobile_settings_revision")
    unchanged = previous.get("settingsRevision") == revision and previous.get("configFingerprint") == fingerprint
    status = {
        "schema": 1,
        "settingsRevision": revision,
        "appliedAt": previous.get("appliedAt") if unchanged and previous.get("appliedAt") else now,
        "logicVersion": logic_version,
        "lastSuccessfulRun": now if state == "ok" else previous.get("lastSuccessfulRun"),
        "updatedAt": now,
        "state": state,
        "error": str(error)[:1000] if error else None,
        "pendingCount": len(pending or []),
        "pendingChecks": [str(value)[:200] for value in (pending or [])[:48]],
        "searchIssueCount": len(search_errors or []),
        "searchIssues": search_issues(active_config,search_errors)[:48],
        "lastPass": last_pass,
        "searchCoverage": coverage,
        "dataSource": data_source,
        "sourcePolicy": source_policy,
        "warning": str(warning)[:1000] if warning else None,
        "activeSearches": sum(bool(row.get("enabled", True)) for row in active_config.get("searches", [])),
        "configFingerprint": fingerprint,
        # A running pass has no throughput yet: keep the last measured plan.
        "schedule": schedule or previous.get("schedule"),
        "apiKeys": api_keys if api_keys is not None else previous.get("apiKeys", []),
    }
    try:
        from mobile.median_reports import delivery_status
        status['medianReports']=delivery_status(path.with_name('median_delivery.json'))
    except (OSError, ValueError, KeyError, TypeError):
        status['medianReports']={'confirmed':0,'held':0,'lastConfirmedAt':None,'error':'Не удалось прочитать состояние отчётов медианы'}
    try:
        feed=json.loads(path.with_name('feed.json').read_text(encoding='utf8'))
        latest=max(feed.get('items',[]),key=lambda r:r.get('telegramConfirmedTime') or r.get('spottedTime') or 0,default={})
        confirmed=latest.get('telegramConfirmedTime') or latest.get('spottedTime')
        if latest.get('telegramMessageId') and confirmed:
            status['lastTelegramConfirmedAt']=datetime.fromtimestamp(confirmed/1000,timezone.utc).isoformat(timespec='seconds')
            for key in ('telegramBotUsername','telegramDeliveryRoute'):
                if latest.get(key):status['last'+key[0].upper()+key[1:]]=latest[key]
    except (OSError,ValueError,TypeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".runtime-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(status, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return status


if __name__ == "__main__":
    import sys
    application_failure(sys.argv[1] if len(sys.argv) > 1 else "Server configuration could not be applied")
