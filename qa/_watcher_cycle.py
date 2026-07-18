#!/usr/bin/env python3
"""One-shot health snapshot for e-monitor watcher (no secrets)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PASTE = ROOT / "qa" / "inbox" / "stats_paste.txt"
STATUS = ROOT / "qa" / "results" / "WATCHER_STATUS.md"


def token_repo():
    url = subprocess.check_output(
        ["git", "remote", "get-url", "origin"], cwd=ROOT, text=True
    ).strip()
    m = re.search(r"https://([^@]+)@github\.com/(.+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2).rstrip("/")
    return "", "GitGayHub/e-monitor"


def api(tok, path):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "e-monitor-watcher-cycle",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def mode():
    p = ROOT / "mode.txt"
    return p.read_text(encoding="utf-8", errors="replace").strip() if p.exists() else "?"


def git_tip():
    return subprocess.check_output(
        ["git", "rev-parse", "--short=9", "HEAD"], cwd=ROOT, text=True
    ).strip()


def analyze_paste(text: str) -> dict:
    return {
        "chars": len(text),
        "prices_eur": len(re.findall(r"\s\d+€", text)),
        "empty": text.count("Не найдено"),
        "fail": text.count("сбой загрузки"),
        "block": text.count("eBay block"),
        "rl": text.count("Rate limit"),
        "z80_lv_block": bool(
            re.search(r"Z80 LV[\s\S]{0,400}eBay block", text)
            or re.search(r"Z80 Ultra Leading[\s\S]{0,400}eBay block", text)
        ),
    }


def main():
    tok, repo = token_repo()
    tip = git_tip()
    md = mode()
    utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    runs = []
    if tok:
        raw = api(tok, f"/repos/{repo}/actions/runs?per_page=12").get("workflow_runs", [])
        for r in raw:
            if "e-monitor.yml" not in (r.get("path") or ""):
                continue
            runs.append(
                {
                    "id": r["id"],
                    "status": r["status"],
                    "conclusion": r.get("conclusion"),
                    "sha": (r.get("head_sha") or "")[:9],
                    "event": r.get("event"),
                    "title": (r.get("display_title") or "")[:60],
                }
            )
    paste_m = None
    if PASTE.exists():
        paste_m = analyze_paste(PASTE.read_text(encoding="utf-8", errors="replace"))

    red = []
    if paste_m:
        if paste_m["block"] >= 4:
            red.append(f"mass eBay block x{paste_m['block']}")
        if paste_m["rl"] >= 2:
            red.append(f"Rate limit x{paste_m['rl']}")
        if paste_m["fail"] >= 10:
            red.append(f"сбой загрузки x{paste_m['fail']}")
        if paste_m.get("z80_lv_block"):
            red.append("Z80 LV still eBay block")
    inprog = [r for r in runs if r["status"] == "in_progress"]
    if len(inprog) > 1:
        red.append(f"parallel runners {len(inprog)}")
    if md == "statistics" and paste_m and paste_m["block"] == 0 and paste_m["rl"] == 0:
        red.append("mode still statistics — consider normal if report honest")

    lines = [
        f"## {utc}",
        f"- tip_local={tip} mode={md}",
        f"- red_flags={red or ['none']}",
        f"- paste={paste_m}",
        "- runs:",
    ]
    for r in runs[:8]:
        lines.append(
            f"  - {r['id']} {r['status']} {r.get('conclusion') or '-'} "
            f"{r['sha']} {r['event']} {r['title']}"
        )
    lines.append("")
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    prev = STATUS.read_text(encoding="utf-8", errors="replace") if STATUS.exists() else ""
    STATUS.write_text(prev.rstrip() + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print("RED" if red else "OK")
    return 1 if any(
        x.startswith("mass") or x.startswith("Rate") or "Z80" in x or "parallel" in x
        for x in red
    ) else 0


if __name__ == "__main__":
    sys.exit(main())
