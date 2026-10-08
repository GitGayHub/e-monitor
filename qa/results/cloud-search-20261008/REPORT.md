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
