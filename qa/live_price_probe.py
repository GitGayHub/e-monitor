"""One manual, durable, labelled GitHub delivery against an applied APK revision.

Never alters config/seen/history/feed. A claim is committed before Telegram I/O;
an uncertain send is never retried. Only the owner's existing LG search is used.
"""
import asyncio
import base64
import copy
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RECEIPTS = "mobile/qa_delivery_receipts.json"
LG_IDS = {"lg_ultragear_oled_480hz_buy", "lg_ultragear_oled_480hz_auc"}


def fingerprint(config):
    payload = {key: config.get(key) for key in (
        "searches", "settings", "global_banned_sellers", "banned_item_ids")}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate_snapshot(config, runtime, manifest, meta, mode, revision, limit):
    uuid.UUID(revision)
    if mode.strip() != "normal":
        raise ValueError("Production mode is not normal")
    if not (config.get("mobile_settings_revision") == runtime.get("settingsRevision") == manifest.get("settingsRevision") == revision):
        raise ValueError("Requested settings revision is not applied everywhere")
    if runtime.get("configFingerprint") != fingerprint(config):
        raise ValueError("Running configuration fingerprint differs")
    if runtime.get("logicVersion") != meta.get("logicVersion"):
        raise ValueError("Running rules differ from app metadata")
    server = {row["id"]: row for row in config["searches"] if row["id"] in LG_IDS}
    phone = {row["id"]: row for row in manifest["searches"] if row["id"] in LG_IDS}
    if set(server) != LG_IDS or set(phone) != LG_IDS:
        raise ValueError("LG variants are missing")
    if not all(server[key]["filters"].get("limit_price") == phone[key].get("maxPrice") == limit for key in LG_IDS):
        raise ValueError("Applied LG group limits differ")
    search = server["lg_ultragear_oled_480hz_buy"]
    if not search.get("enabled", True) or not search.get("notify", True):
        raise ValueError("LG notifications are disabled")
    return search


