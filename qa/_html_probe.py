#!/usr/bin/env python3
"""One-shot HTML probe: URL, status, parse counts (no Browse API)."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import monitor as m

QUERY = sys.argv[1] if len(sys.argv) > 1 else "RedMagic 11 Pro"
search = {
    "id": "probe",
    "query": QUERY,
    "filters": {"listing_type": "buy_now_offer", "sort": "price_asc"},
}
print("=== HTML probe", time.strftime("%H:%M:%S"), QUERY, "===")
url = m._build_url_with_host("ebay.de", search)
print("URL", url)
items, err = m._do_fetch_one("ebay.de", search)
print("do_fetch items", len(items or []), "err", err)
for it in (items or [])[:3]:
    print(" -", it.get("price"), (it.get("title") or "")[:70])

sess = m._get_ebay_session()
resp = sess.get(url, timeout=30, headers={
    "Referer": "https://www.ebay.de/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
})
body = resp.text or ""
print("raw status", resp.status_code, "len", len(body), "final", getattr(resp, "url", "")[:120])
low = body[:12000].lower()
needles = [
    "s-item", "s-card", "srp-results", "srp-river", "data-listingid",
    "splashui", "captcha", "pardon our interruption", "kein ergebnis",
    "0 ergebnisse", "challenge",
]
for n in needles:
    print(f"  count[{n}]={body.lower().count(n)}")
if "<title" in body:
    t0 = body.find("<title")
    t1 = body.find("</title>", t0)
    print("title:", body[t0 : t1 + 8][:200])
out = ROOT / "qa" / "inbox" / "html_probe_last.html"
out.write_text(body[:250000], encoding="utf-8", errors="replace")
print("saved", out)
