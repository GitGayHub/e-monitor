# Полный честный аудит: bot stats vs live eBay

Источник stats: последний GH mixed-fetch report (`stats_paste.txt`).
Метод: локальный Chromium — проверка item-ссылок бота + live BIN/Auction search на пустые/block/RL.

## Сводка (честные вердикты)

| Вердикт | Смысл | N |
|---------|-------|--:|
| `OK_PRICE_LIVE` | бот дал цену, ссылка живая | 27 |
| `BOT_LINK_ERROR_PAGE` | ссылка бота сейчас Error Page | 22 |
| `BOT_LIED_LABEL` | бот сказал block/RL, live search нашёл лоты | 22 |
| `BOT_EMPTY_STOCK_EXISTS` | бот «Не найдено», live search нашёл лоты | 11 |
| `PRICE_DRIFT` | ссылка живая, цена уехала | 5 |
| `LIVE_ALSO_BLOCKED` | и локальный браузер упёрся — проверить нельзя | 4 |
| `CHECK_ERROR` | ошибка проверки | 1 |

## По каждому продукту

### Redmagic 11 Pro
query: `redmagic 11 pro`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 1505€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/800278835200 — item Error Page |
| Sofort+ | 706€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/398181403334 — live EUR 700,00oder Preisvorschlag / Redmagic 11 Pro 16gb Ram 512gb Storage |
| Auktion | 693€ / 🟣 Дорого | **PRICE_DRIFT** | https://www.ebay.de/itm/327257689079 — live AU $850,00 / Nubia Red Magic 11 Pro (Dual SIM 12GB RAM 256GB 5G) Frost Used  |
| Auktion+ | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/327257689079 — EUR 519,36 https://www.ebay.de/itm/327257689079 / Nubia Red Magic 11 Pro (Dual SI |

### Redmagic 11S Pro
query: `redmagic 11s pro`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 1151€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/137414773091 — item Error Page |
| Sofort+ | 746€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/336690246736 — live EUR 700,00oder Preisvorschlag / REDMAGIC 11S Pro 16GB / 512GB Nightfreeze 5G |
| Auktion | --- / ⚠️ Rate limit | **BOT_LIED_LABEL** | https://www.ebay.de/itm/800346805893 — ? https://www.ebay.de/itm/800346805893 / (html-id) |
| Auktion+ | --- / ⚠️ Rate limit | **BOT_LIED_LABEL** | https://www.ebay.de/itm/800346805893 — ? https://www.ebay.de/itm/800346805893 / (html-id) |

### Nubia Z80 Ultra
query: `nubia z80 ultra`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 407€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/178306976467 — item Error Page |
| Sofort+ | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/188297638724 — EUR 67,82 https://www.ebay.de/itm/188297638724 / ZTE nubia Z80 Ultra NX741J Plast |
| Auktion | 407€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/178306976467 — live EUR 401,00 / Nubia Z80 Ultra Starry Night Version + Retro Kit |
| Auktion+ | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/178306976467 — EUR 401,00 https://www.ebay.de/itm/178306976467 / Nubia Z80 Ultra Starry Night Ve |

### Nubia Z80 LV
query: `nubia z80 leading`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | --- / ⚠️ eBay block | **LIVE_ALSO_BLOCKED** | local also failed: error_page |
| Sofort+ | --- / ⚠️ eBay block | **LIVE_ALSO_BLOCKED** | local also failed: error_page |
| Auktion | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/178306976467 — ? https://www.ebay.de/itm/178306976467 / (html-id) |
| Auktion+ | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/178306976467 — ? https://www.ebay.de/itm/178306976467 / (html-id) |

### Nubia Z70 Ultra
query: `nubia z70 ultra`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 459€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/168388431431 — item Error Page |
| Sofort+ | 500€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/366530815294 — live EUR 500,00oder Preisvorschlag / Nubia Z70 Ultra MODELNX733J 512GB 16GB RAM 5 |
| Auktion | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/206412457716 — EUR 525,00 https://www.ebay.de/itm/206412457716 / Nubia Z70 Ultra 24Gb Ram 1Tb Sp |
| Auktion+ | 531€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/206412457716 — live EUR 525,00oder Preisvorschlag / Nubia Z70 Ultra 24Gb Ram 1Tb Speicher Gebrau |

