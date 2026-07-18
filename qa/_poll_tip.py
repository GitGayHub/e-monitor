#!/usr/bin/env python3
"""Poll tip e-monitor run until complete, then fetch stats paste."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = int(os.environ.get("RUN_ID", "29557545188"))
POLL = int(os.environ.get("POLL", "45"))
MAX_SEC = int(os.environ.get("MAX_SEC", str(50 * 60)))


def token_repo():
    url = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], cwd=ROOT, text=True
    ).strip()
    m = re.search(r"https://([^@]+)@github\.com/(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2).rstrip("/")
    return os.environ.get("GITHUB_TOKEN", ""), "GitGayHub/e-monitor"


def api(tok, path):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "e-monitor-poll-tip",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def main():
    tok, repo = token_repo()
    print(f"repo={repo} run_id={RUN_ID} poll={POLL}s", flush=True)
    t0 = time.time()
    while time.time() - t0 < MAX_SEC:
        d = api(tok, f"/repos/{repo}/actions/runs/{RUN_ID}")
        st = d.get("status")
        c = d.get("conclusion")
        sha = (d.get("head_sha") or "")[:9]
        elapsed = int(time.time() - t0)
        print(
            f"[{elapsed}s] {st} {c or '-'} sha={sha} updated={d.get('updated_at')}",
            flush=True,
        )
        if st == "completed":
            print(f"DONE conclusion={c}", flush=True)
            (ROOT / "qa" / "inbox" / "last_gh_run.json").write_text(
                json.dumps(
                    {
                        "run_id": RUN_ID,
                        "sha": d.get("head_sha"),
                        "conclusion": c,
                        "status": st,
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
                    str(RUN_ID),
                ],
                cwd=str(ROOT),
            )
            paste = ROOT / "qa" / "inbox" / "stats_paste.txt"
            if paste.exists():
                text = paste.read_text(encoding="utf-8", errors="replace")
                print(f"paste chars={len(text)}", flush=True)
                # summary buckets
                import re as _re

                prices = len(_re.findall(r"\s\d+€", text))
                empty = text.count("Не найдено")
                fail = text.count("сбой загрузки")
                block = text.count("eBay block")
                rl = text.count("Rate limit")
                print(
                    f"SUMMARY prices={prices} empty={empty} fail={fail} block={block} rl={rl}",
                    flush=True,
                )
                # Z80 LV snippet
                if "Nubia Z80 LV" in text or "Z80 LV" in text:
                    idx = text.find("Z80 LV")
                    print("--- Z80 LV ---", flush=True)
                    print(text[max(0, idx - 20) : idx + 350], flush=True)
                print("--- PASTE HEAD ---", flush=True)
                print(text[:8000], flush=True)
            return 0 if c == "success" and rc == 0 else 1
        time.sleep(POLL)
    print("TIMEOUT", flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main())
