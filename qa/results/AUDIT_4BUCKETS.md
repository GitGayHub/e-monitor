# Full 4-bucket audit (stats vs live)

**STATS_MISS=33 CHEAPER_LIVE=44 total_rows=92**

## Redmagic 11 Pro
query=`Redmagic 11 Pro` min=50

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 1499 | — | LIVE_MISS_OR_FILTER |
| Sofort+ | 700 | — | LIVE_MISS_OR_FILTER |
| Auktion | 692 | 559 | CHEAPER_LIVE |
| Auktion+ | — | — | ok |

_live BIN sc=403 n=0; AUC sc=200 n=1_

## Redmagic 11S Pro
query=`Redmagic 11S Pro` min=50

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 1152 | 156 | CHEAPER_LIVE |
| Sofort+ | 746 | 256 | CHEAPER_LIVE |
| Auktion | — | 606 | STATS_MISS |
| Auktion+ | — | — | ok |

_live BIN sc=200 n=64; AUC sc=200 n=1_

## Nubia Z80 Ultra
query=`Nubia Z80 Ultra` min=50

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 756 | 52 | CHEAPER_LIVE |
| Sofort+ | — | 60 | STATS_MISS |
| Auktion | 511 | 511 | ok |
| Auktion+ | — | 531 | STATS_MISS |

_live BIN sc=200 n=78; AUC sc=200 n=2_

## Nubia Z80 LV
query=`Nubia Z80 Ultra` min=50

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | — | 52 | STATS_MISS |
| Sofort+ | — | 60 | STATS_MISS |
| Auktion | — | 511 | STATS_MISS |
| Auktion+ | — | 531 | STATS_MISS |

_live BIN sc=200 n=78; AUC sc=200 n=2_

## Nubia Z70 Ultra
query=`Nubia Z70 Ultra` min=50

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 459 | 258 | CHEAPER_LIVE |
| Sofort+ | 500 | 306 | CHEAPER_LIVE |
| Auktion | — | 511 | STATS_MISS |
| Auktion+ | 531 | 531 | ok |

_live BIN sc=200 n=63; AUC sc=200 n=2_

## Nubia Z70S Ultra
query=`Nubia Z70S Ultra` min=50

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | — | 266 | STATS_MISS |
| Sofort+ | 753 | 306 | CHEAPER_LIVE |
| Auktion | — | 511 | STATS_MISS |
| Auktion+ | — | 531 | STATS_MISS |

_live BIN sc=200 n=62; AUC sc=200 n=2_

## iPhone 16 Pro Max
query=`iPhone 16 Pro Max` min=50

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 705 | 189 | CHEAPER_LIVE |
| Sofort+ | 735 | 225 | CHEAPER_LIVE |
| Auktion | 407 | 119 | CHEAPER_LIVE |
| Auktion+ | 756 | 238 | CHEAPER_LIVE |

_live BIN sc=200 n=60; AUC sc=200 n=67_

## PlayStation 5 Pro
query=`` min=300

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 810 | — | LIVE_MISS_OR_FILTER |
| Sofort+ | 910 | — | LIVE_MISS_OR_FILTER |
| Auktion | 840 | — | LIVE_MISS_OR_FILTER |
| Auktion+ | 2300 | — | LIVE_MISS_OR_FILTER |

_live BIN sc=200 n=0; AUC sc=200 n=0_

## Pixel 5
query=`Pixel 5` min=50

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 135 | 53 | CHEAPER_LIVE |
| Sofort+ | — | 87 | STATS_MISS |
| Auktion | — | 50 | STATS_MISS |
| Auktion+ | — | 105 | STATS_MISS |

_live BIN sc=200 n=60; AUC sc=200 n=61_

## Sony WH-1000XM6
query=`Sony WH-1000XM6` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 246 | — | LIVE_MISS_OR_FILTER |
| Sofort+ | 280 | — | LIVE_MISS_OR_FILTER |
| Auktion | 157 | 85 | CHEAPER_LIVE |
| Auktion+ | 336 | 102 | CHEAPER_LIVE |

_live BIN sc=200 n=0; AUC sc=200 n=16_

## 5070 ti (pc, rechner, computer, desktop, gaming pc)
query=`5070 ti` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 1785 | 319 | CHEAPER_LIVE |
| Sofort+ | 1523 | 770 | CHEAPER_LIVE |
| Auktion | — | 130 | STATS_MISS |
| Auktion+ | 1831 | 482 | CHEAPER_LIVE |

_live BIN sc=200 n=59; AUC sc=200 n=14_

