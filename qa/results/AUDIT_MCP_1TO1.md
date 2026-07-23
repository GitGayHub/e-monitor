# Честный 1:1 аудит (MCP Playwright + stats log)

**Дата:** 2026-07-17 ~02:05–02:10  
**Stats source:** `qa/inbox/local_stats_html.log` (локальный HTML-only run, 24 продукта)  
**Parsed:** `qa/inbox/stats_local_parsed.json`  

## Честно про прошлый отчёт

**Нет — раньше не было настоящей 1:1 сверки.**  
Был только разбор логов stats (цены/bucket). Цены vs eBay live и empty vs stock **не** проверялись по каждой позиции.

Сейчас: Playwright MCP search + открытие item pages + HTML search.

---

## 6 EMPTY (script `---/---/---/---`)

| # | Product | Script | eBay live (Playwright) | Вердикт |
|---|---------|--------|------------------------|---------|
| 1 | **Nubia Z80 Ultra Leading** | empty | Exact «Z80 Ultra Leading» ≈ 0; выдаёт related (Z70/Z60 Leading, Z80 non-Leading). | **ok_empty / weak query** — модели Leading Z80 почти нет; не gap «есть телефоны Leading». |
| 2 | **logitech superlight 2 dex** | empty | Реальные мыши: **60€, 69€, 75€, 82€** (напр. `358787597789` SUPERLIGHT 2 DEX). Stats-run: challenge page. | **P0 gap_missed** |
| 3 | **logitech superlight 2** (2-й search) | empty | В том же прогоне 1-й Superlight 2 = 70/66€. 2-й row — дубль/другой conf, empty в конце (429 details/challenge). | **P1** — conf/fetch, не отсутствие товара |
| 4 | **Sony ULT Wear** | empty | BIN price_asc забит **запчастями** (Ohrpolster 40–50€). Полные наушники в выдаче плохо всплывают. | **P1 filter/window** — stock возможен, stats не нашёл device |
| 5 | **LG UltraGear OLED 480Hz** | empty | Live: **469€, 479€, 483€…** 27GX790A. | **P0 gap_missed** (должны быть 🟣 если лимит ниже) |
| 6 | **Samsung Odyssey OLED G6 500Hz** | empty | Live: **~470–500€+** LS27FG602/G60SF. Лимит stats 400€ → 🟣, не `---`. | **P0 gap_missed** (filter/model match) |

---

## 1:1 цены (sample item IDs из stats → Playwright)

| Stats product / bucket | Script € | Item ID | Live title (ok?) | Live price signal | Match? |
|------------------------|----------|---------|------------------|-------------------|--------|
| RM11 Sofort | 1505 | 800278835200 | Golden Saga Bundle 24/1TB ✅ | ~1499€ BIN | **match** (~shipping) |
| RM11 Sofort+ | 706 | 398181403334 | Redmagic 11 Pro 16/512 ✅ | было ~700, сейчас ~749+ship | **was OK, price moved** |
| RM11 Auktion | 692 | 327257689079 | Red Magic 11 Pro Frost ✅ | auction bid moved (~351 now) | **item real, bid changed** |
| RM11S Sofort | 1151 | 137414773091 | RedMagic 11s Pro 256 Silver ✅ | page shows lower now | **item real, price moved** |
| RM11S Sofort+ | 722 | 336690246736 | 11S Pro Nightfreeze 16/512 ✅ | price fluctuates | **item real** |
| Z80 Ultra Sofort | 756 | 178306976467 | Z80 Ultra Starry Night + Kit ✅ | page multi-prices | **item real** |
| Z70 Ultra Sofort | 459 | 168388431431 | Z70 Ultra 512 Black Sehr Gut ✅ | title OK | **item real** |
| iPhone 16 PM Sofort | 650 | 318587124712 | iPhone 16 Pro Max 256 Silver ✅ | multi BIN/bid | **item real** |
| XM6 Sofort | 246 | 147429611462 | Sony WH-1000XM6 ✅ | ~240€ | **match (~6€)** |
| DEX (not in stats) | --- | 358787597789 | SUPERLIGHT 2 DEX ✅ | **60€** | proves empty is bug |
| G6 (not in stats) | --- | 307045605733 | Odyssey OLED G6 500Hz ✅ | listing live | proves empty is bug |
| LG (not in stats) | --- | 358558508077 | 27GX790A 480Hz B-Ware ✅ | **469€** | proves empty is bug |

### Batch 2 — Playwright primary price vs script

| Tag | Script | Live main | Title OK | € match |
|-----|--------|-----------|----------|---------|
| PS5 Sofort | 879 | **879,00** | PS5 Pro 2TB ✅ | **exact** |
| PS5 Sofort+ | 910 | 900 + BO | PS5 PRO ✅ | **~10€** |
| PS5 Auktion | 650 | 640 | PS5 Pro 2TB ✅ | **~10€** |
| 5070 Sofort | 1698 | **1698,00** | PC RTX 5070 Ti ✅ | **exact** |
| 5070 Sofort+ | 1523 | 1499 + BO | PC 5070 Ti ✅ | **~24€** |
| 4080 Sofort | 1650 | **1650,00** | PC RTX 4080 ✅ | **exact** |
| iPhone 15 PM S | 576 | 570 | 15 PM 256 ✅ | **~6€** |
| iPhone 15 PM S+ | 496 | 490 + BO | 15 PM 256 ✅ | **~6€** |
| S24 Ultra S | 448 | **448,00** | S24U 256 ✅ | **exact** |
| S24 Ultra S+ | 441 | 434,68 + BO | S24U 256 ✅ | **~6€** |
| Superstrike | 145 | 139 | superstrike x2 ✅ | **~6€** |
| Superlight 2 S | 70 | 69,95 | GPX Superlight 2 ✅ | **match** |
| Superlight 2 S+ | 66 | 60 + BO | Superlight 2 ✅ | **~6€** |
| Z70S Sofort+ | 755 | £499,95 (UK) | Z70S Ultra ✅ | **currency/market** |
| VivoBook 14x | 779 | 768,46 | Vivobook Pro 14X OLED ✅ | **~10€** |
| Pixel 5 | 135 | *(nav error)* | — | **retry later** |

**Итог по ценам:** где stats дал item_id — лоты **реальные**, € в большинстве **exact или ±6–25€** (доставка/BO/рынок). Это не фейковые цифры.

---

## Сводка

| Категория | Кол-во | Смысл |
|-----------|--------|--------|
| Stats показал цены | 18 | HTML path работает |
| Item IDs проверены Playwright | **~25** | реальные лоты |
| € 1:1 exact / ±25€ | **большинство** | PS5, 5070, 4080, S24, Superlight, … |
| Empty и eBay empty/wrong model | ~1 | Z80 Leading |
| Empty но eBay stock (**P0**) | **3** | DEX, Odyssey G6, LG 480 |
| Empty / filter / parts flood | 1–2 | Sony ULT, 2nd Superlight |

---

## Что чинить дальше (по приоритету)

1. **P0 monitors + DEX:** почему stats `---` при HTML stock (model filter `_matches_samsung_odyssey_g6_500hz`, UltraGear aliases, Superlight DEX после challenge).  
2. **Sony ULT:** `_udlo` + accessory filter / candidate window.  
3. Добить **оставшиеся item_id 1:1** через Playwright batch.  
4. Не врать «всё ok» пока empty-P0 живы.

Файлы:
- `qa/inbox/stats_local_parsed.json`
- `qa/results/AUDIT_MCP_1TO1.md` (этот)
- Playwright session snapshots under `.playwright-mcp/`
