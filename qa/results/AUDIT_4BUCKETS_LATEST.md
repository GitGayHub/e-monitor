# 4-bucket stats run 29631195085 (56798e soft-fallback)

UTC: 2026-07-18 05:13

metrics: prices~119 empty=30 fail=0 block=0 rl=0

| Product | Sofort | Sofort+ | Auktion | Auktion+ |
|---------|-------:|--------:|--------:|---------:|
| Redmagic 11 Pro | 1499 | 700 | 692 | — |
| Redmagic 11S Pro | 1152 | 746 | — | — |
| Nubia Z80 Ultra | 756 | — | 511 | — |
| Nubia Z80 LV | — | — | — | — |
| Nubia Z70 Ultra | 459 | 500 | — | 531 |
| Nubia Z70S Ultra | — | 753 | — | — |
| iPhone 16 Pro Max | 705 | 735 | 407 | 756 |
| PS5 Pro | 810 | 910 | 840 | 2300 |
| Pixel 5 | 135 | 210 | 143 | — |
| Sony XM6 | 246 | 280 | 157 | 336 |
| 5070 ti PC | 1785 | 1523 | — | 1831 |
| 4080 PC | 1650 | 1599 | — | — |
| iPhone 15 Pro Max | 576 | 496 | 241 | 581 |
| S24 Ultra | 448 | 441 | 284 | 356 |
| 4050 oled | 1389 | 1112 | — | 818 |
| 4060 oled | 1310 | 1136 | 910 | — |
| VivoBook 14x | 779 | — | — | — |
| Superstrike | 145 | 151 | 60 | — |
| Superlight 2 | 96 | 68 | — | 96 |
| Superlight 2 DEX | 82 | 66 | — | 112 |
| Sony ULT Wear | 191 | 124 | — | 106 |
| LG UltraGear | 1122 | 535 | — | — |
| Odyssey G6 | 569 | 524 | — | — |

Notes:
- Only Z80 LV fully empty (Leading model — market/empty)
- Recovered: Superstrike Auktion 60, ULT Auktion+ 106, Pixel auction, soft-fallback fills
- Remaining auction empties often real thin auction market after filters OR GH soft-empty on auction SERP
- mode still statistics for inspection


## Run 29632945412 c47ad05 (auction HTML-first + PW retry)

### Live Playwright (user browser MCP)
- **Z80 Ultra**: stock OK — stats Sofort 756 / Auktion 511 (itm 178306976467) matches live hybrid
- **Z80 LV (Leading)**: eBay shows **0 Ergebnisse** for BIN and Auction; only related Z80/Z70/Z60/cases — **empty is correct**

### Residual Auktion empty (11S, LG, G6, 4080, Superlight pure)
- Logs: mixed often bin=True auc=False; auction fill gets soft-empty/PW crash then Browse API **0 items**
- DEX auction fill found 1 item via API path; Superstrike Auktion 60 kept; ULT Auktion+ 106 kept
- Not false eBay block; either thin auction market after filters or GH cannot parse auction SERP

### Metrics
prices~118 empty=31 fail=0 block=0 rl=0
mode -> normal after verify
