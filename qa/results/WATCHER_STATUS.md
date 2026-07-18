# e-monitor watcher status

## 2026-07-18 — watcher armed

- **Primary (Grok durable scheduler)**: every **25 min**, task id `019f729dce57`, fire immediately, auto-expires ~7 days
- **Backup (Grok tasks)**: daily **10:00** + **20:00** Europe/Berlin, app notify
- **Playbook**: `qa/WATCHER_PROMPT.md`
- **mode.txt** at arm time: `statistics` (tip `e96920a2f` cracked-back filter + stats diagnose)
- **Goal**: self-heal from GH logs + Telegram; leave production on `normal` when healthy

**Note:** PC must allow Grok/session environment for the 25m durable scheduler. Daily tasks are cloud backup.

Next cycle should report run ids, block/fail/price counts, and actions taken.

## 2026-07-18 00:28 UTC
- tip_local=0af2b1c5a mode=statistics
- red_flags=['mode still statistics — consider normal if report honest']
- paste={'chars': 902, 'prices_eur': 12, 'empty': 6, 'fail': 0, 'block': 0, 'rl': 0, 'z80_lv_block': False}
- runs:
  - 29622988657 in_progress - e96920a2f push fix: block cracked/damaged rear glass (beschädigter Rückseit
  - 29622680245 completed cancelled c2c2665e1 workflow_dispatch E Monitor
  - 29622316281 completed cancelled c2c2665e1 schedule E Monitor
  - 29622112171 completed cancelled 532e2aa19 workflow_dispatch E Monitor
  - 29621489678 completed success e154b7248 workflow_dispatch E Monitor
  - 29620863387 completed success f8cd1d511 workflow_dispatch E Monitor
  - 29620193500 completed success a1e98daa1 workflow_dispatch E Monitor
  - 29619825722 completed cancelled a1e98daa1 schedule E Monitor

