# e-monitor — notes for Grok / other agents

## Mode (production default)

- **`mode.txt` must be `normal`** for day-to-day alerts.
- `statistics` = diagnostic report only (do not leave on for production).
- Telegram footer `GitHub автомониторинг` = Actions runner; `Локальный` = `run.ps1`. Not the same as statistics mode.

## Onboarding another PC

See **[SETUP_OTHER_PC.md](./SETUP_OTHER_PC.md)** (full checklist) and **[MCP_SETUP.md](./MCP_SETUP.md)**.

## MCP

- Repo template: **[.grok/config.toml](./.grok/config.toml)** (edit absolute Bebranoid paths).
- Servers used: **playwright**, **bebranoid-telegram**, **bebranoid-verify** (+ optional Grok **tasks**).

## Secrets

Never commit `set_env.bat`, `config.json` (plaintext). Encrypted config is `config.json.enc` (needs `CONFIG_PASSPHRASE`). Example env keys: `set_env.example.bat`.

## Core flow

`monitor.py` → eBay HTML/API → filters → Telegram. Stats and normal share the same fetch profile (`price_asc`) and notify-eligibility rules (`_notify_eligibility`).
