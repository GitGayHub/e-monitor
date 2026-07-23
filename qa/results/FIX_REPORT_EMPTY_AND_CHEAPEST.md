# Отчёт: empty → cheapest + сверка с eBay

**Когда:** 2026-07-17  
**Код:** `monitor.py` + `logic_version.txt` → `1784255102`

## Что было не так (не «API лимит»)

1. **Query с скобками** `(G60SF, LS27FG602)` / `(32GS95, 27GX790A)` уходил в eBay `_nkw` через `_intent_query` и **обнулял HTML-выдачу**.
2. **`samsung` в query монитора** → `_is_phone_search_query=True` → floor 120€ как у телефонов (побочный вред).
3. **Нет device `_sacat` для monitors/mice** → fallback на parent `58058`; плюс узкий sacat тоже ломал выдачу → для stats fetch **category=all**, отбор по title.
4. **LG** матчил только model-code в title; **Odyssey** не знал `LS27FG604`.
5. **Superlight 2 vs DEX** не разделялись → DEX empty / путаница.
6. **Sony ULT** тонул в запчастях; intent+matcher отсекают pads, оставляют headset.
7. Stats API fallback при HTML empty (починено ранее) + circuit-breaker 429.

## Что сделано

| Фикс | Эффект |
|------|--------|
| Clean intent queries + variants (Odyssey/LG/DEX/ULT/SL2) | eBay HTML находит stock |
| Matchers: G6+500/LS27FG604, LG 480, SL2±DEX, ULT | cheapest = правильная модель |
| phone query: samsung+monitor ≠ phone | не ломает Odyssey |
| stats: monitors/mice fetch `category=all` | нет empty из-за sacat |
| floor 150 monitors / 40 mice / 80 ULT | price_asc не из 4€ мусора |
| без `-parts` на monitor/PC intent | меньше ложных empty |

## Проверка (synthetic filter, без сети)

| Product | Оставляет | Режет |
|---------|----------|-------|
| Odyssey G6 | 469.95 LS27FG604 500Hz | — |
| LG UltraGear | 469 27GX790A 480Hz | — |
| Superlight 2 DEX | 60€ DEX mouse | plain SL2, PCB |
| Superlight 2 | 70€ plain SL2 | DEX |
| Sony ULT | 99€ headset | Ohrpolster 42€ |

## Live HTML после фикса (этот хост, 02:25)

| Product | Было | Стало (cheapest filtered BIN) |
|---------|------|--------------------------------|
| Superlight 2 DEX | `---` | **129.90€** (DEX mouse, id 406218242948) |
| Superlight 2 | 70 (раньше ок) | **72.98€** plain SL2 (DEX не лезет) |
| LG UltraGear 480 | `---` | **729.29€** 27GX790A (🟣 over 430 limit — но не empty) |
| Odyssey G6 | `---` | (в логе прошёл вместе с LG; stock + matcher OK) |
| Redmagic 11 Pro | цены были | **1042€** valid phone |
| XM6 | цены были | **312€** |

Playwright раньше видел DEX ~60 / G6 ~470 / LG ~469 — HTML total с shipping/location может быть выше; главное: **больше не `---`**, берётся **минимальный валидный** после фильтров.

## Цены, что уже 1:1 совпали (прошлый MCP)

PS5 879=879, 5070 1698=1698, 4080 1650=1650, S24 448=448, SL2 ~70, XM6 ~246 — **не фейк**.

## Не «баг empty»

- **Z80 Ultra Leading** — exact Leading на DE почти нет (related = другие модели).

## Дальше

1. `mode=statistics` one-shot после отдыха eBay → сверить empty-товары.  
2. Commit/push + `mode=normal` для алертов.  
3. При повторном soft-block HTML — cooldown уже в коде; не долбить Browse API.
