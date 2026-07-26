# QA status / handoff

## Active task — auction buckets must tell the truth (iteration 2)

- mode: **`statistics`** on purpose — the 4-bucket report is the measuring tool
  for this loop. Back to `normal` (AGENTS.md production default) once the
  auction rows stop lying. While `statistics` is set, the 5-min cron **skips**
  the run, so no alerts are being delivered.
- Loop: change logic → push to `main` → dispatch/push run → read the report →
  compare against live eBay → next change.

### Iteration 1 result — GH run 30218257391 (2026-07-26 20:07–20:35 UTC)

First fix (Chromium crash recovery, commit 5a137324c) measured against the
pre-fix baseline run 30217151118 (19:34–19:58 UTC, same runner):

| marker | before | after |
| --- | ---: | ---: |
| `Page crashed` | 93 | **3** |
| `Playwright HTML fetch failed` | 93 | 92 |
| `-> N items via Playwright HTML` | 0 | **0** |
| `Browse API clean empty` (incl. auction) | 24 | **2** (BIN only) |
| `auction API 0 items … keeping network` | 0 | **24** |

So the crash is gone, and no auction bucket is painted «Не найдено» by a
Browse-API zero any more — but Chromium still never delivered a page. The
failure just changed shape: **`Page.goto: net::ERR_ABORTED`**, 92 times, and
the escalation ignored it (it only retried on crash/timeout), so each auction
SERP got exactly one ~2 s attempt.

### The 5 residual products — report vs live eBay

Ground truth taken the same evening from this PC (real Chromium, real eBay,
`_ipg=60`, same URL builder as the monitor):

| product | report (GH) | live eBay | verdict |
| --- | --- | --- | --- |
| Redmagic 11S Pro | ❌ Не найдено | «0 Ergebnisse / Keine exakten Treffer» | **correct** |
| logitech superlight 2 | Auktion ❌, **Auktion+ 70 €** | 3 lots (69.95 / 30.50 / 90 €) | **recovered** (was «Не найдено» everywhere) |
| lg ultragear oled 480hz | ❌ Не найдено | 1 lot 450 €, passes `filter_results` | **false empty** → fix 3 |
| 4080 (pc, …) | ⚠️ сбой загрузки | «0 Ergebnisse / Keine exakten Treffer» | **false failure** → fix 2 |
| samsung odyssey oled g6 500hz | ⚠️ сбой загрузки | «0 Ergebnisse / Keine exakten Treffer» | **false failure** → fix 2 |

Locally none of the 5 crashed Chromium and all 5 resolved cleanly
(2 with lots, 3 honest empties) — the crash fix itself holds.

### Iteration 2 — what changed (this commit)

1. **Empty marker was unreachable.** `_parse_search_body` only scanned
   `body[:12000]`, and eBay.de renders the null-search headline
   («Keine exakten Treffer gefunden») ~150–200k into a ~400–900k document:

   | page | body_len | marker offset |
   | --- | ---: | ---: |
   | 4080 (pc, …) | 395 177 | 183 989 |
   | odyssey g6 | 451 990 | 196 973 |
   | superlight 2 (has lots) | 905 041 | — (`we couldn'…` @ 732 829) |

   Now the whole body is scanned, but **only** when the page is a SERP with
   zero `/itm/` links — a page that still has listings keeps the head-only
   rule, so a parser failure can never be dressed up as an empty market.
   Generic `we couldn'…` is deliberately not a deep marker (it sits in the
   footer of pages that do have stock). `test_serp_empty_marker.py` — 8 tests.

2. **`net::ERR_ABORTED`.** The `"**/*"` route intercepted the navigation
   itself; continue_()-ing the document through eBay's redirect chain is what
   replaced the crashes with aborts. Blocking is now attached to asset globs
   only (never the document), the escalation retries on `net::` errors
   (`_pw_should_escalate`, unit-tested), and the last attempt drops to plain
   Chromium — no routing, no `--renderer-process-limit` — on a 25-card page.
   Each attempt names its configuration in the log, so the next run says which
   one actually fetched the page.

3. **Auction bucket ≠ auction market.** The dedicated auction fetch only ran
   when the mixed page had *no* auction item at all. LG UltraGear had one
   (`auc=True`), so no auction fetch ran, both auction buckets came out empty
   after filtering and the row printed «Не найдено» — while a 450 € lot sat on
   the auction-only SERP. Now an empty pair of auction buckets triggers one
   dedicated auction fetch + re-filter, capped at `_MAX_AUCTION_REFILLS = 10`
   per report (cap hits are logged, never silent).

### Verified here (local, this PC)

- `python -m py_compile monitor.py config_manager.py`
- `python monitor_runtime_patch.py`
- `python test_auction_serp_recovery.py` — 16/16
- `python test_serp_empty_marker.py` — 8/8
- Live Chromium against all 5 auction SERPs, before and after the parser fix
- Pre-existing failures, reproduce on a clean tree, unrelated:
  `test_search_intent_rules.py` 28/29 (`_ipg` 120 vs ≥240),
  `test_details_filter.py` 12/13 (`test_hybrid_listing_prices_and_grouping`)

### Next step

Dispatch **E Monitor** on `main` and read the run log for:

- `empty-marker … past the 12k head` → 4080 / G6 must flip to «❌ Не найдено»
- `Playwright retry 2/3 … (commit)` / `3/3 (light SERP, plain chromium)` and
  then `-> N items via Playwright HTML` (currently 0 on GH)
- `auction buckets empty after filter — dedicated auction fetch` → LG must show
  its 450 € lot
- still no `Browse API clean empty` on auction-only searches

## Earlier

- Pre-fix evidence run 2026-07-26 17:11–17:13 UTC (every pure-Auktion pass:
  curl soft-empty → `Page crashed` ×2 → Browse API 0 → «Не найдено»)
- Post-fix verification kick — fix commit d50720c05 empty stats (DEX/ULT/G6/LG),
  2026-07-17T02:45 — done, see `qa/results/AUDIT_4BUCKETS_LATEST.md`
- 4-bucket audit results for 24 products: `qa/results/`
- Watcher stopped 2026-07-18 06:17 UTC, mode back to `normal`
- 2026-07-23 `Auto-commit before Windows reinstall` — no code work since then
  until this branch
- `TODO.md` (22 June) deleted: every item was already in the code and its
  «keep mode.txt = statistics» rule contradicted AGENTS.md (`normal` = prod).
