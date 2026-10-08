# eMonitor — состояние работы между ПК и Cloud

Обновлено: 8 октября 2026. Checkpoint: **2026-10-08-cloud-047**. Работа по двум пользовательским планам **НЕ завершена**.

## Где работать

Оба репозитория: `GitGayHub/e-monitor` (Python) и `GitGayHub/e-monitor-android` (APK). Для дорожной работы подготовлены ветки `codex/cloud-work`; начать с одинакового checkpoint в `docs/CLOUD_CHECKPOINT.json`. Рабочий бот продолжает отдельную `main` с режимом normal. На ПК основной бот: `C:\VibeCoding\e-monitor`; Android: `C:\VibeCoding\e-monitor-apk\android`.

В конце каждого завершённого этапа обновить этот файл вместе с кодом: изменённое поведение, проверки/реальные результаты, ветка и commit обоих проектов, следующий шаг, недоступные сценарии. Совпадение Python и Kotlin не является независимой оценкой правильности.

## Обязательные пользовательские решения

- Сохранить production mode normal, получателя Telegram, действующие поиски и seen.
- iPhone 15 Pro Max удалён через приложение в восстанавливаемую корзину.
- iPhone 16 Pro Max — 610 €, оба варианта; iPhone 17 Pro Max — 910 €; Samsung S25 Edge — 325 €; LG — 430 €.
- 48 сохранённых / 46 активных поисков / 24 товара. Применённая ревизия c90d1470-2f38-4d43-87dc-9369e634c61b.
- ПК без накопителя **оставлять**. Политика запрета заменённой сторонней батареи отдельно не подтверждена; не придумывать запрет.
- При исчерпании eBay API переходить на HTML. HTML-ошибку/капчу/недоступное описание не превращать в «Не найдено». Непроверенный лот не подходит и не отправляется.
- До нового сообщения пользователя физический телефон не трогать. ПК скрыто, без переключения/активации окон. В Cloud физический телефон и локальный AyuGram недоступны.

## Исправлено в текущем коде

Настройки bestOffer/пустые/нули, ревизии и ACK сервера, общий лимит всех вариантов, удаление/восстановление, независимая проверка товара/корзины, «Обзор» вместо Telegram-ленты, этапы прогресса. Модель iPhone привязана к поколению; CPU/отдельный model number проверяются; исправлены детали Sony f. Sony swivel/spindle/buckle/Drehgelenk, аксессуары, SIM/зарядка/ремонт и ложные запчасти из батарейных процентов. OLED определяется по подтверждённой модели и собственной панели.

Текущее дополнение 047: автоматический HTML после квоты; OR-пакеты названий <=100 для Browse; отдельные HTML BIN/AUC с объединением гибридных флагов/цен; полный seller iframe имеет приоритет над кратким inline-текстом; dt/dd характеристики, собственный продавец/тип/рейтинг, проданные объявления, время аукциона. Приложение заново фильтрует обновлённые данные. На сервере HTML-очередь по 8 поисков, backoff неудачных попыток и ограничение прохода для сохранения checkpoint.

Эмуляторный путь приведён к настоящему WebView-заголовку; item pages запрашивают полный вид. WebView в эмуляторе уничтожается после страницы; бюджеты достаточны для двух форматов и описаний. Свежее приложение принимает ревизию реально загруженной конфигурации, чтобы распознать ACK; новое редактирование не подтверждается старой ревизией.

## Доказательства и версии

