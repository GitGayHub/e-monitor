# MCP servers used with e-monitor (Grok)

This project was developed with Grok Build using the MCP servers below.
Copy / adapt these into **`~/.grok/config.toml`** (user-global) and/or
**`.grok/config.toml`** (this repo only — supported for `mcp_servers`).

After cloning on another PC: install Node.js 20+, run any one-time Playwright
browser install, point absolute paths at your machine, restart Grok.

## 1. Playwright (browser) — **used heavily**

Opens real eBay item pages headless to verify titles (plushie mouse, wrong
RedMagic model, etc.).

```toml
# Headless Chromium — no visible window
[mcp_servers.playwright]
command = "npx"
args = [
    "-y",
    "@playwright/mcp@latest",
    "--headless",
    "--browser",
    "chromium",
]
enabled = true
startup_timeout_sec = 120
tool_timeout_sec = 120
```

**One-time on a new PC:**

```bash
npx -y playwright install chromium
```

Tools used: `browser_navigate`, `browser_snapshot`, `browser_evaluate`, etc.

## 2. bebranoid-telegram (Telegram session)

Local Node MCP that talks to Telegram via a saved session (Bebranoid tooling).
**Path is machine-specific** — update after clone.

```toml
[mcp_servers.bebranoid-telegram]
command = "node"
# CHANGE ME: absolute path to the MCP server entrypoint on this PC
args = ["C:/VibeCoding/Bebranoid/mcp-telegram-session/server.js"]
enabled = true
startup_timeout_sec = 15
```

Source lives under the **Bebranoid** repo (`mcp-telegram-session/`), not in
e-monitor. Clone that repo (or copy the server folder) and fix `args`.

## 3. bebranoid-verify

Optional verification helper from Bebranoid.

```toml
[mcp_servers.bebranoid-verify]
command = "node"
args = ["C:/VibeCoding/Bebranoid/mcp-bebranoid-verify/server.js"]
enabled = true
startup_timeout_sec = 20
tool_timeout_sec = 180
```

## 4. tasks (Grok built-in / session MCP)

Often auto-connected in Grok sessions for task lists. No separate install if
your Grok build already exposes the `tasks` server. If missing, ignore — the
bot does not depend on it at runtime.

## What e-monitor itself needs (not MCP)

Runtime of the eBay→Telegram bot (separate from Grok MCP):

| Item | Notes |
|------|--------|
| Python 3.11+ | `.venv` + `pip install -r requirements.txt` |
| `set_env.bat` | Copy from `set_env.example.bat` (gitignored secrets) |
| `CONFIG_PASSPHRASE` | Decrypts `config.json.enc` |
| Telegram bot tokens | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Optional eBay API | `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` |
| `mode.txt` | `normal` = alerts, `statistics` = diagnostic report |

Launch: `.\run.ps1` (local) or GitHub Actions workflow `.github/workflows/e-monitor.yml`.

## Project-local Grok MCP config

A template also lives at `.grok/config.toml` in this repo. Edit paths before
use on a new machine.

## Session context (this workstream)

Relevant Grok session folder (this PC only, not committed):

`~/.grok/sessions/C%3A%5CVibeCoding%5Ce-monitor/`

On another PC, clone **GitGayHub/e-monitor**, set env + MCP paths above, open
the repo in Grok — history does not transfer unless you copy the session dir.
