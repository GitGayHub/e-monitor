# e-monitor — notes for Grok / other agents

## Mode

- `mode.txt`: **`normal`** = live alerts; **`statistics`** = diagnostic price report only.
- Prefer leaving production on **`normal`**.

## MCP

See **[MCP_SETUP.md](./MCP_SETUP.md)** and **[.grok/config.toml](./.grok/config.toml)** for Playwright + Bebranoid MCP servers used while debugging eBay listings.

## Secrets

Never commit `set_env.bat`, `config.json` (plaintext). Encrypted config is `config.json.enc` (needs `CONFIG_PASSPHRASE`).

## Core flow

`monitor.py` → eBay HTML/API → filters → Telegram. Stats and normal share the same fetch profile (`price_asc`) and notify-eligibility rules (`_notify_eligibility`).
