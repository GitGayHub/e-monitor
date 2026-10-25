# eBay account-deletion receiver — deployment in progress

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

References: [eBay setup](https://developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion),
[official SDK](https://github.com/eBay/event-notification-nodejs-sdk).
