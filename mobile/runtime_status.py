"""Publish acknowledgement of the configuration held by the running monitor."""
import hashlib
import json
import os
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


def publish(active_config, logic_version, state, error=None, path=None, data_source=None, warning=None):
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
        "dataSource": data_source,
        "warning": str(warning)[:1000] if warning else None,
        "activeSearches": sum(bool(row.get("enabled", True)) for row in active_config.get("searches", [])),
        "configFingerprint": fingerprint,
    }
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
