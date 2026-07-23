#!/usr/bin/env python3
"""Wait for GH Actions run after kick SHA; fetch stats; write summary."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KICK = os.environ.get("KICK_SHA", "d86c269d4")
POLL = 90
MAX_SEC = 50 * 60


def token_repo():
    url = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], cwd=ROOT, text=True
    ).strip()
    m = re.search(r"https://([^@]+)@github\.com/(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2).rstrip("/")
    return os.environ.get("GITHUB_TOKEN", ""), "GitGayHub/e-monitor"


def api(tok, path, binary=False):
    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "e-monitor-wait-v2",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
                return data if binary else data.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 502, 503):
                time.sleep(3 + attempt * 3)
                continue
            raise
        except Exception:
            time.sleep(2 + attempt)
    raise RuntimeError(f"API fail {path}")


def main():
    tok, repo = token_repo()
    print(f"repo={repo} kick={KICK} poll={POLL}s", flush=True)
    t0 = time.time()
    target = None
    while time.time() - t0 < MAX_SEC:
        try:
            raw = api(tok, f"/repos/{repo}/actions/runs?per_page=20")
            runs = json.loads(raw).get("workflow_runs", [])
        except Exception as e:
            print(f"list error: {e}", flush=True)
            time.sleep(POLL)
            continue
        print("\n=== runs ===", flush=True)
        for r in runs[:10]:
            print(
                f"  {r['id']} {r['status']:12} {(r.get('conclusion') or '-'):10} "
                f"{(r.get('head_sha') or '')[:9]} {(r.get('display_title') or '')[:55]}",
                flush=True,
            )
        # prefer kick sha on e-monitor workflow
        target = None
        for r in runs:
            sha = r.get("head_sha") or ""
            path = r.get("path") or ""
            title = (r.get("display_title") or "").lower()
            if "e-monitor" not in path and "e-monitor" not in (r.get("name") or "").lower():
                if KICK[:7] not in sha:
                    continue
            if KICK[:7] in sha or "kick gh stats" in title or "re-verify" in title:
                target = r
                break
        if not target:
            for r in runs:
                if "e-monitor.yml" in (r.get("path") or ""):
                    target = r
                    break
        if not target:
            print("no target yet", flush=True)
            time.sleep(POLL)
            continue
        print(
            f"TARGET {target['id']} {target['status']} {target.get('conclusion')} "
            f"sha={target['head_sha'][:9]}",
            flush=True,
        )
        if target["status"] == "completed":
            print(f"DONE in {int(time.time()-t0)}s", flush=True)
            break
        time.sleep(POLL)
    else:
        print("TIMEOUT", flush=True)
        return 2

    # fetch stats
    rc = subprocess.call(
        [
            sys.executable,
            str(ROOT / "qa" / "fetch_stats_from_github.py"),
            "--run-id",
            str(target["id"]),
        ],
        cwd=str(ROOT),
    )
    print("fetch rc", rc, flush=True)
    paste = ROOT / "qa" / "inbox" / "stats_paste.txt"
    if paste.exists():
        text = paste.read_text(encoding="utf-8", errors="replace")
        print(f"paste chars={len(text)}", flush=True)
        print(text[:8000], flush=True)
    meta = {
        "run_id": target["id"],
        "sha": target.get("head_sha"),
        "conclusion": target.get("conclusion"),
        "status": target["status"],
    }
    (ROOT / "qa" / "inbox" / "last_gh_run.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return 0 if target.get("conclusion") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
