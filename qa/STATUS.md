# QA status / handoff

## Auction buckets — closed 2026-07-26

The residual the night watcher left open on 2026-07-18 («auction SERP recovery,
11S / LG / G6 / 4080 / Superlight pure Auktion») is done: after three GH
iterations every one of the five reads the same as live eBay.

- mode: back to **`normal`** (AGENTS.md production default). `statistics` was on
  only as the measuring tool for this loop — while it is set the 5-min cron
  skips and no alerts go out.
- Loop used: change logic → push to `main` → run → read the report → compare
  against live eBay from the local PC → next change.

### Transport, run by run

| marker | pre-fix 30217151118 | iter 1 · 30218257391 | iter 2 · 30219818970 | iter 3 · 30221035184 |
| --- | ---: | ---: | ---: | ---: |
| `Page crashed` | 93 | 3 | **0** | **0** |
| `net::ERR_ABORTED` | 0 | 92 | **0** | **0** |
| `Playwright HTML fetch failed` | 93 | 92 | **0** | **0** |
| `soft-empty` | 144 | 164 | **0** | **0** |
| `Browse API clean empty` | 24 | 2 | **0** | **0** |
| `eBay HTML exhausted` → API last resort | 24 | 28 | **0** | **0** |
| `genuine no-results marker` | — | — | 162 | **166** |
| `⚠️ сбой загрузки` rows in the report | — | 6 | **0** | **0** |

The HTML chain resolves every search on its own now: no Chromium crash, no
aborted navigation, no Browse-API last resort, no bucket left in limbo.

### The 5 residual products — final

Ground truth taken the same evening from this PC (real Chromium + curl chain,
same URL builder and filters as the monitor):

| product | iter 1 | iter 2 | iter 3 | live eBay | verdict |
| --- | --- | --- | --- | --- | --- |
| Redmagic 11S Pro | ❌ Не найдено | ❌ Не найдено | ❌ Не найдено | «0 Ergebnisse» | **correct** |
| 4080 (pc, …) | ⚠️ сбой загрузки | ❌ Не найдено | ❌ Не найдено | «0 Ergebnisse» | **fixed** |
| samsung odyssey oled g6 500hz | ⚠️ сбой загрузки | ❌ Не найдено | ❌ Не найдено | «0 Ergebnisse» | **fixed** |
| logitech superlight 2 | Auktion ❌ / Auktion+ 70 € | same | same | lots exist | **recovered** |
| lg ultragear oled 480hz | ❌ Не найдено | ❌ Не найдено | **460 €** 🟣 | 1 lot, 450 € + 10.49 | **fixed** |

Everything else in the report is consistent with live eBay: markets with stock
(iPhone 15/16 Pro Max, PS5 Pro, S24 Ultra, 5070 Ti, 4050 OLED, Pixel 5, ULT
Wear) print auction prices, and the empty ones really are empty — checked
`4060 oled`, `asus vivobook 14x oled`, `samsung odyssey g6`: the auction SERP
returns 0 items with no error.

### Fixes so far

1. **Chromium crash** (5a137324c) — asset blocking, ad iframes out of their own
   renderers, escalating retries. `Page crashed` 93 → 3 → 0.
2. **Empty marker was unreachable** — `_parse_search_body` scanned only
   `body[:12000]`, while eBay.de renders «Keine exakten Treffer gefunden»
   ~150–200k into a 400–900k document (4080 @183989, G6 @196973). Now the whole
   body is scanned, but only when the page is a SERP with zero `/itm/` links,
   so a parser failure on a page that has stock can never be dressed up as an
   empty market. `test_serp_empty_marker.py`.
3. **`net::ERR_ABORTED`** — the `"**/*"` route intercepted the navigation
   itself. Blocking now hangs on asset globs only, `_pw_should_escalate` retries
   on `net::` errors, and the last attempt drops to plain Chromium on a 25-card
   page. Aborts 92 → 0.
4. **Auction bucket ≠ auction market** — the dedicated auction fetch only ran
   when the mixed page had *no* auction item. Empty auction buckets after
   filtering now trigger one dedicated fetch + re-filter (cap
   `_MAX_AUCTION_REFILLS = 10`, cap hits logged). It fired for LG in iteration 2
   and pulled the 450 € lot in — but the lot then died in the filter (below).
