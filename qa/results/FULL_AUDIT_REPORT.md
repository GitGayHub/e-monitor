# FULL QA REPORT — all stats products

**Source stats:** GitHub Actions logs (same text as Telegram)  
**Manual check:** Playwright → ebay.de (not only Redmagic 11)

## The bug (simple)

Script said **Не найдено** for many products while eBay has real listings.

**Why:**
1. Sort cheapest-first → page full of Hüllen/Folien  
2. API **429** rate limit during long stats run  
3. Stopped after ~30 junk candidates → never saw real phones at 500–800€  

**Result:** Telegram empty, you open eBay → stuff is there → **gap_missed / bug**.

## Code fix (already on GitHub)

| Commit | What |
|--------|------|
| `e491da23c` | phones `_udlo≥120`, more candidates, API 429 retry, accessory blocks |
| `1aab7f430` | bump `logic_version` |

Next stats run should show **🟣 Дорого** for real over-limit devices, not `---`.

---

## Script baseline (all 23 from GH stats)

| # | Product | Sofort | Sofort+ | Auktion | Auktion+ |
|---|---------|--------|---------|---------|----------|
| 0 | Redmagic 11 Pro | --- | --- | --- | --- |
| 1 | Redmagic 11S Pro | --- | --- | --- | --- |
| 2 | Nubia Z80 Ultra | --- | --- | --- | --- |
| 3 | Nubia Z80 LV | --- | --- | --- | --- |
| 4 | Nubia Z70 Ultra | --- | --- | --- | --- |
| 5 | Nubia Z70S Ultra | --- | --- | --- | --- |
| 6 | iPhone 16 Pro Max | --- | --- | --- | --- |
| 7 | PlayStation 5 Pro | --- | --- | --- | --- |
| 8 | Pixel 5 | --- | --- | --- | --- |
| 9 | Sony WH-1000XM6 | --- | --- | --- | --- |
| 10 | 5070 ti PC | --- | --- | --- | --- |
| 11 | 4080 PC | --- | --- | --- | --- |
| 12 | iPhone 15 Pro Max | --- | --- | --- | --- |
| 13 | samsung s24 ultra | --- | --- | --- | --- |
| 14 | 4050 oled | --- | --- | --- | --- |
| 15 | 4060 oled | --- | --- | --- | --- |
| 16 | vivobook 14x oled | --- | --- | --- | --- |
| 17 | SUPERSTRIKE | --- | --- | --- | --- |
| 18 | superlight 2 | --- | --- | --- | --- |
| 19 | superlight 2 dex | --- | --- | --- | --- |
| 20 | Sony ULT Wear | --- | --- | --- | --- |
| 21 | LG UltraGear OLED | --- | --- | --- | --- |
| 22 | Odyssey OLED G6 500Hz | --- | --- | --- | --- |

**All 23 buckets empty in that stats run** — not “no stock”, run was broken (noise + 429).

---

## Manual eBay (Playwright) — where real stock exists

### P0 — must fix (script --- but eBay has device)

| Product | Bucket | Limit | Manual find | Link | Verdict |
|---------|--------|-------|-------------|------|---------|
| **Redmagic 11 Pro** | Sofort | 400€ | **700€** real 11 Pro 16/512 | [itm/398181403334](https://www.ebay.de/itm/398181403334) | **gap_missed** → should 🟣 |
| **Redmagic 11 Pro** | Auktion | 400€ | **519€** Red Magic 11 Pro | [itm/327257689079](https://www.ebay.de/itm/327257689079) | **gap_missed** → should 🟣 |
| **iPhone 16 Pro Max** | Auktion | 675€ | **271€** 16 Pro Max 256 | [itm/318587124712](https://www.ebay.de/itm/318587124712) | **gap_missed P0** under limit |
| **iPhone 15 Pro Max** | Auktion | ~550€ | **200€** 15 Pro Max 256 | [itm/158085996668](https://www.ebay.de/itm/158085996668) | **gap_missed** (if not defekt) |
| **S24 Ultra** | Auktion | 350€ | **181€** S24 Ultra 256 | [itm/287466310856](https://www.ebay.de/itm/287466310856) | **gap_missed** if valid |
| **Sony WH-1000XM6** | Sofort | 200€ | **240€** XM6 | [itm/147429611462](https://www.ebay.de/itm/147429611462) | **gap_missed** → should 🟣 |
| **Superstrike** | Sofort | ~ | **150€** G Pro X2 Superstrike | [itm/307067684579](https://www.ebay.de/itm/307067684579) | check limit; show if valid |
| **4080 PC** | Sofort | high | **1299€** PC RTX 4080 | [itm/267728726850](https://www.ebay.de/itm/267728726850) | **gap_missed** if script --- |
| **PS5 Pro** | Sofort | 750€ | sealed Pro listings exist | eBay | filter noise; show real consols |

### Noise (NOT gaps — script right to skip)

- Redmagic “1€ FedEx” China listings  
- Magic Keyboard for “11 Pro” iPad  
- Displays/Hüllen/Folien for Z80/Z70  
- Superlight **Gehäuse Ersatzteile 4.99€**  
- Odyssey G5/G60F ≠ G6 500Hz G60SF  

### Aligned when fixed

After udlo+retry, next stats should list **real cheapest valid** (green or purple), not all `---`.

---

## Summary for you

| | |
|--|--|
| Products in stats | **23** |
| Script showed any prices | **0 / 23** (whole run empty) |
| That’s a bug? | **YES** |
| Fixed in code? | **YES** (pushed) |
| Your next stats Telegram | should stop saying empty for everything |

If **after** new version still all `---`, send one screenshot + version line — then dig 429/block further.
