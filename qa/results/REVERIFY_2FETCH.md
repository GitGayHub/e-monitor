# Re-verify after 2-fetch fix (GH run 29548046781, sha 16fcb84)

## Headline

| Metric | Value |
|--------|-------|
| Products | 23 |
| Price buckets filled | **52 / 92** |
| Rate-limit empties | 39 (many false labels — fixed in 2e765b45) |
| True empty (Не найдено) | 1 |

## Previously broken sections

| Product | Sofort | Sofort+ | Auktion | Auktion+ | Verdict |
|---------|--------|---------|---------|----------|---------|
| **DEX** | **82€** | **66€** | RL | RL | ✅ BIN fixed |
| **ULT Wear** | **192€** | **133€** | RL | RL | ✅ BIN fixed |
| **LG UltraGear** | **566€** | **522€** | RL | RL | ✅ BIN fixed |
| **G6 500Hz** | **569€** | **524€** | RL | RL | ✅ BIN fixed |

## Fully OK (4/4 prices)

- PlayStation 5 Pro
- Sony XM6
- 5070 Ti PC
- iPhone 15 Pro Max
- S24 Ultra

## Still weak

- **Z80 LV**: 0/4 RL (likely real empty model + transport)
- Mid-list auctions often RL (second fetch hotter; auction retry added in 2e765b45)
- False RL on empty Sofort+ when BIN OK (e.g. Z80 Ultra Sofort+ labeled RL) — fixed per-side labels

## Follow-up push

`2e765b45` — per-side empty labels, force bypasses cache, auction retry, API only on HTML transport fail.
