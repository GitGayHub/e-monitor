# Задача №1 (активная) — начать масштабный QA stats audit

Когда пользователь на **любом ПК** пишет что-то вроде:  
«продолжи» / «continue» / «дальше QA» / «продолжи проверку» —

агент **обязан** выполнить эту задачу, без переспрашивания «а что делать?».

---

## Цель задачи №1

Взять **первую позицию** из свежего статистического отчёта Telegram и **вручную** сверить все 4 корзины с eBay (multi-query aliases), записать результат.

Это **не** правка `mode.txt` и **не** багфикс кода — пока только audit. Код чинить только если явно нашли gap и пользователь ок (или после серии findings).

---

## Шаги (строго по порядку)

### A. Синхронизация

```text
git pull
```

Прочитать:

1. `qa/STATUS.md` (next_index, blockers)
2. этот файл `qa/FIRST_TASK.md`
3. `qa/WORKFLOW.md` + `qa/VALIDITY.md`

### B. Stats source

1. Если есть `qa/inbox/stats_paste.txt` →  
   `python qa/parse_stats_paste.py` → `qa/inbox/stats_parsed.json`
2. Если paste **нет** → **один раз** попросить пользователя вставить stats из Telegram в чат или в файл.  
   Пример формата: `qa/inbox/stats_paste.EXAMPLE.txt`
3. Без каталога позиций eBay-аудит **не** начинать вслепую.

### C. Позиция №1

- Взять product с `index == next_index` из `stats_parsed.json` (по умолчанию **0** = первая в отчёте).
- Зафиксировать baseline: 4 корзины Sofort / Sofort+ / Auktion / Auktion+ (цены, вердикты, ссылки *ТЫК*).

### D. Manual eBay (Playwright)

Для **этой одной** позиции:

1. Собрать aliases из `qa/query_aliases.json` (+ base query).
2. По каждой корзине: поиск на ebay.de, sort ≈ price+shipping asc, 4–8 query max.
3. Сравнить с baseline по `VALIDITY.md`.
4. Вердикты: `ok` | `ok_filtered` | `gap_cheaper` | `gap_missed` | `blocked_ebay`.

### E. Запись + handoff commit

1. `qa/results/<slug>.json` (из `TEMPLATE.json`)
2. Строки в `qa/results/findings.csv` если gap
3. Обновить `qa/STATUS.md`:
   - `Products done` += 1
   - `next_index` += 1
   - phase → `audit_in_progress`
   - session log
4. Если задача №1 закрыта по первой позиции — в STATUS написать **Задача №2 = следующая позиция (next_index)**.
5. `git commit` + `git push` handoff (results + STATUS), **без** secrets.

### F. Сколько за сессию

- Минимум: **закрыть позицию №1 полностью** (4 корзины).
- Если остаётся время/токены: можно 2–3 позиции, но №1 обязательна.
- Капча eBay → стоп, STATUS, commit.

---

## Definition of done (задача №1)

- [ ] Stats распарсены или явно запрошены у пользователя
- [ ] Позиция index=0 (или текущий next_index) полностью сверена
- [ ] Есть `qa/results/<slug>.json`
- [ ] `STATUS.md` обновлён и запушен
- [ ] Пользователю краткий итог: ok / gaps по 4 корзинам

---

## Триггер-фразы (для агента)

Считать командой «делай FIRST_TASK»:

- продолжи
- continue
- дальше
- продолжи проверку / QA / аудит
- с другого пк продолжаем
