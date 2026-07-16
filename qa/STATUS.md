# QA audit status (handoff)

Обновляй этот файл в конце каждой сессии и **коммить**, чтобы другой ПК продолжил.

## Snapshot

| Field | Value |
|-------|--------|
| Phase | **prep_done** — протокол готов, массовый audit ещё не стартовал |
| Last update | 2026-07-16 |
| Stats source | _empty — нужен paste в `qa/inbox/stats_paste.txt`_ |
| Parsed catalog | _нет — запусти `python qa/parse_stats_paste.py`_ |
| Next product index | `0` (первая позиция после parse) |
| Products done | `0` |
| Open P0/P1 findings | `0` |
| mode.txt note | может быть `statistics` на remote; для prod alerts → `normal` |

## Blockers

1. Нет свежего Telegram stats paste (MCP telegram не читает e-monitor bot).
2. На новом ПК: Playwright chromium + пути в `.grok/config.toml`.

## Session log

### 2026-07-16 — prep

- Создана папка `qa/`: workflow, validity, aliases, parser, templates, results.
- Идея аудита согласована: позиция → 4 корзины → multi-query eBay → compare → findings.
- Коммит на GitHub для продолжения с другого ПК.
- **Audit eBay ещё не выполнялся.**

## Next agent instructions (copy-paste)

```text
Продолжи QA stats audit из qa/STATUS.md.
1) git pull
2) Если есть qa/inbox/stats_paste.txt — parse_stats_paste.py
3) Иначе попроси paste stats из Telegram
4) Начни с next_index, протокол qa/WORKFLOW.md, validity qa/VALIDITY.md
5) Пиши results + STATUS, коммить handoff
Не меняй mode/logic без находок. Playwright для eBay.
```
