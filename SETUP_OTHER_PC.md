# Continue e-monitor on another PC

## 0. Mode (important)

File **`mode.txt`** must be:

```text
normal
```

| Value | Meaning |
|-------|---------|
| **`normal`** | **Default** — live item alerts (what you want day-to-day) |
| `statistics` | Diagnostic price report only (no normal alerts) |

Footer in Telegram:

- `🤖 GitHub автомониторинг` = run from **GitHub Actions** (online cron)
- `💻 Локальный автомониторинг` = run from **this PC** via `run.ps1`

Both can use `mode.txt=normal`. “Git” ≠ “statistics”.

---

## 1. Clone & Python

```powershell
git clone https://github.com/GitGayHub/e-monitor.git
cd e-monitor
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## 2. Secrets

```powershell
copy set_env.example.bat set_env.bat
# edit set_env.bat: tokens, CONFIG_PASSPHRASE, eBay keys
```

Never commit `set_env.bat` or plaintext `config.json`.

## 2b. Continue QA stats audit (optional)

If you are mid **manual stats vs eBay** audit (or starting it on this PC):

1. Tell the agent: **«продолжи»** → it must run **[qa/FIRST_TASK.md](./qa/FIRST_TASK.md)** (task #1).
2. Or read **[qa/STATUS.md](./qa/STATUS.md)** / **[qa/README.md](./qa/README.md)** yourself.
3. Paste latest Telegram statistics into `qa/inbox/stats_paste.txt`.
4. `python qa/parse_stats_paste.py`
5. Playwright + `qa/WORKFLOW.md` — `bebranoid-telegram` does **not** load e-monitor stats.

## 3. Grok MCP (so the agent can browse eBay etc.)

Install **Node.js 20+**, then:

```powershell
npx -y playwright install chromium
```

### Option A — project config (already in repo)

Edit **`.grok/config.toml`**: change `C:/VibeCoding/Bebranoid/...` paths to this machine.

### Option B — user global `~/.grok/config.toml`

Append (paths adjusted):

```toml
[mcp_servers.playwright]
command = "npx"
args = ["-y", "@playwright/mcp@latest", "--headless", "--browser", "chromium"]
enabled = true
startup_timeout_sec = 120
tool_timeout_sec = 120

[mcp_servers.bebranoid-telegram]
command = "node"
args = ["C:/PATH/TO/Bebranoid/mcp-telegram-session/server.js"]
enabled = true
startup_timeout_sec = 15

[mcp_servers.bebranoid-verify]
command = "node"
args = ["C:/PATH/TO/Bebranoid/mcp-bebranoid-verify/server.js"]
enabled = true
startup_timeout_sec = 20
tool_timeout_sec = 180
```

Full notes: **[MCP_SETUP.md](./MCP_SETUP.md)**

MCP used in this project:

| Server | Role |
|--------|------|
| **playwright** | Open eBay pages, verify titles |
| **bebranoid-telegram** | Telegram session tools (Bebranoid repo) |
| **bebranoid-verify** | Extra Bebranoid checks |
| **tasks** | Grok built-in (optional) |

Bebranoid MCP **source code is not inside e-monitor** — clone Bebranoid (or copy those two `mcp-*` folders) and fix paths.

## 4. Run

**Local (default alerts, local footer):**

```powershell
# mode.txt must be: normal
.\run.ps1
```

**Online:** GitHub Actions workflow `.github/workflows/e-monitor.yml` (footer: GitHub автомониторинг). Needs secrets in the repo.

## 5. Quick checklist

- [ ] `git pull`
- [ ] `mode.txt` = `normal`
- [ ] `set_env.bat` filled (`CONFIG_PASSPHRASE` included)
- [ ] `.venv` + `requirements.txt`
- [ ] Playwright chromium installed
- [ ] `.grok/config.toml` paths fixed (if using Bebranoid MCP)
- [ ] Open folder in Grok Build / CLI