### Nubia Z70S Ultra
query: `nubia z70s ultra`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/365756525063 — ? https://www.ebay.de/itm/365756525063 / (html-id) |
| Sofort+ | 731€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/147281691309 — item Error Page |
| Auktion | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/206412457716 — ? https://www.ebay.de/itm/206412457716 / (html-id) |
| Auktion+ | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/206412457716 — ? https://www.ebay.de/itm/206412457716 / (html-id) |

### iPhone 16 Pro Max
query: `iphone 16 pro max`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 271€ / 🟢 Подходит | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/318587124712 — item Error Page |
| Sofort+ | 735€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/366492982859 — live EUR 729,47oder Preisvorschlag / Apple iPhone 16 Pro Max 256 GB Schwarz IOS |
| Auktion | 271€ / 🟡 Ждёт 24ч | **OK_PRICE_LIVE** | https://www.ebay.de/itm/318587124712 — live EUR 271,11 / Apple iPhone 16 Pro Max 256 GB Silber iOS Smartphone gebraucht |
| Auktion+ | 606€ / 🟢 Подходит | **OK_PRICE_LIVE** | https://www.ebay.de/itm/178313548169 — live EUR 600,00oder Preisvorschlag / iPhone 16 Pro Max 256GB |

### PlayStation 5 Pro
query: `ps5 pro`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 879€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/800353117652 — item Error Page |
| Sofort+ | 910€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/156436320090 — live EUR 900,00oder Preisvorschlag / Sony PlayStation 5 PRO |
| Auktion | 650€ / 🟡 Ждёт 24ч | **OK_PRICE_LIVE** | https://www.ebay.de/itm/147439929946 — live EUR 640,00 / Sony PlayStation 5 Pro Konsole 2TB DualSense Controller 4K HDMI |
| Auktion+ | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/398166794888 — ? https://www.ebay.de/itm/398166794888 / (html-id) |

### Pixel 5
query: `google pixel 5`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 135€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/178260069267 — item Error Page |
| Sofort+ | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/317222101600 — EUR 81,62 https://www.ebay.de/itm/317222101600 / Smartphone Google Pixel 4a 5G 6. |
| Auktion | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/198489964194 — EUR 55,00 https://www.ebay.de/itm/198489964194 / Google Pixel 8a 128GB 5G Obsidia |
| Auktion+ | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/198489964194 — EUR 55,00 https://www.ebay.de/itm/198489964194 / Google Pixel 8a 128GB 5G Obsidia |

### Sony WH-1000XM6
query: `sony wh-1000xm6`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 246€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/147429611462 — item Error Page |
| Sofort+ | 280€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/358742904296 — live EUR 280,00oder Preisvorschlag / Sony WH-1000XM6 Bluetooth Noise Cancelling K |
| Auktion | 157€ / 🟡 Ждёт 24ч | **OK_PRICE_LIVE** | https://www.ebay.de/itm/278173249310 — live EUR 151,00 / Sony WH-1000XM6 - Guter Zustand - In Blau - Guter Zustand |
| Auktion+ | 356€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/800332784119 — live EUR 350,00oder Preisvorschlag / Sony 1000X Serie / Kabellose Noise Cancellin |