## 4080 (pc, rechner, computer, desktop, gaming pc)
query=`4080` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 1650 | 129 | CHEAPER_LIVE |
| Sofort+ | 1400 | 146 | CHEAPER_LIVE |
| Auktion | — | 574 | STATS_MISS |
| Auktion+ | — | 866 | STATS_MISS |

_live BIN sc=200 n=55; AUC sc=200 n=9_

## iPhone 15 Pro Max
query=`iPhone 15 Pro Max` min=50

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 576 | 89 | CHEAPER_LIVE |
| Sofort+ | 490 | 118 | CHEAPER_LIVE |
| Auktion | 241 | 66 | CHEAPER_LIVE |
| Auktion+ | 581 | 166 | CHEAPER_LIVE |

_live BIN sc=200 n=60; AUC sc=200 n=71_

## samsung s24 ultra
query=`samsung s24 ultra` min=50

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 448 | 53 | CHEAPER_LIVE |
| Sofort+ | 441 | 440 | ok |
| Auktion | 284 | 121 | CHEAPER_LIVE |
| Auktion+ | 356 | 108 | CHEAPER_LIVE |

_live BIN sc=200 n=60; AUC sc=200 n=62_

## 4050 oled
query=`4050 oled` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 1252 | 101 | CHEAPER_LIVE |
| Sofort+ | 807 | 101 | CHEAPER_LIVE |
| Auktion | — | 457 | STATS_MISS |
| Auktion+ | — | — | ok |

_live BIN sc=200 n=75; AUC sc=200 n=1_

## 4060 oled
query=`4060 oled` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 1469 | 109 | CHEAPER_LIVE |
| Sofort+ | 2591 | 139 | CHEAPER_LIVE |
| Auktion | — | 114 | STATS_MISS |
| Auktion+ | — | 234 | STATS_MISS |

_live BIN sc=200 n=68; AUC sc=200 n=8_

## asus vivobook 14x oled
query=`asus vivobook 14x oled` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | — | 109 | STATS_MISS |
| Sofort+ | — | 110 | STATS_MISS |
| Auktion | — | 100 | STATS_MISS |
| Auktion+ | — | 106 | STATS_MISS |

_live BIN sc=200 n=59; AUC sc=200 n=9_

## PRO X 2 SUPERSTRIKE
query=`PRO X 2 SUPERSTRIKE` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
| Sofort | 145 | 29 | CHEAPER_LIVE |
| Sofort+ | 151 | 66 | CHEAPER_LIVE |
| Auktion | 60 | 36 | CHEAPER_LIVE |
| Auktion+ | — | 40 | STATS_MISS |

_live BIN sc=200 n=65; AUC sc=200 n=8_

## logitech superlight 2
query=`logitech superlight 2` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 70 | 39 | CHEAPER_LIVE |
| Sofort+ | 68 | 38 | CHEAPER_LIVE |
| Auktion | — | 49 | STATS_MISS |
| Auktion+ | 96 | 40 | CHEAPER_LIVE |

_live BIN sc=200 n=47; AUC sc=200 n=5_

## logitech superlight 2 dex
query=`logitech superlight 2` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 82 | 39 | CHEAPER_LIVE |
| Sofort+ | 66 | 38 | CHEAPER_LIVE |
| Auktion | — | 49 | STATS_MISS |
| Auktion+ | 112 | 40 | CHEAPER_LIVE |

_live BIN sc=200 n=47; AUC sc=200 n=5_

## Sony ULT Wear
query=`sony ult wear` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 191 | 80 | CHEAPER_LIVE |
| Sofort+ | 124 | 84 | CHEAPER_LIVE |
| Auktion | — | — | ok |
| Auktion+ | — | 106 | STATS_MISS |

_live BIN sc=200 n=67; AUC sc=200 n=1_

## LG UltraGear OLED
query=`lg ultragear oled 480hz` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 630 | 429 | CHEAPER_LIVE |
| Sofort+ | 483 | 308 | CHEAPER_LIVE |
| Auktion | — | 90 | STATS_MISS |
| Auktion+ | — | 110 | STATS_MISS |

_live BIN sc=200 n=86; AUC sc=200 n=14_

## Samsung Odyssey OLED G6 500Hz
query=`samsung odyssey oled g6 500hz` min=20

| Bucket | Stats € | Live € | Note |
|---|---:|---:|---|
filter err: 'dict' object has no attribute 'get_global_banned_sellers'
| Sofort | 569 | 146 | CHEAPER_LIVE |
| Sofort+ | — | 189 | STATS_MISS |
| Auktion | — | 85 | STATS_MISS |
| Auktion+ | — | 137 | STATS_MISS |

