#!/usr/bin/env python3
"""Pull statistics report content from GitHub Actions logs (same text the bot logs before Telegram).

No Telegram UI, no paste from the user. Uses git remote token or GITHUB_TOKEN / GH_PAT.

Usage:
  python qa/fetch_stats_from_github.py
  python qa/fetch_stats_from_github.py --run-id 123456
  python qa/fetch_stats_from_github.py --out qa/inbox/stats_paste.txt
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = Path(__file__).resolve().parent / "inbox" / "stats_paste.txt"
DEFAULT_JSON = Path(__file__).resolve().parent / "inbox" / "stats_from_github.json"


def _token_and_repo():
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
    repo = os.environ.get("GITHUB_REPO") or os.environ.get("GITHUB_REPOSITORY") or "GitGayHub/e-monitor"
    return tok, repo


def api_get(tok: str, path: str, binary: bool = False):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "e-monitor-qa-fetch-stats",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    last_err = None
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
                return data if binary else data.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (403, 502, 503, 429):
                time.sleep(2 + attempt * 2)
                continue
            raise
        except Exception as e:
            last_err = e
            time.sleep(1 + attempt)
    raise RuntimeError(f"GitHub API failed for {path}: {last_err}")


def list_runs(tok: str, repo: str, per_page: int = 40):
    raw = api_get(tok, f"/repos/{repo}/actions/runs?per_page={per_page}")
    return json.loads(raw).get("workflow_runs", [])


def pick_run(runs, run_id: int | None):
    if run_id:
        for r in runs:
            if int(r["id"]) == int(run_id):
                return r
        raise SystemExit(f"run_id {run_id} not in recent runs list")
    # Prefer completed success runs that likely contain monitor output
    for r in runs:
        if r.get("status") != "completed" or r.get("conclusion") != "success":
            continue
        name = (r.get("name") or "") + " " + ((r.get("path") or ""))
        if "monitor" in name.lower() or "e-monitor" in name.lower() or "E Monitor" in (r.get("name") or ""):
            return r
    for r in runs:
        if r.get("status") == "completed" and r.get("conclusion") == "success":
            return r
    raise SystemExit("No successful Actions run found")


def _strip_gha_prefixes(text: str) -> str:
    """Remove GitHub Actions / python logging prefixes from each line."""
    out = []
    for line in text.splitlines():
        # GHA: 2026-07-16T22:15:51.5102924Z content
        line = re.sub(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s+", "", line)
        # python logging: 2026-07-16 22:15:51,510 - content
        line = re.sub(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[.,]\d+\s+-\s+", "", line)
        # group/step noise sometimes left as-is
        out.append(line)
    return "\n".join(out)


def extract_stats_blocks(text: str) -> list[tuple[str, str]]:
    """Return list of (query, plain block) from monitor / GHA logs."""
    clean = _strip_gha_prefixes(text)
    lines = clean.splitlines()
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        m = re.match(r"Generated statistics block for '([^']+)':\s*$", lines[i])
        if not m:
            i += 1
            continue
        query = m.group(1)
        i += 1
        body: list[str] = []
        while i < len(lines):
            line = lines[i]
            if line.startswith("Generated statistics block for '"):
                break
            # End of this product — rest is fetch noise for the next search
            if re.match(
                r"^(Fetching:|Scraping item|eBay API|📊|=== |=====|Top \d+|eBay session)",
                line,
            ):
                break
            if re.match(r"^.+: (HTML |API |0 results|fetch )", line):
                break
            body.append(line)
            i += 1
        blocks.append((query, "\n".join(body)))
    return blocks


def blocks_to_paste(blocks: list[tuple[str, str]]) -> str:
    """Convert log HTML-ish blocks into parse_stats_paste-friendly text."""
    parts = []
    seen_q = set()
    for query, body in blocks:
        # de-dupe if the same step appears in combined + per-step logs
        key = query.strip().lower()
        if key in seen_q:
            continue
        seen_q.add(key)
        lines = []
        for line in body.splitlines():
            line = re.sub(r"</?b>", "", line)
            line = re.sub(r"</?code>", "", line)
            line = re.sub(r'<a href="([^"]+)">.*?</a>', r"\1", line)
            line = re.sub(r"<[^>]+>", "", line)
            line = line.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            lines.append(line.rstrip())
        text = "\n".join(lines).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts) + ("\n" if parts else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--meta", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--max-runs", type=int, default=40)
    args = ap.parse_args()

    tok, repo = _token_and_repo()
    if not tok:
        print("ERROR: no GitHub token (remote URL or GITHUB_TOKEN)", file=sys.stderr)
        sys.exit(1)

    runs = list_runs(tok, repo, per_page=args.max_runs)
    # Scan several successful runs until we find statistics blocks
    candidates = []
    if args.run_id:
        candidates = [pick_run(runs, args.run_id)]
    else:
        for r in runs:
            if r.get("status") == "completed" and r.get("conclusion") == "success":
                candidates.append(r)

    chosen = None
    all_blocks: list[tuple[str, str]] = []
    used_files = []
    for r in candidates[:15]:
        rid = r["id"]
        print(f"Trying run {rid} {r.get('created_at')} {(r.get('head_commit') or {}).get('message', '')[:50]}")
        try:
            zbytes = api_get(tok, f"/repos/{repo}/actions/runs/{rid}/logs", binary=True)
        except Exception as e:
            print(f"  skip logs: {e}")
            continue
        blocks = []
        with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
            for name in zf.namelist():
                if not name.endswith(".txt"):
                    continue
                data = zf.read(name).decode("utf-8", errors="replace")
                found = extract_stats_blocks(data)
                if found:
                    blocks.extend(found)
                    used_files.append(name)
                    print(f"  {name}: {len(found)} blocks")
        if blocks:
            chosen = r
            all_blocks = blocks
            break

    if not all_blocks:
        # Fallback: local monitor_debug_tail.txt
        tail = ROOT / "monitor_debug_tail.txt"
        if tail.exists():
            print("Fallback: monitor_debug_tail.txt")
            all_blocks = extract_stats_blocks(tail.read_text(encoding="utf-8", errors="replace"))
        if not all_blocks:
            print("ERROR: no Generated statistics block found in recent runs or local tail", file=sys.stderr)
            sys.exit(2)

    paste = blocks_to_paste(all_blocks)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(paste, encoding="utf-8")
    meta = {
        "source": "github_actions_logs" if chosen else "monitor_debug_tail",
        "run_id": chosen["id"] if chosen else None,
        "run_url": chosen.get("html_url") if chosen else None,
        "created_at": chosen.get("created_at") if chosen else None,
        "blocks": len(all_blocks),
        "queries": [q for q, _ in all_blocks],
        "log_files": used_files,
        "out": str(args.out),
    }
    args.meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} ({len(all_blocks)} products, {len(paste)} chars)")
    print(f"Meta {args.meta}")
    for q, _ in all_blocks[:8]:
        print(" -", q)
    if len(all_blocks) > 8:
        print(f" ... +{len(all_blocks) - 8} more")


if __name__ == "__main__":
    main()