### 5070 ti (pc, rechner, computer, desktop, gaming pc)
query: `rtx 5070 ti gaming pc`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 1698€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/235389456368 — item Error Page |
| Sofort+ | 1523€ / 🟣 Дорого | **PRICE_DRIFT** | https://www.ebay.de/itm/257624107538 — live EUR 1.499,00oder Preisvorschlag / Gaming PC Intel 14600k MSI 5070 Ti 32GB RA |
| Auktion | 929€ / 🟢 Подходит | **OK_PRICE_LIVE** | https://www.ebay.de/itm/206414570316 — live EUR 905,00 / MIFCOM High-End Gaming-PC / RTX 5070 Ti / 32 GB RAM / 4 TB SSD  |
| Auktion+ | 1831€ / 🟣 Дорого | **PRICE_DRIFT** | https://www.ebay.de/itm/307063105020 — live EUR 1.800,00oder Preisvorschlag / Captiva Gaming PC R89-486/R5 7600X/16GB DD |

### 4080 (pc, rechner, computer, desktop, gaming pc)
query: `rtx 4080 gaming pc`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 1650€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/358532817350 — item Error Page |
| Sofort+ | 1299€ / 🟣 Дорого | **PRICE_DRIFT** | https://www.ebay.de/itm/267728726850 — live EUR 1.299,00oder Preisvorschlag / ! Premium RGB Gaming PC / MSI RTX 4080 / R |
| Auktion | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/206414570316 — ? https://www.ebay.de/itm/206414570316 / (html-id) |
| Auktion+ | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/206414570316 — ? https://www.ebay.de/itm/206414570316 / (html-id) |

### iPhone 15 Pro Max
query: `iphone 15 pro max`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 576€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/168254452627 — item Error Page |
| Sofort+ | 496€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/366541993988 — live EUR 490,00oder Preisvorschlag / Apple iPhone 15 Pro Max 256 GB Smartphone Sc |
| Auktion | 203€ / 🟡 Ждёт 24ч | **OK_PRICE_LIVE** | https://www.ebay.de/itm/407069883664 — live EUR 203,00 / Apple iPhone 15 Pro Max - 256GB - Titan Natur (Ohne Simlock) (B |
| Auktion+ | 581€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/327258353285 — live EUR 575,00oder Preisvorschlag / iphone 15 pro max 256 |

### samsung s24 ultra
query: `samsung s24 ultra`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 448€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/177788919216 — item Error Page |
| Sofort+ | 441€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/137509241365 — live EUR 434,68oder Preisvorschlag / Samsung Galaxy S24 Ultra - 256GB - Titanium  |
| Auktion | 187€ / 🟡 Ждёт 24ч | **OK_PRICE_LIVE** | https://www.ebay.de/itm/287466310856 — live EUR 181,00 / Samsung Galaxy S24 Ultra 256GB Titanium Black mt OVP |
| Auktion+ | 356€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/398177756980 — live EUR 350,00oder Preisvorschlag / Samsung Galaxy S24 Ultra 5G S928B DS 256GB T |

### 4050 oled
query: `rtx 4050 oled laptop`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 1355€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/267700848730 — item Error Page |
| Sofort+ | 807€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/398172387947 — live EUR 799,00oder Preisvorschlag / Samsung Galaxy Book 3 Ultra 120Hz OLED / RTX |
| Auktion | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/307054893659 — EUR 240,00 https://www.ebay.de/itm/307054893659 / HP Victus Gaming Laptop 15-fb31 |
| Auktion+ | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/307054893659 — EUR 240,00 https://www.ebay.de/itm/307054893659 / HP Victus Gaming Laptop 15-fb31 |

### 4060 oled
query: `rtx 4060 oled laptop`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 1410€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/287355185838 — item Error Page |
| Sofort+ | 1304€ / 🟣 Дорого | **PRICE_DRIFT** | https://www.ebay.de/itm/357207267549 — live EUR 1.299,00oder Preisvorschlag / ASUS Vivobook Pro 15 OLED Laptop - Intel U |
| Auktion | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/336684799325 — EUR 600,00 https://www.ebay.de/itm/336684799325 / Gigabyte G5 KF5 (2024) Gaming L |
| Auktion+ | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/336684799325 — EUR 600,00 https://www.ebay.de/itm/336684799325 / Gigabyte G5 KF5 (2024) Gaming L |

