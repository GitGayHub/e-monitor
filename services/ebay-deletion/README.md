# eBay account-deletion receiver — active inbox, consumer review open

This is a dedicated Cloudflare Worker/D1 inbox, not an exemption claim. eMonitor
stores listing and seller information, so `Not persisting eBay data` is not true.

The Worker answers eBay's GET challenge using the exact configured HTTPS URL and
verification token. POST verifies the notification against eBay's public-key API
(same parsed-message serialization as the reference SDK), then commits to D1
before returning 204. A failed signature returns 412. Upstream/storage failure or
a full inbox returns 503 so eBay can retry. Repeated signed notification IDs are
idempotent. Unknown topics, oversized bodies and missing signatures are rejected.

`GET /internal/events` and `POST /internal/ack` require `QUEUE_TOKEN`. They are
only for the consumer; no data is exposed by the public health/challenge routes.
The receiver does not itself claim to purge historical copies. Do not describe
the integration as complete until the authenticated consumer, deletion policy,
eBay Send Test Notification and actual OAuth/Analytics/Browse checks are accepted.

On 2026-10-25 the live GET challenge, signed eBay Send Test Notification,
OAuth/Analytics/Browse from GitHub, and production loading of the second key all
passed. The new key has an independent 5000-call Browse window. Production quota
routing now also observes official per-key snapshots; one application's positive
legacy counter cannot reopen another application's exhausted quota.

Real account-deletion events are arriving. They remain in the private D1 inbox.
Current-state/text review found no matches for the first two real events, but
historical Git copies were not reviewed. No real event has been acknowledged as
processed, and no production subject data or Git history has been erased. The
explicitly generated synthetic eBay test alone was acknowledged after capture.
Finish the consumer/historical-copy review as a separate outstanding acceptance
item; receiving a notification is not evidence that all copies were deleted.

Runtime secrets (never commit values):

- `VERIFICATION_TOKEN`: 32–80 letters/digits/underscore/hyphen.
- `QUEUE_TOKEN`: random, at least 32 characters.
- `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`: active Production pair for notification
  public-key lookup. These calls are separate from Browse search quota.
- `ENDPOINT_URL`: exact HTTPS callback, without query/fragment; ordinary variable.
- `DB`: dedicated D1 binding; schema in `migrations/0001_inbox.sql`.

No credentials, notification bodies or seller identifiers are logged. Disable
Worker invocation logs. Use the free plan; do not accept a paid upgrade.

Run `node --test worker.test.mjs`. Tests use synthetic identities, generated ECC
keys and an in-memory SQLite inbox; no eBay, GitHub, Telegram or production DB.

The final nine tests include both ECC/ECDSA public-key labels and PEM responses
with/without line breaks. A live response established ECDSA/SHA1; the original
ECC-only assumption caused HTTP503 and was fixed before the successful live test.

References: [eBay setup](https://developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion),
[official SDK](https://github.com/eBay/event-notification-nodejs-sdk).
