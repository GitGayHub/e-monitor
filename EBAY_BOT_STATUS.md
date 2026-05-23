# eBay Monitor Bot — Текущий статус

## Запуск
```powershell
.\run.ps1
```

## Архитектура

### Файлы
- `monitor.py` — основной бот (парсинг eBay, фильтрация, Telegram уведомления)
- `settings_handlers.py` — Telegram меню (поиски, проверка, статистика, фильтры)
- `config_manager.py` — управление config.json
- `config.json` — все поиски, бан-листы, настройки
- `price_history.py` — SQLite статистика цен
- `plz_distance.py` — расчёт расстояния по PLZ (Haversine)
- `plz_geocoord.csv` — координаты 8299 немецких PLZ
- `run_launcher.py` — launcher: git pull → bot → git push
- `run.ps1` — PowerShell обёртка (загружает env, убивает старые процессы)
- `set_env.bat` — токены (НЕ коммитится, в .gitignore)

### Переменные окружения (set_env.bat)
```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=5326338543
GITHUB_TOKEN=your_github_pat_here
GITHUB_REPO=GitGayHub/ebay-monitor
EBAY_CLIENT_ID=your_ebay_client_id_here
EBAY_CLIENT_SECRET=your_ebay_client_secret_here
EBAY_MARKETPLACE_ID=EBAY_DE
EBAY_SOURCE=auto
```

### Git remote (токен в URL, без credential manager)
```
https://your_github_pat@github.com/GitGayHub/ebay-monitor.git
```

## Поиски: 30 товаров, 63 варианта

Категории (все назначены, 0 в "all"):
- Ноутбуки: 4050 oled, 4060 oled, Vivobook OLED
- Компьютеры: 4070 Ti, 4080, 5070
- Смартфоны: iPhone 15/16 PM, Samsung S24U, OnePlus 12/Ace, Nubia Ultra, Red Magic, Pixel 5
- VR: Quest 3, Pico 4, Vive Ultimate, Full Body Tracking, SlimeVR, Slime Tracker
- Мониторы: LG Ultragear OLED, Samsung Odyssey G6/OLED
- Консоли: PS5, PS5 Pro
- Наушники: Sony XM5, XM6, ULT Wear
- Мыши: Logitech Superlight 2

## Фильтрация (трёхуровневая)

### Телефоны
- PHONE_HARD_PART_WORDS — всегда блокирует (motherboard, digitizer, lcd...)
- PHONE_SOFT_ACCESSORY_WORDS — блокирует если нет device hint/storage/model
- PHONE_HARD_ACCESSORY_WORDS — блокирует если нет device hint/storage
- Титулы с "Für/Fuer/For" — всегда аксессуар
- `_has_phone_storage()` — 128/256/512gb отменяет soft words
- `_title_leads_with_phone_model()` — модель в начале отменяет soft words

### Консоли
- Требует device hint (konsole, disc edition, blu-ray, 825gb, cfi-)
- Нет hint = игра/аксессуар → блок
- Лимитки с "Konsole" проходят (PS5 Ghost of Tsushima Edition Konsole)

### Наушники/VR/Мониторы
- Философия: "пропускай всё, блокируй только подтверждённый мусор"
- `_is_category_blocked_title()` ловит запчасти по CATEGORY_ACCESSORY_WORDS
- Для headphones: блокирует только "ersatz/oem/linke/rechte" (spare parts)

### PC
- Требует хотя бы один PC hint (gaming pc, ryzen, ram, ssd, i7...)
- Блокирует standalone GPU (grafikkarte only)

## Уведомления

Формат:
- 🛒 Sofortkauf: `💰 🛒 500€ 🤝` (🤝 = Preisvorschlag доступен)
- 🔨 Аукцион: `💰 🔨 Ставка 450€ · 2T 23Std` + рыночная цена если сильно ниже
- Non-EU: `⚠️ +124€ пошлина → итого ~642€` (19% VAT + 4% customs + 5€)
- Abholung: `📍 Abholung ~22km` или `📍 Abholung ~174km (Berlin)`
- Скрыть/Бан: зачёркивает сообщение, видно при скролле

## GitHub Actions

### Self-trigger цепочка
Workflow сам себя перезапускает через `workflow_dispatch` после каждого реального запуска.
Cooldown: 14 минут между реальными запусками.

### Backup: cron-job.org
Настроен на https://console.cron-job.org — каждые 15 минут POST к GitHub API.
Если self-trigger порвётся, cron-job.org перезапустит цепочку.

### Логи (run_log.json)
Каждый запуск записывает: время, trigger source, new items, blocked, source.

### eBay API (fallback)
- `EBAY_SOURCE=auto` — HTML scraping основной, API при блоке
- При блоке: сразу retry через API в том же запуске (не ждёт следующий цикл)
- Квоты: ~5000/день, реально тратится ~0 (блоков почти нет)

## Известные особенности

- `price_history.db` конфликтует при git merge (бинарный файл) — решается force push
- GitHub Actions перезаписывает config.json каждый запуск — категории нужно фиксить если Actions взял старый config
- Ctrl+C: `os._exit(0)` в signal handler → мгновенная остановка → launcher пушит state
- `_is_eu()`: UK/CH/US явно исключены, короткие коды (ie, it) не матчат внутри слов

## Telegram меню

- 📋 Поиски — список по категориям
- ➕ Добавить — wizard добавления поиска
- 🔎 Проверка — мгновенная проверка eBay по выбранному товару
- 💰 Мін. цены — минимальные цены за 7 дней
- 📊 Статистика — медиана за 30 дней (Sofortkauf + Аукционы)
- 🚫 Стоп-слова — exclude/include words по поискам
- ⚙️ Настройки — ZIP, НДС, бан-лист

## TODO / Что можно улучшить
- Статистика аукционов пока пустая (нужно время на сбор данных)
- OnePlus Ace: 0 результатов на eBay.de (все аксессуары, телефон редкий)
- Pixel 5 за 50€: нереальная цена, можно поднять лимит или убрать
