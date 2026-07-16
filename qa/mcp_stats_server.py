#!/usr/bin/env python3
"""Minimal MCP server: read e-monitor statistics without opening Telegram UI.

Sources (quiet, background):
  1) GitHub Actions logs — same "Generated statistics block" the bot logs before Telegram
  2) Local qa/inbox/stats_paste.txt / stats_parsed.json / STATUS.md

Does NOT inject into the user's Telegram desktop window.

Install for Grok (~/.grok/config.toml or .grok/config.toml):

  [mcp_servers.e-monitor-stats]
  command = "python"
  args = ["C:/PATH/TO/e-monitor/qa/mcp_stats_server.py"]
  enabled = true
  startup_timeout_sec = 30
  tool_timeout_sec = 180

Requires: GITHUB_TOKEN or git remote with token; Python 3.10+.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QA = Path(__file__).resolve().parent


def _tool_list():
    return {
        "tools": [
            {
                "name": "stats_fetch_github",
                "description": (
                    "Download latest e-monitor statistics blocks from GitHub Actions logs "
                    "(same content the bot sends to Telegram). Writes qa/inbox/stats_paste.txt "
                    "and runs parse into stats_parsed.json. No Telegram UI."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "run_id": {
                            "type": "integer",
                            "description": "Optional Actions run id; default: newest successful run with stats",
                        }
                    },
                },
            },
            {
                "name": "stats_read_parsed",
                "description": "Read qa/inbox/stats_parsed.json (product catalog for QA audit).",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "stats_read_status",
                "description": "Read qa/STATUS.md handoff status.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "stats_product",
                "description": "Get one product from stats_parsed.json by index (0-based).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "Product index, default 0"},
                    },
                },
            },
        ]
    }


def _call_fetch(run_id=None):
    cmd = [sys.executable, str(QA / "fetch_stats_from_github.py")]
    if run_id is not None:
        cmd += ["--run-id", str(run_id)]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return {"ok": False, "exit": r.returncode, "log": out[-4000:]}
    # parse
    pr = subprocess.run(
        [sys.executable, str(QA / "parse_stats_paste.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    meta_path = QA / "inbox" / "stats_from_github.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    parsed_path = QA / "inbox" / "stats_parsed.json"
    count = 0
    if parsed_path.exists():
        data = json.loads(parsed_path.read_text(encoding="utf-8"))
        count = data.get("count") or len(data.get("products") or [])
    return {
        "ok": True,
        "fetch_log": out[-2000:],
        "parse_log": (pr.stdout or "")[-1000:],
        "meta": meta,
        "products": count,
    }


def _read_parsed():
    p = QA / "inbox" / "stats_parsed.json"
    if not p.exists():
        return {"ok": False, "error": "stats_parsed.json missing — run stats_fetch_github first"}
    return json.loads(p.read_text(encoding="utf-8"))


def _read_status():
    p = QA / "STATUS.md"
    if not p.exists():
        return {"ok": False, "error": "STATUS.md missing"}
    return {"ok": True, "markdown": p.read_text(encoding="utf-8")}


def _product(index: int = 0):
    data = _read_parsed()
    if isinstance(data, dict) and data.get("ok") is False:
        return data
    products = data.get("products") if isinstance(data, dict) else data
    if not products:
        return {"ok": False, "error": "no products"}
    if index < 0 or index >= len(products):
        return {"ok": False, "error": f"index {index} out of range 0..{len(products)-1}"}
    return {"ok": True, "index": index, "product": products[index]}


def _handle(msg: dict):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "e-monitor-stats", "version": "1.0.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": _tool_list()}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "stats_fetch_github":
                result = _call_fetch(args.get("run_id"))
            elif name == "stats_read_parsed":
                result = _read_parsed()
            elif name == "stats_read_status":
                result = _read_status()
            elif name == "stats_product":
                result = _product(int(args.get("index") or 0))
            else:
                result = {"ok": False, "error": f"unknown tool {name}"}
            text = json.dumps(result, ensure_ascii=False, indent=2)
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": text}]},
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": json.dumps({"ok": False, "error": str(e)})}],
                    "isError": True,
                },
            }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    # ignore other notifications
    if mid is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    # Line-delimited JSON-RPC over stdio
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = _handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
