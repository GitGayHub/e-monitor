# QA status / handoff

## Active task — auction buckets must tell the truth

- mode: **`statistics`** on purpose — the 4-bucket report is the measuring tool
  for this loop. Back to `normal` (AGENTS.md production default) once the
  auction rows stop lying. While `statistics` is set the 5-min cron **skips**,
  so no alerts are being delivered.
- Loop: change logic → push to `main` → run → read the report → compare against
  live eBay from the local PC → next change.

### Where it stands after iteration 2 (GH run 30219818970, 20:50–21:14 UTC)

| marker | pre-fix 30217151118 | iter 1 · 30218257391 | iter 2 · 30219818970 |
| --- | ---: | ---: | ---: |
| `Page crashed` | 93 | 3 | **0** |
| `net::ERR_ABORTED` | 0 | 92 | **0** |
| `Playwright HTML fetch failed` | 93 | 92 | **0** |
| `soft-empty` | 144 | 164 | **0** |
| `Browse API clean empty` | 24 | 2 | **0** |
| `eBay HTML exhausted` → API last resort | 24 | 28 | **0** |
| `genuine no-results marker` | — | — | **162** |
| `⚠️ сбой загрузки` rows in the report | — | 6 | **0** |

The HTML chain now resolves every search on its own: no Chromium crash, no
aborted navigation, no Browse-API last resort, and no bucket left in limbo.

### The 5 residual products

Ground truth taken the same evening from this PC (real Chromium + curl chain,
same URL builder and filters as the monitor):

| product | iter 1 | iter 2 | live eBay | verdict |
| --- | --- | --- | --- | --- |
| Redmagic 11S Pro | ❌ Не найдено | ❌ Не найдено | «0 Ergebnisse» | **correct** |
| 4080 (pc, …) | ⚠️ сбой загрузки | ❌ Не найдено | «0 Ergebnisse» | **fixed** |
| samsung odyssey oled g6 500hz | ⚠️ сбой загрузки | ❌ Не найдено | «0 Ergebnisse» | **fixed** |
| logitech superlight 2 | Auktion ❌ / Auktion+ 70 € | same | lots exist | **recovered** |
| lg ultragear oled 480hz | ❌ Не найдено | ❌ Не найдено | 1 lot, 450 € | **still wrong** → fix 4 |

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

### Next step

Run **E Monitor** on `main` and check:

- `lg ultragear oled 480hz` — auction row must show the 450 € lot (🟣 Дорого,
  limit 430) instead of «Не найдено»
- `auction buckets empty after filter — dedicated auction fetch` still fires
  where it should, and `report cap` never appears silently
- no `Page crashed` / `net::ERR_ABORTED` / `Browse API clean empty` regressions
- 11S Pro / 4080 / G6 stay «❌ Не найдено»

Then flip `mode.txt` back to `normal` and commit.

## Earlier

- Pre-fix evidence run 2026-07-26 17:11–17:13 UTC (every pure-Auktion pass:
  curl soft-empty → `Page crashed` ×2 → Browse API 0 → «Не найдено»)
- Post-fix verification kick — fix commit d50720c05 empty stats (DEX/ULT/G6/LG),
  2026-07-17T02:45 — done, see `qa/results/AUDIT_4BUCKETS_LATEST.md`
- 4-bucket audit results for 24 products: `qa/results/`
- Watcher stopped 2026-07-18 06:17 UTC, mode back to `normal`
- `TODO.md` (22 June) deleted: every item was already in the code and its
  «keep mode.txt = statistics» rule contradicted AGENTS.md (`normal` = prod).
