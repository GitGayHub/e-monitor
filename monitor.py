import time
import logging
import re
import functools
import requests
try:
    from curl_cffi import requests as curl_requests
    _HAS_CURL_CFFI = True
except ImportError:
    curl_requests = None
    _HAS_CURL_CFFI = False
from bs4 import BeautifulSoup
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, MenuButtonCommands
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import os
import sys
import argparse
import asyncio
import json
import html
import hashlib
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import base64
import copy
import random

from config_manager import ConfigManager
from price_history import (
    init_db, record_snapshot, record_seller_price, delete_seller_data,
    get_median_7d, get_stats_7d, get_trend, is_outlier,
    get_last_run, record_search_run,
    record_api_call, get_api_calls_count_24h,
)
from ebay_access import access as browse_access


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT")
GITHUB_REPO = os.environ.get("GITHUB_REPO") or os.environ.get("GITHUB_REPOSITORY")
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID") or os.environ.get("EBAY_APP_ID")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET") or os.environ.get("EBAY_CERT_ID")
EBAY_MARKETPLACE_ID = os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_DE")
EBAY_SOURCE = os.environ.get("EBAY_SOURCE", "auto").strip().lower()

SEEN_IDS_FILE = os.path.join(os.path.dirname(__file__), "seen_ids.json")
HTTP_TIMEOUT = (10, 20)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]

# Module-level persistent session: keeps cookies across fetches so eBay sees
# us as a returning browser, not a fresh anonymous bot every call.
_ebay_session = None
_ebay_session_ua = None
_ebay_session_warmed = False

# After repeated blocks we cool down for a while — hammering a flagged IP
# only makes the situation worse. While cooldown is active we don't even hit
# eBay, returning a 'cooldown' error so the UI can tell the user to wait.
# Cooldown grows exponentially with each consecutive block (5 → 10 → 20 → 40)
# and resets back to the base on the first successful fetch.
_EBAY_BLOCK_COOLDOWN_BASE = 300   # 5 minutes initially
_EBAY_BLOCK_COOLDOWN_MAX = 3600   # cap at 60 minutes
_ebay_block_until = 0.0
_ebay_consecutive_blocks = 0

# Short per-query result cache. Absorbs 'Retry' button spam from the UI so
# we don't hit eBay several times for the same query within a few seconds.
_EBAY_QUERY_CACHE_TTL = 30.0
_ebay_query_cache = {}  # key -> (timestamp, items, err)

_ebay_api_token = None
_ebay_api_token_expiry = 0.0

# When eBay blocks one fingerprint we rotate to the next. curl_cffi exposes
# multiple TLS / HTTP-2 fingerprints — rotating helps when an IP is flagged
# for a particular browser profile.
_EBAY_IMPERSONATION_CHAIN = (
    "chrome124",
    "chrome120",
    "safari17_2_ios",
    "safari17_0",
    "chrome131",
)
_ebay_impersonate_idx = 0


def _build_chrome_headers(ua):
    """Build full Chrome-like headers including sec-ch-ua client hints."""
    is_chrome = "Chrome/" in ua and "Firefox" not in ua
    chrome_ver = "131"
    m = re.search(r"Chrome/(\d+)", ua)
    if m:
        chrome_ver = m.group(1)
    is_mac = "Macintosh" in ua
    platform = '"macOS"' if is_mac else '"Windows"'
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    if is_chrome:
        headers.update({
            "sec-ch-ua": f'"Chromium";v="{chrome_ver}", "Not_A Brand";v="24", "Google Chrome";v="{chrome_ver}"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": platform,
        })
    return headers


def _get_ebay_session():
    """Returns a persistent session, warming it up on first use.
    Uses curl_cffi with Chrome TLS-impersonation if available (bypasses eBay's
    JA3 bot detection), otherwise falls back to plain requests."""
    global _ebay_session, _ebay_session_ua, _ebay_session_warmed, _ebay_impersonate_idx
    import random
    if _ebay_session is None:
        if _HAS_CURL_CFFI:
            profile = _EBAY_IMPERSONATION_CHAIN[_ebay_impersonate_idx % len(_EBAY_IMPERSONATION_CHAIN)]
            _ebay_session = curl_requests.Session(impersonate=profile)
            _ebay_session_ua = profile
            logger.info("eBay session ready (impersonate=%s)", profile)
        else:
            _ebay_session = requests.Session()
            _ebay_session_ua = random.choice(USER_AGENTS)
            _ebay_session.headers.update(_build_chrome_headers(_ebay_session_ua))
    return _ebay_session


def reset_ebay_session(rotate=False):
    """Drop session. If rotate=True also advance to the next fingerprint."""
    global _ebay_session, _ebay_session_warmed, _ebay_impersonate_idx
    _ebay_session = None
    _ebay_session_warmed = False
    if rotate:
        _ebay_impersonate_idx = (_ebay_impersonate_idx + 1) % len(_EBAY_IMPERSONATION_CHAIN)


# eBay host fallback chain. .de is hard-blocked at some IPs, .com works more reliably.
_EBAY_HOST_CHAIN = ["ebay.de", "ebay.com"]
_ebay_active_host = None  # remembered after a successful fetch
EBAY_CATEGORY_IDS = {
    "all": "",
    "electronics": "293",
    "phones": "15032",
    "phone_parts": "15032",
    "phone_accessories": "15032",
    "tablets": "58058",
    "computers": "58058",
    "laptops": "58058",
    "monitors": "58058",
    "mice": "58058",
    "headphones": "293",
    "vr": "293",
    "vr_headsets": "293",
    "cameras": "625",
    "video_games": "1249",
    "consoles": "1249",
    "smart_watches": "15032",
}

ALLOWED_SUBCATEGORIES = {
    "phones": {"9355", "178893"},      # Handys & Smartphones, Smartwatches
    "consoles": {"139971"},             # Videospiel-Konsolen
    "laptops": {"177"},                # Notebooks & Netbooks
    "tablets": {"171485"},              # Tablets & eReader
    "computers": {"179"},              # PC Desktops & All-in-Ones
    "mice": {"23160", "3676", "11195"}, # Mäuse, Tastaturen/Mäuse/Pointings, parent category
    "headphones": {"112529"},          # Kopfhörer & Headsets
    "monitors": {"80053"},             # Monitore (verified Browse category, 2026-10-05)
    "vr": {"190066"},                  # VR-Headsets
    "vr_headsets": {"190066"},         # VR-Headsets
}

EBAY_DEVICE_CATEGORY_IDS = {
    "phones": "9355",          # Handys & Smartphones / Cell Phones & Smartphones
    "smart_watches": "178893",  # Smartwatches
    "consoles": "139971",       # Videospiel-Konsolen / Video Game Consoles
    "laptops": "177",          # Notebooks & Netbooks / Laptops & Netbooks
    "tablets": "171485",        # Tablets & eBook Readers
    "computers": "179",        # PC Desktops & All-in-Ones
    "headphones": "112529",    # Kopfhörer & Headsets / Headphones
    "vr_headsets": "190066",   # VR-Headsets / Virtual Reality Headsets
    # Without these, monitors/mice fell back to parent 58058 (Computers/Tablets)
    # and eBay returned empty / wrong catalog for dedicated monitor & mouse listings.
    "monitors": "80053",       # Monitore
    "mice": "23160",           # Mäuse / Mice
}


PHONE_HARD_ACCESSORY_WORDS = (
    "case", "cover", "protector", "tempered glass", "bumper", "magsafe",
    "funda", "fundas", "coque", "coques", "custodia", "custodie",
    "hoes", "hoesje", "hoesjes", "riemhoes", "riemhoesje",
    "etui", "étui", "tasche", "funda de cinturon", "etui ceinture",
    "carcasa", "carcasas", "protector de pantalla", "protecteur d'ecran",
    "pellicola protettiva", "schermprotector", "screenprotector",
    "cristal templado", "verre trempe", "vetro temprato",
    "pellicola vetro", "protection ecran",
    "shell case", "skin case", "lens film", "camera lens",
    "camera protector", "holster", "wallet case", "armor case",
    "armour case", "shockproof case", "hydrogel film", "privacy filter",
    "silicone case", "rubber case", "tpu case", "frameless cover",
    "screen protector", "protective film", "schutzfolie", "panzerglas",
    "glass film", "lens protector", "metal lens film", "stand case",
    "leather case", "gel skin", "charging cable", "usb-c", "usb c",
    "charger", "metal frame", "bracket", "hybridglas", "flexibleglass",
    "schutzglas", "hartglas", "displayfolie", "panzerfolie", "privacy",
    "datenschutz", "grizzglass", "hülle", "huelle", "hulle", "h?lle", "magcase",
    "clearcase", "klarsichtcase", "hardglass", "objektivschutz",
    "silverprotection", "silky matt", "3mk", "original display",
    "display defekt", "display gewechselt", "teildefekt", "icloud sperre",
    "wie besehen", "psn servern ausgeschlossen", "schaltgetriebe",
    "kabel", "cable", "ladekabel", "linse", "lens", "kameralinse",
    "glas", "glass", "deckel",
    "ladegerät", "ladegeraet", "lader", "netzteil", "netzlader", "schnellladegerät", "schnellladegeraet",
    "gürteltasche", "guerteltasche", "gürtelclip", "guertelclip", "handytasche", "handy-tasche", "schlaufe",
    "panzerglasfolie", "panzer-glasfolie", "schutz-folie", "schutzfolien", "panzerglasfolien",
    "kopfhörer", "kopfhoerer", "earphones", "headphones", "headset", "in-ear", "inear",
    # Accessory stands / pads / mounts
    "anti rutsch", "pad", "pads", "halterung", "holder", "stand", "mount", "handyhalterung",
    "car mount", "car holder", "unterlage",
    # Additional case / custom descriptors / brands
    "transparent", "tasche", "ledertasche", "gürteltasche", "gurteltasche", "schale",
    "ledercase", "lederhülle", "lederhuelle", "lederhulle", "silikonhülle", "silikonhuelle", "silikonhulle",
    "silicon case", "schutzhüllen", "schutzhuellen", "schutzhullen", "schutzh?llen",
    "handyhüllen", "handyhuellen", "handyhullen", "handyh?llen",
    "displayglas", "digitizer", "touch digitizer", "ersatzdisplay",
    "panzerfolie", "schutzglas", "glasfolie", "motiv", "design", "muster", "print",
    "displayschutz", "kameraschutz", "linsenschutz", "displayschutzfolie", "kameraschutzfolie",
    "displayschutzglas", "kameraschutzglas", "hardcover", "sto?fest", "stossfest", "dexnor", "spigen", "otterbox", "torras",
    "rhinoshield", "esr", "jetech", "elago", "ringke", "caseology", "ugreen", "anker", "belkin",
    "guscio", "sleeve", "pellicola", "pellicole",
    # Books, manuals, instructions
    "buch", "buecher", "bucher", "anleitung", "anleitungen", "manual", "manuals", "guide", "guides",
    "praxisbuch", "praxis-buch", "lesebuch", "lesebücher", "lesebuecher",
    # Stylus / Pens
    "spen", "s-pen", "s pen", "stylus", "stift", "stifte", "touchpen", "touch-pen", "touchstift", "touch-stift",
    # Screen protector plurals / variants
    "hartgläser", "hartglaeser", "gläser", "glaeser", "schutzgläser", "schutzglaeser",
    # Quadlock / rain covers
    "quadlock", "quad lock", "poncho",
    # Fashion case / case brands
    "guess", "karl lagerfeld", "lagerfeld", "uag", "speck", "presidio", "pitaka", "mous", "casetify", "urban armor gear", "urban armor", "nomad", "monarch pro", "monarch",
    # Spanish, French, Italian accessory terms
    "estuche", "estuches", "antigolpes", "portatarjetas", "magnetico", "anillo", "anillos", "bague",
    "soporte", "soportes", "supporto", "supporti", "antichoc", "anti-choc", "antiurto",
    "cargador", "cargadores", "chargeur", "chargeurs", "caricabatterie"
)

# HARD PART WORDS — these ALWAYS indicate a spare part / repair listing.
# No override possible. A title with "motherboard" or "digitizer" is never a phone for sale.
PHONE_HARD_PART_WORDS = (
    "display", "bildschirm", "screen", "oled",
    "lcd", "digitizer", "touch screen", "touchscreen", "displayeinheit",
    "reparatur", "reparaturservice", "serviceware", "pulled",
    "screen replacement",
    "screen assembly", "display assembly", "charging port", "back glass",
    "back cover", "housing", "spare part", "spare parts",
    "motherboard", "mainboard", "logic board", "flex cable", "flexkabel",
    "hauptplatine", "basisplatine", "earpiece", "vibrator", "sim tray",
    "ersatzteil", "ersatzteile", "modul", "module", "platine",
    "sim kartenfach", "kartenfach", "ringer", "buzzer",
    "replacement", "replacements", "sensor", "sensoren",
    "fingerprint", "fingerabdrucksensor",
    "signalkabel", "klingelton", "summer", "rückkamera", "rueckkamera",
    "kamera linse", "kartenleser", "mikrofonanschluss", "rückabdeckung",
    "rueckabdeckung", "anschlussplatine", "objektivabdeckung",
    "rückseite", "rueckseite", "akku rückseite",
    "empty box", "box only", "dummy", "mockup",
    "power-taste", "power taste", "powertaste", "lautstärketaste",
    "lautstaerketaste", "volume button", "power button",
    "lautstärkeregelungstaste", "lautstaerkeregelungstaste",
    "ein/aus taste", "ein-aus-taste", "seitentaste",
    "ladebuchse", "ladeanschluss",
    "hybridglass", "grizzglass", "paperscreen", "hydrofilm",
    "display kamera", "display+kamera", "tpu", "imak",
    "rueckcover", "rückcover",
    "box only", "empty box", "leere box", "nur box", "nur verpackung",
    "leerverpackung", "leere verpackung", "nur die box", "nur die verpackung",
    "nur ovp", "nur die ovp",
    # Middle frame, bezel, photography kits
    "middle frame", "mittelrahmen", "mitte rahmen", "bezel", "frame bezel",
    "central frame", "center frame", "mid frame", "inner frame",
    "cornice", "cornice centrale", "telaio", "telaio centrale",
    "marco intermedio", "placa bisel", "marco central", "bisel de marco",
    "replacement bezel", "displayrahmen", "rahmen", "photography kit",
    "photo kit", "fotografie-kit", "camera kit", "photography-kit",
    "photography set", "photography-set", "photo set", "photo-set", "fotografie set", "fotografie-set",
    "camera set", "camera-set",
    # Additional replacements / parts
    "ersatz", "abdeckung", "rückseitige", "rueckseitige", "schrauben",
    "halterung", "kleber", "klebestreifen", "klebepad",
    # Batteries / battery parts
    "akku", "battery", "batterie", "batteries",
    # Empty boxes / packaging variants
    "ovp leer", "leer ovp", "leere schachtel", "nur schachtel", "schachtel leer"
)

# SOFT ACCESSORY WORDS — these often appear in accessory listings but CAN also
# appear in real phone listings ("mit Zubehör", "Transparent Edition", "mit Case").
# Overridden by PHONE_STRONG_DEVICE_HINTS.
PHONE_SOFT_ACCESSORY_WORDS = (
    "hülle", "huelle", "handy hülle", "handyhuelle", "schutzfolie",
    "schutzhülle", "schutzhuelle", "schutz folie", "folie",
    "zubehör", "zubehoer",
    "etui", "wallet", "magnetic case", "stoßschutz",
    "stosschutz", "stoβfest", "stoßfest", "stossfest",
    "kratzfest",
    "lautsprecher", "kameraobjektiv",
    "usb port", "usb anschluss",
)

# Strong signals — in practice only appear in real phone listings.
# Used to override soft accessory words like 'case'/'cover'/'transparent' in titles such as
# 'Phone with case included Snapdragon 256GB' or 'RedMagic Transparent Edition'.
PHONE_STRONG_DEVICE_HINTS = (
    "unlocked", "snapdragon", "qualcomm",
    "imei", "phone only", "fully working",
    "gaming phone", "gaming-smartphone",
    "ohne simlock", "dual sim", "single sim", "esim",
    "global version", "global rom",
)

def _has_phone_storage(title_norm):
    """Check if title mentions phone storage capacity (128gb, 256gb, 512gb, 1tb).
    This is a strong signal that the listing is a phone, not an accessory."""
    return bool(re.search(r"\b(?:64|128|256|512|1024)\s*(?:gb|go)\b", title_norm) or
                re.search(r"\b[12]\s*tb\b", title_norm) or
                re.search(r"\b\d+\s*/\s*(?:64|128|256|512|1024)\s*(?:gb|go)\b", title_norm))


def _has_phone_model_pattern(title_norm):
    """Check if title contains a recognizable phone model pattern.
    Used as additional override for soft accessory words."""
    patterns = (
        r"\biphone\s*\d{2}\s*pro",
        r"\bgalaxy\s*s\d{2}",
        r"\boneplus\s+\d{1,2}",
        r"\boneplus\s+ace",
        r"\bpixel\s+\d",
        r"\b(?:red\s*magic|redmagic)\s*\d{1,2}",
        r"\bnubia\s+z\d+[a-z]?",
        r"\bsamsung\s+.*\bultra\b",
    )
    return any(re.search(p, title_norm) for p in patterns)


def _title_leads_with_phone_model(title_norm):
    """Check if the title STARTS with a phone model (first 40 chars).
    This distinguishes 'Samsung Galaxy S24 Ultra 5G Mit Zubehör' (phone)
    from 'Hülle für Samsung Galaxy S24 Ultra' (accessory, caught by 'für' rule).
    """
    # Check if a phone model appears in the first ~40 characters
    prefix = title_norm[:45]
    patterns = (
        r"^(?:apple\s+)?iphone\s*\d{2}",
        r"^(?:samsung\s+)?(?:galaxy\s+)?s\d{2}",
        r"^oneplus\s+(?:\d{1,2}|ace)",
        r"^(?:google\s+)?pixel\s+\d",
        r"^(?:zte\s+)?(?:nubia\s+)?(?:red\s*magic|redmagic)\s*\d{1,2}",
        r"^(?:zte\s+)?nubia\s+(?:z\d+[a-z]?|focus)",
        r"^(?:neu|new)[\s!]*(?:zte\s+)?nubia",
        r"^(?:neu|new)[\s!]*(?:samsung|apple|oneplus|google)",
    )
    return any(re.search(p, prefix) for p in patterns)

# Weak signals — also frequently appear in accessory titles as
# compatibility hints ('Case for X 5G phone', 'Glass for 256GB model',
# 'Cover for dual sim'). Used only to mark something as a probable phone
# when there is no accessory word at all.
PHONE_WEAK_DEVICE_HINTS = (
    "5g", "4g", "lte", "android",
    "sim free", "dual sim", "single sim", "esim",
    "global version", "global rom",
)

PHONE_DEVICE_HINTS = PHONE_STRONG_DEVICE_HINTS + PHONE_WEAK_DEVICE_HINTS

BAD_CONDITION_WORDS = (
    "konvolut", "konvolute", "defekt", "teildefekt", "displayschaden", "display gewechselt", "icloud sperre", "gesperrt",
    "funktioniert nicht", "nur box", "nur verpackung", "leere verpackung", "tauschen", "tausche", "tausch",
    "leerbox", "leerhuelle", "leerhülle", "empty box", "empty case", "nur ovp",
    "nur karton", "leerer karton", "schachtel leer", "leere schachtel",
    "psn servern ausgeschlossen", "von psn servern ausgeschlossen",
    "banned from psn servers", "nur ersatzteile", "ersatzteile reparatur",
    "als ersatzteile", "fuer ersatzteile",
    "for parts", "parts only", "spares repair", "not working",
    "als ersatzteil", "ersatzteil defekt", "for repair", "needs repair",
    "solo per pezzi", "per parti di ricambio", "non funzionante",
    "pour pieces", "pour pieces detachees", "ne fonctionne pas",
    "para piezas", "no funciona", "piezas recambio",
    "icloud lock", "icloud locked", "icloud bypass", "activation lock",
    "activationlock", "aktivierungssperre", "icloudsperre",
    # Broken / cracked screen
    "display riss", "displaybruch", "display gebrochen", "display gesprungen",
    "gesprungenes display", "gebrochenes display", "gerissenes display",
    "bildschirmbruch", "bildschirm gebrochen", "bildschirm gesprungen",
    "bildschirm riss", "cracked screen", "broken screen", "screen cracked",
    "cracked display", "broken display", "screen broken",
    "glas gebrochen", "glas gesprungen", "glas riss",
    "back glass broken", "glass cracked", "glass broken",
    "display defekt", "bildschirm defekt", "screen defect",
    "riss im display", "riss im bildschirm", "riss im glas",
    "sprung im display", "sprung im glas", "sprung im bildschirm",
    "mit riss", "mit sprung",
    # Cracked / damaged rear glass / housing (common DE seller phrasing)
    "beschaedigte rueckseite", "beschaedigter rueckseite", "beschaedigtes rueckseite",
    "beschaedigtes gehaeuse", "beschaedigter gehaeuse", "beschaedigtes gehaeuse",
    "rueckseite beschaedigt", "rueckseite gebrochen", "rueckseite gesprungen",
    "rueckseite riss", "riss in der rueckseite", "riss auf der rueckseite",
    "hinterglas", "rueckglas", "backglass gebrochen", "backglass gesprungen",
    "back glass cracked", "cracked back", "cracked rear", "shattered back",
    "gehaeuse gebrochen", "gehaeuse gesprungen", "gehaeuse riss",
    "trotz beschaedigter rueckseite", "trotz beschaedigtem gehaeuse",
    "rueckseite hat riss", "rueckseite hat risse", "rueckseite hat kratzer",
    # Water damage
    "wasserschaden", "water damage", "water damaged",
    "feuchtigkeitsschaden", "nass geworden",
    # Screen/Backcover lifted/loose
    "lifted screen", "screen lifted", "display lifted", "lifted display",
    "screen lifting", "display lifting", "screen loose", "display lose",
    "loose screen", "lose display", "display geloest",
    "backcover geloest", "back cover loose", "backcover loose",
    "rueckseite geloest", "display steht ab", "steht ab",
    "abstehendes display", "abstehend",
    # Display errors / lines / spots
    "displayfehler", "bildschirmfehler", "pixelfehler", "green line",
    "gruene linie", "grüne linie", "pink line", "white line", "streifen im display",
    "linien im display", "display streifen", "fleck im display", "flecken im display",
    "burn in", "burn-in", "burn ins", "burnins", "eingebranntes display", "eingebrannt", "schatten im display",
    "whitespot", "whitespots", "flecken", "fleck", "streifen", "linien"
)

# Conditions parsed from eBay's condition badge that should always be blocked.
# These are the lowercased condition strings from the HTML / API.
BAD_CONDITIONS = {
    "defekt", "als ersatzteile", "fuer ersatzteile", "for parts or not working",
    "for parts", "not working", "for parts / not working",
    "als ersatzteile oder nicht funktionsfaehig",
    "ersatzteile", "parts only",
    "salvage",
    "solo per pezzi di ricambio o non funzionante",
    "per parti di ricambio o non funzionante",
    "pour pieces detachees ou ne fonctionne pas",
    "para piezas o no funciona",
}

KNOWN_BAD_ITEM_IDS = {
    "366386077847",
    "326775074774",
    "206385453277",
}

KNOWN_BAD_SELLERS = {
    "talk-point-gmbh",
    "talk-point gmbh",
    "talk point gmbh",
}

REFURBISHED_CONDITION_WORDS = (
    "refurbished",
    "generaluberholt",
    "generalueberholt",
    "generalüberholt",
    "renewed",
    "reconditioned",
    "wiederaufbereitet",
)

CATEGORY_ACCESSORY_WORDS = {
    "computers": (
        "grafikkarte", "graphics card",
        "konfigurator", "configurator", "konfigurierbar", "configurable",
        "zusammenstellen", "configure your", "wunsch pc", "wunschpc",
        "build to order", "bto", "selbst zusammenstellen",
        "waehle deine", "waehlbar", "individuell",
    ),
    "monitors": (
        "wandhalterung", "halterung", "halterungen", "adapter", "netzteil",
        "pied", "standfuss", "standfuß", "staender", "stand base", "standbase", "wall mount", "mount", "vesa",
    ),
    "headphones": (
        "scharnier", "halterung", "kopfbuegel", "kopfbügel", "speaker horn",
        "driver part", "schutzhülle", "schutzhuelle", "hülle", "huelle",
        "case", "cover", "sweat cover", "silikon", "abdeckung", "ersatzteil",
        "ersatzteile", "ersatz teile", "part", "zubehoer", "zubehör",
        "ohrpolster", "audio kabel", "kabel", "3.5mm", "kopfband", "hinge",
        "lautsprecher", "gehörschützer", "gehoerschuetzer", "ohrenschützer",
        "ohrenschuetzer", "storage bag", "replacement earpads", "earpads",
        "travel ready", "protective case", "kühlgel", "kuehlgel", "lautsprechertreiber",
        "kopfhoererbuegel", "kabelanschluss", "drahtanschluss", "12-pin",
        "kopfbügel abdeckung", "kopfbuegel abdeckung", "stirnband abdeckung",
        "schaumstoff", "einlagen", "polster paar", "nur ohrpolster",
        "foam earpad", "ear cushions", "pads pair", "earmuff", "earmuffs",
        "ear muff", "ear muffs", "gehoerschuetzer", "gehoerschutz",
    ),
    "vr_headsets": (
        "lens protector", "protector cover", "controller stand", "halterung",
        "dock", "zubehoer", "zubehör", "silikonring", "gurte", "kabel",
        "link kabel", "battery strap", "strap", "cover", "controllergriffe",
        "loading station", "hardcase", "tasche", "tragetasche", "bobo",
        "griffaufsätze", "griffaufsaetze", "headstrap", "handschlaufe",
        "kompatibel", "sin bateria", "activity-schlaufen", "touch plus-controller",
        "golfschläger", "golfschlaeger", "aufsatz", "lentes", "graduadas",
        "ladestantion", "ladestation", "woojer", "weste", "facial interface",
        "myopie", "kurzsichtig", "controller links", "controller rechts",
        "wireless dongle", "dongle", "trackstraps", "trackstrap",
        "ersatzteile", "reparatur", "spi/iic", "spi5253",
    ),
    "consoles": (
        "controller", "dualsense", "dualshock", "joycon", "joy-con",
        "ladestation", "charging station", "headset", "remote player",
        "portal", "playstation portal", "ps portal",
        "skin", "aufkleber", "sticker", "decal",
        "standfuss", "standfuß", "stand", "vertical stand",
        "kamera", "camera", "ps vr", "psvr",
        "tastatur", "keyboard", "maus", "mouse",
        "hdmi kabel", "hdmi cable", "usb kabel",
        "ssd", "festplatte", "hard drive", "m.2",
        "faceplates", "faceplate", "cover plate",
        "thumb grip", "thumbstick", "analog stick", "fightstick", "fight stick", "arcade stick",
        "lenkrad", "steering wheel", "racing wheel",
        "lüfter", "luefter", "fan", "cooling fan", "cooler", "kühler", "kuehler", "cooling system",
        "staubschutz", "dust plug", "dust cover", "dustproof", "schmutzschutz",
        "tasche", "case", "bag", "tragetasche", "carrying case", "travel bag",
        "wandhalterung", "wall mount", "halterung", "mount", "bracket",
        "netzkabel", "stromkabel", "netzteil", "power cable", "power cord", "power supply",
    ),
    "laptops": (
        "parts", "ersatzteil", "ersatzteile", "displayschaden", "netzteil",
        "ladegerät", "charger", "tastatur", "keyboard", "akku", "battery",
        "tasche", "hülle", "huelle", "case",
        # Screen/chassis assemblies sold as spare (compat title names the laptop).
        "baugruppe", "baugruppen", "komplettbaugruppe",
        "displaybaugruppe", "lcd baugruppe", "lcd-schirm", "lcd schirm",
        "schirm komplett", "komplett montage", "komplettmontage",
        "display montage", "displaymontage", "screen assembly",
        "display assembly", "lcd assembly", "panel assembly",
        "nur display", "nur bildschirm", "nur schirm", "only screen",
        "ersatzdisplay", "ersatz bildschirm", "replacement screen",
        "replacement display", "digitizer", "touch digitizer",
    ),
    "mice": (
        "shell", "tastenflächen", "tastenflaechen", "tasten", "buttons", "button", "clicker",
        "ladedock", "dock", "charging dock", "lade-dock", "charger", "kabel", "cable",
        "scroll rad", "scroll-rad", "scrollrad", "mausrad", "wheel", "scroll wheel", "mouse wheel",
        "pcb", "motherboard", "mainboard", "platine", "switch", "switches", "taster", "microswitch",
        "micro-switch", "grip", "grips", "griptape", "tape", "anti-slip", "skates", "feet",
        "glides", "mausfüße", "mausfuesse", "mouse skates", "mouse feet", "receiver", "dongle",
        "adapter", "akku", "battery", "ersatzteil", "ersatzteile", "spare part", "spare parts",
        "reparatur", "tasche", "case", "box", "mod", "3d print", "3d gedruckt", "gewicht", "weight",
        "ladekabel", "cover", "hülle", "huelle", "tastenfeld", "tastenkappe", "tastenkappen",
        "taste", "panel", "tastenset", "maustaste", "maustasten", "maus-taste", "maus-tasten",
        "skatez", "skate", "glide", "foot", "mausgleiter", "gleitpad", "gleitpads", "gleiter",
        "mausersatzfüße", "mausersatzfuesse", "ersatzfüße", "ersatzfuesse", "ersatzfuss", "ersatzfuß",
        "mauspad", "mauspads", "mousepad", "mousepads", "puck", "ladepuck", "lade-puck",
        # Merch / toys that mention the mouse name (e.g. Superstrike plushie)
        "plush", "plushie", "plusch", "pluschtier", "pluesch", "plueschtier",
        "kuscheltier", "stofftier", "spielzeug", "toy", "mascot", "maskottchen",
    ),
}

CATEGORY_HARD_PART_WORDS = {
    "headphones": (
        "scharnier", "halterung", "kopfbuegel", "kopfbügel", "speaker horn",
        "driver part", "abdeckung", "ersatzteil", "ersatzteile", "ersatz teile", "part",
        "ohrpolster", "kopfband", "hinge", "lautsprecher", "replacement earpads", "earpads",
        "lautsprechertreiber", "kopfhoererbuegel", "kabelanschluss", "drahtanschluss", "12-pin",
        "kopfbügel abdeckung", "kopfbuegel abdeckung", "stirnband abdeckung",
        "schaumstoff", "einlagen", "polster paar", "nur ohrpolster",
        "foam earpad", "ear cushions", "pads pair", "earmuff", "earmuffs",
        "ear muff", "ear muffs", "gehoerschuetzer", "gehoerschutz", "schrauben",
        "reparaturteil", "slider", "aussenpanel", "außenpanel", "kopfbandschieber", "kopfbuegelschieber", "schwenkgelenk", "schwenkscharnier",
    ),
    "vr_headsets": (
        "lens protector", "gurte", "strap", "controllergriffe", "aufsatz", "lentes",
        "graduadas", "facial interface", "myopie", "kurzsichtig", "controller links",
        "controller rechts", "wireless dongle", "dongle", "trackstraps", "trackstrap",
        "ersatzteile", "reparatur", "spi/iic", "spi5253",
    ),
    "consoles": (
        "skin", "aufkleber", "sticker", "decal", "standfuss", "standfuß", "stand",
        "vertical stand", "kamera", "camera", "tastatur", "keyboard", "maus", "mouse",
        "hdmi kabel", "hdmi cable", "usb kabel", "ssd", "festplatte", "hard drive", "m.2",
        "faceplates", "faceplate", "cover plate", "thumb grip", "thumbstick", "analog stick",
        "lenkrad", "steering wheel", "racing wheel", "lüfter", "luefter", "fan",
        "cooling fan", "cooler", "kühler", "kuehler", "cooling system", "staubschutz",
        "dust plug", "dust cover", "dustproof", "schmutzschutz", "wandhalterung",
        "wall mount", "halterung", "mount", "bracket", "netzkabel", "stromkabel",
        "netzteil", "power cable", "power cord", "power supply",
    ),
    "laptops": (
        "parts", "ersatzteil", "ersatzteile", "netzteil", "ladegerät", "charger",
        "tastatur", "keyboard", "akku", "battery",
        # Hard block: spare display assemblies (Zenbook title + "LCD-Schirm Komplett Baugruppe").
        "baugruppe", "baugruppen", "komplettbaugruppe",
        "displaybaugruppe", "lcd baugruppe", "lcd-schirm", "lcd schirm",
        "schirm komplett", "komplett montage", "komplettmontage",
        "display montage", "displaymontage", "screen assembly",
        "display assembly", "lcd assembly", "panel assembly",
        "nur display", "nur bildschirm", "nur schirm", "only screen",
        "ersatzdisplay", "ersatz bildschirm", "replacement screen",
        "replacement display", "digitizer", "touch digitizer",
    ),
    "mice": (
        "shell", "tastenflächen", "tastenflaechen", "tasten", "buttons", "button",
        "clicker", "ladedock", "dock", "charging dock", "lade-dock", "charger", "kabel",
        "cable", "scroll rad", "scroll-rad", "scrollrad", "mausrad", "wheel",
        "scroll wheel", "mouse wheel", "pcb", "motherboard", "mainboard", "platine",
        "switch", "switches", "taster", "microswitch", "micro-switch", "grip", "grips",
        "griptape", "tape", "anti-slip", "skates", "feet", "glides", "mausfüße",
        "mausfuesse", "mouse skates", "mouse feet", "receiver", "dongle", "adapter",
        "akku", "battery", "ersatzteil", "ersatzteile", "spare part", "spare parts",
        "reparatur", "mod", "3d print", "3d gedruckt", "gewicht", "weight", "ladekabel",
        "cover", "tastenfeld", "tastenkappe", "tastenkappen", "taste", "panel",
        "tastenset", "maustaste", "maustasten", "maus-taste", "maus-tasten",
        "skatez", "skate", "glide", "foot", "mausgleiter", "gleitpad", "gleitpads", "gleiter",
        "mausersatzfüße", "mausersatzfuesse", "ersatzfüße", "ersatzfuesse", "ersatzfuss", "ersatzfuß",
        "mauspad", "mauspads", "mousepad", "mousepads", "puck", "ladepuck", "lade-puck",
        "plush", "plushie", "plusch", "pluschtier", "pluesch", "plueschtier",
        "kuscheltier", "stofftier", "spielzeug", "toy", "mascot", "maskottchen",
    ),
}

# Words that indicate a listing is a GAME, not a console.
# Used for console category searches to filter out game-only listings.
# NOTE: Only use words that NEVER appear in console edition names.
# "ghost of", "last of us" etc. can be console limited editions!
CONSOLE_GAME_WORDS = (
    "spiel", "spiele", "game", "games", "videospiel", "videospiele", "video game",
    "steelbook", "steelbox", "steel book",
    "digital code", "download code", "gutschein", "voucher",
    "ps plus", "playstation plus", "ps now", "ea play",
    "remastered", "remake",
    "fifa", "call of duty", "cod", "gta", "fortnite",
    "assassin", "god of war",
    "ratchet", "returnal", "demon souls", "demons souls",
    "gran turismo", "final fantasy", "resident evil",
    "hogwarts", "elden ring", "diablo", "cyberpunk",
    "dragon ball", "fighterz", "fighter z",
    "hell is us", "astro bot", "stellar blade",
    "mortal kombat", "tekken", "street fighter",
    "nba", "madden", "fc 24", "fc 25", "fc24", "fc25", "ea sports",
)

# Strong signals that a listing IS a console (not a game or accessory)
CONSOLE_DEVICE_HINTS = (
    "konsole", "console", "spielekonsole", "spielkonsole",
    "heimkonsole", "digital edition", "disc edition",
    "disk edition", "blu-ray", "blu ray",
    "825 gb", "825gb",
    "cfi-", "cuh-",
    "inkl. controller", "mit controller", "with controller",
    "originalverpackt",
    "mit laufwerk", "mit cd", "cd laufwerk",
    "bundle konsole", "konsolen bundle",
)

SHORT_QUERY_WORDS = {"lg", "pc", "ti", "vr", "wh"}

LAPTOP_DEVICE_HINTS = (
    "laptop", "notebook", "ultrabook", "vivobook", "zenbook", "rog", "tuf",
    "thinkpad", "ideapad", "legion", "omen", "victus", "xps", "latitude",
    "inspiron", "alienware", "razer blade", "blade", "aorus", "gigabyte",
    "msi", "katana", "stealth", "creator", "predator", "nitro", "aspire",
    # Galaxy Book / Acer Swift titles often omit the word "laptop" entirely.
    "galaxybook", "galaxy book", "galaxy book4", "galaxybook4",
    "macbook", "chromebook", "surface laptop", "surface book",
    "swift", "travelmate", "extensa", "yoga", "thinkbook",
    "pavilion", "envy", "elitebook", "probook", "zbook",
    "vostro", "precision", "zephyrus", "strix", "matebook", "magicbook",
    "acer", "lenovo", "asus",
)

PC_DEVICE_HINTS = (
    "gaming pc", "desktop pc", "pc system", "komplett pc", "komplettpc",
    "mini pc", "mini-pc", "minipc",
    "gaming rechner", "rechner", "desktop", "computer", "workstation",
    "tower", "system", "setup", "windows", "win11", "win10", "ryzen",
    "core i", " i5", " i7", " i9", "ram", "ssd",
)


def _search_identity(search_or_query):
    if isinstance(search_or_query, dict):
        raw = " ".join(str(search_or_query.get(k) or "") for k in ("id", "query", "display_name"))
    else:
        raw = str(search_or_query or "")
    return _normalize(raw)


def _search_intent(search_or_query):
    ident = _search_identity(search_or_query)
    if not ident:
        return None
    requested = _normalize(search_or_query.get("query") or "") if isinstance(search_or_query, dict) else ident
    mouse_model = re.search(r"\b(?:superlight|gpx)\s*(?:2|ii)(c)?\b(?:[\s-]+(dex|se)\b)?", requested)
    if mouse_model:
        compact = bool(mouse_model.group(1))
        dex = mouse_model.group(2) == "dex"
        se = mouse_model.group(2) == "se"
        model = "superlight 2" + ("c" if compact else "") + (" dex" if dex else " se" if se else "")
        return {"kind": "superlight_2_dex" if dex else "superlight_2", "query": "logitech " + model,
                "display_name": "logitech " + model, "category": "mice", "compact": compact, "se": se}
    if "32gs95" in ident or "27gx790a" in ident or "lg ultragear oled" in ident:
        return {
            "kind": "lg_ultragear_oled",
            # Clean eBay _nkw — parentheses OR groups zero out monitor results.
            "query": "lg ultragear oled 480hz",
            "display_name": "LG UltraGear OLED",
            "category": "monitors",
        }
    if (
        "g60sf" in ident
        or "ls27fg602" in ident
        or "ls27fg604" in ident
        or (
            "odyssey" in ident
            and "g6" in ident
            and ("500hz" in ident or "500 hz" in ident or re.search(r"\b500\b", ident))
        )
        or ("samsung odyssey oled g6" in ident)
    ):
        return {
            "kind": "samsung_odyssey_oled_g6",
            # No (G60SF, LS27FG602) in _nkw — eBay treats that as near-empty.
            "query": "samsung odyssey oled g6 500hz",
            "display_name": "Samsung Odyssey OLED G6 500Hz",
            "category": "monitors",
        }
    if "superlight" in ident and "dex" in ident:
        return {
            "kind": "superlight_2_dex",
            "query": "logitech superlight 2 dex",
            "display_name": "logitech superlight 2 dex",
            "category": "mice",
        }
    if "superlight" in ident and "2" in ident and "dex" not in ident:
        return {
            "kind": "superlight_2",
            "query": "logitech superlight 2",
            "display_name": "logitech superlight 2",
            "category": "mice",
        }
    if "ult wear" in ident or "ult900" in ident or re.search(
        r"\bsony\s+ult\b", ident
    ):
        return {
            "kind": "sony_ult_wear",
            "query": "sony ult wear",
            "display_name": "Sony ULT Wear",
            "category": "headphones",
        }
    if re.search(r"\b4050\b", ident) and "oled" in ident:
        return {
            "kind": "rtx_oled_laptop",
            "query": "4050 oled",
            "gpu": "4050",
            "category": "laptops",
            "details_can_satisfy": True,
        }
    if re.search(r"\b4060\b", ident) and "oled" in ident:
        return {
            "kind": "rtx_oled_laptop",
            "query": "4060 oled",
            "gpu": "4060",
            "category": "laptops",
            "details_can_satisfy": True,
        }
    if "vivobook" in ident and "14x" in ident and "oled" in ident:
        return {
            "kind": "vivobook_14x_oled_3050",
            "query": "asus vivobook 14x oled",
            "display_name": "asus vivobook 14x oled",
            "category": "laptops",
            "details_can_satisfy": True,
        }
    if re.search(r"\b4080\b", ident) and _has_term(ident, "pc"):
        return {
            "kind": "gpu_pc",
            # Clean _nkw — parentheses OR-groups scramble eBay (same as monitors).
            "query": "4080 pc",
            "gpu": "4080",
            "category": "computers",
        }
    if re.search(r"\b5070\s*ti\b|\b5070ti\b", ident) and _has_term(ident, "pc"):
        return {
            "kind": "gpu_pc",
            # Live check 2026-08-15: `_nkw=5070+ti+pc&_sacat=0` finds auctions
            # and ~1450€ BIN that `(pc, rechner, …)` + `_sacat=179` misses.
            "query": "5070 ti pc",
            "gpu": "5070ti",
            "category": "computers",
        }
    if "superstrike" in ident:
        return {
            "kind": "superstrike",
            "query": "logitech superstrike",
            "display_name": "PRO X 2 SUPERSTRIKE",
            "category": "all",
        }
    return None


def _matches_samsung_odyssey_g6_500hz(text_norm):
    """True for Odyssey OLED G6 500Hz (G60SF / LS27FG602 / LS27FG604), not 360Hz G60SD."""
    t = text_norm or ""
    if re.search(r"\bg60sf\b", t) or re.search(r"\bls27fg60[24][a-z0-9]*\b", t):
        return True
    # Explicit non-500Hz sibling models without a 500Hz claim
    if re.search(r"\b(?:g60sd|g61sd|ls27dg60[12]|ls27dg61)\b", t) and not re.search(
        r"\b500\s*hz\b|\b500hz\b", t
    ):
        return False
    has_odyssey_g6 = ("odyssey" in t and re.search(r"\bg6\b", t)) or re.search(
        r"\bodyssey\s*oled\s*g6\b", t
    )
    has_500 = re.search(r"\b500\s*hz\b|\b500hz\b", t) is not None
    return bool(has_odyssey_g6 and has_500)


def _matches_lg_ultragear_oled_480(text_norm):
    """LG UltraGear OLED 480Hz — model codes OR ultragear+oled+480."""
    t = text_norm or ""
    # Independently inspected 227242702853 advertises 480Hz for a 27GX700A.
    # LG specifies 280Hz. Compare the first device model, not a later comparison.
    model = re.search(r"\b\d{2}(?:gs|gx)\d{2,3}[a-z]{1,2}\b", t)
    if model and model.group(0) == "27gx700a":
        return False
    # LG's 32GS94UX and 32GX870A/B also support 480Hz in Full HD dual mode.
    if model and re.fullmatch(r"32gs95[a-z]{1,2}|32gs94ux|27gx790a|32gx870[ab]", model.group(0)):
        return True
    has_ug = "ultragear" in t or ("lg" in t and "oled" in t and "monitor" in t)
    has_480 = re.search(r"\b480\s*hz\b|\b480hz\b", t) is not None
    has_oled = "oled" in t
    return bool(has_ug and has_480 and has_oled)


def _matches_superlight_2_mouse(title_norm, require_dex=False, require_se=False, require_compact=False):
    """Logitech G Pro X Superlight 2 (+ optional DEX). Not parts/dongle-only."""
    t = title_norm or ""
    model = re.search(r"\b(?:superlight|gpx)\s*(?:2|ii)(c)?\b(?:[\s-]+(dex|se)\b)?", t)
    if not model or bool(model.group(1)) != require_compact or (model.group(2) == "se") != require_se:
        return False
    has_dex = model.group(2) == "dex"
    if require_dex and not has_dex:
        return False
    if not require_dex and has_dex:
        # Plain Superlight 2 search must not pick DEX as "cheapest"
        return False
    # Block obvious parts already in category hard words; extra dongle/pcb noise
    if re.search(
        r"\b(?:dongle|receiver|empfaenger|empfänger|pcb|ersatzteil|skate|mausfuss|"
        r"mausfuß|shell|hot-swap|hot swap)\b",
        t,
    ) and not _is_device_bundle(t, "mice"):
        return False
    return True


def _matches_sony_ult_wear(title_norm):
    t = title_norm or ""
    if not (
        re.search(r"\bult\s*wear\b", t)
        or re.search(r"\bwh[\s-]*ult900n\b", t)
        or re.search(r"\bult900n\b", t)
    ):
        return False
    # Full headset hints beat spare-part flood on price_asc
    if re.search(
        r"\b(?:ohrpolster|earpad|ear pad|earpads|scharnier|halterung|batterie|akku|"
        r"ersatz|replacement|oem|gehäuse|gehaeuse|lautsprechergehäuse)\b",
        t,
    ):
        if not re.search(
            r"\b(?:kopfhoerer|kopfhörer|headphones|headset|over[\s-]*ear)\b", t
        ):
            return False
    return True


def _intent_query(search):
    if isinstance(search, dict) and search.get("_query_override"):
        return str(search["_query_override"]).strip()
    intent = _search_intent(search)
    if intent and intent.get("query"):
        return intent["query"]
    return (search.get("query", "") if isinstance(search, dict) else str(search or "")).strip()


def _search_query_variants(search):
    from query_variants import stored_aliases, phone_aliases
    if isinstance(search,dict) and search.get('_variant_child'):
        return [_intent_query(search)]
    raw=search.get('query','') if isinstance(search,dict) else str(search)
    explicit=stored_aliases(raw)
    if explicit:
        intent = _search_intent(search)
        if intent and intent.get('kind') == 'rtx_oled_laptop':
            explicit += [f"rtx {intent['gpu']} (aero,vivobook,spectre,yoga,xps,legion,proart)"]
        return list(dict.fromkeys(explicit))
    phone=phone_aliases(_intent_query(search))
    if phone:
        return list(dict.fromkeys(phone))
    intent = _search_intent(search)
    if not intent:
        return [_intent_query(search)]
    kind = intent.get("kind")
    if kind == "superstrike":
        return [
            "logitech superstrike",
            "logitech g pro x 2 superstrike",
            "logitech pro x2 superstrike",
            "superstrike lunar eclipse",
            "pro x 2 superstrike lunar eclipse",
        ]
    if kind == "samsung_odyssey_oled_g6":
        # Keep short: multi-variant bursts trip soft HTML empty responses.
        return [
            "samsung odyssey oled g6 500hz",
            "G60SF LS27FG602",
            "LS27FG604 500Hz",
        ]
    if kind == "lg_ultragear_oled":
        return [
            "lg ultragear oled 480hz",
            "27GX790A",
            "32GS95UE OLED",
        ]
    if kind == "superlight_2_dex":
        return [
            "logitech superlight 2 dex",
            "g pro x superlight 2 dex",
        ]
    if kind == "superlight_2":
        if intent.get("compact") or intent.get("se"):
            return [intent["query"], intent["query"].replace("logitech ", "logitech g pro x ")]
        return [
            "logitech g pro x superlight 2",
            "logitech superlight 2",
        ]
    if kind == "sony_ult_wear":
        return [
            "sony ult wear WH-ULT900N",
            "WH-ULT900N",
        ]
    if kind == "rtx_oled_laptop":
        gpu = intent.get("gpu") or "4050"
        return [
            f"rtx {gpu} oled laptop",
            f"rtx {gpu} oled notebook",
            f"laptop {gpu} oled",
            f"{gpu} oled",
            f"rtx {gpu} (aero,vivobook,spectre,yoga,xps,legion,proart)",
        ]
    return [_intent_query(search)]


def _intent_text_from_item_and_details(item=None, details=None):
    parts = []
    if item:
        parts.extend(str(item.get(k) or "") for k in ("title", "condition", "location"))
    if details:
        parts.append(_details_search_text(details))
        desc = details.get("description")
        if desc:
            parts.append(_clean_description(desc))
    return _normalize(" ".join(parts))


def _has_laptop_hint(text_norm):
    return any(_has_term(text_norm, w) for w in LAPTOP_DEVICE_HINTS)


def _has_pc_hint(text_norm):
    return any(w in text_norm for w in PC_DEVICE_HINTS)


def _declared_rtx_matches(text_norm, gpu):
    declared = re.findall(r"\brtx[\s®™]*(\d{4})(?:\s*(ti|super))?\b", text_norm)
    expected = re.fullmatch(r"(\d{4})(ti|super)?", str(gpu))
    if not declared or not expected:
        return True
    return any(number == expected.group(1) and (not expected.group(2) or modifier == expected.group(2)) for number,modifier in declared)


def _has_rtx_gpu(text_norm, gpu):
    if not _declared_rtx_matches(text_norm,gpu):
        return False
    if re.search(rf"\b(?:rtx\s*)?{re.escape(str(gpu))}\b", text_norm):
        return True
    # Seller shorthand, independently confirmed by the own RTX 4080 Super specs.
    return str(gpu) in ('4080','4080super') and re.search(r"\brtx[\s®™]*4080s\b",text_norm) is not None


def _has_rtx_5070_ti(text_norm):
    return _declared_rtx_matches(text_norm,'5070ti') and re.search(r"\b(?:rtx\s*)?5070\s*ti\b|\b(?:rtx\s*)?5070ti\b", text_norm) is not None


def _intent_prelim_matches_title(title_norm, search):
    intent = _search_intent(search)
    if not intent:
        return _query_matches_title(title_norm, search.get("query", ""))
    kind = intent["kind"]
    if kind == "lg_ultragear_oled":
        return _matches_lg_ultragear_oled_480(title_norm)
    if kind == "samsung_odyssey_oled_g6":
        return _matches_samsung_odyssey_g6_500hz(title_norm)
    if kind == "superlight_2_dex":
        return _matches_superlight_2_mouse(title_norm, require_dex=True, require_se=intent.get("se",False), require_compact=intent.get("compact",False))
    if kind == "superlight_2":
        return _matches_superlight_2_mouse(title_norm, require_dex=False, require_se=intent.get("se",False), require_compact=intent.get("compact",False))
    if kind == "sony_ult_wear":
        return _matches_sony_ult_wear(title_norm)
    if kind == "rtx_oled_laptop":
        gpu = intent["gpu"]
        if any(_has_term(title_norm, w) for w in ("grafikkarte", "graphics card", "gpu only", "nur gpu", "nur grafikkarte")):
            return False
        has_gpu = _has_rtx_gpu(title_norm, gpu)
        has_oled = _has_term(title_norm, "oled")
        # Strict path: GPU or OLED already on the SERP card.
        if (has_gpu or has_oled) and (_has_laptop_hint(title_norm) or has_gpu):
            return True
        # Soft path when details_can_satisfy: keep real laptop-looking cards
        # (e.g. GalaxyBook without "4050"/"OLED" in the title) so item-page
        # validation can accept GPU/OLED from description — and reject cracked
        # screens there too. Spare assemblies are dropped by hard part words.
        if intent.get("details_can_satisfy") and _has_laptop_hint(title_norm):
            return True
        return False
    if kind == "vivobook_14x_oled_3050":
        # M7400QC / M7400QA = RTX 3050 SKUs even when title omits "3050"
        return (
            "vivobook" in title_norm
            and ("14x" in title_norm or "m7400" in title_norm)
            and "oled" in title_norm
        )
    if kind == "gpu_pc":
        if intent["gpu"] == "5070ti":
            has_gpu = _has_rtx_5070_ti(title_norm)
        else:
            has_gpu = _has_rtx_gpu(title_norm, intent["gpu"])
        return has_gpu and _has_pc_hint(title_norm)
    if kind == "superstrike":
        return _matches_superstrike_mouse(title_norm)
    return True


def _known_oled_configuration(model_text, screen_text):
    # Lenovo PSREF Yoga Pro 7 14IMH9: 2880x1800 is OLED, whereas
    # 2560x1600 and 3072x1920 are IPS. Model name alone proves nothing.
    # Source: psref.lenovo.com/syspool/Sys/PDF/Yoga/Yoga_Pro_7_14IMH9/Yoga_Pro_7_14IMH9_Spec.PDF
    # Dell XPS 15 9530 (2023): 3456x2160 is OLED, 1920x1200 is LCD.
    # dell.com/support/manuals/de-ch/xps-15-9530-laptop/xps-15-9530-setup-and-specifications/display
    # ASUS official specifications: ProArt PX13 HN7306 / Vivobook N6506CU.
    # asus.com/us/laptops/for-creators/proart/proart-px13-hn7306/techspec/
    # press.asus.com/news/press-releases/asus-vivobook-pro-15-intel-core-ultra-nvidia-geforce-rtx/
    resolution = r"2880\s*(?:x|\*|×)?\s*1800" if re.search(r"\b14imh9\b|\b(?:px13\s*)?hn7306[a-z]*\b", model_text) else (
        r"2880\s*(?:x|\*|×)?\s*1620" if re.search(r"\bn6506cu\b", model_text) else
        r"3456\s*(?:x|\*|×)?\s*2160" if re.search(r"\bxps\s*15\s*9530\b", model_text) else None
    )
    if resolution is None:
        return False
    for match in re.finditer(r"\b(?:display(?:aufloesung)?|bildschirm|screen|aufloesung|resolution)\b[^.!?]{0,100}\b" + resolution + r"\b", screen_text):
        context=screen_text[max(0,match.start()-50):match.end()]
        if not re.search(r"\b(?:extern\w*|external|ausgang|output|hdmi|displayport)\b", context):
            return True
    return False


def _intent_details_match(search, item=None, details=None):
    intent = _search_intent(search)
    if not intent:
        return True
    text_norm = _intent_text_from_item_and_details(item, details)
    kind = intent["kind"]
    title_only = _normalize((item or {}).get("title") or "")
    if kind == "lg_ultragear_oled":
        return _matches_lg_ultragear_oled_480(text_norm) or _matches_lg_ultragear_oled_480(title_only)
    if kind == "samsung_odyssey_oled_g6":
        return _matches_samsung_odyssey_g6_500hz(text_norm) or _matches_samsung_odyssey_g6_500hz(title_only)
    if kind == "superlight_2_dex":
        return _matches_superlight_2_mouse(title_only or text_norm, require_dex=True, require_se=intent.get("se",False), require_compact=intent.get("compact",False))
    if kind == "superlight_2":
        return _matches_superlight_2_mouse(title_only or text_norm, require_dex=False, require_se=intent.get("se",False), require_compact=intent.get("compact",False))
    if kind == "sony_ult_wear":
        return _matches_sony_ult_wear(title_only or text_norm)
    if kind == "rtx_oled_laptop":
        own_model = _normalize((details or {}).get('title') or (item or {}).get('title') or '')
        panel_confirmed = _has_term(text_norm, "oled") or _known_oled_configuration(own_model,text_norm)
        return _has_rtx_gpu(text_norm, intent["gpu"]) and panel_confirmed and _has_laptop_hint(text_norm)
    if kind == "vivobook_14x_oled_3050":
        # 3050 text OR official ASUS model codes that are 3050-class
        if details:
            text_norm = _intent_text_from_item_and_details(None, details)
        has_gpu = (
            re.search(r"\b(?:rtx\s*)?3050\s*ti\b|\b(?:rtx\s*)?3050ti\b|\b(?:rtx\s*)?3050\b", text_norm) is not None
            or re.search(r"\bm7400q[ca]?\b", text_norm) is not None
        )
        return "vivobook" in text_norm and "oled" in text_norm and has_gpu
    if kind == "gpu_pc":
        has_gpu = _has_rtx_5070_ti(text_norm) if intent["gpu"] == "5070ti" else _has_rtx_gpu(text_norm, intent["gpu"])
        return has_gpu and _has_pc_hint(text_norm)
    if kind == "superstrike":
        # Use listing title only — description often mentions skates as related products.
        if title_only:
            return _matches_superstrike_mouse(title_only)
        return _matches_superstrike_mouse(text_norm)
    return True


def _is_plush_or_toy_title(title_norm):
    return bool(
        re.search(
            r"\b(?:plush(?:ie)?|plusch(?:tier)?|pluesch(?:tier)?|kuscheltier|stofftier|"
            r"mascot|maskottchen|pluschi)\b",
            title_norm or "",
        )
        or (
            _has_term(title_norm, "spielzeug")
            and not any(_has_term(title_norm, w) for w in ("maus", "mouse", "gaming"))
        )
    )


def _matches_superstrike_mouse(title_norm):
    """Real Superstrike mouse only — not merch plushies that say 'Mouse Plushie'."""
    t = title_norm or ""
    if _is_plush_or_toy_title(t):
        return False
    if re.search(r"\bmouse\s+plush|\bplush\s+mouse|\bmaus\s+plusch|\bplusch\s+maus\b", t):
        return False
    if "superstrike" not in t:
        return False
    if not ("logitech" in t or "pro x" in t):
        return False
    if _is_category_blocked_title(t, "mice", "superstrike"):
        return False
    return True


def _parse_redmagic_model(text_norm):
    """First RedMagic model glued to the brand: (num, is_s_variant, tier).

    Title like 'RedMagic 9S Pro ... (10 11 GPD)' → ('9', True, 'pro').
    Loose '11' later in the title must NOT count as the phone model.
    """
    m = re.search(
        r"\b(?:red\s*magic|redmagic)\s*(\d{1,2})\s*(s)?(?:\s*|-)?(pro|air)?\b",
        text_norm or "",
    )
    if not m:
        return None
    return (m.group(1), bool(m.group(2)), (m.group(3) or "").lower())


def _matches_redmagic_query(title_norm, query_norm):
    if any(
        _has_term(title_norm, w)
        for w in ("magic the gathering", "mtg", "karten", "orlando magic", "tablet")
    ):
        return False
    q = _parse_redmagic_model(query_norm)
    if not q:
        return _has_term(title_norm, "redmagic") or "red magic" in (title_norm or "")
    t = _parse_redmagic_model(title_norm)
    if not t:
        return False
    q_num, q_s, q_tier = q
    t_num, t_s, t_tier = t
    if t_num != q_num:
        return False
    # Redmagic 11 Pro ≠ Redmagic 11S Pro
    if q_s != t_s:
        return False
    if q_tier and t_tier and q_tier != t_tier:
        return False
    if q_tier == "pro" and t_tier != "pro":
        return False
    return True


def _query_words(query):
    words = []
    for word in re.findall(r"\w+", _normalize(query)):
        if len(word) >= 3 or word.isdigit() or any(ch.isdigit() for ch in word) or word in SHORT_QUERY_WORDS:
            words.append(word)
    return words


def _query_match_plan(query):
    """Return (required_words, alternative_groups) for eBay-style OR groups.

    A query such as "(playstation 5, ps5) pro" means:
    - require "pro"
    - require either "playstation 5" or "ps5"
    """
    query = query or ""
    alternative_groups = []

    def consume_group(match):
        raw_alts = [p.strip().strip("\"'") for p in match.group(1).split(",")]
        alts = []
        for alt in raw_alts:
            words = _query_words(alt)
            if words:
                alts.append(words)
        if len(alts) > 1:
            alternative_groups.append(alts)
            return " "
        if len(alts) == 1:
            return " ".join(alts[0])
        return " "

    remainder = re.sub(r"\(([^()]*)\)", consume_group, query)
    return _query_words(remainder), alternative_groups


def _query_matches_title(title_norm, query):
    query_norm = _normalize(query)
    # RedMagic model must sit next to the brand — bare "11" later in the title
    # (compat list / chipset) is not a match for "Redmagic 11 Pro".
    if "redmagic" in query_norm or "red magic" in query_norm:
        return _matches_redmagic_query(title_norm, query_norm)
    required_words, alternative_groups = _query_match_plan(query)
    if required_words and not all(_has_query_word(title_norm, w) for w in required_words):
        return False
    for alternatives in alternative_groups:
        if not any(all(_has_query_word(title_norm, w) for w in alt) for alt in alternatives):
            return False
    return True


def _has_query_word(title_norm, word):
    if word == "redmagic":
        return _has_term(title_norm, "redmagic") or "red magic" in title_norm
    # DualSense Gamepad is the pad, not a miss for query «dualsense controller».
    if word == "controller" and _has_term(title_norm, "gamepad"):
        return True
    if word == "gamepad" and _has_term(title_norm, "controller"):
        return True
    if word in ("ti", "super", "xt"):
        # GPU titles are often written as "5070ti"/"4070super"/"7900xt".
        if re.search(rf"\b\d{{3,4}}\s*{re.escape(word)}\b", title_norm):
            return True
    if word.isdigit():
        return re.search(rf"\b{re.escape(word)}(?:[a-zA-Z]+)?(?:gb|go|tb)?\b", title_norm) is not None
    return _has_term(title_norm, word)


def _sort_code(filters):
    if "sort_code" in filters:
        return filters.get("sort_code")
    sort_map = {
        "newest": "10",
        "price_asc": "15",
        "price_desc": "12",
        # eBay: Zeit — zuerst endende Angebote. The only order that puts a lot
        # in its last minutes on page 1.
        "ending_soon": "1",
    }
    return sort_map.get(filters.get("sort"), "10")


def _category_id(value):
    value = str(value or "all")
    if value.isdigit():
        return value
    return EBAY_CATEGORY_IDS.get(value, "")


def _phone_model_aspect_params(query_norm):
    """Return eBay phone model aspect params for obvious model searches."""
    model = None
    pixel = re.search(r"\b(?:google\s+)?pixel\s+(\d+[a-z]?)(?:\s+(pro|xl|fold))?\b", query_norm)
    if pixel:
        parts = [pixel.group(1)]
        if pixel.group(2):
            parts.append(pixel.group(2).upper() if pixel.group(2) == "xl" else pixel.group(2).title())
        model = "Google Pixel " + " ".join(p.upper() if p == "xl" else p for p in parts)

    iphone = re.search(
        r"\b(?:apple\s+)?iphone\s+(\d{1,2})(?:\s+(pro\s+max|pro|plus|mini|e))?\b",
        query_norm,
    )
    if iphone:
        parts = [iphone.group(1)]
        if iphone.group(2):
            parts.append(" ".join(part.title() for part in iphone.group(2).split()))
        model = "Apple iPhone " + " ".join(parts)

    galaxy = re.search(
        r"\b(?:samsung\s+)?galaxy\s+((?:s|z|a)\d{1,2})(?:\s+(ultra|plus|fe|edge|fold|flip))?\b",
        query_norm,
    )
    if galaxy:
        parts = [galaxy.group(1).upper()]
        if galaxy.group(2):
            parts.append(galaxy.group(2).title())
        model = "Samsung Galaxy " + " ".join(parts)

    if not model:
        return None

    # eBay aspect values in search URLs are encoded once inside the parameter,
    # then encoded again as part of the query string.
    return {
        "Modell": requests.utils.quote(model),
        "_dcat": EBAY_DEVICE_CATEGORY_IDS.get("phones") or "9355",
    }


def _host_chain_for_search(search):
    filters = search.get("filters", {}) or {}
    if EBAY_MARKETPLACE_ID == "EBAY_DE" or filters.get("category") == "phones":
        return ["ebay.de"]
    return _EBAY_HOST_CHAIN[:]


def _has_term(title_norm, term):
    term_norm = _normalize(term)
    if " " in term_norm or not re.fullmatch(r"[a-z0-9]+", term_norm):
        return term_norm in title_norm
    return re.search(rf"\b{re.escape(term_norm)}\b", title_norm) is not None


def _has_stickdrift_problem(title_norm):
    """True when title/description admits stick drift / abgenutzte Sticks (DE/EN).

    Does NOT match 'ohne Stickdrift' / 'kein Stick Drift' (seller claims no drift).
    Covers seller prose like «Der linke Stick hat einen leichten Stickdrift».
    """
    t = title_norm or ""
    # Explicit no-drift claims first
    if re.search(
        r"\b(?:ohne|kein|keine|keinen|nicht|no|without)\s+"
        r"(?:stick\s*-?\s*drift|stickdrift|stick\s*drift)\b",
        t,
    ):
        return False
    # bare / leichten / leichten Stickdrift
    if re.search(r"\b(?:stick\s*-?\s*drift|stickdrift)\b", t):
        return True
    # «hat einen … Stickdrift» / «mit leichtem Stickdrift»
    if re.search(
        r"\b(?:hat|mit|wegen|durch)\b.{0,40}\b(?:stick\s*-?\s*drift|stickdrift)\b",
        t,
    ):
        return True
    # DE wear phrasing from live cards: «Linker Stick abgenutzt»
    if re.search(
        r"\b(?:linker|rechter|linke[rn]?|rechte[rn]?)?\s*sticks?\s+"
        r"(?:abgenutzt|abgenutz|verschlissen|defekt|hakt|klemmt)\b",
        t,
    ):
        return True
    if re.search(r"\bsticks?\b.{0,24}\b(?:hakt|klemmt)\b", t):
        return True
    if re.search(
        r"\b(?:abgenutzte[rn]?|verschlissene[rn]?)\s+"
        r"(?:linker|rechter)?\s*sticks?\b",
        t,
    ):
        return True
    return False


def _is_hall_or_tmr_stick_upgrade(title_norm):
    """Hall Effect / TMR sticks on a complete DualSense are an upgrade, not spare sticks."""
    t = title_norm or ""
    pad = re.search(
        r"\b(?:dualsense|dual\s*sense|dualshock|dual\s*shock|gamepad|controller)\b",
        t,
    )
    hall = re.search(
        r"\b(?:hall\s*-?\s*effect|hall\s*-?\s*effekt|halleffekt|tmr)\b",
        t,
    )
    return bool(pad and hall)


def _is_dock_exclude_word(word):
    compact = _normalize(word or "").replace(" ", "").replace("-", "")
    return compact in {
        "ladestation",
        "doppelladestation",
        "chargingstation",
        "chargingdock",
        "ladedock",
        "ladegeraet",
    }


def _exclude_word_hits(title_norm, word):
    """exclude_words match, but stickdrift-family respects ohne/kein negation."""
    w = _normalize(word or "")
    if not w:
        return False
    if w in _normalized_bad_condition_words():
        return _has_term(_strip_negated_condition_terms(title_norm), w)
    if w in (
        "stickdrift",
        "stick drift",
        "stick-drift",
        "stick_drift",
        "drift",
    ) or "stickdrift" in w.replace(" ", "").replace("-", ""):
        return _has_stickdrift_problem(title_norm) and _has_term(title_norm, word)
    # DualSense + Ladestation is the pad, not a dock-only listing.
    if _is_dock_exclude_word(w) and _controller_bundle_keeps_pad(title_norm):
        return False
    # Hall Effect / TMR on a complete pad are an upgrade, not a stop-word hit.
    if w in (
        "stick", "sticks", "hall", "hallpi", "halleffekt", "effect", "effekt", "tmr"
    ) and _is_hall_or_tmr_stick_upgrade(title_norm):
        return False
    return _has_term(title_norm, word)


def _is_phone_device_title(title_norm):
    if any(_has_term(title_norm, w) for w in PHONE_DEVICE_HINTS):
        return True
    if re.search(r"\bnubia\s+(?:z\d+[a-z]?|focus|red\s*magic)\b.*\bultra\b", title_norm):
        return True
    if re.search(r"\biphone\s+\d{2}\s+pro\s+max\b", title_norm):
        return True
    if re.search(r"\b(?:samsung\s+)?(?:galaxy\s+)?s\d{2}\s+ultra\b", title_norm):
        return True
    if re.search(r"\b(?:oneplus\s+(?:\d{1,2}|ace)|google\s+pixel\s+\d|pixel\s+\d)\b", title_norm):
        return True
    if re.search(r"\b(?:red\s*magic|redmagic)\b.*\b\d{1,2}[a-z]?\b", title_norm):
        return bool(
            re.search(r"\b\d+\s*(?:gb|go|tb)\b", title_norm)
            or re.search(r"\b\d+\s*/\s*\d+\s*(?:gb|go|tb)\b", title_norm)
            or re.search(r"\b(?:red\s*magic|redmagic)\b.*\b\d{1,2}\s*(?:pro|air|s)\b", title_norm)
            or any(_has_term(title_norm, w) for w in ("smartphone", "phone", "5g", "snapdragon", "nubia", "zte", "unlocked", "gaming phone", "gaming-smartphone", "nfc"))
        )
    if re.search(r"\b\d+\s*(gb|go|tb)\b", title_norm):
        return True
    if re.search(r"\b\d+\s*(\+|/)\s*\d+\s*(gb|go|tb)\b", title_norm):
        return True
    return False


def _check_separator(sep):
    s = sep.lower()
    if "+" in s or "&" in s:
        return False
    words = re.findall(r"\b\w+\b", s)
    forbidden = {"mit", "with", "and", "und", "plus", "inkl", "inklusive", "including"}
    if any(w in forbidden for w in words):
        return False
    return True


def _matches_console_query_model(title_norm, query_norm):
    if "ps5" in query_norm and "pro" in query_norm:
        if _is_ps5_vr_only_title(title_norm) or _is_console_game_only_title(title_norm):
            return False
        patterns = [
            r"\b(?:ps5|playstation\s*5|ps\s*5)([^a-z0-9]{0,10})pro\b",
            r"\bpro([^a-z0-9]{0,10})(?:konsole|console|system)\b",
            r"\b(?:konsole|console|system)([^a-z0-9]{0,10})pro\b"
        ]
        accessory_pattern = re.compile(
            r"^(?:\s+|-)(?:wireless\s+|wired\s+|dualsense\s+|edge\s+|concept\s+)*(?:controller|gamepad|pad|lenkrad|wheel|joystick|headset|kopfhörer|kopfhoerer|tasche|case|hülle|huelle|skin|cover|stick|zubehör|zubehoer|halterung|mount|stand|ständer|staender)\b",
            re.IGNORECASE
        )
        for p in patterns:
            for match in re.finditer(p, title_norm):
                if _check_separator(match.group(1)):
                    pro_match = re.search(r"\bpro\b", match.group(0))
                    if pro_match:
                        pro_end_in_title = match.start() + pro_match.end()
                        remaining = title_norm[pro_end_in_title:]
                        if accessory_pattern.match(remaining):
                            continue
                    return True
        return False
    if "ps5" in query_norm and "slim" in query_norm:
        patterns = [
            r"\b(?:ps5|playstation\s*5|ps\s*5)([^a-z0-9]{0,10})slim\b",
            r"\bslim([^a-z0-9]{0,10})(?:konsole|console|system)\b",
            r"\b(?:konsole|console|system)([^a-z0-9]{0,10})slim\b"
        ]
        for p in patterns:
            for match in re.finditer(p, title_norm):
                if _check_separator(match.group(1)):
                    return True
        return False
    return True


def _is_ps5_pro_search_query(query_norm):
    return (
        "playstation 5 pro" in query_norm
        or "ps5 pro" in query_norm
        or (
            "pro" in _query_words(query_norm)
            and any(
                all(_has_query_word(" ".join(alt), w) for w in ("playstation", "5")) or "ps5" in alt
                for alt_group in _query_match_plan(query_norm)[1]
                for alt in alt_group
            )
        )
    )


def _has_ps5_pro_console_hint(title_norm):
    if _is_console_game_only_title(title_norm):
        return False
    if _is_accessory_product(title_norm, "consoles"):
        return False
    if any(term in title_norm for term in ("vr2", "psvr2", "ps vr2", "brille", "sense controller")):
        hardware_cue = re.search(
            r"\b(?:konsole|console|spielkonsole|cfi-\d|2\s*tb|1\s*tb|disc edition|digital edition|mit laufwerk|laufwerk)\b",
            title_norm,
        )
        if not hardware_cue:
            return False
    if re.search(r"\bcfi\s*[- ]?\s*7[01]\d{2}\b", title_norm):
        return True
    accessory = r"^(?:\s+|-)(?:wireless\s+|wired\s+|dualsense\s+|edge\s+|concept\s+)*(?:controller|gamepad|pad|lenkrad|wheel|joystick|headset|kopfhoerer|tasche|case|huelle|skin|cover|stick|zubehoer|halterung|mount|stand|staender)\b"
    for match in re.finditer(r"\b(?:ps5|playstation[\s®™]*5|ps\s*5)([^a-z0-9]{0,10})pro\b", title_norm):
        separator = match.group(1)
        if '+' not in separator and '&' not in separator and not re.search(accessory,title_norm[match.end():]):
            return True
    return False


def _is_ps5_console_and_vr_bundle(title_norm):
    """Detect PS5 console + VR headset bundles (e.g. 'PS5 + PSVR2 + Spiele').

    Returns True only when the title contains BOTH a VR term AND a standalone
    PS5/PlayStation 5 reference that is NOT part of the VR product name or a
    compatibility phrase like 'für PS5'.

    Two-pass cleaning strategy:
      1) preceded_pattern – removes 'PS5 VR2', 'Playstation 5 VR2' etc. where
         the console name is glued to the VR term.
      2) vr_pattern – removes remaining VR terms together with any trailing
         platform-compatibility list ('PS5 / PS5 Pro', 'for PS5', …).
    After both passes any surviving 'ps5' / 'playstation 5' token means a
    real console is present in the bundle.
    """
    if not any(term in title_norm for term in ("vr2", "psvr2", "ps vr2", "brille", "viewer", "sense controller")):
        return False

    clean_title = title_norm

    # Pass 1 – platform followed by VR term (e.g. "ps5 vr2", "playstation 5 vr brille")
    preceded_pattern = (
        r"\b(?:playstation\s*5|ps5|ps\s*5|ps4|playstation\s*4|ps\s*4)"
        r"\s*(?:pro)?"
        r"\s*(?:for|fuer|für|zu|compatible|kompatibel)?"
        r"\s*(?:ps\s*vr2|psvr2|vr2|vr\s*brille|vr-brille|vr\s*headset|vr-headset|brille|viewer)\b"
    )
    clean_title = re.sub(preceded_pattern, " ", clean_title)

    # Pass 2 – VR term optionally followed by platform-compatibility list
    vr_pattern = (
        r"\b(?:ps\s*vr2|psvr2|vr2|vr\s*brille|vr-brille|vr\s*headset|vr-headset"
        r"|vr\s*glasses|brille|viewer|sense\s*controller|virtual\s*reality)\b"
        r"(?:\s*(?:for|fuer|für|zu|compatible|kompatibel|system|brille|headset"
        r"|viewer|set|bundle|pack|edition|playstation\s*5|ps5|ps\s*5|ps4"
        r"|playstation\s*4|ps\s*4|pro|[\/\+,\s]))*"
    )
    clean_title = re.sub(vr_pattern, " ", clean_title)

    # Pass 3 – explicit compatibility phrases ("for PS5", "für PlayStation 5")
    clean_title = re.sub(
        r"\b(?:fuer|für|for|compatibel|kompatibel|zu|to)\b\s*\b(?:sony|playstation|ps5|ps\s*5)\b",
        " ", clean_title,
    )

    # If the cleaned title still mentions a PS5 console, it is a real bundle
    return bool(re.search(r"\b(?:playstation\s*5|ps5|ps\s*5)\b", clean_title))


def _has_ps5_console_hardware_hint(title_norm):
    if re.search(r"\b(?:playstation|ps5|ps\s*5).{0,30}\b(?:konsole|console|spielkonsole|system)\b", title_norm):
        return True
    if re.search(r"\b(?:konsole|console|spielkonsole|system).{0,30}\b(?:playstation|ps5|ps\s*5)\b", title_norm):
        return True
    if re.search(r"\b(?:2\s*tb|cfi-\d|digital edition|disc edition|disk edition|mit laufwerk|ohne disk laufwerk)\b", title_norm):
        return True
    if _is_ps5_console_and_vr_bundle(title_norm):
        return True
    return False


def _is_console_game_only_title(title_norm):
    if not any(_has_term(title_norm, w) for w in CONSOLE_GAME_WORDS):
        return False
    return not _has_ps5_console_hardware_hint(title_norm)


def _is_ps5_vr_only_title(title_norm):
    if not any(term in title_norm for term in ("vr2", "psvr2", "ps vr2", "brille", "viewer", "sense controller")):
        return False
    return not _has_ps5_console_hardware_hint(title_norm)


_IPHONE_PRO_MAX_CODES = {
    "15": {"a2849", "a3105", "a3108", "a3106"},
    "16": {"a3084", "a3295", "a3297", "a3296"},
    "17": {"a3257", "a3525", "a3527", "a3526"},
}  # https://support.apple.com/en-us/108044, checked 2026-10-05


_PHONE_MODEL_PATTERNS = (
    r"\biphone\s*(\d{1,2}|xs|xr|x|se)(?:\s*(pro\s*max|pro|max|plus|mini|air|se))?\b",
    r"\b(?:galaxy\s*)?s(\d{2})(?:\s*(ultra|plus|fe|edge))?\b",
    r"\bpixel\s*(\d+[a-z]?)(?:\s*(pro\s*xl|pro|xl|fold))?\b",
    r"\boneplus\s*(\d{1,2}[a-z]?|ace)(?:\s*(pro|ultra))?\b",
    r"\b(?:nubia\s+)?z\s*(\d{2})\s*([a-z]?)(?:\s*(ultra|pro))?(?:\s*(leading))?\b",
    r"\b(?:red\s*magic|redmagic)\s*(\d{1,2})\s*(s)?(?:\s*(pro|air))?\b",
)


def _phone_model_aspect_matches(value, query):
    value, query = _normalize(value), _normalize(query)
    if any(re.search(pattern, value) for pattern in _PHONE_MODEL_PATTERNS):
        return _matches_phone_query_model(value, query)
    generation = re.search(r"\biphone\s*(15|16|17)\s*pro\s*max\b", query)
    if not generation:
        return True
    return all(code in _IPHONE_PRO_MAX_CODES[generation.group(1)] for code in re.findall(r"\ba\d{4}\b", value))


def _phone_chipset_matches(value, query):
    pro = re.search(r"\biphone\s*(15|16|17)\s*pro\b", _normalize(query))
    if pro:
        # Apple specifications: support.apple.com/en-us/111828, /121032,
        # apple.com/am/iphone-17-pro/specs/ (checked2026-10-07).
        expected = {'15':'17','16':'18','17':'19'}[pro.group(1)]
        chip = re.search(r"\b(?:apple\s+)?a(\d{1,2})(?:\s*(pro|bionic))?\b", _normalize(value))
        return not chip or (chip.group(1) == expected and chip.group(2) == 'pro')
    if not re.search(r"\bs25\s*edge\b", _normalize(query)):
        return True
    # Samsung specifies Snapdragon 8 Elite globally for Galaxy S25 Edge:
    # https://news.samsung.com/uk/meet-the-samsung-galaxy-s25-edge-an-engineering-marvel-of-new-slim-hardware-innovation
    value = _normalize(value)
    if re.search(r"\b(?:exynos|mediatek|dimensity|bionic)\b", value):
        return False
    chip = re.search(r"\bsnapdragon\s*(\d+)(?:\s*(elite|gen\s*\d+))?\b", value)
    return not chip or (chip.group(1) == '8' and chip.group(2) in (None, 'elite'))


def _phone_model_number_matches(value, query):
    """Code fields can abbreviate a family (S25); explicit conflicts still fail."""
    value, query = _normalize(value), _normalize(query)
    for pattern in _PHONE_MODEL_PATTERNS:
        actual, wanted = re.search(pattern,value), re.search(pattern,query)
        if actual and wanted:
            return all(not a or a.replace(' ','') == (b or '').replace(' ','')
                       for a,b in zip(actual.groups(),wanted.groups()))
    return _phone_model_aspect_matches(value,query)


def _phone_description_purpose_confirmed(description):
    own = _normalize(_clean_description(description or ''))
    # 307191399998: the short seller body only inventories spare parts.
    # That does not independently establish that a whole phone is supplied.
    parts_inventory = re.search(r"\bersatzteile\s+(?:sind\s+)?(?:alle\s+)?(?:parat|vorhanden|komplett)\b", own)
    if not parts_inventory:
        return True
    phone = r"(?:iphone|smartphone|telefon|handy|geraet)"
    supplied = re.search(rf"\b(?:lieferumfang|enthalten|verkaufe|verkauft\s+wird)\b[^.!?]{{0,80}}\b{phone}\b", own)
    functional = re.search(rf"\b{phone}\b[^.!?]{{0,70}}\b(?:funktioniert|funktionsfaehig|funktionstuechtig)\b", own)
    return bool(supplied or functional)


def _phone_specifications_match(title, description, query):
    q = _normalize(query)
    own_description = _normalize(_clean_description(description))
    if re.search(r"\b(?:typ|produkttyp|produktart|device\s+type|type)\s*:?\s*(?:notebook|laptop|desktop|gaming\s*pc|monitor|headphones|kopfhoerer)\b", own_description):
        return False
    # Samsung's official S24 Ultra specification lists 12GB for every variant.
    if re.search(r"\bs24\s*ultra\b|\bs25\s*edge\b", q) and re.search(r"\b(?:8|16)\s*gb\s*(?:ram|arbeitsspeicher)\b|\b(?:ram|arbeitsspeicher)\s*:?\s*(?:8|16)\s*gb\b", _normalize(title) + " " + own_description):
        return False
    declared_chips = re.findall(r"\b(?:prozessor|processor|chipsatz|chipset|cpu)\s*:\s*([^.!?]{1,70})", own_description)
    declared_chips += re.findall(r"\b(?:leistungsfaehig\w*|powerful)\s+((?:qualcomm\s+)?(?:exynos|snapdragon|dimensity|mediatek)[a-z0-9 +]*?)\s+(?:prozessor|processor)\b", own_description)
    if any(not _phone_chipset_matches(chip,q) for chip in declared_chips):
        return False
    if re.search(r"\biphone\s*(15|16|17)\s*pro\b", q):
        for chip in re.finditer(r"\b(?:apple\s+)?a\d{1,2}(?:\s*(?:pro|bionic))?\s*(?:chip(?:satz|set)?|processor|prozessor)\b", own_description):
            before = own_description[max(0,chip.start()-45):chip.start()]
            if re.search(r"\b(?:als|than|vs|versus|gegenueber|compared\s+to|vergleich\s+zu)\s+(?:(?:dem|the)\s+)?$", before):
                continue
            if not _phone_chipset_matches(chip.group(),q):
                return False
    generation = re.search(r"\biphone\s*(15|16|17)\s*pro\s*max\b", _normalize(query))
    if not generation:
        return True
    generation = generation.group(1)
    own_title = re.split(r"\b(?:mit|with|inkl(?:usive)?|incl(?:uded|uding)?|ink|bundle)\b", _normalize(title), maxsplit=1)[0]
    allowed = {256, 512, 1024, 2000, 2048} if generation == "17" else {256, 512, 1024}
    for gb, tb in re.findall(r"\b(64|128|256|512|1024|2000|2048)\s*gb\b|\b([12])\s*tb\b", own_title):
        if (int(gb) if gb else int(tb) * 1024) not in allowed:
            return False
    return True


def _matches_phone_query_model(title_norm, query_norm):
    if not _phone_specifications_match(title_norm, "", query_norm):
        return False
    # Parse the number next to the device name, not iOS 17 / A17 / 17 cm.
    q = re.sub(r"(?<=\d)\s*\+", " plus", query_norm)
    t = re.sub(r"(?<=\d)\s*\+", " plus", title_norm)
    # 198671049337 is an XS conversion; 407252002537 explicitly sells a replica.
    if "iphone" in q and re.search(r"\b(?:android|nachbau|replica|replika|clone|klon|umbau|conversion|converter)\b", t):
        return False
    for pattern in _PHONE_MODEL_PATTERNS:
        wanted = re.search(pattern, q)
        if not wanted:
            continue
        actual = re.search(pattern, t)
        signature = lambda m: tuple((v or "").replace(" ", "") for v in m.groups())
        if not actual or signature(wanted) != signature(actual):
            return False
        break
    # Brand cross-exclusion check (e.g. reject HTC U11 matching Google Pixel 5)
    query_brands = set()
    for b in ("pixel", "google", "iphone", "apple", "samsung", "galaxy", "oneplus", "nubia", "redmagic", "red magic", "xiaomi", "redmi", "huawei", "honor", "oppo", "realme", "sony", "xperia", "motorola", "moto", "lg", "htc", "nokia", "asus", "rog"):
        if b in query_norm:
            query_brands.add(b)
            if b == "pixel": query_brands.add("google")
            if b == "google": query_brands.add("pixel")
            if b == "iphone": query_brands.add("apple")
            if b == "apple": query_brands.add("iphone")
            if b == "galaxy": query_brands.add("samsung")
            if b == "samsung": query_brands.add("galaxy")
            if b in ("redmagic", "red magic", "nubia"):
                query_brands.update({"redmagic", "red magic", "nubia"})

    all_brands = {"pixel", "google", "iphone", "apple", "samsung", "galaxy", "oneplus", "nubia", "redmagic", "red magic", "xiaomi", "redmi", "huawei", "honor", "oppo", "realme", "sony", "xperia", "motorola", "moto", "lg", "htc", "nokia", "asus", "rog"}
    competing_brands = all_brands - query_brands

    for b in competing_brands:
        if re.search(rf"\b{re.escape(b)}\b", title_norm):
            return False

    if "nubia" in query_norm and "ultra" in query_norm:
        return re.search(r"\bnubia\s+(?:z\s*\d+[a-z]?|z\d+[a-z]?|focus(?:\s*\d+)?|red\s*magic)\b.*\bultra\b", title_norm) is not None
    iphone = re.search(r"\biphone\s*(\d{2})\s*pro\s*max\b", query_norm)
    if iphone:
        return re.search(rf"\biphone\s*{iphone.group(1)}\s*pro\s*max\b", title_norm) is not None
    galaxy = re.search(r"\b(?:samsung\s+)?(?:galaxy\s+)?s(\d{2})\s+ultra\b", query_norm)
    if galaxy:
        model = galaxy.group(1)
        if f"no s{model}" in title_norm:
            return False
        other_models = [m for m in re.findall(r"\bs(\d{2})\b", title_norm) if m != model]
        if other_models and "/" in title_norm:
            return False
        return re.search(rf"\b(?:samsung\s+)?(?:galaxy\s+)?s{model}\s*ultra\b", title_norm) is not None
    oneplus = re.search(r"\boneplus\s+(\d{1,2}|ace)\b", query_norm)
    if oneplus:
        return re.search(rf"\boneplus\s+{re.escape(oneplus.group(1))}\b", title_norm) is not None
    pixel = re.search(r"\bpixel\s+(\d[a-z]?)\b", query_norm)
    if pixel:
        return re.search(rf"\b(?:google\s+)?pixel\s+{re.escape(pixel.group(1))}\b", title_norm) is not None
    if "redmagic" in query_norm or "red magic" in query_norm:
        return _matches_redmagic_query(title_norm, query_norm)
    return True


def _is_smartwatch_search_query(query_norm):
    watch_terms = ("watch", "smartwatch", "smart-watch", "applewatch", "fitbit", "garmin")
    return any(term in query_norm for term in watch_terms)


def _is_phone_search_query(query_norm):
    # Monitors / TVs that contain "samsung" must NOT be treated as phones
    # (wrong floor 120€ + phone filters → empty Odyssey G6 stats).
    if any(
        w in (query_norm or "")
        for w in (
            "odyssey",
            "monitor",
            "g60sf",
            "ls27fg",
            "ultragear",
            "27gx790",
            "32gs95",
            "fernseher",
            " television",
            " tv ",
        )
    ) or re.search(r"\b(?:g6|g7|g8|g9)\b.*\b(?:hz|oled|qhd|uhd)\b", query_norm or ""):
        return False
    phone_terms = (
        "iphone", "galaxy", "oneplus", "nubia", "red magic", "redmagic", "pixel",
        "xiaomi", "motorola", "realme", "huawei", "oppo", "xperia",
    )
    # "samsung" alone is ambiguous (phones vs monitors) — only with phone model hints
    if "samsung" in (query_norm or ""):
        if re.search(
            r"\b(?:galaxy|s\d{2}|a\d{2}|z\s*fold|z\s*flip|note\s*\d+)\b",
            query_norm or "",
        ):
            return True
        return False
    if any(term in query_norm for term in phone_terms):
        return True
    return re.search(r"\b(?:samsung\s+)?s\d{2}\s+ultra\b", query_norm) is not None


def _is_controller_pad_query(query_norm):
    q = query_norm or ""
    return bool(re.search(r"\bdual\s*sense\b|\bdualsense\b|\bdual\s*shock\b|\bdualshock\b", q))


def _controller_accessory_label(title_norm):
    t = title_norm or ""
    pairs = (
        ("doppelladestation", "зарядка"),
        ("ladestation", "зарядка"),
        ("lade station", "зарядка"),
        ("charging station", "зарядка"),
        ("charging dock", "зарядка"),
        ("ladedock", "зарядка"),
        ("lade-dock", "зарядка"),
        ("lade dock", "зарядка"),
        ("ladegeraet", "зарядка"),
        ("charger", "зарядка"),
        ("tragetasche", "чехол"),
        ("schutztasche", "чехол"),
        ("aufbewahrungstasche", "чехол"),
        ("tasche", "чехол"),
        ("schutzhuelle", "чехол"),
        ("silikonhuelle", "чехол"),
        ("huelle", "чехол"),
        ("hulle", "чехол"),
        ("skin", "скин"),
        ("aufkleber", "наклейка"),
    )
    hit = None
    for word, label in pairs:
        if _has_accessory_term(t, word) or word in t:
            hit = label
            break
    if not hit:
        return None
    if _controller_bundle_keeps_pad(t):
        return None
    return hit


def _controller_bundle_keeps_pad(title_norm):
    if not re.search(r"\b(?:dualsense|dual\s*sense|dualshock|dual\s*shock|gamepad)\b", title_norm):
        return False
    if not re.search(r"\b(?:inkl|mit|with|bundle)\b|(?<=\s)\+(?=\s)", title_norm):
        return False
    acc = re.search(r"ladestation|charging station|ladedock|charging dock|tasche|hulle|huelle", title_norm)
    pad = re.search(r"dualsense|dualshock|gamepad|controller", title_norm)
    return bool(pad and acc and pad.start() < acc.start())


def _wrong_controller_generation(title_norm, query_norm):
    t = title_norm or ""
    q = query_norm or ""
    q_ds = bool(re.search(r"\bdual\s*sense\b|\bdualsense\b", q))
    q_ds4 = bool(re.search(r"\bdual\s*shock\b|\bdualshock\b", q))
    t_ps4 = bool(re.search(r"\bps4\b|playstation\s*4|dualshock\s*4|dual\s*shock\s*4", t))
    t_ps5 = bool(re.search(r"\bps5\b|playstation\s*5", t))
    t_ds = bool(re.search(r"\bdualsense\b|dual\s*sense", t))
    t_ds4 = bool(re.search(r"\bdualshock\b|dual\s*shock", t))
    if q_ds and not q_ds4:
        if t_ps4 and not t_ps5:
            return "PS4"
        if t_ds4 and not t_ds:
            return "DualShock"
    if q_ds4 and not q_ds:
        if t_ds and not t_ds4:
            return "DualSense"
        if t_ps5 and not t_ps4:
            return "PS5"
    return None


def _controller_console_bundle_label(title_norm):
    """PS5 Konsole + DualSense is not a DualSense listing. Pad SKU is CFI-ZCT*."""
    t = title_norm or ""
    if re.search(r"\bcfi[- ]?zct", t):
        return None
    console_sku = bool(re.search(r"\bcfi[- ]?(?:1|12)\d|\bcuh[- ]?\d", t))
    console_word = any(
        w in t
        for w in (
            "konsole", "spielekonsole", "spielkonsole", "heimkonsole",
            "disc edition", "disk edition", "digital edition", "blu-ray", "blu ray",
        )
    ) or bool(re.search(r"\bconsole\b", t))
    if not console_sku and not console_word:
        return None
    pad = re.search(r"dualsense|dual\s*sense|dualshock|dual\s*shock|gamepad|controller", t)
    fuer = re.search(r"\b(?:fuer|fur|for)\b", t)
    if pad and fuer and pad.start() < fuer.start():
        return None
    return "приставка"


def _is_console_search_query(query_norm):
    console_terms = ("playstation", "ps5", "ps4", "xbox", "nintendo switch", "switch konsole")
    return any(term in query_norm for term in console_terms)


def _is_laptop_search_query(query_norm):
    laptop_terms = ("laptop", "notebook", "macbook", "thinkpad", "ultrabook", "chromebook")
    return any(term in query_norm for term in laptop_terms) or (
        "oled" in query_norm and re.search(r"\b(?:rtx\s*)?(?:3050|4050|4060)\b", query_norm)
    )


def _is_tablet_search_query(query_norm):
    tablet_terms = ("ipad", "galaxy tab", "tablet", "lenovo tab")
    return any(term in query_norm for term in tablet_terms)



def _has_accessory_term(title_norm, term):
    term_norm = _normalize(term)
    if " " in term_norm or not re.fullmatch(r"[a-z0-9]+", term_norm):
        return term_norm in title_norm

    words = re.findall(r'[a-z0-9]+', title_norm)
    for w in words:
        # German condition compounds (including common `tustand` spelling)
        # describe the device; they are not a phone stand.
        if term_norm == "stand" and re.search(r"(?:zu|tu)stands?$", w):
            continue
        if term_norm == "kabel" and w.startswith("kabellos"):
            continue
        if w == term_norm:
            return True
        if len(w) > len(term_norm):
            if w.endswith(term_norm):
                return True
            if w.startswith(term_norm):
                return True
    return False


def _is_phone_accessory_title(title_norm):
    service_patterns = (
        r"\b(?:unlock|entsperr|freischalt)[a-z]*\b.{0,30}\bservice\b",
        r"\bservice\b.{0,30}\b(?:unlock|entsperr|freischalt)[a-z]*\b",
        r"\bicloud\b.{0,30}\b(?:unlock|entsperr|freischalt)[a-z]*\b",
    )
    if any(re.search(pattern, title_norm) for pattern in service_patterns):
        return True

    """Detect titles that are clearly accessories or spare parts.

    Hard parts (battery/lcd/digitizer/motherboard/...) are always treated as accessory
    regardless of other signals — these are never sold as working phones.

    Soft accessory words (case/cover/glass/transparent/zubehör) CAN appear in
    real phone listings ("iPhone mit Case", "Transparent Edition", "mit Zubehör").
    These are only treated as accessory if there's NO strong device hint AND
    no phone storage capacity mentioned.

    Titles starting with "für" / "fuer" / "for" are always accessories.
    """
    # Titles starting with "für/fuer/for/voor/para/pour/per" are always accessories
    if re.match(r"^(?:fuer|für|for|voor|para|pour|per)\s+", title_norm):
        return True
    if re.match(r"^(?:original\s+|replacement\s+)?(?:\d{1,3}\s*%\s*)?(?:akku|battery|batterie|batteries)\b", title_norm):
        return True

    # Standalone bundle indicator checks
    is_bundle = re.search(r"\b(?:mit|and|inkl(?:usive)?|incl(?:uded|uding)?|ink|with|bundle)\b|(?<=\s)\+(?=\s)|(?<=\s)&(?=\s)", title_norm) is not None

    # Battery words can sometimes be description of battery health (e.g. "100% Akku")
    # rather than a replacement battery.
    battery_words = {"akku", "battery", "batterie", "batteries"}
    is_battery_health_desc = False
    if any(_has_accessory_term(title_norm, w) for w in battery_words):
        has_storage = re.search(r"\b\d+\s*(?:gb|go|tb)\b", title_norm) is not None
        has_health = re.search(r"\b\d{1,3}\s*%(?!\d)", title_norm) is not None or any(w in title_norm for w in ("zyklen", "cycles", "kapazität", "kapazitaet", "zustand", "health", "neu", "top", "gut"))
        health_label = r"(?:batteriekapazitaet|akkukapazitaet|akkuzustand|battery\s*health|akku|batterie|battery)"
        explicit_health = re.search(rf"\b\d{{1,3}}\s*%\s*{health_label}\b|\b{health_label}\s*:?\s*\d{{1,3}}\s*%", title_norm) is not None
        if has_storage and has_health or explicit_health and _title_leads_with_phone_model(title_norm):
            is_battery_health_desc = True

    # Hard parts — always accessory, no override possible
    hard_parts_to_check = [w for w in PHONE_HARD_PART_WORDS if not (is_battery_health_desc and w in battery_words)]
    has_hard_part = any(_has_accessory_term(title_norm, w) for w in hard_parts_to_check)
    if has_hard_part:
        if is_bundle and _title_leads_with_phone_model(title_norm):
            sep_pattern = re.compile(r"\b(?:mit|and|inkl(?:usive)?|incl(?:uded|uding)?|ink|with|bundle)\b|(?<=\s)\+(?=\s)|(?<=\s)&(?=\s)")
            m = sep_pattern.search(title_norm)
            if m:
                before_sep = title_norm[:m.start()]
                before_has_hard = any(_has_accessory_term(before_sep, w) for w in hard_parts_to_check)
                if before_has_hard:
                    return True
            return False
        return True

    # Soft part/accessory words and hard accessory words
    has_acc = any(_has_accessory_term(title_norm, w) for w in PHONE_HARD_ACCESSORY_WORDS + PHONE_SOFT_ACCESSORY_WORDS)
    if has_acc:
        category = None
        if category == "phones":
            protective_acc_words = (
                "case", "cover", "protector", "hülle", "huelle", "h?lle",
                "displayschutz", "screen protector", "schutzfolie", "panzerglas",
                "schutzglas", "displayfolie", "panzerfolie", "hardcover",
                "sto?fest", "stossfest", "shockproof", "bumper",
            )
            strong_phone_hint = (
                _has_phone_storage(title_norm)
                or any(_has_term(title_norm, w) for w in (
                    "smartphone", "handy", "phone", "5g", "gaming phone",
                    "ohne simlock", "dual sim", "single sim", "global version",
                    "global rom", "unlocked",
                ))
            )
            if any(_has_accessory_term(title_norm, w) for w in protective_acc_words) and not strong_phone_hint:
                return True
        if is_bundle and _title_leads_with_phone_model(title_norm):
            sep_pattern = re.compile(r"\b(?:mit|and|inkl(?:usive)?|incl(?:uded|uding)?|ink|with|bundle)\b|(?<=\s)\+(?=\s)|(?<=\s)&(?=\s)")
            m = sep_pattern.search(title_norm)
            if m:
                before_sep = title_norm[:m.start()]
                before_has_acc = any(_has_accessory_term(before_sep, w) for w in PHONE_HARD_ACCESSORY_WORDS + PHONE_SOFT_ACCESSORY_WORDS + PHONE_HARD_PART_WORDS)
                if before_has_acc:
                    return True
            return False
        return True

    return False


def _is_for_accessory_title(title_norm, query_norm, category):
    # Detect if listing is for an accessory by checking for target compatibility phrases (e.g. "for PS5")
    # if the main device keyword/model only appears after the "for" term (or not at all).
    for_patterns = re.compile(
        r"\b(?:fuer|für|f\?{1,3}r|for|voor|para|pour|per|geeignet\s+(?:fuer|für|f\?{1,3}r)|compatible\s*(?:with|to|con|avec)?|kompatib(?:el|le)\s*(?:mit|zu|fuer|für|f\?{1,3}r)?|compatibile\s*(?:con)?)\b",
        re.IGNORECASE
    )
    for_match = for_patterns.search(title_norm)
    if not for_match:
        return False

    for_start = for_match.start()
    before_part = title_norm[:for_start]

    # If before_part contains any known accessory/part word, and there is no bundle indicator,
    # then the model name in before_part was just part of the accessory description, so it IS an accessory.
    if category == "phones":
        has_acc = any(_has_accessory_term(before_part, w) for w in PHONE_HARD_ACCESSORY_WORDS + PHONE_SOFT_ACCESSORY_WORDS + PHONE_HARD_PART_WORDS)
        if has_acc:
            is_bundle = re.search(r"\b(?:mit|and|inkl|with|bundle)\b|(?<=\s)\+(?=\s)|(?<=\s)&(?=\s)", title_norm) is not None
            if not is_bundle:
                return True
    elif category == "consoles":
        console_words = CATEGORY_ACCESSORY_WORDS.get("consoles", ()) + CATEGORY_HARD_PART_WORDS.get("consoles", ())
        has_acc = any(_has_accessory_term(before_part, w) for w in console_words)
        if has_acc:
            is_bundle = re.search(r"\b(?:mit|and|inkl|with|bundle)\b|(?<=\s)\+(?=\s)|(?<=\s)&(?=\s)", title_norm) is not None
            if not is_bundle:
                return True

    if query_norm:
        if category == "consoles":
            if _matches_console_query_model(before_part, query_norm):
                return False
        elif category == "phones":
            if _matches_phone_query_model(before_part, query_norm):
                return False
        else:
            q_words = _query_words(query_norm)
            if q_words and all(_has_query_word(before_part, w) for w in q_words):
                return False
    else:
        # Fallback when query_norm is not provided (e.g. in some unit tests)
        if category == "consoles":
            if any(w in before_part for w in CONSOLE_DEVICE_HINTS):
                return False
            if re.search(r"\b(?:500|825|1000|1024)\s*(?:gb|go)\b", before_part):
                return False
            if re.search(r"\b[12]\s*tb\b", before_part):
                return False
            if re.search(r"\bcfi-\d", before_part) or re.search(r"\bcuh-\d", before_part):
                return False
        elif category == "phones":
            if any(w in before_part for w in PHONE_DEVICE_HINTS):
                return False
            if _has_phone_storage(before_part):
                return False
        elif category == "laptops":
            if any(w in before_part for w in ("laptop", "notebook", "macbook", "zenbook", "vivobook")):
                return False
        elif category == "headphones":
            if any(w in before_part for w in ("kopfhoerer", "kopfhörer", "headphones", "headset")):
                return False

    return True


_DISPLAY_PART_WORDS = r"(?:display|bildschirm|screen|oled|glas|glass|scheibe)"
_DISPLAY_REPAIR_WORDS = (
    r"(?:(?:aus)?getauscht|gewechselt|repariert|ersetzt|wechsel|wechseln|austausch"
    r"|bekommen|erneuert|reparatur|(?:aus)?getauschtes|gewechseltes|repariertes"
    r"|ersetztes|erneuertes)"
)
# "neu" alone only means a swapped screen when it sits *next to* the part.
_DISPLAY_NEW_WORDS = r"(?:neu|neue|neues|neuer|frisches)"
_DISPLAY_NEG = (
    r"(?<!wie\s)(?<!nicht\s)(?<!kein\s)(?<!keine\s)(?<!ohne\s)(?<!no\s)"
    r"(?<!not\s)(?<!without\s)(?<!nie\s)(?<!never\s)"
)


def _is_display_replacement(text_norm):
    """Detect display/screen/oled/glass/backglass replacements in title or description.

    "Display neu" on a phone means the screen was swapped. On an OLED device
    "neu" is just the condition: «LG Ultragear … 4K UHD OLED Gaming Monitor
    240Hz/480Hz - NEU» is a new monitor, and the old `oled .* neu` match ate the
    only live LG auction lot in the 2026-07-26 report (item 267738467047).
    So repair verbs may sit anywhere in the text, but the bare "neu" family has
    to be adjacent (one word apart at most) to the display word.
    """
    near = r"\W+(?:\w+\W+)?"
    patterns = (
        rf"\b{_DISPLAY_PART_WORDS}\b.*\b{_DISPLAY_NEG}{_DISPLAY_REPAIR_WORDS}\b",
        rf"\b{_DISPLAY_NEG}{_DISPLAY_REPAIR_WORDS}\b.*\b{_DISPLAY_PART_WORDS}\b",
        rf"\b{_DISPLAY_PART_WORDS}\b{near}{_DISPLAY_NEG}{_DISPLAY_NEW_WORDS}\b",
        rf"\b{_DISPLAY_NEG}{_DISPLAY_NEW_WORDS}\b{near}{_DISPLAY_PART_WORDS}\b",
    )
    return any(re.search(p, text_norm, re.IGNORECASE) for p in patterns)


# Categories where the panel IS the product — a "new OLED" there is a new device,
# never a replacement part.
_PANEL_IS_PRODUCT_CATEGORIES = ("monitors", "tvs")


def _is_display_replacement_description(text_norm):
    repair_words = "(?:aus)?getauscht|tauschen\\s+lassen|gewechselt|repariert|ersetzt|wechsel|wechseln|austausch|erneuert|reparatur"
    part = r"(?:display|bildschirm|screen|oled|glas|glass|scheibe|rueckseitenglas|rueckglas|hinterglas|backglass|back\s*glass|rear\s*glass)"
    p1 = rf"\b{part}\b[^.!?]{{0,80}}\b{_DISPLAY_NEG}(?:{repair_words})\b"
    p2 = rf"\b{_DISPLAY_NEG}(?:(?:aus)?getauschtes|gewechseltes|repariertes|ersetztes|erneuertes)\b[^.!?]{{0,80}}\b{part}\b"
    return bool(re.search(p1, text_norm, re.IGNORECASE) or re.search(p2, text_norm, re.IGNORECASE))


# Defect stems AFTER _normalize (ä→ae, ü→ue). Must match inflected DE forms:
# beschädigter/beschädigte/beschädigtes → beschaedigter/... not only exact "beschaedigt".
_DAMAGE_DEFECT_RE = (
    r"(?:beschaedig\w*|schaden|schaeden|beschaedigung(?:en)?"
    r"|damage|damaged|defect|defective"
    r"|gebrochen\w*|gesprungen\w*|gerissen\w*|kaputt"
    r"|riss(?:e|ig\w*)?|sprung|spruenge|sprünge|bruch|brueche|brüche"
    r"|crack(?:s|ed)?|absplitter\w*|gesplittert\w*|zerkratzt\w*|zerschrammt\w*)"
)
_DAMAGE_PART_RE = (
    r"(?:backcover|back\s*cover|rueckseite|rueckabdeckung|rueckglas|hinterglas"
    r"|rear\s*glass|back\s*glass|backglass|gehaeuse|gehäuse|housing|rahmen|frame"
    r"|display|bildschirm|screen|oled|glas|glass|scheibe|akkudeckel"
    r"|kamera|camera|linse|linsen|lens|frontglas|frontglass|displayglas|displayglass)"
)


def _has_damage_word(text_norm):
    """Title/description damage signal. text_norm must already be _normalize()'d."""
    if not text_norm:
        return False
    neg = r"(?<!ohne\s)(?<!kein\s)(?<!keine\s)(?<!keinen\s)(?<!nicht\s)(?<!no\s)(?<!without\s)(?<!not\s)"
    # Standalone defect (any inflected form)
    if re.search(rf"\b{neg}{_DAMAGE_DEFECT_RE}\b", text_norm, re.IGNORECASE):
        return True
    # Part near defect either order (covers "beschädigter Rückseite" and reverse)
    if re.search(
        rf"\b(?:{_DAMAGE_PART_RE})\b.{{0,60}}\b{neg}{_DAMAGE_DEFECT_RE}\b",
        text_norm,
        re.IGNORECASE,
    ):
        return True
    if re.search(
        rf"\b{neg}{_DAMAGE_DEFECT_RE}\b.{{0,60}}\b(?:{_DAMAGE_PART_RE})\b",
        text_norm,
        re.IGNORECASE,
    ):
        return True
    return False


def _is_accessory_product(title_norm, category):
    noun_and_part = {
        "consoles": r"(?:konsole|console|spielkonsole)\s+(?:covers?|case|skin|faceplates?|abdeckung)",
        "laptops": r"(?:laptop|notebook)\s+(?:tastatur|keyboard|akku|battery|ladegeraet|charger|netzteil)",
        "monitors": r"(?:monitor|bildschirm)\s+(?:[a-z0-9]*\d[a-z0-9]*(?:[ -][a-z])?\s+)?(?:netzteil|halterung|standfuss|staender|stand(?:\s*base)?|adapter)",
        "mice": r"(?:maus|mouse|superlight\s*(?:2c?|ii)(?:\s+(?:dex|se))?|superstrike)\s+(?:receiver|empfaenger|dongle|pcb|shell|switch|taster|skates?|feet|glides?|mausfuesse|mausgleiter|ersatzteil)",
        "headphones": r"(?:kopfhoerer|headphones|headset)\s+(?:ohrpolster|earpads?|ersatzbuegel|scharnier|hinge)",
        "vr": r"(?:vr\s+headset|vr\s+brille)\s+(?:headstrap|strap|kopfband|linsenschutz)",
        "vr_headsets": r"(?:vr\s+headset|vr\s+brille)\s+(?:headstrap|strap|kopfband|linsenschutz)",
    }.get(category)
    return bool(noun_and_part and re.search(rf"\b{noun_and_part}\b", title_norm))


def _is_device_bundle(title_norm, category):
    if _is_accessory_product(title_norm,category):
        return False
    if re.search(r"\b(?:fuer|for|voor|para|pour|per|kompatibel|compatible|fits)\b|\bf\s*\.\s*", title_norm):
        return False
    nouns = {
        "headphones": r"kopfhoerer|headphones|headset|(?:sony\s+)?wh[\s-]*1000[\s-]*xm\d+",
        "consoles": "konsole|spielkonsole|console|digital edition|disc edition",
        "laptops": "laptop|notebook|macbook|vivobook|zenbook",
        "mice": r"maus|mouse|gaming mouse|superlight\s*(?:2c?|ii)(?:\s+(?:dex|se))?|superstrike",
        "vr_headsets": "headset|vr brille", "vr": "headset|vr brille",
        "monitors": "monitor|bildschirm",
    }.get(category)
    if not nouns:
        return False
    device = re.search(rf"\b(?:{nouns})\b", title_norm)
    if not device:
        return False
    component = r"(?:ersatz\w*|spare|replacement|swivel|spindle|buckle|drehgelenk|scharnier|hinge|earpads?|ohrpolster|cover|case|tasche|kabel|cable|charger|netzteil|dock|controller|ssd|tastatur|keyboard|receiver|empfaenger|dongle|pcb)"
    if re.search(rf"\b{component}\b", title_norm[:device.start()]):
        return False
    if category == "headphones" and re.search(r"\b(?:ersatz\w*|spare|replacement|swivel|spindle|buckle|drehgelenk|scharnier|hinge)\b", title_norm):
        return False
    receiver_feature = category == "mice" and re.search(r"\b(?:maus|mouse)\b", title_norm) and re.search(r"\b(?:kabellos|wireless)\b.{0,25}\b(?:usb[- ]?)?(?:empfaenger|receiver)\b", title_norm)
    implicit_headphone = category == "headphones" and not re.search(r"\b(?:kopfhoerer|headphones|headset)\b", title_norm)
    connector = r"\b(?:mit|and|inkl|with|bundle)\b|(?<=\s)\+(?=\s)|(?<=\s)&(?=\s)"
    if implicit_headphone:
        connector = r"\|"
    headphone_case = category == 'headphones' and not implicit_headphone and re.search(
        r"\b(?:anc|wireless|bluetooth|ldac|noise\s*cancell?ing)\b.*\bcase\b", title_norm[device.end():])
    # Model may occur before the explicit noun; require a technical feature,
    # then verify in the own description that the device is included.
    if category == 'headphones' and not implicit_headphone:
        headphone_case = headphone_case or re.search(r"\b(?:anc|wireless|bluetooth|ldac|noise\s*cancell?ing)\b.*\b(?:kopfhoerer|headphones|headset)\b.*\bcase\b",title_norm)
    return bool(re.search(connector, title_norm[device.end():]) or receiver_feature or headphone_case)


@functools.lru_cache(maxsize=1)
def _normalized_bad_condition_words():
    return frozenset(_normalize(w) for w in BAD_CONDITION_WORDS)


@functools.lru_cache(maxsize=1)
def _negated_condition_pattern():
    words = set(_normalized_bad_condition_words())
    words.update(('kratzer','gebrauchsspuren','scratches','signs of wear','dead pixels','burn ins','burnins'))
    atom = '(?:' + '|'.join(re.escape(w) for w in sorted(words,key=len,reverse=True)) + r')\b'
    neg = r'(?:kein|keine|keinen|ohne|nicht|nichts|no|without|not)'
    adjective = r'(?:(?:sichtbar\w*|bekannt\w*|visible|known|sonst|sonstige\w*|andere\w*|any|other)\s+){0,2}'
    # Only explicit coordinated lists share the negation. "aber" and a bare
    # comma do not erase a subsequent real defect; double negations stay blocked.
    prefix = r'(?<!nicht )(?<!not )(?<!kein )(?<!keine )(?<!no )'
    return re.compile(prefix + rf'\b{neg}\s+{adjective}{atom}(?:\s+(?:oder|und|or|and|nor)\s+(?:{neg}\s+)?{adjective}{atom})*')


def _strip_negated_condition_terms(text_norm):
    text = _negated_condition_pattern().sub(' ',text_norm)
    # Samsung's cooling feature prevents burn-in; it does not admit an existing
    # fault. Remove only that exact prevention statement, keeping later defects.
    burn = r'(?:burn\s*ins?|einbrennen)'
    text = re.sub(rf'\b{burn}\s+(?:vermieden|verhindert)\s+werden(?:\s+koennen)?\b', ' ', text)
    return re.sub(rf'\b(?:prevent(?:s|ing)?|verhindert|vermeidet|schutz\s+(?:vor|gegen))\s+{burn}\b', ' ', text)


def _is_category_blocked_title(title_norm, category, query_norm=None):
    # Reuse the phone accessory classifier here, too: this helper is called
    # outside the main filter pipeline (including previews and diagnostics).
    # Previously "iPhone 16 Pro Max Display Ersatzteil" could return False
    # even though _is_phone_accessory_title correctly rejected it.
    if category == "phones" and _is_phone_accessory_title(title_norm):
        return True
    if _is_accessory_product(title_norm,category):
        return True
    condition_title = _strip_negated_condition_terms(title_norm)
    if any(_has_term(condition_title, w) for w in BAD_CONDITION_WORDS):
        return True
    if category not in _PANEL_IS_PRODUCT_CATEGORIES and _is_display_replacement(title_norm):
        return True
    if _has_damage_word(title_norm):
        return True
    # Check for screen/backcover lifting/loose/separation
    if re.search(r"\b(?:screen|display|backcover|glass|glas|rueckseite)\b.*\b(?:lifted|lifting|loose|geloest|steht\s+ab|lose|abgeloest|abgeht)\b", title_norm):
        return True
    if re.search(r"\b(?:lifted|lifting|loose|geloest|steht\s+ab|lose|abgeloest|abgeht)\b.*\b(?:screen|display|backcover|glass|glas|rueckseite)\b", title_norm):
        return True
    # Check for non-negated cracks/breakage/damage (e.g. "Glasbruch", "Riss", "gesprungen", "kaputt", "Bildschirmbruch")
    # Matches words ending in riss, risse, sprung, sprünge, bruch, brüche (like displayriss, glasbruch)
    # as long as they are not preceded by a negation (ohne, kein, no, etc.) and not kaufabbruch (ab)
    defect_pattern = re.compile(
        r"\b(?<!ohne\s)(?<!kein\s)(?<!keine\s)(?<!nicht\s)(?<!no\s)(?<!without\s)"
        r"(?:[a-z]*(?<!ab)(?:riss|risse|sprung|spruenge|sprünge|bruch|brüche|brueche)|gebrochen|gesprungen|kaputt)\b",
        re.IGNORECASE
    )
    if defect_pattern.search(title_norm):
        return True
    if _is_for_accessory_title(title_norm, query_norm, category):
        return True
    if category == "phones":
        protective_acc_words = (
            "case", "cover", "protector", "hülle", "huelle", "h?lle",
            "displayschutz", "screen protector", "schutzfolie", "panzerglas",
            "schutzglas", "displayfolie", "panzerfolie", "hardcover",
            "sto?fest", "stossfest", "shockproof", "bumper",
        )
        strong_phone_hint = (
            _has_phone_storage(title_norm)
            or any(_has_term(title_norm, w) for w in (
                "smartphone", "handy", "phone", "5g", "gaming phone",
                "ohne simlock", "dual sim", "single sim", "global version",
                "global rom", "unlocked",
            ))
        )
        if any(_has_accessory_term(title_norm, w) for w in protective_acc_words) and not strong_phone_hint:
            return True
    # Kopfbügel followed by the form factor describes a complete over-ear headset,
    # as independently confirmed on 366021140413. Damage checks use the original title.
    title_norm = re.sub(r"\b(?:kein|keine|keinen|ohne|no|without)\s+(?:box|ovp|verpackung|karton|originalverpackung)\b", " ", title_norm)
    if category == "laptops" and re.search(r"\brtx\s*\d{4}\b", title_norm) and not re.match(r"^(?:akku|battery)\b", title_norm):
        # A declared health percentage describes the laptop's own battery.
        # Replacement batteries, compatibility and actual defects stay blocked.
        title_norm = re.sub(r"\b(?:akku|battery)(?:\s*(?:zustand|health|kapazitaet))?\s*(?:ca\.?|approx\.?|about|:)?\s*\d{1,3}\s*%", " ", title_norm)
    if category == "headphones" and re.search(r"\b(?:kopfhoerer|headphones|headset)\b.*\bkopfbuegel\b.*\b(?:over[- ]ear|on[- ]ear|bluetooth|faltbar|anc)\b", title_norm):
        title_norm = re.sub(r"\bkopfbuegel\b", " ", title_norm)
    # Components are rejected unless explicitly supplied with the main device.
    hard_parts = CATEGORY_HARD_PART_WORDS.get(category, ())
    if any(_has_accessory_term(title_norm, w) for w in hard_parts) and not _is_device_bundle(title_norm, category):
        return True
    if _is_device_bundle(title_norm, category):
        return False

    acc_words = CATEGORY_ACCESSORY_WORDS.get(category, ())
    has_acc = any(_has_accessory_term(title_norm, w) for w in acc_words)
    if has_acc:
        # Check if the title starts with "fuer", "für", "for", "voor", "para", "pour", "per", "geeignet", "fits" -> always block
        if re.match(r"^(?:fuer|für|for|voor|para|pour|per|geeignet|fits)\s+", title_norm):
            return True
        # Check if this is a bundle (main device + accessory)
        is_bundle = re.search(r"\b(?:mit|and|inkl|with|bundle)\b|(?<=\s)\+(?=\s)|(?<=\s)&(?=\s)", title_norm) is not None
        if is_bundle:
            device_patterns = r"\b(?:sony|playstation|ps5|xbox|nintendo|switch|meta|quest|pico|oculus|logitech|razer|superlight|g pro|iphone|samsung|pixel|redmagic|nubia|laptop|notebook|macbook|vivobook|zenbook|asus|hp|lenovo|dell)\b"
            if re.search(device_patterns, title_norm):
                # Ensure no "for/fuer/etc" precedes the device name (which indicates it's an accessory for that device)
                if re.search(r"\b(?:fuer|für|for|compatibel|kompatibel|zu|to)\b.*\b(?:sony|playstation|ps5|xbox|nintendo|switch|meta|quest|pico|oculus|logitech|razer|superlight|g pro|iphone|samsung|pixel|redmagic|nubia|laptop|notebook|macbook|vivobook|zenbook|asus|hp|lenovo|dell)\b", title_norm):
                    return True  # Block!
                return False  # Do NOT block (it's a bundle)

        # BUNDLE OVERRIDE FOR CONSOLES
        if category == "consoles":
            # Pure accessory words to exclude from bypass
            pure_acc_words = (
                "tasche", "case", "bag", "tragetasche", "hülle", "huelle", "cover", "skin",
                "aufkleber", "sticker", "decal", "wandhalterung", "wall mount", "halterung",
                "mount", "bracket", "faceplate", "faceplates", "kabel", "cable", "luefter",
                "lüfter", "fan", "cooler", "standfuss", "standfuß", "vertical stand",
                "schutzfolie", "folie"
            )
            console_indicators = (
                "konsole", "console", "system", "digital edition", "disc edition", "2tb", "2 tb", "spielkonsole"
            )
            has_indicator = any(w in title_norm for w in console_indicators)
            has_pure_acc = any(w in title_norm for w in pure_acc_words)
            if has_indicator and not has_pure_acc:
                return False  # Do NOT block (it's a real console)

        return True  # Block accessory-only listings

    return False


def _effective_category(category, query_norm):
    if _is_controller_pad_query(query_norm):
        return "all"
    intent = _search_intent(query_norm)
    if intent and intent.get("category"):
        return intent["category"]
    if _is_smartwatch_search_query(query_norm):
        return "smart_watches"
    if _is_phone_search_query(query_norm):
        return "phones"
    if "sony wh" in query_norm or "sony ult wear" in query_norm:
        return "headphones"
    if any(w in query_norm for w in ("quest", "pico", "vive", "slimevr", "slime tracker", "full body tracking")):
        return "vr_headsets"
    if _is_console_search_query(query_norm):
        return "consoles"
    if _is_laptop_search_query(query_norm):
        return "laptops"
    if _is_tablet_search_query(query_norm):
        return "tablets"
    if _has_term(query_norm, "pc"):
        return "computers"

    if category and category != "all":
        return category
    return category


def _matches_category_query(title_norm, category, query_norm):
    """Check if a title matches the intent of the search query.

    Philosophy: PASS everything by default, BLOCK only confirmed garbage.
    Lazy sellers write short titles — we don't want to miss good deals.
    Accessories/parts are caught separately by _is_category_blocked_title.
    """
    if _is_controller_pad_query(query_norm):
        return _query_matches_title(title_norm, query_norm)
    if _has_term(query_norm, "pc"):
        # PC searches: block standalone GPUs and parts, pass everything else
        # A standalone GPU listing without any PC/system word is not what we want
        gpu_only = ("grafikkarte", "graphics card", "gpu only", "nur gpu", "nur grafikkarte")
        if any(_has_term(title_norm, w) for w in gpu_only):
            return False
        # Must have at least some hint it's a full system, not just a component
        pc_hints = (
            "gaming pc", "desktop pc", "high end pc", "high-end pc",
            "komplett", "computer", "workstation", "system", "setup",
            "omen", "predator", "orion", "alienware", "corsair one",
            "ryzen", "core i", " i7", " i9", " i5", "windows", "win11", "win10",
            "ram", "ssd", "tower", "gehaeuse",
        ) + PC_DEVICE_HINTS
        return any(term in title_norm for term in pc_hints)

    if re.search(r"\bquest\s*3\b", query_norm):
        return re.search(r"\bquest\s*3\b", title_norm) is not None

    if re.search(r"\bpico\s*4\b", query_norm):
        if not re.search(r"\bpico\s*4\b", title_norm):
            return False
        # Block known VR accessories, pass everything else
        vr_acc = ("strap", "cover", "case", "tasche", "kabel", "link kabel",
                  "gesichtspolster", "facial interface", "grips", "controller grips",
                  "halterung", "dock", "ladestation")
        if any(_has_term(title_norm, w) for w in vr_acc):
            return False
        return True

    if "vive ultimate" in query_norm:
        return "vive ultimate" in title_norm and "tracker" in title_norm

    if "slimevr" in query_norm or "slime tracker" in query_norm:
        # Block raw electronic components, pass assembled trackers
        if any(_has_term(title_norm, w) for w in ("qmc6309", "imu", "modu", "module")):
            return False
        return ("slimevr" in title_norm or "slime vr" in title_norm or "slime tracker" in title_norm) and (
            "tracker" in title_norm or "tracking" in title_norm
        )

    if "sony wh" in query_norm or "sony ult wear" in query_norm:
        # Block spare parts / cases / pads / sweat covers — never the headset itself.
        # Bug: "Silikon Sweat Cover … Zubehör für Kopfhörer" matched because
        # "kopfhörer" appeared in the accessory phrase and "cover" was not blocked.
        part_words = (
            "ersatz", "ersatzteil", "spare", "replacement", "oem",
            "linke", "rechte", "left ear", "right ear",
            "ohrpolster", "earpad", "ear pad", "earpads", "ear cushions",
            "hülle", "huelle", "case", "cover", "tasche", "silikon", "schutzhülle",
            "schutzhuelle", "kabel", "cable", "stand", "halterung", "only", "nur ",
            "zubehoer", "zubehör", "sweat", "earcup", "ear cup", "pad set",
            "swivel", "spindle", "buckle", "drehgelenk", "gelenk", "scharnier", "hinge",
        )
        # 206593245393 sells complete functional headphones without the box.
        # Only remove the explicit whole-device scope, never "only case/pads".
        purpose_title = re.sub(r"\b(?:nur|only)\s+(?:(?:die|the)\s+)?(?:kopfhoerer|headphones|headset)\b", " ", title_norm)
        if any(_has_term(purpose_title, w) for w in ("linke", "rechte", "left ear", "right ear", "only", "nur")):
            return False
        if any(_has_term(purpose_title, w) for w in part_words) and not _is_device_bundle(title_norm, "headphones"):
            return False
        if re.search(r"\bf\s*\.\s*(?:sony|wh[\s-]*|ult|kopfhoerer)", title_norm):
            return False
        # "für Sony WH…", "für Kopfhörer", "compatible with XM6" = accessory
        if re.search(
            r"\b(?:for|fuer|für|compatibel|kompatibel)\b.*\b(?:sony|wh[\s-]*1000|xm[456]|kopfhoerer|headphones|headset)\b",
            title_norm,
        ):
            return False
        if re.search(
            r"\b(?:fuer|für|for)\s+(?:kopfhoerer|headphones|headset)\b",
            title_norm,
        ):
            return False
        return True

    is_ps5_pro_query = _is_ps5_pro_search_query(query_norm)
    if is_ps5_pro_query:
        return (
            _has_ps5_pro_console_hint(title_norm)
            and not _is_ps5_vr_only_title(title_norm)
            and not _is_category_blocked_title(title_norm, category, query_norm)
        )

    if category == "consoles":
        return _is_console_device_title(title_norm, query_norm)

    # Default: pass everything — rely on _is_category_blocked_title for garbage
    return True


def _is_console_device_title(title_norm, query_norm):
    """Check if a title in the consoles category is actually a console device.

    Logic: a listing is a console ONLY if it has a device hint.
    No device hint = game, accessory, or irrelevant item.

    This is safe because real console listings ALWAYS mention one of:
    - "konsole", "console", "spielekonsole"
    - "digital edition", "disc edition", "disk edition", "blu-ray"
    - "825gb", "cfi-", "cuh-"
    - "inkl. controller", "mit controller"

    Limited editions like "PS5 Spider-Man Edition Konsole" pass because
    they contain "konsole". Games like "Spider-Man PS5" don't.
    """
    if _is_ps5_pro_search_query(query_norm):
        return _has_ps5_pro_console_hint(title_norm) and not _is_ps5_vr_only_title(title_norm)

    # Must have at least one console device hint to pass
    has_device_hint = any(_has_term(title_norm, w) for w in CONSOLE_DEVICE_HINTS)
    if has_device_hint:
        return True

    # No device hint — check if it's at least a bundle with console keywords
    # "PS5 + 3 Spiele" without explicit "konsole" but with storage/model number
    if re.search(r"\b(?:825|1000|1024)\s*gb\b", title_norm):
        return True
    if re.search(r"\b[12]\s*tb\b", title_norm) and not any(w in title_norm for w in ("ssd", "nvme", "m.2", "festplatte", "hard drive")):
        return True
    if re.search(r"\bcfi-\d", title_norm) or re.search(r"\bcuh-\d", title_norm):
        return True

    # Check for accessory words that confirm it's NOT a console
    for word in CATEGORY_ACCESSORY_WORDS.get("consoles", ()):
        if _has_term(title_norm, word):
            is_bundle = (
                any(b in title_norm for b in ("mit", "+", "and", "&", "inkl", "with", "bundle"))
                and re.match(r"^(?:sony\s+)?(?:playstation|ps5|xbox|nintendo|switch)\b", title_norm)
            )
            if is_bundle:
                return True
            return False

    # No device hint and no accessory word — likely a game or irrelevant
    return False


def _build_smart_search_query(search):
    """HTML eBay discovery: fetch candidates; reject wrong items after parsing.

    eBay's minus operator suppresses titles containing the negative keyword
    and can disable search expansion. In particular, -ersatzteil drops titles
    explicitly saying "kein Ersatzteil". Search terms supplied by the user
    (including their own operators) are preserved. Parts, faults, repair and
    excluded sellers remain rejected by the existing title/detail filters.
    Browse API uses a separate query and is unaffected.
    """
    return _intent_query(search)


def _build_url_with_host(host, search, sub="www"):
    """Build search URL on a specific host, mapping LH_PrefLoc semantics.

    sub: 'www' (default) or 'm' for the mobile subdomain. We use 'm' as a
    retry path on ebay.de when the desktop search hits the splashui
    anti-bot challenge — the same query on m.ebay.de is served normally
    after the challenge has set its bm_sv cookie on the session.
    """
    filters = search.get("filters", {})
    params = {"_nkw": _build_smart_search_query(search)}
    postal_code = str(config.get_settings().get("user_zip") or "").strip()
    if host == "ebay.de" and postal_code:
        params.update(_stpos=postal_code, _fcid="77")

    category = filters.get("category", "all")
    query_norm = _normalize(_intent_query(search))
    eff_category = _effective_category(category, query_norm)

    intent = _search_intent(search)
    # GPU-PCs are listed under Desktops, Komponenten, Sonstiges… Pinning
    # `_sacat=179` drops auctions and cheap used towers. Search site-wide;
    # title filters still require a real PC + the GPU.
    pin_sacat = not (intent and intent.get("kind") == "gpu_pc")
    if pin_sacat and category and category != "all":
        device_cat_id = EBAY_DEVICE_CATEGORY_IDS.get(eff_category)
        if device_cat_id:
            params["_sacat"] = device_cat_id
        elif eff_category and eff_category != "all":
            cat_id = _category_id(eff_category)
            if cat_id:
                params["_sacat"] = cat_id

    phone_aspects = _phone_model_aspect_params(query_norm) if eff_category == "phones" else None
    if phone_aspects:
        params.update(phone_aspects)

    sort_code = _sort_code(filters)
    if sort_code:
        params["_sop"] = str(sort_code)
    # Search across ALL categories to catch items listed in wrong/parent categories.
    # Programmatic title-based filtering handles irrelevant results.
    base = f"https://{sub}.{host}/sch/i.html"
    min_p = filters.get("min_price")
    max_p = filters.get("max_price")

    if min_p is not None:
        params["_udlo"] = str(min_p)
    if max_p is not None:
        params["_udhi"] = str(max_p)
    if filters.get("_ipg"):
        params["_ipg"] = str(filters["_ipg"])
    cond_code = filters.get("condition_code")
    cond = filters.get("condition", "any")
    if cond_code:
        params["LH_ItemCondition"] = str(cond_code)
    else:
        if cond == "new":
            params["LH_ItemCondition"] = "1000|1500"
        elif cond == "used":
            params["LH_ItemCondition"] = "3000"
        elif cond == "any":
            params["LH_ItemCondition"] = "1500|1000|2010|2020|2030|3000"
    lt = filters.get("listing_type", "all")
    if lt in ("buy_now", "buy_now_offer"):
        params["LH_BIN"] = "1"
        if filters.get("best_offer"):
            params["LH_BO"] = "1"
    elif lt == "auction":
        params["LH_Auction"] = "1"
        if filters.get("best_offer"):
            params["LH_BO"] = "1"
    elif lt == "offer":
        params["LH_BO"] = "1"
    st = filters.get("seller_type", "any")
    if st == "private":
        params["LH_SellerType"] = "1"
    loc = filters.get("location", "de")
    if host == "ebay.de":
        # Verified in the live ebay.de location controls on 2026-10-05:
        # 1 = Deutschland, 3 = Europäische Union, 2 = Weltweit.
        if loc == "de":
            params["LH_PrefLoc"] = "1"
        elif loc == "eu":
            params["LH_PrefLoc"] = "3"
        elif loc == "worldwide":
            params["LH_PrefLoc"] = "2"
    else:  # ebay.com
        if loc == "eu":
            params["LH_PrefLoc"] = "2"
        elif loc == "worldwide":
            params["LH_PrefLoc"] = "2"
    qstr = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{base}?{qstr}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s", stream=sys.stdout, force=True)
logger = logging.getLogger()
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

config = ConfigManager()
init_db()

# item_id -> {"initial": bool, "final_hour": bool}
# "initial" = first notify (or permanently skipped after validation reject)
# "final_hour" = second notify when ≤1h left and price still in limit
seen_state = {}
process_lock = asyncio.Lock()


# Auction alerts fire three times: when the lot first qualifies (≤24 h left),
# in the last hour, and one last call ~15 min before the hammer — each time only
# if the price still fits.
NOTIFY_STAGES = ("initial", "final_hour", "final_15m")
FINAL_HOUR_MINUTES = 60
FINAL_15M_MINUTES = 15
# The search card only hints at the time left and a pass is minutes long, so the
# candidate window is wider than the send gate — the precise end date from the
# item details decides.
FINAL_HOUR_CANDIDATE_MINUTES = 90
FINAL_15M_CANDIDATE_MINUTES = 25


def _empty_seen_entry():
    return {"initial": False, "final_hour": False, "final_15m": False}


class _SeenIdsProxy:
    """Backward-compatible set-like view over seen_state keys with initial=True."""

    def __contains__(self, item_id):
        entry = seen_state.get(str(item_id) if item_id is not None else "")
        return bool(entry and entry.get("initial"))

    def add(self, item_id):
        mark_seen_item(item_id, stage="initial")

    def clear(self):
        seen_state.clear()

    def __len__(self):
        return sum(1 for e in seen_state.values() if e.get("initial"))

    def __iter__(self):
        return (k for k, e in seen_state.items() if e.get("initial"))


# Kept for settings_handlers / external imports that still use seen_ids.add(...)
seen_ids = _SeenIdsProxy()

EU_COUNTRIES = {
    "deutschland", "germany", "de", "frankreich", "france", "fr", "italien", "italy", "it",
    "spanien", "spain", "es", "niederlande", "netherlands", "nl", "belgien", "belgium", "be",
    "österreich", "austria", "at", "polen", "poland", "pl", "portugal", "pt", "griechenland",
    "greece", "gr", "irland", "ireland", "ie", "tschechien", "czech", "cz", "schweden", "sweden",
    "se", "dänemark", "denmark", "dk", "finnland", "finland", "fi", "ungarn", "hungary", "hu",
    "rumänien", "romania", "ro", "bulgarien", "bulgaria", "bg", "kroatien", "croatia", "hr",
    "slowakei", "slovakia", "sk", "slowenien", "slovenia", "si", "litauen", "lithuania", "lt",
    "lettland", "latvia", "lv", "estland", "estonia", "ee", "luxemburg", "luxembourg", "lu",
    "malta", "mt", "zypern", "cyprus", "cy",
}

COUNTRY_INFO = {
    "DE": ("\U0001f1e9\U0001f1ea", "\u0413\u0435\u0440\u043c\u0430\u043d\u0438\u044f", True),
    "GB": ("\U0001f1ec\U0001f1e7", "\u0412\u0435\u043b\u0438\u043a\u043e\u0431\u0440\u0438\u0442\u0430\u043d\u0438\u044f", False),
    "UK": ("\U0001f1ec\U0001f1e7", "\u0412\u0435\u043b\u0438\u043a\u043e\u0431\u0440\u0438\u0442\u0430\u043d\u0438\u044f", False),
    "US": ("\U0001f1fa\U0001f1f8", "\u0421\u0428\u0410", False),
    "CN": ("\U0001f1e8\U0001f1f3", "\u041a\u0438\u0442\u0430\u0439", False),
    "JP": ("\U0001f1ef\U0001f1f5", "\u042f\u043f\u043e\u043d\u0438\u044f", False),
    "FR": ("\U0001f1eb\U0001f1f7", "\u0424\u0440\u0430\u043d\u0446\u0438\u044f", True),
    "IT": ("\U0001f1ee\U0001f1f9", "\u0418\u0442\u0430\u043b\u0438\u044f", True),
    "ES": ("\U0001f1ea\U0001f1f8", "\u0418\u0441\u043f\u0430\u043d\u0438\u044f", True),
    "NL": ("\U0001f1f3\U0001f1f1", "\u041d\u0438\u0434\u0435\u0440\u043b\u0430\u043d\u0434\u044b", True),
    "AT": ("\U0001f1e6\U0001f1f9", "\u0410\u0432\u0441\u0442\u0440\u0438\u044f", True),
    "PL": ("\U0001f1f5\U0001f1f1", "\u041f\u043e\u043b\u044c\u0448\u0430", True),
    "BE": ("\U0001f1e7\U0001f1ea", "\u0411\u0435\u043b\u044c\u0433\u0438\u044f", True),
    "PT": ("\U0001f1f5\U0001f1f9", "\u041f\u043e\u0440\u0442\u0443\u0433\u0430\u043b\u0438\u044f", True),
    "SE": ("\U0001f1f8\U0001f1ea", "\u0428\u0432\u0435\u0446\u0438\u044f", True),
    "DK": ("\U0001f1e9\U0001f1f0", "\u0414\u0430\u043d\u0438\u044f", True),
    "FI": ("\U0001f1eb\U0001f1ee", "\u0424\u0438\u043d\u043b\u044f\u043d\u0434\u0438\u044f", True),
    "IE": ("\U0001f1ee\U0001f1ea", "\u0418\u0440\u043b\u0430\u043d\u0434\u0438\u044f", True),
    "CZ": ("\U0001f1e8\U0001f1ff", "\u0427\u0435\u0445\u0438\u044f", True),
    "CH": ("\U0001f1e8\U0001f1ed", "\u0428\u0432\u0435\u0439\u0446\u0430\u0440\u0438\u044f", False),
    "NO": ("\U0001f1f3\U0001f1f4", "\u041d\u043e\u0440\u0432\u0435\u0433\u0438\u044f", False),
    "CA": ("\U0001f1e8\U0001f1e6", "\u041a\u0430\u043d\u0430\u0434\u0430", False),
    "AU": ("\U0001f1e6\U0001f1fa", "\u0410\u0432\u0441\u0442\u0440\u0430\u043b\u0438\u044f", False),
}

COUNTRY_ALIASES = {
    "deutschland": "DE", "germany": "DE", "germania": "DE",
    "grossbritannien": "GB", "great britain": "GB", "united kingdom": "GB",
    "vereinigtes konigreich": "GB", "vereinigtes koenigreich": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB",
    "usa": "US", "united states": "US", "china": "CN", "japan": "JP",
    "frankreich": "FR", "france": "FR", "italien": "IT", "italy": "IT",
    "spanien": "ES", "spain": "ES", "niederlande": "NL", "netherlands": "NL",
    "oesterreich": "AT", "osterreich": "AT", "austria": "AT",
    "polen": "PL", "poland": "PL", "belgien": "BE", "belgium": "BE",
    "portugal": "PT", "schweden": "SE", "sweden": "SE",
    "daenemark": "DK", "danemark": "DK", "denmark": "DK",
    "finnland": "FI", "finland": "FI", "irland": "IE", "ireland": "IE",
    "tschechien": "CZ", "czech": "CZ", "schweiz": "CH", "switzerland": "CH",
    "norwegen": "NO", "norway": "NO", "kanada": "CA", "canada": "CA",
    "australien": "AU", "australia": "AU",
}


def _country_code_from_location(location_text):
    if not location_text:
        return None
    raw = str(location_text).strip()
    for part in reversed([p.strip() for p in re.split(r"[,|/]", raw) if p.strip()]):
        token = re.sub(r"[^A-Za-z]", "", part).upper()
        if token in COUNTRY_INFO:
            return token
    loc = _normalize(raw)
    for alias, code in sorted(COUNTRY_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if _has_term(loc, alias):
            return code
    return None


def _format_country_for_notification(location_text):
    code = _country_code_from_location(location_text)
    if code and code in COUNTRY_INFO:
        flag, name, _is_eu_country = COUNTRY_INFO[code]
        return f"{flag} {name}"
    return "\u041d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d\u043e"


def _parse_time_left_to_minutes(time_left_str):
    t = (time_left_str or "").lower().strip()
    if not t:
        return None
    days = hours = minutes = 0
    matched = False
    m_days = re.search(r"(\d+)\s*(?:tag|t\b|d\b|day|д)", t)
    if m_days:
        days = int(m_days.group(1)); matched = True
    m_hours = re.search(r"(\d+)\s*(?:std|h\b|hour|ч)", t)
    if m_hours:
        hours = int(m_hours.group(1)); matched = True
    m_minutes = re.search(r"(\d+)\s*(?:min|m\b|minute|мин)", t)
    if m_minutes:
        minutes = int(m_minutes.group(1)); matched = True
    if not matched:
        if re.search(r"\b\d+\s*(?:sekunden?|sek|secs?|seconds?|s|сек)\b", t):
            return 1
        return None
    return days * 1440 + hours * 60 + minutes


def _format_minutes_short(minutes):
    if minutes is None or minutes <= 0:
        return None
    d, rem = divmod(int(minutes), 1440)
    h, m = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d}д")
    if h:
        parts.append(f"{h}ч")
    if not d and not h:
        parts.append(f"{m}м")
    return " ".join(parts) or None


def _auction_meta(item):
    minutes = _parse_time_left_to_minutes(item.get("time_left") or "")
    clock = _format_minutes_short(minutes) or (item.get("time_left") or "").strip() or None
    bids = item.get("bids_count")
    bid_str = None
    if bids is not None:
        try:
            n = int(bids)
            if n == 1:
                bid_str = "1 ставка"
            elif 2 <= n <= 4:
                bid_str = f"{n} ставки"
            else:
                bid_str = f"{n} ставок"
        except (TypeError, ValueError):
            bid_str = None
    return " · ".join(p for p in (clock, bid_str) if p)


def _passes_notification_price_and_auction_rules(item, search):
    return _notify_eligibility(item, search)[0]


def _notify_eligibility(item, search):
    """Shared verdict for normal notify + statistics green.

    Returns (eligible: bool, reason: str) where reason is one of:
      notify | over_limit | wait_24h | missing | too_cheap
    """
    if not item:
        return False, "missing"
    if _is_implausibly_cheap_device(item, search):
        return False, "too_cheap"
    hard_max = (search.get("filters") or {}).get("max_price")
    if (hard_max is not None and float(item.get("price") or 0) > float(hard_max)) or not _price_within_limit(item, search):
        return False, "over_limit"
    if item.get("auction") and not item.get("buy_now"):
        if item.get("best_offer"):
            return True, "notify"
        minutes = _parse_time_left_to_minutes(item.get("time_left", ""))
        if minutes is not None and minutes <= 1440:
            return True, "notify"
        return False, "wait_24h"
    return True, "notify"


def _serp_price_floor(search, device_floor, category, query_norm):
    """eBay `_udlo` for a search.

    Raising it above the bait floor only keeps a price-ascending page 1 free of
    Hüllen und Folien — and that convenience cost real finds: with a 45€ limit
    the mouse searches asked eBay for ≥40€ and never saw a live 30.50€ PRO X
    SUPERLIGHT 2 auction (2026-07-27). So once the owner set a limit, the entire
    band up to it is fetched and the cosmetic raise is skipped; page 1 may carry
    some accessories, and the title/category filters drop them.
    """
    raise_to = device_floor
    if category == "phones" or _is_phone_search_query(query_norm):
        raise_to = max(device_floor, 120.0)
    elif category == "headphones" or "sony wh" in query_norm or "ult wear" in query_norm:
        raise_to = max(device_floor, 80.0)
    elif category == "monitors":
        raise_to = max(device_floor, 150.0)
    elif category == "mice" or "superlight" in query_norm:
        raise_to = max(device_floor, 40.0)
    limit = _search_limit_price(search)
    if limit:
        # Same share as the bait floor: keep page 1 usable on a huge market
        # (iPhone: ≥112€ instead of ≥120€) without ever reaching into the band
        # where the finds live (mice: 11€ instead of 40€).
        raise_to = min(raise_to, limit * _BAIT_FLOOR_SHARE_OF_LIMIT)
    return max(device_floor, raise_to)


def _prepare_monitor_fetch_search(search):
    """Same eBay fetch profile for normal alerts and statistics.

    Statistics used price_asc + large page size and found real cheap deals;
    default newest-first often never saw them. Keep one pipeline.
    """
    prepared = copy.deepcopy(search)
    filters = prepared.setdefault("filters", {})
    # Cheapest-first so page-1 matches what stats used to show.
    filters["sort"] = "price_asc"
    filters["_ipg"] = 60 if _on_github_actions() else max(int(filters.get("_ipg") or 0), 240)
    if filters.get("listing_type") not in ("buy_now", "buy_now_offer", "offer"):
        # Low opening bids belong in the auction buckets; descriptions/model
        # checks establish whether it is a device, then timing controls alerts.
        filters["min_price"] = None
        return prepared
    # Soft notify limit stays in limit_price; do not shrink eBay _udhi here.
    # Raise _udlo so price_asc is not 100% Hüllen/Folien before real devices.
    query_norm = _normalize(_intent_query(prepared))
    category = _effective_category(filters.get("category", "all"), query_norm)
    device_floor = _min_plausible_device_price(prepared)
    search_floor = _serp_price_floor(prepared, device_floor, category, query_norm)
    # The raise above device_floor is cosmetic — it only keeps page 1 free of
    # Hüllen/Folien. It must never climb above the price we would alert at, or
    # the search asks eBay for a band where no deal can live: Pixel 5 was asking
    # for ≥120€ under a 70€ limit, so its live 40–70€ lots were never fetched.
    try:
        limit_f = float(filters.get("limit_price") or 0)
    except (TypeError, ValueError):
        limit_f = 0.0
    if limit_f and search_floor > limit_f:
        search_floor = device_floor

    # A current auction bid is exempt from the configured lower price bound.
    cur_min = filters.get("min_price") if filters.get("listing_type") in ("buy_now", "buy_now_offer") else None
    if cur_min is None:
        filters["min_price"] = None
    try:
        cur_min_f = float(cur_min) if cur_min is not None else 0.0
    except (TypeError, ValueError):
        cur_min_f = 0.0
    if search_floor and search_floor > cur_min_f:
        filters["min_price"] = search_floor
    return prepared


def _format_time_left_from_seconds(total_seconds):
    if total_seconds <= 0:
        return "0мин"
    # eBay auctions can last at most 30 days; anything beyond is bogus
    if total_seconds > 30 * 86400:
        return ""
    days = int(total_seconds // 86400)
    hours = int((total_seconds % 86400) // 3600)
    minutes = int((total_seconds % 3600) // 60)

    parts = []
    if days > 0:
        parts.append(f"{days}д")
    if hours > 0:
        parts.append(f"{hours}ч")
    if (minutes > 0 and days == 0) or not parts:
        parts.append(f"{minutes}мин")
    return " ".join(parts)


def _parse_end_date_to_seconds(end_date_str):
    if not end_date_str:
        return None
    try:
        clean_date = end_date_str.strip()
        if clean_date.endswith("Z"):
            clean_date = clean_date[:-1] + "+00:00"
        from datetime import datetime, timezone
        end_dt = datetime.fromisoformat(clean_date)
        if end_dt.tzinfo is not None:
            now_dt = datetime.now(timezone.utc)
        else:
            now_dt = datetime.utcnow()
        diff = end_dt - now_dt
        return diff.total_seconds()
    except Exception as e:
        logger.warning("Error parsing end date '%s': %s", end_date_str, e)
        return None


def _normalize(text):
    if text is None:
        return ""
    t = text.lower()
    t = t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    t = t.replace("\ufffd", "?")
    t = re.sub(r"\bf\?{1,3}r\b", "fuer", t)
    t = re.sub(r"\bgeh\?rsch\?{1,3}tzer\b", "gehoerschuetzer", t)
    t = t.replace("-", " ")  # Treat hyphens as spaces
    t = re.sub(r"\bplaystation[\s®™]*(?=\d)", "playstation ", t)
    t = re.sub(r"\bps\s+5\b", "ps5", t)
    t = re.sub(r"\b(\d+)\s+(gb|go|tb)\b", r"\1\2", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _item_hash(seller, title, price):
    raw = f"{seller}|{title}|{price:.2f}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _normalize_seen_payload(data):
    """Migrate list-of-ids or dict stages into seen_state dict."""
    state = {}
    if isinstance(data, list):
        for x in data:
            iid = str(x).strip()
            if iid:
                state[iid] = {"initial": True, "final_hour": False, "final_15m": False}
    elif isinstance(data, dict):
        for k, v in data.items():
            iid = str(k).strip()
            if not iid:
                continue
            if isinstance(v, dict):
                state[iid] = {
                    "initial": bool(v.get("initial")),
                    "final_hour": bool(v.get("final_hour")),
                    # Files written before the 15-min stage existed simply have
                    # no flag; those lots get their last call on the next pass.
                    "final_15m": bool(v.get("final_15m")),
                }
            else:
                # Bare true / legacy values mean initial notify done
                state[iid] = {"initial": True, "final_hour": False, "final_15m": False}
    return state


def load_seen_ids():
    global seen_state
    if os.path.exists(SEEN_IDS_FILE):
        try:
            with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            seen_state = _normalize_seen_payload(data)
        except (json.JSONDecodeError, IOError):
            seen_state = {}
    else:
        seen_state = {}


def save_seen_ids():
    # Cap growth: drop oldest-inserted keys (dict preserves insertion order)
    keys = list(seen_state.keys())
    if len(keys) > 15000:
        for old_key in keys[: len(keys) - 10000]:
            seen_state.pop(old_key, None)
    payload = {
        k: {
            "initial": bool(v.get("initial")),
            "final_hour": bool(v.get("final_hour")),
            "final_15m": bool(v.get("final_15m")),
        }
        for k, v in seen_state.items()
    }
    with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def mark_seen_item(item_id, stage="initial"):
    """Mark a notification stage. stage: 'initial' | 'final_hour' | 'final_15m'."""
    if not item_id:
        return
    iid = str(item_id).strip()
    if not iid:
        return
    entry = seen_state.setdefault(iid, _empty_seen_entry())
    if stage == "final_15m":
        # A lot can go straight from the initial alert into the last 15 minutes
        # (nothing guarantees a pass landed inside the final hour), so the
        # skipped stage is closed too — no late "1 час до конца" afterwards.
        entry["final_15m"] = True
        entry["final_hour"] = True
        entry["initial"] = True
    elif stage == "final_hour":
        entry["final_hour"] = True
        entry["initial"] = True
    else:
        entry["initial"] = True
    save_seen_ids()


def unmark_seen_stage(item_id, stage="initial"):
    """Undo a reserved stage after a failed Telegram send (allows retry)."""
    if not item_id:
        return
    iid = str(item_id).strip()
    entry = seen_state.get(iid)
    if not entry:
        return
    if stage == "final_15m":
        entry["final_15m"] = False
    elif stage == "final_hour":
        entry["final_hour"] = False
    else:
        entry["initial"] = False
    if not any(entry.get(s) for s in NOTIFY_STAGES):
        seen_state.pop(iid, None)
    save_seen_ids()


def get_seen_entry(item_id):
    iid = str(item_id).strip() if item_id is not None else ""
    if not iid:
        return _empty_seen_entry()
    entry = seen_state.get(iid)
    if not entry:
        return _empty_seen_entry()
    return {
        "initial": bool(entry.get("initial")),
        "final_hour": bool(entry.get("final_hour")),
        "final_15m": bool(entry.get("final_15m")),
    }


def _price_within_limit(item, search):
    filters = search.get("filters", {}) or {}
    limit_or_max = filters.get("limit_price") if "limit_price" in filters else filters.get("max_price")
    if limit_or_max is None:
        return True
    try:
        return float(item.get("total_price") or 0) <= float(limit_or_max)
    except (TypeError, ValueError):
        return False


def _search_limit_price(search):
    filters = (search.get("filters") if isinstance(search, dict) else {}) or {}
    try:
        return float(filters.get("limit_price") or 0)
    except (TypeError, ValueError):
        return 0.0


# A bait floor may only guard the bottom quarter of what the owner would pay.
# Above that it stops protecting and starts hiding the finds this bot exists
# for: a 40€ floor under a 45€ mouse limit buried a live 36.69€ SUPERLIGHT 2,
# while a quarter of a 200€ XM6 limit still throws out the 4€ earpad bait.
_BAIT_FLOOR_SHARE_OF_LIMIT = 0.25


def _min_plausible_device_price(search):
    """Bait floor for this query, capped against the owner's limit.

    The point of this bot is the rare underpriced lot, so `limit_price` says
    what is worth seeing. The category floor still throws out «XM6 ab 4€»
    multi-SKU bait, but it may never climb into the band the owner is hunting.
    """
    floor = _category_device_floor(search)
    if not floor:
        return floor
    limit = _search_limit_price(search)
    if limit:
        return min(floor, limit * _BAIT_FLOOR_SHARE_OF_LIMIT)
    return floor


def _category_device_floor(search):
    """Reject earpad/case/bait floors that are not a real device for this query.

    Fake 'from 4€' / multi-SKU listings often survive as fixed 4–30€ cards.
    Real WH-1000XM6 units start well above that on the market.
    """
    query_norm = _normalize(_intent_query(search) if isinstance(search, dict) else search)
    filters = (search.get("filters") if isinstance(search, dict) else {}) or {}
    category = _effective_category(filters.get("category", "all"), query_norm)

    # Market floor for full WH-1000XM4/5/6 units (~200€+). 4–30€ is always pads/bait.
    if re.search(r"\b(?:wh[\s-]*1000\s*xm|1000\s*xm\s*[456]|ult\s*wear|ult900)\b", query_norm):
        return 80.0
    if "xm6" in query_norm or "xm5" in query_norm or "xm4" in query_norm:
        return 80.0
    if category == "headphones" or "sony wh" in query_norm:
        return 50.0
    if category == "phones" or _is_phone_search_query(query_norm):
        return 40.0
    if _is_controller_pad_query(query_norm):
        return 0.0
    if category == "consoles":
        return 80.0
    if category == "monitors":
        return 60.0
    if category in ("laptops", "computers"):
        return 100.0
    if category == "mice" or "superstrike" in query_norm or "superlight" in query_norm:
        return 35.0
    return 0.0


def _is_implausibly_cheap_device(item, search):
    if item.get("auction"):
        return False
    floor = _min_plausible_device_price(search)
    if floor <= 0:
        return False
    try:
        total = float(item.get("total_price") or item.get("price") or 0)
    except (TypeError, ValueError):
        return False
    return total > 0 and total < floor


def _is_statistics_mode(config_obj):
    mode_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mode.txt')
    if os.path.exists(mode_file):
        try:
            with open(mode_file, 'r', encoding='utf-8') as f:
                return f.read().strip().lower() == 'statistics'
        except Exception:
            pass
    return config_obj.get_settings().get('test_summary_mode', False)


def clear_monitoring_state():
    # Do not wipe production dedup state after statistics reports.
    # (Previously this cleared seen_ids and caused mass re-notifies.)
    logger.info("Statistics finished: keeping seen_state (%d ids)", len(seen_state))


def _git_commit_and_push(files_to_sync, commit_msg):
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir_safe = repo_dir.replace("\\", "/")
    git_base = ["git", "-c", f"safe.directory={repo_dir_safe}"]

    def git_run(*args):
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        try:
            return subprocess.run(
                git_base + list(args),
                cwd=repo_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env
            )
        except FileNotFoundError:
            class DummyResult:
                returncode = 127
                stdout = ""
                stderr = "Git executable not found in PATH"
            return DummyResult()

    gh_token = GITHUB_TOKEN
    if gh_token:
        r_url = git_run("remote", "get-url", "origin")
        r_str = (r_url.stdout or "").strip()
        if r_str:
            fixed = re.sub(r'https://(?:[^@]+@)?github\.com', f'https://{gh_token}@github.com', r_str)
            if fixed != r_str:
                git_run("remote", "set-url", "origin", fixed)

    git_run("add", *files_to_sync)

    diff = git_run("diff", "--cached", "--quiet")
    if diff.returncode != 0:
        commit = git_run("commit", "-m", commit_msg, "--", *files_to_sync)
        if commit.returncode != 0:
            raise Exception(f"Git commit failed: {commit.stderr.strip()}")

        push = git_run("push")
        if push.returncode == 0:
            logger.info(f"Git push successful for: {files_to_sync}")
            return True
        else:
            logger.info(f"First git push failed, trying to pull & rebase... Error: {push.stderr.strip()}")
            pull = git_run("pull", "--rebase", "--autostash")
            if pull.returncode != 0:
                resolved = True
                for attempt in range(10):
                    status = git_run("status", "--porcelain")
                    unmerged = []
                    for line in (status.stdout or "").splitlines():
                        if len(line) >= 2 and line[:2] in ("UU", "AA", "DD", "AU", "UA", "DU", "UD"):
                            unmerged.append(line[3:].strip().strip('"'))
                    if not unmerged:
                        break

                    for f in unmerged:
                        pick = git_run("checkout", "--theirs", "--", f)
                        if pick.returncode != 0:
                            git_run("checkout", "--ours", "--", f)
                        git_run("add", "--", f)

                    env = os.environ.copy()
                    env["GIT_EDITOR"] = "true"
                    env["GIT_TERMINAL_PROMPT"] = "0"
                    cont = subprocess.run(git_base + ["rebase", "--continue"], cwd=repo_dir, capture_output=True, text=True, env=env)
                    if cont.returncode == 0:
                        break
                else:
                    resolved = False

                if not resolved:
                    git_run("rebase", "--abort")
                    raise Exception(f"Git rebase conflict could not be resolved automatically. Pull error: {pull.stderr.strip()}")

            push = git_run("push")
            if push.returncode == 0:
                logger.info(f"Git push successful after rebase for: {files_to_sync}")
                return True
            else:
                raise Exception(f"Git push failed after rebase: {push.stderr.strip()}")
    else:
        logger.info(f"No changes staged for: {files_to_sync}")
        return False


def _sync_mode_to_github():
    mode_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mode.txt')
    if os.path.exists(mode_file):
        with open(mode_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
    else:
        content = 'normal'

    if os.environ.get("BOT_RUNNING_UNDER_LAUNCHER") == "1":
        logger.info("Бот запущен под лаунчером. Выполняю прямую синхронизацию mode.txt через Git...")
        return _git_commit_and_push(["mode.txt"], f"Toggle auto-monitoring mode to {content}")

    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/mode.txt"
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }

    sha = None
    try:
        resp = requests.get(api_url, headers=headers, timeout=15)
        if resp.status_code == 200:
            sha = resp.json().get('sha')
        elif resp.status_code != 404:
            raise Exception(f"GitHub API ошибка ({resp.status_code}): {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Error fetching mode.txt SHA from GitHub API: {e}")

    encoded = base64.b64encode(content.encode('utf-8')).decode('ascii')

    payload = {
        'message': f'🔄 Toggle auto-monitoring mode to {content}',
        'content': encoded,
    }
    if sha:
        payload['sha'] = sha

    resp = requests.put(api_url, headers=headers, json=payload, timeout=15)
    if resp.status_code in (200, 201):
        return True
    else:
        raise Exception(f"GitHub PUT ошибка ({resp.status_code}): {resp.text[:200]}")


def build_ebay_url(search):
    filters = search.get("filters", {})
    params = {"_nkw": _build_smart_search_query(search)}
    sort_code = _sort_code(filters)
    if sort_code:
        params["_sop"] = str(sort_code)
    # Search across ALL categories — programmatic filtering handles relevance.
    base = "https://www.ebay.de/sch/i.html"
    if filters.get("min_price"):
        params["_udlo"] = str(filters["min_price"])
    if filters.get("max_price"):
        params["_udhi"] = str(filters["max_price"])
    if filters.get("_ipg"):
        params["_ipg"] = str(filters["_ipg"])
    cond_code = filters.get("condition_code")
    cond = filters.get("condition", "any")
    if cond_code:
        params["LH_ItemCondition"] = str(cond_code)
    else:
        if cond == "new":
            params["LH_ItemCondition"] = "1000|1500"
        elif cond == "used":
            params["LH_ItemCondition"] = "3000"
        elif cond == "any":
            params["LH_ItemCondition"] = "1500|1000|2010|2020|2030|3000"
    lt = filters.get("listing_type", "all")
    if lt in ("buy_now", "buy_now_offer"):
        params["LH_BIN"] = "1"
        if filters.get("best_offer"):
            params["LH_BO"] = "1"
    elif lt == "auction":
        params["LH_Auction"] = "1"
        if filters.get("best_offer"):
            params["LH_BO"] = "1"
    elif lt == "offer":
        params["LH_BO"] = "1"
    st = filters.get("seller_type", "any")
    if st == "private":
        params["LH_SellerType"] = "1"
    loc = filters.get("location", "de")
    if loc == "de":
        params["LH_PrefLoc"] = "1"
    elif loc == "eu":
        params["LH_PrefLoc"] = "3"
    elif loc == "worldwide":
        params["LH_PrefLoc"] = "2"
    qstr = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{base}?{qstr}"


def _clean_time_left(txt):
    if not txt:
        return ""
    import re
    from datetime import datetime, timedelta
    t = txt.strip()

    # If it already has remaining time terms (Std, Min, Tag, std, min, tag|[hmdtT]), return it cleaned
    if re.search(r"\d+\s*(?:Std|Min|Tag|std|min|tag|[hmdtT]|day|hour|minute)", t):
        if t.lower().startswith("noch "):
            t = t[5:]
        t = re.sub(r"\s*\(.*?\)", "", t)
        minutes = _parse_time_left_to_minutes(t)
        if minutes is not None and minutes > 0:
            return _format_time_left_from_seconds(minutes * 60)
        return t.strip()

    # Check for DayOfWeek, HH:MM format (e.g. "Mo, 09:18" or "Sonntag, 10:55" or "So., 10:55")
    m_dow = re.search(r"\b(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|Mo|Di|Mi|Do|Fr|Sa|So)\.?,?\s*(\d{2}):(\d{2})\b", t, re.IGNORECASE)
    if m_dow:
        dow_str = m_dow.group(1).lower()
        hour = int(m_dow.group(2))
        minute = int(m_dow.group(3))

        dow_map = {
            "mo": 0, "montag": 0,
            "di": 1, "dienstag": 1,
            "mi": 2, "mittwoch": 2,
            "do": 3, "donnerstag": 3,
            "fr": 4, "freitag": 4,
            "sa": 5, "samstag": 5,
            "so": 6, "sonntag": 6
        }
        target_dow = dow_map[dow_str]

        now = datetime.now()
        target_date = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        days_ahead = target_dow - now.weekday()
        if days_ahead < 0 or (days_ahead == 0 and target_date < now):
            days_ahead += 7

        target_date += timedelta(days=days_ahead)
        diff = target_date - now
        if diff.total_seconds() <= 0:
            return ""
        return _format_time_left_from_seconds(diff.total_seconds())

    # Check for DD. MMM. HH:MM format (e.g. "27. Apr. 09:17" or "15. Jun. 09:18")
    m_date = re.search(r"\b(\d{1,2})\.\s*(Jan|Feb|Mär|Maer|Apr|Mai|Jun|Jul|Aug|Sep|Okt|Nov|Dez)\.?\s*(\d{2}):(\d{2})\b", t, re.IGNORECASE)
    if m_date:
        day = int(m_date.group(1))
        month_str = m_date.group(2).lower()
        hour = int(m_date.group(3))
        minute = int(m_date.group(4))

        month_map = {
            "jan": 1, "feb": 2, "mär": 3, "maer": 3, "apr": 4, "mai": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dez": 12
        }
        month_key = month_str[:3]
        if month_key in month_map:
            month = month_map[month_key]
        else:
            return t

        now = datetime.now()
        year = now.year

        try:
            target_date = datetime(year, month, day, hour, minute)
            if target_date < now:
                # Only add 1 year if it results in a date in the near future (e.g. <= 30 days)
                future_date = datetime(year + 1, month, day, hour, minute)
                if (future_date - now).days <= 30:
                    target_date = future_date
                else:
                    return ""
        except ValueError:
            return t

        diff = target_date - now
        if diff.total_seconds() <= 0:
            return ""
        return _format_time_left_from_seconds(diff.total_seconds())

    return t


def _is_nested_in_card(el, card_el):
    curr = el.parent
    while curr and curr != card_el:
        cl = curr.get("class", []) if hasattr(curr, "get") else []
        if "s-card" in cl or "s-item" in cl:
            return True
        curr = curr.parent
    return False


def _parse_feedback_count(num, suffix=""):
    """German `(1.744)` is 1744, not 1.744. `1,2k` / `1.2k` stay 1200."""
    suffix = (suffix or "").lower()
    if suffix in ("k", "m"):
        val = float(str(num).replace(",", "."))
        return int(val * (1000 if suffix == "k" else 1_000_000))
    digits = re.sub(r"[.,\s]", "", str(num))
    return int(digits) if digits else 0


def parse_ebay_results(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    cards = soup.select("li.s-card, li.s-item")
    for card in cards:
        try:
            listing_id = card.get("data-listingid") or card.get("data-id") or card.get("id") or ""
            # Strip prefixes like 'item' from id if present
            if listing_id.startswith("item"):
                listing_id = listing_id[4:]

            link_el = card.select_one("a.s-card__link, a.s-item__link, a.s-item__link-wrapper")
            if not link_el:
                continue
            href = link_el.get("href", "")
            item_id_match = re.search(r"/itm/(\d+)", href)
            item_id = item_id_match.group(1) if item_id_match else listing_id
            if not item_id:
                continue

            title_el = card.select_one("span.su-styled-text.primary.default, div.s-item__title, h3.s-item__title, span[role='heading']")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title or title.lower().startswith("shop on ebay"):
                continue

            price_elements = [el for el in card.select("span.s-card__price, span.s-item__price") if not _is_nested_in_card(el, card)]
            price_texts = [el.get_text(strip=True) for el in price_elements]
            price_text_combined = " ".join(price_texts)
            price_lower = price_text_combined.lower()
            # "EUR 4,00 bis EUR 250,00" / "from … to …" / "ab 4 €" = multi-SKU bait
            is_multivariation = bool(
                "bis" in price_lower
                or re.search(r"\bto\b", price_lower)
                or re.search(r"\bab\s*(?:eur|€|\$)?\s*\d", price_lower)
                or re.search(r"\bfrom\s*(?:eur|€|\$)?\s*\d", price_lower)
                or re.search(r"(?:eur|€|\$)\s*\d+[.,]\d+\s*[-–—]\s*(?:eur|€|\$)?\s*\d", price_lower)
            )

            parsed_prices = []
            for pt in price_texts:
                p_val = _parse_price(pt)
                if p_val is not None:
                    parsed_prices.append(p_val)
            if not is_multivariation and len(parsed_prices) >= 2:
                lo, hi = min(parsed_prices), max(parsed_prices)
                if hi >= lo * 1.5 and hi - lo >= 15:
                    is_multivariation = True

            price = parsed_prices[0] if parsed_prices else None
            if price is None:
                continue

            img_el = card.select_one("img.s-card__image, img.s-item__image, .s-item__image-img img")
            image_url = ""
            if img_el:
                image_url = img_el.get("src", "") or img_el.get("data-defer-load", "")
                if "ebaystatic.com" in image_url and "ebayimg" not in image_url:
                    image_url = ""

            all_spans = [s for s in card.select("span") if not _is_nested_in_card(s, card)]
            all_texts = [s.get_text(strip=True).lower() for s in all_spans]
            card_text = card.get_text(" ", strip=True)
            card_text_lower = card_text.lower()
            if card_text_lower:
                all_texts.append(card_text_lower)

            is_pickup_only = False
            for txt in all_texts:
                if any(marker in txt for marker in ("nur abholung", "nur selbstabholung", "abholung: nur abholung", "kein versand", "no shipping", "collection in person", "local pickup only", "pickup only")):
                    is_pickup_only = True
                    break

            shipping_cost = 0.0
            if not is_pickup_only:
                for s in all_spans:
                    txt = s.get_text(strip=True)
                    if _is_delivery_speed_or_date(txt):
                        continue
                    if "Lieferung" in txt or "Versand" in txt or "shipping" in txt.lower():
                        shipping_cost = _parse_shipping(txt)
                        break
                    if "kostenlos" in txt.lower() or "gratis" in txt.lower():
                        shipping_cost = 0.0
                        break

            buy_now = True
            best_offer = False
            auction = False
            time_left = ""
            bids_count = None
            for txt in all_texts:
                tl = (txt or "").lower()
                if "preisvorschlag" in tl or "best offer" in tl:
                    best_offer = True
                if (
                    ("gebot" in tl and "angebot" not in tl)
                    or "bid" in tl
                    or "ставк" in tl
                    or "auktion" in tl
                    or "höchstgebot" in tl
                    or "hochstgebot" in tl
                ):
                    auction = True
                    m_bids = re.search(r"(\d+)\s*(?:gebot|bid|ставк)", tl)
                    if m_bids:
                        try:
                            bids_count = int(m_bids.group(1))
                        except ValueError:
                            pass

            if (
                re.search(r"\b\d+\s*(?:gebot|gebote|bid|bids)\b", card_text_lower)
                or "endet in" in card_text_lower
                or "ends in" in card_text_lower
                or "auktion" in card_text_lower
                or "höchstgebot" in card_text_lower
                or re.search(r"\bnoch\s+\d", card_text_lower)
            ):
                auction = True
                m_bids_new = re.search(r"(\d+)\s*(?:gebot|gebote|bid|bids)\b", card_text_lower)
                if m_bids_new:
                    try:
                        bids_count = int(m_bids_new.group(1))
                    except ValueError:
                        pass

            has_sofort_kaufen = any(
                "sofort-kaufen" in t or "oder sofort" in t or "buy it now" in t or "sofort kaufen" in t
                for t in all_texts
            )
            if auction and not has_sofort_kaufen:
                buy_now = False
            if auction and buy_now and len(parsed_prices) >= 2:
                # A bid and a separate buy-now price are not a variant range.
                is_multivariation = bool(re.search(r"\bbis\b|\bto\b|\b(?:ab|from)\s*(?:eur|€|\$)?\s*\d", price_lower))

            auc_price = None
            bin_price = None
            if auction and buy_now:
                if len(parsed_prices) >= 2:
                    auc_price = parsed_prices[0]
                    bin_price = parsed_prices[1]
                else:
                    auc_price = price
                    bin_price = price
            elif auction:
                auc_price = price
            else:
                bin_price = price

            for s in all_spans:
                txt = s.get_text(strip=True)
                cls = s.get("class", [])
                cls_str = " ".join(cls)
                if ("secondary" in cls_str or "time-left" in cls_str or "s-card__time" in cls_str) and (re.search(r"\d+\s*(Std|Min|Tag|[hmdtT])", txt) or re.search(r"\b\d{2}:\d{2}\b", txt)):
                    is_specific = "s-item__time-left" in cls_str or "time-left" in cls_str or "s-card__time-left" in cls_str
                    if is_specific or not time_left:
                        cleaned = _clean_time_left(txt)
                        if cleaned:
                            time_left = cleaned

            if not time_left and auction:
                m_time = re.search(
                    r"(?:endet in|ends in)\s*([0-9]+\s*(?:t|tag|tage|d|day|days|std|h|hour|hours|min|minute|minutes)(?:\s+[0-9]+\s*(?:t|tag|tage|d|day|days|std|h|hour|hours|min|minute|minutes))?)",
                    card_text_lower,
                    flags=re.IGNORECASE,
                )
                if m_time:
                    cleaned = _clean_time_left(m_time.group(1))
                    if cleaned:
                        time_left = cleaned

            seller_name = ""
            rating_count = 0
            rating_percent = 0.0
            for a in card.select("a[href*='/usr/'], a[href*='/str/'], a[href*='_ssn=']"):
                href = a.get("href") or ""
                m_usr = re.search(r"/(?:usr|str)/([^/?#&]+)", href, flags=re.I)
                m_ssn = re.search(r"[?&]_ssn=([^&]+)", href, flags=re.I)
                cand = m_usr.group(1) if m_usr else (m_ssn.group(1) if m_ssn else "")
                if cand:
                    try:
                        cand = urllib.parse.unquote(cand)
                    except Exception:
                        pass
                    if cand and "%" not in cand and len(cand) < 80:
                        seller_name = cand
                        break
            for idx, s in enumerate(all_spans):
                cls = " ".join(s.get("class", []))
                txt = s.get_text(strip=True)
                if "primary" in cls and "large" in cls and "bold" not in cls and "price" not in cls:
                    if txt and not txt.startswith(("EUR", "USD", "$", "€")) and len(txt) < 50:
                        if not re.match(r"^\d", txt) and "%" not in txt:
                            seller_name = txt
                rating_hit = re.search(
                    r"positiv|positive|положитель|позитивн|feedback|bewertung",
                    txt,
                    flags=re.I,
                )
                if rating_hit:
                    m = re.search(
                        r"([\d.,]+)%\s*(?:positiv|positive|положитель\w*|позитивн\w*|feedback|bewertung).*?\(([\d.,]+)\s*([kKmM]?)\)",
                        txt,
                        flags=re.I,
                    )
                    if m:
                        try:
                            rating_percent = float(m.group(1).replace(",", "."))
                            rating_count = _parse_feedback_count(m.group(2), m.group(3))
                        except ValueError:
                            pass
                    if not seller_name and idx > 0:
                        prev = all_spans[idx - 1].get_text(" ", strip=True)
                        if prev and "%" not in prev and len(prev) < 80:
                            seller_name = prev

            top_rated = False
            condition = ""
            seller_type = "unknown"
            location = ""
            for s in all_spans:
                cls = " ".join(s.get("class", []))
                txt = s.get_text(strip=True)
                if "secondary" in cls and "default" in cls:
                    txt_lower = txt.lower().rstrip(" |")
                    txt_clean = txt_lower.replace("·", "").strip()
                    txt_norm = _normalize(txt_clean)
                    is_condition = False
                    for cond_word in ("gebraucht", "neu", "new", "used", "refurbished", "generaluberholt", "pre owned"):
                        if cond_word in txt_norm:
                            is_condition = True
                            break
                    for defect_word in ("defekt", "ersatzteil", "parts", "not working", "salvage", "reparatur"):
                        if defect_word in txt_norm:
                            is_condition = True
                            condition = "defekt"
                            break
                    if is_condition and not condition:
                        condition = txt.rstrip(" |").strip()
                    elif txt_clean == "privat":
                        seller_type = "private"
                    elif txt_clean == "gewerblich":
                        seller_type = "commercial"
                if "aus " in txt.lower() and len(txt) < 40:
                    location = re.sub(r"^aus\s+", "", txt, flags=re.IGNORECASE).strip()
                if txt.lower().startswith("located in ") and len(txt) < 80:
                    location = re.sub(r"^located in\s+", "", txt, flags=re.IGNORECASE).strip()

            items.append({
                "item_id": str(item_id) if item_id is not None else "",
                "title": title,
                "price": price,
                "auc_price": auc_price,
                "bin_price": bin_price,
                "_was_hybrid": auction and buy_now,
                "shipping_cost": shipping_cost,
                "total_price": price + shipping_cost,
                "image_url": image_url,
                "url": href,
                "buy_now": buy_now,
                "best_offer": best_offer,
                "auction": auction,
                "bids_count": bids_count,
                "is_pickup_only": is_pickup_only,
                "condition": condition,
                "seller_name": seller_name,
                "seller_rating_count": rating_count,
                "seller_rating_percent": rating_percent,
                "seller_type": seller_type,
                "top_rated": top_rated,
                "location": location,
                "time_left": time_left,
                "is_multivariation": is_multivariation,
            })
        except Exception as e:
            logger.debug("parse card error: %s", e)
            continue
    return items


def _normalize_price_number(text):
    text = text.replace("\xa0", " ").strip()
    text = re.sub(r"^(EUR|USD|US|€|\$)\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*(EUR|USD|US|€|\$)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^\d.,]", "", text)
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "." in text:
        parts = text.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            text = "".join(parts)
    return text


def _currency_rate(currency):
    rates = {
        "EUR": 1.0,
        "GBP": 1.18,
        "USD": 0.92,
        "AUD": 0.61,
        "CHF": 1.04,
        "CAD": 0.67,
    }
    return rates.get((currency or "EUR").strip().upper(), 1.0)


def _detect_price_currency(text):
    text_upper = (text or "").replace("\xa0", " ").upper()
    if "GBP" in text_upper or "£" in text_upper or "Ł" in text_upper:
        return "GBP"
    if "AUD" in text_upper or "A$" in text_upper or re.search(r"\bAU\s*\$", text_upper):
        return "AUD"
    if "CAD" in text_upper or "C$" in text_upper or re.search(r"\bCA\s*\$", text_upper):
        return "CAD"
    if "CHF" in text_upper:
        return "CHF"
    if "USD" in text_upper or re.search(r"\bUS\s*\$", text_upper) or "$" in text_upper:
        return "USD"
    return "EUR"


def _strip_approx_price_text(text):
    text_clean = (text or "").replace("\xa0", " ").strip()
    text_clean = re.split(r"\(|approx\.", text_clean, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    ca_match = re.search(r"\bca\.\s*", text_clean, flags=re.IGNORECASE)
    if ca_match:
        if ca_match.start() == 0:
            text_clean = text_clean[ca_match.end():].strip()
        else:
            text_clean = text_clean[:ca_match.start()].strip()
    return text_clean


def _convert_currency_value(value, currency):
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    return round(val * _currency_rate(currency), 2)


def _parse_price(text):
    text = text.replace("\xa0", " ").strip()
    if "bis" in text.lower() or "to" in text.lower():
        parts = re.split(r"bis|to", text, flags=re.IGNORECASE)
        text = parts[0].strip()

    # Truncate anything in parentheses or after "ca." / "approx."
    text_clean = _strip_approx_price_text(text)

    currency = _detect_price_currency(text_clean)

    # Extract number
    match = re.search(r'\d+[\d.,\s]*', text_clean)
    if match:
        val_str = _normalize_price_number(match.group(0).strip())
        try:
            val = float(val_str)
            return _convert_currency_value(val, currency)
        except ValueError:
            return None
    val_str = _normalize_price_number(text_clean)
    try:
        return float(val_str)
    except ValueError:
        return None


def _is_delivery_speed_or_date(text):
    t_lower = text.lower()
    time_indicators = (
        "tage", "day", "werktag", "business day", "bis ", "am ",
        "est. delivery", "estimated", "lieferung bis", "lieferung am",
        "lieferung ca", "lieferung zwischen", "delivery between", "delivery by",
        "tägliche", "taegliche"
    )
    if any(w in t_lower for w in time_indicators):
        return True
    months_pattern = r"\b(?:jan|feb|mär|maer|apr|mai|jun|jul|aug|sep|okt|nov|dez|january|february|march|april|may|june|july|august|september|october|november|december)\b"
    if re.search(months_pattern, t_lower):
        return True
    return False


def _parse_shipping(text):
    text_clean = text.lower().strip()
    if not text_clean or any(w in text_clean for w in ("kostenlos", "free", "gratis")):
        return 0.0

    # Truncate anything in parentheses or after "ca." / "approx."
    text_clean = _strip_approx_price_text(text_clean)

    currency = _detect_price_currency(text_clean)

    # Extract number
    match = re.search(r'\d+[\d.,\s]*', text_clean)
    if match:
        val_str = _normalize_price_number(match.group(0).strip())
        try:
            val = float(val_str)
            return _convert_currency_value(val, currency) or 0.0
        except ValueError:
            return 0.0
    return 0.0


def _money_obj_eur(value):
    if value is None:
        return None
    return {"value": f"{float(value):.2f}", "currency": "EUR"}


def _parse_labeled_money(lines, label_patterns):
    labels = tuple(re.compile(p, re.IGNORECASE) for p in label_patterns)
    stop = re.compile(
        r"^(?:lieferung|delivery|zahlungen|payments|r[üu]ckgabe|returns|standort|item location|artikelzustand|condition)\b",
        re.IGNORECASE,
    )
    for idx, line in enumerate(lines):
        if not any(p.search(line) for p in labels):
            continue
        candidates = []
        after_label = re.sub(r"^.*?:", "", line, count=1).strip()
        if after_label and after_label != line:
            candidates.append(after_label)
        for nxt in lines[idx + 1: idx + 5]:
            if stop.search(nxt) and not re.search(r"(?:eur|€|gbp|£|usd|\$|\d+[,.]\d+)", nxt, re.IGNORECASE):
                break
            candidates.append(nxt)
        for candidate in candidates:
            if any(w in candidate.lower() for w in ("kostenlos", "free", "gratis")):
                return 0.0
            if re.search(r"(?:eur|€|gbp|£|usd|\$|\d+[,.]\d+)", candidate, re.IGNORECASE):
                value = _parse_price(candidate)
                if value is not None:
                    return value
    return None


def _extract_html_current_bid_price(html, soup=None):
    """Extract the live auction bid from eBay item HTML."""
    if not html:
        return None

    def from_currency_value(raw_value, currency="EUR"):
        try:
            value = float(str(raw_value).replace(",", "."))
        except (TypeError, ValueError):
            return None
        return round(value * _currency_rate(currency or "EUR"), 2)

    # eBay often embeds a dedicated currentBidPrice object even when the main
    # Product offer price is the Sofort-Kaufen value on hybrid listings.
    for field in ("currentBidPrice", "bidPrice"):
        pattern = rf'["\']{field}["\']\s*:\s*\{{(?P<body>.{{0,800}}?)\}}'
        for match in re.finditer(pattern, html, re.IGNORECASE | re.DOTALL):
            body = match.group("body")
            values = list(re.finditer(r'["\']value["\']\s*:\s*["\']?([0-9][0-9.,]*)["\']?', body, re.IGNORECASE))
            if not values:
                continue
            currency_match = re.search(r'["\']currency["\']\s*:\s*["\']([A-Z]{3})["\']', body, re.IGNORECASE)
            currency = currency_match.group(1) if currency_match else "EUR"
            for value_match in values:
                price = from_currency_value(value_match.group(1), currency)
                if price and price > 0:
                    return price

    if soup is None:
        soup = BeautifulSoup(html, "html.parser")

    for node in soup.find_all(class_=lambda c: c and "bid-price" in " ".join(c if isinstance(c, list) else [c]).lower()):
        price = _parse_price(node.get_text(" ", strip=True))
        if price and price > 0:
            return price

    page_lines = [line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip()]
    bid_label = re.compile(r"\b(?:gebot|gebote|bids?|bid)\b", re.IGNORECASE)
    buy_now_label = re.compile(r"\b(?:sofort|buy it now)\b", re.IGNORECASE)
    for idx, line in enumerate(page_lines):
        if not bid_label.search(line) or buy_now_label.search(line):
            continue
        for candidate in page_lines[idx: idx + 4]:
            if buy_now_label.search(candidate):
                break
            if re.search(r"(?:eur|gbp|usd|\$|[0-9][0-9.,]+\s*(?:eur|gbp|usd))", candidate, re.IGNORECASE):
                price = _parse_price(candidate)
                if price and price > 0:
                    return price
    return None


EBAY_API_CURRENCY_BY_MARKETPLACE = {
    "EBAY_DE": "EUR",
    "EBAY_AT": "EUR",
    "EBAY_FR": "EUR",
    "EBAY_IT": "EUR",
    "EBAY_ES": "EUR",
    "EBAY_NL": "EUR",
    "EBAY_BE": "EUR",
    "EBAY_IE": "EUR",
    "EBAY_US": "USD",
    "EBAY_GB": "GBP",
}

EBAY_API_COUNTRY_BY_MARKETPLACE = {
    "EBAY_DE": "DE",
    "EBAY_AT": "AT",
    "EBAY_FR": "FR",
    "EBAY_IT": "IT",
    "EBAY_ES": "ES",
    "EBAY_NL": "NL",
    "EBAY_BE": "BE",
    "EBAY_IE": "IE",
    "EBAY_US": "US",
    "EBAY_GB": "GB",
}


def _ebay_api_configured():
    return bool(EBAY_CLIENT_ID and EBAY_CLIENT_SECRET)


def _ebay_api_http_error(code):
    if code == 429:
        return "api_rate_limit"
    if code in (400, 401, 403):
        return "api_auth"
    return f"api_http_{code}"


def _get_ebay_api_token():
    global _ebay_api_token, _ebay_api_token_expiry
    if not _ebay_api_configured():
        return None, "api_not_configured"
    now = time.time()
    if _ebay_api_token and now < _ebay_api_token_expiry:
        return _ebay_api_token, None
    try:
        raw = f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode("utf-8")
        auth = base64.b64encode(raw).decode("ascii")
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.ebay.com/identity/v1/oauth2/token",
            data=body,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        token = data.get("access_token")
        if not token:
            return None, "api_auth"
        expires = int(data.get("expires_in") or 7200)
        _ebay_api_token = token
        _ebay_api_token_expiry = time.time() + max(60, expires - 120)
        return token, None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            logger.warning("eBay API token HTTP %s: %s", e.code, body[:300])
        except Exception:
            pass
        return None, _ebay_api_http_error(e.code)
    except Exception as e:
        logger.warning("eBay API token error: %s", e)
        return None, "api_network"


def _api_float(obj):
    if not obj:
        return None
    try:
        val = float(obj.get("value"))
        currency = obj.get("currency", "EUR")
        if currency and currency.strip().upper() != "EUR":
            val = round(val * _currency_rate(currency), 2)
        return val
    except (TypeError, ValueError, AttributeError):
        return None


def _api_shipping_cost(summary):
    costs = []
    for opt in summary.get("shippingOptions") or []:
        cost = _api_float(opt.get("shippingCost"))
        if cost is not None:
            costs.append(cost)
    return min(costs) if costs else 0.0


def _api_location(summary):
    loc = summary.get("itemLocation") or {}
    parts = []
    pc = loc.get("postalCode")
    city = loc.get("city")
    country = loc.get("country")
    if pc:
        parts.append(str(pc))
    if city:
        parts.append(str(city))
    if country:
        parts.append(str(country))
    return ", ".join(parts)


def _api_item_id(summary):
    raw = str(summary.get("itemId") or "")
    url = str(summary.get("itemWebUrl") or "")
    m = re.search(r"\|(\d{6,})\|", raw)
    if m:
        return m.group(1)
    m = re.search(r"/itm/(?:[^/]+/)?(\d{6,})", url)
    if m:
        return m.group(1)
    m = re.search(r"\d{6,}", raw)
    return m.group(0) if m else raw


def _build_ebay_api_query(search):
    q = _intent_query(search)
    if not q:
        q = _build_smart_search_query(search)
    if not search.get('_api_query_batch'):
        q = re.sub(r"\bred\s*magic\b", '(redmagic, "red magic")', q, flags=re.IGNORECASE)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _build_ebay_api_params(search, market=None):
    if market is None:
        market = EBAY_MARKETPLACE_ID
    filters = search.get("filters", {}) or {}
    sort_param = "newlyListed"
    if filters.get("sort") == "price_asc":
        sort_param = "price"
    elif filters.get("sort") == "ending_soon":
        sort_param = "endingSoonest"
    params = {
        "q": _build_ebay_api_query(search),
        "limit": "200",
        "sort": sort_param,
        "fieldgroups": "EXTENDED",
    }

    category = filters.get("category", "all")
    query_norm = _normalize(_intent_query(search))
    eff_category = _effective_category(category, query_norm)
    intent = _search_intent(search)
    pin_category = not (intent and intent.get("kind") == "gpu_pc")

    if pin_category and category and category != "all":
        device_cat_id = EBAY_DEVICE_CATEGORY_IDS.get(eff_category)
        if device_cat_id:
            params["category_ids"] = device_cat_id
        elif eff_category and eff_category != "all":
            cat_id = _category_id(eff_category)
            if cat_id:
                params["category_ids"] = cat_id

    filter_parts = []
    currency = EBAY_API_CURRENCY_BY_MARKETPLACE.get(market, "EUR")
    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    if min_price is not None or max_price is not None:
        lo = str(min_price) if min_price is not None else ""
        hi = str(max_price) if max_price is not None else ""
        filter_parts.append(f"price:[{lo}..{hi}]")
        filter_parts.append(f"priceCurrency:{currency}")

    cond = filters.get("condition", "any")
    if cond == "new":
        filter_parts.append("conditions:{NEW}")
    elif cond == "used":
        filter_parts.append("conditions:{USED}")
    # "any" omits the condition filter. REFURBISHED is not a valid Browse
    # conditions enum; the API ignores that entire filter and returns 12002.
    # Refurbishment/defect policy is still enforced on each returned candidate.

    lt = filters.get("listing_type", "all")
    buying_map = {
        "buy_now": "FIXED_PRICE",
        "buy_now_offer": "FIXED_PRICE",
        "auction": "AUCTION",
        "offer": "BEST_OFFER",
    }
    if lt in buying_map:
        buying_options = [buying_map[lt]]
        filter_parts.append(f"buyingOptions:{{{'|'.join(buying_options)}}}")
    else:
        filter_parts.append("buyingOptions:{FIXED_PRICE|AUCTION}")

    st = filters.get("seller_type", "any")
    seller_map = {
        "private": "INDIVIDUAL",
        "commercial": "BUSINESS",
    }
    if st in seller_map:
        filter_parts.append(f"sellerAccountTypes:{{{seller_map[st]}}}")

    loc = filters.get("location", "de")
    if loc == "de":
        filter_parts.append("itemLocationCountry:DE")
    elif loc == "worldwide":
        filter_parts.append("itemLocationRegion:WORLDWIDE")
    elif loc == "eu":
        filter_parts.append("itemLocationRegion:EUROPEAN_UNION")

    if filter_parts:
        params["filter"] = ",".join(filter_parts)
    return params


def _ebay_end_user_context(market):
    country = EBAY_API_COUNTRY_BY_MARKETPLACE.get(market, "DE")
    postal_code = str(config.get_settings().get("user_zip") or "").strip()
    value = f"country={country}"
    if postal_code:
        value += ",zip=" + postal_code
    return "contextualLocation=" + urllib.parse.quote(value, safe="")


def _is_auction_only_search(search):
    return ((search or {}).get("filters") or {}).get("listing_type") == "auction"


# One extra auction SERP per product whose auction buckets came back empty from
# the shared mixed page. Statistics has a 45 min budget — never unbounded.
_MAX_AUCTION_REFILLS = 10


# Once Browse API hard-429s, stop calling it for the rest of this process —
# multi-product stats was burning 500+ 429s and every bucket became "Не найдено".
_ebay_api_circuit_open = False
_ebay_api_circuit_reason = None


def fetch_ebay_api_ex(search, force=False):
    """Browse API on the same configured marketplace as the phone.

    Force bypasses scheduling, never the provider's quota/cooldown.
    """
    if len(_build_ebay_api_query(search))>100:
        return [], 'api_query_too_long'
    token, err = _get_ebay_api_token()
    if err:
        return [], err
    market = EBAY_MARKETPLACE_ID
    target = (search.get("id", ""), market)
    if not force and target not in _allowed_api_targets_this_run:
        return [], "api_deferred"
    if not browse_access.acquire():
        return [], "api_rate_limit"
    _allowed_api_targets_this_run.discard(target)
    params = _build_ebay_api_params(search, market=market)
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search?" + urllib.parse.urlencode(params)
    country = EBAY_API_COUNTRY_BY_MARKETPLACE.get(market, "DE")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "X-EBAY-C-MARKETPLACE-ID": market,
        "X-EBAY-C-ENDUSERCTX": _ebay_end_user_context(market),
    })
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT[1]) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if data.get("warnings"):
            logger.warning("eBay did not fully apply search parameters for %s", search.get("query"))
            return [], "api_filters_ignored"
        record_search_run(search.get("id", ""), market)
        items = parse_ebay_api_results(data)
        logger.info("  %s -> %d items via eBay Browse API (%s)", search.get("query"), len(items), market)
        return items, None
    except urllib.error.HTTPError as e:
        if e.code == 429:
            browse_access.pause(e.headers.get("Retry-After") if e.headers else None)
        logger.warning("eBay Browse HTTP %s for %s", e.code, search.get("query"))
        return [], _ebay_api_http_error(e.code)
    except Exception as e:
        logger.warning("eBay Browse search failed for %s: %s", search.get("query"), e)
        return [], "api_network"



def parse_ebay_api_results(data):
    items = []
    for summary in data.get("itemSummaries") or []:
        title = summary.get("title") or ""
        price = _api_float(summary.get("price")) or _api_float(summary.get("currentBidPrice"))
        if not title or price is None:
            continue
        opts = set(summary.get("buyingOptions") or [])
        seller = summary.get("seller") or {}
        feedback_percent = seller.get("feedbackPercentage")
        try:
            feedback_percent = float(feedback_percent)
        except (TypeError, ValueError):
            feedback_percent = 0.0
        try:
            feedback_score = int(seller.get("feedbackScore") or 0)
        except (TypeError, ValueError):
            feedback_score = 0
        image = summary.get("image") or {}
        shipping_cost = _api_shipping_cost(summary)
        is_multivariation = summary.get("itemGroupType") == "SELLER_DEFINED_VARIATIONS"

        is_pickup_only = False
        pickup_opts = summary.get("pickupOptions") or []
        shipping_opts = summary.get("shippingOptions") or []
        if pickup_opts or summary.get("localPickup") == True:
            has_delivery = False
            for opt in shipping_opts:
                stype = opt.get("shippingType", "").upper()
                scode = opt.get("shippingServiceCode", "").lower()
                if stype != "LOCAL_PICKUP" and "pickup" not in scode and "local" not in scode:
                    has_delivery = True
                    break
            if not has_delivery:
                is_pickup_only = True

        try:
            bids_count = int(summary.get("bidCount") or 0)
        except (TypeError, ValueError):
            bids_count = 0

        time_left_str = ""
        end_date_str = summary.get("itemEndDate")
        seconds_left = _parse_end_date_to_seconds(end_date_str)
        if seconds_left is not None and seconds_left > 0:
            time_left_str = _format_time_left_from_seconds(seconds_left)

        api_auc_price = _api_float(summary.get("currentBidPrice")) if "AUCTION" in opts else None
        api_bin_price = _api_float(summary.get("price")) if "FIXED_PRICE" in opts else None
        if "AUCTION" in opts and "FIXED_PRICE" in opts:
            auc_price = api_auc_price or price
            bin_price = api_bin_price or price
        elif "AUCTION" in opts:
            auc_price = price
            bin_price = None
        else:
            auc_price = None
            bin_price = price

        items.append({
            "item_id": _api_item_id(summary),
            "source": "api",
            "title": title,
            "price": price,
            "auc_price": auc_price,
            "bin_price": bin_price,
            "_was_hybrid": "AUCTION" in opts and "FIXED_PRICE" in opts,
            "shipping_cost": shipping_cost,
            "total_price": price + shipping_cost,
            "image_url": image.get("imageUrl", ""),
            "url": summary.get("itemWebUrl", ""),
            "buy_now": "FIXED_PRICE" in opts,
            "best_offer": "BEST_OFFER" in opts,
            "auction": "AUCTION" in opts,
            "bids_count": bids_count,
            "condition": summary.get("condition", ""),
            "seller_name": seller.get("username", ""),
            "seller_rating_count": feedback_score,
            "seller_rating_percent": feedback_percent,
            "seller_type": "unknown",
            "top_rated": bool(summary.get("topRatedBuyingExperience")),
            "location": _api_location(summary),
            "time_left": time_left_str,
            "is_multivariation": is_multivariation,
            "is_pickup_only": is_pickup_only,
        })
    return items


def _html_buying_options(soup):
    """Read this listing's purchase actions, excluding prose and recommendations."""
    action_labels = {button.get_text(" ", strip=True).lower() for button in soup.select("a.ux-call-to-action, button.ux-call-to-action")}
    return [option for option, labels in (("FIXED_PRICE", {"sofort-kaufen", "buy it now"}),
                                          ("AUCTION", {"bieten", "place bid"}),
                                          ("BEST_OFFER", {"preisvorschlag senden", "make offer", "make an offer"}))
            if action_labels & labels]


def _html_auction_end(soup, now=None):
    """Own visible ending time, corroborated by its countdown, minute precision."""
    from datetime import datetime, timezone, timedelta
    from zoneinfo import ZoneInfo
    timer = soup.select_one(".ux-timer")
    if not timer:
        return None
    relative = timer.select_one(".ux-timer__text")
    exact = timer.select_one(".ux-timer__time-left")
    if not relative or not exact:
        return None
    text = relative.get_text(" ",strip=True).lower()
    def count(pattern):
        match = re.search(pattern,text)
        return int(match[1]) if match else 0
    days=count(r"(\d+)\s*(?:tage?|t|days?|d)(?=\s|\d|$)")
    hours=count(r"(\d+)\s*(?:stunden?|std|hours?|h)(?=\s|\d|$)")
    minutes=count(r"(\d+)\s*(?:minuten?|min|minutes?|m)(?=\s|\d|$)")
    rough=days*1440+hours*60+minutes
    if rough<=0 or rough>366*1440:
        return None
    weekdays=dict(zip(("montag","dienstag","mittwoch","donnerstag","freitag","samstag","sonntag"),range(7)))
    weekdays.update(zip(("monday","tuesday","wednesday","thursday","friday","saturday","sunday"),range(7)))
    match=re.search(r"("+"|".join(weekdays)+r")\s*,?\s*(\d{1,2}):(\d{2})",exact.get_text(" ",strip=True).lower())
    if not match:
        return None
    now = now or datetime.now(timezone.utc)
    local=now.astimezone(ZoneInfo("Europe/Berlin"))
    try:
        target=(local+timedelta(days=(weekdays[match[1]]-local.weekday())%7)).replace(hour=int(match[2]),minute=int(match[3]),second=59,microsecond=0)
    except ValueError:
        return None
    if target<=local:
        target+=timedelta(days=7)
    def delta():
        return (target.astimezone(timezone.utc)-now.astimezone(timezone.utc)).total_seconds()/60
    while delta()+1440<rough:
        target+=timedelta(days=7)
    difference=delta()-rough
    tolerance=2 if re.search(r"\d+\s*(?:minuten?|min|minutes?|m)(?=\s|\d|$)",text) else 61 if re.search(r"\d+\s*(?:stunden?|std|hours?|h)(?=\s|\d|$)",text) else 1441
    if not -3<=difference<=tolerance:
        return None
    return target.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_item_details_html(item_id):
    """Fetches item details (description, exact end date, etc.) by scraping the item page."""
    session = _get_ebay_session()
    host = _ebay_active_host or "ebay.de"
    url = f"https://www.{host}/itm/{item_id}"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": f"https://www.{host}/",
    }
    logger.info("Scraping item page details for item %s via HTML", item_id)
    try:
        resp = session.get(url, headers=headers, timeout=15)
    except Exception as e:
        logger.warning("_fetch_item_details_html: network error for %s: %s", item_id, e)
        return _fetch_item_details_browser(item_id)

    if resp.status_code != 200 and host == "ebay.de":
        try:
            mobile_url = f"https://m.{host}/itm/{item_id}"
            resp = session.get(mobile_url, headers=headers, timeout=15)
        except Exception as e:
            logger.warning("_fetch_item_details_html: mobile retry network error for %s: %s", item_id, e)

    if resp.status_code != 200:
        logger.warning("_fetch_item_details_html: HTTP %d for item %s", resp.status_code, item_id)
        return _fetch_item_details_browser(item_id)

    html = resp.text or ""
    challenge_markers = (
        "pardon our interruption",
        "bitte entschuldigen sie die störung",
        "splashui/captcha",
        "are you a robot",
        "automated access",
        "/splashui/",
        "verify you are a human",
        "checking your browser",
        "access denied",
    )
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("title")
    title_text = title_el.get_text(strip=True) if title_el else ""
    if "/splashui/" in resp.url.lower() or any(m in title_text.lower() for m in challenge_markers) or any(m in html[:8000].lower() for m in challenge_markers):
        logger.warning("_fetch_item_details_html: challenge page hit for item %s", item_id)
        return None

    details = _parse_item_details_html(html, session=session, host=host)
    if not _clean_description(details.get("description") or "").strip() and not details.get("estimatedAvailabilities"):
        return _fetch_item_details_browser(item_id)
    return details


def _fetch_item_details_browser(item_id):
    """One bounded ordinary browser visit; never solve or retry a challenge."""
    if os.environ.get("EBAY_HTML_PLAYWRIGHT", "1").lower() in ("0", "false", "no"):
        return None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            try:
                page = browser.new_page(locale="de-DE")
                page.goto(f"https://www.ebay.de/itm/{item_id}", wait_until="domcontentloaded", timeout=25000)
                if _is_challenge_html(page.content(), page.url):
                    return None
                # Wait only for the seller's own iframe, excluding reviews/recs.
                page.locator("#desc_ifr").scroll_into_view_if_needed(timeout=6000)
                frame = page.frame_locator("#desc_ifr")
                frame.locator("body").wait_for(state="visible", timeout=6000)
                desc = frame.locator("body").inner_html(timeout=6000)
                if not _clean_description(desc).strip():
                    return None
                return _parse_item_details_html(page.content(), description=desc)
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("HTML browser details unavailable for %s: %s", item_id, type(exc).__name__)
        return None


def _parse_item_details_html(html, description=None, session=None, host="ebay.de"):
    """Parse own listing fields. Characteristics cannot substitute seller text."""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("h1.x-item-title, .x-item-title__mainTitle") or soup.find("title")
    title_text = title_el.get_text(" ", strip=True) if title_el else ""
    headers = {}

    is_mv = any(k in html for k in ("x-msku", "vi-msku", "msku-select", "itm-variation", "x-msku-evo"))
    item_group_type = "SELLER_DEFINED_VARIATIONS" if is_mv else None

    price_val = None
    currency = "EUR"
    current_bid_price = None
    end_date_iso = None

    schema_scripts = soup.find_all("script", type="application/ld+json")
    for s in schema_scripts:
        try:
            data = json.loads(s.text or s.string or "")
            products = []
            if isinstance(data, dict):
                if data.get("@type") == "Product":
                    products.append(data)
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Product":
                        products.append(item)

            for prod in products:
                offers = prod.get("offers")
                if offers:
                    if isinstance(offers, dict):
                        price_val = offers.get("price")
                        currency = offers.get("priceCurrency") or "EUR"
                        end_date_iso = offers.get("validThrough") or offers.get("priceValidUntil")
                    elif isinstance(offers, list) and len(offers) > 0:
                        price_val = offers[0].get("price")
                        currency = offers[0].get("priceCurrency") or "EUR"
                        end_date_iso = offers[0].get("validThrough") or offers[0].get("priceValidUntil")
                if end_date_iso:
                    break
        except Exception:
            pass

    if not end_date_iso:
        for script in soup.find_all("script"):
            content = script.text or script.string or ""
            if not content:
                continue
            m = re.search(r'["\'](?:validThrough|priceValidUntil|endDate|endDateTime|endTime)["\']\s*:\s*["\']([^"\']+)["\']', content)
            if m:
                end_date_iso = m.group(1)
                break
            m2 = re.search(r'["\'](?:endTime|endDateTime|endTimeStamp)["\']\s*:\s*(\d{10,13})', content)
            if m2:
                ts = int(m2.group(1))
                if ts > 1000000000000:
                    ts = ts / 1000.0
                from datetime import datetime, timezone
                end_date_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
                break

    # Raw HTML fallback for end date and price if structured parsing failed
    if not end_date_iso:
        m = re.search(r'["\'](?:validThrough|priceValidUntil|endDate|endDateTime|endTime)["\']\s*:\s*["\']([^"\']+)["\']', html)
        if m:
            end_date_iso = m.group(1)
        else:
            m2 = re.search(r'["\'](?:endTime|endDateTime|endTimeStamp)["\']\s*:\s*(\d{10,13})', html)
            if m2:
                ts = int(m2.group(1))
                if ts > 1000000000000:
                    ts = ts / 1000.0
                from datetime import datetime, timezone
                end_date_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    if price_val is None:
        m_price = re.search(r'["\']price["\']\s*:\s*["\']([\d.]+)["\']', html)
        if m_price:
            price_val = m_price.group(1)
            m_curr = re.search(r'["\']priceCurrency["\']\s*:\s*["\']([A-Z]{3})["\']', html)
            if m_curr:
                currency = m_curr.group(1)

    current_bid_price = _extract_html_current_bid_price(html, soup)

    desc_html = ""
    desc_ifr = soup.find("iframe", id="desc_ifr") or soup.find("iframe", attrs={"name":"desc_ifr"})
    if not desc_ifr:
        for iframe in soup.find_all("iframe"):
            src = iframe.get("src") or ""
            if "ViewItemDescV4" in src or "ebaydesc.com" in src:
                desc_ifr = iframe
                break

    if description is not None:
        desc_html = description
    elif desc_ifr:
        desc_src = desc_ifr.get("src") or ""
        if desc_src:
            if desc_src.startswith("//"):
                desc_src = "https:" + desc_src
            elif desc_src.startswith("/"):
                desc_src = f"https://www.{host}" + desc_src
            logger.info("Fetching description HTML from iframe: %s", desc_src)
            try:
                desc_headers = {
                    "User-Agent": headers["User-Agent"] if "User-Agent" in headers else "Mozilla/5.0",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
                desc_resp = (session or _get_ebay_session()).get(desc_src, headers=desc_headers, timeout=10)
                if desc_resp.status_code == 200:
                    desc_html = desc_resp.text or ""
                else:
                    logger.warning("Description iframe HTTP %d", desc_resp.status_code)
            except Exception as e:
                logger.warning("Failed to fetch description iframe: %s", e)
    else:
        desc_div = soup.find(id="desc_div") or soup.find(class_="vi-desc-main-container")
        if desc_div:
            desc_html = str(desc_div)

    # Buyer reviews (Produktbewertungen) are never seller description.
    if desc_html:
        desc_html = _strip_review_sections(desc_html)
    # Keep the description separate: specs-only pages remain unverified.
    aspects = []
    for term in soup.select("dt.ux-labels-values__labels"):
        value = term.find_next_sibling("dd")
        if value:
            name = term.get_text(" ", strip=True)
            text = value.get_text(" ", strip=True)
            if name and text:
                aspects.append({"name": name, "value": text})

    location_text = ""
    page_lines = [line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip()]
    shipping_cost = _parse_labeled_money(page_lines, (r"^versand\b", r"^shipping\b"))
    import_charges = _parse_labeled_money(page_lines, (r"^einfuhrabgaben\b", r"^import charges\b", r"^import fees\b"))
    for idx, line in enumerate(page_lines):
        m = re.match(r"^(?:Standort|Artikelstandort|Item location|Located in)\s*:?\s*(.+)$", line, re.IGNORECASE)
        if m and m.group(1).strip():
            location_text = m.group(1).strip()
            break
        if re.match(r"^(?:Standort|Artikelstandort|Item location|Located in)\s*:?\s*$", line, re.IGNORECASE):
            if idx + 1 < len(page_lines):
                location_text = page_lines[idx + 1].strip()
                break

    if end_date_iso:
        end_date_iso = end_date_iso.strip()
        if not end_date_iso.endswith("Z") and "+" not in end_date_iso and len(end_date_iso) >= 19:
            end_date_iso += ".000Z"
        elif end_date_iso.endswith("Z") and "." not in end_date_iso:
            end_date_iso = end_date_iso[:-1] + ".000Z"

    result = {
        "description": desc_html,
        "itemEndDate": end_date_iso,
        "title": title_text,
        "localizedAspects": aspects,
    }
    status = " ".join(el.get_text(" ", strip=True) for el in soup.select(".d-top-panel-message, .d-statusmessage__notice-live-region"))
    if re.search(r"dieses angebot.{0,160}beendet|this listing.{0,160}(?:ended|sold)", status, re.I):
        result["estimatedAvailabilities"] = [{"estimatedAvailabilityStatus":"UNAVAILABLE"}]
    condition = next((a["value"] for a in aspects if a["name"].lower() in ("artikelzustand", "condition")), "")
    if condition:
        result["condition"] = condition.split(":", 1)[0].strip()
    categories = []
    for link in soup.select("nav.breadcrumbs a[href], nav.breadcrumb a[href]"):
        match = re.search(r"/b/[^/]+/(\d+)/", link.get("href", ""))
        if match:
            categories.append(match.group(1))
    if categories:
        result["categoryId"] = categories[-1]
        result["categoryIdPath"] = "|".join(categories)
    if location_text:
        result["itemLocationText"] = location_text
    if item_group_type:
        result["itemGroupType"] = item_group_type
    if shipping_cost is not None:
        result["htmlShippingCost"] = _money_obj_eur(shipping_cost)
    if import_charges is not None:
        result["htmlImportCharges"] = _money_obj_eur(import_charges)
    if price_val is not None:
        result["price"] = {"value": str(price_val), "currency": currency}
    if current_bid_price is not None:
        result["currentBidPrice"] = _money_obj_eur(current_bid_price)
    # Purchase actions belong to this listing. Words in seller descriptions,
    # scripts or recommended listings cannot restore a removed purchase side.
    buying_options = _html_buying_options(soup)
    if "AUCTION" in buying_options:
        visible_end = _html_auction_end(soup)
        if visible_end:
            result["itemEndDate"] = visible_end
            result["htmlEndPrecision"] = "minute"
    primary = soup.select_one(".x-price-primary")
    primary_price = _parse_labeled_money(["price: " + primary.get_text(" ", strip=True)], (r"^price\b",)) if primary else None
    if primary_price is not None and (price_val is None or buying_options == ["AUCTION"]):
        result["price"] = _money_obj_eur(primary_price)
    if primary_price is not None and "AUCTION" in buying_options and "FIXED_PRICE" not in buying_options:
        result["currentBidPrice"] = _money_obj_eur(primary_price)
    if buying_options:
        result["buyingOptions"] = buying_options

    # Own seller identity must refresh the blacklist/type check after HTML.
    # Reviewer profiles and promoted shops elsewhere on the page are unrelated.
    card = soup.select_one(".x-sellercard-atf")
    name = card.select_one(".x-sellercard-atf__about-seller-item--seller-name a") if card else None
    if name and name.get_text(strip=True):
        seller = {"username": name.get_text(strip=True)}
        text = card.get_text(" ", strip=True)
        score = re.search(r"\(([\d.,\s]+)\)", text)
        if score:
            seller["feedbackScore"] = int(re.sub(r"\D", "", score.group(1)))
        percentage = re.search(r"([\d.,]+)%\s*(?:positive|positiv)", text, re.I)
        if percentage:
            seller["feedbackPercentage"] = float(percentage.group(1).replace(",", "."))
        if re.search(r"\b(?:gewerblich|business)\b", text, re.I):
            seller["sellerAccountType"] = "BUSINESS"
        elif re.search(r"\b(?:privat|private)\b", text, re.I):
            seller["sellerAccountType"] = "INDIVIDUAL"
        result["seller"] = seller

    return result


_item_details_cache = {}


def _fetch_item_details(item_id):
    """Read the complete seller description before classifying a candidate."""
    context = _ebay_end_user_context(EBAY_MARKETPLACE_ID)
    cache_key = (str(item_id), EBAY_MARKETPLACE_ID, context)
    cached = _item_details_cache.get(cache_key)
    if cached and time.time() - cached[0] < 120:
        return copy.deepcopy(cached[1])
    def html_details():
        global _runtime_html_fallback
        _runtime_html_fallback = True
        data = _fetch_item_details_html(item_id)
        if data and (_clean_description(data.get("description") or "").strip() or data.get("estimatedAvailabilities")):
            _item_details_cache[cache_key] = (time.time(), data)
            return copy.deepcopy(data)
        return None
    if not _ebay_api_configured() or EBAY_SOURCE == "html" or browse_access.is_paused() is True:
        return html_details()
    token, err = _get_ebay_api_token()
    if err:
        return None
    if not browse_access.acquire():
        return html_details()
    browse_id = f"v1|{item_id}|0"
    url = f"https://api.ebay.com/buy/browse/v1/item/{urllib.parse.quote(browse_id)}"
    country = EBAY_API_COUNTRY_BY_MARKETPLACE.get(EBAY_MARKETPLACE_ID, "DE")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
        "X-EBAY-C-ENDUSERCTX": context,
    })
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT[1]) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if not _clean_description(data.get("description") or "").strip():
            logger.warning("Description missing for item %s; leaving unverified", item_id)
            return html_details()
        _item_details_cache[cache_key] = (time.time(), data)
        return copy.deepcopy(data)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            browse_access.pause(e.headers.get("Retry-After") if e.headers else None)
            return html_details()
        logger.warning("eBay Browse details HTTP %s for item %s", e.code, item_id)
    except Exception as e:
        logger.warning("eBay Browse details unavailable for item %s: %s", item_id, e)
    return None


_REVIEW_NODE_SELECTORS = (
    "#rwid",
    "#reviews",
    "#review-section",
    "#rwid-tab",
    "[data-testid=x-reviews]",
    "[data-testid*=x-review]",
    ".reviews",
    ".x-reviews",
    ".reviews--section",
    ".testimonials",
)
_REVIEW_HEADING_RE = re.compile(
    r"produktbewertung|kundenrezension|artikelbewertung|"
    r"ratings\s*(?:and|&)\s*reviews|item reviews|product reviews|"
    r"\brezensionen\b",
    re.IGNORECASE,
)
_REVIEW_HEADING_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:produktbewertungen|kundenrezensionen|artikelbewertungen|"
    r"ratings\s*(?:and|&)\s*reviews|item reviews|product reviews|"
    r"rezensionen)\b"
)


def _strip_review_sections(html_or_text):
    """Drop buyer reviews. Defects / Stickdrift come from seller text only."""
    if not html_or_text:
        return html_or_text
    raw = html_or_text
    looks_html = "<" in raw and ">" in raw and re.search(r"</?\w+", raw)
    if looks_html:
        soup = BeautifulSoup(raw, "html.parser")
        for sel in _REVIEW_NODE_SELECTORS:
            for el in soup.select(sel):
                el.decompose()
        for h in soup.find_all(["h1", "h2", "h3", "h4"]):
            title = h.get_text(" ", strip=True) or ""
            if _REVIEW_HEADING_RE.search(title):
                parent = h.find_parent(["section", "article"]) or h.parent
                if parent is not None:
                    parent.decompose()
                else:
                    h.decompose()
        return str(soup)
    m = _REVIEW_HEADING_LINE_RE.search(raw)
    if m:
        return raw[: m.start()].rstrip()
    return raw


def _item_specifics_html(soup):
    """Item specifics / Merkmale — seller-authored, not reviews."""
    if soup is None:
        return ""
    chunks = []
    seen = set()
    for sel in (
        ".ux-labels-values",
        ".x-about-this-item",
        "[data-testid=x-about-this-item]",
        ".itemAttr",
        "#viTabs_0_is",
        ".ux-layout-section--features",
    ):
        for el in soup.select(sel):
            text = el.get_text(" ", strip=True)
            if not text or len(text) < 10:
                continue
            key = text[:180]
            if key in seen:
                continue
            seen.add(key)
            chunks.append(str(el))
            if len(chunks) >= 8:
                return "\n".join(chunks)
    return "\n".join(chunks)


def _clean_description(html_text):
    """Strips HTML tags and unescapes HTML entities from the description."""
    if not html_text:
        return ""
    html_text = _strip_review_sections(html_text)
    if "<" in html_text:
        soup = BeautifulSoup(html_text, "html.parser")
        for el in soup.select("script,style,noscript,.product_crosssell"):
            el.decompose()
        # Actual Office Partner template keeps legal warranty examples in a
        # separate tab. A hypothetical broken device there is not this item.
        for label in soup.select('.tabs label'):
            if re.fullmatch(r'rechtl\.?\s+hinweise|rechtliche\s+hinweise', label.get_text(' ',strip=True), re.I):
                panel = label.find_next_sibling()
                if panel is not None and 'panel' in (panel.get('class') or []):
                    panel.decompose()
        html_text = str(soup)
    else:
        crosssell = re.search(r"(?im)^[ \t]*das k[oö]nnte ihnen auch gefallen\b", html_text)
        if crosssell:
            html_text = html_text[:crosssell.start()]
    # Strip HTML tags
    text = re.sub(r'<[^>]+>', ' ', html_text)
    # Unescape HTML entities (like &amp;, &nbsp;)
    import html
    text = html.unescape(text)
    compact = re.sub(r"\s+", " ", text).strip().casefold()
    # Actual manufacturer listing 800461000257 supplies just "N/a".
    # Downloading that placeholder cannot complete the description check.
    if re.fullmatch(r"(?:n\s*[/.-]\s*a\.?|na|none|null|not available|no description(?: available)?|keine beschreibung(?: vorhanden)?|beschreibung folgt|description to follow|[-.?]+)", compact):
        return ""
    return text


def _has_damage_in_description(desc_norm):
    """Part+defect near each other in listing description (normalized text).

    Catches seller copy like:
      'funktionsfähig trotz beschädigter Rückseite'
      'Rückseite ist gesprungen, Display und Kamera ok'

    Does NOT use standalone defect words — seller boilerplate often says
    'warranty does not cover any damaged caused by the user' which wiped
    all Z80 Ultra candidates (14 SERP hits → 0 valid) while phones were fine.
    """
    if not desc_norm:
        return False
    # Strip warranty / policy boilerplate that mentions damage/cover generically.
    cleaned = re.sub(
        r"(?:warranty|garantie).{0,60}(?:does not cover|deckt nicht|nicht ab).{0,100}",
        " ",
        desc_norm,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"does not cover any damage\w*.{0,40}",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(?:wear and tear|normalen verschleiss|normalem verschleiss).{0,40}",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Require part + defect proximity only (not bare 'damaged'/'defekt').
    part_pattern = re.compile(rf"\b(?:{_DAMAGE_PART_RE}|halterung|scharnier|gelenk|kopfbuegel|kopfband|hinge|headband|earcup)\b", re.IGNORECASE)
    defect_pattern = re.compile(rf"\b(?:{_DAMAGE_DEFECT_RE})\b", re.IGNORECASE)
    neg_tokens = (
        "nicht", "kein", "keine", "keinen", "ohne", "no", "without", "free", "frei", "not",
        "unbeschaedig", "undamaged",
    )

    for m_part in part_pattern.finditer(cleaned):
        part_start, part_end = m_part.span()
        after_window = cleaned[part_end : part_end + 70]
        for m_defect in defect_pattern.finditer(after_window):
            between = after_window[: m_defect.start()]
            if not any(w in between for w in neg_tokens):
                return True

        before_window_start = max(0, part_start - 70)
        before_window = cleaned[before_window_start:part_start]
        for m_defect in defect_pattern.finditer(before_window):
            between = before_window[m_defect.end() :]
            if any(w in between for w in neg_tokens):
                continue
            abs_defect_start = before_window_start + m_defect.start()
            pre_defect = cleaned[max(0, abs_defect_start - 18) : abs_defect_start]
            if not any(w in pre_defect for w in neg_tokens):
                return True
    # Explicit cracked-back phrasing still blocked after cleaning.
    if re.search(
        r"\b(?:trotz\s+)?beschaedig\w*\s+(?:rueckseite|gehaeuse|back\s*glass|hinterglas)\b",
        cleaned,
    ) or re.search(
        r"\b(?:rueckseite|gehaeuse|back\s*glass|hinterglas)\s+(?:ist\s+)?(?:beschaedig\w*|gebrochen\w*|gesprungen\w*)\b",
        cleaned,
    ):
        return True
    return False


def _has_display_blemish(text_norm):
    # 257624149520 explicitly discloses a blemish in the middle of the panel.
    # A lid dent is cosmetic and "no panel blemishes" must remain allowed.
    panel=r"(?:display|bildschirm|screen|panel)"
    mark=r"(?:macke|macken|druckstelle|druckstellen)"
    patterns=(rf"\b{mark}\b[^.!?]{{0,45}}\b(?:auf|im|am|in|an)\s+(?:(?:dem|der|des|den|the)\s+)?{panel}\b",
              rf"\b{panel}\b\s+(?:hat|zeigt|mit|has)\s+(?:(?:eine?|kleine?|leichte?|sichtbare?)\s+){{0,3}}{mark}\b")
    for pattern in patterns:
        for match in re.finditer(pattern,text_norm):
            before=text_norm[max(0,match.start()-35):match.start()]
            if re.search(r"\b(?:kein\w*|ohne|no|without)\s+(?:\w+\s+){0,2}$",before):
                continue
            return True
    return False


def _has_charging_failure(text):
    # 227556560158: wireless charging works only at1%; USB charging is broken.
    # Mentioning MagSafe or omitting a charger is not itself a device fault.
    patterns = (
        r"\blaedt\s+nicht(?:\s+mehr)?(?:\s*(?:[.!?,;:]|$)|\s+(?:mit|ueber|am|an|per|via|durch|auf|richtig|zuverlaessig)\b)",
        r"\b(?:does\s+not|doesn['’]t|will\s+not|won['’]t|cannot|can['’]t|no\s+longer)\s+charg(?:e|ing)\b(?!\s+(?:slow|slowly|slower)\b)",
        r"\b(?:ladebuchse|ladeanschluss|ladeport|charging\s*port|usb[\s-]*c[\s-]*(?:port|anschluss|buchse))\b[^.!?]{0,40}\b(?:(?:funktioniert|geht)\s+nicht|does\s+not\s+work|doesn['’]t\s+work|not\s+working)\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _is_description_blocked(desc_html, category):
    """Checks the description for bad condition keywords or lifting screen/backcover patterns."""
    if not desc_html:
        return False
    desc_html = _strip_review_sections(desc_html)
    clean_desc = _clean_description(desc_html)
    desc_norm = _normalize(clean_desc)
    # 318450377900: the merchant restricts customer DATA after fulfillment,
    # not the phone. Remove only this data-subject clause, never a device lock.
    data_subject = r"(?:(?:ihre|die)\s+)?(?:personenbezogenen?\s+)?(?:kunden)?daten"
    data_use = r"(?:fuer\s+die\s+weitere\s+verwendung\s+)?"
    desc_norm = re.sub(rf"\b(?:werden\s+{data_subject}\s+{data_use}gesperrt|{data_subject}\s+werden\s+{data_use}gesperrt)\b", " ", desc_norm)
    # A private-sale exclusion of exchange is not an offer to swap the device.
    # Independently read on Sony ULT Wear auction 168749410138.
    policy = r"(?:ruecknahme|wandlung|tausch|preisminderung)"
    desc_norm = re.sub(rf"\b{policy}(?:\s*(?:,|oder|und|/)\s*{policy})*\s+(?:ist|sind|wird|werden)\s+ausgeschlossen\b", " ", desc_norm)
    # 168745903984 describes the failed PREVIOUS phone replaced by Apple.
    # Keep every statement about the device now being sold.
    desc_norm = re.sub(r"\b(?:da|weil)\s+mein\s+(?:vorheriges|altes)\s+(?:iphone|handy|smartphone|geraet)\b[^.!?\n]{0,180}\b(?:defekt|kaputt|beschaedig\w*)\b[^.!?\n]{0,100}\b(?:ersetzt|ausgetauscht)\b[^.!?\n]*[.!?]?", " ", desc_norm)
    # 298435287203: only the removable protector is broken, not the screen.
    # Remove just that explicit clause; any later device damage remains checked.
    desc_norm = re.sub(r"\b(?:nur|lediglich|only)\s+(?:(?:das|die|der|the)\s+)?(?:panzerglas|schutzglas|schutzfolie|screen\s*protector|tempered\s*glass)\b[^.!?\n]{0,60}?\b(?:kaputt|gebrochen\w*|gesprungen\w*|beschaedig\w*|gerissen\w*|crack(?:ed|s)?|broken|damaged)\b", " ", desc_norm)
    # A precise denial of back-glass replacement must not trigger the generic
    # spare-part noun. Remove only that noun; preserve every later defect.
    desc_norm = re.sub(r"\b(?:rueckglas|hinterglas|backglass)\b(?=\s+(?:(?:wurde|was)\s+)?(?:nie|nicht|never|not)\s+(?:(?:aus)?getauscht|ersetzt|repariert|replaced)\b)", " ", desc_norm)

    if _has_charging_failure(desc_norm):
        return True
    # 227554664933: recurring SIM-Fehler persists with a newly supplied SIM.
    sim_error = r"\bsim[\s-]*(?:fehler|errors?)\b"
    sim_error_text = re.sub(rf"\b(?:kein\w*|ohne|no|without)\s+{sim_error}", " ", desc_norm)
    if re.search(sim_error, sim_error_text):
        return True
    # A working eSIM does not make a failed physical SIM reader defect-free.
    # PS5 Pro 137809113124 includes a controller whose touchpad cannot swipe.
    if re.search(r"\btouchpad\b.{0,180}\bnicht\s+als\s+(?:fingerwisch|wisch|touch)", desc_norm) or re.search(r"\b(?:touchpad|touchscreen|fingerabdrucksensor|fingerprint\s*(?:reader|sensor))\b[^.!?]{0,60}\b(?:funktioniert|reagiert|geht)\s+nicht\b", desc_norm):
        return True
    if re.search(r"\bsim(?:\s*(?:karten?|cards?))?\b[^.!?]{0,80}\b(?:nicht(?:\s+mehr)?\s+(?:erkannt|gelesen)|(?:not|no longer)\s+(?:recognized|recognised|detected|working))\b", desc_norm) or re.search(r"\b(?:erkennt|erkennen)\s+(?:keine|keinen|nicht)\s+.{0,20}\bsim\b", desc_norm):
        return True

    desc_norm = _strip_negated_condition_terms(desc_norm)
    if _has_display_blemish(desc_norm):
        return True
    if _has_damage_in_description(desc_norm):
        logger.info("Description blocked due to damage check (part + defect words)")
        return True

    # Stickdrift often only appears in seller text, not SERP title
    # e.g. «Der linke Stick hat einen leichten Stickdrift»
    if _has_stickdrift_problem(desc_norm):
        logger.info("Description blocked due to Stickdrift / abgenutzte Sticks")
        return True

    if _is_display_replacement_description(desc_norm):
        logger.info("Description blocked due to display/screen replacement pattern")
        return True

    # 1. Check for bad condition words/phrases
    for w in BAD_CONDITION_WORDS:
        if w in ("tausch", "tauschen") and re.search(r"\b(?:kein|keine|keinen|nicht|no)\s+(?:um)?tausch\b|\bumtausch\b", desc_norm):
            continue
        if _has_term(desc_norm, w):
            logger.info("Description blocked due to bad condition word/phrase: '%s'", w)
            return True

    # 2. Check for screen/backcover lifting/loose/separation patterns
    if re.search(r"\b(?:screen|display|backcover|glass|glas|rueckseite)\b.*\b(?:lifted|lifting|loose|geloest|steht\s+ab|lose|abgeloest|abgeht)\b", desc_norm):
        logger.info("Description blocked due to screen/backcover lifting pattern 1")
        return True
    if re.search(r"\b(?:lifted|lifting|loose|geloest|steht\s+ab|lose|abgeloest|abgeht)\b.*\b(?:screen|display|backcover|glass|glas|rueckseite)\b", desc_norm):
        logger.info("Description blocked due to screen/backcover lifting pattern 2")
        return True

    return False


def _details_search_text(details):
    if not details:
        return ""
    parts = []
    # Keep this scoped to listing metadata. The full eBay description iframe can
    # include promoted/recommended items and other page chrome; description risk
    # is handled separately by _is_description_blocked().
    for key in ("title", "shortDescription", "subtitle", "itemLocationText", "condition", "itemCondition"):
        val = details.get(key)
        if val:
            parts.append(str(val))
    for key in ("categoryPath", "categoryIdPath", "categoryName"):
        val = details.get(key)
        if val:
            parts.append(str(val))
    for aspect in details.get("localizedAspects") or []:
        if not isinstance(aspect, dict):
            continue
        name = aspect.get("name")
        value = aspect.get("value")
        if name or value:
            parts.append(f"{name or ''} {value or ''}")
    loc = _api_location(details)
    if loc:
        parts.append(loc)
    return " ".join(parts)


def _is_details_blocked(details, search):
    if not details:
        return False
    filters = search.get("filters", {}) or {}
    query_norm = _normalize(search.get("query", ""))
    category = _effective_category(filters.get("category", "all"), query_norm)
    details_norm = _normalize(_details_search_text(details))
    if not details_norm:
        return False
    condition_text = _strip_negated_condition_terms(details_norm)
    if any(_has_term(condition_text, w) for w in BAD_CONDITION_WORDS):
        logger.info("Details blocked due to bad condition text")
        return True
    if details_norm in BAD_CONDITIONS:
        logger.info("Details blocked due to bad condition value")
        return True
    if category == "phones":
        if any(_has_term(details_norm, w) for w in REFURBISHED_CONDITION_WORDS):
            logger.info("Phone details blocked due to refurbished condition")
            return True
        phone_title_norm = _normalize(" ".join(
            str(details.get(k) or "") for k in ("title", "subtitle")
        ))
        if phone_title_norm and _is_phone_accessory_title(phone_title_norm):
            logger.info("Details blocked due to phone accessory/part title")
            return True
        if phone_title_norm and _is_category_blocked_title(phone_title_norm, category, query_norm):
            logger.info("Details blocked due to phone damage/part title")
            return True
        return False
    purpose_title = _normalize(" ".join(str(details.get(k) or "") for k in ("title", "subtitle")))
    if _is_category_blocked_title(purpose_title, category, query_norm):
        logger.info("Details blocked due to category/accessory/damage text")
        return True
    if category == "headphones":
        if re.search(r"\b(?:produktart|type)\s+(?:earmuffs?|ear\s+muffs?|gehoerschuetzer|gehoerschutz)\b", details_norm):
            logger.info("Details blocked: headphone listing is earmuffs/ear protectors")
            return True
    return False


def _seller_trust(rating_count, rating_percent, top_rated=False):
    if top_rated and rating_count >= 3:
        return "trusted"
    if rating_count >= 3 and rating_percent >= 95:
        return "trusted"
    if rating_count >= 1 and rating_percent >= 90:
        return "newbie"
    return "risky"


def _trust_emoji(trust):
    if trust == "trusted":
        return "✅"
    if trust == "newbie":
        return "⚠️"
    return "⚠️❗️"


def _is_eu(location_text):
    code = _country_code_from_location(location_text)
    if code and code in COUNTRY_INFO:
        return COUNTRY_INFO[code][2]
    loc = location_text.lower().strip()
    # Known non-EU countries that must NOT match
    non_eu = ("großbritannien", "grossbritannien", "great britain", "united kingdom",
              "uk", "england", "schottland", "scotland", "wales",
              "schweiz", "switzerland", "norwegen", "norway",
              "usa", "united states", "china", "japan", "türkei", "turkey",
              "indien", "india", "australien", "australia", "kanada", "canada")
    if any(n in loc for n in non_eu):
        return False
    # Only match full words or long country names
    for country in EU_COUNTRIES:
        if len(country) <= 2:
            # Short codes: must be exact word boundary to avoid false matches (like "ie" in "grossbritannien")
            if re.search(rf"\b{re.escape(country)}\b", loc):
                return True
        else:
            if country in loc:
                return True
    return False


def _is_clearly_non_germany_location(location_text):
    code = _country_code_from_location(location_text)
    if code:
        return code != "DE"
    loc = _normalize(location_text)
    non_de_terms = (
        "grossbritannien", "great britain", "united kingdom", "uk", "england",
        "schottland", "scotland", "wales", "oesterreich", "osterreich", "austria",
        "frankreich", "france", "italien", "italy", "spanien", "spain",
        "niederlande", "netherlands", "belgien", "belgium", "polen", "poland",
        "portugal", "griechenland", "greece", "tschechien", "czech",
        "schweden", "sweden", "daenemark", "danemark", "denmark",
        "finnland", "finland", "ungarn", "hungary", "rumaenien", "rumanien",
        "romania", "bulgarien", "bulgaria", "kroatien", "croatia",
        "slowakei", "slovakia", "slowenien", "slovenia", "litauen", "lithuania",
        "lettland", "latvia", "estland", "estonia", "luxemburg", "luxembourg",
        "malta", "zypern", "cyprus", "schweiz", "switzerland", "norwegen",
        "norway", "usa", "united states", "china", "japan", "tuerkei",
        "turkey", "indien", "india", "australien", "australia", "kanada",
        "canada",
    )
    if any(term in loc for term in non_de_terms):
        return True
    return re.search(r"\b(?:at|fr|it|es|nl|be|pl|pt|gr|cz|se|dk|fi|hu|ro|bg|hr|sk|si|lt|lv|ee|lu|ch|no|gb|uk|us|cn|jp|tr|in|au|ca)\b", loc) is not None


def _is_germany_location(location_text):
    code = _country_code_from_location(location_text)
    if code:
        return code == "DE"
    loc = _normalize(location_text)
    return _has_term(loc, "deutschland") or _has_term(loc, "germany")


def _looks_like_geo_shipping_for_german_item(shipping_cost, location_text):
    if shipping_cost is None:
        return False
    try:
        shipping = float(shipping_cost)
    except (TypeError, ValueError):
        return False
    return shipping > 80.0 and _is_germany_location(location_text)


def _get_api_shipping_and_import(details):
    shipping_cost = _api_float(details.get("htmlShippingCost"))
    import_charges = _api_float(details.get("htmlImportCharges"))
    shipping_opts = details.get("shippingOptions") or []
    if shipping_opts:
        min_opt = None
        min_cost = None
        for opt in shipping_opts:
            cost = _api_float(opt.get("shippingCost"))
            if cost is not None:
                if min_cost is None or cost < min_cost:
                    min_cost = cost
                    min_opt = opt
        if min_opt:
            if shipping_cost is None:
                shipping_cost = min_cost
            opt_import = _api_float(min_opt.get("importCharges"))
            if import_charges is None:
                import_charges = opt_import
    return shipping_cost, import_charges


def _shipping_estimate_matches_destination(details, settings, cost):
    """An API quote for the actual destination can replace even a stale fee."""
    country = str(settings.get("user_country") or "de").upper()
    postal_code = str(settings.get("user_zip") or "").strip()
    for option in details.get("shippingOptions") or []:
        destination = option.get("shipToLocationUsedForEstimate") or {}
        if (option.get("shippingCostType") in ("FIXED", "CALCULATED")
                and _api_float(option.get("shippingCost")) == cost
                and destination.get("country") == country
                and (not postal_code or destination.get("postalCode") == postal_code)):
            return True
    return False


def _calculate_total(item, settings, details=None):
    """Calculate total price including import duties for non-EU items.

    Supports separate calculation for bin_price and auc_price in hybrid listings.
    """
    if details:
        buying_options = details.get("buyingOptions") or []
        if buying_options:
            # Preserve a selected hybrid side only while it is still offered.
            # After the first bid eBay may remove Buy It Now: its API `price`
            # then represents the bid, never a refreshed fixed purchase price.
            is_stashed_bin = item.get("buy_now") and not item.get("auction")
            is_stashed_auc = item.get("auction") and not item.get("buy_now")
            selected_side_available = (is_stashed_bin and "FIXED_PRICE" in buying_options) or (is_stashed_auc and "AUCTION" in buying_options)
            if not selected_side_available:
                item["buy_now"] = "FIXED_PRICE" in buying_options
                item["auction"] = "AUCTION" in buying_options
                if item.get("buy_now") and item.get("auction"):
                    item["_was_hybrid"] = True
            item["best_offer"] = "BEST_OFFER" in buying_options

        api_price = _api_float(details.get("price"))
        api_auc_price = _api_float(details.get("currentBidPrice"))

        # For stashed pure items, only update their relevant active price
        if item.get("buy_now") and not item.get("auction"):
            if api_price is not None:
                item["price"] = api_price
                item["bin_price"] = api_price
        elif item.get("auction") and not item.get("buy_now"):
            if api_auc_price is not None:
                item["price"] = api_auc_price
                item["auc_price"] = api_auc_price
            elif (not item.get("_was_hybrid") or buying_options and "FIXED_PRICE" not in buying_options) and api_price is not None:
                # Only use details price for pure auction if it wasn't hybrid originally
                item["price"] = api_price
                item["auc_price"] = api_price
        else:
            # General/hybrid/unseparated item: update both prices
            if item.get("buy_now") and api_price is not None:
                item["bin_price"] = api_price
            if item.get("auction") and api_auc_price is not None:
                item["auc_price"] = api_auc_price
            elif item.get("auction") and api_price is not None and not item.get("buy_now"):
                item["auc_price"] = api_price

            if item.get("buy_now") and item.get("bin_price") is not None:
                item["price"] = item["bin_price"]
            else:
                item["price"] = item.get("auc_price") or item.get("price")

        api_loc = _api_location(details) or details.get("itemLocationText", "")
        if api_loc:
            item["location"] = api_loc

        api_shipping, _ = _get_api_shipping_and_import(details)
        verified_delivery = _shipping_estimate_matches_destination(details, settings, api_shipping)
        try:
            existing_shipping = float(item.get("shipping_cost") or 0.0)
        except Exception:
            existing_shipping = 0.0
        if not verified_delivery and _looks_like_geo_shipping_for_german_item(api_shipping, item.get("location", "")):
            logger.info(
                "Ignoring geo-inflated shipping %.2f for German item %s",
                float(api_shipping),
                item.get("item_id"),
            )
        elif api_shipping is not None and (verified_delivery or api_shipping > 0 or existing_shipping <= 0):
            item["shipping_cost"] = api_shipping

    shipping = item.get("shipping_cost") or 0.0

    def get_import_charges(price_val):
        if settings.get("warn_non_eu") and item.get("location") and not _is_eu(item["location"]):
            actual_import = item.get("actual_import_charges")
            if details:
                _, actual_import = _get_api_shipping_and_import(details)
                if actual_import is not None:
                    item["actual_import_charges"] = actual_import
            if actual_import is not None:
                return round(actual_import, 2)
            else:
                base = price_val + shipping
                vat = base * float(settings.get("non_eu_tax_rate", 0.19))
                customs = base * 0.04
                handling = 5.0
                return round(vat + customs + handling, 2)
        return 0.0

    # Calculate Buy It Now total
    if item.get("buy_now") and item.get("bin_price") is not None:
        bin_price = item["bin_price"]
        imp = get_import_charges(bin_price)
        item["bin_import_charges"] = imp
        item["bin_total_price"] = round(bin_price + shipping + imp, 2)

    # Calculate Auction total
    if item.get("auction") and item.get("auc_price") is not None:
        auc_price = item["auc_price"]
        imp = get_import_charges(auc_price)
        item["auc_import_charges"] = imp
        item["auc_total_price"] = round(auc_price + shipping + imp, 2)

    # Calculate general/default total
    default_price = item.get("price") or 0.0
    imp = get_import_charges(default_price)
    item["import_charges"] = imp
    item["total_price"] = round(default_price + shipping + imp, 2)

    return item


def _details_relevant_price_for_item(item, details):
    if not details:
        return None
    if item.get("auction") and not item.get("buy_now"):
        bid_price = _api_float(details.get("currentBidPrice"))
        if bid_price is not None:
            return bid_price
        if item.get("_was_hybrid"):
            return None
    return _api_float(details.get("price"))


def _details_price_mismatch(item, details):
    details_price = _details_relevant_price_for_item(item, details)
    if details_price is None:
        return False, None, None
    try:
        item_price = float(item["price"])
    except (KeyError, TypeError, ValueError):
        return False, None, details_price
    return (abs(details_price - item_price) > 1.0 if item.get("auction") else details_price > item_price + 1.0), item_price, details_price


def _headphone_models(text):
    pattern = r"\b(?:(wh|wf)[\s-]*1000[\s-]*)?xm(\d+)\b|\b(?:wh[\s-]*ult900n|ult\s*wear)\b"
    return [(match.group(1) or 'wh') + '1000xm' + match.group(2) if match.group(2) else 'ult900n'
            for match in re.finditer(pattern, _normalize(text))]


def _headphone_details_match(query, title, description, aspects):
    expected = _headphone_models(query)
    if not expected:
        return True
    expected = expected[0]
    declared = _headphone_models(title)
    if declared and declared[0] != expected:
        return False
    own = _normalize(_clean_description(description))
    described = _headphone_models(own)
    if described and described[0] != expected:
        return False
    for aspect in aspects:
        if _normalize(aspect.get('name') or '') in ('model', 'modell'):
            models = _headphone_models(aspect.get('value') or '')
            if models and models[0] != expected:
                return False
    # An implicit model + case title is preliminary until the seller confirms
    # that headphones are actually included, rather than a case for that model.
    title_norm = _normalize(title)
    case_bundle = _is_device_bundle(title_norm,'headphones') and re.search(r"\b(?:case|cover|hulle|huelle|schutzhulle|tasche)\b",title_norm)
    if case_bundle:
        device = re.search(r"\b(?:kopfhoerer|headphones|headset)\b", own)
        if not device or re.search(r"\b(?:case|cover|hulle|huelle|schutzhulle|tasche)\b", own[:device.start()]):
            return False
        if re.search(r"\b(?:headphones|headset|kopfhoerer)\s+(?:are\s+|sind\s+)?(?:not\s+included|nicht\s+enthalten)\b", own):
            return False
    return True


def _details_match_contract(item, search, details, *, require_description=True):
    """Common checks; only isolated legacy metadata fixtures may omit description."""
    if require_description and (not details or not _clean_description(details.get("description") or "").strip()):
        return False
    if not details:
        return _intent_details_match(search, item, details)
    if require_description:
        seconds_left = _parse_end_date_to_seconds(details.get("itemEndDate"))
        if seconds_left is not None and seconds_left <= 0:
            return False
        availability = details.get("estimatedAvailabilities") or []
        if any(entry.get("estimatedAvailabilityStatus") in ("OUT_OF_STOCK", "UNAVAILABLE") for entry in availability):
            return False
    query = _normalize(_intent_query(search))
    category = _effective_category(search.get("filters", {}).get("category", "all"), query)
    allowed = ALLOWED_SUBCATEGORIES.get(category)
    cat_id = str(details.get("categoryId") or "")
    path = str(details.get("categoryIdPath") or "").split("|")
    if allowed and cat_id and cat_id not in allowed and not any(cid in allowed for cid in path):
        return False
    gpu_intent = _search_intent(search)
    if gpu_intent and gpu_intent.get('kind') in ('gpu_pc','rtx_oled_laptop','vivobook_14x_oled_3050'):
        gpu = gpu_intent.get('gpu') or '3050'
        values = [aspect.get('value') or '' for aspect in details.get('localizedAspects') or []
                  if _normalize(aspect.get('name') or '') in ('grafikkarte','grafikprozessor','graphics card','graphics processor','gpu')]
        values += re.findall(r"\b(?:grafikkarte|graphics card|grafikprozessor|graphics processor|gpu)\s*:\s*([^.!?]{1,80})",_normalize(_clean_description(details.get('description') or '')))
        if any(not _declared_rtx_matches(_normalize(value),gpu) for value in values):
            return False
    if _effective_category(category, query) == 'headphones' and not _headphone_details_match(
            query, details.get('title') or item.get('title') or '', details.get('description') or '',
            details.get('localizedAspects') or []):
        return False
    if _effective_category(category, query) in ("monitors", "laptops") and "oled" in query:
        non_oled = r"(?:ips|tn|va|lcd|led|qled)"
        panel_label = r"(?:panel(?:[ -]*(?:typ|type|technologie|technology))?|display[ -]*(?:typ|type|technologie|technology)|bildschirm[ -]*(?:typ|technologie))"
        if re.search(rf"\b{panel_label}\s*:?\s*{non_oled}\b", _normalize(_clean_description(details.get("description") or ""))):
            return False
        for aspect in details.get("localizedAspects") or []:
            if re.fullmatch(panel_label, _normalize(aspect.get("name") or "")) and re.search(rf"\b{non_oled}\b", _normalize(aspect.get("value") or "")):
                return False
    mouse_intent = _search_intent(search)
    if mouse_intent and mouse_intent["kind"] in ("superlight_2", "superlight_2_dex"):
        title = _normalize(details.get("title") or item.get("title") or "")
        if not _matches_superlight_2_mouse(title, mouse_intent["kind"] == "superlight_2_dex", mouse_intent.get("se",False), mouse_intent.get("compact",False)):
            return False
        own_description = _normalize(_clean_description(details.get("description") or ""))
        described_model = re.search(r"\b(?:superlight|gpx)\s*(?:2|ii)(c)?\b(?:[\s-]+(dex|se)\b)?", own_description)
        if described_model and (bool(described_model.group(1)) != mouse_intent.get("compact",False) or
                                (described_model.group(2) == "dex") != (mouse_intent["kind"] == "superlight_2_dex") or
                                (described_model.group(2) == "se") != mouse_intent.get("se",False)):
            return False
        if re.search(r"^(?:logitech\s+)?(?:g\s+)?pro\s*2\s+lightspeed\b", own_description):
            return False
        for aspect in details.get("localizedAspects") or []:
            if _normalize(aspect.get("name") or "") not in ("modell", "model"):
                continue
            value = _normalize(aspect.get("value") or "")
            if ("superlight" in value and not _matches_superlight_2_mouse(value, mouse_intent["kind"] == "superlight_2_dex", mouse_intent.get("se",False), mouse_intent.get("compact",False))) or re.search(r"\bpro\s*2\s+lightspeed\b", value):
                return False
    if _effective_category(category, query) == "consoles" and re.search(r"\b(?:ps5|playstation\s*5)\b", query):
        declared_models = [
            _normalize(aspect.get("value") or "") for aspect in details.get("localizedAspects") or []
            if _normalize(aspect.get("name") or "") in ("modell", "model", "modellnummer", "model number")
        ]
        declared_models += re.findall(
            r"\b(?:modell(?:nummer)?|model(?:\s+number)?)\s+(?:ist\s+|is\s+)?((?:cuh|cfi)[- ]?\d+[a-z]?)\b",
            _normalize(_clean_description(details.get("description") or "")),
        )
        if any(re.search(r"\bcuh[- ]?\d|\b(?:ps4|playstation\s*4)\b", model) or
               (re.search(r"\bpro\b", query) and re.search(r"\bcfi[- ]?[12]\d{3}", model))
               for model in declared_models):
            return False
    if _effective_category(category, query) == "phones":
        title = _normalize(details.get("title") or item.get("title") or "")
        if not _matches_phone_query_model(title, query):
            return False
        if not _phone_specifications_match(title, details.get("description") or "", query):
            return False
        if not _phone_description_purpose_confirmed(details.get("description") or ""):
            return False
        if "iphone" in query and re.search(r"\b(?:nachbau|replica|replika|clone|klon|umbau|conversion|converter)\b|\b(?:nicht|kein)\s+(?:um\s+)?(?:ein\s+)?(?:original(?:es|er|en)?\s+)?(?:apple\s+)?iphone\b", _normalize(_clean_description(details.get("description") or ""))):
            return False
        for aspect in details.get("localizedAspects") or []:
            name = _normalize(aspect.get("name") or "")
            value = _normalize(aspect.get("value") or "")
            if name in ('modell','model') and value and not _phone_model_aspect_matches(value, query):
                return False
            if name.replace(' ','') in ('modellnummer','modelnumber','modellnr','modelno') and value and not _phone_model_number_matches(value, query):
                return False
            if name.replace(' ','') in ('prozessor','processor','chipsatz','chipsatzmodell','chipset','chipsetmodel','cpu') and not _phone_chipset_matches(value,query):
                return False
            if name in ("ram", "arbeitsspeicher", "memory") and re.search(r"\bs24\s*ultra\b|\bs25\s*edge\b", query):
                ram = re.search(r"\b(\d+)\s*gb\b", value)
                if ram and int(ram.group(1)) != 12:
                    return False
            if "iphone" in query and name in ("betriebssystem", "operating system") and "android" in value:
                return False
    return not (
        details.get("itemGroupType") == "SELLER_DEFINED_VARIATIONS"
        or _is_details_blocked(details, search)
        or _is_description_blocked(details.get("description", ""), category)
        or not _intent_details_match(search, item, details)
    )


def _refresh_candidate_details(item, details, settings):
    _calculate_total(item, settings, details)
    seller = details.get("seller") or {}
    if seller.get("username"):
        item["seller_name"] = seller["username"]
    if seller.get("feedbackScore") is not None:
        item["seller_rating_count"] = seller["feedbackScore"]
    if seller.get("feedbackPercentage") is not None:
        item["seller_rating_percent"] = seller["feedbackPercentage"]
    account = {"BUSINESS": "commercial", "INDIVIDUAL": "private"}.get(seller.get("sellerAccountType"))
    if account:
        item["seller_type"] = account
    if details.get("title"):
        item["title"] = details["title"]
    if details.get("condition") or details.get("itemCondition"):
        item["condition"] = details.get("condition") or details.get("itemCondition")
    seconds_left = _parse_end_date_to_seconds(details.get("itemEndDate"))
    if seconds_left is not None:
        item["time_left"] = _format_time_left_from_seconds(max(0, seconds_left))
    return item


def _include_word_in_title(title_norm, word_norm):
    """Match include_words with known GPU↔model synonyms (vivobook 3050 ↔ m7400qc)."""
    if not word_norm:
        return False
    if word_norm in title_norm:
        return True
    # ASUS Vivobook 14X OLED M7400Q* ships with RTX 3050; titles often omit "3050"
    if word_norm in ("3050", "rtx 3050", "rtx3050"):
        if re.search(r"\bm7400q[ca]?\b", title_norm):
            return True
        if re.search(r"\b(?:rtx\s*)?3050\s*ti\b|\b(?:rtx\s*)?3050ti\b|\b(?:rtx\s*)?3050\b", title_norm):
            return True
    return False


def filter_results(items, search, config_obj, skip_seen=False, is_statistics=False):
    global_banned = config_obj.get_global_banned_sellers()
    global_banned_norm = {_normalize(s) for s in global_banned}
    banned_ids = config_obj.get_banned_item_ids() | KNOWN_BAD_ITEM_IDS
    item_hashes = config_obj.get_item_hashes()
    filters = search.get("filters", {})
    category = filters.get("category", "all")
    query_text = _intent_query(search)
    exclude_words = [_normalize(w) for w in search.get("exclude_words", [])]
    include_words = [_normalize(w) for w in search.get("include_words", [])]
    exclude_sellers = [s.lower() for s in search.get("exclude_sellers", [])]
    exclude_sellers_norm = {_normalize(s) for s in exclude_sellers}
    settings = config_obj.get_settings()

    filtered = []
    seen_batch_ids = set()
    for item in items:
        # Bucket selection must never change the cached SERP used by another search.
        item = copy.deepcopy(item)
        # Multi-variation bait (price "from X") is never a real deal for either mode.
        if item.get("is_multivariation"):
            continue
        item_id = str(item.get("item_id") or "")
        item["item_id"] = item_id
        if not item_id or item_id in seen_batch_ids:
            continue
        if item_id in banned_ids:
            continue
        listing_type = filters.get("listing_type", "all")
        item = _calculate_total(item, settings)
        # Select correct price for hybrid listings based on the search/bucket type
        if item.get("buy_now") and item.get("auction"):
            if listing_type == "auction":
                item["_was_hybrid"] = True
                item["price"] = item.get("auc_price") or item["price"]
                item["total_price"] = item.get("auc_total_price") or item["total_price"]
                item["import_charges"] = item.get("auc_import_charges") or item.get("import_charges")
                item["buy_now"] = False
            elif listing_type in ("buy_now", "buy_now_offer"):
                item["_was_hybrid"] = True
                item["price"] = item.get("bin_price") or item["price"]
                item["total_price"] = item.get("bin_total_price") or item["total_price"]
                item["import_charges"] = item.get("bin_import_charges") or item.get("import_charges")
                item["auction"] = False

        # Apply the bait floor to the selected price, not the other hybrid side.
        if _is_implausibly_cheap_device(item, search):
            continue

        if filters.get("location", "de") == "de" and item.get("location"):
            if _is_clearly_non_germany_location(item["location"]):
                continue
        if filters.get("location") == "eu" and not _is_eu(item.get("location", "")):
            continue
        wanted_condition = filters.get("condition", "any")
        condition_text = _normalize(item.get("condition", ""))
        conditions = {"used": ("used", "gebraucht"), "new": ("new", "neu"),
                      "refurbished": ("refurbished", "erneuert", "generaluberholt", "generalueberholt")}
        if wanted_condition != "any" and not any(_has_term(condition_text, word) for word in conditions.get(wanted_condition, (_normalize(wanted_condition),))):
            continue
        wanted_seller = filters.get("seller_type", "any")
        actual_seller = item.get("seller_type", "unknown")
        if wanted_seller != "any" and actual_seller != "unknown" and wanted_seller != actual_seller:
            continue
        radius = filters.get("max_distance_km")
        if radius is not None:
            from plz_distance import distance_between_plz, extract_plz
            center = filters.get("plz_center") or settings.get("user_zip")
            distance = distance_between_plz(center, extract_plz(item.get("location", "")))
            if distance is None or distance > float(radius):
                continue
            item["distance_km"] = distance
        hard_max = filters.get("max_price")
        if not is_statistics and hard_max is not None and item.get("price", 0) > hard_max:
            continue
        # Check min_price only for Buy It Now (non-auction) items
        min_price = filters.get("min_price")
        if min_price is not None and not item.get("auction") and item.get("total_price", 0) < min_price:
            continue
        # Check limit_price (or max_price if limit_price not set) for all items.
        # If the item (even an auction) is already more expensive than our target limit, filter it out.
        # Statistics keeps over-limit items so the report can show "🟣 Дорого".
        limit_or_max = filters.get("limit_price") if "limit_price" in filters else filters.get("max_price")
        if limit_or_max is not None and item.get("total_price", 0) > limit_or_max:
            if not skip_seen and not is_statistics:
                continue

        if item.get("is_pickup_only"):
            nearby = False
            if item.get("location"):
                from plz_distance import is_nearby
                nearby, _ = is_nearby(item["location"], max_km=100)
            if not nearby:
                continue

        if is_statistics and filters.get("_stats_bucket_filter"):
            if listing_type == "auction" and not item.get("auction"):
                continue
            if listing_type in ("buy_now", "buy_now_offer") and not item.get("buy_now"):
                continue
            if filters.get("best_offer"):
                if not item.get("best_offer"):
                    continue
            elif item.get("best_offer"):
                continue
        else:
            if listing_type == "auction" and not item.get("auction"):
                continue
            if listing_type in ("buy_now", "buy_now_offer") and not item.get("buy_now"):
                continue
            if listing_type == "offer" and not item.get("best_offer"):
                continue
            if filters.get("best_offer") and not item.get("best_offer"):
                continue

        # Auction notify rules (same for normal + statistics filtering of "alertable"):
        # A) Best Offer auctions: ok when price limit is satisfied.
        # B) Regular auctions: only when ending within 24 hours.
        # Statistics still keeps non-alertable auctions so the report can show
        # "🟡 Ждёт 24ч" instead of green — controlled later via _notify_eligibility.
        if not is_statistics:
            if item.get("auction") and not item.get("buy_now"):
                is_best_offer = item.get("best_offer")
                is_ending_soon = False
                time_left_str = item.get("time_left", "")
                if time_left_str:
                    minutes = _parse_time_left_to_minutes(time_left_str)
                    if minutes is not None and minutes <= 1440:  # 24 hours (1 day)
                        is_ending_soon = True
                if not (is_best_offer or is_ending_soon):
                    continue

        seller_norm = _normalize(item["seller_name"])
        if seller_norm in global_banned_norm or seller_norm in KNOWN_BAD_SELLERS:
            continue
        if seller_norm in exclude_sellers_norm:
            continue
        title_norm = _normalize(item["title"])
        # Block items with bad conditions (Defekt, Als Ersatzteile, etc.)
        cond_norm = _normalize(item.get("condition", ""))
        if cond_norm:
            if cond_norm in BAD_CONDITIONS or any(w in cond_norm for w in ("defekt", "ersatzteil", "parts", "not working", "salvage", "reparatur", "broken")):
                continue
            if _effective_category(category, _normalize(query_text)) == "phones" and any(_has_term(cond_norm, w) for w in REFURBISHED_CONDITION_WORDS):
                continue
        if not _intent_prelim_matches_title(title_norm, search):
            continue
        query_norm = _normalize(query_text)
        effective_category = _effective_category(category, query_norm)
        if not _matches_category_query(title_norm, effective_category, query_norm):
            continue
        if _is_category_blocked_title(title_norm, effective_category, query_norm):
            continue
        if _is_controller_pad_query(query_norm):
            if _controller_accessory_label(title_norm):
                continue
            if _controller_console_bundle_label(title_norm):
                continue
            if _wrong_controller_generation(title_norm, query_norm):
                continue
        if effective_category == "phones":
            # Same rule as the bait floor: never drop something the owner said
            # they would buy. A 40€ limit means 40€ finds are the point.
            try:
                phone_floor = min(50.0, float(filters.get("limit_price") or 50.0))
            except (TypeError, ValueError):
                phone_floor = 50.0
            if "pixel" not in query_norm and item.get("buy_now") and item.get("total_price", 0) < phone_floor:
                continue
            if not _matches_phone_query_model(title_norm, query_norm):
                continue
            if _is_phone_accessory_title(title_norm):
                continue
            if not _is_phone_device_title(title_norm):
                continue
        if effective_category == "consoles":
            if not _matches_console_query_model(title_norm, query_norm):
                continue
        if any(_exclude_word_hits(title_norm, w) for w in exclude_words):
            continue
        # Controllers: Stickdrift / abgenutzte Sticks (even without per-search exclude)
        if _has_stickdrift_problem(title_norm):
            continue
        if include_words and not any(_include_word_in_title(title_norm, w) for w in include_words):
            continue
        if not skip_seen:
            h = _item_hash(item["seller_name"], item["title"], item["price"])
            if not item.get("auction") and h in item_hashes:
                continue
        filtered.append(item)
        seen_batch_ids.add(item_id)
    return filtered


def fetch_ebay(search, force=False):
    """Returns list of items. On error returns []. For detailed status use fetch_ebay_ex."""
    items, _err = fetch_ebay_ex(search, force=force)
    return items



def _valid_price_value(value):
    try:
        if value is None:
            return None
        value = float(value)
        if value <= 0:
            return None
        return value
    except (TypeError, ValueError):
        return None


def _prefer_lower_price(current, candidate):
    current_val = _valid_price_value(current)
    candidate_val = _valid_price_value(candidate)
    if candidate_val is None:
        return current
    if current_val is None or candidate_val < current_val:
        return candidate
    return current


def _prefer_present(current, candidate):
    return candidate if current in (None, "", 0) and candidate not in (None, "", 0) else current


def _merge_same_item(existing, incoming):
    merged = copy.deepcopy(existing)
    incoming = incoming or {}

    merged["buy_now"] = bool(existing.get("buy_now") or incoming.get("buy_now"))
    merged["auction"] = bool(existing.get("auction") or incoming.get("auction"))
    merged["best_offer"] = bool(existing.get("best_offer") or incoming.get("best_offer"))
    merged["_was_hybrid"] = bool(
        existing.get("_was_hybrid")
        or incoming.get("_was_hybrid")
        or (merged["buy_now"] and merged["auction"])
    )

    merged["bin_price"] = _prefer_lower_price(existing.get("bin_price"), incoming.get("bin_price"))
    merged["auc_price"] = _prefer_lower_price(existing.get("auc_price"), incoming.get("auc_price"))
    merged["bin_total_price"] = _prefer_lower_price(existing.get("bin_total_price"), incoming.get("bin_total_price"))
    merged["auc_total_price"] = _prefer_lower_price(existing.get("auc_total_price"), incoming.get("auc_total_price"))

    if merged.get("auction") and merged.get("buy_now"):
        if _valid_price_value(merged.get("bin_price")) is None:
            merged["bin_price"] = _prefer_present(merged.get("bin_price"), incoming.get("price"))
        if _valid_price_value(merged.get("auc_price")) is None:
            merged["auc_price"] = _prefer_present(merged.get("auc_price"), incoming.get("price"))
        if _valid_price_value(merged.get("bin_total_price")) is None and _valid_price_value(merged.get("bin_price")) is not None:
            merged["bin_total_price"] = float(merged["bin_price"]) + float(merged.get("shipping_cost") or 0)
        if _valid_price_value(merged.get("auc_total_price")) is None and _valid_price_value(merged.get("auc_price")) is not None:
            merged["auc_total_price"] = float(merged["auc_price"]) + float(merged.get("shipping_cost") or 0)

    for key in ("title", "image_url", "url", "condition", "seller_name", "seller_type", "location", "time_left"):
        merged[key] = _prefer_present(merged.get(key), incoming.get(key))
    for key in ("seller_rating_count", "seller_rating_percent", "bids_count"):
        merged[key] = max(existing.get(key) or 0, incoming.get(key) or 0)
    merged["top_rated"] = bool(existing.get("top_rated") or incoming.get("top_rated"))
    merged["is_pickup_only"] = bool(existing.get("is_pickup_only") or incoming.get("is_pickup_only"))
    merged["is_multivariation"] = bool(existing.get("is_multivariation") or incoming.get("is_multivariation"))

    return merged


def _merge_items_by_id(*groups):
    merged = {}
    for group in groups:
        for item in group or []:
            item_id = item.get("item_id")
            if not item_id:
                continue
            if item_id in merged:
                merged[item_id] = _merge_same_item(merged[item_id], item)
            else:
                merged[item_id] = item
    return list(merged.values())


def _auction_sweep_search(search):
    filters = search.get("filters", {}) or {}
    if filters.get("listing_type", "all") != "all":
        return None
    sweep = copy.deepcopy(search)
    sweep.setdefault("filters", {})["listing_type"] = "auction"
    sweep["id"] = f"{search.get('id', 'search')}__auction_sweep"
    return sweep


# Both sweeps below take an already-prepared fetch search (price floors set) and
# only change how eBay orders and pages the same query. 25 cards is plenty: what
# they look for sits at the very top of their sort.
_SWEEP_PAGE_SIZE = 25


def _ending_soon_auction_search(search):
    """Auction lots ordered by hammer time.

    The monitoring profile is price-ascending, so a lot in its last minutes can
    sit deep on page 3 and never be seen — which is exactly when the final-hour
    and 15-minute alerts have to fire.
    """
    filters = search.get("filters", {}) or {}
    if filters.get("listing_type", "all") not in ("all", "auction"):
        return None
    sweep = copy.deepcopy(search)
    f = sweep.setdefault("filters", {})
    f["listing_type"] = "auction"
    f["sort"] = "ending_soon"
    f.pop("sort_code", None)
    f["_ipg"] = _SWEEP_PAGE_SIZE
    sweep["id"] = f"{search.get('id', 'search')}__ending_soon"
    return sweep


def _newly_listed_search(search):
    """Freshly listed items, newest first.

    Being first is the whole point of the bot, and a price-ascending page 1 hides
    a brand-new listing behind the cheaper ones until one of them ends — that is
    the "sometimes it arrives an hour late" case.
    """
    sweep = copy.deepcopy(search)
    f = sweep.setdefault("filters", {})
    f["sort"] = "newest"
    f.pop("sort_code", None)
    f["_ipg"] = _SWEEP_PAGE_SIZE
    sweep["id"] = f"{search.get('id', 'search')}__newest"
    return sweep


def _statistics_search_variant(search, listing_type, min_price=None, best_offer=False):
    # Same base fetch profile as normal monitoring (price_asc + large page).
    variant = _prepare_monitor_fetch_search(search)
    filters = variant.setdefault("filters", {})
    filters["_stats_category"] = filters.get("category", "all")
    # Use intent query (clean eBay _nkw), not raw config query with parentheses.
    query_norm = _normalize(_intent_query(variant))
    effective_category = _effective_category(filters.get("category", "all"), query_norm)
    if effective_category == "consoles":
        filters["category"] = "all"
    # Intent category drives title filters; for eBay _sacat we open monitors/mice
    # to "all" — narrow sacat + heavy negatives sometimes returned 0 HTML
    # hits while Playwright still saw stock site-wide.
    intent = _search_intent(variant)
    if intent and intent.get("category"):
        effective_category = intent["category"]
        filters["_stats_category"] = effective_category
        if effective_category in ("monitors", "mice", "computers"):
            filters["category"] = "all"
        else:
            filters["category"] = intent["category"]
    filters["listing_type"] = listing_type
    filters["best_offer"] = bool(best_offer)
    # Same floor rule as the monitoring fetch: once a limit is set, the whole
    # band under it is fetched, so the report shows the cheap finds too.
    device_floor = _min_plausible_device_price(search)
    search_floor = _serp_price_floor(search, device_floor, effective_category, query_norm)
    if min_price is not None:
        try:
            search_floor = max(float(min_price), float(search_floor or 0))
        except (TypeError, ValueError):
            pass
    filters["min_price"] = search_floor if search_floor and search_floor > 0 else min_price
    # Keep a wide eBay ceiling so sort=price_asc surfaces real floor prices;
    # soft limit_price is applied in filter / green verdict, not as _udhi.
    filters["max_price"] = None
    filters["_stats_bucket_filter"] = True
    # 240 ipg is ignored/odd on some eBay edges and can yield empty shells on CI.
    filters["_ipg"] = 60 if _on_github_actions() else max(int(filters.get("_ipg") or 0), 120)
    suffix = "bo" if best_offer else "all"
    variant["id"] = f"{search.get('id', 'search')}__stats_{listing_type}_{suffix}"
    return variant


def _statistics_filter_search(search):
    stats_filter = copy.deepcopy(search)
    filters = stats_filter.setdefault("filters", {})
    filters["listing_type"] = "all"
    filters.pop("best_offer", None)
    filters.pop("_stats_bucket_filter", None)
    return stats_filter


def _on_github_actions():
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"))


def _clear_gh_fetch_pressure(had_results=False):
    """Between GH stats products: never carry cooldown into the next search."""
    global _ebay_block_until, _ebay_consecutive_blocks
    if not _on_github_actions():
        return
    _ebay_block_until = 0.0
    if had_results:
        _ebay_consecutive_blocks = 0


def _warmup_session(session, host):
    """Visit homepage and a category index before the search to look like a
    real user navigating the site. Cookies stick to the session, which keeps
    eBay's anti-bot far happier than a cold search hit."""
    import random
    home = f"https://www.{host}/"
    try:
        session.get(
            home,
            timeout=HTTP_TIMEOUT,
            headers=None if _HAS_CURL_CFFI else {"Referer": ""},
        )
        time.sleep(random.uniform(0.8, 1.8) if _on_github_actions() else random.uniform(0.6, 1.4))
        # Touch electronics + phones like a real shopper (more cookies / consent).
        for path in (
            f"{home}b/Cell-Phones-Smartphones/9355/bn_320094",
            f"https://www.{host}/sch/i.html?_nkw=test&_sacat=0",
        ):
            try:
                session.get(path, timeout=HTTP_TIMEOUT, headers={"Referer": home})
                time.sleep(random.uniform(0.3, 0.9))
            except Exception:
                pass
    except Exception as e:
        logger.debug("warmup on %s failed (non-fatal): %s", host, e)


# Below this many hits a single missing card changes the answer, so a thin
# result set is worth one cross-check against the sibling host.
_THIN_MARKET_ITEMS = 5


_CHALLENGE_MARKERS = (
    "pardon our interruption",
    "bitte entschuldigen sie die störung",
    "bitte entschuldigen sie die storung",
    "splashui/captcha",
    "are you a robot",
    "automated access",
    "/splashui/",
    "verify you are a human",
    "checking your browser",
    "access denied",
    "security measure",
    "unusual traffic",
)


def _is_challenge_html(body, final_url=""):
    low = (body or "")[:12000].lower()
    fu = (final_url or "").lower()
    return "/splashui/" in fu or any(m in low for m in _CHALLENGE_MARKERS)


# Null-search phrases eBay only renders when the query really has no hits.
# Unambiguous enough to trust deep in the document — unlike "we couldn'…",
# which also shows up in the footer of pages that DO have listings.
_DEEP_EMPTY_MARKERS = (
    "keine exakten treffer",
    "kein ergebnis",
    "keine treffer",
    "keine ergebnisse",
    "es wurden keine ergebnisse",
    "no exact matches",
    "no results found",
)


def _parse_search_body(body, host, query):
    try:
        items = parse_ebay_results(body or "")
    except Exception as e:
        logger.error("Parse error for '%s' on %s: %s", query, host, e)
        return [], "parse"
    if items:
        return items, None
    raw = body or ""
    low = raw[:12000].lower()
    if "something went wrong on our end" in low:
        return [], "network"
    has_result_container = (
        'class="srp-results' in raw
        or "srp-river-results" in raw
        or 'class="srp-list' in raw
        or "data-listingid" in raw
        or "li.s-card" in raw
        or 'class="s-item' in raw
        or "s-item__" in raw
        or "s-card__" in raw
    )
    has_no_results_marker = (
        "kein ergebnis" in low
        or "keine treffer" in low
        or "keine exakten treffer" in low
        or "keine ergebnisse" in low
        or "no exact matches" in low
        or "0 ergebnisse" in low
        or "0 results" in low
        or "we couldn" in low
        or "no results found" in low
        or "es wurden keine ergebnisse" in low
    )
    body_len = len(raw)
    itm_links = len(re.findall(r"/itm/\d{9,15}", raw))
    # eBay.de renders the null-search headline ("Keine exakten Treffer gefunden")
    # ~150–200k into a 400k document, far past the 12k head we scan on every page,
    # so a genuinely empty market looked like the GH soft-empty and came back as
    # "parse" — which the auction policy then reports as «сбой загрузки».
    # Deep scan only when the page is a SERP with zero listing links: with no
    # /itm/ links there is nothing to mistake an empty page for, and pages that
    # DO have listings keep the old head-only rule.
    if not has_no_results_marker and itm_links == 0 and has_result_container:
        deep = raw.lower()
        deep_hit = next((m for m in _DEEP_EMPTY_MARKERS if m in deep), None)
        if deep_hit:
            has_no_results_marker = True
            logger.info(
                "eBay %s empty-marker %r past the 12k head (body_len=%d) for '%s'",
                host, deep_hit, body_len, query,
            )
    # Honest empty SERP (model not listed yet) — ONLY with explicit no-results text.
    # NEVER call this eBay block.
    if has_no_results_marker:
        logger.info(
            "eBay %s genuine no-results marker for '%s'", host, query
        )
        return [], None
    # Datacenter stealth shell: fat HTML, no result markup, no empty marker.
    if body_len > 5000 and not has_result_container and itm_links == 0:
        logger.warning(
            "eBay %s stealth empty body_len=%d for '%s'", host, body_len, query
        )
        return [], "blocked"
    if not has_result_container and itm_links == 0 and not has_no_results_marker:
        logger.warning("eBay %s empty (likely stealth block) for '%s'", host, query)
        return [], "blocked"
    # Result chrome + almost no /itm/ links WITHOUT no-results marker is the classic
    # GH soft-empty (Z80 Ultra still in stock live, curl shows container/itm=0).
    # Must NOT be "honest empty" — force Playwright / retries via parse.
    if has_result_container and itm_links <= 2:
        logger.warning(
            "eBay %s soft-empty chrome (container, itm=%d, no empty-marker) for '%s' — retry PW",
            host, itm_links, query,
        )
        return [], "parse"
    # Many /itm/ links but parser got 0 — markup drift. Prefer "parse" so caller
    # retries Playwright, not "blocked" (which opens API circuit on 429 spam).
    if itm_links > 2:
        logger.warning(
            "eBay %s unparseable listings itm=%d body_len=%d for '%s'",
            host, itm_links, body_len, query,
        )
        return [], "parse"
    return [], None


def _statistics_empty_bucket_label(*, side_ok=False, genuine_empty=False, error=None):
    if side_ok:
        return "❌", "Не найдено подходящих"
    if error in ("rate_limit", "api_rate_limit", "api_rate"):
        return "⚠️", "Rate limit"
    if error in ("blocked", "cooldown"):
        return "⚠️", "eBay block"
    if error:
        return "⚠️", "сбой загрузки"
    if genuine_empty:
        return "❌", "Не найдено"
    return "⚠️", "Проверка не завершена"


# Subresources we never parse. eBay SERP pulls 60+ thumbnails per page and the
# renderer used to die ("Page crashed") on every auction attempt on GH runners.
_PW_BLOCKED_RESOURCE_TYPES = ("image", "media", "font")


def _pw_light_serp_url(url, ipg="25"):
    """Same SERP with fewer cards — a 60-card auction page is what kills the
    renderer. Sort is price+shipping asc, so the cheapest lot is still on page 1.
    """
    if re.search(r"[?&]_ipg=\d+", url):
        return re.sub(r"([?&]_ipg=)\d+", r"\g<1>" + ipg, url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}_ipg={ipg}"


# Asset URLs only — a "**/*" route also intercepts the navigation itself, and
# continue_()-ing the document through eBay's redirect chain is what turned
# every GH "Page crashed" into "Page.goto: net::ERR_ABORTED" (run 20:07 UTC:
# 3 crashes, 92 aborts, 0 pages parsed). These globs never match the document.
_PW_BLOCKED_URL_GLOBS = (
    "**/*.{png,jpg,jpeg,gif,webp,avif,svg,ico,bmp}",
    "**/*.{woff,woff2,ttf,otf,eot}",
    "**/*.{mp4,webm,ogg,ogv,mp3,m4a,mov}",
    "**i.ebayimg.com/**",
    "**ir.ebaystatic.com/**",
)


def _pw_block_heavy(route):
    """Abort thumbnails/fonts/video — HTML is all we parse.

    Only ever attached to asset globs (never to the navigation request), but
    resource_type stays as a second guard for anything the glob over-matches.
    """
    try:
        if route.request.resource_type == "document":
            route.continue_()
        else:
            route.abort()
    except Exception:
        # Route already handled / page gone — never let this kill the fetch.
        try:
            route.continue_()
        except Exception:
            pass


def _pw_should_escalate(exc_msg, attempt):
    """Is this failure worth the next (cheaper, plainer) attempt?

    - crash: the renderer died — repeating the same load is pointless, escalate.
    - net::ERR_ABORTED: the navigation itself died. This is what GH returned 92
      times on 2026-07-26 20:07 UTC after we started intercepting requests, and
      it used to end the chain after a single ~2s try, leaving every auction
      bucket without a page.
    - timeout: only worth the commit-only retry once — statistics has a budget.
    """
    msg = (exc_msg or "").lower()
    crashed = "crash" in msg or "target closed" in msg or "destroyed" in msg
    navigation_died = "net::" in msg or "err_aborted" in msg
    return crashed or navigation_died or (attempt == 0 and "timeout" in msg)


def _do_fetch_playwright(url, query=""):
    """Real Chromium HTML fetch — last HTML hope on blocked datacenter IPs (GH Actions).

    Auction SERPs are the heaviest page we load and the renderer used to crash
    on every single attempt on GH, which turned every pure-Auktion bucket into
    a false «Не найдено». So we drop the subresources we never read, keep
    eBay's ad iframes out of their own renderer processes, and *escalate* on
    each retry (lighter wait, then fewer cards) instead of repeating the exact
    attempt that just crashed.
    """
    if os.environ.get("EBAY_HTML_PLAYWRIGHT", "1").strip().lower() in ("0", "false", "no"):
        return [], "no_playwright"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.info("playwright not installed — skip browser HTML fallback")
        return [], "no_playwright"

    # Retries must get cheaper AND less exotic, not repeat the attempt that just
    # died: full load → commit-only wait → plain Chromium (no asset routing, no
    # renderer cap) on a 25-card page. Each step names itself in the log, so the
    # next GH run says which configuration actually fetched the page.
    attempts = (
        {
            "url": url, "warm": True, "wait_until": "domcontentloaded",
            "settle": 1500, "block": True, "cap_renderers": True, "name": "full",
        },
        {
            "url": url, "warm": False, "wait_until": "commit",
            "settle": 900, "block": True, "cap_renderers": True, "name": "commit",
        },
        {
            "url": _pw_light_serp_url(url), "warm": False, "wait_until": "commit",
            "settle": 900, "block": False, "cap_renderers": False,
            "name": "light SERP, plain chromium",
        },
    )

    last_err = None
    for attempt, plan in enumerate(attempts):
        browser = None
        try:
            with sync_playwright() as p:
                launch_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--disable-extensions",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                ]
                if plan["cap_renderers"]:
                    # eBay SERP embeds ad/tracking iframes; site-per-process
                    # gives each one its own renderer and the runner runs
                    # out of memory mid-navigation → "Page crashed".
                    launch_args += [
                        "--disable-features=IsolateOrigins,site-per-process,TranslateUI",
                        "--renderer-process-limit=2",
                    ]
                browser = p.chromium.launch(headless=True, args=launch_args)
                context = browser.new_context(
                    locale="de-DE",
                    timezone_id="Europe/Berlin",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1365, "height": 900},
                )
                if plan["block"]:
                    for glob in _PW_BLOCKED_URL_GLOBS:
                        context.route(glob, _pw_block_heavy)
                page = context.new_page()
                page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                if plan["warm"]:
                    # Warm homepage first for cookies
                    try:
                        page.goto(
                            "https://www.ebay.de/",
                            wait_until="domcontentloaded",
                            timeout=25000,
                        )
                        page.wait_for_timeout(600)
                    except Exception:
                        pass
                if attempt:
                    logger.info(
                        "Playwright retry %d/%d for '%s' (%s)",
                        attempt + 1, len(attempts), query, plan["name"],
                    )
                page.goto(plan["url"], wait_until=plan["wait_until"], timeout=35000)
                page.wait_for_timeout(plan["settle"])
                # dismiss cookie banner if present
                for sel in (
                    "button#gdpr-banner-accept",
                    "button[data-testid='gdpr-banner-accept']",
                    "#consent-page .btn-primary",
                ):
                    try:
                        page.locator(sel).first.click(timeout=1200)
                        page.wait_for_timeout(400)
                    except Exception:
                        pass
                # Wait for result cards when SPA paints late (common on auction SERP).
                try:
                    page.wait_for_selector(
                        "li.s-card, li.s-item, .srp-results, .srp-river-results",
                        timeout=8000,
                    )
                    page.wait_for_timeout(700)
                except Exception:
                    page.wait_for_timeout(900)
                body = page.content()
                final = page.url
                browser.close()
                browser = None
            if _is_challenge_html(body, final):
                logger.warning("Playwright still got challenge for '%s'", query)
                return [], "blocked"
            items, err = _parse_search_body(body, "playwright", query)
            if items:
                logger.info("  %s -> %d items via Playwright HTML", query, len(items))
            return items, err
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            logger.warning(
                "Playwright HTML fetch failed for '%s' (try %d/%d): %s",
                query, attempt + 1, len(attempts), e,
            )
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            if attempt >= len(attempts) - 1:
                break
            if _pw_should_escalate(msg, attempt):
                continue
            break
    return [], "network"


def _http_get_search(session, url, common_headers):
    resp = session.get(url, timeout=HTTP_TIMEOUT, headers=common_headers)
    sc = resp.status_code
    body = resp.text or ""
    final_url = getattr(resp, "url", "") or ""
    return sc, body, final_url


def _do_fetch_one(host, search, referer=None):
    """Single attempt against a specific host. Returns (items, error).

    On GH/datacenter IPs www often soft-empties or challenges; we always try
    m.<host> before giving up this host.
    """
    global _ebay_session_warmed
    query = search.get("query", "")
    url = _build_url_with_host(host, search)
    # GitHub runners: hit mobile first — desktop challenge is near-certain.
    prefer_mobile = _on_github_actions() or os.environ.get("EBAY_HTML_MOBILE_FIRST", "").strip() in (
        "1",
        "true",
        "yes",
    )
    session = _get_ebay_session()
    home = f"https://www.{host}/"
    referer = referer or home
    common_headers = {
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        if not _ebay_session_warmed:
            _warmup_session(session, host)
            _ebay_session_warmed = True
        urls_try = []
        if prefer_mobile and host in ("ebay.de", "ebay.com"):
            urls_try.append(_build_url_with_host(host, search, sub="m"))
        urls_try.append(url)
        if host in ("ebay.de", "ebay.com") and not prefer_mobile:
            urls_try.append(_build_url_with_host(host, search, sub="m"))

        last_err = "blocked"
        for try_url in urls_try:
            try:
                sc, body, final_url = _http_get_search(session, try_url, common_headers)
            except Exception as e:
                if "impersonating" in str(e).lower() and "not supported" in str(e).lower():
                    logger.warning("Unsupported eBay fingerprint %s, rotating", _ebay_session_ua)
                    reset_ebay_session(rotate=True)
                    return [], "blocked"
                if "timeout" in str(e).lower():
                    last_err = "network"
                    continue
                last_err = "network"
                continue

            if sc == 429:
                return [], "rate_limit"
            if sc in (403, 503):
                last_err = "blocked"
                continue
            if sc >= 400:
                last_err = f"http_{sc}"
                continue

            if _is_challenge_html(body, final_url):
                logger.warning(
                    "eBay challenge on %s for '%s' (impersonate=%s, url=%s)",
                    host, query, _ebay_session_ua, (final_url or try_url)[:80],
                )
                last_err = "blocked"
                # cookie from challenge page may unlock next URL (m.)
                continue

            items, err = _parse_search_body(body, host, query)
            if items:
                logger.info(
                    "  %s -> %d items via %s body_len=%d",
                    query, len(items), try_url.split("/")[2], len(body),
                )
                # eBay sometimes answers with a real page that carries a partial
                # list — measured 2026-07-27: the same URL gave 2 lots on one
                # request and 3 on the next, and the missing one was a live
                # 36.69€ SUPERLIGHT 2 under a 45€ limit. On a thin market that
                # single lot is the whole point, so cross-check it against the
                # sibling host (m ↔ www serve the same market) and merge. One
                # cheap HTML request, only when there is almost nothing to lose.
                if len(items) < _THIN_MARKET_ITEMS:
                    sibling_sub = "www" if "//m." in try_url else "m"
                    samples = [
                        (sibling_sub, _build_url_with_host(host, search, sub=sibling_sub)),
                        # Same URL again: measured 2026-07-27, three of five
                        # requests carried the full list and two came back 403 or
                        # a 14 KB shell, so a second sample is worth ~2 seconds.
                        ("retry", try_url),
                    ]
                    for label, sample_url in samples:
                        if len(items) >= _THIN_MARKET_ITEMS:
                            break
                        if sample_url == try_url and label != "retry":
                            continue
                        try:
                            sc2, body2, final2 = _http_get_search(
                                session, sample_url, common_headers
                            )
                            if sc2 >= 400 or _is_challenge_html(body2, final2):
                                continue
                            extra, _ = _parse_search_body(body2, host, query)
                            merged = _merge_items_by_id(items, extra or [])
                            if len(merged) > len(items):
                                logger.info(
                                    "  %s -> +%d lot(s) missing from the first page "
                                    "(thin market, recovered via %s)",
                                    query, len(merged) - len(items), label,
                                )
                                items = merged
                        except Exception as e:
                            logger.debug("thin-market cross-check (%s) failed: %s", label, e)
                return items, None
            if err:
                last_err = err
            else:
                # honest empty
                last_err = None
        return [], last_err
    except Exception as e:
        if "timeout" in str(e).lower():
            logger.error("Timeout fetching '%s' on %s: %s", query, host, e)
            return [], "network"
        logger.error("Network error fetching '%s' on %s: %s", query, host, e)
        return [], "network"


def _query_cache_key(search):
    """Stable key for the search-input portion that affects eBay results."""
    filters = search.get("filters", {}) or {}
    keys = ("category", "max_price", "min_price", "condition", "condition_code", "listing_type", "best_offer", "seller_type", "location", "sort", "sort_code", "_ipg")
    source = "html" if search.get("_html_fallback") else EBAY_SOURCE if EBAY_SOURCE in ("auto", "html", "api") else "auto"
    parts = [f"source={source}", f"market={EBAY_MARKETPLACE_ID}", search.get("query", "").strip().lower()]
    if search.get("_query_override"):
        parts.append(f"query_override={str(search.get('_query_override')).strip().lower()}")
    for k in keys:
        parts.append(f"{k}={filters.get(k, '')}")
    return "|".join(parts)


def _tag_items_for_search(items, search):
    """Fix listing-type flags from the *search* we ran.

    eBay mobile/desktop cards often omit 'Gebot'/'Auktion' text. Then the HTML
    parser leaves auction=False / buy_now=True, so auction-search hits land in
    Sofort buckets and Auktion stays empty — the main 'нет данных' lie after
    a successful auction page fetch.
    """
    if not items:
        return items or []
    lt = (search.get("filters") or {}).get("listing_type", "all")
    out = []
    for raw in items:
        it = raw
        # time-left is a strong auction signal even on mixed pages
        if it.get("time_left") and not it.get("auction"):
            it = dict(it)
            it["auction"] = True
        if lt == "auction":
            it = dict(it)
            it["auction"] = True
            # Pure auction SERP: default parser buy_now=True is wrong unless hybrid.
            if not it.get("_was_hybrid"):
                it["buy_now"] = False
            if it.get("auc_price") is None and it.get("price") is not None:
                it["auc_price"] = it.get("price")
            if it.get("auc_total_price") is None and it.get("total_price") is not None:
                it["auc_total_price"] = it.get("total_price")
        elif lt in ("buy_now", "buy_now_offer"):
            it = dict(it)
            it["buy_now"] = True
            if it.get("bin_price") is None and it.get("price") is not None:
                it["bin_price"] = it.get("price")
            if it.get("bin_total_price") is None and it.get("total_price") is not None:
                it["bin_total_price"] = it.get("total_price")
        out.append(it)
    return out


def _fetch_quota_html(search, force=False):
    global _runtime_html_fallback
    _runtime_html_fallback = True
    target = (search.get("id", ""), EBAY_MARKETPLACE_ID)
    if not force and target not in _allowed_api_targets_this_run:
        return [], "api_deferred"
    _allowed_api_targets_this_run.discard(target)
    if not force:
        browse_access.record_html_attempt(search.get("id", ""), EBAY_MARKETPLACE_ID)
    child = copy.deepcopy(search)
    child["_html_fallback"] = True
    # Return the HTML error itself if it fails. No API loop and no fake empty.
    logger.info("Browse quota paused; checking %s through HTML", search.get("query"))
    from query_variants import api_query_batches
    batches = api_query_batches(_search_query_variants(search))
    collected, errors = [], []
    formats = ["buy_now", "auction"] if (search.get("filters") or {}).get("listing_type","all") == "all" else [None]
    for listing in formats:
        for query in batches or [_intent_query(search)]:
            variant = copy.deepcopy(child)
            variant.update(_query_override=query, _variant_child=True)
            if listing:
                variant.setdefault("filters",{})["listing_type"] = listing
            found, error = fetch_ebay_ex(variant, force=force)
            collected.extend(found)
            if error:
                errors.append(error)
                break
    rows, error = _merge_items_by_id(collected), errors[0] if errors else None
    if error is None:
        record_search_run(search.get("id", ""), EBAY_MARKETPLACE_ID)
    return [{**row,"source":"html"} for row in rows], error


def fetch_ebay_ex(search, force=False):
    """Returns (items, error). Tries host chain: remembers a working one,
    falls back to next host on block/rate_limit. After sustained blocks the
    eBay client cools down for a while so a flagged IP can recover.
    error: None | 'rate_limit' | 'blocked' | 'cooldown' | 'network' | 'http_<code>' | 'parse' | 'api_*'.
    """
    global _ebay_active_host, _ebay_block_until, _ebay_consecutive_blocks
    now = time.time()
    source = "html" if search.get("_html_fallback") else EBAY_SOURCE if EBAY_SOURCE in ("auto", "html", "api") else "auto"
    if source != "html" and _ebay_api_configured() and browse_access.is_paused() is True:
        return _fetch_quota_html(search, force=force)

    # Short per-query cache: absorbs duplicate calls from the UI ('Retry'
    # button spam, double-presses) so we don't hammer eBay.
    # force=True bypasses cache so stats retries after a soft-block can re-hit HTML.
    cache_key = _query_cache_key(search)
    if not force:
        cached = _ebay_query_cache.get(cache_key)
        if cached and now - cached[0] < _EBAY_QUERY_CACHE_TTL:
            items, err = cached[1], cached[2]
            logger.info("  %s -> cached (%ds old, %d items, err=%s)",
                        search["query"], int(now - cached[0]), len(items), err)
            return items, err

    # With credentials, auto uses Browse immediately. Empty is a valid result;
    # A quota pause switches to the existing paced HTML transport exactly once.
    if source == "api" or (source == "auto" and _ebay_api_configured()):
        from query_variants import api_query_batches
        variants=api_query_batches(_search_query_variants(search))
        if len(variants)>1:
            merged=[];errors=[]
            for index, query in enumerate(variants):
                child=copy.deepcopy(search);child['_query_override']=query;child['_variant_child']=True;child['_api_query_batch']=True
                # The scheduler reserves one product. Later aliases belong to
                # that reservation; acquire() still checks quota and cooldown.
                rows,error=fetch_ebay_api_ex(child,force=force or index > 0)
                merged.extend(rows)
                if error:
                    errors.append(error)
                    break
            items,err=_merge_items_by_id(merged), errors[0] if errors else None
        else:
            child=copy.deepcopy(search)
            if variants:
                child['_query_override']=variants[0];child['_variant_child']=True;child['_api_query_batch']=True
            items, err = fetch_ebay_api_ex(child, force=force)
        if err == "api_rate_limit":
            return _fetch_quota_html(search, force=force)
        _ebay_query_cache[cache_key] = (time.time(), items, err)
        return items, err

    variants = _search_query_variants(search)
    if len(variants) > 1 and not search.get("_variant_child"):
        merged_items = []
        errors = []
        saw_clean_empty = False
        # On GH: primary query first; if empty try at most ONE alias.
        # Full 3–5 variant bursts × many products was the main reason eBay
        # flipped to soft-empty / rate-limit mid statistics report.
        if _on_github_actions():
            order = list(variants)[:2]
        else:
            order = list(variants)
        for qi, query in enumerate(order):
            # Stop at the first alias that worked — but only when nothing failed
            # on the way. eBay answers curl with a 403 or a 14 KB shell now and
            # then (measured 2026-07-27), and stopping on a set collected around
            # such a failure silently reports a partial market as complete.
            if qi > 0 and merged_items and not errors:
                break
            # Primary already saw a real empty SERP — do not burn a second
            # alias (PW crashes + API) and then upgrade empty → network/block.
            if qi > 0 and saw_clean_empty and not errors:
                break
            variant = copy.deepcopy(search)
            variant["_query_override"] = query
            variant["_variant_child"] = True
            variant_items, variant_err = fetch_ebay_ex(variant, force=force)
            if variant_items:
                merged_items.extend(variant_items)
            elif variant_err is None:
                saw_clean_empty = True
            elif variant_err:
                errors.append(variant_err)
        merged_items = _merge_items_by_id(merged_items)
        if merged_items:
            err = None
        elif saw_clean_empty:
            # At least one variant returned a clean empty page — honest empty,
            # not the last alias's network/PW crash.
            err = None
        else:
            err = errors[-1] if errors else None
        logger.info(
            "  %s -> %d merged items via %d/%d query variants (empty_ok=%s err=%s)",
            search["query"], len(merged_items), len(order), len(variants),
            saw_clean_empty, err,
        )
        _ebay_query_cache[cache_key] = (time.time(), merged_items, err)
        return merged_items, err

    if source == "api":
        items, err = fetch_ebay_api_ex(search, force=force)
        _ebay_query_cache[cache_key] = (time.time(), items, err)
        return items, err

    if now < _ebay_block_until:
        wait = int(_ebay_block_until - now)
        logger.info("eBay cooldown active, %d s left", wait)
        # On GH/stats we still try Playwright per query — a full 5–60 min skip
        # turns every remaining product into fake empty / rate-limit rows.
        if _on_github_actions() or force:
            pw_url = _build_url_with_host("ebay.de", search)
            pw_items, pw_err = _do_fetch_playwright(pw_url, search.get("query", ""))
            if pw_items:
                _ebay_consecutive_blocks = 0
                _ebay_block_until = 0.0
                _ebay_query_cache[cache_key] = (time.time(), pw_items, None)
                return pw_items, None
        if source == "auto" and _ebay_api_configured() and not _ebay_api_circuit_open:
            items, err = fetch_ebay_api_ex(search, force=force)
            if err is None and items:
                _ebay_query_cache[cache_key] = (time.time(), items, None)
                return items, None
            logger.warning("eBay API fallback failed during HTML cooldown: %s", err)
        return [], "cooldown"

    logger.info("Fetching: %s", search["query"])

    chain = _host_chain_for_search(search)
    if _ebay_active_host and _ebay_active_host in chain:
        chain.remove(_ebay_active_host)
        chain.insert(0, _ebay_active_host)

    def _try_chain(referer=None):
        last = None
        saw_clean_empty = False
        # Per-host retries: first attempt uses the current impersonation
        # profile, the second one rotates to the next profile and re-warms
        # the session. eBay sometimes flags one fingerprint while leaving
        # the next alone, so this turns a transient block into a hit.
        attempts_per_host = 3 if _on_github_actions() else 2
        for host in chain:
            for attempt in range(attempts_per_host):
                its, e = _do_fetch_one(host, search, referer=referer)
                if its:
                    return its, None, host
                # Soft/true empty (err None): do NOT keep a prior "blocked" —
                # `last = last or None` was wrong (blocked stays blocked) and
                # upgraded real empty SERPs (LG/G6/Z80 LV) to eBay block after
                # one soft-block attempt earlier in the chain.
                if e is None and not its:
                    saw_clean_empty = True
                    last = None
                    if _on_github_actions() and attempt < attempts_per_host - 1:
                        reset_ebay_session(rotate=True)
                        continue
                    # Last attempt on this host with clean empty — try next host.
                    reset_ebay_session(rotate=True)
                    break
                last = e
                if e in ("blocked", "rate_limit", "parse"):
                    # Last attempt for this host? Roll over to the next host.
                    if attempt == attempts_per_host - 1:
                        reset_ebay_session(rotate=True)
                        break
                    # Otherwise rotate fingerprint and try the same host again.
                    reset_ebay_session(rotate=True)
                    continue
                # network: still try next host
                reset_ebay_session(rotate=True)
                break
        # Any clean empty SERP in the chain wins over earlier soft-blocks.
        if saw_clean_empty and last in (None, "blocked", "parse", "network"):
            return [], None, None
        return [], last, None

    items, err, host = _try_chain()
    if items:
        _ebay_active_host = host
        _ebay_consecutive_blocks = 0
        logger.info("  %s -> %d items via %s", search["query"], len(items), host)
        _ebay_query_cache[cache_key] = (time.time(), items, None)
        return items, None

    # True empty SERP from curl (0 itm, result chrome) — e.g. unlisted models.
    # Must NOT be upgraded to eBay block / API 429 by a later Playwright crash.
    html_confirmed_empty = (err is None)

    # Chromium recovery when chain failed or to double-check soft empties.
    if not items and err in (None, "blocked", "rate_limit", "parse", "network"):
        pw_urls = [
            _build_url_with_host("ebay.de", search, sub="www"),
            _build_url_with_host("ebay.de", search, sub="m"),
        ]
        pw_err = None
        for pw_url in pw_urls:
            pw_items, pw_err = _do_fetch_playwright(pw_url, search.get("query", ""))
            if pw_items:
                _ebay_consecutive_blocks = 0
                _ebay_query_cache[cache_key] = (time.time(), pw_items, None)
                return pw_items, None
            if pw_err is None:
                _ebay_consecutive_blocks = 0
                _ebay_query_cache[cache_key] = (time.time(), [], None)
                return [], None
            if pw_err in ("no_playwright",):
                break
        if html_confirmed_empty:
            # Only genuine no-results marker (err=None from parse). Soft-empty
            # is now "parse", so PW crash will surface as transport fail, not
            # "Не найдено" while live stock exists (Z80 Ultra audit).
            logger.info(
                "HTML genuine empty for '%s'; ignoring PW fail (%s)",
                search.get("query"), pw_err,
            )
            _ebay_consecutive_blocks = 0
            _ebay_query_cache[cache_key] = (time.time(), [], None)
            return [], None
        if pw_err and pw_err not in ("no_playwright",):
            err = pw_err or err

    if err is None and not items:
        _ebay_query_cache[cache_key] = (time.time(), [], None)
        return [], None

    if err not in ("blocked", "rate_limit", "network", "parse"):
        _ebay_query_cache[cache_key] = (time.time(), items or [], err)
        return items or [], err

    # API only after real HTML transport failure — never after confirmed empty SERP
    # (empty + API 429 was painting Z80 LV as eBay block and opening the circuit).
    if (
        source == "auto"
        and not html_confirmed_empty
        and _ebay_api_configured()
        and not _ebay_api_circuit_open
    ):
        logger.info("eBay HTML exhausted (%s), trying Browse API last resort", err)
        api_items, api_err = fetch_ebay_api_ex(search, force=force)
        if api_err is None:
            # Clean API response — 0 items is honest empty, NOT a failure.
            # (Was: only accepted non-empty, then "API failed: None" + kept network.)
            if api_items:
                _ebay_query_cache[cache_key] = (time.time(), api_items, None)
                return api_items, None
            if _is_auction_only_search(search):
                # buyingOptions:{AUCTION} coverage is thin, so an API 0 cannot
                # confirm an empty auction market once the HTML side died on
                # transport. Report the transport failure — «сбой загрузки»
                # is honest, «Не найдено» would not be. Return it straight:
                # one thin auction bucket is not an eBay outage, so it must not
                # bump _ebay_consecutive_blocks or arm the local cooldown.
                logger.info(
                    "  %s -> auction API 0 items after HTML %s — keeping %s, not empty",
                    search.get("query"), err, err,
                )
                _ebay_query_cache[cache_key] = (time.time(), [], err)
                return [], err
            else:
                _ebay_query_cache[cache_key] = (time.time(), [], None)
                logger.info(
                    "  %s -> Browse API clean empty (0 items) after HTML %s",
                    search.get("query"), err,
                )
                return [], None
        else:
            logger.warning("eBay API last-resort failed: %s", api_err)
            err = api_err or err

    # Still blocked / transport-fail. On GH never arm multi-product cooldown.
    _ebay_consecutive_blocks += 1
    if _on_github_actions():
        # Do not call every network/parse fail "eBay block" — logs + run_log
        # classifier treated soft fails as full outages.
        kind = err or "blocked"
        logger.warning(
            "eBay fetch fail #%d (%s) for '%s' on GH — no cooldown, next product retries",
            _ebay_consecutive_blocks, kind, search.get("query"),
        )
        _ebay_query_cache[cache_key] = (time.time(), [], kind)
        return [], kind
    cooldown = min(
        _EBAY_BLOCK_COOLDOWN_MAX,
        _EBAY_BLOCK_COOLDOWN_BASE * (2 ** (_ebay_consecutive_blocks - 1)),
    )
    _ebay_block_until = time.time() + cooldown
    logger.warning(
        "eBay sustained block #%d, cooling down for %ds",
        _ebay_consecutive_blocks, cooldown,
    )
    _ebay_query_cache[cache_key] = (time.time(), [], "cooldown")
    return [], "cooldown"


# Version label for Telegram = contents of logic_version.txt only.
#
# Why not git log / HEAD / "(live)" wall-clock:
# - Actions checkout is depth=1. On a shallow tip, `git log -- <path>` treats the
#   single commit as introducing every file, so path-based "last code commit"
#   collapses to the latest *state* commit time (changes every run). That is
#   what produced drifting 20:40 / 21:16 / 21:44 "versions".
# - State sync (Update/Checkpoint monitor state, mode toggles) must never bump
#   the version. They never touch logic_version.txt.
#
# Bump logic_version.txt (unix UTC seconds on the first line) whenever you change
# bot logic / filters / bugfixes. Leave it alone for state-only commits.

LOGIC_VERSION_FILENAME = "logic_version.txt"
_STABLE_VERSION_CACHE = None


def _format_version_timestamp(timestamp):
    from datetime import datetime, timezone, timedelta
    dt = datetime.fromtimestamp(int(timestamp), timezone(timedelta(hours=2)))
    # Unicode escapes so month names survive any file encoding mishap on push.
    months = [
        "\u044f\u043d\u0432\u0430\u0440\u044f",
        "\u0444\u0435\u0432\u0440\u0430\u043b\u044f",
        "\u043c\u0430\u0440\u0442\u0430",
        "\u0430\u043f\u0440\u0435\u043b\u044f",
        "\u043c\u0430\u044f",
        "\u0438\u044e\u043d\u044f",
        "\u0438\u044e\u043b\u044f",
        "\u0430\u0432\u0433\u0443\u0441\u0442\u0430",
        "\u0441\u0435\u043d\u0442\u044f\u0431\u0440\u044f",
        "\u043e\u043a\u0442\u044f\u0431\u0440\u044f",
        "\u043d\u043e\u044f\u0431\u0440\u044f",
        "\u0434\u0435\u043a\u0430\u0431\u0440\u044f",
    ]
    return f"{dt.strftime('%H:%M')} {dt.day} {months[dt.month - 1]}"


def _logic_version_path(repo_dir=None):
    base = repo_dir or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, LOGIC_VERSION_FILENAME)


def _read_logic_version_timestamp(repo_dir=None):
    """Parse first token of logic_version.txt as unix UTC seconds."""
    path = _logic_version_path(repo_dir)
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            token = line.split()[0]
            return int(token)
    raise ValueError(f"no timestamp in {path}")


def _get_stable_version_string():
    """
    Version label for Telegram footers.

    Always the stamp from logic_version.txt (last intentional logic change).
    Never HEAD time, never run-end time, never '(live)'.
    """
    global _STABLE_VERSION_CACHE
    if _STABLE_VERSION_CACHE:
        return _STABLE_VERSION_CACHE
    try:
        ts = _read_logic_version_timestamp()
        _STABLE_VERSION_CACHE = _format_version_timestamp(ts)
        return _STABLE_VERSION_CACHE
    except Exception as exc:
        logger.warning("logic_version.txt unreadable: %s", exc)
    # Honest unknown — never wall-clock "now" and never '(live)'.
    _STABLE_VERSION_CACHE = "unknown"
    return _STABLE_VERSION_CACHE


def _get_version_string():
    return _get_stable_version_string()


def _apk_version_label():
    try:
        with open(os.path.join(os.path.dirname(__file__), "mobile", "app_version.json"), encoding="utf-8") as stream:
            return str(json.load(stream)["versionName"])
    except (OSError, ValueError, KeyError):
        return "unknown"


def _fetch_source_label(source=None):
    if source:
        return "eBay Browse API" if source == "api" else "eBay HTML" if source == "html" else str(source)
    if EBAY_SOURCE == "html" or not _ebay_api_configured():
        return "eBay HTML"
    if _runtime_html_fallback:
        return "eBay HTML (резерв после квоты API)" if browse_access.is_paused() is True else "eBay Browse API / HTML"
    return "eBay Browse API"


def get_category_emoji(cat_name):
    cat_name = (cat_name or "").strip().lower()
    mapping = {
        "phones": "📱",
        "phone_parts": "⚙️",
        "phone_accessories": "🔌",
        "tablets": "📟",
        "laptops": "💻",
        "computers": "🖥️",
        "monitors": "🖥️",
        "mice": "🖱️",
        "headphones": "🎧",
        "vr": "🥽",
        "vr_headsets": "🥽",
        "cameras": "📷",
        "video_games": "🎮",
        "consoles": "🎮",
        "smart_watches": "⌚",
        "electronics": "🔌",
    }
    return mapping.get(cat_name, "📦")


async def send_notification(bot, item, search, stats_7d=None, notify_stage="initial"):
    item_url = item.get("url") or ""
    item_id = str(item.get("item_id") or "")
    if item_id:
        if "ebay.de" in item_url:
            item_url = f"https://www.ebay.de/itm/{item_id}"
        elif "ebay" in item_url:
            from urllib.parse import urlparse
            try:
                p = urlparse(item_url)
                item_url = f"https://{p.netloc}/itm/{item_id}"
            except Exception:
                pass

    trust = _seller_trust(item["seller_rating_count"], item["seller_rating_percent"], item.get("top_rated"))
    emoji = _trust_emoji(trust)

    if item["buy_now"]:
        type_str = "Sofortkauf+" if item["best_offer"] else "Sofortkauf"
    elif item["auction"]:
        type_str = "Auktion+" if item["best_offer"] else "Auktion"
    else:
        type_str = "Sofortkauf+" if item["best_offer"] else "Sofortkauf"

    base_p = item.get("total_price", item["price"] + item["shipping_cost"])

    if item.get("is_pickup_only"):
        shipping_suffix = " (Nur Abholung)"
    else:
        shipping_suffix = ""

    outlier = is_outlier(item["price"], search["id"])

    # 1. Header: cat_emoji query_name with location & category symbols
    category_name = search.get("filters", {}).get("category")
    cat_emoji = get_category_emoji(category_name)

    query_esc = html.escape(search.get("display_name") or search.get("query", ""))
    loc = search.get("filters", {}).get("location")
    if loc == "de":
        query_esc += " 🇩🇪"
    elif loc == "eu":
        query_esc += " 🇪🇺"
    elif loc == "worldwide":
        query_esc += " 🌍"

    cat_filter = search.get("filters", {}).get("category", "all")
    if cat_filter and cat_filter != "all":
        query_esc += " ⚙️"
    else:
        query_esc += " ♾️"

    header = f"{cat_emoji} <b>{query_esc}</b>"
    if notify_stage == "final_15m":
        # Header from actual remaining time when known (avoid "15 мин" while card shows 5).
        mins = _parse_time_left_to_minutes(item.get("time_left", ""))
        if mins is not None and mins <= 5:
            header = f"🔥 <b>~{int(mins)} МИН ДО КОНЦА</b>\n{header}"
        else:
            header = f"🔥 <b>15 МИНУТ ДО КОНЦА</b>\n{header}"
    elif notify_stage == "final_hour":
        header = f"⏰ <b>1 ЧАС ДО КОНЦА</b>\n{header}"
    if outlier:
        header = f"🚨 {header}"
    if item.get("is_pickup_only"):
        header = "⚠️ <b>NUR ABHOLUNG (Без доставки)</b> ⚠️\n\n" + header

    # Helper padding function
    def pad_lbl(lbl, width=14):
        return lbl.ljust(width)

    # 2. Price Line
    esc_url = html.escape(item_url)
    if item["auction"] and not item["buy_now"]:
        bids_count = item.get("bids_count", 0)
        time_left = item.get("time_left", "")
        minutes = _parse_time_left_to_minutes(time_left)
        circle = "🟠" if (minutes is not None and minutes > 1440) else "🟢"

        if item["best_offer"]:
            price_val_str = f"🤝{base_p:.2f}€"
        else:
            price_val_str = f"{base_p:.2f}€"

        price_line = f"<a href=\"{esc_url}\">🎲</a> Цена: <a href=\"{esc_url}\">{price_val_str}</a> 🔨 {bids_count} Bids ⏳{time_left} {circle}"
    else:
        if item["best_offer"]:
            price_val_str = f"🤝 {base_p:.2f}€"
        else:
            price_val_str = f"{base_p:.2f}€"

        price_line = f"<a href=\"{esc_url}\">🛍</a> Цена: <a href=\"{esc_url}\">{price_val_str}</a>"

    # Add shipping suffix to price line if present
    if shipping_suffix:
        price_line += f" {shipping_suffix}"

    price_line += f"\nТовар: {item['price']:.2f}€ · Доставка: {item['shipping_cost']:.2f}€"

    # 3. Type Line
    type_line = f"🏷 Тип: {type_str}"

    # 4. Description Line
    desc_line = f"📌 Описание: {html.escape(item['title'])}"

    # 5. Details Table: Condition, Country, Seller, Limit
    cond_str = html.escape(item["condition"]) if item.get("condition") else "Не указано"
    cond_line = f"📦 <code>{pad_lbl('Состояние')}│  </code>{cond_str}"

    country_val = _format_country_for_notification(item.get("location", ""))
    country_line = f"🌐 <code>{pad_lbl('Страна')}│  </code>{country_val}"

    rating_count = item.get("seller_rating_count", 0)
    rating_str = f" ({rating_count} отзывов)" if rating_count > 0 else " (0 отзывов)"
    seller_val = f"{emoji} {html.escape(item['seller_name'])}{rating_str}"
    seller_line = f"👤 <code>{pad_lbl('Продавец')}│  </code>{seller_val}"

    limit_val = search.get("filters", {}).get("limit_price")
    max_price_val = search.get("filters", {}).get("max_price")
    min_price_val = search.get("filters", {}).get("min_price")

    limit_parts = []
    limit_parts.append(f"🎯 {limit_val:.0f}€" if limit_val is not None else "🎯 ♾️")
    limit_parts.append(f"⬆️ {max_price_val:.0f}€" if max_price_val is not None else "⬆️ ♾️")
    limit_parts.append(f"⬇️ {min_price_val:.0f}€" if min_price_val is not None else "⬇️ ♾️")
    limit_val_str = " ".join(limit_parts)
    limit_line = f"💸 <code>{pad_lbl('Лимит:')}│  </code>{limit_val_str}"

    # 6. Extra details
    extra_lines = []
    if item["location"]:
        from plz_distance import is_nearby, get_distance_from_location
        nearby, dist_km = is_nearby(item["location"], max_km=100)
        if nearby:
            if dist_km is not None:
                if dist_km > 120:
                    extra_lines.append(f"📍 <b>Дистанция:</b> Abholung ~{dist_km:.0f}km (Berlin)")
                else:
                    extra_lines.append(f"📍 <b>Дистанция:</b> Abholung ~{dist_km:.0f}km")
            else:
                extra_lines.append(f"📍 <b>Дистанция:</b> Abholung möglich")

    if item["total_price"] != item["price"] + item["shipping_cost"]:
        import_extra = item["total_price"] - item["price"] - item["shipping_cost"]
        extra_lines.append(f"⚠️ <b>Пошлина:</b> +{import_extra:.2f}€ пошлина → итого {item['total_price']:.2f}€")

    if outlier:
        median = get_median_7d(search["id"])
        if median:
            extra_lines.append(f"⚠️ <b>Подозрительно низкая цена</b> (медиана: {median:.0f}€)\nНе учтено в статистике")
    elif stats_7d and stats_7d.get("median"):
        median = stats_7d["median"]
        diff_pct = ((median - item["price"]) / median) * 100
        if diff_pct > 5:
            extra_lines.append(f"🔥 <b>Скидка:</b> {item['price']:.0f}€ — на {diff_pct:.0f}% ниже медианы! ({stats_7d['first_date']}–{stats_7d['last_date']})")

    # 7. Assemble deep links
    try:
        bot_info = await bot.get_me()
        bot_username = bot_info.username
    except Exception:
        bot_username = "FunPayMonitor1488_BOT"

    import base64
    try:
        encoded_seller = base64.urlsafe_b64encode(item['seller_name'].encode('utf-8')).decode('utf-8').rstrip('=')
    except Exception:
        encoded_seller = "unknown"

    hide_url = f"https://t.me/{bot_username}?start=ban_{item['item_id']}"
    ban_url = f"https://t.me/{bot_username}?start=banseller_{encoded_seller}"

    links_line = f"🔗 <a href=\"{html.escape(item_url)}\">Ссылка</a>  │  ❌ <a href=\"{html.escape(hide_url)}\">Скрыть</a>  │  🚫 <a href=\"{html.escape(ban_url)}\">Бан</a>"

    is_github = os.environ.get("GITHUB_ACTIONS") == "true"
    source_line = "🤖 GitHub автомониторинг" if is_github else "💻 Локальный автомониторинг"
    source_line += f"\nℹ️ Сервер: {_get_version_string()}\n📱 APK: {_apk_version_label()}\n🔎 Поиск: {_fetch_source_label(item.get('source'))}"

    details_block = f"{cond_line}\n{country_line}\n{seller_line}\n{limit_line}"

    parts = [header, price_line, type_line, desc_line, details_block]
    if extra_lines:
        parts.append("\n".join(extra_lines))
    parts.append(source_line)
    parts.append(links_line)

    caption = "\n\n".join(parts)
    if item.get("_audit_test"):
        caption = "🧪 <b>ТЕСТ APK ↔ Telegram</b>\n" + caption

    img = item.get("image_url") or ""
    # Long HTML is sent as text; cutting HTML can break a link or formatting tag.
    if len(caption) > 1024:
        img = ""
    if img and not img.startswith("data:"):
        import re as _re
        img = _re.sub(r"/s-l\d+\.(jpg|jpeg|png|webp)", r"/s-l800.\1", img, flags=_re.IGNORECASE)

    logger.info("send_notification: %s", caption.replace("\n", " | "))
    try:
        sent = await safe_send_telegram(
            bot,
            TELEGRAM_CHAT_ID,
            caption,
            img=img,
            keyboard=None,
            parse_mode="HTML"
        )
        if sent:
            item["_telegram_message_id"] = getattr(sent, "message_id", None)
        return bool(sent)
    except Exception as e:
        logger.error("send_notification error: %s", e)
        return False


# Sticky menu: message ID of the last "menu" message at the bottom of the chat.
# We delete the old one and send a new one after each batch of notifications
# so the menu is always at the bottom, not buried under new items.
_sticky_menu_msg_id = None


async def _refresh_sticky_menu(bot):
    """Delete old sticky menu and send a fresh one at the bottom of the chat."""
    global _sticky_menu_msg_id
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    # Delete old sticky menu
    if _sticky_menu_msg_id:
        try:
            await bot.delete_message(chat_id=TELEGRAM_CHAT_ID, message_id=_sticky_menu_msg_id)
        except Exception:
            pass
        _sticky_menu_msg_id = None

    # Build a compact menu message
    searches = config.get_searches()
    from settings_handlers import _search_groups
    groups = _search_groups(searches)
    text = f"📋 <b>{len(groups)}</b> товаров · <b>{len(searches)}</b> вариантов"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Поиски", callback_data="m:list"),
            InlineKeyboardButton("🔎 Проверка", callback_data="m:actual"),
        ],
        [
            InlineKeyboardButton("🚫 Фильтры", callback_data="m:filters"),
            InlineKeyboardButton("⚙️ Меню", callback_data="m:main"),
        ],
    ])

    try:
        msg = await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        _sticky_menu_msg_id = msg.message_id
    except Exception as e:
        logger.debug("sticky menu send error: %s", e)


async def safe_send_telegram(bot, chat_id, text, img=None, keyboard=None, parse_mode="HTML", force_backup=False):
    backup_token = os.environ.get("TELEGRAM_BOT_TOKEN_BACKUP")

    bots_to_try = []
    if force_backup and backup_token:
        try:
            from telegram import Bot as TelegramBot
            bots_to_try.append(TelegramBot(token=backup_token))
        except Exception as eb:
            logger.error("Failed to initialize backup bot: %s", eb)

    bots_to_try.append(bot)

    if not force_backup and backup_token:
        try:
            from telegram import Bot as TelegramBot
            bots_to_try.append(TelegramBot(token=backup_token))
        except Exception:
            pass

    for active_bot in bots_to_try:
        try:
            if img and not img.startswith("data:"):
                message = await active_bot.send_photo(
                    chat_id=chat_id,
                    photo=img,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode,
                )
            else:
                message = await active_bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )
            return message
        except Exception as e:
            from telegram.error import BadRequest
            if img and isinstance(e, BadRequest):
                # A definite photo rejection delivered nothing; text is safe to
                # retry. An ambiguous timeout is never retried by this fallback.
                try:
                    return await active_bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard,
                                                         parse_mode=parse_mode, disable_web_page_preview=True)
                except Exception as fallback_error:
                    logger.warning("Telegram text fallback failed: %s", fallback_error)
            logger.warning("Failed to send message via bot: %s. Trying next...", e)

    return False


def _is_item_page_multivariation(item_id):
    """Fetches the item web page and parses it to check if it's a multi-variation listing."""
    session = _get_ebay_session()
    host = _ebay_active_host or "ebay.de"
    url = f"https://www.{host}/itm/{item_id}"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        r = session.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            html_content = r.text
            # 1. Check for standard Multi-SKU strings/classes in HTML
            if any(k in html_content for k in ("x-msku", "vi-msku", "msku-select", "itm-variation", "x-msku-evo")):
                return True
            # 2. Check for selecting drop-downs that are native listboxes but not feedback
            soup = BeautifulSoup(html_content, "html.parser")
            selects = soup.find_all("select")
            for s in selects:
                name = s.get("name", "") or ""
                s_id = s.get("id", "") or ""
                s_class = s.get("class") or []
                if "feedbackFilterDropdown" not in name and "feedbackFilterDropdown" not in s_id:
                    if "listbox__native" in s_class or any("msku" in c for c in s_class):
                        return True
    except Exception as e:
        logger.warning("_is_item_page_multivariation error for %s: %s", item_id, e)
    return False


async def _validate_candidate(item, search):
    details = await asyncio.to_thread(_fetch_item_details, item["item_id"])
    if details:
        item["_details_status"] = "rejected"
        if not _details_match_contract(item, search, details):
            return False, details
        _refresh_candidate_details(item, details, config.get_settings())
        # Price limits are represented by the statistics verdict; all structural
        # filters still apply to the actual country, condition and radius.
        structural = copy.deepcopy(search)
        structural.setdefault("filters", {}).update(min_price=None, limit_price=None, max_price=None)
        if not filter_results([item], structural, config, skip_seen=True, is_statistics=True):
            return False, details
    else:
        item["_details_status"] = "unavailable"
        return False, None

    if _is_implausibly_cheap_device(item, search):
        return False, details

    if not _intent_details_match(search, item, details):
        logger.info("Blocking item %s: does not satisfy search intent for %s", item.get("item_id"), search.get("query"))
        return False, details

    item["_details_status"] = "verified"
    return True, details


def _live_validation_price_window(search_cfg):
    filters = search_cfg.get("filters", {}) or {}
    category = _effective_category(filters.get("category", "all"), _normalize(search_cfg.get("query", "")))
    if category in ("phones", "computers", "laptops"):
        return 300.0
    if category in ("consoles", "monitors"):
        return 200.0
    return 100.0


def _live_validation_limit(search_cfg):
    query_norm = _normalize(search_cfg.get("query", ""))
    filters = (search_cfg.get("filters") if isinstance(search_cfg, dict) else {}) or {}
    category = _effective_category(filters.get("category", "all"), query_norm)
    if "samsung s24 ultra" in query_norm:
        return 40
    # Accessory noise used to burn a short budget before real phones appear.
    if category == "phones" or _is_phone_search_query(query_norm):
        return 80
    if category == "headphones" or "sony wh" in query_norm:
        return 50
    return 40


async def _select_cheapest_valid_candidate(items, search_cfg, limit=None, stats_soft_fallback=False):
    if limit is None:
        limit = len(items)
    price_window = _live_validation_price_window(search_cfg)
    valid_items = []
    soft_pool = []
    query_norm = _normalize(search_cfg.get("query", ""))
    category = _effective_category(
        (search_cfg.get("filters") or {}).get("category", "all"), query_norm
    )
    checked = 0
    for item in items:
        if checked >= limit:
            break
        if item.get("is_multivariation"):
            continue
        card_total = float(item.get("total_price") or item.get("price") or 0)
        # Only stop early once we already have a VALID device and the rest is far more expensive.
        if valid_items:
            best_total = min(float(x.get("total_price") or 0) for x in valid_items)
            if card_total > best_total + price_window:
                break
        checked += 1
        title_norm = _normalize(item.get("title") or "")
        if (
            stats_soft_fallback
            and title_norm
            and not _is_implausibly_cheap_device(item, search_cfg)
            and not _is_category_blocked_title(title_norm, category, query_norm)
            and not _is_for_accessory_title(title_norm, query_norm, category)
        ):
            soft_pool.append(item)
        is_valid, _ = await _validate_candidate(item, search_cfg)
        if is_valid:
            valid_items.append(item)
            logger.info(
                "Stats candidate OK [%s] total=%.0f title=%s",
                item.get("item_id"),
                float(item.get("total_price") or 0),
                (item.get("title") or "")[:60],
            )
        else:
            logger.info(
                "Stats candidate reject [%s] total=%.0f title=%s",
                item.get("item_id"),
                card_total,
                (item.get("title") or "")[:60],
            )
    unavailable_pool = [x for x in soft_pool if x.get("_details_status") == "unavailable"]
    if not valid_items and stats_soft_fallback and unavailable_pool:
        selected = min(unavailable_pool, key=lambda x: float(x.get("total_price") or 0))
        logger.info(
            "Stats soft-fallback [%s] total=%.0f for %s (details validation all failed)",
            selected.get("item_id"),
            float(selected.get("total_price") or 0),
            search_cfg.get("query"),
        )
        return selected
    if not valid_items:
        logger.info(
            "Stats candidate: no valid of %d checked for %s",
            checked,
            search_cfg.get("query"),
        )
        return None
    selected = min(valid_items, key=lambda x: float(x.get("total_price") or 0))
    logger.info(
        "Stats selected [%s] total=%.0f for %s",
        selected.get("item_id"),
        float(selected.get("total_price") or 0),
        search_cfg.get("query"),
    )
    return selected


_allowed_api_targets_this_run = set()

def initialize_api_budget_and_queue(searches):
    global _allowed_api_targets_this_run, _runtime_html_fallback
    _runtime_html_fallback = False
    active = [s for s in searches if s.get("enabled", True)]
    token, err = _get_ebay_api_token()
    state = browse_access.state()
    if token and time.time() - state.get("checked", 0) >= 900:
        req = urllib.request.Request(
            "https://api.ebay.com/developer/analytics/v1_beta/rate_limit?api_name=browse&api_context=buy",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                browse_access.update_quota(json.loads(resp.read().decode("utf-8")))
        except Exception as exc:
            logger.warning("eBay quota refresh unavailable: %s", exc)
    quota_paused = browse_access.is_paused() is True
    interval = 900 if quota_paused else browse_access.interval(len(active))
    state = browse_access.state()
    if state.get('remaining',1)<=0 and state.get('reset',0)>time.time():
        from datetime import datetime, timezone
        reset = datetime.fromtimestamp(state['reset'],timezone.utc).isoformat()
        _runtime_html_fallback = True
        logger.info("Browse quota exhausted until %s; using paced HTML checks", reset)
    from datetime import datetime
    now = datetime.now()
    due = set()
    priority = {}
    for search in active:
        last = get_last_run(search.get("id", ""), EBAY_MARKETPLACE_ID)
        try:
            elapsed = (now - datetime.fromisoformat(last)).total_seconds() if last else float("inf")
        except (ValueError, TypeError):
            elapsed = float("inf")
        if quota_paused:
            attempted = state.get("html_attempts", {}).get(str(search.get("id", ""))+"|"+EBAY_MARKETPLACE_ID)
            if attempted:
                elapsed = min(elapsed, time.time()-attempted)
        if elapsed >= interval:
            target = (search.get("id", ""), EBAY_MARKETPLACE_ID)
            due.add(target)
            priority[target] = elapsed
    if quota_paused:
        # A HTML sweep must checkpoint before the runner's execution limit.
        # Oldest due searches go first; subsequent passes continue the queue.
        due = set(sorted(due, key=lambda target: (-priority[target], target))[:8])
    _allowed_api_targets_this_run = due
    state = browse_access.state()
    logger.info("eBay Browse: %d/%d searches due; interval %.0fs; real quota remaining=%s, reset=%s",
                len(due), len(active), interval, state.get("remaining", "unknown"), state.get("reset", "unknown"))



def _notify_candidates_from_filtered(filtered):
    """Pick items for the initial notify or an auction re-notify.

    Stages: initial (lot qualifies, ≤24 h left) → final_hour (≤1 h) →
    final_15m (last call before the hammer). The time here comes from the
    search card, which is coarse, so the windows are wide; the exact end date
    from the item details makes the final call in _process_notify_candidate.
    """
    candidates = []
    for r in filtered:
        iid = str(r.get("item_id") or "")
        if not iid:
            continue
        r["item_id"] = iid
        entry = get_seen_entry(iid)
        if not entry.get("initial"):
            candidates.append((r, "initial"))
            continue
        if not (r.get("auction") and not r.get("buy_now")):
            continue
        minutes = _parse_time_left_to_minutes(r.get("time_left", ""))
        if not entry.get("final_15m") and (
            minutes is not None and minutes <= FINAL_15M_CANDIDATE_MINUTES
        ):
            candidates.append((r, "final_15m"))
            continue
        if entry.get("final_hour"):
            continue
        if minutes is not None and minutes > FINAL_HOUR_CANDIDATE_MINUTES:
            continue
        candidates.append((r, "final_hour"))
    return candidates


async def _process_notify_candidate(bot, item, search, stats_7d, stage):
    """Validate details and send one notification stage. Returns True if sent."""
    item["item_id"] = str(item.get("item_id") or "")
    if get_seen_entry(item["item_id"]).get(stage):
        return False
    # Never spam the chat with incomplete SERP shells (APK-style "Seller: unknown").
    seller = (item.get("seller_name") or "").strip()
    if not seller or seller.lower() in ("unknown", "n/a", "-", "none"):
        logger.info(
            "Skipping notification for item %s: seller missing/unknown",
            item.get("item_id"),
        )
        return False
    h = _item_hash(item["seller_name"], item["title"], item["price"])
    details = await asyncio.to_thread(_fetch_item_details, item["item_id"])
    if not details:
        # APK also keeps unavailable descriptions preliminary. Leave the stage
        # unconfirmed so a later scan can retry after eBay becomes reachable.
        logger.warning("Skipping notification for item %s: details unavailable; will retry", item["item_id"])
        return False
    if not _details_match_contract(item, search, details):
        logger.info("Skipping notification for item %s: details do not pass common rules", item["item_id"])
        return False
    if details:
        _refresh_candidate_details(item, details, config.get_settings())
        if not filter_results([item], search, config, skip_seen=True):
            logger.info("Skipping notification for item %s: refreshed details no longer pass search", item["item_id"])
            return False
        h = _item_hash(item["seller_name"], item["title"], item["price"])

    if stage in ("final_hour", "final_15m"):
        # Re-notify only while the deal still stands: the price moved with every
        # bid since the first alert.
        if not _price_within_limit(item, search):
            logger.info(
                "Skipping %s notify for item %s: price no longer within limit",
                stage, item["item_id"],
            )
            return False
        gate = FINAL_15M_MINUTES if stage == "final_15m" else FINAL_HOUR_MINUTES
        minutes = _parse_time_left_to_minutes(item.get("time_left", ""))
        if minutes is None or minutes > gate:
            logger.info(
                "Skipping %s notify for item %s: time_left=%s (need ≤%d min)",
                stage, item["item_id"], item.get("time_left"), gate,
            )
            return False
        if not (item.get("auction") and not item.get("buy_now")):
            return False
    else:
        if not _passes_notification_price_and_auction_rules(item, search):
            logger.info(
                "Skipping notification for item %s: price/auction rules failed after details refresh",
                item["item_id"],
            )
            return False

    # Reserve stage before send to prevent double-notify across overlapping runs
    previous_seen = get_seen_entry(item["item_id"])
    mark_seen_item(item["item_id"], stage=stage)
    sent = await send_notification(bot, item, search, stats_7d, notify_stage=stage)
    if sent:
        try:
            from mobile.feed_writer import enqueue
            enqueue(item, search, telegram_message_id=item.get("_telegram_message_id"),
                    notify_stage=stage, logic_version=_read_logic_version_timestamp(),
                    seller_trust=_seller_trust(item.get("seller_rating_count", 0),item.get("seller_rating_percent", 0),item.get("top_rated", False)))
        except Exception:
            logger.exception("Telegram delivered; mobile feed publication pending for %s", item["item_id"])
        if stage == "initial" and not item.get("auction"):
            config.add_item_hash(h)
        return True
    logger.warning(
        "Notification failed; will retry item %s stage=%s on next run",
        item["item_id"], stage,
    )
    if any(previous_seen.values()):
        seen_state[item["item_id"]] = previous_seen
    else:
        seen_state.pop(item["item_id"], None)
    save_seen_ids()
    return False


async def process_searches(bot, once=False):
    async with process_lock:
        try:
            from mobile.feed_writer import flush_pending
            flush_pending()
        except Exception:
            logger.exception("Mobile feed publication retry failed")
        searches = config.get_searches()
        initialize_api_budget_and_queue(searches)
        modified = False

        # Explicit user settings replace the legacy hard-coded product migrations.
        if not config.raw.get("mobile_managed"):
            # 1. Reorder searches programmatically
            id_order = [
                "redmagic_11_pro_buy", "redmagic_11_pro_auc",
                "redmagic_11s_pro_buy", "redmagic_11s_pro_auc",
                "nubia_z80_ultra_buy", "nubia_z80_ultra_auc",
                "nubia_z80_ultra_leading_buy", "nubia_z80_ultra_leading_auc",
                "nubia_z70_ultra_buy", "nubia_z70_ultra_auc",
                "nubia_z70s_ultra_buy", "nubia_z70s_ultra_auc"
            ]
            by_id = {s["id"]: s for s in searches}
            new_searches = []
            for s_id in id_order:
                if s_id in by_id:
                    new_searches.append(by_id[s_id])
            for s in searches:
                if s["id"] not in id_order:
                    new_searches.append(s)
            if [s["id"] for s in searches] != [s["id"] for s in new_searches]:
                searches[:] = new_searches
                modified = True

            # 1.5 Migrate location filters from "eu" to "worldwide"
            for s in searches:
                filters = s.setdefault("filters", {})
                if filters.get("location") == "eu":
                    filters["location"] = "worldwide"
                    modified = True

            banned_items = config.raw.setdefault("banned_item_ids", [])
            for item_id in sorted(KNOWN_BAD_ITEM_IDS):
                if item_id not in banned_items:
                    banned_items.append(item_id)
                    modified = True
            banned_sellers = config.raw.setdefault("global_banned_sellers", [])
            banned_sellers_norm = {_normalize(s) for s in banned_sellers}
            for seller in sorted(KNOWN_BAD_SELLERS):
                if _normalize(seller) not in banned_sellers_norm:
                    banned_sellers.append(seller)
                    banned_sellers_norm.add(_normalize(seller))
                    modified = True

            for s in searches:
                intent = _search_intent(s)
                if intent:
                    expected_query = intent.get("query")
                    if expected_query and s.get("query") != expected_query:
                        s["query"] = expected_query
                        modified = True
                    expected_display = intent.get("display_name")
                    if expected_display and s.get("display_name") != expected_display:
                        s["display_name"] = expected_display
                        modified = True
                    expected_category = intent.get("category")
                    filters = s.setdefault("filters", {})
                    if expected_category and filters.get("category") != expected_category:
                        filters["category"] = expected_category
                        modified = True
                q_norm = _normalize(s.get("query", ""))
                if re.search(r"\biphone\s*(?:15|16)\s*pro\s*max\b", q_norm):
                    filters = s.setdefault("filters", {})
                    if filters.get("location") != "de":
                        filters["location"] = "de"
                        modified = True

            # 2. Existing and new filters/excludes migration for redmagic/nubia
            accessory_excludes = [
                "hülle", "hüllen", "case", "cover", "schutzfolie", "panzerglas",
                "folie", "folien", "charger", "ladegerät", "kabel", "tasche",
                "schutzhülle", "film", "glass", "glas", "cable", "cables",
                "netzteil", "netzteile", "panzerfolie", "displayfolie", "glasfolie",
                "mats", "ibwind", "skin", "sticker", "adapter", "dock"
            ]
            for s in searches:
                q_lower = s.get("query", "").lower()
                if any(w in q_lower for w in ("redmagic", "red magic", "nubia")):
                    filters = s.setdefault("filters", {})
                    if filters.get("category") != "all":
                        filters["category"] = "all"
                        modified = True




            # 3. Specific excludes for base Redmagic 11 and Nubia Z80 Ultra
            redmagic_excludes = ["11s", "11 s", "11spro", "11s pro", "11 s pro"]
            for s_id in ("redmagic_11_pro_buy", "redmagic_11_pro_auc"):
                if s_id in by_id:
                    excludes = by_id[s_id].setdefault("exclude_words", [])
                    for w in redmagic_excludes:
                        if w not in excludes:
                            excludes.append(w)
                            modified = True

            nubia_excludes = ["leading", "leading version", "leading-version"]
            for s_id in ("nubia_z80_ultra_buy", "nubia_z80_ultra_auc"):
                if s_id in by_id:
                    excludes = by_id[s_id].setdefault("exclude_words", [])
                    for w in nubia_excludes:
                        if w not in excludes:
                            excludes.append(w)
                            modified = True

            for s_id in ("nubia_z80_ultra_leading_buy", "nubia_z80_ultra_leading_auc"):
                if s_id in by_id and by_id[s_id].get("display_name") != "Nubia Z80 LV":
                    by_id[s_id]["display_name"] = "Nubia Z80 LV"
                    modified = True

            for s_id in ("nubia_z70_ultra_buy", "nubia_z70_ultra_auc"):
                if s_id in by_id:
                    filters = by_id[s_id].setdefault("filters", {})
                    if filters.get("limit_price") != 325:
                        filters["limit_price"] = 325
                        modified = True
                    if filters.get("max_price") != 2500:
                        filters["max_price"] = 2500
                        modified = True

            ps5_safe_bundle_words = {
                "laufwerk", "drive", "stand", "stÃ¤nder", "ständer",
                "ovp", "verpackung", "karton",
            }
            for s_id in ("ps5_pro_buy", "ps5_pro_auc"):
                if s_id in by_id:
                    search = by_id[s_id]
                    if search.get("display_name") != "PlayStation 5 Pro":
                        search["display_name"] = "PlayStation 5 Pro"
                        modified = True
                    if search.get("query") != "(playstation 5 pro, ps5 pro)":
                        search["query"] = "(playstation 5 pro, ps5 pro)"
                        modified = True
                    filters = search.setdefault("filters", {})
                    if filters.get("limit_price") != 750:
                        filters["limit_price"] = 750
                        modified = True
                    if filters.get("max_price") != 2500:
                        filters["max_price"] = 2500
                        modified = True
                    excludes = search.setdefault("exclude_words", [])
                    cleaned = [w for w in excludes if _normalize(w) not in ps5_safe_bundle_words]
                    if cleaned != excludes:
                        search["exclude_words"] = cleaned
                        modified = True

            # Ensure Samsung Odyssey OLED G6 500Hz searches exist
            def ensure_odyssey_g6_search(new_id, listing_type, min_price):
                nonlocal modified
                if new_id in by_id:
                    search = by_id[new_id]
                else:
                    search = {
                        "id": new_id,
                        "query": "samsung odyssey oled g6 500hz",
                        "display_name": "Samsung Odyssey OLED G6 500Hz",
                        "filters": {},
                        "exclude_words": [],
                        "include_words": [],
                        "exclude_sellers": [],
                        "notify": True,
                        "enabled": True,
                    }
                    searches.append(search)
                    by_id[new_id] = search
                    modified = True
                # Prefer clean query (parenthetical OR groups break eBay HTML search).
                if search.get("query") in (
                    "samsung odyssey oled g6 500hz (G60SF, LS27FG602)",
                    "samsung odyssey oled g6 500hz",
                ) or "odyssey" in _normalize(search.get("query") or "") and "g6" in _normalize(
                    search.get("query") or ""
                ):
                    if search.get("query") != "samsung odyssey oled g6 500hz":
                        search["query"] = "samsung odyssey oled g6 500hz"
                        modified = True
                if search.get("display_name") != "Samsung Odyssey OLED G6 500Hz":
                    search["display_name"] = "Samsung Odyssey OLED G6 500Hz"
                    modified = True
                filters = search.setdefault("filters", {})
                expected = {
                    "min_price": min_price,
                    "limit_price": 400,
                    "max_price": 2500,
                    "condition": "any",
                    "listing_type": listing_type,
                    "seller_type": "any",
                    "location": "worldwide",
                    "category": "monitors",
                }
                for key, value in expected.items():
                    if filters.get(key) != value:
                        filters[key] = value
                        modified = True

            ensure_odyssey_g6_search("samsung_odyssey_oled_g6_500hz_buy", "buy_now_offer", None)
            ensure_odyssey_g6_search("samsung_odyssey_oled_g6_500hz_auc", "auction", None)

            # Clean LG UltraGear query — parentheses OR-groups zero eBay HTML results.
            for s in searches:
                qn = _normalize(s.get("query") or "")
                if "ultragear" in qn or "27gx790" in qn or "32gs95" in qn:
                    if s.get("query") != "lg ultragear oled 480hz":
                        s["query"] = "lg ultragear oled 480hz"
                        if not s.get("display_name"):
                            s["display_name"] = "LG UltraGear OLED"
                        modified = True
                    filters = s.setdefault("filters", {})
                    if filters.get("category") != "monitors":
                        filters["category"] = "monitors"
                        modified = True

            # Second Superlight 2 row (limit 65) was empty at end of long stats runs
            # while the std row found stock — keep one enabled pair to avoid tail empty.
            for s in searches:
                sid = s.get("id") or ""
                if sid.startswith("logitech_superlight_2_c_"):
                    if s.get("enabled", True):
                        s["enabled"] = False
                        modified = True

            def ensure_z70s_search(source_id, new_id, listing_type, min_price):
                nonlocal modified
                if new_id in by_id:
                    search = by_id[new_id]
                else:
                    template = copy.deepcopy(by_id.get(source_id) or {})
                    if not template:
                        return
                    template["id"] = new_id
                    template["query"] = "Nubia Z70S Ultra"
                    searches.append(template)
                    by_id[new_id] = template
                    search = template
                    modified = True
                if search.get("query") != "Nubia Z70S Ultra":
                    search["query"] = "Nubia Z70S Ultra"
                    modified = True
                filters = search.setdefault("filters", {})
                expected = {
                    "min_price": min_price,
                    "limit_price": 325,
                    "max_price": 2500,
                    "condition": "any",
                    "listing_type": listing_type,
                    "seller_type": "any",
                    "location": "worldwide",
                    "category": "all",
                }
                for key, value in expected.items():
                    if filters.get(key) != value:
                        filters[key] = value
                        modified = True

            ensure_z70s_search("nubia_z70_ultra_buy", "nubia_z70s_ultra_buy", "buy_now_offer", 50)
            ensure_z70s_search("nubia_z70_ultra_auc", "nubia_z70s_ultra_auc", "auction", None)

            by_id = {s["id"]: s for s in searches}
            new_searches = []
            for s_id in id_order:
                if s_id in by_id:
                    new_searches.append(by_id[s_id])
            for s in searches:
                if s["id"] not in id_order:
                    new_searches.append(s)
            if [s["id"] for s in searches] != [s["id"] for s in new_searches]:
                searches[:] = new_searches
                modified = True

            # 4. iPhone exclude_words are NOT programmatically overridden here.
            # The min_price floor of 50 EUR and the PHONE_HARD_ACCESSORY_WORDS
            # filter in _is_category_blocked_title already handle accessory spam.
            # Adding words like "kabel", "display", "glass" etc. was blocking
            # real phone listings (e.g. "iPhone 16 Pro Max mit Ladekabel").

            if modified:
                config.save()
                logger.info("Programmatically migrated searches configuration (reordering, excludes, price limits)")
        if not searches:
            logger.info("No searches configured")
            return

        test_summary_mode = _is_statistics_mode(config)

        if test_summary_mode:
            is_github = os.environ.get("GITHUB_ACTIONS") == "true"
            source_str = "GitHub Автомониторинг" if is_github else "Локальный"
            logger.info(f"🔍 Statistics/Diagnostic mode active ({source_str})...")
            report_entries = []  # list of (sort_key, block_text) for alphabetical ordering
            blocked_searches = []
            processed_base_ids = set()
            # Post-filter auction refills cost one extra SERP each; the report has
            # a 45 min budget, so cap them and say so in the log when the cap hits.
            auction_refills_done = 0

            for search in searches:
                if not search.get("enabled", True):
                    continue
                s_id = search.get("id", "")
                base_id = s_id
                if base_id.endswith("_buy"):
                    base_id = base_id[:-4]
                elif base_id.endswith("_auc"):
                    base_id = base_id[:-4]

                if base_id in processed_base_ids:
                    continue
                processed_base_ids.add(base_id)

                orig_max_price = search.get("filters", {}).get("limit_price") or search.get("filters", {}).get("max_price")

                # Find matching searches in config to get correct min_price for BIN and Auctions
                bin_search_cfg = None
                auc_search_cfg = None
                for s in searches:
                    s_id_inner = s.get("id", "")
                    s_base_id = s_id_inner
                    if s_base_id.endswith("_buy"):
                        s_base_id = s_base_id[:-4]
                    elif s_base_id.endswith("_auc"):
                        s_base_id = s_base_id[:-4]
                    if s_base_id == base_id:
                        lt = s.get("filters", {}).get("listing_type", "")
                        if lt in ("buy_now_offer", "buy_now") or s_id_inner.endswith("_buy"):
                            bin_search_cfg = s
                        elif lt == "auction" or s_id_inner.endswith("_auc"):
                            auc_search_cfg = s

                bin_min_price = bin_search_cfg.get("filters", {}).get("min_price") if bin_search_cfg else None
                auc_min_price = auc_search_cfg.get("filters", {}).get("min_price") if auc_search_cfg else None

                # ONE primary HTML fetch (listing_type=all) → client-split into
                # Sofort / Sofort+ / Auktion / Auktion+. Extra BIN or Auction hit
                # only when that side is missing from the mixed page.
                # Halves eBay traffic vs always doing BIN+Auction (and kills the
                # "second hit always blocked" mid-report pattern).
                floor = None
                for cand in (bin_min_price, auc_min_price):
                    if cand is None:
                        continue
                    try:
                        floor = float(cand) if floor is None else max(floor, float(cand))
                    except (TypeError, ValueError):
                        pass
                mixed_search = _statistics_search_variant(
                    search, "buy_now_offer", floor, False
                )
                mixed_search.setdefault("filters", {})["listing_type"] = "all"
                mixed_search["filters"]["best_offer"] = False
                mixed_search["filters"].pop("_stats_bucket_filter", None)
                # Wider page so mixed BIN+Auction both appear under price_asc.
                if _on_github_actions():
                    mixed_search["filters"]["_ipg"] = max(
                        int(mixed_search["filters"].get("_ipg") or 0), 60
                    )
                else:
                    mixed_search["filters"]["_ipg"] = max(
                        int(mixed_search["filters"].get("_ipg") or 0), 120
                    )

                result_groups = []
                fetch_errors = []
                did_auction_fill = False
                side_err = {"bin": None, "auc": None}
                side_ok = {"bin": False, "auc": False}
                # True when a fetch returned a clean page with 0 items (not transport fail).
                side_genuine_empty = {"bin": False, "auc": False}

                async def _stats_one_fetch(label, stats_search):
                    stats_search = copy.deepcopy(stats_search)
                    stats_search.setdefault("filters", {})["best_offer"] = False
                    stats_search["filters"].pop("_stats_bucket_filter", None)
                    # fetch_ebay_ex already does HTML + PW + API last resort.
                    # Do NOT call Browse API again here — second 429 on empty models
                    # (Z80 LV) opened the circuit and poisoned the rest of the report.
                    bucket_results, bucket_err = await asyncio.to_thread(
                        fetch_ebay_ex, stats_search, force=True
                    )
                    bucket_results = _tag_items_for_search(bucket_results or [], stats_search)
                    return bucket_results or [], bucket_err

                def _mark_sides_from_items(items):
                    has_bin = any(it.get("buy_now") for it in items)
                    has_auc = any(it.get("auction") for it in items)
                    if has_bin:
                        side_ok["bin"] = True
                        side_err["bin"] = None
                    if has_auc:
                        side_ok["auc"] = True
                        side_err["auc"] = None
                    return has_bin, has_auc

                def _note_side_outcome(side, items, err):
                    if items:
                        side_ok[side] = True
                        side_err[side] = None
                        side_genuine_empty[side] = False
                    elif err is None:
                        # Clean empty page — real "no stock" for this listing type.
                        side_genuine_empty[side] = True
                        side_err[side] = None
                    else:
                        side_err[side] = err
                        if err:
                            fetch_errors.append(err)

                async def _auction_fill_hard():
                    """Auction fill: curl/m.ebay first, then PW multi-sort.

                    Returns (items, err). err is None on genuine empty.
                    GH logs showed m.ebay often works for mixed pages while PW
                    crashes on auction SERP — so HTML chain first, Chromium second.
                    """
                    base = _statistics_search_variant(
                        search, "auction", auc_min_price, False
                    )
                    base.setdefault("filters", {})["best_offer"] = False
                    base["filters"].pop("_stats_bucket_filter", None)
                    base["filters"]["category"] = "all"
                    base["filters"].pop("sort_code", None)
                    if EBAY_SOURCE != "html" and _ebay_api_configured():
                        return await _stats_one_fetch("Auction API", base)
                    q = base.get("query") or search.get("query") or ""
                    last_err = None
                    saw_clean_empty = False
                    sort_variants = ("price_asc", "newest")

                    # 1) HTML chain (m.ebay first on GH) — cheaper and more stable
                    for sort_name in sort_variants:
                        trial = copy.deepcopy(base)
                        trial["filters"]["sort"] = sort_name
                        items, err = await _stats_one_fetch(
                            f"Auction fill/{sort_name}", trial
                        )
                        if items:
                            auc_only = [it for it in items if it.get("auction")] or items
                            logger.info(
                                "  %s: auction HTML/%s %d items",
                                search["query"], sort_name, len(auc_only),
                            )
                            return auc_only, None
                        if err is None:
                            saw_clean_empty = True
                            logger.info(
                                "  %s: auction HTML/%s clean empty",
                                search["query"], sort_name,
                            )
                            # try other sort once (price_asc vs newest differ)
                            continue
                        last_err = err
                    if saw_clean_empty and last_err in (None, "blocked", "network", "parse"):
                        return [], None

                    # 2) Playwright recovery when HTML soft-failed
                    if _on_github_actions():
                        for sort_name in sort_variants:
                            trial = copy.deepcopy(base)
                            trial["filters"]["sort"] = sort_name
                            for sub in ("m", "www"):
                                pw_url = _build_url_with_host("ebay.de", trial, sub=sub)
                                pw_items, pw_err = await asyncio.to_thread(
                                    _do_fetch_playwright, pw_url, q
                                )
                                pw_items = _tag_items_for_search(pw_items or [], trial)
                                if pw_items:
                                    auc_only = [
                                        it for it in pw_items if it.get("auction")
                                    ] or pw_items
                                    logger.info(
                                        "  %s: auction PW-%s/%s %d items",
                                        search["query"], sub, sort_name, len(auc_only),
                                    )
                                    return auc_only, None
                                if pw_err is None:
                                    saw_clean_empty = True
                                    logger.info(
                                        "  %s: auction PW-%s/%s clean empty",
                                        search["query"], sub, sort_name,
                                    )
                                    break
                                if pw_err == "no_playwright":
                                    last_err = pw_err
                                    break
                                last_err = pw_err
                                await asyncio.sleep(0.6)
                            if last_err == "no_playwright":
                                break
                        if saw_clean_empty and last_err in (
                            None, "blocked", "network", "parse",
                        ):
                            return [], None

                    # HTML/PW soft-failed but BIN often works — Browse API can still
                    # return auction lots (ULT / Pixel5 / G6) when Chromium is blocked.
                    if (
                        last_err
                        and last_err not in ("no_playwright",)
                        and _ebay_api_configured()
                        and not _ebay_api_circuit_open
                    ):
                        try:
                            api_items, api_err = await asyncio.to_thread(
                                fetch_ebay_api_ex, base, True
                            )
                        except Exception as e:
                            logger.warning(
                                "  %s: auction API fill crashed: %s",
                                search.get("query"), e,
                            )
                            api_items, api_err = [], last_err
                        if api_items:
                            tagged = _tag_items_for_search(api_items, base)
                            auc_only = [
                                it for it in tagged if it.get("auction")
                            ] or tagged
                            logger.info(
                                "  %s: auction API fill %d items",
                                search.get("query"), len(auc_only),
                            )
                            return auc_only, None
                        # No clean-empty from an API 0 here: the HTML/PW chain
                        # already failed on transport and buyingOptions:{AUCTION}
                        # is too thin to prove an empty auction market. Keeping
                        # last_err makes the bucket «сбой загрузки», not a false
                        # «Не найдено» (11S / LG / G6 / 4080 / Superlight pure).
                        if api_err is None:
                            logger.info(
                                "  %s: auction API fill 0 items after %s — keeping %s",
                                search.get("query"), last_err, last_err,
                            )
                        # Don't open circuit here — 429 on empty auction is common.
                        last_err = api_err or last_err
                    return [], last_err

                mixed_items, mixed_err = await _stats_one_fetch("mixed stats", mixed_search)
                if mixed_items:
                    result_groups.append(mixed_items)
                    has_bin, has_auc = _mark_sides_from_items(mixed_items)
                    logger.info(
                        "  %s: mixed page %d items (bin=%s auc=%s)",
                        search["query"], len(mixed_items), has_bin, has_auc,
                    )
                    # Fill missing side with one targeted fetch only.
                    if not has_bin:
                        if _on_github_actions():
                            await asyncio.sleep(1.5)
                        bin_search = _statistics_search_variant(
                            search, "buy_now_offer", bin_min_price, False
                        )
                        bin_items, bin_err = await _stats_one_fetch("BIN fill", bin_search)
                        if bin_items:
                            result_groups.append(bin_items)
                        _note_side_outcome("bin", bin_items, bin_err)
                    if not has_auc:
                        if _on_github_actions():
                            await asyncio.sleep(1.5)
                        auc_items, auc_err = await _auction_fill_hard()
                        did_auction_fill = True
                        if auc_items:
                            result_groups.append(auc_items)
                        _note_side_outcome("auc", auc_items, auc_err)
                else:
                    # Mixed page dead — fall back to separate BIN + Auction once each.
                    logger.warning(
                        "  %s: mixed page failed (%s) — BIN then Auction fallback",
                        search["query"], mixed_err,
                    )
                    if mixed_err is None:
                        # Clean empty mixed page — both sides may be empty stock.
                        side_genuine_empty["bin"] = True
                        side_genuine_empty["auc"] = True
                    elif mixed_err:
                        fetch_errors.append(mixed_err)
                    for side, label, lt, mprice in (
                        ("bin", "BIN fallback", "buy_now_offer", bin_min_price),
                        ("auc", "Auction fallback", "auction", auc_min_price),
                    ):
                        if _on_github_actions():
                            await asyncio.sleep(2.0)
                            _clear_gh_fetch_pressure(had_results=False)
                        if side == "auc":
                            side_items, side_e = await _auction_fill_hard()
                            did_auction_fill = True
                        else:
                            side_search = _statistics_search_variant(search, lt, mprice, False)
                            side_items, side_e = await _stats_one_fetch(label, side_search)
                        if side_items:
                            result_groups.append(side_items)
                        _note_side_outcome(side, side_items, side_e)

                results = _merge_items_by_id(*result_groups)
                # Reconcile sides from final merge (hybrids fill both).
                if results:
                    _mark_sides_from_items(results)
                fetch_err = fetch_errors[0] if fetch_errors else None
                if fetch_err and not results:
                    blocked_searches.append(search)
                if _on_github_actions():
                    await asyncio.sleep(1.5)
                    _clear_gh_fetch_pressure(had_results=bool(results))

                # Filter results with skip_seen=True (to show already notified items).
                # BIN/Auction/BO split happens after this merge (see bin_no_bo / auc_bo).
                stats_filter_search = _statistics_filter_search(search)
                filtered = filter_results(results, stats_filter_search, config, skip_seen=True, is_statistics=True)

                # Group filtered items into Buy It Now and Auction, handling hybrid listings
                def _split_buckets(rows):
                    bin_no_bo = []
                    bin_bo = []
                    auc_no_bo = []
                    auc_bo = []
                    for item in rows:
                        if item.get("buy_now"):
                            bin_item = copy.deepcopy(item)
                            bin_item["auction"] = False
                            bin_item["price"] = item.get("bin_price") or item["price"]
                            bin_item["total_price"] = item.get("bin_total_price") or item["total_price"]
                            bin_item["import_charges"] = item.get("bin_import_charges") or item.get("import_charges")
                            if not item.get("best_offer"):
                                bin_no_bo.append(bin_item)
                            else:
                                bin_bo.append(bin_item)
                        if item.get("auction"):
                            auc_item = copy.deepcopy(item)
                            auc_item["buy_now"] = False
                            auc_item["price"] = item.get("auc_price") or item["price"]
                            auc_item["total_price"] = item.get("auc_total_price") or item["total_price"]
                            auc_item["import_charges"] = item.get("auc_import_charges") or item.get("import_charges")
                            if not item.get("best_offer"):
                                auc_no_bo.append(auc_item)
                            else:
                                if item.get("bids_count") in (0, None):
                                    auc_bo.append(auc_item)
                                minutes = _parse_time_left_to_minutes(item.get("time_left") or "")
                                if minutes is not None and minutes <= 1440:
                                    auc_no_bo.append(auc_item)
                    return bin_no_bo, bin_bo, auc_no_bo, auc_bo

                bin_no_bo, bin_bo, auc_no_bo, auc_bo = _split_buckets(filtered)

                # An auction item on the mixed page proves the side *loaded*, not
                # that we saw the auction market: that page is one price-ascending
                # list shared with Sofort, so cheap BIN cards push live lots off it.
                # LG UltraGear (20:31 UTC) had auc=True on the mixed page, both
                # auction buckets empty after filtering, and a 450€ lot sitting on
                # the auction-only SERP that passes the very same filters. One
                # dedicated fetch, once per product, capped per report.
                if (
                    not auc_no_bo
                    and not auc_bo
                    and not did_auction_fill
                    and (bin_no_bo or bin_bo)
                ):
                    if auction_refills_done >= _MAX_AUCTION_REFILLS:
                        logger.info(
                            "  %s: auction buckets empty after filter — refill skipped "
                            "(report cap %d reached)",
                            search["query"], _MAX_AUCTION_REFILLS,
                        )
                    else:
                        auction_refills_done += 1
                        logger.info(
                            "  %s: auction buckets empty after filter — dedicated auction fetch (%d/%d)",
                            search["query"], auction_refills_done, _MAX_AUCTION_REFILLS,
                        )
                        if _on_github_actions():
                            await asyncio.sleep(1.5)
                        refill_items, refill_err = await _auction_fill_hard()
                        did_auction_fill = True
                        if refill_items:
                            result_groups.append(refill_items)
                            results = _merge_items_by_id(*result_groups)
                            _mark_sides_from_items(results)
                            filtered = filter_results(
                                results, stats_filter_search, config,
                                skip_seen=True, is_statistics=True,
                            )
                            bin_no_bo, bin_bo, auc_no_bo, auc_bo = _split_buckets(filtered)
                            logger.info(
                                "  %s: auction refill %d raw items -> buckets %d/%d",
                                search["query"], len(refill_items),
                                len(auc_no_bo), len(auc_bo),
                            )
                        else:
                            _note_side_outcome("auc", refill_items, refill_err)

                # After filter: if a side still has raw items but filter wiped them,
                # empty buckets are real empty — clear transport errors for that side.
                raw_has_bin = any(it.get("buy_now") for it in results)
                raw_has_auc = any(it.get("auction") for it in results)
                if raw_has_bin:
                    side_ok["bin"] = True
                    side_err["bin"] = None
                if raw_has_auc:
                    side_ok["auc"] = True
                    side_err["auc"] = None
                # Sibling side recovered prices → never paint full eBay outage on the
                # missing side. Soft-fail alone is NOT proof of empty stock (live
                # auctions for ULT/Pixel5/G6 exist while PW soft-blocks) — only a
                # clean empty SERP (side_genuine_empty) is «Не найдено».
                if results:
                    soft_transport = (
                        "blocked", "cooldown", "network", "parse",
                        "rate_limit", "api_rate_limit",
                    )
                    if not raw_has_auc and side_err.get("auc") in soft_transport:
                        if side_genuine_empty.get("auc"):
                            side_err["auc"] = None
                        else:
                            side_err["auc"] = "side_fetch_failed"
                    if not raw_has_bin and side_err.get("bin") in soft_transport:
                        if side_genuine_empty.get("bin"):
                            side_err["bin"] = None
                        else:
                            side_err["bin"] = "side_fetch_failed"

                total_price_key = lambda x: float(x.get("total_price") or 0)
                # Drop bait floors again after bucket split (defense in depth).
                bin_no_bo = [x for x in bin_no_bo if not _is_implausibly_cheap_device(x, search)]
                bin_bo = [x for x in bin_bo if not _is_implausibly_cheap_device(x, search)]
                auc_no_bo = [x for x in auc_no_bo if not _is_implausibly_cheap_device(x, search)]
                auc_bo = [x for x in auc_bo if not _is_implausibly_cheap_device(x, search)]
                # Same validation as normal alerts — no multi-variation exceptions.
                stats_search_cfg = copy.deepcopy(search)
                # stats_soft_fallback: if details API/description boilerplate rejects
                # every SERP hit, still surface the cheapest card that already
                # passed filter_results (title/intent/price floor). Full details
                # rules remain for normal notifications.
                cheapest_bin_no_bo = await _select_cheapest_valid_candidate(
                    sorted(bin_no_bo, key=total_price_key), stats_search_cfg, stats_soft_fallback=True
                )
                cheapest_bin_bo = await _select_cheapest_valid_candidate(
                    sorted(bin_bo, key=total_price_key), stats_search_cfg, stats_soft_fallback=True
                )
                cheapest_auc_no_bo = await _select_cheapest_valid_candidate(
                    sorted(auc_no_bo, key=total_price_key), stats_search_cfg, stats_soft_fallback=True
                )
                cheapest_auc_bo = await _select_cheapest_valid_candidate(
                    sorted(auc_bo, key=total_price_key), stats_search_cfg, stats_soft_fallback=True
                )

                def get_verdict_for_item(item, bucket=None):
                    """🟢 = default mode would alert; 🟡 = wait / uncertain Auktion+; 🟣 = over limit."""
                    if not item:
                        return "❌ Не найдено"
                    if item.get("_details_status") != "verified":
                        return "🟡 описание недоступно (eBay API)"
                    if _is_implausibly_cheap_device(item, search):
                        return "❌ дешевле пола"
                    eligible, reason = _notify_eligibility(item, search)
                    clock = _auction_meta(item)
                    tail = f" · {clock}" if clock else ""
                    bucket_s = (bucket or "").strip()
                    offer_only = item.get("auction") and item.get("best_offer") and not item.get("buy_now")
                    if reason == "too_cheap":
                        return "❌ дешевле пола"
                    if reason == "over_limit":
                        return "🟣 Дорого"
                    if bucket_s.startswith("Auktion") and not bucket_s.startswith("Auktion+") and offer_only:
                        return f"🟡 Auktion+{tail}"
                    if reason == "wait_24h":
                        return f"🟡{tail}" if tail else "🟡 аукцион"
                    if eligible:
                        if offer_only:
                            return f"🟢 Auktion+{tail}"
                        if item.get("auction") and tail:
                            return f"🟢 Подходит{tail}"
                        return "🟢 Подходит"
                    return "🟣 Дорого"

                def get_verdict_str(price_val):
                    # Legacy helper for price-only checks; prefer get_verdict_for_item.
                    if orig_max_price and price_val is not None and price_val > orig_max_price:
                        return "🟣 Дорого"
                    return "🟢 Подходит"

                def get_short_url(item_id):
                    return f"https://www.ebay.de/itm/{item_id}"

                def get_category_emoji(cat_name):
                    cat_name = (cat_name or "").strip().lower()
                    mapping = {
                        "phones": "📱",
                        "phone_parts": "⚙️",
                        "phone_accessories": "🔌",
                        "tablets": "📟",
                        "laptops": "💻",
                        "computers": "🖥️",
                        "monitors": "🖥️",
                        "mice": "🖱️",
                        "headphones": "🎧",
                        "vr": "🥽",
                        "vr_headsets": "🥽",
                        "cameras": "📷",
                        "video_games": "🎮",
                        "consoles": "🎮",
                        "smart_watches": "⌚",
                        "electronics": "🔌",
                    }
                    return mapping.get(cat_name, "📦")

                def display_price(item):
                    if not item:
                        return None
                    return round(float(item.get("total_price") or 0), 2)

                p1_val = display_price(cheapest_bin_no_bo)
                p2_val = display_price(cheapest_bin_bo)
                p3_val = display_price(cheapest_auc_no_bo)
                p4_val = display_price(cheapest_auc_bo)

                p1_base = p1_val
                p2_base = p2_val
                p3_base = p3_val
                p4_base = p4_val

                p1 = f"{p1_base:.0f}€" if p1_base else None
                p2 = f"{p2_base:.0f}€" if p2_base else None
                p3 = f"{p3_base:.0f}€" if p3_base else None
                p4 = f"{p4_base:.0f}€" if p4_base else None

                max_len = 7
                dashes = "---"

                # Prefix labels and emojis (one emoji and one space outside <code>)
                lbl_bin_emoji = "🛒"
                lbl_bin_bo_emoji = "🤝"
                lbl_auc_emoji = "🔨"
                lbl_auc_bo_emoji = "⏳"

                label_width = 8
                lbl_bin = "Sofort".ljust(label_width)
                lbl_bin_bo = "Sofort+".ljust(label_width)
                lbl_auc = "Auktion".ljust(label_width)
                lbl_auc_bo = "Auktion+".ljust(label_width)

                def _tg_link_spaces(*vals):
                    return 11

                bin_link_spaces = _tg_link_spaces()
                auc_link_spaces = _tg_link_spaces()

                def _shorten_time_left(t_str):
                    if not t_str:
                        return ""
                    import re
                    t = t_str.strip()
                    if t.lower().startswith("noch "):
                        t = t[5:]
                    t = re.sub(r"\s*\(.*?\)", "", t)
                    return t.strip()

                def is_under_one_hour(t_str):
                    if not t_str:
                        return False
                    t_lower = t_str.lower()
                    return not any(w in t_lower for w in ("tag", "std", "d", "h", "day", "hour", "день", "дня", "дней", "дн", "д", "ч"))

                def _empty_bucket_label(is_auction=False):
                    side = "auc" if is_auction else "bin"
                    # A successful sibling cannot prove that this basket was fetched.
                    error = side_err.get(side)
                    if not side_genuine_empty.get(side) and not side_ok.get(side):
                        error = error or fetch_err
                    return _statistics_empty_bucket_label(
                        side_ok=side_ok.get(side, False),
                        genuine_empty=side_genuine_empty.get(side, False),
                        error=error,
                    )

                def make_aligned_row(emoji, label, item, total_price_val, total_price_str, is_auction=False, link_spaces_len=9):
                    row_lines = []
                    if item:
                        url = get_short_url(item["item_id"])
                        raw_verdict = get_verdict_for_item(item, bucket=label)

                        if raw_verdict.startswith("🟢"):
                            v_emoji, v_text = "🟢", raw_verdict[2:].strip() or "Подходит"
                        elif raw_verdict.startswith("🟡"):
                            v_emoji, v_text = "🟡", raw_verdict[2:].strip() or "аукцион"
                        elif raw_verdict.startswith("🟣"):
                            v_emoji, v_text = "🟣", "Дорого"
                        elif raw_verdict.startswith("❌"):
                            v_emoji, v_text = "❌", raw_verdict[2:].strip() or "отсев"
                        else:
                            v_emoji, v_text = "🟣", "Дорого"

                        verdict_info = f"{v_emoji} {v_text}"

                        num_digits = len(str(int(total_price_val))) if total_price_val else 0
                        if num_digits >= 3:
                            padded_price = total_price_str.rjust(max_len + 1)
                            after_price_spaces = " "
                        else:
                            padded_price = total_price_str.rjust(max_len)
                            after_price_spaces = "  "

                        time_line = ""
                        if is_auction:
                            t_left = item.get("time_left", "")
                            if t_left:
                                time_emoji = "🟢" if is_under_one_hour(t_left) else "⚠️"
                                time_line = f"{time_emoji} {_shorten_time_left(t_left)}"

                        row_lines.append(f"{emoji} <code>{label}{padded_price}{after_price_spaces}│ </code>{verdict_info}")
                        if time_line:
                            row_lines.append(f"<code>{time_line}</code>")

                        spaces_str = " " * link_spaces_len
                        row_lines.append(f"🔗 <code>{spaces_str}</code><a href=\"{html.escape(url)}\"><b>*ТЫК*</b></a>")
                    else:
                        padded_dashes = dashes.rjust(max_len)
                        v_emoji, v_text = _empty_bucket_label(is_auction=is_auction)
                        verdict_info = f"{v_emoji} {v_text}"
                        row_lines.append(f"{emoji} <code>{label}{padded_dashes}  │ </code>{verdict_info}")
                    return row_lines

                # Build Sofortkauf block with blank lines in between
                bin_lines = []
                bin_lines.extend(make_aligned_row(lbl_bin_emoji, lbl_bin, cheapest_bin_no_bo, p1_val, p1, is_auction=False, link_spaces_len=bin_link_spaces))
                bin_lines.append("")
                bin_lines.extend(make_aligned_row(lbl_bin_bo_emoji, lbl_bin_bo, cheapest_bin_bo, p2_val, p2, is_auction=False, link_spaces_len=bin_link_spaces))

                # Build Auction block with blank lines in between
                auc_lines = []
                auc_lines.extend(make_aligned_row(lbl_auc_emoji, lbl_auc, cheapest_auc_no_bo, p3_val, p3, is_auction=True, link_spaces_len=auc_link_spaces))
                auc_lines.append("")
                auc_lines.extend(make_aligned_row(lbl_auc_bo_emoji, lbl_auc_bo, cheapest_auc_bo, p4_val, p4, is_auction=True, link_spaces_len=auc_link_spaces))

                # Build report block
                query_norm = _normalize(search.get("query", ""))
                category_name = search.get("filters", {}).get("category")
                effective_category = _effective_category(category_name, query_norm)
                min_price_val = None
                if bin_min_price is not None:
                    min_price_val = bin_min_price
                elif auc_min_price is not None:
                    min_price_val = auc_min_price
                if min_price_val is None and effective_category == "phones" and "pixel" not in query_norm:
                    min_price_val = 50

                limit_val = search.get("filters", {}).get("limit_price")
                max_price_val = search.get("filters", {}).get("max_price")

                limit_str_part = f"🎯 {limit_val:.0f}€" if limit_val is not None else ""
                max_str_part = f"⬆️ {max_price_val:.0f}€" if max_price_val is not None else "⬆️ без лимита"
                min_str_part = f"⬇️ {min_price_val:.0f}€" if min_price_val is not None else "⬇️ без лимита"

                parts = []
                if limit_str_part:
                    parts.append(limit_str_part)
                parts.append(max_str_part)
                parts.append(min_str_part)
                limit_str = " ".join(parts)

                query_esc = html.escape(search.get("display_name") or search.get("query", ""))
                loc = search.get("filters", {}).get("location")
                if loc == "de":
                    query_esc += " 🇩🇪"
                elif loc == "eu":
                    query_esc += " 🇪🇺"
                elif loc == "worldwide":
                    query_esc += " 🌍"

                cat_filter = search.get("filters", {}).get("category", "all")
                if cat_filter and cat_filter != "all":
                    query_esc += " ⚙️"
                else:
                    query_esc += " ♾️"

                cat_emoji = get_category_emoji(category_name)

                block_lines = [
                    f"{cat_emoji} <b>{query_esc}</b>",
                    "",
                    f"💸 Лимит: {limit_str}",
                    "",
                    "\n".join(bin_lines),
                    "",
                    "\n".join(auc_lines)
                ]

                sort_key = (search.get("display_name") or search.get("query", "")).strip().lower()
                report_entries.append((sort_key, "\n".join(block_lines)))
                logger.info(f"Generated statistics block for '{search.get('query')}':\n" + "\n".join(block_lines))

                if not once:
                    await asyncio.sleep(random.uniform(2, 5))

            # Sort report blocks alphabetically by product name so related items are grouped together
            report_entries.sort(key=lambda x: x[0])
            report_lines = [block for _, block in report_entries]

            # Split report_lines into chunks of at most 8 items to avoid Telegram's 100 HTML entities limit
            chunks = []
            chunk_size = 8

            is_github = os.environ.get("GITHUB_ACTIONS") == "true"
            footer_str = "📋 <b>Автомониторинг: Git 🤖</b>" if is_github else "📋 <b>Автомониторинг: Локальный 💻</b>"
            # Version = last logical code change, not run end time (see _get_stable_version_string).
            footer_str += f"\nℹ️ <i>Сервер: {_get_stable_version_string()}</i>\n📱 APK: {_apk_version_label()}\n🔎 Поиск: {_fetch_source_label()}"

            report_lines.append(footer_str)

            content_lines = report_lines[:-1]
            footer_line = report_lines[-1]
            chunks_data = [content_lines[i:i + chunk_size] for i in range(0, len(content_lines), chunk_size)]
            if chunks_data:
                chunks_data[-1].append(footer_line)
            else:
                chunks_data = [[footer_line]]

            for idx, chunk in enumerate(chunks_data, 1):
                chunk_text = "\n\n<code>───────────────────────────────</code>\n\n".join(chunk)
                if idx > 1:
                    chunk_text = f"<code>───────────────────────────────</code>\n\n" + chunk_text
                chunks.append(chunk_text)

            logger.info(f"📊 Отправляю diagnostic report в Telegram ({len(chunks)} частей)...")

            force_backup = len(blocked_searches) > 0
            for i, chunk_text in enumerate(chunks):
                sent = await safe_send_telegram(
                    bot,
                    TELEGRAM_CHAT_ID,
                    chunk_text,
                    keyboard=None,
                    parse_mode="HTML",
                    force_backup=force_backup
                )
                if sent:
                    logger.info("Diagnostic report part %d/%d sent to Telegram", i + 1, len(chunks))
                if not sent:
                    logger.error(f"Ошибка отправки части {i+1} диагностического отчета")
                await asyncio.sleep(1.0)

            clear_monitoring_state()
            return


        total_new = 0
        blocked_searches = []  # Searches that failed due to block/rate_limit/cooldown

        for search in searches:
            if not search.get("enabled", True):
                continue
            # Same eBay sort/page profile as statistics so alerts match green rows.
            # Always fetch/filter (feed + seen + stats). Telegram only if notify=true.
            fetch_search = _prepare_monitor_fetch_search(search)
            results, fetch_err = await asyncio.to_thread(fetch_ebay_ex, fetch_search)
            if fetch_err == "api_deferred":
                logger.debug("%s: waiting for next quota-aware refresh", search["query"])
                continue
            if fetch_err:
                if fetch_err in ("blocked", "rate_limit", "cooldown"):
                    blocked_searches.append(search)
                logger.warning("  %s: fetch error %s", search["query"], fetch_err)
                _runtime_errors.append(f"{search['id']}: {fetch_err}")
                continue
            # Flag listing types from the search we ran, exactly like statistics
            # does. eBay cards often omit "Gebot"/"Auktion", and an untagged lot
            # from an auction-only search counts as Sofort: it would be alerted
            # immediately instead of under the auction rules, and would never
            # reach the final-hour or 15-minute stages, which both require
            # auction and not buy_now.
            results = _tag_items_for_search(results, fetch_search)
            # A full page means the price sort truncated the market: fresh or
            # ending lots can be hiding behind it. A short page already IS the
            # whole market, and paying for two more fetches there would only
            # slow every pass down.
            page_size = int((fetch_search.get("filters") or {}).get("_ipg") or 0)
            market_truncated = bool(page_size) and len(results) >= page_size
            sweep = _auction_sweep_search(fetch_search)
            if sweep:
                sweep = _prepare_monitor_fetch_search(sweep)
                auction_results, auction_err = await asyncio.to_thread(fetch_ebay_ex, sweep)
                if auction_err:
                    logger.warning("  %s: auction sweep error %s", search["query"], auction_err)
                    if auction_err != "api_deferred":
                        _runtime_errors.append(f"{search['id']}: auction {auction_err}")
                else:
                    before = len(results)
                    auction_results = _tag_items_for_search(auction_results or [], sweep)
                    results = _merge_items_by_id(results, auction_results)
                    if len(results) > before:
                        logger.info("  %s: auction sweep added %d item(s)", search["query"], len(results) - before)

            async def _extra_sweep(label, sweep_search):
                """Merge one re-sorted page of the same query into results."""
                nonlocal results
                if not sweep_search:
                    return
                items, err = await asyncio.to_thread(fetch_ebay_ex, sweep_search)
                if err:
                    logger.warning("  %s: %s sweep error %s", search["query"], label, err)
                    if err != "api_deferred":
                        _runtime_errors.append(f"{search['id']}: {label} {err}")
                    return
                before = len(results)
                items = _tag_items_for_search(items or [], sweep_search)
                results = _merge_items_by_id(results, items)
                if len(results) > before:
                    logger.info(
                        "  %s: %s sweep added %d item(s)",
                        search["query"], label, len(results) - before,
                    )

            if market_truncated:
                # Newest first: catches a listing the price sort buried.
                await _extra_sweep("newly listed", _newly_listed_search(fetch_search))
                # Ending soonest: without it a lot in its last minutes can sit
                # deep on page 3 and the final-hour / 15-minute alerts never fire.
                await _extra_sweep("ending soon", _ending_soon_auction_search(fetch_search))

            if not results:
                logger.info("  %s: 0 results", search["query"])
                continue

            filtered = filter_results(results, search, config)

            sofort = [r for r in filtered if r["buy_now"]]
            preisvorschlag = [r for r in filtered if r["best_offer"]]
            auctions = [r for r in filtered if r["auction"]]

            sofort_prices = [r["total_price"] for r in sofort if not is_outlier(r["total_price"], search["id"])]
            pv_prices = [r["total_price"] for r in preisvorschlag if not is_outlier(r["total_price"], search["id"])]
            auction_prices = [r["total_price"] for r in auctions if not is_outlier(r["total_price"], search["id"])]
            record_snapshot(search["id"], sofort_prices, pv_prices, auction_prices, len(filtered))

            for r in filtered:
                if not is_outlier(r["total_price"], search["id"]):
                    record_seller_price(search["id"], r["seller_name"], r["total_price"], r["item_id"])

            stats_7d = get_stats_7d(search["id"])

            candidates = _notify_candidates_from_filtered(filtered)
            by_stage = {s: sum(1 for _, st in candidates if st == s) for s in NOTIFY_STAGES}
            logger.info(
                "  %s: %d results, %d candidates (%s)",
                search["query"], len(filtered), len(candidates),
                ", ".join(f"{s}={by_stage[s]}" for s in NOTIFY_STAGES if by_stage[s]) or "none",
            )

            # notify=false: still scan/record, only skip Telegram deal alerts.
            # (Earlier bug: continue at top skipped the whole search → TG silent forever.)
            if not search.get("notify", True):
                logger.info("  %s: skip Telegram sends (notify=false)", search.get("query"))
            else:
                for item, stage in sorted(candidates, key=lambda x: x[0]["total_price"]):
                    if await _process_notify_candidate(bot, item, search, stats_7d, stage):
                        total_new += 1
                    await asyncio.sleep(0.5)

            if not once:
                await asyncio.sleep(random.uniform(2, 5))

        # === API RETRY for blocked searches ===
        # If any searches were blocked by HTML scraping, retry them NOW via API
        # so we don't miss items (especially important for GitHub Actions where
        # the next run is 15 minutes away).
        if blocked_searches and _ebay_api_configured():
            logger.info("=== API retry for %d blocked search(es) ===", len(blocked_searches))
            for search in blocked_searches:
                fetch_search = _prepare_monitor_fetch_search(search)
                api_items, api_err = await asyncio.to_thread(fetch_ebay_api_ex, fetch_search)
                if api_err:
                    logger.warning("  %s: API retry failed: %s", search["query"], api_err)
                    continue
                if not api_items:
                    logger.info("  %s: API retry 0 results", search["query"])
                    continue

                filtered = filter_results(api_items, search, config)
                stats_7d = get_stats_7d(search["id"])
                candidates = _notify_candidates_from_filtered(filtered)
                logger.info(
                    "  %s: API retry %d results, %d candidates",
                    search["query"], len(filtered), len(candidates),
                )

                if not search.get("notify", True):
                    logger.info("  %s: API retry skip Telegram (notify=false)", search.get("query"))
                    continue
                for item, stage in sorted(candidates, key=lambda x: x[0]["total_price"]):
                    if await _process_notify_candidate(bot, item, search, stats_7d, stage):
                        total_new += 1
                    await asyncio.sleep(0.5)

        save_seen_ids()
        config.save()

        # After sending notifications, refresh the sticky menu at the bottom
        if total_new > 0 and not once:
            await _refresh_sticky_menu(bot)


async def process_pending_callbacks(bot):
    try:
        updates = await bot.get_updates(timeout=5)
        for update in updates:
            if update.callback_query:
                data = update.callback_query.data or ""
                if data.startswith("hide:"):
                    item_id = data[5:]
                    config.ban_item(item_id)
                    mark_seen_item(item_id)
                    try:
                        await update.callback_query.answer("❌ Объявление скрыто")
                        msg = update.callback_query.message
                        if msg:
                            await msg.edit_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    logger.info("Banned item: %s", item_id)
                elif data.startswith("ban:"):
                    seller = data[4:]
                    config.ban_seller_global(seller)
                    delete_seller_data(seller)
                    try:
                        await update.callback_query.answer(f"🚫 Продавец {seller} забанен")
                        msg = update.callback_query.message
                        if msg:
                            await msg.edit_reply_markup(reply_markup=None)
                    except Exception:
                        pass
                    logger.info("Banned seller: %s", seller)
        if updates:
            last_id = max(u.update_id for u in updates)
            await bot.get_updates(offset=last_id + 1, timeout=1)
    except Exception as e:
        logger.error("process_pending_callbacks error: %s", e)


def _validate_github_pat():
    if not GITHUB_TOKEN:
        return "❌ не задан"
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return f"✅ {data.get('login', '?')}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return "❌ СЛЕТЕЛ (401 Unauthorized)"
        return f"⚠️ HTTP {e.code}"
    except Exception as e:
        return f"⚠️ {e}"


def _humanize_age(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _validate_github_actions(repo):
    """Query latest workflow run status for the configured repo. Returns
    a short human-readable summary like '✅ success 2h ago' or '❌ failure 3m ago'."""
    if not repo or repo == "—":
        return "— нет репозитория"
    if not GITHUB_TOKEN:
        return "⚠️ нет GH Token"
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/actions/runs?per_page=1",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        runs = data.get("workflow_runs") or []
        if not runs:
            return "— нет запусков"
        run = runs[0]
        status = run.get("status") or "?"
        conclusion = run.get("conclusion")
        name = run.get("name") or "workflow"
        created = run.get("created_at") or run.get("run_started_at")
        from datetime import datetime, timezone
        age_str = ""
        if created:
            try:
                dt = datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                age_str = f" {_humanize_age(age)} ago"
            except Exception:
                pass
        if status in ("queued", "in_progress", "waiting", "requested"):
            return f"🔄 {status}{age_str} ({name})"
        emoji = {
            "success": "✅",
            "failure": "❌",
            "cancelled": "🚫",
            "skipped": "⏭️",
            "timed_out": "⏱️",
            "neutral": "➖",
            "action_required": "⚠️",
        }.get(conclusion, "⚠️")
        return f"{emoji} {conclusion or status}{age_str} ({name})"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return "❌ 401 — токен не имеет доступа"
        if e.code == 404:
            return "❌ 404 — репозиторий или Actions не найдены"
        return f"⚠️ HTTP {e.code}"
    except Exception as e:
        return f"⚠️ {e}"


def _validate_ebay_api():
    source = EBAY_SOURCE if EBAY_SOURCE in ("auto", "html", "api") else "auto"
    prefix = f"source={source}, market={EBAY_MARKETPLACE_ID}"
    if not _ebay_api_configured():
        return f"⚠️ {prefix}, keys not configured"
    token, err = _get_ebay_api_token()
    if err:
        return f"❌ {prefix}, {err}"
    return f"✅ {prefix}, token ok"


def _short_secret(value):
    if not value:
        return "❌ не задан"
    if len(value) <= 12:
        return "******"
    return f"{value[:6]}…{value[-4:]}"


def _normalize_github_repo(value):
    if not value:
        return "—"
    raw = value.strip().replace("\\", "/")
    if "github.com" in raw:
        tail = raw.split("github.com", 1)[1].lstrip("/:").split("?", 1)[0]
        parts = tail.split("/")
        if len(parts) >= 2:
            repo = f"{parts[0]}/{parts[1]}"
            return repo[:-4] if repo.endswith(".git") else repo
    raw = raw[:-4] if raw.endswith(".git") else raw
    return raw


def _get_git_remote_repo():
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={repo_dir}", "remote", "get-url", "origin"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if result.returncode != 0:
            return "⚠️ remote not found"
        return _normalize_github_repo(result.stdout.strip())
    except Exception as e:
        return f"⚠️ {e}"


def _validate_telegram_bot():
    if not TELEGRAM_BOT_TOKEN:
        return "❌ не задан", "—", "—"
    token_bot_id = TELEGRAM_BOT_TOKEN.split(":", 1)[0] if ":" in TELEGRAM_BOT_TOKEN else "?"
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe")
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        if not data.get("ok"):
            return "❌ getMe ok=false", token_bot_id, "—"
        bot_data = data.get("result", {})
        actual_id = str(bot_data.get("id", "—"))
        username = bot_data.get("username") or "?"
        match = "✅" if actual_id == token_bot_id else "⚠️"
        return f"{match} @{username} id={actual_id}", token_bot_id, actual_id
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return "❌ СЛЕТЕЛ/INVALID (401 Unauthorized)", token_bot_id, "—"
        return f"⚠️ HTTP {e.code}", token_bot_id, "—"
    except Exception as e:
        return f"⚠️ {e}", token_bot_id, "—"


def _count_search_words(field):
    return sum(len(s.get(field, [])) for s in config.get_searches())


def _log_startup_banner(mode):
    searches = config.get_searches()
    remote_repo = _get_git_remote_repo()
    env_repo = _normalize_github_repo(GITHUB_REPO) if GITHUB_REPO else "—"
    remote_ok = not remote_repo.startswith("⚠️") and remote_repo != "—"
    tg_status, token_bot_id, actual_bot_id = _validate_telegram_bot()
    settings = config.get_settings()

    # Validate all tokens belong to same account
    gh_pat_user = _validate_github_pat()
    gh_actions = _validate_github_actions(remote_repo if remote_ok else env_repo)
    ebay_status = _validate_ebay_api()

    logger.info("╔══════════════════════════════════════════════╗")
    logger.info("║              eBay Monitor Bot               ║")
    logger.info("╠══════════════════════════════════════════════╣")
    logger.info("  Mode:       %s", mode)
    logger.info("  Repo:       %s", remote_repo)
    logger.info("  GH Token:   %s", gh_pat_user)
    logger.info("  GH Actions: %s", gh_actions)
    logger.info("  eBay API:   %s", ebay_status)
    logger.info("  Telegram:   %s", tg_status)
    logger.info("  Chat ID:    %s", TELEGRAM_CHAT_ID or "❌ не задан")
    logger.info("╠══════════════════════════════════════════════╣")
    logger.info("  Searches:   %d (%d excl, %d incl words)",
                len(searches), _count_search_words("exclude_words"), _count_search_words("include_words"))
    logger.info("  Bans:       %d sellers, %d items",
                len(config.get_global_banned_sellers()), len(config.get_banned_item_ids()))
    logger.info("  Seen:       %d ids", len(seen_ids))
    logger.info("╚══════════════════════════════════════════════╝")


_runtime_errors = []
_runtime_html_fallback = False


def _publish_runtime(state, error=None):
    from mobile.runtime_status import publish
    quota_paused = browse_access.is_paused() is True
    html_only = quota_paused or EBAY_SOURCE == "html" or not _ebay_api_configured()
    publish(config.raw, _read_logic_version_timestamp(), state, error,
            data_source="html" if html_only else "api+html" if _runtime_html_fallback else "api",
            warning="Квота API закончилась: проверяю сайт eBay через HTML" if quota_paused else "Описание проверяется через сайт eBay" if _runtime_html_fallback and not html_only else None)


async def run_once():
    load_seen_ids()
    _runtime_errors.clear()
    _publish_runtime("running")
    _log_startup_banner("ONE-SHOT")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    try:
        await process_pending_callbacks(bot)
        await process_searches(bot, once=True)
        save_seen_ids()
    except Exception as error:
        _publish_runtime("error", type(error).__name__)
        raise
    _publish_runtime("error" if _runtime_errors else "ok", "; ".join(_runtime_errors) or None)
    logger.info("=== Done ===")

    # The workflow publishes one atomic checkpoint after this sweep.


async def run_continuous():
    from settings_handlers import register_settings_handlers

    load_seen_ids()
    _log_startup_banner("POLLING")

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    register_settings_handlers(app, config)

    job_queue = app.job_queue
    interval_val = 300
    if _is_statistics_mode(config) and os.environ.get("GITHUB_ACTIONS") != "true":
        interval_val = 60
    job_queue.run_repeating(
        scheduled_check,
        interval=interval_val,
        first=10,
        name="ebay_check",
    )

    logger.info("Bot started, polling...")
    await app.initialize()
    await app.bot.set_my_commands([
        BotCommand("start", "Открыть меню"),
    ])
    try:
        await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as e:
        logger.warning("set_chat_menu_button failed: %s", e)
    await app.start()
    await app.updater.start_polling(drop_pending_updates=False)

    stop_event = asyncio.Event()

    import signal
    def _stop(sig, frame):
        logger.info("Stopping...")
        save_seen_ids()
        config.save()
        os._exit(0)

    try:
        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
    except (ValueError, OSError):
        pass

    await stop_event.wait()
    await app.stop()
    await app.shutdown()


async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    _runtime_errors.clear()
    _publish_runtime("running")
    try:
        await process_searches(bot, once=False)
        _publish_runtime("error" if _runtime_errors else "ok", "; ".join(_runtime_errors) or None)
    except Exception as e:
        _publish_runtime("error", type(e).__name__)
        logger.error("scheduled_check error: %s", e)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    data = query.data
    if data.startswith("hide:"):
        item_id = data[5:]
        config.ban_item(item_id)
        mark_seen_item(item_id)
        await query.answer("❌ Объявление скрыто")
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        logger.info("Hidden item: %s", item_id)
        save_seen_ids()
    elif data.startswith("ban:"):
        seller = data[4:]
        config.ban_seller_global(seller)
        delete_seller_data(seller)
        await query.answer(f"🚫 Продавец {seller} забанен навсегда")
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        logger.info("Banned seller: %s", seller)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)
    if not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_CHAT_ID not set")
        sys.exit(1)

    if args.once:
        asyncio.run(run_once())
    else:
        asyncio.run(run_continuous())


if __name__ == "__main__":
    main()
