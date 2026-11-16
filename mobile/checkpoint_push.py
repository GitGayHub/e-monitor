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


def merge_app_sync(base, local, remote):
    if remote.get("writer") == "android":
        return remote
    merged = dict(local)
    if all(isinstance(d.get("searches"), list) and all(isinstance(r, dict) and "id" in r for r in d["searches"]) for d in (base, local, remote)):
        merged["searches"] = _merge_search_lists(base["searches"], local["searches"], remote["searches"], "app_sync.searches")
    elif local.get("searches") == base.get("searches") and "searches" in remote:
        merged["searches"] = remote["searches"]
    for key in ("bannedSellers", "hiddenItems", "config"):
        if key in local or key in remote:
            missing = object()
            b_val = base.get(key, missing)
            l_val = local.get(key, missing)
            r_val = remote.get(key, missing)
            if l_val == b_val:
                if r_val is not missing:
                    merged[key] = r_val
                else:
                    merged.pop(key, None)
            elif r_val == b_val or l_val == r_val:
                if l_val is not missing:
                    merged[key] = l_val
            elif isinstance(l_val, dict) and isinstance(r_val, dict) and isinstance(b_val, dict):
                try:
                    merged[key] = merge_config(b_val, l_val, r_val, f"app_sync.{key}")
                except ValueError:
                    merged[key] = r_val
            elif isinstance(l_val, list) and isinstance(r_val, list):
                merged[key] = sorted(set(l_val) | set(r_val))
    remote_searches_changed = remote.get("searches") != base.get("searches")
    merged["logicVersion"] = max(
        (v for v in (base.get("logicVersion"), local.get("logicVersion"), remote.get("logicVersion")) if isinstance(v, (int, float))),
        default=local.get("logicVersion"),
    )
    updated_values = [str(v) for v in (local.get("updatedAt"), remote.get("updatedAt")) if v]
    if updated_values:
        merged["updatedAt"] = max(updated_values)
    if remote.get("settingsRevision") != base.get("settingsRevision") and (local.get("settingsRevision") == base.get("settingsRevision") or remote_searches_changed):
        merged["settingsRevision"] = remote.get("settingsRevision")
    if remote_searches_changed and remote.get("commit"):
        merged["commit"] = remote["commit"]
    for key in ("items", "medianPrices", "medianReports"):
        if local.get(key) == base.get(key) and key in remote:
            merged[key] = remote[key]
    merged["writer"] = "server"
    return merged


def _refresh_local_decrypted_config():
    cfg_path = ROOT / "config.json"
    enc_path = ROOT / "config.json.enc"
    passphrase = os.environ.get("CONFIG_PASSPHRASE")
    if passphrase and cfg_path.is_file() and enc_path.is_file():
        decrypted = decrypt_config(enc_path.read_bytes(), passphrase)
        cfg_path.write_bytes(decrypted if decrypted.endswith(b"\n") else decrypted + b"\n")


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=check,
                          env={**os.environ, "GIT_EDITOR": "true", "GIT_TERMINAL_PROMPT": "0"})


def _merge_base():
    res = git("merge-base", "HEAD", "origin/main", check=False)
    if res.returncode != 0:
        git("fetch", "--deepen=25", "origin", "main", check=False)
        res = git("merge-base", "HEAD", "origin/main", check=False)
        if res.returncode != 0:
            git("fetch", "--unshallow", "origin", check=False)
            res = git("merge-base", "HEAD", "origin/main")
    return res.stdout.decode().strip()


def push():
    rebased_once = False
    for attempt in range(5):
        if git("push", check=False).returncode == 0:
            if rebased_once:
                _refresh_local_decrypted_config()
            return
        git("fetch", "origin", "main")
        base = _merge_base()
        snapshots = {}
        for name in ("config.json.enc", "mobile/app_sync.json"):
            snapshots[name] = [git("show", f"{ref}:{name}").stdout for ref in (base, "HEAD", "origin/main")]
        rebased = git("rebase", "origin/main", check=False)
        rebased_once = True
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
                        base_sync, local_sync, remote_sync = [json.loads(value) for value in versions]
                        merged = merge_app_sync(base_sync, local_sync, remote_sync)
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
