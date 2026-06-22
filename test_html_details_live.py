import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

p = Path('monitor.py')
if not p.exists():
    print('preflight: monitor.py not found')
    raise SystemExit(0)

s = p.read_text(encoding='utf-8')
o = s

# Keep GitHub runs in diagnostic/report mode so they always send the report.
old_mode = '        test_summary_mode = _is_statistics_mode(config)'
new_mode = '        test_summary_mode = True if os.environ.get("GITHUB_ACTIONS") == "true" else _is_statistics_mode(config)'
if old_mode in s:
    s = s.replace(old_mode, new_mode)

# In gear/all mode, HTML must really search all categories.
old_cat = '''    device_cat_id = EBAY_DEVICE_CATEGORY_IDS.get(eff_category)
    if device_cat_id:
        params["_sacat"] = device_cat_id
    elif eff_category and eff_category != "all":
        cat_id = _category_id(eff_category)
        if cat_id:
            params["_sacat"] = cat_id
        
    sort_code = _sort_code(filters)
'''
new_cat = '''    if category and category != "all":
        device_cat_id = EBAY_DEVICE_CATEGORY_IDS.get(eff_category)
        if device_cat_id:
            params["_sacat"] = device_cat_id
        elif eff_category and eff_category != "all":
            cat_id = _category_id(eff_category)
            if cat_id:
                params["_sacat"] = cat_id
        
    sort_code = _sort_code(filters)
'''
if old_cat in s:
    s = s.replace(old_cat, new_cat)

# Smaller Telegram chunks, but keep normal HTML formatting.
s = s.replace('            chunk_size = 8', '            chunk_size = 4')

# Footer source label, static and safe for current GitHub HTML-primary run.
old_footer = '            footer_str += f"\\nℹ️ <i>Версия: {_get_version_string()}</i>"'
new_footer = '            footer_str += f"\\nℹ️ <i>Версия: {_get_version_string()}\\n🔎 Поиск: full html</i>"'
if old_footer in s:
    s = s.replace(old_footer, new_footer)

if s != o:
    p.write_text(s, encoding='utf-8')
    print('preflight: restored safe HTML all-category report')
else:
    print('preflight: no monitor.py changes')
