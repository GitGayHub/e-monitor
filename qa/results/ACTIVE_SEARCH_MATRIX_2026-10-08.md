# Матрица действующих eMonitor-запросов — read-only снимок 8 октября 2026

Источник: опубликованный рабочий `GitGayHub/e-monitor/main/mobile/app_sync.json`. Это статический **снимок запросов и лимитов**, не новые предложения менять пользовательские настройки. Запросы в рабочей конфигурации не редактировались. Секреты, user ZIP, ключи API, Telegram, seen и личные параметры в матрицу не копировались.

**Всего 24 групп товаров, 48 сохранённых поисков, 46 включено, 2 отключено.**

| № | Запрос пользователя | Включено / всего | Лимит maxPrice (сырое значение) | Категория | Подчинённые поиски и типы |
|---:|---|---:|---|---|---|
| 1 | samsung galaxy s25 edge | 1/1 | 325€ | phones | samsung_galaxy_s25_edge (all) |
| 2 | iphone 17 pro max | 1/1 | 910€ | phones | iphone_17_pro_max (all) |
| 3 | Redmagic 11 Pro | 2/2 | 400€ | all | redmagic_11_pro_buy (buy_now_offer); redmagic_11_pro_auc (auction) |
| 4 | Redmagic 11S Pro | 2/2 | 450€ | all | redmagic_11s_pro_buy (buy_now_offer); redmagic_11s_pro_auc (auction) |
| 5 | Nubia Z80 Ultra | 2/2 | 375€ | all | nubia_z80_ultra_buy (buy_now_offer); nubia_z80_ultra_auc (auction) |
| 6 | Nubia Z80 Ultra Leading | 2/2 | 450€ | all | nubia_z80_ultra_leading_buy (buy_now_offer); nubia_z80_ultra_leading_auc (auction) |
| 7 | Nubia Z70 Ultra | 2/2 | 325€ | all | nubia_z70_ultra_buy (buy_now_offer); nubia_z70_ultra_auc (auction) |
| 8 | Nubia Z70S Ultra | 2/2 | 325€ | all | nubia_z70s_ultra_buy (buy_now_offer); nubia_z70s_ultra_auc (auction) |
| 9 | Pixel 5 | 2/2 | 70€ | phones | pixel_5_buy (buy_now_offer); pixel_5_auc (auction) |
| 10 | Sony WH-1000XM6 | 2/2 | 200€ | all | sony_wh_1000xm6_buy (buy_now_offer); sony_wh_1000xm6_auc (auction) |
| 11 | 5070 ti (pc, rechner, computer, desktop, gaming pc) | 2/2 | 1300€ | computers | 5070_ti_pc_buy (buy_now_offer); 5070_ti_pc_auc (auction) |
| 12 | 4080 (pc, rechner, computer, desktop, gaming pc) | 2/2 | 1200€ | computers | 4080_pc_buy (buy_now_offer); 4080_pc_auc (auction) |
| 13 | samsung s24 ultra | 2/2 | 350€ | phones | samsung_s24_ultra_buy (buy_now_offer); samsung_s24_ultra_auc (auction) |
| 14 | 4050 oled | 2/2 | 625€ | laptops | 4050_oled_buy (buy_now_offer); 4050_oled_auc (auction) |
| 15 | 4060 oled | 2/2 | 750€ | laptops | 4060_oled_buy (buy_now_offer); 4060_oled_auc (auction) |
| 16 | asus vivobook 14x oled | 2/2 | 425€ | laptops | asus_vivobook_14x_oled_buy (buy_now_offer); asus_vivobook_14x_oled_auc (auction) |
| 17 | logitech superstrike | 2/2 | 85€ | all | logitech_superstrike_buy (buy_now_offer); logitech_superstrike_auc (auction) |
| 18 | logitech superlight 2 | 2/4 | 45€ / 65€ | mice | logitech_superlight_2_std_buy (buy_now_offer); logitech_superlight_2_std_auc (auction); logitech_superlight_2_c_buy (buy_now_offer, выключен); logitech_superlight_2_c_auc (auction, выключен) |
| 19 | logitech superlight 2 dex | 2/2 | 65€ | mice | logitech_superlight_2_dex_buy (buy_now_offer); logitech_superlight_2_dex_auc (auction) |
| 20 | sony ult wear | 2/2 | 30€ | all | sony_ult_wear_buy (buy_now_offer); sony_ult_wear_auc (auction) |
| 21 | samsung odyssey oled g6 500hz | 2/2 | 400€ | monitors | samsung_odyssey_oled_g6_500hz_buy (buy_now_offer); samsung_odyssey_oled_g6_500hz_auc (auction) |
| 22 | (playstation 5 pro, ps5 pro) | 2/2 | 750€ | consoles | ps5_pro_buy (buy_now_offer); ps5_pro_auc (auction) |
| 23 | iPhone 16 Pro Max | 2/2 | 610€ | phones | iphone_16_pro_max_buy (buy_now_offer); iphone_16_pro_max_auc (auction) |
| 24 | lg ultragear oled 480hz | 2/2 | 430€ | monitors | lg_ultragear_oled_480hz_buy (buy_now_offer); lg_ultragear_oled_480hz_auc (auction) |

## Контракт корректности

1. **Алиасы для расширения охвата**, а не изменение целевой модели: iPhone 17 Pro Max ≠ 16; RedMagic 11 Pro ≠ 11S Pro; Z80 Ultra Leading ≠ обычный Z80; Superlight 2 ≠ DEX / 2C.
2. **Проверки полного товара после получения результатов**: запчасти, аксессуары, модели GPU, тип консоли и конкретная OLED-панель должны отсеиваться уже после расширенного запроса. Минус-слова eBay в `_nkw` могут скрыть честное `kein Ersatzteil`; они не заменяют локальный фильтр.
3. **Цена по верному формату покупки**: BIN и аукцион в гибридной карточке не взаимозаменяемы. Ограничения из пользовательского манифеста — отдельны от технических hardMax / дешёвых bait-floor отсевов. Не менять лимиты из отчёта.
4. **Чёрный список и завершённые объявления**: глобальный забаненный seller, 16 вручную скрытых ID, реальные eBay item endDate, факт завершения, полное описание и доставка применяются при финальном подтверждении, а не по одному title.
5. **Без ложных побед**: веб-индекс доказывает пример названия, но не действующее предложение; успешная Python/Kotlin паритетность не доказывает истинность обеих реализаций.

Связанный read-only аудит конкретных индексированных товаров: `qa/results/WEB_INDEX_AUDIT_2026-10-08.md` (Python) / `docs/qa/WEB_INDEX_AUDIT_2026-10-08.md` (Android). Незавершённая ручная выборка 40–50 живых объявлений по каждой группе — отдельная задача.
