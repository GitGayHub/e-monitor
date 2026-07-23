#!/usr/bin/env python3
"""Wait for GitHub Actions stats run after kick commit; fetch and summarize."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KICK_SHA = "9a4c5e64e"
POLL_SEC = 60
MAX_WAIT_SEC = 90 * 60  # 90 min stats can be long


def token_repo():
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
    except Exception:
        url = ""
    m = re.search(r"https://([^@]+)@github\.com/(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2).rstrip("/")
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT") or ""
    repo = os.environ.get("GITHUB_REPO") or "GitGayHub/e-monitor"
    return tok, repo


def api_get(tok: str, path: str, binary: bool = False):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "e-monitor-wait-check",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    last_err = None
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
                return data if binary else data.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (403, 502, 503, 429):
                time.sleep(3 + attempt * 3)
                continue
            raise
        except Exception as e:
            last_err = e
            time.sleep(2 + attempt)
    raise RuntimeError(f"API fail {path}: {last_err}")


def list_runs(tok: str, repo: str):
    raw = api_get(tok, f"/repos/{repo}/actions/runs?per_page=30")
    return json.loads(raw).get("workflow_runs", [])


def find_target_run(runs):
    """Prefer completed/in-progress run for kick SHA on e-monitor workflow."""
    candidates = []
    for r in runs:
        path = r.get("path") or ""
        name = r.get("name") or ""
        if "e-monitor" not in path and "e-monitor" not in name.lower():
            # still allow if head_sha matches kick
            pass
        sha = (r.get("head_sha") or "")[:9]
        title = r.get("display_title") or r.get("head_commit", {}).get("message", "") or ""
        if KICK_SHA in sha or "kick verification" in title.lower() or "empty-bucket" in title.lower():
            candidates.append(r)
        if sha.startswith(KICK_SHA[:7]):
            candidates.append(r)
    # de-dupe by id
    seen = set()
    out = []
    for r in candidates:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(r)
    if out:
        return out[0]
    # fallback: newest workflow run for e-monitor.yml
    for r in runs:
        if "e-monitor.yml" in (r.get("path") or ""):
            return r
    return runs[0] if runs else None


def main():
    tok, repo = token_repo()
    if not tok:
        print("ERROR: no token")
        return 1
    print(f"repo={repo} kick={KICK_SHA} poll={POLL_SEC}s max={MAX_WAIT_SEC}s", flush=True)

    t0 = time.time()
    target = None
    while time.time() - t0 < MAX_WAIT_SEC:
        try:
            runs = list_runs(tok, repo)
        except Exception as e:
            elapsed = int(time.time() - t0)
            print(f"list_runs error after {elapsed}s: {e} — sleep {POLL_SEC}s", flush=True)
            time.sleep(POLL_SEC)
            continue
        print("\n=== runs ===", flush=True)
        for r in runs[:12]:
            print(
                f"  {r['id']} {r['status']:12} {(r.get('conclusion') or '-'):10} "
                f"{r['created_at']} {(r.get('head_sha') or '')[:9]} "
                f"{(r.get('display_title') or '')[:50]}",
                flush=True,
            )
        target = find_target_run(runs)
        if not target:
            print("no run yet, waiting...", flush=True)
            time.sleep(POLL_SEC)
            continue
        rid = target["id"]
        st = target["status"]
        conc = target.get("conclusion")
        print(f"\nTARGET id={rid} status={st} conclusion={conc} sha={(target.get('head_sha') or '')[:9]}", flush=True)
        if st == "completed":
            print(f"DONE after {int(time.time()-t0)}s", flush=True)
            break
        elapsed = int(time.time() - t0)
        print(f"still {st} elapsed={elapsed}s — sleep {POLL_SEC}s", flush=True)
        time.sleep(POLL_SEC)
    else:
        print("TIMEOUT waiting for run", flush=True)
        return 2

    # Fetch stats via existing script
    print("\n=== fetch_stats_from_github ===", flush=True)
    rc = subprocess.call(
        [sys.executable, str(ROOT / "qa" / "fetch_stats_from_github.py"), "--run-id", str(target["id"])],
        cwd=str(ROOT),
    )
    print(f"fetch rc={rc}", flush=True)

    paste = ROOT / "qa" / "inbox" / "stats_paste.txt"
    meta = ROOT / "qa" / "inbox" / "stats_from_github.json"
    if paste.exists():
        text = paste.read_text(encoding="utf-8", errors="replace")
        print(f"\n=== stats_paste ({len(text)} chars) ===", flush=True)
        print(text[:12000], flush=True)
        # quick bucket summary
        products = re.findall(r"(?m)^(?:📱|🖥️|🎧|🎮|📺|💻|⌚|📷|🔑|📦|🟣|🟢|🟡|🔴|•|\*)?\s*(.+?)\s*$", text)
        empty_markers = text.count("---") + text.count("Не найдено") + text.count("не найдено")
        purple = text.count("🟣")
        green = text.count("🟢")
        print(f"\n=== summary ---={text.count('---')} not_found={text.count('Не найдено')} purple={purple} green={green} ===", flush=True)
    else:
        print("NO stats_paste.txt", flush=True)

    if meta.exists():
        print("meta:", meta.read_text(encoding="utf-8", errors="replace")[:2000], flush=True)

    # Parse if available
    parse = ROOT / "qa" / "parse_stats_paste.py"
    if parse.exists() and paste.exists():
        print("\n=== parse_stats_paste ===", flush=True)
        subprocess.call([sys.executable, str(parse)], cwd=str(ROOT))

    return 0 if target and target.get("status") == "completed" else 3


if __name__ == "__main__":
    sys.exit(main())