### asus vivobook 14x oled
query: `asus vivobook 14x oled`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 779€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/377126864169 — item Error Page |
| Sofort+ | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/117305840782 — EUR 650,00 https://www.ebay.de/itm/117305840782 / NEUES ANGEBOTASUS Vivobook Pro  |
| Auktion | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/236940425656 — EUR 175,00 https://www.ebay.de/itm/236940425656 / Asus VivoBook S433EA, Intel Cor |
| Auktion+ | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/236940425656 — EUR 175,00 https://www.ebay.de/itm/236940425656 / Asus VivoBook S433EA, Intel Cor |

### PRO X 2 SUPERSTRIKE
query: `logitech superstrike`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 145€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/147430856720 — item Error Page |
| Sofort+ | 156€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/307067684579 — live EUR 150,00oder Preisvorschlag / Logitech G Pro X2 Superstrike Wireless Gamin |
| Auktion | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/307054017770 — EUR 55,00 https://www.ebay.de/itm/307054017770 / Logitech G502 X PLUS Gaming-Maus |
| Auktion+ | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/307054017770 — EUR 55,00 https://www.ebay.de/itm/307054017770 / Logitech G502 X PLUS Gaming-Maus |

### logitech superlight 2
query: `logitech g pro x superlight 2 -dex`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 70€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/366134867215 — item Error Page |
| Sofort+ | 66€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/358776580314 — live EUR 60,00oder Preisvorschlag / Logitech G PRO X Superlight 2 Kabellose Gamin |
| Auktion | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/407076777960 — EUR 90,00 https://www.ebay.de/itm/407076777960 / NEUES ANGEBOTLogitech G Pro x Su |
| Auktion+ | 96€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/407076777960 — live EUR 90,00oder Preisvorschlag / Logitech G Pro x Superlight 2 Kabellose Gamin |

### logitech superlight 2 dex
query: `logitech superlight 2 dex`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 82€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/257624076023 — item Error Page |
| Sofort+ | 66€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/358787597789 — live EUR 60,00oder Preisvorschlag / Logitech G PRO X SUPERLIGHT 2 DEX Gaming Maus |
| Auktion | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/407076777960 — ? https://www.ebay.de/itm/407076777960 / (html-id) |
| Auktion+ | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/407076777960 — ? https://www.ebay.de/itm/407076777960 / (html-id) |

### Sony ULT Wear
query: `sony ult wear WH-ULT900N`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 192€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/227338481724 — item Error Page |
| Sofort+ | 133€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/186919071916 — live £79,19oder Preisvorschlag / Sony ULT WEAR WH-ULT900N Kopfhörer Over-Ear Blue |
| Auktion | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/168535497091 — EUR 100,00 https://www.ebay.de/itm/168535497091 / Sony Ult Wear / WH-ULT900N / Ko |
| Auktion+ | --- / ❌ Не найдено | **BOT_EMPTY_STOCK_EXISTS** | https://www.ebay.de/itm/168535497091 — EUR 100,00 https://www.ebay.de/itm/168535497091 / Sony Ult Wear / WH-ULT900N / Ko |

### LG UltraGear OLED
query: `lg ultragear oled 480hz`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 566€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/198494640410 — item Error Page |
| Sofort+ | 522€ / 🟣 Дорого | **OK_PRICE_LIVE** | https://www.ebay.de/itm/358691478783 — live EUR 522,22oder Preisvorschlag / LG UltraGear 27GX790A 67cm/27Zoll OLED-Monit |
| Auktion | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/800354758653 — EUR 420,00 https://www.ebay.de/itm/800354758653 / NEUES ANGEBOTLG OLED WQHD 480Hz |
| Auktion+ | --- / ⚠️ eBay block | **BOT_LIED_LABEL** | https://www.ebay.de/itm/800354758653 — EUR 420,00 https://www.ebay.de/itm/800354758653 / NEUES ANGEBOTLG OLED WQHD 480Hz |

### Samsung Odyssey OLED G6 500Hz
query: `samsung odyssey oled g6 500hz`