- Python: 231 изолированный тест OK. Android: 224 теста OK, APK собрана. Cloud merge: 5 проверок OK, включая реальный Git merge опубликованного snapshot с локальными правками и конфликт/удаление. Первый чистый Linux CI выявил зависимость старого теста размера страницы от среды: на Actions предусмотрено60, наПК240. Теперь тест явно проверяет оба режима;231тест повторно прошёл с GITHUB_ACTIONS=true. Повторный Linux CI ещё нужен.
- Рабочий код бота 047 опубликован: e17d4fdb869d5273082b6acc3b7e6931063be25a, правила 1791439498. Источник APK 047 выгружается этим checkpoint; точные commits см. CLOUD_CHECKPOINT.
- APK 047 в скрытом эмуляторе Android 16: SHA256 2ADE4B1E471948D7195B4523A9598E271495905339FD56132CE59E119F4599AA. Физическая APK 047 более ранняя; одинаковое имя не доказывает одинаковый бинарник.
- Изолированный живой Python при квоте 0: 60 HTML-лотов / 0 Browse API-запросов; 128121409205 принят, 189051391793 с заменой заднего стекла отказ, 117448535436 с несовместимыми CPU/model отказ. Полные описания вручную прочитаны в настоящем браузере повторно 8 октября.
- Эмулятор через UI: iPhone16 четыре корзины за 115479 мс: Sofort 606,19 (257781838595), Sofort+ 656,19 (168725281592, дорого), Auktion 208,00 (800756316838, время неизвестно), Auktion+ 303,32 (128121409205). Это частичная проверка, не итоговая приёмка. Отдельная проверка ремонтированного 189051391793 в списке Auktion+ ещё требуется.
- Нужна сверка HTML-времени/продавца в фактическом Android-HTTP ответе: в debug projection время 128121409205 не записалось; seller не был включён в разрешённые debug-поля. Не выдавать это за проверенный end-time/seller blacklist в приложении.
- До публикации 047 сервер фактически использовал правила 1791415329 / 046, state error с HTML-ошибками нескольких поисков; lastSuccessfulRun 2026-10-07T22:45:33+00:00. Новый runtime ACK047 подтверждён8Oct06:20UTC:правила1791439498,та жеc90ревизия/46активных/fingerprint28be3a9...;lastSuccessfulRun06:16:55UTC. На06:20:39stateerrorиз-заnubia_z80_ultra_leading_buy:network. Этоуспехотдельногопроходаочереди,НЕвсех46поисков.
- Telegram 119905 прочитано в правильном AyuGram: исторический LOCAL035 LG 423,99 / лимит430. Финальный тест047 и рабочая доставка новой версии ещё **не подтверждены**.

## Независимый аудит — неполные количества

| Товар / группа | Проверено | Что осталось |
|---|---|---|
| iPhone16 | 47 уникальных, 45 полных описаний | свежая API-сверка после квоты; батарейный пример условно разрешён текущей политикой |
| iPhone17 | >=48 в прежнем ledger + новые | дедупликация, все корзины и свежие минимумы |
| S25 Edge | 45 / 42 полных браузерных | 3 iframe недоступны браузеру, ранее API полные; актуальные минимумы |
| S24 Ultra | около50 с новыми | сверить ID и время, прежний дешёвый лот продан |
| Sony XM6 | 45 / 45 | старые дешёвые проданы, свежие минимумы |
| Sony ULT | 41 + новые реальные детали | часть описаний в TXT; свести доказательства без двойного счёта |
| ПК5070Ti | 50 / 49 полных | 1 iframe empty, неоднозначная видеокарта, все корзины |
| ПК4080 | 42 полных | цены/доставка/категория и независимые минимумы |
| Ноутбуки4050OLED | 18 полных | до40–50 или все доступные варианты |
| Ноутбуки4060OLED | 30 полных | дополнить и сверить минимумы/гибриды |
| PS5 Pro | 37 описаний + другие ledgers | дедупликация, точное количество и пустые корзины |
| Superlight2 | около50 в старом аудите | свести доказательства; DEX/Superstrike отдельно не закончены |
| Z70 | 26 полных | дополнить доступный каталог |
| Z70S / Redmagic / LG / G6500 | небольшие частичные выборки | все доступные объявления, пояснение реального малого каталога |
| Прочие активные товары | недостаточно | завершить все24; не считать таблицу полным покрытием |

