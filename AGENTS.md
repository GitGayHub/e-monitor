# e-monitor — notes for Grok / other agents

## Mode (production default)

- **`mode.txt` must be `normal`** for day-to-day alerts.
- `statistics` = diagnostic report only (do not leave on for production).
- Telegram footer `GitHub автомониторинг` = Actions runner; `Локальный` = `run.ps1`. Not the same as statistics mode.

## Version (Telegram «Версия»)

- Source of truth: **`logic_version.txt`** (unix UTC seconds on the first line).
- Bump it when you change bot **logic** (filters, bugfixes, notify rules). Do **not** bump on state/mode/sync commits.
- Never derive version from `git log` HEAD — Actions shallow clones make that equal the last state commit.

## Onboarding another PC

See **[SETUP_OTHER_PC.md](./SETUP_OTHER_PC.md)** (full checklist) and **[MCP_SETUP.md](./MCP_SETUP.md)**.

## QA stats audit (scale handoff)

Manual eBay vs Telegram statistics report (4 buckets × multi-query aliases):

- Start: **[qa/README.md](./qa/README.md)** and **[qa/STATUS.md](./qa/STATUS.md)**
- Protocol: `qa/WORKFLOW.md`, validity `qa/VALIDITY.md`, aliases `qa/query_aliases.json`
- Paste stats → `qa/inbox/stats_paste.txt` → `python qa/parse_stats_paste.py`
- Playwright required for eBay. **bebranoid-telegram does not read e-monitor bot messages.**

## MCP

- Repo template: **[.grok/config.toml](./.grok/config.toml)** (edit absolute Bebranoid paths).
- Servers used: **playwright**, **bebranoid-telegram**, **bebranoid-verify** (+ optional Grok **tasks**).

## Secrets

Never commit `set_env.bat`, `config.json` (plaintext). Encrypted config is `config.json.enc` (needs `CONFIG_PASSPHRASE`). Example env keys: `set_env.example.bat`.

## Core flow

`monitor.py` → eBay HTML/API → filters → Telegram. Stats and normal share the same fetch profile (`price_asc`) and notify-eligibility rules (`_notify_eligibility`).
