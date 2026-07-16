import os
import sys
import json
import shutil

def _normalize_seen_state(data):
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


def merge_json_lists(path_origin, path_local):
    """Merge seen_ids: supports legacy list and stage-dict formats."""
    origin = {}
    local = {}
    if os.path.exists(path_origin):
        try:
            with open(path_origin, "r", encoding="utf-8") as f:
                origin = _normalize_seen_state(json.load(f))
        except Exception:
            origin = {}
    if os.path.exists(path_local):
        try:
            with open(path_local, "r", encoding="utf-8") as f:
                local = _normalize_seen_state(json.load(f))
        except Exception:
            local = {}

    merged = {}
    for iid in set(origin) | set(local):
        a = origin.get(iid) or {}
        b = local.get(iid) or {}
        merged[iid] = {
            "initial": bool(a.get("initial") or b.get("initial")),
            "final_hour": bool(a.get("final_hour") or b.get("final_hour")),
        }
    return merged

def merge_run_logs(path_origin, path_local):
    if os.path.exists(path_origin):
        try:
            with open(path_origin, "r", encoding="utf-8") as f:
                origin = json.load(f)
        except Exception:
            origin = []
    else:
        origin = []

    if os.path.exists(path_local):
        try:
            with open(path_local, "r", encoding="utf-8") as f:
                local = json.load(f)
        except Exception:
            local = []
    else:
        local = []

    if not isinstance(origin, list): origin = []
    if not isinstance(local, list): local = []

    # Combine
    combined = origin + local
    
    # Deduplicate by 'time' key
    seen_times = set()
    deduped = []
    for entry in combined:
        if not isinstance(entry, dict):
            continue
        t = entry.get("time")
        if t and t not in seen_times:
            seen_times.add(t)
            deduped.append(entry)
            
    # Sort by time
    deduped.sort(key=lambda x: x.get("time", ""))
    
    # Keep last 50
    return deduped[-50:]

def merge_configs(path_origin, path_local):
    if os.path.exists(path_origin):
        try:
            with open(path_origin, "r", encoding="utf-8") as f:
                origin = json.load(f)
        except Exception:
            origin = {}
    else:
        origin = {}

    if os.path.exists(path_local):
        try:
            with open(path_local, "r", encoding="utf-8") as f:
                local = json.load(f)
        except Exception:
            local = {}
    else:
        local = {}

    if not isinstance(origin, dict): origin = {}
    if not isinstance(local, dict): local = {}

    # We want to keep settings and searches from origin (which might have user updates)
    # but merge item_hashes, banned_item_ids, and global_banned_sellers from local run
    for list_key in ("item_hashes", "banned_item_ids", "global_banned_sellers"):
        origin_val = origin.get(list_key, [])
        local_val = local.get(list_key, [])
        if not isinstance(origin_val, list): origin_val = []
        if not isinstance(local_val, list): local_val = []
        
        merged_list = sorted(list(set(origin_val) | set(local_val)))
        origin[list_key] = merged_list

    return origin

def main():
    if len(sys.argv) < 3:
        print("Usage: python merge_state.py <backup_dir> <repo_root>")
        sys.exit(1)

    backup_dir = sys.argv[1]
    repo_root = sys.argv[2]

    # 1. Merge seen_ids.json
    seen_origin = os.path.join(repo_root, "seen_ids.json")
    seen_local = os.path.join(backup_dir, "seen_ids.json")
    if os.path.exists(seen_local):
        merged_seen = merge_json_lists(seen_origin, seen_local)
        with open(seen_origin, "w", encoding="utf-8") as f:
            json.dump(merged_seen, f, ensure_ascii=False)
        print("Merged seen_ids.json successfully")

    # 2. Merge run_log.json
    log_origin = os.path.join(repo_root, "run_log.json")
    log_local = os.path.join(backup_dir, "run_log.json")
    if os.path.exists(log_local):
        merged_logs = merge_run_logs(log_origin, log_local)
        with open(log_origin, "w", encoding="utf-8") as f:
            json.dump(merged_logs, f, indent=1, ensure_ascii=False)
        print("Merged run_log.json successfully")

    # 3. Merge config.json
    cfg_origin = os.path.join(repo_root, "config.json")
    cfg_local = os.path.join(backup_dir, "config.json")
    if os.path.exists(cfg_local):
        merged_cfg = merge_configs(cfg_origin, cfg_local)
        with open(cfg_origin, "w", encoding="utf-8") as f:
            json.dump(merged_cfg, f, indent=2, ensure_ascii=False)
        print("Merged config.json successfully")

    # 4. Copy price_history.db (only written by monitor, backup has latest)
    db_origin = os.path.join(repo_root, "price_history.db")
    db_local = os.path.join(backup_dir, "price_history.db")
    if os.path.exists(db_local):
        shutil.copy2(db_local, db_origin)
        print("Copied price_history.db successfully")

    # 5. Copy mobile/app_sync.json
    sync_origin = os.path.join(repo_root, "mobile", "app_sync.json")
    sync_local = os.path.join(backup_dir, "mobile", "app_sync.json")
    if os.path.exists(sync_local):
        os.makedirs(os.path.dirname(sync_origin), exist_ok=True)
        shutil.copy2(sync_local, sync_origin)
        print("Copied app_sync.json successfully")

    # 6. Copy details_test_output.json
    det_origin = os.path.join(repo_root, "details_test_output.json")
    det_local = os.path.join(backup_dir, "details_test_output.json")
    if os.path.exists(det_local):
        shutil.copy2(det_local, det_origin)
        print("Copied details_test_output.json successfully")

if __name__ == "__main__":
    main()
