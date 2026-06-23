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

# Current tg-monitor layout uses a fixed 7-char price column.
s = s.replace('                max_len = max(lengths) if lengths else 4\n                if max_len < 4:\n                    max_len = 4', '                max_len = 7')
s = s.replace('                dashes = "-" * max_len', '                dashes = "---"')

# tg-monitor pair logic: the two rows in a pair share the same click-link offset.
s = s.replace(
    '                lbl_auc_bo = "Auktion+"\n                \n                def _shorten_time_left',
    '                lbl_auc_bo = "Auktion+"\n                \n                def _tg_link_spaces(*vals):\n                    ok = True\n                    for v in vals:\n                        if v is not None and int(v) >= 100:\n                            ok = False\n                            break\n                    return 10 if ok else 9\n                \n                bin_link_spaces = _tg_link_spaces(p1_base, p2_base)\n                auc_link_spaces = _tg_link_spaces(p3_base, p4_base)\n                \n                def _shorten_time_left'
)

# Remove verdict padding that makes rows wrap on Android.
s = s.replace('                            v_text_padded = v_text.ljust(10)', '                            v_text_padded = v_text')
s = s.replace('                        v_text_padded = v_text.ljust(10)', '                        v_text_padded = v_text')

# Match tg-monitor row rendering: emoji outside code, table columns inside code, verdict outside code.
old_row = '                        # Verdict first, then time info\n                        row_lines.append(f"<code>{emoji} {label} {padded_price}  │ {verdict_info}{time_info}</code>")'
new_row = '                        row_lines.append(f"{emoji} <code>{label} {padded_price} | </code>{verdict_info}")\n                        if time_info:\n                            row_lines.append(f"<code>{time_info.strip()}</code>")'
if old_row in s:
    s = s.replace(old_row, new_row)

s = s.replace('                        row_lines.append(f"<code>{emoji} {label} {padded_dashes}  │ {verdict_info}</code>")',
              '                        row_lines.append(f"{emoji} <code>{label} {padded_dashes} | </code>{verdict_info}")')

# Add a link spacing argument to make_aligned_row and use the pair-level value.
s = s.replace(
    '                def make_aligned_row(emoji, label, item, total_price_val, total_price_str, is_auction=False):',
    '                def make_aligned_row(emoji, label, item, total_price_val, total_price_str, is_auction=False, link_spaces_len=9):'
)
s = s.replace(
    '                        spaces_str = " " * (len(label) + 1)',
    '                        spaces_str = " " * link_spaces_len'
)
s = s.replace('price_num < 10 else 9', 'price_num < 100 else 9')
s = s.replace(
    'bin_lines.extend(make_aligned_row(lbl_bin_emoji, lbl_bin, cheapest_bin_no_bo, p1_val, p1, is_auction=False))',
    'bin_lines.extend(make_aligned_row(lbl_bin_emoji, lbl_bin, cheapest_bin_no_bo, p1_val, p1, is_auction=False, link_spaces_len=bin_link_spaces))'
)
s = s.replace(
    'bin_lines.extend(make_aligned_row(lbl_bin_bo_emoji, lbl_bin_bo, cheapest_bin_bo, p2_val, p2, is_auction=False))',
    'bin_lines.extend(make_aligned_row(lbl_bin_bo_emoji, lbl_bin_bo, cheapest_bin_bo, p2_val, p2, is_auction=False, link_spaces_len=bin_link_spaces))'
)
s = s.replace(
    'auc_lines.extend(make_aligned_row(lbl_auc_emoji, lbl_auc, cheapest_auc_no_bo, p3_val, p3, is_auction=True))',
    'auc_lines.extend(make_aligned_row(lbl_auc_emoji, lbl_auc, cheapest_auc_no_bo, p3_val, p3, is_auction=True, link_spaces_len=auc_link_spaces))'
)
s = s.replace(
    'auc_lines.extend(make_aligned_row(lbl_auc_bo_emoji, lbl_auc_bo, cheapest_auc_bo, p4_val, p4, is_auction=True))',
    'auc_lines.extend(make_aligned_row(lbl_auc_bo_emoji, lbl_auc_bo, cheapest_auc_bo, p4_val, p4, is_auction=True, link_spaces_len=auc_link_spaces))'
)

# Match tg-monitor: link icon outside monospace, spaces inside monospace.
s = s.replace('<code>🔗 {spaces_str}</code>', '🔗 <code>{spaces_str}</code>')

# Footer source label, static and safe for current GitHub HTML-primary run.
old_footer = '            footer_str += f"\\nℹ️ <i>Версия: {_get_version_string()}</i>"'
new_footer = '            footer_str += f"\\nℹ️ <i>Версия: {_get_version_string()}\\n🔎 Поиск: full html</i>"'
if old_footer in s:
    s = s.replace(old_footer, new_footer)

if s != o:
    p.write_text(s, encoding='utf-8')
    print('preflight: using tg-monitor row rendering scheme')
else:
    print('preflight: no monitor.py changes')
