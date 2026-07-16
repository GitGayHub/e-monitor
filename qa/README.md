# QA: масштабная сверка stats vs eBay (ручной аудит)

Цель: по позициям из **статистического** Telegram-отчёта проверить, что скрипт находит **реально самый дешёвый валидный** лот в каждой корзине (Sofort / Sofort+ / Auktion / Auktion+).  
Если вручную находится дешевле (и это валидный товар) — это **баг/дыра** → чиним `monitor.py` / конфиг.

**Сейчас:** подготовка + handoff между ПК. Саму проверку не гоняем, пока агент не начал audit.

---

## Быстрый старт на другом ПК

1. `git pull` репо `e-monitor`.
2. MCP: **Playwright** обязателен (см. [MCP_SETUP.md](../MCP_SETUP.md), [SETUP_OTHER_PC.md](../SETUP_OTHER_PC.md)).  
   `bebranoid-telegram` **не** читает stats-бот — только музыка Bebranoid.
3. Скажи агенту: **«продолжи»** — он берёт **[FIRST_TASK.md](./FIRST_TASK.md)** (задача №1 = первая позиция stats).
4. Или вручную: [STATUS.md](./STATUS.md) → paste stats → `python qa/parse_stats_paste.py` → [WORKFLOW.md](./WORKFLOW.md).
5. Результаты в `qa/results/`.

---

## Откуда брать stats (Telegram)

MCP **не** умеет читать сообщения e-monitor бота. Варианты:

| Способ | Как |
|--------|-----|
| **A. Paste (рекомендуется)** | Скопировать куски отчёта из Telegram → файл `qa/inbox/stats_paste.txt` |
| **B. Скрин + OCR/агент** | Скрин в `qa/inbox/` + описание |
| **C. Actions log** | Логи workflow (хуже, чем Telegram-разметка) |

Формат блоков в боте (примерно):

```text
📱 iPhone 16 Pro Max 🇩🇪 ⚙️
💸 Лимит: 🎯 700€ ⬆️ 900€ ⬇️ 50€
🛒 Sofort   612€ │ 🟢 Подходит
🔗 *ТЫК*
🤝 Sofort+  590€ │ 🟢 Подходит
🔗 *ТЫК*
🔨 Auktion  540€ │ 🟡 Ждёт 24ч
🔗 *ТЫК*
⏳ Auktion+ ---  │ ❌ Не найдено
```

Корзины = 4 stats-бакета в коде:

| UI | Код | listing |
|----|-----|---------|
| Sofort | BIN no BO | buy_now / fixed, без Best Offer как «+» |
| Sofort+ | BIN + Best Offer | buy_now_offer + BO |
| Auktion | auction no BO | auction |
| Auktion+ | auction + BO | auction + best offer |

Точные варианты поиска: `_statistics_search_variant` в `monitor.py`.

---

## Что считается «дырой»

Вручную нашли лот **дешевле** зелёного/показанного скриптом (или нашли, когда скрипт `--- Не найдено`), **и** лот проходит [VALIDITY.md](./VALIDITY.md).

Не дыра: аксессуар, bait multi-SKU, другая модель, не тот регион, «дешево но ❌ фейк» по правилам скрипта.

---

## Файлы в этой папке

| Файл | Назначение |
|------|------------|
| [WORKFLOW.md](./WORKFLOW.md) | Пошаговый протокол аудита (агент + человек) |
| [VALIDITY.md](./VALIDITY.md) | Правила «валидный дешевле» |
| [STATUS.md](./STATUS.md) | Прогресс / handoff между ПК |
| [query_aliases.json](./query_aliases.json) | Альтернативные запросы (iPhone, PS5, …) |
| [parse_stats_paste.py](./parse_stats_paste.py) | Paste → `inbox/stats_parsed.json` |
| [results/TEMPLATE.json](./results/TEMPLATE.json) | Шаблон одной позиции |
| [results/findings.csv](./results/findings.csv) | Сводная таблица находок |
| [inbox/](./inbox/) | Сюда класть paste/скрины (gitignore на крупные бинарники по желанию) |

---

## MCP readiness (чеклист)

| Нужно | Статус |
|-------|--------|
| Playwright → eBay search/item | ✅ достаточно |
| Читать stats из Telegram MCP | ❌ нет → paste |
| Код фильтров / green verdict | ✅ `_notify_eligibility`, stats buckets |
| Алиасы запросов | ✅ стартовый `query_aliases.json` (расширять) |
| Запись результатов для handoff | ✅ `results/` + STATUS |

---

## Коммиты

- Доки/шаблоны QA **не** требуют bump `logic_version.txt`.
- Багфиксы логики после аудита → **да**, bump `logic_version.txt`.
- `mode.txt`: для дневных алертов верни `normal`; stats-only = `statistics`.
