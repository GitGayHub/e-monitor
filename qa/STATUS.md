# QA status / handoff

## Active task — verify auction SERP recovery on GH

- Last code fix: **auction SERP recovery** (branch `claude/continue-after-reboot-26uavs`)
- Picks up the residual left open on 2026-07-18 06:17 UTC by the stopped night
  watcher: *"auction SERP recovery (11S / LG / G6 / 4080 / Superlight pure Auktion)"*
- mode: `normal`

### What was broken (evidence: run 2026-07-26 17:11–17:13 UTC)

Every pure-Auktion pass on GH died the same way, for every product:

```
eBay ebay.de soft-empty chrome (container, itm=0, no empty-marker) — retry PW
Playwright HTML fetch failed (try 1/2): Page.goto: Page crashed
Playwright HTML fetch failed (try 2/2): Page.goto: Page crashed
eBay HTML exhausted (network), trying Browse API last resort
  -> 0 items via eBay Browse API
  -> Browse API clean empty (0 items) after HTML network   <-- printed «Не найдено»
```

So the auction bucket claimed empty stock while the fetch had actually died.

### Fix

1. `_do_fetch_playwright` — renderer no longer OOM-crashes on the SERP:
   images/media/fonts aborted via route, ad iframes kept out of their own
   renderers (`--disable-features=IsolateOrigins,site-per-process`,
   `--renderer-process-limit=2`), and the retries *escalate*
   (full load → commit-only wait → commit-only on a 25-card page) instead of
   repeating the attempt that just crashed.
2. Auction-only search + Browse API 0 items after a dead HTML chain is no
   longer a clean empty — `buyingOptions:{AUCTION}` cannot prove an empty
   auction market. The bucket now reads **⚠️ сбой загрузки**, not
   **❌ Не найдено**. BIN keeps the old clean-empty behaviour.
   Guarded so one thin auction bucket never arms the local cooldown.

### Verified here

- `python -m py_compile monitor.py config_manager.py test_html_details_live.py`
- `python monitor_runtime_patch.py`
- `python test_auction_serp_recovery.py` — 10/10
- `python test_search_intent_rules.py` — 28/29 (`_ipg` 120 vs ≥240 fails on a
  clean tree too — pre-existing, unrelated)
- Chromium launch flags + resource blocking + commit-only wait exercised
  against a local page (images aborted, document/script/css pass)

### Next step (needs main)

The workflow checks out `ref: main`, so this cannot run in CI from a branch.
After merge, dispatch **E Monitor** and check the run log for:

- `Page crashed` gone from the auction passes (or, at worst, followed by
  `Playwright retry 2/3` / `3/3 (commit, light SERP)` that succeeds)
- `-> N items via Playwright HTML` on pure-Auktion queries
- no `Browse API clean empty` on auction-only searches

Then re-check the 5 residual products (11S Pro, LG UltraGear, Odyssey G6,
4080 PC, Superlight 2 pure Auktion): a price = recovered, `⚠️ сбой загрузки`
= still unreachable, `❌ Не найдено` = genuinely thin auction market.

## Earlier

- Post-fix verification kick — fix commit d50720c05 empty stats (DEX/ULT/G6/LG),
  2026-07-17T02:45 — done, see `qa/results/AUDIT_4BUCKETS_LATEST.md`
- 4-bucket audit results for 24 products: `qa/results/`
- Watcher stopped 2026-07-18 06:17 UTC, mode back to `normal`
- 2026-07-23 `Auto-commit before Windows reinstall` — no code work since then
  until this branch
