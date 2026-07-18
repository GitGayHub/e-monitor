#!/usr/bin/env python3
"""Wait for a specific e-monitor.yml Actions run, then fetch stats paste."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = int(os.environ.get("RUN_ID", "29548046781"))
KICK = os.environ.get("KICK_SHA", "16fcb84")
POLL = int(os.environ.get("POLL", "90"))
MAX_SEC = int(os.environ.get("MAX_SEC", str(55 * 60)))


def token_repo():
    url = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], cwd=ROOT, text=True
    ).strip()
    m = re.search(r"https://([^@]+)@github\.com/(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2).rstrip("/")
    return os.environ.get("GITHUB_TOKEN", ""), "GitGayHub/e-monitor"


def api(tok, path):
    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "e-monitor-wait-run",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    last = None
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as e:
            last = e
            time.sleep(2 + attempt * 2)
    raise RuntimeError(last)


def main():
    tok, repo = token_repo()
    print(f"repo={repo} run_id={RUN_ID} kick={KICK} poll={POLL}s", flush=True)
    t0 = time.time()
    target = None
    while time.time() - t0 < MAX_SEC:
        runs = api(tok, f"/repos/{repo}/actions/runs?per_page=20").get(
            "workflow_runs", []
        )
        print(f"\n=== {int(time.time() - t0)}s ===", flush=True)
        target = None
        for r in runs:
            path = r.get("path") or ""
            sha = (r.get("head_sha") or "")[:9]
            print(
                f"  {r['id']} {r['status']:12} {(r.get('conclusion') or '-'):10} "
                f"{sha} {path} {(r.get('display_title') or '')[:55]}",
                flush=True,
            )
            if int(r["id"]) == RUN_ID:
                target = r
            elif (
                target is None
                and KICK in (r.get("head_sha") or "")
                and "e-monitor.yml" in path
            ):
                target = r
        if not target:
            print("target not in list yet", flush=True)
            time.sleep(POLL)
            continue
        print(
            f"TARGET {target['id']} {target['status']} {target.get('conclusion')}",
            flush=True,
        )
        if target["status"] == "completed":
            print(f"DONE in {int(time.time() - t0)}s", flush=True)
            break
        time.sleep(POLL)
    else:
        print("TIMEOUT", flush=True)
        return 2

    (ROOT / "qa" / "inbox" / "last_gh_run.json").write_text(
        json.dumps(
            {
                "run_id": target["id"],
                "sha": target.get("head_sha"),
                "conclusion": target.get("conclusion"),
                "status": target["status"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    rc = subprocess.call(
        [
            sys.executable,
            str(ROOT / "qa" / "fetch_stats_from_github.py"),
            "--run-id",
            str(target["id"]),
        ],
        cwd=str(ROOT),
    )
    paste = ROOT / "qa" / "inbox" / "stats_paste.txt"
    if paste.exists():
        text = paste.read_text(encoding="utf-8", errors="replace")
        print(f"paste chars={len(text)}", flush=True)
        print(text[:12000], flush=True)
    return 0 if target.get("conclusion") == "success" and rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