5. **«OLED … NEU» is not a spare part** — `_is_display_replacement` matched
   `(display|oled|glas|…) .* (neu|getauscht|…)` across the whole title, so
   «LG Ultragear 32GS95UX-B.AEU (32") 4K UHD OLED Gaming Monitor 240Hz/480Hz -
   NEU» (item 267738467047, 450 €) was thrown away as a replacement screen and
   the row printed «Не найдено» over live stock. Repair verbs still match at any
   distance; the bare "neu" family must now sit next to the display word; and
   monitors/TVs, where the panel *is* the product, skip the heuristic.
   Measured blast radius before the fix: exactly 1 live lot across the six
   OLED-ish auction searches. `test_display_replacement_rule.py`.

### Verified here (local, this PC)

- `python -m py_compile monitor.py config_manager.py` · `monitor_runtime_patch.py`
- `test_auction_serp_recovery.py` 16/16 · `test_serp_empty_marker.py` 8/8 ·
  `test_display_replacement_rule.py` 9/9
- Live Chromium on all five auction SERPs, before and after each parser change
- LG refill reproduced end to end: fetch → filter → bucket, now `Auktion=1`
- Pre-existing failures, reproduce on a clean tree, unrelated:
  `test_search_intent_rules.py` 28/29 (`_ipg` 120 vs ≥240),
  `test_details_filter.py` 12/13 (`test_hybrid_listing_prices_and_grouping`)

### Known gap (documented, not changed)

`_is_display_replacement` guards its negations only in front of the repair word,
so «ohne Display Austausch» still reads as a swap. Phone-filter behaviour,
untouched by this work — see `test_display_replacement_rule.py`.

## Alert timing (same session, not yet measured on GH)

Reported symptom: some links arrive while the listing is still fresh, others
about an hour late. Two causes, both in the code rather than in eBay:

1. **Visibility.** The monitoring profile fetches one price-ascending page
   (`_sop=15`, 60 cards on GH). A new listing that is not among the 60 cheapest
   matches is invisible until one of them ends. A lot in its last minutes sits
   just as deep — which would also have kept the new 15-minute alert from ever
   firing. When (and only when) the price page comes back full, i.e. the market
   really is truncated, the pass now also takes two 25-card pages: «newly
   listed» (`_sop=10`) and «ending soonest» (`_sop=1`, auction only).
2. **Cadence.** The workflow did two passes and exited, then waited for the
   5-min cron, which GitHub delivers late by 10–40 min routinely. The run is now
   time-boxed: it keeps sweeping for `RUN_BUDGET_SEC` (35 min) with 60 s between
   passes, and the concurrency group queues the next run right behind it.
   Statistics stays a single diagnostic pass.

**New auction stage.** Alerts were initial (≤24 h) → final_hour (≤1 h). Added
`final_15m`: a last call ~15 min before the hammer, sent only while the price is
still inside the limit. `seen_ids.json` carries a third flag and migrates old
files silently. `test_auction_final_stages.py` — 17 tests.

### Measured on GH — first normal run (30221996333, 21:53–22:36 UTC)

| | before | this run |
| --- | ---: | ---: |
| passes per run | 2, then wait for a late cron | **5** (21:54, 22:02, 22:11, 22:19, 22:27) |
| gap between passes | 2 min ×1, then 10–40 min of nothing | **~8 min, continuously** |
| listings the price page was hiding | invisible | **+39…48 per truncated search** |

`newly listed sweep added 39 item(s)` fired for iPhone 16 Pro Max, iPhone 15 Pro
Max (48), samsung s24 ultra (48), Sony WH-1000XM6 (16), logitech superlight 2
(44) — 30 sweeps in the run. Those items were simply not visible to the monitor
before: the price-ascending page 1 was full without them.

`ending soon sweep added` fired **0 times**, and that is the gate working, not a
bug: the auction-only SERPs come back with 21–29 lots, well under the 60-card
page, so the market is not truncated and every ending lot is already in the
primary fetch. The sweep exists for the day an auction market outgrows a page.

One alert went out during the run (iPhone 16 Pro Max, Sofortkauf,
`telegram_failed: False`), no fetch errors, no crashes.

Budget overshoot found and fixed: the loop only compared the remaining budget
against the sleep interval, so a 5th pass started at minute 34 and the run took
2406 s against a 2100 s budget — 42 min against a 45 min job timeout. It now
also accounts for how long the previous pass took, and the budget is 1800 s.

### Next step

- confirm «🔥 15 МИНУТ ДО КОНЦА» on a real lot: a pass has to land inside the
  last 15 minutes of an auction that is still under the limit
- watch that runs now finish inside ~32 min, well clear of the timeout

## Earlier

- Pre-fix evidence run 2026-07-26 17:11–17:13 UTC (every pure-Auktion pass:
  curl soft-empty → `Page crashed` ×2 → Browse API 0 → «Не найдено»)
- Post-fix verification kick — fix commit d50720c05 empty stats (DEX/ULT/G6/LG),
  2026-07-17T02:45 — done, see `qa/results/AUDIT_4BUCKETS_LATEST.md`
- 4-bucket audit results for 24 products: `qa/results/`
- Watcher stopped 2026-07-18 06:17 UTC, mode back to `normal`
- `TODO.md` (22 June) deleted: every item was already in the code and its
  «keep mode.txt = statistics» rule contradicted AGENTS.md (`normal` = prod).
