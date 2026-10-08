# eMonitor — независимая проверка поисковых запросов и отсева (8 октября 2026)

## Границы проверки

Источник: публично индексируемые карточки/каталоги `ebay.de` и синтетические контрольные примеры. **Это не живой интерактивный браузерный аудит**: прямой HTTP/браузерный доступ к каталогу из этого окружения блокируется. Цены, наличие, продавец и окончание аукциона из индекса не считаются актуальными без свежей проверки. Каждая ссылка / название ниже — свидетельство типа товара, не заявка на отправку уведомления.

Оба проекта работают над одинаковым набором JSON-примеров, сохранённым в `qa/fixtures/web_indexed_listing_cases_2026-10-08.json` бота и `app/src/test/resources/web_indexed_listing_cases_2026-10-08.json` Android. Всего 31 контрольных карточек, из них 18 имеют ссылки на индексированную eBay-страницу (прочие контроли синтетические или из прежних локальных материалов). Независимость источника относится только к названиям/типу товара; ожидаемые вердикты задаются вручную.

## Проверяемые семействá

- **Sony WH‑1000XM6 и ULT Wear:** амбушюры, запасные платы/оголовья не должны учитываться как наушники. Учитываются модели целых устройств, включая корректные формы Sony ULT Wear / WH‑ULT900N.
- **PS5 Pro:** накладки Faceplate/Cover, игры, VR-гарнитура и отдельный DualSense не равны консоли. Полная PS5 Pro с контроллером подходит по типу товара.
- **Logitech Superlight 2, DEX, Superstrike:** ножки/skates/glides, receiver, игрушки и другие запчасти не являются мышью. DEX не подменяет стандартную Superlight 2.
- **RedMagic:** разные поколения 11/11S не смешиваются; настоящий прозрачный корпус смартфона (Transparent Edition) не равен прозрачному чехлу, даже если модель и объём памяти в обоих заголовках.
- **Nubia, Pixel, GPU-компьютеры:** совпадение номера модели на рамке/плате, Pixel 4a 5G вместо Pixel 5 или RTX 5070 Ti в ноутбуке вместо настольного ПК не означает искомый товар.
- **Глобальный бан:** продавец Talk‑Point GmbH должен отсеиваться независимо от категории при проверке вариантов записи имени.

## Индексированные внешние примеры

| Продукт / название | Ожидаемое решение по **типу товара и названию** | URL |
|---|---|---|
| Ersatz Ohrpolster für Sony WH-1000XM6 Kopfhörer schwarz 2 Stück Set | Отсеять | https://www.ebay.de/itm/278301040297 |
| 2 Stück Ohrpolster Ersatz für Sony WH-1000XM6 Kopfhörer weich ComFort | Отсеять | https://www.ebay.de/itm/178441550619 |
| Sony PlayStation 5 PRO Konsole Cover Ghost of Yotei Gold CFI-ZCS3GZ7 | Отсеять | https://www.ebay.de/itm/376667792763 |
| Playstation 5 Pro Disc Edition Faceplate Cover Schwarz Ghost Yotei (OVP) | Отсеять | https://www.ebay.de/itm/287193637992 |
| Logitech G PRO X Superlight 2 - GPX2 - Tiger ICE V2 Mouse Feet Skates | Отсеять | https://www.ebay.de/itm/226446333348 |
| RUSH Glas Mausfüße (1x Set) für Logitech G PRO X Superlight 2 - Skates, Glides | Отсеять | https://www.ebay.de/itm/156116710641 |
| RUSH Glas Mausfüße (1x) für Logitech G PRO X Superlight 2 Dex - Skates, Glides | Отсеять | https://www.ebay.de/itm/157449791714 |
| REDMAGIC 11 Pro 144Hz 5G Smartphone 16GB 512GB Gaming Transparent | Допустить к дальнейшей проверке | https://www.ebay.de/itm/358301335572 |
| Original Display für Google Pixel 5 Aufbereitet | Отсеять | https://www.ebay.de/itm/137748784916 |
| OEM Sony WH-1000XM6 Powerboard PCB SUB-R-11 Rechts Interne Platine - Ersatzteile | Отсеять | https://www.ebay.de/itm/327337313041 |
| Apple iPhone 16 PRO MAX - 256GB - TITAN WÜSTENSAND , sehr gut erhalten in OVP | Допустить к дальнейшей проверке | https://www.ebay.de/itm/206576929321 |
| Cooling-Gel Ohrpolster Kissen für Sony ULT Wear /(WH-ULT900NB) Kopfhörer Ersatz | Отсеять | https://www.ebay.de/itm/297348059775 |
| Sony ULT Wear WH-ULT900N Ohrpolster Ersatzteile Paar Schwarz OEM | Отсеять | https://www.ebay.de/itm/327178408900 |
| Sony ULT Wear Bluetooth-Kopfhörer Schwarz Kopfbügel Over-Ear faltbar ANC | Допустить к дальнейшей проверке | https://www.ebay.de/shop/ult-wear?_nkw=ult+wear |
| ZTE Nubia Redmagic 11 Pro 16GB / 512GB | Допустить к дальнейшей проверке | https://www.ebay.de/itm/227534369510 |
| Original Display für Samsung Galaxy S25 Edge SM-S937B OLED mit Rahmen Schwarz | Отсеять | https://www.ebay.de/itm/397349158680 |
| Original Display für Samsung Galaxy S25 Edge Service Pack mit Rahmen | Отсеять | https://www.ebay.de/itm/137722598679 |
| Samsung S25 Edge OLED Display Ersatz mit Rahmen Titan Schwarz Aftermarket+ | Отсеять | https://www.ebay.de/itm/168409770689 |

## Подтверждённая ошибка и изменение

1. `_is_category_blocked_title` у Python мог ответить «не запчасть» на `iPhone 16 Pro Max Display Ersatzteil`, несмотря на отбрасывание этой позиции специализированным классификатором. Теперь общий guard использует `_is_phone_accessory_title`.
2. Python-фильтр отклонял индексированное объявление настоящего `REDMAGIC 11 Pro … Gaming Transparent` по слову `transparent`. Добавлен ограниченный допуск прозрачной расцветки **только** при распознанной модели, памяти и явном признаке целого смартфона без других аксессуарных слов. Чехлы `Transparent Case` по-прежнему должны отбрасываться.
3. Реальные названия из каталога оформлены как регрессионные случаи и тестируются и в Python, и в Kotlin. CI-вердикт нужно читать из свежего запуска, а не считать сохранённые expected результаты тестами, пока они не прошли.

## Остаток приёмки (не закрыт)

- Независимое чтение **40–50 актуальных уникальных объявлений** по каждому из 24 отслеживаемых товаров (или весь доступный каталог), включая все 4 корзины поиска, различные алиасы, сортировку, пропущенные дешёвые лоты, добавочную доставку и переключение API ↔ HTML.
- Полные описания собственного продавца (iframe), HTML-структура продавца, рейтинг, состояние, ключевые детали дефектов/ремонта, время окончания и повторный контроль конкретных eBay ID.
- Проверка применения **16 скрытых ID** и глобального бана продавца на текущих production данных без их изменения.
- Доставка уведомлений рабочим ботом 047 в Telegram, проверка дедупликации, запуск/обновление Android на физическом телефоне с прежним ключом подписи.
- Не переносить в `main` или на телефон неподтверждённые исправления; текущая ветка `codex/cloud-work` отдельно от production.