| Bucket | Bot | Honest | Proof / note |
|--------|-----|--------|--------------|
| Sofort | 470€ / 🟣 Дорого | **BOT_LINK_ERROR_PAGE** | https://www.ebay.de/itm/307045605733 — item Error Page |
| Sofort+ | 524€ / 🟣 Дорого | **CHECK_ERROR** | https://www.ebay.de/itm/398162444700 — Page.goto: Target page, context or browser has been closed
Call log:
  - navigati |
| Auktion | --- / ⚠️ eBay block | **LIVE_ALSO_BLOCKED** | local also failed: Page.goto: Target page, context or browser has been closed |
| Auktion+ | --- / ⚠️ eBay block | **LIVE_ALSO_BLOCKED** | local also failed: Page.goto: Target page, context or browser has been closed |

## Где бот соврал / не добрал (stock есть)

- **Redmagic 11 Pro** / Auktion+: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/327257689079`
  - EUR 519,36 https://www.ebay.de/itm/327257689079 | Nubia Red Magic 11 Pro (Dual SIM 12GB RAM 256GB 5G) Frost Us
- **Redmagic 11S Pro** / Auktion: bot=`⚠️ Rate limit` → live `https://www.ebay.de/itm/800346805893`
  - ? https://www.ebay.de/itm/800346805893 | (html-id)
- **Redmagic 11S Pro** / Auktion+: bot=`⚠️ Rate limit` → live `https://www.ebay.de/itm/800346805893`
  - ? https://www.ebay.de/itm/800346805893 | (html-id)
- **Nubia Z80 Ultra** / Sofort+: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/188297638724`
  - EUR 67,82 https://www.ebay.de/itm/188297638724 | ZTE nubia Z80 Ultra NX741J Plastic Back Cover with Camera Le
- **Nubia Z80 Ultra** / Auktion+: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/178306976467`
  - EUR 401,00 https://www.ebay.de/itm/178306976467 | Nubia Z80 Ultra Starry Night Version + Retro Kit Wird in neu
- **Nubia Z80 LV** / Auktion: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/178306976467`
  - ? https://www.ebay.de/itm/178306976467 | (html-id)
- **Nubia Z80 LV** / Auktion+: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/178306976467`
  - ? https://www.ebay.de/itm/178306976467 | (html-id)
- **Nubia Z70 Ultra** / Auktion: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/206412457716`
  - EUR 525,00 https://www.ebay.de/itm/206412457716 | Nubia Z70 Ultra 24Gb Ram 1Tb Speicher Gebraucht Wird in neue
- **Nubia Z70S Ultra** / Sofort: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/365756525063`
  - ? https://www.ebay.de/itm/365756525063 | (html-id)
- **Nubia Z70S Ultra** / Auktion: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/206412457716`
  - ? https://www.ebay.de/itm/206412457716 | (html-id)
- **Nubia Z70S Ultra** / Auktion+: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/206412457716`
  - ? https://www.ebay.de/itm/206412457716 | (html-id)
- **PlayStation 5 Pro** / Auktion+: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/398166794888`
  - ? https://www.ebay.de/itm/398166794888 | (html-id)
- **Pixel 5** / Sofort+: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/317222101600`
  - EUR 81,62 https://www.ebay.de/itm/317222101600 | Smartphone Google Pixel 4a 5G 6.2" 2340x1080px 6GB/127GB 16.
- **Pixel 5** / Auktion: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/198489964194`
  - EUR 55,00 https://www.ebay.de/itm/198489964194 | Google Pixel 8a 128GB 5G Obsidian DEFEKT! # AU 9052 Wird in 
- **Pixel 5** / Auktion+: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/198489964194`
  - EUR 55,00 https://www.ebay.de/itm/198489964194 | Google Pixel 8a 128GB 5G Obsidian DEFEKT! # AU 9052 Wird in 