Nubia Z80 Ultra Leading/LV должен показывать честное «Не найдено» только после успешных нулевых запросов. Старый браузер/API дали0; текущая ошибка HTML-запроса остаётся ошибкой, не подтверждает отсутствие.

## Следующий шаг

1. Если продолжается локально: завершить открытый picker «Проверить → Auktion+» iPhone16 в эмуляторе; 189051391793 должен быть отвергнут по настоящему iframe, 128121409205 допущен. Проверить time/seller на реальных входах, исправить подтверждённый пропуск.
2. В Cloud: начать с чистой проверки обоих репозиториев `tools/cloud-check.py`; далее общие случаи, причины HTML-ошибок, seller/time fields и независимое браузерное чтение доступного eBay. Каждый новый expected обосновывать ручным прочтением. Cloud не сможет подтвердить физическое устройство.
3. Прочитать mobile/runtime_status.json в рабочей main без изменения конфигурации; проверить ACK 047 и очередь/backoff. При APIreset проверить фактическую квоту; старый reset был 8Oct09:00Berlin.
4. Завершить все24 независимые выборки40–50/всё доступное; все корзины/пустые результаты/дешёвые пропуски/цены/сетевые ошибки/повторные отправки.
5. На ПК после разрешения пользователя обновить физическую APK с сохранением данных и подтвердить настоящую новую Telegram-доставку и повторный запуск. Финальный отчёт — после этих доказательств.

## Передача изменений

Облачная работа сохраняется в codex/cloud-work либо явно указанной отдельной ветке/PR. Для возврата `tools/cloud_sync.py --check`, затем чистый --apply и тесты. Резервные копии .cloud-sync-backups и private-аудит остаются на ПК. При конфликте не перезаписывать файлы и не очищать checkout. Не переносить production state из облачной ветки на рабочий сервер.

## Запись следующего этапа

При продолжении заменить эту секцию конкретной записью: дата UTC; среда Cloud/ПК; commits обоих репо; внесённые изменения; фактические тесты; браузерные ID и вердикты; недоступные проверки; следующий шаг. Не повторять старые результаты как новые.

## Продолжение через ChatGPT/GitHub — 8 октября 2026 (Cloud branch)

- Изменения делаются только в `codex/cloud-work` Android-репозитория; production `main` Python-бота, режим `normal`, получатель, поиски, seen, секреты и данные телефона не изменялись.
- Подтверждён CI Android `37743710421` (commit `aefa7d72341880b64672b1983ec5a3fa8c6ff6f2`): 231 offline Python-тест, 5 проверок облачного переноса, Gradle Android unit/build завершились успешно; создан свежий debug APK в GitHub Actions (artifact `11534639482`, zip 69 430 610 байт, SHA-256 самого APK `39c37627f5b0d1bc11c04f5865a6654e9c02b5700b63bab36d50b2af9df4d45d`). Это **не** APK физического телефона.
- GitHub Actions теперь использует парный `codex/cloud-work` Python-бота для облачной ветки Android и сохраняет debug APK в artifacts на 14 дней.
- Код Android в `6238b51d4d3d822226ae5f3cbc2d547db12cc620`: исправлена ошибочная атрибуция ставки при слове «Gebot» в рекомендациях; немецкое время аукциона распознаёт разделительные знаки и `Std.`/`Min.`; добавлены регрессионные случаи (часть синтетическая).
- Код Android в `a5050410c54751be08dceeac59a17c88f552439d`: seller iframe может запрашивать только доверенные HTTPS-хосты eBay, запрет проверки произвольных локальных/чужих адресов; добавлен отдельный unit-тест.
- Последний лично прочитанный runtime Python `main`: `2026-10-08T07:38:24Z`, `state=ok`, `logicVersion=1791439498`, `activeSearches=46`, `dataSource=api`, `error=null`. Один успешный проход **не** доказывает завершение полного аудита.
- CI `37744483140` (ставки/время) завершился **success** в 2026-10-08T07:44:22Z: 231 Python unit, 5 Cloud sync, Android Gradle unit/build; APK SHA-256 `d30cb04e7c88c827e86bfbb294fcd3dd1b26bb64d835a4f536918edcc11e9f88`, artifact `11535865645`. CI `37744707396` (доверенные iframe) ещё выполняется; его результат не объявлять успешным до проверки. Окружение Codex Cloud в аккаунте не создано/не подтверждено через эту сессию GitHub.
- Следом: проверить последние CI и APK SHA, реальные сведения seller/time из HTTP на Android, ручную сверку eBay (сайт был недоступен через текущую среду), все 24 товара, настоящую доставку Telegram 047 и установку с прежней подписью **только** после доступности устройства. Обновление поверх установленной APK не тестировалось; ключ подписи телефона отсутствует в Cloud.


