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
