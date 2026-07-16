import sys
import os
import json
import subprocess
import shutil
import re

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
    """list of ids or stage-dict -> {id: {initial, final_hour}}."""
    state = {}
    if isinstance(data, list):
        for x in data:
            iid = str(x).strip()
            if iid:
                state[iid] = {"initial": True, "final_hour": False}
    elif isinstance(data, dict):
        for k, v in data.items():
            iid = str(k).strip()
            if not iid:
                continue
            if isinstance(v, dict):
                state[iid] = {
                    "initial": bool(v.get("initial")),
                    "final_hour": bool(v.get("final_hour")),
                }
            else:
                state[iid] = {"initial": True, "final_hour": False}
    return state


def merge_seen_ids():
    local_path = os.path.join(REPO_DIR, "seen_ids.json")
    local_data = {}
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                local_data = _normalize_seen_state(json.load(f))
        except Exception:
            local_data = {}

    remote_bytes = get_remote_file_content("seen_ids.json")
    remote_data = {}
    if remote_bytes:
        try:
            remote_data = _normalize_seen_state(
                json.loads(remote_bytes.decode("utf-8", errors="replace"))
            )
        except Exception:
            remote_data = {}

    merged = {}
    for iid in set(local_data) | set(remote_data):
        a = local_data.get(iid) or {}
        b = remote_data.get(iid) or {}
        merged[iid] = {
            "initial": bool(a.get("initial") or b.get("initial")),
            "final_hour": bool(a.get("final_hour") or b.get("final_hour")),
        }

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
        print("WARNING: CONFIG_PASSPHRASE not set; skipping config.json merge.")
        return
        
    local_path = os.path.join(REPO_DIR, "config.json")
    local_data = {}
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                local_data = json.load(f)
        except Exception:
            local_data = {}
    else:
        # Try decrypting local config.json.enc if config.json is not present
        enc_path = os.path.join(REPO_DIR, "config.json.enc")
        if os.path.exists(enc_path):
            try:
                sys.path.append(REPO_DIR)
                import config_crypt
                with open(enc_path, "rb") as f:
                    enc_bytes = f.read()
                dec_bytes = config_crypt.decrypt(enc_bytes, passphrase)
                local_data = json.loads(dec_bytes.decode("utf-8", errors="replace"))
            except Exception as e:
                print(f"WARNING: failed to decrypt local config.json.enc: {e}")
                local_data = {}
            
    remote_bytes_enc = get_remote_file_content("config.json.enc")
    remote_data = {}
    if remote_bytes_enc:
        try:
            sys.path.append(REPO_DIR)
            import config_crypt
            remote_bytes_dec = config_crypt.decrypt(remote_bytes_enc, passphrase)
            remote_data = json.loads(remote_bytes_dec.decode("utf-8", errors="replace"))
        except Exception as e:
            print(f"WARNING: failed to decrypt remote config: {e}")
            remote_data = {}
            
    if not isinstance(local_data, dict): local_data = {}
    if not isinstance(remote_data, dict): remote_data = {}
    
    if not remote_data:
        # If no remote config, just encrypt the local config and write it back
        if local_data:
            save_and_encrypt_config(local_data, passphrase)
        return
        
    # We want to keep settings and searches from remote/origin (which has master updates)
    # but merge item_hashes, banned_item_ids, and global_banned_sellers from local run
    merged_data = remote_data.copy()
    for list_key in ("item_hashes", "banned_item_ids", "global_banned_sellers"):
        origin_val = remote_data.get(list_key, [])
        local_val = local_data.get(list_key, [])
        if not isinstance(origin_val, list): origin_val = []
        if not isinstance(local_val, list): local_val = []
        
        merged_list = sorted(list(set(origin_val) | set(local_val)))
        merged_data[list_key] = merged_list
        
    save_and_encrypt_config(merged_data, passphrase)
    print("Merged config.json successfully.")

def save_and_encrypt_config(config_dict, passphrase):
    local_path = os.path.join(REPO_DIR, "config.json")
    enc_path = os.path.join(REPO_DIR, "config.json.enc")
    
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=2, ensure_ascii=False)
        
    import config_crypt
    with open(local_path, "rb") as f:
        dec_data = f.read()
        
    enc_data = config_crypt.encrypt(dec_data, passphrase)
    with open(enc_path, "wb") as f:
        f.write(enc_data)

def main():
    print(f"=== [git_sync] Starting Sync ===")
    
    # 1. Git config safe checkout setup for remote push auth
    gh_token = os.environ.get("GITHUB_TOKEN")
    if gh_token:
        r_url = git_run("remote", "get-url", "origin")
        r_str = (r_url.stdout or "").strip()
        if r_str and "github.com" in r_str:
            fixed = re.sub(r'https://(?:[^@]+@)?github\.com', f'https://{gh_token}@github.com', r_str)
            if fixed != r_str:
                git_run("remote", "set-url", "origin", fixed)

    # 2. Fetch origin main
    print("Fetching remote changes...")
    fetch = git_run("fetch", "origin", "main")
    if fetch.returncode != 0:
        print(f"WARNING: git fetch failed: {fetch.stderr.strip()}")
        # We can still commit local state if fetch fails
    
    # 3. Merge State Files
    print("Merging state files...")
    merge_seen_ids()
    merge_run_logs()
    merge_configs()
    
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
            git_run("add", f)
            staged_any = True
            
    if not staged_any:
        print("No state files found to sync.")
        return

    # 5. Commit and Push Loop (to handle push races)
    for attempt in range(5):
        diff = git_run("diff", "--cached", "--quiet")
        if diff.returncode != 0:
            print("Committing local state changes...")
            commit = git_run("commit", "-m", "Update monitor state")
            if commit.returncode != 0:
                print(f"ERROR: commit failed: {commit.stderr.strip()}")
                break
                
        print("Pulling & Rebasing with remote to avoid conflicts...")
        # -X theirs tells git to prefer our changes (which are pre-merged anyway) on conflicts
        pull = git_run("pull", "--rebase", "-X", "theirs", "origin", "main")
        if pull.returncode != 0:
            print(f"WARNING: pull rebase failed: {pull.stderr.strip()}. Aborting rebase.")
            git_run("rebase", "--abort")
            
        print("Pushing to origin...")
        push = git_run("push", "origin", "main")
        if push.returncode == 0:
            print("=== [git_sync] Push successful! ===")
            break
        else:
            print(f"Push failed (attempt {attempt+1}/5): {push.stderr.strip()}. Retrying fetch and merge...")
            git_run("fetch", "origin", "main")
            merge_seen_ids()
            merge_run_logs()
            merge_configs()
            for f in state_files:
                if os.path.exists(os.path.join(REPO_DIR, f)):
                    git_run("add", f)
    else:
        print("ERROR: Failed to push state updates after 5 attempts.")
        sys.exit(1)

if __name__ == "__main__":
    main()