## Независимый веб-индекс + исправления поисковых фильтров (8 октября 2026)

- Среда: GitHub-connector + публичная поисковая индексация eBay. Прямой интерактивный браузер eBay/Playwright не был доступен, и это **не считается живой приёмкой**.
- Проверены фактические read-only настройки production mobile manifest (main): **48 поисков / 46 активных**, глобальный заблокированный продавец `talk point gmbh`, **16 скрытых ID**. Не меняли настройки, mode, адресата, seen или ключи.
- В обоих `codex/cloud-work` сохранены 31 контрольный случай: 18 источников с индексированными eBay-страницами, остальные явно помечены как синтетические / старые материалы. JSON: `qa/fixtures/web_indexed_listing_cases_2026-10-08.json` в боте, `app/src/test/resources/web_indexed_listing_cases_2026-10-08.json` в Android. Результат — только `title-intent + seller blacklist`, не цена, не live-availability.
- Python: `_is_category_blocked_title` вызывает единый `_is_phone_accessory_title`; устранён ложный отказ для настоящего RedMagic 11 Pro Transparent Edition при наличии подтверждения модели/памяти/устройства, **но не для чехлов Transparent Case**. Kotlin `PhoneRules.accessory` применяет аналогичный ограниченный критерий.
- Ссылки и внешний аудит в `qa/results/WEB_INDEX_AUDIT_2026-10-08.md` бота / `docs/qa/WEB_INDEX_AUDIT_2026-10-08.md` Android. Исторический `HONEST_AUDIT` не является доказательством пропуска, когда найден Pixel 4a 5G вместо Pixel 5.
- CI ранних прогонов обнаружил полезные ошибки, поэтому существовали красные запуски `37747518085` и `37747639068`. Исправления вносятся по результатам. Новые CI `37748158919`, `37748234092`, `37748483788` **были в процессе на момент этой записи**; не считать их прошедшими до явного `success`. Последний подтверждённый успешный полный CI до этих QA-изменений: `37744707396`.
- Cloud commits на начало записи: Python `b3005f2c82e7152fb5be11876922efab138c9d78`, Android `a5688b93b940398f56d5e70835579f350bed825d`. Только cloud-work, без переноса в main.
- НЕ закрыто: независимая полная проверка каждой из 24 групп (40–50 актуальных лотов либо всё доступное), все 4 корзины, описания и продавцы, цены/доставка, действительная API/HTML выдача, Telegram 047 и APK на физическом устройстве.

## Отдельные подтверждённые исправления после веб-аудита (8 октября 2026)

