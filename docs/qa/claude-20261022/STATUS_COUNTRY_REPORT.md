# Claude — статусы HTML/API и страна товара (e-monitor-android#2), 22 октября 2026

База: bot `codex/cloud-work` `85355923702ca5117bc3ad6a8f19ce67b7446654`, Android `codex/cloud-work` `12bbd327ec5a33190ce21849b0f960486c813903`. Ветки `claude/html-api-status-country` в обоих репозиториях. Работа не пересекается с очередью из PR e-monitor#3.

## Уже работало (проверено, не переписывалось)

* Честный ноль с рекомендациями («0 Ergebnisse» + карточки ниже) → ноль в обоих парсерах (`search_response_oct16`, `mobile_search_status_oct20`).
* «Something went wrong» → `site_error` / `SiteUnavailable`; «Pardon Our Interruption» → `blocked`; контейнер без карточек → `parse`.
* Ошибка дополнительного alias не теряется: Python `_fetch_html_primary` хранит `errors[0]`, Kotlin `QueryVariants.merge` — первую ошибку, а для `all` — `formatErrors`.
* Python не угадывает страну по маркетплейсу (`_api_location` → пусто). Пикап-карта `Brand-Erbisdorf DE 09618` уже исправлена ранее.
* Положительный вердикт по-прежнему требует собственного описания. DOM-правило вариантов 0.137 (CSS `rx-msku-evo`) не тронуто.

## Найденные реальные дефекты и исправления

| # | Где | Вход | Было | Стало |
|---|---|---|---|---|
| 1 | Python Telegram + Kotlin `CountryRules` | `Sofia, Bulgarien`, `Hongkong`, `Istanbul, TR` и др. — 24 из 33 мест fixture | `None` → Telegram «🌐 Страна │ Не указано» | Код страны: 13 стран ЕС и 9 вне ЕС добавлены в таблицы обеих реализаций |
| 2 | Kotlin `CountryRules.code` | `Berlin, de` | `null` (Python давал DE) | DE — тот же разбор полей по `,`/`\|`/`/`, что в Python |
| 3 | Kotlin `EbayBrowseClient.location` | карточка Browse без `itemLocation` | **«DE» по маркетплейсу ebay.de** | пусто: неизвестное остаётся неизвестным, как в Python |
| 4 | Kotlin `emptySearchError` | HTTP 200 `/splashui/challenge` (только форма), немецкий заголовок «Bitte entschuldigen Sie die Störung», reCAPTCHA | `Parse` → «не удалось прочитать выдачу eBay» | `Blocked` → «сайт eBay запросил проверку доступа» (паритет с Python `_description_is_protection`) |
| 5 | Python `mobile/runtime_status.search_issues` (серверный статус в APK) | `http_403`, `http_429`, `http_500`, `api_auth`, неизвестный код | **«Не удалось полностью проверить описание или цену»** | `blocked (403)`, `rate_limit (429)`, `http (500)`, `api_auth`, `unknown` с понятным текстом; `details_unavailable` — только при реальной недоступности описания или цены |

Таблица fixture «вход → статус/страна»: `qa/fixtures/search_challenge_oct22.json` и `qa/fixtures/country_location_oct22.json`. Байт-в-байт те же файлы лежат в Android `app/src/test/resources/`, оба набора тестов читают их.

Решения по региону не меняются: страны ЕС и Турция/Индия и раньше определялись запасными списками имён (`_is_eu`, `_is_clearly_non_germany_location`). Новое поведение только одно: под фильтром `de` лот, о котором точно известно, что он в HK/TW/KR/IL/UA/SG/RS, теперь отсекается (раньше считался неизвестным). Сами запросы и так ограничены `LH_PrefLoc=1` / `itemLocationCountry:DE`. Это изменение фильтра местоположения, поэтому решение о повышении History оставлено Codex при интеграции. Номер я не занимал.

## Проверки (реально выполнены)

* Исходное поведение Python на новых fixtures (до правок): 24 места → «Не указано»; `http_403/429/500`, `api_auth` → `details_unavailable`; challenge/truncated/zero — уже верно.
* `python qa/run_unit_tests.py` (изолированно): **501 tests OK** (+4 `test_status_country_oct22`). Базовая линия ветки до правок — 497.
* Android: `StatusCountryOct22Test` (3), `CountryLocationTest` (1), `SearchResponseStatusTest` (2) — 6/6 PASS. Полный `testDebugUnitTest`: **424 tests / 94 suites, 0 failures/errors/skips**; `assembleDebug` PASS (Windows, JDK 21). На исходном Kotlin-коде `StatusCountryOct22Test` — **3/3 FAIL**.

## Ограничения

* Fixtures — синтетические сокращения. Реальные страницы eBay не запрашивались (live challenge — правило «немедленно остановиться»), ручная проверка 40–50 лотов не выполнялась.
* CAPTCHA не обходилась. HTML по-прежнему может быть ограничен сайтом; исправлена только честная классификация.
* Не унифицировано (известное расхождение): страницу без SERP-контейнера (consent/interstitial) Python называет `blocked` («stealth»), Kotlin — `Parse`. Оба варианта не превращаются в «Не найдено». Менять Python-эвристику без живых образцов не стал: она управляет API-circuit.
* Не проверялось и не менялось: телефон, PC Telegram, production state, Actions.
