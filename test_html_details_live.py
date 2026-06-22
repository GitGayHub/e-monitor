import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

p = Path('monitor.py')
if not p.exists():
    print('preflight: monitor.py not found')
else:
    s = p.read_text(encoding='utf-8')
    o = s
    old = '''    device_cat_id = EBAY_DEVICE_CATEGORY_IDS.get(eff_category)
    if device_cat_id:
        params["_sacat"] = device_cat_id
    elif eff_category and eff_category != "all":
        cat_id = _category_id(eff_category)
        if cat_id:
            params["_sacat"] = cat_id
        
    sort_code = _sort_code(filters)
'''
    new = '''    # Gear/all mode must really search all eBay categories.
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
    if old in s:
        s = s.replace(old, new)
    else:
        print('preflight: html category block already patched or not found')
    if s != o:
        p.write_text(s, encoding='utf-8')
        print('preflight patched HTML all-category search')
    else:
        print('preflight: no monitor.py changes')
