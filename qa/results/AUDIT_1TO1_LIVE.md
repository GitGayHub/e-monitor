# Audit 1:1 live HTML — 2026-07-17T00:06:04.791639+00:00

Source: `qa/inbox/local_stats_html.log` (stats run) vs live `fetch_ebay_ex` + `filter_results(is_statistics=True)`.

| # | Product | Script S/S+/A/A+ | Live filt BIN min | Verdict | Notes |
|---|---------|------------------|-------------------|---------|-------|
| 1 | Redmagic 11 Pro | 1505.0/706.0/692.0/--- | --- | **stale_or_strict** | script Sofort=1505.0 but live filter empty (market moved or strict); sofort item 800278835200 not in current search page |
| 2 | Redmagic 11S Pro | 1151.0/722.0/---/--- | --- | **stale_or_strict** | script Sofort=1151.0 but live filter empty (market moved or strict); sofort item 137414773091 not in current search page |
| 3 | Nubia Z80 Ultra | 756.0/---/407.0/--- | --- | **stale_or_strict** | script Sofort=756.0 but live filter empty (market moved or strict); sofort item 178306976467 not in current search page  |
| 4 | Nubia Z80 Ultra Leading | ---/---/---/--- | --- | **fetch_empty** | HTML fetch empty/block err=None n=0 |
| 5 | Nubia Z70 Ultra | 459.0/500.0/---/531.0 | --- | **stale_or_strict** | script Sofort=459.0 but live filter empty (market moved or strict); sofort item 168388431431 not in current search page  |
| 6 | Nubia Z70S Ultra | ---/755.0/---/--- | --- | **ok** | sofort_plus item 147281691309 not in current search page (may sold/ended) |
| 7 | iPhone 16 Pro Max | 650.0/680.0/271.0/606.0 | --- | **stale_or_strict** | script Sofort=650.0 but live filter empty (market moved or strict); sofort item 318587124712 not in current search page  |
| 8 | (playstation 5 pro, ps5 pro) | 879.0/910.0/650.0/2300.0 | --- | **stale_or_strict** | script Sofort=879.0 but live filter empty (market moved or strict); sofort item 800353117652 not in current search page  |
| 9 | Pixel 5 | 135.0/---/---/--- | --- | **stale_or_strict** | script Sofort=135.0 but live filter empty (market moved or strict); sofort item 178260069267 not in current search page  |
| 10 | Sony WH-1000XM6 | 246.0/280.0/157.0/356.0 | --- | **stale_or_strict** | script Sofort=246.0 but live filter empty (market moved or strict); sofort item 147429611462 not in current search page  |
| 11 | 5070 ti (pc, rechner, computer, desktop, | 1698.0/1523.0/929.0/1831.0 | --- | **stale_or_strict** | script Sofort=1698.0 but live filter empty (market moved or strict); sofort item 235389456368 not in current search page |
| 12 | 4080 (pc, rechner, computer, desktop, ga | 1650.0/1299.0/---/--- | --- | **stale_or_strict** | script Sofort=1650.0 but live filter empty (market moved or strict); sofort item 358532817350 not in current search page |
| 13 | iPhone 15 Pro Max | 576.0/496.0/203.0/581.0 | --- | **stale_or_strict** | script Sofort=576.0 but live filter empty (market moved or strict); sofort item 168254452627 not in current search page  |
| 14 | samsung s24 ultra | 448.0/441.0/187.0/356.0 | --- | **stale_or_strict** | script Sofort=448.0 but live filter empty (market moved or strict); sofort item 177788919216 not in current search page  |
| 15 | 4050 oled | 1469.0/807.0/---/--- | --- | **stale_or_strict** | script Sofort=1469.0 but live filter empty (market moved or strict); sofort item 267714992639 not in current search page |
| 16 | 4060 oled | 1344.0/1304.0/---/--- | --- | **stale_or_strict** | script Sofort=1344.0 but live filter empty (market moved or strict); sofort item 198496599774 not in current search page |
| 17 | asus vivobook 14x oled | 779.0/---/---/--- | --- | **stale_or_strict** | script Sofort=779.0 but live filter empty (market moved or strict); sofort item 377126864169 not in current search page  |
| 18 | logitech superstrike | 145.0/156.0/---/--- | --- | **stale_or_strict** | script Sofort=145.0 but live filter empty (market moved or strict); sofort item 147430856720 not in current search page  |
| 19 | logitech superlight 2 | 70.0/66.0/---/96.0 | --- | **stale_or_strict** | script Sofort=70.0 but live filter empty (market moved or strict); sofort item 366134867215 not in current search page ( |
| 20 | logitech superlight 2 dex | ---/---/---/--- | --- | **fetch_empty** | HTML fetch empty/block err=None n=0 |
| 21 | logitech superlight 2 | ---/---/---/--- | --- | **fetch_empty** | HTML fetch empty/block err=None n=0 |
| 22 | Sony ULT (Wear, 900N, WH-ULT900N) | ---/---/---/--- | --- | **fetch_empty** | HTML fetch empty/block err=None n=0 |
| 23 | lg ultragear oled 480hz (32GS95, 27GX790 | ---/---/---/--- | --- | **fetch_empty** | HTML fetch empty/block err=None n=0 |
| 24 | samsung odyssey oled g6 500hz (G60SF, LS | ---/---/---/--- | --- | **fetch_empty** | HTML fetch empty/block err=None n=0 |

## Summary counts

- `stale_or_strict`: **17**
- `fetch_empty`: **6**
- `ok`: **1**

JSON: `C:/VibeCoding/e-monitor/qa/results/audit_1to1_live.json`