- Независимо открыты eBay [358301335572](https://www.ebay.de/itm/358301335572) — модель REDMAGIC 11 Pro 16/512 Transparent действительно целый телефон, **но лот уже не в наличии**; [227534369510](https://www.ebay.de/itm/227534369510) — другой целый REDMAGIC 11 Pro, но цена открытия аукциона 750 € выше рабочего лимита 400 €. Корректный позитивный тест модели не является положительным вердиктом о покупке или уведомлении.
- Другие веб-контроли: [157875418037](https://www.ebay.de/itm/157875418037) RTX4050/OLED — явно `DEFEKT` и продан; [800366377085](https://www.ebay.de/itm/800366377085) LG 27GX790A-B 480Hz OLED — модель соответствует, но цена, доставка и собственный текст продавца требуют живой повторной проверки до уведомления.
- Помимо фикса REDMAGIC Transparent Edition улучшена проверка явного отрицания **«kein Ersatzteil»** у полноценного телефона с моделью и памятью; действительные запчасти/чехлы/дефекты не должны проходить. Python `monitor.py` commit `b3005f2c82e7152fb5be11876922efab138c9d78`, Android `PhoneRules.kt` commit `a5688b93b940398f56d5e70835579f350bed825d`. Дополнительные тесты обоих репозиториев.
- HTML-описания `Nicht mehr vorrätig` / `Out of stock` теперь интерпретируются как `UNAVAILABLE`, только если статус находится в собственном блоке quantity/status, а не в сторонних рекомендациях. Python commit `88af71ddcae2131584a054259fa74a72d2762d18`, Android `801bb5980521863a4fd558f5db9ad6375cccf33c`; добавлены тесты настоящего статуса и синтетических контрольных случаев. Точное соответствие DOM eBay в реальном Android-HTTP остаётся непроверенным.
- Подробная отдельная запись с доказательствами: `qa/results/WEB_AUDIT_2026-10-08_CHATGPT.md` в Python-репозитории.
- На момент записи полный CI со **всеми последними исправлениями** всё ещё выполняется, включая Android Actions run `37748852705`; не утверждать, что финальная APK уже прошла тесты, пока статус не станет success. Уже подтверждённый предыдущий успешный run `37744707396` относится к прежнему состоянию ветки.
- Как и прежде, `main`, production mode/recipient/searches/seen, действующие чёрные списки и физическая APK не менялись. Всё ещё необходимы полный независимый live-аудит 24 продуктов, работающий браузер/Playwright, тест доставки Telegram 047 и подписанное обновление на устройстве.


## Проверенный CI независимого index QA (8 октября 2026 08:20 UTC)

- **GitHub Actions `37748234092` — SUCCESS**, Android commit `7a376e0cdde8f5a142e05c892d5d1ad0830d1016`. Реально выполнены 233 offline Python-теста, 5 Cloud-sync тестов и Android Gradle unit/build. Сам APK SHA-256: `e1640e1a0a3597ccf78e042224ea95baf729a6e232687795d0a5956c46fd8fc7`. Это был набор **28** карточек (а не позднейшие 31).
- Добавлены ещё 3 реальные индексированные дисплейные запчасти Samsung S25 Edge; в текущих публичных fixtures теперь **31** случай. Не объявлять их зелёными на основании более раннего #37748234092; дождаться нового CI.
- В GitHub создана полная read-only матрица **24 продуктов / 48 поисков / 46 включено**: `qa/results/ACTIVE_SEARCH_MATRIX_2026-10-08.md` бота, `docs/qa/ACTIVE_SEARCH_MATRIX_2026-10-08.md` Android. Не изменяли пользовательский manifest.

## Повторный аудит вариантов поиска Sony XM6 (8 октября 2026, GitHub + публичный веб)

- Публичная страница `https://www.ebay.de/itm/377067104303` подтверждает название целых **WH-1000XM6** наушников, но цена 521,71 € превышает цель 200 €; это тест модели, а не доступная сделка.
- Индексированы также аксессуары/чехлы и проданные лоты; название товара, реальное состояние, продажа и цена должны проверяться отдельно.
- Дополнены алиасы `Sony WH-1000XM6` / `Sony 1000XM6` / `1000XM6` в Python `query_variants.py` (`f1c04013fcf6df5cb9cb8f49982ed0530cd6654c`) и Android `QueryVariants.kt` (`2cc87eabb507420419175c90d75522be8ab21410`). WH и WF генерации не смешиваются в явных алиасах; финальный фильтр аксессуаров сохранён.
- Прежний дефис `WH-1000XM6` уже корректно нормализовался; **реальный пропуск** был у объявления с написанием только `1000XM6` без `WH` — исправлен именно этот случай.
- Android Actions `37750723357` запущен, результат считать не подтверждённым до явного `success`; изменение не развернуто в production `main` и не установлено на телефон.

- Дополнительно добавлено **5 контрольных карточек с открытых публичных eBay-страниц** (Pixel 5 Display/варианты; iPhone 16 Pro Max repair service/стекло; Sony WH-1000XM6 — наушники против compatible case) в общие Python/Android JSON fixtures. В снимке после добавления **41** случай. Сравнение проверяет title/device intent и banned seller, но не утверждает актуальную доступность лотов; CI сборки с новыми cases ещё не подтверждён.

## CLOUD ACCEPTANCE HANDOFF — 2026-10-08

Owner instructed continued autonomous work on accurate live eBay search and banning, not just APK. See **docs/CLOUD_SEARCH_ACCEPTANCE_2026-10-08.md** and machine-readable **docs/qa/CLOUD_ACCEPTANCE_QUEUE_2026-10-08.json**, published in BOTH cloud-work branches. 24 products × 4 buckets = 96 initially PENDING checks derived from 48 stored/46 enabled searches in read-only production manifest. Real live evidence, seller, description, prices, missed cheap items, wrong-device/parts and false positives must be assessed; previous 41 web-index cases only establish titles. Report actual CI HEAD and APK hash. Keep production normal, Telegram, limits, searches, seen and blacklist untouched; physical phone inaccessible. Cloud handoff documents alone do **not** start a Codex Cloud task, and acceptance remains NOT DONE.


## Реальная Cloud-сессия 2026-10-08T09:07:32.561248+00:00 — промежуточный checkpoint

Работа в обоих codex/cloud-work; исходные Python 117c9095409c0bce5ae154e1d777f6610d41f4e4 / Android 8553f6634e9a9f8e2c38a86aabf20018fa3c7eae. Окружение теперь действительно доступно: Python3.12, Chromium/Playwright, SDK36, отдельный JDK21. .de выдача/страницы часто CAPTCHA; .com HTTP даёт собственные данные и seller iframe. Без подмены Германии условиями доставки США.

Исправления обеих реализаций: итальянский Numero modello/Modello не может скрыть несовместимый iPhone (реальный 117449336412); собственный Item sold on распознаётся UNAVAILABLE, независимо от end date. Фикстуры одинаковые, synthetic controls явно помечены. Python logic_version 1791449810 — только Cloud, не deployment.

Baseline237 Python +5 sync OK; после первого фикса238 Python OK. Последние Android tests/build и CI пока в работе. Подробные новые доказательства: https://github.com/GitGayHub/e-monitor/blob/codex/cloud-work/qa/results/cloud-live-20261008/REPORT.md . Десять специальных лотов повторно открыты, полный текст коротких описаний прочитан; repair/sold/parts/дорогие лоты не пригодные сделки. 128121409205 модель/own seller/time подтверждены HTTP .com, доставка DE и реальный Android HTTP не подтверждены.

Часть24×4 очереди обновлена с явными dependency BLOCKED и verifiedUnique0; directBucketAcceptancePerformed=false означает, что отдельная корзина не пройдена. Сбор оставшихся групп продолжается. Количества fetched descriptions не выдавать за независимые40–50 подходящих товаров. Production main/mode/searches/limits/seen/blacklist/Telegram/телефон не менялись. Общий статус PARTIAL. Следом — завершить доступный сбор, latest tests/build, GitHub CI актуального HEAD и парный checkpoint.


## Cloud acceptance checkpoint 2026-10-08T09:31:47.972475+00:00

PARTIAL. All24 groups recorded;96 baskets BLOCKED by original DE-profile catalogue/destination dependency, not96 executed basket checks.68 bounded independent .com requests,500 records/498 IDs,483 own item pages,478 fetched seller bodies.25 reviewed records/22 whole bodies read. No complete catalogue, suitable DE listing, minimum or no-results proof.

Paired fixes: Italian model labels and own Item sold on status (earlier checkpoint), exact Lightweight adjective vs weights, explicit snapped/broken headphone structure, non500Hz G6 contradiction despite model code, one complete hypothetical return-policy promise vs actual failure. Actual parts/damage and negative/benign controls retained.13 identical private full seller-body/aspect relevance inputs agree in Python and local JVM Kotlin;25 public paired cases. Full-body snapshots remain private.

Final local cloud-check:238 Python +5 sync +233 Android tests passed;APK built. Local debug APK SHA256 e0796d146f54b760680fc5aa66cddc0b59f8dee49875814ad1495236cb6a0b86. Logic version 1791451374 (Cloud only). Prior Android CI37754559306/e700deae succeeded; it does not cover new final code. Final current-HEAD CI check remains pending publication at this commit timestamp. Companion: Android e700deae10f6a70cd5a08de62b0bfeb38c5ac052 (prior published checkpoint; final counterpart will be linked after publication). Shared report: https://github.com/GitGayHub/e-monitor/blob/codex/cloud-work/qa/results/cloud-live-20261008/REPORT.md

Cloud inherited network proxy began returning HTTP503 on GitHub and eBay during final recheck; use available GitHub Connector for safe non-force branch publication and CI reads. No protection bypass. Production main/mode/Telegram/searches/limits/enabled/seen/ban lists/raw manifest and physical phone preserved. All16 hidden IDs and seller-ban controls verified in isolated state; not live-owner retrieval proof.

Next: accessible .de40–50 unique reviewed IDs/group or complete smaller catalogue,4 basket profiles, Germany shipping/import totals, pagination/minima, actual seller/time Android HTTP. Ambiguous insured iPhone/chipped S24 and counted-button/scroll-wheel mice require own-photo/full-product clarification before filtering changes. PC cloud_sync --check before integration; no blind reset/clean/pull or phone install.


## Additional live mouse-feature checkpoint 2026-10-08T09:54:35.663385+00:00

Full seller body + own Type/Model/MPN/5-button aspects prove318767580494 is a whole Superstrike mouse. Both engines now remove counted-button feature wording only from declared mouse titles without compatibility/replacement/spare/repair/set/only wording. Real button sets/PCB/damage retained. Additional historical whole5-button Superlight rejection reason corrected to over-limit. No confirmed Germany delivered cheap deal.

Latest local cloud-check238 Python +5 sync +233 Android tests and APK passed;31 paired public cases,14 identical complete seller-body/aspect inputs. Owner16 hidden IDs + global/search-specific seller bans also passed isolated Kotlin replay, with allowed control kept; no state/list changes. Local APK SHA256 d6beeb65bb86245b073514c5e1690315701b2f72cd64a0cfbe68aa9711039c2f; Cloud logic_version 1791453018. Coverage now26 reviewed/23 full bodies read;500 records/498 IDs,483 own pages,478 fetched bodies;96 baskets still BLOCKED.

Previous exact Android ff85bd030d324bcdc5f90865b1090786a68ae612 CI37758006402 passed with Python66a033562014a2f2d951ec31ab5c44b2e6c6bd5b, artifact11541087919, APK9dc3a34af56772e91c15bc2e04e41908dd6672f763ae75592edb886b06c361c7. It does not cover this last fix; monitor new current-HEAD CI after publishing. Companion Cloud branch retains paired source; exact new counterpart recorded on publication. Production settings/Telegram/seen/searches/bans/main and physical phone untouched.

Continue only available DE profile/basket/delivery/minimum live acceptance, unresolved scroll-wheel accessory ambiguity, and authorized PC/device checks. Report remains PARTIAL: https://github.com/GitGayHub/e-monitor/blob/codex/cloud-work/qa/results/cloud-live-20261008/REPORT.md
