# Правила валидности (ручная сверка ≈ green stats)

Цель: «дешевле вручную» считается **дырой** только если лот **должен был** пройти те же смыслы, что stats/green.

Ориентир в коде (не дублировать логику 1:1, а **совпадать по смыслу**):

- `_notify_eligibility` / `_passes_notification_price_and_auction_rules`
- title/category filters, multi-SKU bait, floor prices
- location (🇩🇪 DE / 🇪🇺 EU / 🌍)

## Всегда CHECK

1. **Та же модель / продукт**, не соседняя (16 Pro ≠ 16 Pro Max; PS5 ≠ PS5 Pro).
2. **Не аксессуар**: case, cover, Hülle, Ladegerät only, box only, display only, flex, Rahmen — если ищем устройство.
3. **Не bait multi-SKU** / «ab 1€» витрина с кучей вариантов, где реальная цена выше.
4. **Цена = total** (item + shipping), в EUR; сравнивать total с total.
5. **Корзина совпадает**:
   - Sofort: есть Buy It Now / fixed, не чистый auction-only
   - Sofort+: BIN, Best Offer допустим
   - Auktion: auction bid, не «только BIN»
   - Auktion+: auction + BO если проверяем +
6. **Лимиты** из блока 💸: не ниже ⬇️ floor без причины; «подозрительно низко» помечать отдельно.
7. **Location**: если в заголовке 🇩🇪 — не хвалить .com US pickup-only как победу DE-поиска (кроме worldwide).
8. **Состояние**: если конфиг режет «nur Defekt/Für Teile» — не считать дырой.

## Вердикты скрипта (как в Telegram)

| Emoji | Смысл | Ручная «дыра»? |
|-------|--------|----------------|
| 🟢 Подходит | alertable | да, если нашёл **дешевле валидный** |
| 🟡 Ждёт 24ч | auction timing | сравнивать осторожно; дешевле+валидный всё ещё gap |
| 🟣 Дорого | over limit | gap только если скрипт **не** показал более дешёвый valid |
| ❌ Фейк/часть | отфильтровано | manual «дешевле» тем же фейком → **не gap** |
| ❌ Не найдено | empty bucket | manual valid → **gap_missed** |

## Когда НЕ заводить finding

- Нашёл на другом marketplace (Amazon, Kleinanzeigen) — вне scope
- Нашёл с query, который **намеренно** conf исключает (banned seller / banned id)
- Разница &lt; 1€ или из-за курса/округления
- Лоты «ending in seconds» которые stats мог честно не успеть

## Severity (для findings.csv)

| Level | Когда |
|-------|--------|
| `P0` | Script empty, manual obvious valid cheap (часто) |
| `P1` | Script shows X€, manual valid ≤ 85% of X or ≥20€ cheaper |
| `P2` | Небольшой gap, edge title, редкий alias |
| `info` | Интересно, но скрипт корректен (`ok_filtered`) |
