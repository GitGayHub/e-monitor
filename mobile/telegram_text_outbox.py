"""Durable replies to confirmed photos. Never resend a photo from this queue.

A network timeout is an unknown delivery, not evidence of failure. Such replies
are held for review; retrying them automatically could duplicate delivered text.
"""
import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from bs4 import BeautifulSoup
from config_crypt import encrypt, decrypt
from telegram.error import BadRequest, RetryAfter

PATH = Path(__file__).resolve().parent / "telegram_text_outbox.json.enc"
LOCK = threading.RLock()
MAGIC = b"EMTG1"


def _key():
    value = os.environ.get("CONFIG_PASSPHRASE")
    if not value:
        raise ValueError("Telegram reply queue encryption key unavailable")
    return value


def _mac_key(key):
    return hashlib.sha256(("emonitor-telegram-replies:" + key).encode()).digest()


def _load():
    if not PATH.exists():
        return {"schema": 1, "entries": {}}
    key = _key()
    raw = PATH.read_bytes()
    if raw[:5] != MAGIC or not hmac.compare_digest(raw[5:37], hmac.digest(_mac_key(key), raw[37:], "sha256")):
        raise ValueError("Telegram reply queue authentication failed")
    result = json.loads(decrypt(raw[37:], key))
    if result.get("schema") != 1 or not isinstance(result.get("entries"), dict):
        raise ValueError("Invalid Telegram reply queue")
    return result


def _save(data):
    key = _key()
    payload = encrypt(json.dumps(data, ensure_ascii=False).encode(), key)
    content = MAGIC + hmac.digest(_mac_key(key), payload, "sha256") + payload
    PATH.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=PATH.parent, delete=False) as file:
            name = file.name
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, PATH)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def _route(bot, chat_id):
    token = bot.token
    if not isinstance(token, str) or not token:
        raise ValueError("Telegram sender identity unavailable")
    return hashlib.sha256(token.encode()).hexdigest(), hashlib.sha256(str(chat_id).encode()).hexdigest()


def chunks(text, parse_mode="HTML"):
    """Keep normal HTML intact; split oversized text without breaking tags/emoji."""
    soup = BeautifulSoup(text, "html.parser") if parse_mode == "HTML" else None
    plain = soup.get_text() if soup is not None else text
    if len(plain.encode("utf-16-le")) // 2 <= 4096:
        return [{"text": text, "parseMode": parse_mode}]
    if soup is not None:
        for link in soup.find_all("a", href=True):
            label = link.get_text()
            url = link["href"]
            link.replace_with(label if url in label else f"{label} ({url})")
        plain = soup.get_text()
    result, current, units = [], [], 0
    for character in plain:
        size = 2 if ord(character) > 0xFFFF else 1
        if units + size > 3900:
            result.append({"text": "".join(current), "parseMode": None})
            current, units = [], 0
        current.append(character)
        units += size
    if current:
        result.append({"text": "".join(current), "parseMode": None})
    return result


def enqueue(bot, chat_id, photo_id, text, parse_mode="HTML"):
    sender, recipient = _route(bot, chat_id)
    identifier = hashlib.sha256(f"{sender}:{recipient}:{photo_id}".encode()).hexdigest()
    with LOCK:
        data = _load()
        if identifier not in data["entries"]:
            data["entries"][identifier] = {
                "sender": sender, "recipient": recipient, "photoId": photo_id,
                "chunks": chunks(text, parse_mode), "next": 0, "status": "pending",
                "notBefore": 0, "createdAt": time.time(), "attempts": 0,
            }
            _save(data)
    return identifier


def prepare():
    """Check encryption and atomic storage before delivering a long photo."""
    with LOCK:
        _save(_load())


def _update(identifier, **changes):
    with LOCK:
        data = _load()
        entry = data["entries"].get(identifier)
        if entry is None:
            return
        entry.update(changes)
        if entry["next"] >= len(entry["chunks"]):
            del data["entries"][identifier]
        _save(data)


async def flush(bot, chat_id, only=None):
    sender, recipient = _route(bot, chat_id)
    with LOCK:
        data = _load()
        entries = list(data["entries"].items())
    delivered = 0
    for identifier, entry in entries:
        if only is not None and identifier != only:
            continue
        if (entry["sender"], entry["recipient"]) != (sender, recipient):
            continue
        if entry["status"] != "pending" or entry["notBefore"] > time.time():
            continue
        while True:
            # Claim atomically: a callback and a monitor sweep may flush together.
            with LOCK:
                data = _load()
                current = data["entries"].get(identifier)
                if current is None or current["status"] != "pending" or current["notBefore"] > time.time():
                    break
                index = current["next"]
                chunk = current["chunks"][index]
                current.update(status="sending", attempts=current["attempts"] + 1)
                _save(data)
            try:
                await bot.send_message(chat_id=chat_id, text=chunk["text"], parse_mode=chunk["parseMode"],
                                       reply_to_message_id=entry["photoId"], disable_web_page_preview=True)
            except RetryAfter as error:
                delay = error.retry_after
                seconds = delay.total_seconds() if hasattr(delay, "total_seconds") else float(delay)
                _update(identifier, status="pending", notBefore=time.time() + max(1, seconds), error="RetryAfter")
                break
            except BadRequest:
                # Rejected by Telegram: delivered nothing. Retain for diagnosis;
                # automatic retries cannot repair a missing photo/invalid entity.
                _update(identifier, status="rejected", error="BadRequest")
                break
            except Exception as error:
                _update(identifier, status="uncertain", error=type(error).__name__)
                break
            else:
                delivered += 1
                _update(identifier, next=index + 1, status="pending", notBefore=0)
    return delivered


def warning():
    with LOCK:
        entries = list(_load()["entries"].values())
    if not entries:
        return None
    pending = sum(entry["status"] == "pending" for entry in entries)
    held = len(entries) - pending
    return (f"Telegram: полный текст {pending} уведомлений ожидает повторной отправки; "
            f"{held} требуют проверки доставки. Фотографии повторно не отправляются.")
