## Cloud 0.137 — актуализация 21 октября 2026

Сначала docs/WORK_STATE.md и docs/qa/cloud-20261021/REPORT_137.md. Source0.137/rules1792609320/History40, физически установленная0.136. Обеcodex/cloud-work; общаяприёмкаPARTIAL. SonyCSS-ложныйвариантисправлен;7уникальныхown,2перепроверены. Livechallenge/renderercrash:неповторятьпакетдообычногодоступа,приошибкенемедленноостанавливать. Main/normal/recipient/settings/seen/bansсохранить. НоваяAPKнепроверенанафизическомтелефоне.

## Актуальная передача в Cloud — 21 октября2026,0.136

Пользователь сейчас просит продолжать вCodexCloud, затем вернуться наПК. **Сначала читать docs/CLOUD_CONTINUE_NOW.md, docs/WORK_STATE.md, docs/CLOUD_CHECKPOINT.json.** Вобоихрепозиториях использоватьcodex/cloud-work. Это новее исторических отменCloud/очередей ниже. НикакихQR/Remote. Сохранятькод+WORK_STATEвGitHub обоихрепозиториев;productionnormal/recipient/searches/seen/bansнеизменны. Общаяприёмканезавершена. Cloud не подтверждает физическийтелефон/локальныйTelegram. ВозвратнаПК:сначалаcloud_sync--check,совместимый--applyитестыбезreset/clean. НаПКподтверждениеустройстваиспользуетphone_adb.py;приdeviceADBнеперезапускать.

## Проверенная ценовая история

История отделена от лимита уведомлений, времени аукциона и already-sent. Медиана использует только полностью проверенные snapshots текущей структуры поиска; legacy/incomplete записи сохраняются, но не доказывают скидку. При изменении семантики модели/дефектов/цены повысить одновременно price_history.HISTORY_VERSION и Android HistoryCohort.VERSION, чтобы ошибочные агрегаты старых правил не подтверждали новые. Только UI-изменения этого не требуют.

## USB телефона — актуальное исправление 12 октября

На ПК использовать `C:/VibeCoding/e-monitor-apk/android/tools/phone_adb.py`: официальныйWinGet adb37.0.1, `ADB_USB_LEGACY=1`, без `ADB_LIBUSB`. При `device` не перезапускать сервер. `--recover` восстанавливает только сервер отладки с прежним ключом. Не подменять инструмент SDK37.0.0 и не просить повторно перетыкать кабель без новых доказательств. Подробности в Android `docs/PHONE_USB.md` и общем `docs/WORK_STATE.md`.

## Возвращение на ПК — 9 октября 2026

Пользователь отменил задачу настройки Cloud: вчера уже работал там. Сейчас продолжать основную проверку eMonitor на ПК из новых исходников GitHub. Пользователь заново разрешил физический телефон (USB), сообщил, что чат бота открыт в Telegram на ПК. Окна ПК не переключать/не активировать; AyuGram читать только в фоне. Старый запрет телефона относится к прежнему этапу Cloud и отменён этим сообщением.

Обязательная актуальная передача: docs/WORK_STATE.md. Разрешённое прежними пользовательскими планами внедрение проверенных исправлений и небольшие явно обозначенные Telegram-тесты сохраняются; production mode/recipient/searches/seen не менять.

# ACTIVE CLOUD HANDOFF — search QA acceptance (2026-10-08)

**Read first:** [docs/CLOUD_SEARCH_ACCEPTANCE_2026-10-08.md](docs/CLOUD_SEARCH_ACCEPTANCE_2026-10-08.md) and [docs/qa/CLOUD_ACCEPTANCE_QUEUE_2026-10-08.json](docs/qa/CLOUD_ACCEPTANCE_QUEUE_2026-10-08.json). User requested complete independent **real eBay discovery + correct bans** on BOTH `codex/cloud-work` repositories; a successful APK build alone does NOT complete the task. Explicit authorization overrides older generic qa/FIRST_TASK and qa/WORKFLOW instructions to wait for stats input, but NEVER permits touching production searches, normal mode, recipient, seen, blacklist or physical phone. Record each verified batch with evidence and GitHub commits. Do not use blind pull/reset.

# e-monitor — notes for Grok / other agents

## Continuation between PC and Codex Cloud

Read `docs/WORK_STATE.md` and `docs/MOBILE_CONTINUE.md` before continuing. They contain the current two-repository checkpoint, unfinished acceptance and user decisions. On PC inspect cloud changes with the companion Android repository's `tools/cloud_sync.py --check`; integrate with `--apply` only after reviewing its clean merge plan, then run isolated tests. Preserve dirty work; no blind pull/reset/clean. This takes precedence over the older generic pull instructions in QA.

In Cloud check out both `GitGayHub/e-monitor` and `GitGayHub/e-monitor-android`. Save code plus an updated WORK_STATE in a commit/PR at each completed stage. Record tests actually run, counterpart branch/commit and remaining work. Cloud cannot verify the physical phone or local Telegram client; never describe those as tested there. Production mode/recipient/searches/seen and private backups remain untouched. Do not publish secrets.

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

- **If user says «продолжи» / continue / «дальше QA»** → execute **[qa/FIRST_TASK.md](./qa/FIRST_TASK.md)** immediately (task #1 = first stats product, 4 buckets).
- Status / handoff: **[qa/STATUS.md](./qa/STATUS.md)** · overview **[qa/README.md](./qa/README.md)**
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
