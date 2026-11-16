"""Push confirmed delivery state without overwriting a concurrent phone edit."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config_crypt import decrypt_config, encrypt_config


def _merge_search_lists(base, local, remote, path):
    missing = object()
    by_b = {row["id"]: row for row in base}
    by_l = {row["id"]: row for row in local}
    by_r = {row["id"]: row for row in remote}
    order = list(dict.fromkeys([row["id"] for row in remote] + [row["id"] for row in local]))
    merged = []
    for sid in order:
        val = merge_config(by_b.get(sid, missing), by_l.get(sid, missing), by_r.get(sid, missing), f"{path}.{sid}")
        if val is not missing:
            merged.append(val)
    return merged


def merge_config(base, local, remote, path="config"):
    if local == base:
        return remote
    if remote == base or local == remote:
        return local
    if path == "config.searches" and all(
        isinstance(x, list) and all(isinstance(row, dict) and "id" in row for row in x)
        for x in (base, local, remote)
    ):
        return _merge_search_lists(base, local, remote, path)
    if all(isinstance(x, dict) for x in (base, local, remote)):
        missing = object()
        result = {}
        for key in base.keys() | local.keys() | remote.keys():
            value = merge_config(base.get(key, missing), local.get(key, missing), remote.get(key, missing), f"{path}.{key}")
            if value is not missing:
                result[key] = value
        return result
    raise ValueError(f"Conflicting concurrent change: {path}; checkpoint retained locally")


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=check,
                          env={**os.environ, "GIT_EDITOR": "true", "GIT_TERMINAL_PROMPT": "0"})


def push():
    for attempt in range(5):
        if git("push", check=False).returncode == 0:
            return
        git("fetch", "origin", "main")
        base = git("merge-base", "HEAD", "origin/main").stdout.decode().strip()
        snapshots = {}
        for name in ("config.json.enc", "mobile/app_sync.json"):
            snapshots[name] = [git("show", f"{ref}:{name}").stdout for ref in (base, "HEAD", "origin/main")]
        rebased = git("rebase", "origin/main", check=False)
        if rebased.returncode:
            conflicts = git("diff", "--name-only", "--diff-filter=U").stdout.decode().splitlines()
            if not conflicts or set(conflicts) - set(snapshots):
                git("rebase", "--abort", check=False)
                raise RuntimeError("Checkpoint rebase conflict; refusing to discard confirmed deliveries")
            try:
                for name in conflicts:
                    versions = snapshots[name]
                    if name.endswith(".enc"):
                        passphrase = os.environ["CONFIG_PASSPHRASE"]
                        documents = [json.loads(decrypt_config(value, passphrase)) for value in versions]
                        merged = merge_config(*documents)
                        content = encrypt_config(json.dumps(merged, ensure_ascii=False, indent=2).encode(), passphrase, previous=versions)
                    else:
                        _, local, remote = [json.loads(value) for value in versions]
                        # An unconsumed phone snapshot is authoritative until next sweep.
                        merged = remote if remote.get("writer") == "android" else local
                        content = (json.dumps(merged, ensure_ascii=False, indent=2) + "\n").encode()
                    (ROOT / name).write_bytes(content)
                    git("add", name)
                git("rebase", "--continue")
            except BaseException:
                git("rebase", "--abort", check=False)
                raise
        time.sleep(2)
    raise RuntimeError("Checkpoint publication failed after five attempts; no next sweep")


if __name__ == "__main__":
    push()
