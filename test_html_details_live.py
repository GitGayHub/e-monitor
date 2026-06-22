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

# Compact limit line: emojis are separators, no extra pipe characters.
s = s.replace('                limit_str = " | ".join(parts)', '                limit_str = " ".join(parts)')

# Short labels with fixed width columns, like tg-monitor visual style.
s = s.replace('                lbl_bin = "Sofortkauf  "', '                lbl_bin = "Sofort  "')
s = s.replace('                lbl_bin_bo = "Sofortkauf+ "', '                lbl_bin_bo = "Sofort+ "')
s = s.replace('                lbl_auc = "Auktion     "', '                lbl_auc = "Auktion "')
s = s.replace('                lbl_auc_bo = "Auktion+    "', '                lbl_auc_bo = "Auktion+"')

# Missing prices stay as 3 dashes, but remain right-aligned in the price column.
s = s.replace('                dashes = "-" * max_len', '                dashes = "---"')

# Remove verdict padding that makes rows wrap on Android.
s = s.replace('                            v_text_padded = v_text.ljust(10)', '                            v_text_padded = v_text')
s = s.replace('                        v_text_padded = v_text.ljust(10)', '                        v_text_padded = v_text')

# Put auction time on its own short line instead of forcing the main row to wrap.
old_row = '                        # Verdict first, then time info\n                        row_lines.append(f"<code>{emoji} {label} {padded_price}  │ {verdict_info}{time_info}</code>")'
new_row = '                        row_lines.append(f"<code>{emoji} {label} {padded_price} | {verdict_info}</code>")\n                        if time_info:\n                            row_lines.append(f"<code>{time_info.strip()}</code>")'
if old_row in s:
    s = s.replace(old_row, new_row)

s = s.replace('                        row_lines.append(f"<code>{emoji} {label} {padded_dashes}  │ {verdict_info}</code>")',
              '                        row_lines.append(f"<code>{emoji} {label} {padded_dashes} | {verdict_info}</code>")')

# Footer source label, static and safe for current GitHub HTML-primary run.
old_footer = '            footer_str += f"\\nℹ️ <i>Версия: {_get_version_string()}</i>"'
new_footer = '            footer_str += f"\\nℹ️ <i>Версия: {_get_version_string()}\\n🔎 Поиск: full html</i>"'
if old_footer in s:
    s = s.replace(old_footer, new_footer)

if s != o:
    p.write_text(s, encoding='utf-8')
    print('preflight: aligned Telegram report columns like tg-monitor')
else:
    print('preflight: no monitor.py changes')