_live BIN sc=200 n=68; AUC sc=200 n=6_

## STATS_MISS detail
- **Redmagic 11S Pro** auktion: live 606€ id=398177800499 q=`Redmagic 11S Pro`
- **Nubia Z80 Ultra** sofort_plus: live 61€ id=227434233131 q=`Nubia Z80 Ultra`
- **Nubia Z80 Ultra** auktion_plus: live 531€ id=206412457716 q=`Nubia Z80 Ultra`
- **Nubia Z80 LV** sofort: live 52€ id=398007364485 q=`Nubia Z80 Ultra`
- **Nubia Z80 LV** sofort_plus: live 61€ id=227434233131 q=`Nubia Z80 Ultra`
- **Nubia Z80 LV** auktion: live 511€ id=178306976467 q=`Nubia Z80 Ultra`
- **Nubia Z80 LV** auktion_plus: live 531€ id=206412457716 q=`Nubia Z80 Ultra`
- **Nubia Z70 Ultra** auktion: live 511€ id=178306976467 q=`Nubia Z70 Ultra`
- **Nubia Z70S Ultra** sofort: live 267€ id=127122080049 q=`Nubia Z70S Ultra`
- **Nubia Z70S Ultra** auktion: live 511€ id=178306976467 q=`Nubia Z70S Ultra`
- **Nubia Z70S Ultra** auktion_plus: live 531€ id=206412457716 q=`Nubia Z70S Ultra`
- **Pixel 5** sofort_plus: live 87€ id=137468548749 q=`Pixel 5`
- **Pixel 5** auktion: live 50€ id=206407796848 q=`Pixel 5`
- **Pixel 5** auktion_plus: live 105€ id=278174643375 q=`Pixel 5`
- **5070 ti (pc, rechner, computer, desktop, gaming pc)** auktion: live 131€ id=206419632634 q=`5070 ti`
- **4080 (pc, rechner, computer, desktop, gaming pc)** auktion: live 575€ id=318594596497 q=`4080`
- **4080 (pc, rechner, computer, desktop, gaming pc)** auktion_plus: live 867€ id=236929573787 q=`4080`
- **4050 oled** auktion: live 458€ id=278184937608 q=`4050 oled`
- **4060 oled** auktion: live 115€ id=188640645720 q=`4060 oled`
- **4060 oled** auktion_plus: live 234€ id=307058891676 q=`4060 oled`
- **asus vivobook 14x oled** sofort: live 110€ id=295677643105 q=`asus vivobook 14x oled`
- **asus vivobook 14x oled** sofort_plus: live 110€ id=147442883897 q=`asus vivobook 14x oled`
- **asus vivobook 14x oled** auktion: live 100€ id=366529790070 q=`asus vivobook 14x oled`
- **asus vivobook 14x oled** auktion_plus: live 106€ id=227434013398 q=`asus vivobook 14x oled`
- **PRO X 2 SUPERSTRIKE** auktion_plus: live 40€ id=800334765477 q=`PRO X 2 SUPERSTRIKE`
- **logitech superlight 2** auktion: live 49€ id=398181977889 q=`logitech superlight 2`
- **logitech superlight 2 dex** auktion: live 49€ id=398181977889 q=`logitech superlight 2`
- **Sony ULT Wear** auktion_plus: live 106€ id=168535497091 q=`sony ult wear`
- **LG UltraGear OLED** auktion: live 90€ id=398177370380 q=`lg ultragear oled 480hz`
- **LG UltraGear OLED** auktion_plus: live 110€ id=298503449251 q=`lg ultragear oled 480hz`
- **Samsung Odyssey OLED G6 500Hz** sofort_plus: live 190€ id=336661987015 q=`samsung odyssey oled g6 500hz`
- **Samsung Odyssey OLED G6 500Hz** auktion: live 85€ id=168535301217 q=`samsung odyssey oled g6 500hz`
- **Samsung Odyssey OLED G6 500Hz** auktion_plus: live 137€ id=236940799672 q=`samsung odyssey oled g6 500hz`

