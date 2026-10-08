# Cloud live acceptance checkpoint — 2026-10-08T09:07:32.561248+00:00

Acceptance is **PARTIAL**, not complete. Starting bot SHA `117c9095409c0bce5ae154e1d777f6610d41f4e4`; Android SHA `8553f6634e9a9f8e2c38a86aabf20018fa3c7eae`. Both work on `codex/cloud-work`.

## Independently confirmed findings

1. [117449336412](https://www.ebay.com/itm/117449336412): Italian `Numero modello=A3126` was ignored by both implementations. Read own title, seller trunf-2015/533/100%, item specifics, EUR 1070 bid and full seller iframe. Model contradicts iPhone 17 Pro Max. [Apple identification](https://support.apple.com/en-us/108044) lists A3257/A3525/A3527/A3526. Python details contract returned true before fix and false after; Android follows the same labelled-field fix, with identical JSON regressions. This is a **model acceptance error**, not evidence of an actual notification: the price is independently over the owner's limit. Added Italian `Modello` and `Numero modello` without changing allowed generations.
2. [189051391793](https://www.ebay.com/itm/189051391793) and [227534369510](https://www.ebay.com/itm/227534369510): own status is `Item sold on…`, which neither parser marked UNAVAILABLE. Existing past end date already rejects these snapshots; the fix makes own sold status sufficient even when end date is absent. Quantity `More than 10 available 2 sold` and a recommendation's sold text remain valid negative controls. The iPhone seller's full text still explicitly admits replacement of broken rear glass.
3. [128121409205](https://www.ebay.com/itm/128121409205): own seller is marclemmor, feedback 452/100%; auction + Best Offer, EUR 297.13, structured end 2026-10-14T18:45:27Z. Full seller description is consistent with the requested model and discloses a glass blemish. Germany delivery is unverified; **no eligible-buy/notification PASS**. This does not verify actual Android network behavior or phone.
4. Remaining mandated controls were reopened over HTTP on `.com`: expired Transparent REDMAGIC, sold expensive REDMAGIC, PS5 disc drive, expensive whole PS5 Pro, two screens and Nubia frame. Current source, status, prices and individual verdicts: [reviewed-items.json](reviewed-items.json).

## Retrieval limitations

A normal Chromium `.de` smoke visit initially rendered an auction SERP (HTTP 200); `.de` item 128121409205 redirected to browser challenge. Ordinary requests to www/m `.de` were also challenged. Web-reading tool could not open the two control pages. `.com` opened the same public item without solving CAPTCHA, changing IP, dropping the Cloud proxy or using credentials. Subsequently bounded first-page `.com` discovery was tried for each product, using up to three prioritized spellings and separate auction/BIN URLs. Per-product JSON records **every actually attempted URL**, parameters, UTC timestamp and outcome. No inaccessible request is zero-result proof.

These `.com` searches use worldwide/default US delivery and may include **matching fewer words**, accessories and other models. They are an independent comparison source, not a replacement for the owner's Germany/worldwide `.de` searches. Counts are discovered IDs / fetched item pages / fetched seller descriptions, **not** independently verified suitable devices. Unreviewed records remain UNVERIFIABLE; descriptionsFetched does not mean descriptionsVerified. No complete-catalogue claim, no confirmed minimum, and no missed cheap Germany deal claim.

[request-contracts.json](request-contracts.json) renders all 48 stored Python request profiles and aliases without issuing API calls; `requestWasSent=false` distinguishes this static check from live requests. Kotlin tests check actual manifest query/alias/HTML parameter parity, permitting the documented 240-vs-60 page size difference. API access/quota is unavailable here because Cloud provides no eBay credential binding; the read-only server runtime at 08:48:12Z reported API/ok/46 active/rules 1791439498, which does not establish this session's credentials.

## Preservation and validation

Production main, settings/limits, enabled flags, raw searches, Telegram, seen, lists and physical phone are unchanged. Snapshot confirms 48 stored, 46 enabled, one global seller ban (`talk point gmbh`) and 16 hidden IDs. No ZIP, cookie, secret, full personal manifest or private backup is published. Raw HTML/complete seller bodies stay in private scratch; public evidence contains only listing facts and hashes.

Baseline: 237 Python tests + 5 Cloud-sync tests passed. Initial local Android attempts exposed missing Java proxy configuration, then JRE without javac. Installed SDK36/build tools and a separate JDK21; build runs through the configured proxy and CA. Python after model fix: 238 passed. Targeted latest checks and full latest Android result/CI are recorded in the next checkpoint; **not yet claimed successful here**.

## Next stage

Finish recording all 24 products; examine remaining live model/description candidates, all four DE-profile baskets, destination shipping/import costs, pagination and minima once accessible. Queue status BLOCKED is a dependency blocker, not proof that every basket was directly searched; each updated basket says `directBucketAcceptancePerformed=false`. Resume with the original saved settings and these evidence records. Phone install, real Android HTTP seller/time, signed update and Telegram delivery stay for PC/device access under the owner's existing restrictions.
