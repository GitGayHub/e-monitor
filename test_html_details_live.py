import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

p = Path('monitor.py')
if not p.exists():
    print('preflight: monitor.py not found')
    raise SystemExit(0)

s = p.read_text(encoding='utf-8')
o = s

# 1) HTML gear/all mode: really search all eBay categories.
old_html_cat = '''    device_cat_id = EBAY_DEVICE_CATEGORY_IDS.get(eff_category)
    if device_cat_id:
        params["_sacat"] = device_cat_id
    elif eff_category and eff_category != "all":
        cat_id = _category_id(eff_category)
        if cat_id:
            params["_sacat"] = cat_id
        
    sort_code = _sort_code(filters)
'''
new_html_cat = '''    # Gear/all mode must really search all eBay categories.
    # Do not force inferred device category (phones/consoles/etc.) into _sacat.
    # Programmatic title filters below still reject accessories and garbage.
    if category and category != "all":
        device_cat_id = EBAY_DEVICE_CATEGORY_IDS.get(eff_category)
        if device_cat_id:
            params["_sacat"] = device_cat_id
        elif eff_category and eff_category != "all":
            cat_id = _category_id(eff_category)
            if cat_id:
                params["_sacat"] = cat_id
        
    sort_code = _sort_code(filters)
'''
if old_html_cat in s:
    s = s.replace(old_html_cat, new_html_cat)
else:
    print('preflight: HTML all-category block already patched or not found')

# 2) API fallback should mirror the broad HTML query when it is actually used.
if 'def _build_ebay_api_query(search):' not in s:
    s = s.replace(
        '\ndef _build_ebay_api_params(search, market=None):',
        '''\ndef _build_ebay_api_query(search):
    q = (search.get("query") or "").strip()
    if not q:
        q = _build_smart_search_query(search)
    q = re.sub(r"[()\"']", " ", q)
    q = re.sub(r"\\bredmagic\\b", "red magic", q, flags=re.IGNORECASE)
    q = re.sub(r"\\s+", " ", q).strip()
    return q


def _build_ebay_api_params(search, market=None):'''
    )
s = s.replace('        "q": _build_smart_search_query(search),', '        "q": _build_ebay_api_query(search),')
s = s.replace(
    '    if filters.get("sort") == "price_asc":\n        sort_param = "price"\n',
    '    if filters.get("sort") == "price_asc":\n        sort_param = "price"\n    elif filters.get("sort") == "price_desc":\n        sort_param = "-price"\n'
)

# 3) Track what was actually used in the statistics report: full html / html + api / full api.
s = s.replace(
    '            processed_queries = set()\n             \n            for search in searches:',
    '            processed_queries = set()\n            used_html = False\n            used_api = False\n             \n            for search in searches:'
)
s = s.replace(
    '                bin_results, bin_err = await asyncio.to_thread(fetch_ebay_ex, bin_search, force=True)',
    '                used_html = True\n                bin_results, bin_err = await asyncio.to_thread(fetch_ebay_ex, bin_search, force=True)'
)
s = s.replace(
    '                    bin_api_results, api_err = await asyncio.to_thread(fetch_ebay_api_ex, bin_search, force=True)',
    '                    used_api = True\n                    bin_api_results, api_err = await asyncio.to_thread(fetch_ebay_api_ex, bin_search, force=True)'
)
s = s.replace(
    '                auc_results, auc_err = await asyncio.to_thread(fetch_ebay_ex, auc_search, force=True)',
    '                used_html = True\n                auc_results, auc_err = await asyncio.to_thread(fetch_ebay_ex, auc_search, force=True)'
)
s = s.replace(
    '                    auc_api_results, api_err = await asyncio.to_thread(fetch_ebay_api_ex, auc_search, force=True)',
    '                    used_api = True\n                    auc_api_results, api_err = await asyncio.to_thread(fetch_ebay_api_ex, auc_search, force=True)'
)
s = s.replace(
    '            footer_str += f"\\nℹ️ <i>Версия: {_get_version_string()}</i>"',
    '            if used_html and used_api:\n                search_mode = "html + api"\n            elif used_api:\n                search_mode = "full api"\n            else:\n                search_mode = "full html"\n            footer_str += f"\\nℹ️ <i>Версия: {_get_version_string()}</i>\\n🔎 <i>Поиск: {search_mode}</i>"'
)

if s != o:
    p.write_text(s, encoding='utf-8')
    print('preflight patched HTML/API parity and source footer')
else:
    print('preflight: no monitor.py changes')