## CHEAPER_LIVE detail
- **Redmagic 11 Pro** auktion: stats 692 → live 559€ (Δ133) id=327257689079
- **Redmagic 11S Pro** sofort: stats 1152 → live 156€ (Δ996) id=206395810934
- **Redmagic 11S Pro** sofort_plus: stats 746 → live 256€ (Δ490) id=147064674763
- **Nubia Z80 Ultra** sofort: stats 756 → live 52€ (Δ704) id=398007364485
- **Nubia Z70 Ultra** sofort: stats 459 → live 258€ (Δ201) id=197526753432
- **Nubia Z70 Ultra** sofort_plus: stats 500 → live 306€ (Δ194) id=397965825478
- **Nubia Z70S Ultra** sofort_plus: stats 753 → live 306€ (Δ447) id=397965825478
- **iPhone 16 Pro Max** sofort: stats 705 → live 190€ (Δ515) id=298431690967
- **iPhone 16 Pro Max** sofort_plus: stats 735 → live 225€ (Δ510) id=127978922907
- **iPhone 16 Pro Max** auktion: stats 407 → live 119€ (Δ288) id=227432418342
- **iPhone 16 Pro Max** auktion_plus: stats 756 → live 238€ (Δ518) id=188656856718
- **Pixel 5** sofort: stats 135 → live 53€ (Δ82) id=177993401761
- **Sony WH-1000XM6** auktion: stats 157 → live 86€ (Δ71) id=327256928204
- **Sony WH-1000XM6** auktion_plus: stats 336 → live 103€ (Δ233) id=327261842509
- **5070 ti (pc, rechner, computer, desktop, gaming pc)** sofort: stats 1785 → live 319€ (Δ1466) id=198503579010
- **5070 ti (pc, rechner, computer, desktop, gaming pc)** sofort_plus: stats 1523 → live 770€ (Δ753) id=366495225807
- **5070 ti (pc, rechner, computer, desktop, gaming pc)** auktion_plus: stats 1831 → live 483€ (Δ1348) id=117307558858
- **4080 (pc, rechner, computer, desktop, gaming pc)** sofort: stats 1650 → live 130€ (Δ1520) id=206409753422
- **4080 (pc, rechner, computer, desktop, gaming pc)** sofort_plus: stats 1400 → live 147€ (Δ1253) id=127922574558
- **iPhone 15 Pro Max** sofort: stats 576 → live 89€ (Δ487) id=116533674685
- **iPhone 15 Pro Max** sofort_plus: stats 490 → live 118€ (Δ372) id=407059277605
- **iPhone 15 Pro Max** auktion: stats 241 → live 66€ (Δ175) id=377336424316
- **iPhone 15 Pro Max** auktion_plus: stats 581 → live 166€ (Δ415) id=298512686593
- **samsung s24 ultra** sofort: stats 448 → live 53€ (Δ395) id=177993401761
- **samsung s24 ultra** auktion: stats 284 → live 121€ (Δ163) id=267727304113
- **samsung s24 ultra** auktion_plus: stats 356 → live 109€ (Δ247) id=278184146684
- **4050 oled** sofort: stats 1252 → live 101€ (Δ1151) id=273580670726
- **4050 oled** sofort_plus: stats 807 → live 102€ (Δ705) id=206086267132
- **4060 oled** sofort: stats 1469 → live 110€ (Δ1359) id=388795199348
- **4060 oled** sofort_plus: stats 2591 → live 139€ (Δ2452) id=157999034998
- **PRO X 2 SUPERSTRIKE** sofort: stats 145 → live 30€ (Δ115) id=365747799549
- **PRO X 2 SUPERSTRIKE** sofort_plus: stats 151 → live 66€ (Δ85) id=358787597789
- **PRO X 2 SUPERSTRIKE** auktion: stats 60 → live 36€ (Δ24) id=168531033011
- **logitech superlight 2** sofort: stats 70 → live 40€ (Δ30) id=389879817294
- **logitech superlight 2** sofort_plus: stats 68 → live 38€ (Δ30) id=398072849700
- **logitech superlight 2** auktion_plus: stats 96 → live 40€ (Δ56) id=800334765477
- **logitech superlight 2 dex** sofort: stats 82 → live 40€ (Δ42) id=389879817294
- **logitech superlight 2 dex** sofort_plus: stats 66 → live 38€ (Δ28) id=398072849700
- **logitech superlight 2 dex** auktion_plus: stats 112 → live 40€ (Δ72) id=800334765477
- **Sony ULT Wear** sofort: stats 191 → live 80€ (Δ111) id=318238828051
- **Sony ULT Wear** sofort_plus: stats 124 → live 85€ (Δ39) id=307029264069
- **LG UltraGear OLED** sofort: stats 630 → live 429€ (Δ201) id=267620729002
- **LG UltraGear OLED** sofort_plus: stats 483 → live 309€ (Δ174) id=336687755172
- **Samsung Odyssey OLED G6 500Hz** sofort: stats 569 → live 146€ (Δ423) id=135150133347
