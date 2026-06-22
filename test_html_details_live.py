import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

p = Path('monitor.py')
if not p.exists():
    print('preflight: monitor.py not found')
    raise SystemExit(0)

s = p.read_text(encoding='utf-8')
o = s

old = '        test_summary_mode = _is_statistics_mode(config)'
new = '        test_summary_mode = True if os.environ.get("GITHUB_ACTIONS") == "true" else _is_statistics_mode(config)'

if old in s:
    s = s.replace(old, new)
    p.write_text(s, encoding='utf-8')
    print('preflight: forced GitHub diagnostic report mode')
elif new in s:
    print('preflight: GitHub diagnostic report mode already forced')
else:
    print('preflight: statistics mode line not found')

if s == o:
    print('preflight: no monitor.py changes')
