import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

try:
    import monitor_runtime_patch
    monitor_runtime_patch.patch_monitor()
    monitor_runtime_patch.migrate_config()
    print('monitor patch applied')
except Exception as exc:
    print(f'monitor patch skipped: {exc}')

p = Path('monitor.py')
if p.exists():
    s = p.read_text(encoding='utf-8')
    o = s
    s = s.replace('    if filters.get("sort") == "price_asc":\n        sort_param = "price"\n', '    if filters.get("sort") == "price_asc":\n        sort_param = "price"\n    elif filters.get("sort") == "price_desc":\n        sort_param = "-price"\n')
    s = s.replace('                auc_bo = [item for item in filtered if item.get("auction") and item.get("best_offer") and item.get("bids_count") in (0, None)]', '                auc_bo = [item for item in filtered if item.get("auction") and item.get("bids_count") in (0, None)]')
    s = s.replace('                auc_bo = [item for item in filtered if item.get("auction") and item.get("best_offer")]', '                auc_bo = [item for item in filtered if item.get("auction") and item.get("bids_count") in (0, None)]')
    if s != o:
        p.write_text(s, encoding='utf-8')
        print('monitor preflight patch applied')