class GitHubStore:
    def __init__(self):
        import requests
        self.session = requests.Session()
        self.session.headers.update(Authorization="Bearer " + os.environ["GITHUB_TOKEN"], Accept="application/vnd.github+json")
        self.api = "https://api.github.com/repos/GitGayHub/e-monitor/"

    def get(self, path, missing=False):
        response = self.session.get(self.api + path, timeout=30)
        if missing and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def content(self, path, commit):
        value = self.get("contents/" + path + "?ref=" + commit)
        return base64.b64decode(value["content"])

    def snapshot(self):
        from config_crypt import decrypt
        head = self.get("git/ref/heads/main")["object"]["sha"]
        read_json = lambda path: json.loads(self.content(path, head))
        config = json.loads(decrypt(self.content("config.json.enc", head), os.environ["CONFIG_PASSPHRASE"]))
        return head, config, read_json("mobile/runtime_status.json"), read_json("mobile/app_sync.json"), read_json("mobile/app_version.json"), self.content("mode.txt", head).decode()

    def receipts(self):
        value = self.get("contents/" + RECEIPTS + "?ref=main", missing=True)
        return (json.loads(base64.b64decode(value["content"])), value["sha"]) if value else ({}, None)

    def write(self, records, sha):
        payload = {"branch": "main", "message": "Record explicitly labelled price QA delivery [skip ci]",
                   "content": base64.b64encode((json.dumps(records, indent=2) + "\n").encode()).decode()}
        if sha:
            payload["sha"] = sha
        # Never retry a mutation after an ambiguous response.
        response = self.session.put(self.api + "contents/" + RECEIPTS, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["content"]["sha"]


async def deliver_once(store, request_id, proof, sender):
    records, sha = store.receipts()
    if request_id in records:
        return {**records[request_id], "duplicateSuppressed": True}
    proof = {**proof, "status": "claimed_no_blind_retry", "claimedAtUtc": datetime.now(timezone.utc).isoformat()}
    records[request_id] = proof
    sha = store.write(records, sha)
    try:
        message = await sender()
        if not message or not message.message_id or not message.photo:
            raise RuntimeError("Photo acknowledgement missing")
    except Exception as error:
        proof.update(status="uncertain_do_not_retry", errorType=type(error).__name__)
        store.write(records, sha)
        raise
    proof.update(status="photo_confirmed", messageId=message.message_id,
                 confirmedAtUtc=datetime.now(timezone.utc).isoformat())
    store.write(records, sha)
    return proof


def quote_candidate(rows, item_id, expected_shipping):
    row = next((value for value in rows if value.get('item_id') == item_id), None)
    if row is None or row.get('is_pickup_only') or row.get('shipping_cost') != expected_shipping:
        raise ValueError('Fresh search card does not confirm the independently checked shipping quote')
    return copy.deepcopy(row)


async def correct_caption_once(store, request_id, proof, editor):
    records, sha = store.receipts()
    existing = records.get(request_id)
    if not existing or not existing.get('messageId'):
        raise ValueError('No confirmed original photo is available for correction')
    if existing.get('correction'):
        return {**existing, 'duplicateCorrectionSuppressed': True}
    if existing.get('status') != 'photo_confirmed':
        raise ValueError('Original photo delivery is not confirmed')
    existing['initialDelivery'] = copy.deepcopy(existing)
    existing['correction'] = {**proof, 'status': 'claimed_no_blind_retry'}
    sha = store.write(records, sha)
    try:
        message = await editor(existing['messageId'])
        if not message or message.message_id != existing['messageId']:
            raise RuntimeError('Caption correction acknowledgement missing')
    except Exception as error:
        existing['correction'].update(status='uncertain_do_not_retry', errorType=type(error).__name__)
        store.write(records, sha)
        raise
    existing.update(proof)
    existing['status'] = 'photo_confirmed_caption_corrected'
    existing['correction'].update(status='confirmed', confirmedAtUtc=datetime.now(timezone.utc).isoformat())
    store.write(records, sha)
    return existing


def require_verified_details(monitor, details, item, search):
    """Report the failed guard without dumping seller text or credentials."""
    if not details:
        raise ValueError('Fresh listing details unavailable; nothing sent')
    description = monitor._clean_description(details.get('description') or '')
    print(json.dumps({'qaDetails': {'descriptionCharacters': len(description),
        'pricePresent': bool(details.get('price')), 'bidPresent': bool(details.get('currentBidPrice')),
        'providerComplete': monitor._provider_details_complete(details),
        'unavailable': any(x.get('estimatedAvailabilityStatus')=='UNAVAILABLE' for x in (details.get('estimatedAvailabilities') or []) if isinstance(x,dict))}}))
    if not monitor._provider_details_complete(details):
        raise ValueError('Fresh seller description unavailable; nothing sent' if not description else 'Fresh live price unavailable; nothing sent')
    if not monitor._details_match_contract(item, search, details):
        raise ValueError('Fresh own listing rejected by common filters; nothing sent')


async def main():
    request_id = os.environ["QA_REQUEST_ID"]
    if not re.fullmatch(r"lg-price-[a-z0-9-]{1,70}", request_id):
        raise ValueError("Invalid QA request ID")
    revision = os.environ["QA_SETTINGS_REVISION"]
    limit = float(os.environ["QA_EXPECTED_LIMIT"])
    if limit not in (429, 430):
        raise ValueError("Only the authorized one-euro LG control is supported")
    store = GitHubStore()
    existing, _ = store.receipts()
    previous = existing.get(request_id)
    if previous and (os.environ.get('QA_CORRECT_EXISTING') != 'true' or previous.get('correction')):
        print(json.dumps({**previous, 'duplicateSuppressed': True}))
        return
    head, config, runtime, manifest, meta, mode = store.snapshot()
    search = validate_snapshot(config, runtime, manifest, meta, mode, revision, limit)
    old_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="emonitor-price-qa-") as directory:
        import config_manager, price_history
        config_manager.CONFIG_PATH = str(Path(directory) / "config.json")
        price_history.DB_PATH = str(Path(directory) / "history.db")
        Path(config_manager.CONFIG_PATH).write_text(json.dumps(config), encoding="utf8")
        os.chdir(directory)
        try:
            import monitor
            from ebay_access import MonitorPassBudget
            from telegram import Bot
            monitor.EBAY_SOURCE = "html"
            monitor.SEEN_IDS_FILE = str(Path(directory) / "seen.json")
            logging.disable(logging.CRITICAL)
            expected_shipping = float(os.environ.get('QA_EXPECTED_SHIPPING', '18.99'))
            token = MonitorPassBudget.current.set(MonitorPassBudget(170))
            try:
                rows, fetch_error = monitor.fetch_ebay_ex(monitor._prepare_monitor_fetch_search(search))
                if fetch_error:
                    raise ValueError('Fresh search quote is unavailable; nothing sent or edited')
                item = quote_candidate(rows, '800366377085', expected_shipping)
                details = monitor._fetch_item_details("800366377085")
            finally:
                MonitorPassBudget.current.reset(token)
            require_verified_details(monitor, details, item, search)
            monitor._refresh_candidate_details(item, details, config.get("settings", {}), search)
            if item.get('shipping_cost') != expected_shipping:
                raise ValueError('Refreshed delivery quote changed; independently recheck before sending')
            item["_details_status"] = "verified"
            kept = monitor.filter_results([item], search, monitor.config, skip_seen=True, is_statistics=True)
            if len(kept) != 1 or not monitor._notify_eligibility(kept[0], search)[0] or not item.get("image_url"):
                raise ValueError("Fresh item is not eligible under applied conditions")
            item = kept[0]; item["_audit_test"] = True
            fake = Mock(); fake.get_me = AsyncMock(return_value=Mock(username="eBaySearcherBOT"))
            with patch.object(monitor, "safe_send_telegram", new=AsyncMock(return_value=Mock(message_id=0))) as capture:
                if not await monitor.send_notification(fake, item, search, None):
                    raise ValueError("Caption preparation failed")
            caption = capture.await_args.args[2]
            image = capture.await_args.kwargs["img"]
            if "GitHub автомониторинг" not in caption or "ТЕСТ APK" not in caption:
                raise ValueError("Probe must be labelled as actual GitHub execution")
            if monitor._read_logic_version_timestamp() != meta["logicVersion"]:
                raise ValueError("Checked-out rules are stale")
            # Recheck active settings immediately before any delivery claim.
            latest, current, rt, mf, md, mode = store.snapshot()
            validate_snapshot(current, rt, mf, md, mode, revision, limit)
            if md["logicVersion"] != meta["logicVersion"]:
                raise ValueError("Rules changed during validation")
            proof = {"requestId": request_id, "settingsRevision": revision, "serverCommit": latest,
                     "logicVersion": meta["logicVersion"], "apkVersion": meta["versionName"],
                     "limit": limit, "itemId": item["item_id"], "price": item["price"],
                     "shipping": item["shipping_cost"], "total": item["total_price"],
                     "descriptionCharacters": len(monitor._clean_description(details["description"])),
                     "execution": "github", "productionStateChanged": False}
            if os.environ.get("QA_SEND") != "true":
                print(json.dumps({**proof, "status": "preview_no_send"})); return
            if os.environ.get('QA_CORRECT_EXISTING') == 'true':
                caption = '🧪 Исправление теста: доставка учтена.\n' + caption
                if len(caption) > 1024:
                    raise ValueError('Corrected caption exceeds Telegram photo limit')
                async def editor(message_id):
                    async with Bot(os.environ['TELEGRAM_BOT_TOKEN']) as bot:
                        if (await bot.get_me()).username.lower() != 'ebaysearcherbot':
                            raise ValueError('Wrong bot identity')
                        return await bot.edit_message_caption(chat_id=os.environ['TELEGRAM_CHAT_ID'],
                                                              message_id=message_id, caption=caption,
                                                              parse_mode='HTML', connect_timeout=20,
                                                              read_timeout=35, write_timeout=35)
                print(json.dumps(await correct_caption_once(store, request_id, proof, editor)))
                return
            async def sender():
                async with Bot(os.environ["TELEGRAM_BOT_TOKEN"]) as bot:
                    if (await bot.get_me()).username.lower() != "ebaysearcherbot":
                        raise ValueError("Wrong bot identity")
                    return await bot.send_photo(chat_id=os.environ["TELEGRAM_CHAT_ID"], photo=image,
                                                caption=caption, parse_mode="HTML", connect_timeout=20,
                                                read_timeout=35, write_timeout=35)
            print(json.dumps(await deliver_once(store, request_id, proof, sender)))
        finally:
            os.chdir(old_cwd)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print("Price QA stopped:", type(error).__name__, str(error) if isinstance(error, ValueError) else "")
        raise SystemExit(1)
