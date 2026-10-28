import sys
import os
import base64
import json
import subprocess
import shutil
from seen_state_merge import normalize_seen_state, merge_seen_state

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

def get_git_exe():
    # 1. Check if git is in PATH
    try:
        subprocess.run(["git", "--version"], capture_output=True)
        return "git"
    except FileNotFoundError:
        pass
    
    # 2. Check Windows default Git path
    win_git = r"C:\Program Files\Git\cmd\git.exe"
    if os.path.exists(win_git):
        return win_git
        
    return "git"

GIT_EXE = get_git_exe()
_REPO_SAFE = REPO_DIR.replace('\\', '/')
GIT_BASE = [GIT_EXE, "-c", f"safe.directory={_REPO_SAFE}"]

def git_run(*args, capture=True):
    cmd = GIT_BASE + list(args)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = env.get("GITHUB_TOKEN")
    if token:
        try:
            count = int(env.get("GIT_CONFIG_COUNT", "0"))
            if count < 0:
                raise ValueError()
        except ValueError as e:
            raise ValueError("Invalid GIT_CONFIG_COUNT; Git operation stopped") from e
        credential = base64.b64encode(("x-access-token:" + token).encode("utf-8")).decode("ascii")
        env[f"GIT_CONFIG_KEY_{count}"] = "http.https://github.com/.extraheader"
        env[f"GIT_CONFIG_VALUE_{count}"] = "AUTHORIZATION: Basic " + credential
        env["GIT_CONFIG_COUNT"] = str(count + 1)
    kwargs = {"cwd": REPO_DIR, "env": env}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
        kwargs["encoding"] = "utf-8"
        kwargs["errors"] = "replace"
    return subprocess.run(cmd, **kwargs)

def get_remote_file_content(filename):
    r = git_run("show", f"origin/main:{filename}")
    if r.returncode == 0:
        # Return as bytes to handle binary files (like config.json.enc)
        # git show output is captured as text if capture=True. Let's run a separate binary capture.
        cmd = GIT_BASE + ["show", f"origin/main:{filename}"]
        res = subprocess.run(cmd, cwd=REPO_DIR, capture_output=True)
        if res.returncode == 0:
            return res.stdout
    return None

def _normalize_seen_state(data):
    return normalize_seen_state(data)


def merge_seen_ids(*, validate_only=False):
    local_path = os.path.join(REPO_DIR, "seen_ids.json")
    local_data = {}
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                raw_local = json.load(f)
            if not isinstance(raw_local, (dict, list)):
                raise ValueError("invalid seen state")
            local_data = _normalize_seen_state(raw_local)
        except Exception as e:
            raise ValueError("Local seen state is unreadable; sync stopped") from e

    remote_bytes = get_remote_file_content("seen_ids.json")
    if remote_bytes is None:
        raise ValueError("Remote seen state unavailable; sync stopped")
    try:
        raw_remote = json.loads(remote_bytes.decode("utf-8"))
        if not isinstance(raw_remote, (dict, list)):
            raise ValueError("invalid seen state")
        remote_data = _normalize_seen_state(raw_remote)
    except Exception as e:
        raise ValueError("Remote seen state is unreadable; sync stopped") from e

    merged = merge_seen_state(local_data, remote_data)

    if validate_only:
        return

    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)
    print(
        f"Merged seen_ids.json: {len(local_data)} local + {len(remote_data)} remote "
        f"-> {len(merged)} total (stage format)"
    )

def merge_run_logs():
    local_path = os.path.join(REPO_DIR, "run_log.json")
    local_data = []
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                local_data = json.load(f)
        except Exception:
            local_data = []
            
    remote_bytes = get_remote_file_content("run_log.json")
    remote_data = []
    if remote_bytes:
        try:
            remote_data = json.loads(remote_bytes.decode("utf-8", errors="replace"))
        except Exception:
            remote_data = []
            
    if not isinstance(local_data, list): local_data = []
    if not isinstance(remote_data, list): remote_data = []
    
    combined = remote_data + local_data
    seen_times = set()
    deduped = []
    for entry in combined:
        if not isinstance(entry, dict):
            continue
        t = entry.get("time")
        if t and t not in seen_times:
            seen_times.add(t)
            deduped.append(entry)
            
    deduped.sort(key=lambda x: x.get("time", ""))
    merged = deduped[-300:]  # Keep last 300 logs
    
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=1, ensure_ascii=False)
    print(f"Merged run_log.json: {len(local_data)} local + {len(remote_data)} remote -> {len(merged)} total")

