from pathlib import Path
import re, shutil

p = Path("qa/inbox/postfix_local_stats.log")
dst = Path("qa/inbox/postfix_local_stats_snap.log")
try:
    shutil.copyfile(p, dst)
except Exception:
    dst.write_bytes(p.read_bytes())
raw = dst.read_bytes()
if raw[:2] == b"\xff\xfe" or (len(raw) > 2 and raw[1] == 0):
    t = raw.decode("utf-16", errors="replace")
else:
    t = raw.decode("utf-8", errors="replace")
print("len", len(t))
prods = re.findall(r"Generated statistics block for '([^']+)'", t)
print("blocks", len(prods), "done", "=== Done ===" in t)
for x in prods:
    print(" -", x)
print("TAIL:")
print("\n".join(t.splitlines()[-10:]))
