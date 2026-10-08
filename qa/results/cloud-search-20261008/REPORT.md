# Search correction checkpoint — 8 October 2026

Status: PARTIAL. Fresh cloud-work HEADs matched the owner's handoff (Python `8a84533`, Android `ebd216e`). No production code/state or physical phone changes.

## Confirmed retrieval defect

The same DE-profile, hard ceiling 2500 €, condition any, fixed-price query returned 60 first-page cards for `5070 ti pc`, but only one for `(5070 ti pc,5070 ti rechner,5070 ti computer,5070 ti desktop,5070 ti gaming pc)`. That sole card was [267128690331](https://www.ebay.de/itm/267128690331), a whole gaming-PC variation listing whose minimum does not establish the requested configuration's price. Android HTML and Python quota fallback incorrectly shared Browse API OR batching with the website. Browser independently opened the simple .de query, HTTP repeated both exact profiles. See `retrieval-comparison.json`; page limits are not catalogue totals.

HTML now sends individual aliases in both engines, deduplicates item IDs, stops on a technical failure and preserves the failure. Browse API retains its <=100 character OR batches. Normal Python HTML no longer stops at the first success/clean empty or hides a later failure. Generated PC aliases retain saved aliases and add reversed word order, RTX prefix and compact RTX5070TI/RTX4080. GPU/category post-filters remain active; raw owner queries and limits were not edited.

## Confirmed pickup defect

[800423940260](https://www.ebay.de/itm/800423940260): own title `Gaming PC (Rtx5070TI, Ryzen 7 5800x, 32gb DDR4 Ram)`, 1450 €, seller `pa_426428`, fixed price, no Best Offer, no price range. Independent DE SERP explicitly says **Kostenlose Abholung**. Both parsers missed this pickup-only marker. Both now recognise it; delivery to an Abholstation remains delivery. Full seller body independently read: installed RTX5070Ti, Ryzen7 5800X, Corsair32GB, AorusB550Elite,2TB NVMe+1TB SSD, PurePower13M750W, LightLoop360, Corsair465X. This is a real PC above the1300€ limit, not an accessory. Item HTTP defaulted to a US shipping destination, so no Germany delivered total is certified from it.

## Validation at checkpoint

Python baseline238 +5 cloud-sync passed; after fix243 unit tests passed. Added captured-card pickup regression and synthetic station-delivery, all-alias, deduplication, failure-preservation and model-preservation controls. Android paired regression tests added; local Gradle unit/build still running at this checkpoint. Initial build setup failures were environment-only (Java proxy, then missing javac); installed isolated SDK36/JDK21 and configured the inherited proxy/CA. No source workaround for those failures.

Independent collection is proceeding across24 groups/four dedicated profiles; not yet full description/basket/minimum acceptance. Emulator API36 software boot lacked KVM and did not complete boot during the attempt; terminated the specific emulator to release resources. No UI gestures or Android link invocation claimed.


## Statistics and manual-search checkpoint

Confirmed by source/isolated regression: near-end Best Offer auctions duplicated between Auktion/Auktion+; hybrid BO applied to the auction side, and per-bucket verification used the other price. Both statistics splits now use one offer/bid bucket per format and the actual format price. Normal alert eligibility/24h policy remains intact. Python dedicated auction HTML drops the purchase-price floor; Android/manual request rules covered by regressions.

Android refill previously erased real rejected candidates after an empty reply and ignored cheaper refill candidates for a populated companion bucket. A rejection ledger retains/deduplicates actual IDs, updates reclassified IDs, keeps up to15 samples per basket, and preserves known evidence alongside technical errors. Variation PCs now have an unconfirmed configuration/price reason, distinct from accessories. Pickup reason names the condition. Long press exposes generated individual aliases instead of the broken website OR expression; uses the actual request builder, with local-only filters disclosed. Link-launch failures become visible. Original phone-model nested encoding independently proved necessary (eBay selected-filter DOM comparison); preserved, not repaired.

Local validation:246 Python unit,5 cloud-sync,248 Android unit tests passed; debug APK and instrumentation APK built. Three isolated Compose instrumentation cases prepared for GitHub KVM emulator, pending execution at this checkpoint. Local software emulator did not boot without KVM; no local UI proof.

Fresh DE HTTP four-profile requests collected for all24 groups (bounded first pages); eight PC aliases additionally exercised and OLED variants sampled. Independent browser stopped at Sofort+ challenge (`/splashui/challenge`, HTTP200) at12:27:47 UTC; no subsequent eBay requests or bypass. This is BLOCKED, never zero-results. Delivery to Germany, all descriptions, pagination/minima, actual Android HTTP and full96-basket acceptance remain incomplete. Detailed matrix and reviewed item evidence follow in a documentation checkpoint.


## Completed bounded DE discovery and description parity

See [MATRIX.md](MATRIX.md), matrix.json and reviewed-items.json.130 DE HTTP requests:94/96 dedicated profiles attempted (93 valid; S24 Ultra Sofort+503 stopped its two auctions),36 extra aliases;2702 union IDs include irrelevant/related cards. All24 groups/48 stored searches documented,46 enabled unchanged. No whole catalogue/minimum proof.323 own pages/321 seller bodies fetched;35 full bodies independently read in this pass, not321 fully reviewed. One valid dedicated browser profile (5070Ti Sofort); next protectedHTTP200 at12:27:47, stopped all eBay access. No live Browse credentials, no actual Android HTTP parity claim.

Paired private offline replay of321 complete captured HTML descriptions/aspects passed after resolving four disagreements: Python rejected two legitimate Nubia Model=Z80 Ultra aspects without brand, whereas Android already accepted them; Python iframe head/titleeBay made N/a falsely nonempty and hid anchored GPRO2LIGHTSPEED conflicting-description checks. Python now excludes iframe head and expands Nubia brand only in model aspects, retaining neighboring generation/S/Leading exclusions. Actual contradictory mouse406063677998 remains unconfirmed/rejected; no claim that its photo conclusively proves another model. Both now reject affirmative spacedF A K E declarations in whole seller body, confirmed820206597250. Negated/warning controls remain accepted.17 identical public whole-body model/description fixtures supplement private321 replay; neither proves Germany purchase eligibility.

5070Ti:8004239402601450€ whole desktop, pickup-only, over1300€;227550437275 real ROG NUC5070Ti auction own bid2024€, end2026-10-10T14:36:45Z, expensive and Germany shipping unverified.4080:3270269296951600€ full tower pickup-only Gotha;2872219874461699€ whole desktop;8002845287322150€ pickupHamburg. Dedicated auction profiles found related beads/cards/wrong GPUs, no independently qualifying4080PC auction in inspected first pages; absence across whole catalogue not established.4060OLED:3572072675491299€ and2678064455891143.55€ correct model/panel but >750€;168760655359 auction2099€ is1920×1200 nonOLED,189044975691 OLED106€ auction has Radeon, not4060. These are precise rejections, not zero-results proofs.

Other controls:XM6307217017060157€ bid ends13October (>24h), Superlight21687612813943.50€ bid ends11October (>24h), PS5Pro407268664029590€ bid ends12October (>24h); model match does not mean available fixed-price bargain. LG800366377085405€ +18.99€ SERP=423.99€ potential under430€; own short body only says10months, functional condition/destination/total remain unconfirmed. Galaxy500Hz137797112911450€ before shipping is over400€ saved target. User limits not changed.

Local current suite250 Python +5 sync and251 Android tests/APKs verified (final CI pending publication). Four fixture instrumentation cases now include actualopenUrl ACTION_VIEW interception, cap/persistence, legacy repeat, tap+long-press four baskets+alias selection. Real browser handler launch uses offline emulator network; UI still pending at checkpoint. Prior CI37778181423 green covers stage2c7552c8/5e681fd, not these last corrections.


Private owner-ban replay repeated:16 hidden IDs,1 global seller and allowed control passed in both engines using read-only manifest;0 configured search-specific sellers, synthetic per-search ban still passed. No lists/state writes. Initial GitHub UI37778181504 failed before boot:API36 emulator fatal insufficient userdata disk6650.61MB available/7372.80MB required. KVM available; disposable-runner unused .NET/GHC cleanup added, rerun pending. No UI result claimed from failed boot.


## Verified Actions source checkpoint and external-window limit

Both source commits Python2fac998 / Android631e0a9 are green in [readiness37780829091](https://github.com/GitGayHub/e-monitor-android/actions/runs/37780829091):250 Python+5sync, Android unit/APK build. Downloaded artifact11552816199 and independently hashed its APK:445c8eee4ffc8d475310524e93cb002d828c40f566d887b89a792a1dafe8e1b8 (expires2026-10-22T13:04:26Z).

[API36 UI37780828987](https://github.com/GitGayHub/e-monitor-android/actions/runs/37780828987) boots with KVM after disk fix; all4 instrumentation tests passed,0skip/fail. Downloaded XML verifies persistence/cap15, legacy repeat, four-basket longpress+alias and actualopenUrl ACTION_VIEW interception. External adb launch correctly resolves Chrome, but downloaded browser screenshot shows SystemUI ANR; it is NOT proof of a rendered browser window.

Only isolated workflow changes follow: stop the4GB Gradle daemon before emulator, run prebuilt connected tests with1.5GB heap, API35/Nexus4/3GBRAM/4cores, and explicitly assert focused Chrome window after offline ACTION_VIEW -W. No new eBay network requests. Both API36 component proof and external-window limit remain recorded; next test pending. App/Python source unchanged since green631e0a9/2fac998.