def merge_configs():
    passphrase = os.environ.get("CONFIG_PASSPHRASE")
    if not passphrase:
        raise ValueError("CONFIG_PASSPHRASE missing; configuration and sync left unchanged")
        
    local_path = os.path.join(REPO_DIR, "config.json")
    enc_path = os.path.join(REPO_DIR, "config.json.enc")
    local_exists = os.path.exists(local_path) or os.path.exists(enc_path)
    local_data = {}
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                local_data = json.load(f)
        except Exception as e:
            raise ValueError("Local configuration is unreadable; sync stopped") from e
    else:
        # Try decrypting local config.json.enc if config.json is not present
        if os.path.exists(enc_path):
            try:
                sys.path.append(REPO_DIR)
                import config_crypt
                with open(enc_path, "rb") as f:
                    enc_bytes = f.read()
                dec_bytes = config_crypt.decrypt_config(enc_bytes, passphrase)
                local_data = json.loads(dec_bytes.decode("utf-8"))
            except Exception as e:
                raise ValueError("Local encrypted configuration is unreadable; sync stopped") from e
            
    remote_bytes_enc = get_remote_file_content("config.json.enc")
    if not remote_bytes_enc:
        raise ValueError("Remote configuration unavailable; sync stopped")
    try:
        sys.path.append(REPO_DIR)
        import config_crypt
        remote_bytes_dec = config_crypt.decrypt_config(remote_bytes_enc, passphrase)
        remote_data = json.loads(remote_bytes_dec.decode("utf-8"))
    except Exception as e:
        raise ValueError("Remote configuration is unreadable; sync stopped") from e
    if (not isinstance(local_data, dict) or (local_exists and not isinstance(local_data.get('searches'), list)) or
            not isinstance(remote_data, dict) or not isinstance(remote_data.get('searches'), list)):
        raise ValueError("Invalid configuration structure; sync stopped")
        
    # We want to keep settings and searches from remote/origin (which has master updates)
    # but merge item_hashes, banned_item_ids, and global_banned_sellers from local run
    merged_data = remote_data.copy()
    for list_key in ("item_hashes", "banned_item_ids", "global_banned_sellers"):
        origin_val = remote_data.get(list_key, [])
        local_val = local_data.get(list_key, [])
        if not isinstance(origin_val, list) or not isinstance(local_val, list):
            raise ValueError("Invalid ban or item hash list; sync stopped")
        
        merged_list = sorted(list(set(origin_val) | set(local_val)))
        merged_data[list_key] = merged_list
        
    local_encrypted = None
    if os.path.exists(enc_path):
        with open(enc_path, "rb") as f:
            local_encrypted = f.read()
    save_and_encrypt_config(merged_data, passphrase, previous=(local_encrypted, remote_bytes_enc))
    print("Merged config.json successfully.")

def save_and_encrypt_config(config_dict, passphrase, previous=()):
    local_path = os.path.join(REPO_DIR, "config.json")
    enc_path = os.path.join(REPO_DIR, "config.json.enc")
    # Validate the policy and prior authenticated envelopes before touching either file.
    import config_crypt
    dec_data = json.dumps(config_dict, indent=2, ensure_ascii=False).encode("utf-8")
    enc_data = config_crypt.encrypt_config(dec_data, passphrase, previous=previous)
    with open(local_path, "wb") as f:
        f.write(dec_data)
    with open(enc_path, "wb") as f:
        f.write(enc_data)

def main():
    print(f"=== [git_sync] Starting Sync ===")
    
    # Fetch origin main using transient authentication, never a credential URL.
    print("Fetching remote changes...")
    fetch = git_run("fetch", "origin", "main")
    if fetch.returncode != 0:
        raise RuntimeError("Git fetch failed; sync stopped before modifying state")
    
    # 3. Merge State Files
    print("Merging state files...")
    merge_seen_ids(validate_only=True)
    merge_configs()
    merge_seen_ids()
    merge_run_logs()
    
    # 4. Stage State Files
    state_files = [
        "seen_ids.json", 
        "config.json.enc", 
        "run_log.json", 
        "price_history.db",
        "mobile/app_sync.json",
        "details_test_output.json",
        "monitor_debug_tail.txt"
    ]
    staged_any = False
    for f in state_files:
        full_path = os.path.join(REPO_DIR, f)
        if os.path.exists(full_path):
            if git_run("add", f).returncode != 0:
                raise RuntimeError("Git staging failed; sync stopped without pushing")
            staged_any = True
            
    if not staged_any:
        print("No state files found to sync.")
        return

    # 5. Commit and Push Loop (to handle push races)
    for attempt in range(5):
        diff = git_run("diff", "--cached", "--quiet")
        if diff.returncode not in (0, 1):
            raise RuntimeError("Git staging check failed; sync stopped without pushing")
        if diff.returncode != 0:
            print("Committing local state changes...")
            commit = git_run("commit", "-m", "Update monitor state")
            if commit.returncode != 0:
                raise RuntimeError("Git commit failed; sync stopped without pushing")
                
        print("Pulling & Rebasing with remote to avoid conflicts...")
        # -X theirs tells git to prefer our changes (which are pre-merged anyway) on conflicts
        pull = git_run("pull", "--rebase", "-X", "theirs", "origin", "main")
        if pull.returncode != 0:
            git_run("rebase", "--abort")
            raise RuntimeError("Git rebase failed; sync stopped without pushing")
            
        print("Pushing to origin...")
        push = git_run("push", "origin", "main")
        if push.returncode == 0:
            print("=== [git_sync] Push successful! ===")
            break
        else:
            print(f"Push failed (attempt {attempt+1}/5): {push.stderr.strip()}. Retrying fetch and merge...")
            if git_run("fetch", "origin", "main").returncode != 0:
                raise RuntimeError("Git fetch failed during retry; sync stopped")
            merge_seen_ids(validate_only=True)
            merge_configs()
            merge_seen_ids()
            merge_run_logs()
            for f in state_files:
                if os.path.exists(os.path.join(REPO_DIR, f)):
                    if git_run("add", f).returncode != 0:
                        raise RuntimeError("Git staging failed during retry; sync stopped without pushing")
    else:
        print("ERROR: Failed to push state updates after 5 attempts.")
        sys.exit(1)

if __name__ == "__main__":
    main()