- **4080 (pc, rechner, computer, desktop, gaming pc)** / Auktion: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/206414570316`
  - ? https://www.ebay.de/itm/206414570316 | (html-id)
- **4080 (pc, rechner, computer, desktop, gaming pc)** / Auktion+: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/206414570316`
  - ? https://www.ebay.de/itm/206414570316 | (html-id)
- **4050 oled** / Auktion: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/307054893659`
  - EUR 240,00 https://www.ebay.de/itm/307054893659 | HP Victus Gaming Laptop 15-fb3149AX AMD RyzenTM 77445HS NVID
- **4050 oled** / Auktion+: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/307054893659`
  - EUR 240,00 https://www.ebay.de/itm/307054893659 | HP Victus Gaming Laptop 15-fb3149AX AMD RyzenTM 77445HS NVID
- **4060 oled** / Auktion: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/336684799325`
  - EUR 600,00 https://www.ebay.de/itm/336684799325 | Gigabyte G5 KF5 (2024) Gaming Laptop | i7-13620H | 32GB | RT
- **4060 oled** / Auktion+: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/336684799325`
  - EUR 600,00 https://www.ebay.de/itm/336684799325 | Gigabyte G5 KF5 (2024) Gaming Laptop | i7-13620H | 32GB | RT
- **asus vivobook 14x oled** / Sofort+: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/117305840782`
  - EUR 650,00 https://www.ebay.de/itm/117305840782 | NEUES ANGEBOTASUS Vivobook Pro 14X OLED (N7400) M7400QC-KM08
- **asus vivobook 14x oled** / Auktion: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/236940425656`
  - EUR 175,00 https://www.ebay.de/itm/236940425656 | Asus VivoBook S433EA, Intel Core i7-1165G7 mit Windows 11 Wi
- **asus vivobook 14x oled** / Auktion+: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/236940425656`
  - EUR 175,00 https://www.ebay.de/itm/236940425656 | Asus VivoBook S433EA, Intel Core i7-1165G7 mit Windows 11 Wi
- **PRO X 2 SUPERSTRIKE** / Auktion: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/307054017770`
  - EUR 55,00 https://www.ebay.de/itm/307054017770 | Logitech G502 X PLUS Gaming-Maus - Weiß Wird in neuem Fenste
- **PRO X 2 SUPERSTRIKE** / Auktion+: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/307054017770`
  - EUR 55,00 https://www.ebay.de/itm/307054017770 | Logitech G502 X PLUS Gaming-Maus - Weiß Wird in neuem Fenste
- **logitech superlight 2** / Auktion: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/407076777960`
  - EUR 90,00 https://www.ebay.de/itm/407076777960 | NEUES ANGEBOTLogitech G Pro x Superlight 2 Kabellose Gaming-
- **logitech superlight 2 dex** / Auktion: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/407076777960`
  - ? https://www.ebay.de/itm/407076777960 | (html-id)
- **logitech superlight 2 dex** / Auktion+: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/407076777960`
  - ? https://www.ebay.de/itm/407076777960 | (html-id)
- **Sony ULT Wear** / Auktion: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/168535497091`
  - EUR 100,00 https://www.ebay.de/itm/168535497091 | Sony Ult Wear | WH-ULT900N | Kopfhörer | Over Ear Wird in ne
- **Sony ULT Wear** / Auktion+: bot=`❌ Не найдено` → live `https://www.ebay.de/itm/168535497091`
  - EUR 100,00 https://www.ebay.de/itm/168535497091 | Sony Ult Wear | WH-ULT900N | Kopfhörer | Over Ear Wird in ne
- **LG UltraGear OLED** / Auktion: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/800354758653`
  - EUR 420,00 https://www.ebay.de/itm/800354758653 | NEUES ANGEBOTLG OLED WQHD 480Hz OVP + Garantie Wird in neuem
- **LG UltraGear OLED** / Auktion+: bot=`⚠️ eBay block` → live `https://www.ebay.de/itm/800354758653`
  - EUR 420,00 https://www.ebay.de/itm/800354758653 | NEUES ANGEBOTLG OLED WQHD 480Hz OVP + Garantie Wird in neuem