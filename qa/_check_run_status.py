#!/usr/bin/env python3
import json, re, subprocess, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
url = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=ROOT, text=True).strip()
m = re.search(r"https://([^@]+)@github\.com/(.+?)(?:\.git)?$", url)
tok, repo = m.group(1), m.group(2).rstrip("/")


def api(path):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "e-monitor-check",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def age(iso):
    if not iso:
        return "?"
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    sec = int((datetime.now(timezone.utc) - t).total_seconds())
    return f"{sec // 60}m{sec % 60}s"


print("=== recent e-monitor runs ===")
inprog = 0
for r in api(f"/repos/{repo}/actions/runs?per_page=15")["workflow_runs"]:
    path = r.get("path") or ""
    if "e-monitor.yml" not in path:
        continue
    if r["status"] == "in_progress":
        inprog += 1
    print(
        r["id"],
        r["status"],
        r.get("conclusion") or "-",
        (r.get("head_sha") or "")[:9],
        "age",
        age(r.get("run_started_at")),
        (r.get("display_title") or "")[:48],
    )

print(f"\nin_progress count: {inprog}")

rid = 29549171035
r = api(f"/repos/{repo}/actions/runs/{rid}")
print(f"\n=== target {rid} ===")
print("status", r["status"], "conclusion", r.get("conclusion"))
print("started", r.get("run_started_at"), "age", age(r.get("run_started_at")))
print("updated", r.get("updated_at"), "age", age(r.get("updated_at")))
jobs = api(f"/repos/{repo}/actions/runs/{rid}/jobs")
for j in jobs.get("jobs", []):
    print("job", j["name"], j["status"], j.get("conclusion"), "age", age(j.get("started_at")))
    for s in j.get("steps") or []:
        if s.get("status") == "pending" and not s.get("conclusion"):
            continue
        print(
            " ",
            s.get("number"),
            s.get("name"),
            s.get("status"),
            s.get("conclusion"),
            "start",
            s.get("started_at"),
            "done",
            s.get("completed_at"),
        )
