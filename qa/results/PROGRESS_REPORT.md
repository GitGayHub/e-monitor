# Progress (ongoing)

## Local stats after filter fixes (HTML, ~03:09, 23 products)

| Product | Sofort | Sofort+ | Auktion | Auktion+ |
|---------|--------|---------|---------|----------|
| Redmagic 11 Pro | --- | **1042** | **692** | --- |
| Redmagic 11S | **1151** | **722** | --- | --- |
| Z80 Ultra | **1538** | --- | --- | --- |
| Z80 Leading | --- | --- | --- | --- |
| Z70 Ultra | **732** | --- | --- | --- |
| Z70S | --- | **763** | --- | --- |
| iPhone 16 PM | **910** | **740** | **701** | --- |
| PS5 Pro | **633** | **725** | **1243** | --- |
| Pixel 5 | --- | --- | --- | --- |
| XM6 | **271** | **318** | **148** | --- |
| 5070 Ti PC | **2891** | **2419** | **1361** | --- |
| 4080 PC | **1729** | **1995** | --- | --- |
| iPhone 15 PM | **613** | **614** | **764** | --- |
| S24 Ultra | **671** | **613** | **342** | **695** |
| 4050 OLED | **1482** | **1525** | --- | --- |
| 4060 OLED | **1509** | **1975** | **1215** | --- |
| VivoBook 14x | --- | --- | --- | --- |
| Superstrike | --- | **385** | --- | --- |
| Superlight 2 | **95** | **73** | --- | --- |
| **Superlight 2 DEX** | **130** | **230** | --- | --- |
| **Sony ULT Wear** | **132** | **120** | --- | --- |
| LG UltraGear 480 | --- | --- | --- | --- |
| Odyssey G6 500 | --- | --- | --- | --- |

### Was empty before → fixed locally
- **DEX** 130/230 ✅
- **ULT** 132/120 ✅

### Still empty locally (end-of-run / stock / model)
- Odyssey G6, LG 480 (earlier mid-run HTML found ~774/729 — likely tail soft-block or strict match on that pass)
- Z80 Leading (likely real empty model)
- Pixel 5, VivoBook

## GH run (with Playwright, sha 3a66b0d)
- First products **got real prices** (RM11 1505/706/692, RM11S …)
- Then long **cooldown 300s** wiped rest → ⚠️ Rate limit
- **Fix pushed:** short CI cooldown + Playwright even during cooldown (`a5053d9`)

## Waiting
Next GH Actions on `a5053d9` / tip for full product prices without 5-min skip.
