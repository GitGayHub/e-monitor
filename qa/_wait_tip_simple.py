#!/usr/bin/env python3
import json, re, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
url = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=ROOT, text=True).strip()
m = re.search(r"https://([^@]+)@github\.com/(.+?)(?:\.git)?$", url)
tok, repo = m.group(1), m.group(2).rstrip("/")
H = {
    "Authorization": f"Bearer {tok}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "e-monitor-wait",
    "X-GitHub-Api-Version": "2022-11-28",
    "Content-Type": "application/json",
}


def api(path, method="GET", data=None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}", data=data, method=method, headers=H
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = resp.read().decode()
        return resp.status, (json.loads(body) if body else {})


_, data = api("/actions/runs?per_page=12")
runs = [r for r in data.get("workflow_runs", []) if "e-monitor.yml" in (r.get("path") or "")]
active = []
for r in runs:
    print(r["id"], r["status"], r.get("conclusion") or "-", (r.get("head_sha") or "")[:9])
    if r["status"] in ("in_progress", "pending", "queued", "waiting"):
        active.append(r)

if len(active) > 1:
    keep = max(a["id"] for a in active)
    for a in active:
        if a["id"] != keep:
            try:
                code, _ = api(f"/actions/runs/{a['id']}/cancel", method="POST", data=b"{}")
                print("cancel", a["id"], code)
            except Exception as e:
                print("cancel err", a["id"], e)

if not active:
    print("no active run")
    sys.exit(1)
rid = max(active, key=lambda x: x["id"])["id"]
print("WAIT", rid)
t0 = time.time()
while time.time() - t0 < 3200:
    try:
        _, d = api(f"/actions/runs/{rid}")
        print(int(time.time() - t0), d["status"], d.get("conclusion"), (d.get("head_sha") or "")[:9], flush=True)
        if d["status"] == "completed":
            (ROOT / "qa" / "inbox" / "tip_run_id.txt").write_text(str(rid), encoding="utf-8")
            print("DONE", d.get("conclusion"))
            sys.exit(0 if d.get("conclusion") == "success" else 1)
    except Exception as e:
        print("err", e, flush=True)
    time.sleep(55)
print("TIMEOUT")
sys.exit(2)
