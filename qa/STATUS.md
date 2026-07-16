# QA audit status (handoff)

Обновляй этот файл в конце каждой сессии и **коммить**, чтобы другой ПК продолжил.

> **Активная задача:** [FIRST_TASK.md](./FIRST_TASK.md) — позиция №1 stats vs eBay.  
> Пользователь говорит «продолжи» → делать FIRST_TASK, не спрашивать заново весь план.

## Snapshot

| Field | Value |
|-------|--------|
| Phase | **ready_for_task_1** — prep done, audit not started |
| Active task | **#1** → [FIRST_TASK.md](./FIRST_TASK.md) |
| Last update | 2026-07-16 |
| Stats source | _empty — нужен paste в `qa/inbox/stats_paste.txt`_ |
| Parsed catalog | _нет — `python qa/parse_stats_paste.py`_ |
| Next product index | `0` (**первая позиция = задача №1**) |
| Products done | `0` |
| Open P0/P1 findings | `0` |
| mode.txt note | remote может быть `statistics`; для prod alerts → `normal` |

## Blockers

1. Нет свежего Telegram stats paste (MCP telegram **не** читает e-monitor bot) — при «продолжи» **запросить paste**, затем audit.
2. На новом ПК: Playwright chromium + пути в `.grok/config.toml`.

## Session log

### 2026-07-16 — prep + first task pinned

- Папка `qa/`: workflow, validity, aliases, parser, templates, results.
- Добавлен **`qa/FIRST_TASK.md`** — явная задача №1 для handoff («продолжи» с другого ПК).
- **Audit eBay ещё не выполнялся** — next_index=0.

## Next agent instructions (если сказали «продолжи»)

```text
1) git pull
2) Открыть qa/FIRST_TASK.md и выполнить задачу №1 целиком
3) qa/STATUS.md + qa/WORKFLOW.md + qa/VALIDITY.md
4) Stats: paste → python qa/parse_stats_paste.py (или попросить paste)
5) Позиция next_index (0): 4 корзины, Playwright eBay, multi-query aliases
6) results/<slug>.json + findings.csv + обновить STATUS + push
Не чинить monitor.py в рамках task1 без явных gaps и необходимости.
```
