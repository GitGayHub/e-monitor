# Cloud live acceptance — PARTIAL (2026-10-08)

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

## Further independently reviewed findings

5. Superstrike [407258358438](https://www.ebay.com/itm/407258358438), [398359202699](https://www.ebay.com/itm/398359202699), [178510190739](https://www.ebay.com/itm/178510190739): full seller bodies and own model/MPN confirm whole wireless gaming mice. Both classifiers interpreted Lightweight as a separate weight. Exact-word exemption fixes this while actual weight sets/shells stay rejected. US154.99/159.99/169 quotes are not Germany delivered totals; no missed cheap Germany deal is claimed. Historical Superlight2 Lightweight fixtures now correctly reject over-limit prices rather than call them parts.
6. Sony ULT [267806813661](https://www.ebay.com/itm/267806813661) and [287377210763](https://www.ebay.com/itm/287377210763): own SNAPPED/Broken Headband disclosures were missed despite the complete seller descriptions being readable. Both now reject explicit structural faults, retain not-broken/not-snapped controls and do not treat snapped photos/broken packaging as a headphone defect. Historical snapped ULT fixture now rejects relevance before price.
7. Samsung G6 [198686063183](https://www.ebay.com/itm/198686063183): own title and complete description explicitly 240Hz; LS27FG602SNXZA code in specifics previously overrode that mismatch. Both implementations reject an explicit non500Hz refresh claim when there is no500Hz claim, retaining model-code-only500Hz variants. Price remains separately over limit; no actual false notification is established.
8. Pixel5 [206604238695](https://www.ebay.com/itm/206604238695): full body, own765G/OLED90Hz/128GB and hardware test table consistently describe a functional handset. A specific hypothetical return-policy promise was treated as actual not-working damage. Remove only that complete promise, preserving separate actual-fault statements. Contiguous-US shipping terms do not prove Germany eligibility. [800756789770](https://www.ebay.com/itm/800756789770) actually admits cracked camera housing and remains rejected.

Other reviewed controls: real S24Ultra bundle with front/camera cracks rejected; consistent whole VivobookPro14X N7400PC/OLED/RTX3050 is over limit; two whole iPhone17 models are consistent but Germany shipping/import totals remain unknown. Dropped insurer-serviced iPhone wording and severely chipped S24 appearance remain UNVERIFIABLE. Details: [reviewed-items.json](reviewed-items.json).

[full-input-replay.json](full-input-replay.json) records14 matching Python/Kotlin runs on identical **complete own seller iframes plus own aspects**, with independent expectations and input/body hashes. JVM Android validation ran locally against private full inputs; the public31-case regression file uses short excerpts/paraphrases plus synthetic controls. No full personal seller text/IMEI is uploaded. Relevance replay deliberately excludes price/destination/status; it cannot prove buy eligibility or actual Android HTTP behavior.

9. Superstrike [318767580494](https://www.ebay.com/itm/318767580494): full seller body and own Type=Gaming Mouse/Model=PRO X2 SUPERSTRIKE/MPN910-007700/Number of Buttons=5 confirm a complete mouse. The title's5-Button feature was falsely interpreted as separately sold buttons. Remove counted-button wording only from declared mouse titles without compatibility/replacement/spare/repair/set/only language. Actual button sets, PCB and damage remain rejected. Historical complete5-button Superlight now has an over-limit reason rather than a parts reason. US150 and seller8 feedback do not prove DE delivered eligibility or a missed cheap Germany deal.

## Coverage of all24 groups and96 baskets

[coverage-summary.json](coverage-summary.json):68 actually attempted bounded .com SERP requests,500 collected records/498 distinct IDs,483 own item pages,478 fetched seller bodies.26 records independently reviewed;23 complete bodies independently read. The initial mandated10 control IDs are separate from these500 collection records. Counts of collected or fetched pages are not suitable-device counts.13 groups' primary .com discovery was blocked;11 groups yielded bounded first-page records. No complete catalogue, all-basket pagination or minimum verified.

| Product group | Actual .com search requests | Own pages | Bodies fetched | Acceptance baskets |
|---|---:|---:|---:|---|
| 1 samsung_galaxy_s25_edge | 1 | 0 | 0 | BLOCKED ×4 |
| 2 iphone_17_pro_max | 2 | 50 | 49 | BLOCKED ×4 |
| 3 redmagic_11_pro | 6 | 50 | 50 | BLOCKED ×4 |
| 4 redmagic_11s_pro | 6 | 50 | 50 | BLOCKED ×4 |
| 5 nubia_z80_ultra | 1 | 0 | 0 | BLOCKED ×4 |
| 6 nubia_z80_ultra_leading | 1 | 0 | 0 | BLOCKED ×4 |
| 7 nubia_z70_ultra | 1 | 0 | 0 | BLOCKED ×4 |
| 8 nubia_z70s_ultra | 6 | 50 | 49 | BLOCKED ×4 |
| 9 pixel_5 | 5 | 50 | 50 | BLOCKED ×4 |
| 10 sony_wh_1000xm6 | 1 | 0 | 0 | BLOCKED ×4 |
| 11 5070_ti_pc | 1 | 0 | 0 | BLOCKED ×4 |
| 12 4080_pc | 1 | 0 | 0 | BLOCKED ×4 |
| 13 samsung_s24_ultra | 6 | 50 | 50 | BLOCKED ×4 |
| 14 4050_oled | 1 | 0 | 0 | BLOCKED ×4 |
| 15 4060_oled | 1 | 0 | 0 | BLOCKED ×4 |
| 16 asus_vivobook_14x_oled | 5 | 50 | 50 | BLOCKED ×4 |
| 17 logitech_superstrike | 6 | 50 | 50 | BLOCKED ×4 |
| 18 logitech_superlight_2_std | 1 | 0 | 0 | BLOCKED ×4 |
| 19 logitech_superlight_2_dex | 1 | 0 | 0 | BLOCKED ×4 |
| 20 sony_ult_wear | 6 | 43 | 42 | BLOCKED ×4 |
| 21 samsung_odyssey_oled_g6_500hz | 6 | 40 | 38 | BLOCKED ×4 |
| 22 ps5_pro | 1 | 0 | 0 | BLOCKED ×4 |
| 23 iphone_16_pro_max | 1 | 0 | 0 | BLOCKED ×4 |
| 24 lg_ultragear_oled_480hz | 1 | 0 | 0 | BLOCKED ×4 |

All96 queue baskets remain **BLOCKED** by the unavailable original DE-profile catalogue/destination verification; `directBucketAcceptancePerformed=false`. This is a dependency status, not a claim of96 separately executed basket searches. `pendingChecks=0` means no unrecorded group remains; `acceptanceIncompleteChecks=96` preserves the unfinished acceptance. No PASS or NO_RESULTS_CONFIRMED.

At the final recheck (approximately09:30UTC), ordinary inherited-proxy requests to GitHub API, GitHub and eBay returned HTTP503/upstream connection failure ([network-availability.json](network-availability.json)). This also prevents a fresh post-fix browser confirmation; final replay uses saved live snapshots. GitHub Connector remained available for publication and CI reads. No CAPTCHA solving, IP/proxy change or eBay credentials were used.

## Preservation and validation

Production main, normal mode, settings/limits, enabled flags, raw searches, Telegram, seen, lists and physical phone unchanged. Snapshot:48 stored/46 enabled,1 global seller ban and16 hidden IDs. [blacklist-validation.json](blacklist-validation.json) verifies all16 hidden IDs plus global/search-specific seller ban against an isolated synthetic otherwise-accepted control in both Python and Kotlin. Kotlin replay checks16 HiddenByHand results, the global seller ban and search-specific BannedSeller result, plus accepted control; this is not live seller retrieval proof. ZIP/raw manifest/cookies/secrets/private backups never staged.

Baseline237 Python +5 Cloud-sync passed. Final **238 Python +5 Cloud-sync +233 Android tests passed**, APK built,14 complete-input paired live replays passed. Same31 published regression cases run in both suites. Java21 and SDK36 installed in separate toolchain; configured proxy and CA retained. Expected D8 API36 warning remains; physical API36 compatibility is not tested. [validation.json](validation.json) and [local-check.log](local-check.log) record source blob hashes and actual local validation.

Local debug APK SHA256 `d6beeb65bb86245b073514c5e1690315701b2f72cd64a0cfbe68aa9711039c2f`. Actions signing can produce a different hash; use the CI artifact/hash for that run. Prior checkpoint [37758006402](https://github.com/GitGayHub/e-monitor-android/actions/runs/37758006402) succeeded for ff85bd03 with Actions APK SHA2569dc3a34af56772e91c15bc2e04e41908dd6672f763ae75592edb886b06c361c7, **not the additional5-Button fix**. Final current Android HEAD `7aa32121e0ff6fb78c138eb71da66508003cede8` passed [CI 37760420537](https://github.com/GitGayHub/e-monitor-android/actions/runs/37760420537) with Python `fe77982b9d7027a376e93061735402701b005fa2`. CI debug APK SHA256 `09aa6f1d2fd86c446f4b44f0495c97e7b6075f2aca930ab86f46b9fde57000b0`; artifact `11541838680` expires 2026-10-22T10:07:18Z. See [ci-current-head.json](ci-current-head.json). Final Python evidence-only followup retains all tested source blob hashes. Cloud-only logic_version `1791453018` is not deployment.

## Next available stage / PC handoff

Resume live eBay .de original saved profiles when access works:40–50 independently reviewed unique IDs per group or demonstrably complete smaller catalogue; all four buying-option baskets, actual Germany delivery/import totals, separate bid/BIN hybrid prices,24h auction rule, seller ownership/bans and actual minimum comparison. Inspect remaining scroll-wheel mouse titles before changing part heuristics; wording can sell either a whole mouse or spare wheel. Counted-button whole mice now have specific guarded regression coverage. Inspect ambiguous insurer/back-housing and chipped phones with own photos before suitability. Do not invent carrier/battery/storage policy or alter owner searches.

On PC use companion tools/cloud_sync.py --check; preserve dirty work, review integration plan, then isolated tests. Under existing restrictions leave physical phone/Telegram untouched. Real Android HTTP seller/endtime control128121409205, installation/signing and Telegram delivery still require a separately authorized PC/device stage.
