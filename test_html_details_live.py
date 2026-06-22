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
    s = s.replace('EBAY_SOURCE = os.environ.get("EBAY_SOURCE", "auto").strip().lower()', 'EBAY_SOURCE = "api_first"')
    s = s.replace('    if filters.get("sort") == "price_asc":\n        sort_param = "price"\n', '    if filters.get("sort") == "price_asc":\n        sort_param = "price"\n    elif filters.get("sort") == "price_desc":\n        sort_param = "-price"\n')
    if s != o:
        p.write_text(s, encoding='utf-8')
        print('monitor preflight patch applied')
