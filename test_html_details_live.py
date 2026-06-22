import json
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
    s = s.replace('                auc_bo = [item for item in filtered if item.get("auction") and item.get("best_offer") and item.get("bids_count") in (0, None)]', '                auc_bo = [item for item in filtered if item.get("auction") and item.get("bids_count") in (0, None)]')
    s = s.replace('                auc_bo = [item for item in filtered if item.get("auction") and item.get("best_offer")]', '                auc_bo = [item for item in filtered if item.get("auction") and item.get("bids_count") in (0, None)]')
    if s != o:
        p.write_text(s, encoding='utf-8')
        print('monitor preflight patch applied')

try:
    import monitor
    cfg = monitor.ConfigManager()
    debug = {}
    base = {
        'id': 'debug_redmagic_auc',
        'query': 'Redmagic 11 Pro',
        'filters': {'listing_type': 'auction', 'location': 'worldwide', 'condition': 'any', 'max_price': None, 'sort': 'price_desc'},
        'exclude_words': ['11s', '11 s', '11spro', '11s pro', '11 s pro'],
        'include_words': [],
        'exclude_sellers': [],
    }
    for q in ['Redmagic 11 Pro', 'Red Magic 11 Pro', 'Red Magic 11', 'Redmagic 11']:
        ss = json.loads(json.dumps(base))
        ss['query'] = q
        items, err = monitor.fetch_ebay_api_ex(ss, force=True)
        flt = monitor.filter_results(items, ss, cfg, skip_seen=True, is_statistics=True)
        debug[q] = {
            'err': err,
            'raw_count': len(items),
            'filtered_count': len(flt),
            'raw_top': [{'id': i.get('item_id'), 'title': i.get('title'), 'total': i.get('total_price'), 'bo': i.get('best_offer'), 'bids': i.get('bids_count')} for i in items[:10]],
            'filtered_top': [{'id': i.get('item_id'), 'title': i.get('title'), 'total': i.get('total_price'), 'bo': i.get('best_offer'), 'bids': i.get('bids_count')} for i in flt[:10]],
        }
    Path('details_test_output.json').write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding='utf-8')
    print('redmagic api debug written')
except Exception as exc:
    Path('details_test_output.json').write_text(json.dumps({'debug_error': str(exc)}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'redmagic api debug failed: {exc}')
