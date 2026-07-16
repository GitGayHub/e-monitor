# Протокол масштабного аудита (агент)

Не запускай массовый eBay-обход без явной команды. Этот файл — **как** делать, когда аудит начат.

## 0. Подготовка сессии

1. `git pull`
2. Прочитай `qa/STATUS.md`
3. Убедись, что Playwright MCP жив (`npx` + chromium)
4. Есть ли свежий stats?
   - Если есть `qa/inbox/stats_paste.txt` →  
     `python qa/parse_stats_paste.py`  
     → `qa/inbox/stats_parsed.json`
   - Если нет — **спросить пользователя** paste или работать только с уже распарсенным JSON

## 1. Выбор позиции

- Порядок: как в отчёте / алфавит в stats (бот сортирует по имени).
- Начать с **позиции №1** из `STATUS.md` → `next_index` (0-based в JSON).
- Одна позиция = один product block (4 корзины).

## 2. Baseline из stats

Для выбранной позиции выписать в `qa/results/<slug>.json` (см. TEMPLATE):

- `query` / display name
- лимиты (🎯 ⬆️ ⬇️) если есть
- по каждой корзине: price | verdict | item url (если *ТЫК*)

## 3. Alias-запросы

1. Взять base query из stats.
2. Найти family в `qa/query_aliases.json` (или `default_patterns`).
3. Собрать список **q1…qn** (base + aliases), без дублей.
4. Не больше **6–8** запросов на позицию в первой волне (масштаб контролируй).

Примеры:

- `iPhone 16 Pro Max` → `16 pro max`, `iphone 16 promax`, …
- `PlayStation 5 Pro` → `ps5 pro`, `playstation 5 pro`, …

## 4. Ручной eBay (Playwright)

Для **каждой корзины** отдельно:

| Корзина | Что выставить на eBay (ориентир DE) |
|---------|-------------------------------------|
| Sofort | Buy It Now / Sofortkauf, **без** акцента на Best Offer only |
| Sofort+ | BIN + допускаем Best Offer |
| Auktion | Auction only |
| Auktion+ | Auction + Best Offer если фильтр доступен |

Сортировка: **price + shipping ascending** (как stats `price_asc`), если UI позволяет.

На каждый query:

1. `browser_navigate` на search URL (ebay.de предпочтительно).
2. Snapshot выдачи: топ 5–15 по цене.
3. Отсечь по [VALIDITY.md](./VALIDITY.md) (title, модель, bait, регион).
4. При сомнении — открыть item page (title, price, shipping, buying options).
5. Зафиксировать **лучший валидный** manual candidate.

Сравни:

- `manual_total` vs `script_total`
- если script `---` и manual есть → `gap_missed`
- если manual < script (с запасом ≥1€) и valid → `gap_cheaper`
- если примерно равно → `ok`
- если manual «дешевле» но invalid → `ok_filtered` (скрипт прав)

## 5. Запись результата

1. Заполнить `qa/results/<slug>.json`
2. Добавить строку(и) в `qa/results/findings.csv`
3. Обновить `qa/STATUS.md` (`next_index`, last notes)
4. **Не** коммить secrets; findings и STATUS — да, для handoff

## 6. После серии находок (отдельная задача)

Кластеризовать gaps:

- query слишком узкий → aliases / config query
- фильтр title/category слишком жёсткий
- bucket split (hybrid BIN/auction) ошибочный
- shipping/total не учтён
- location LH_PrefLoc

Чинить код + **bump `logic_version.txt`**.

## 7. Стоп-условия

- Капча / block eBay → пауза, записать в STATUS, не долбить
- > N позиций за сессию (договорённость, default 3–5) → handoff commit
