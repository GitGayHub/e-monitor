import time
import logging
import re
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

from config_manager import ConfigManager
from price_history import (
    init_db, record_snapshot, record_seller_price, delete_seller_data,
    get_median_7d, get_stats_7d, get_trend, is_outlier,
)

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
    "monitors": {"80182"},             # Monitore, Projektoren & Zubehör
    "vr": {"190066"},                  # VR-Headsets
    "vr_headsets": {"190066"},         # VR-Headsets
}

PHONE_HARD_ACCESSORY_WORDS = (
    "case", "cover", "protector", "tempered glass", "bumper", "magsafe",
    "shell case", "skin case", "lens film", "camera lens",
    "camera protector", "holster", "wallet case", "armor case",
    "armour case", "shockproof case", "hydrogel film", "privacy filter",
    "silicone case", "rubber case", "tpu case", "frameless cover",
    "screen protector", "protective film", "schutzfolie", "panzerglas",
    "glass film", "lens protector", "metal lens film", "stand case",
    "leather case", "gel skin", "charging cable", "usb-c", "usb c",
    "charger", "metal frame", "bracket", "hybridglas", "flexibleglass",
    "schutzglas", "hartglas", "displayfolie", "panzerfolie", "privacy",
    "datenschutz", "grizzglass", "hülle", "huelle", "magcase",
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
    "ledercase", "lederhülle", "lederhuelle", "silikonhülle", "silikonhuelle",
    "silicon case", "schutzhüllen", "schutzhuellen", "handyhüllen", "handyhuellen",
    "panzerfolie", "schutzglas", "glasfolie", "motiv", "design", "muster", "print",
    "displayschutz", "kameraschutz", "linsenschutz", "displayschutzfolie", "kameraschutzfolie",
    "displayschutzglas", "kameraschutzglas", "dexnor", "spigen", "otterbox", "torras",
    "rhinoshield", "esr", "jetech", "elago", "ringke", "caseology", "ugreen", "anker", "belkin"
)

# HARD PART WORDS — these ALWAYS indicate a spare part / repair listing.
# No override possible. A title with "motherboard" or "digitizer" is never a phone for sale.
PHONE_HARD_PART_WORDS = (
    "lcd", "digitizer", "touch screen", "screen replacement",
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
    "replacement bezel", "displayrahmen", "rahmen", "photography kit",
    "photo kit", "fotografie-kit", "camera kit", "photography-kit",
    # Additional replacements / parts
    "ersatz", "abdeckung", "rückseitige", "rueckseitige", "schrauben",
    "halterung", "kleber", "klebestreifen", "klebepad",
    # Batteries / battery parts
    "akku", "battery", "batterie", "batteries"
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
        r"\bnubia\s+z\d+",
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
        r"^(?:nubia\s+)?(?:red\s*magic|redmagic)\s*\d{1,2}",
        r"^(?:zte\s+)?nubia\s+z\d+",
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
    "defekt", "teildefekt", "displayschaden", "display gewechselt", "icloud sperre", "gesperrt",
    "funktioniert nicht", "nur box", "verpackung", "tauschen", "tausch",
    "leerbox", "leerhuelle", "leerhülle", "empty box", "empty case", "nur ovp",
    "nur karton", "leerer karton", "schachtel leer", "leere schachtel",
    "psn servern ausgeschlossen", "von psn servern ausgeschlossen",
    "banned from psn servers", "nur ersatzteile", "ersatzteile reparatur",
    "als ersatzteile", "fuer ersatzteile",
    "for parts", "parts only", "spares repair", "not working",
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
    "burn in", "burn-in", "eingebranntes display", "eingebrannt", "schatten im display",
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
}

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
        "pied", "standfuss", "standfuß", "wall mount", "mount", "vesa",
    ),
    "headphones": (
        "scharnier", "halterung", "kopfbuegel", "kopfbügel", "speaker horn",
        "driver part", "schutzhülle", "schutzhuelle", "hülle", "huelle",
        "case", "silikon", "abdeckung", "ersatzteil", "ersatzteile", "ersatz teile", "part",
        "ohrpolster", "audio kabel", "kabel", "3.5mm", "kopfband", "hinge",
        "lautsprecher", "gehörschützer", "gehoerschuetzer", "ohrenschützer",
        "ohrenschuetzer", "storage bag", "replacement earpads", "earpads",
        "travel ready", "protective case", "kühlgel", "kuehlgel", "lautsprechertreiber",
        "kopfhoererbuegel", "kabelanschluss", "drahtanschluss", "12-pin",
        "kopfbügel abdeckung", "kopfbuegel abdeckung", "stirnband abdeckung",
        "schaumstoff", "einlagen", "polster paar", "nur ohrpolster",
        "foam earpad", "ear cushions", "pads pair",
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
        "thumb grip", "thumbstick", "analog stick",
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
        "tasche", "hülle", "huelle", "case", "display", "bildschirm", "screen",
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
        "taste", "panel", "tastenset", "maustaste", "maustasten", "maus-taste", "maus-tasten"
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
        "foam earpad", "ear cushions", "pads pair", "schrauben",
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
        "tastatur", "keyboard", "akku", "battery", "display", "bildschirm", "screen",
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


def _query_words(query):
    words = []
    for word in re.findall(r"\w+", _normalize(query)):
        if len(word) >= 3 or word.isdigit() or any(ch.isdigit() for ch in word) or word in SHORT_QUERY_WORDS:
            words.append(word)
    return words


def _has_query_word(title_norm, word):
    if word == "redmagic":
        return _has_term(title_norm, "redmagic") or "red magic" in title_norm
    if word.isdigit():
        return re.search(rf"\b{re.escape(word)}(?:gb|go|tb)?\b", title_norm) is not None
    return _has_term(title_norm, word)


def _sort_code(filters):
    if "sort_code" in filters:
        return filters.get("sort_code")
    sort_map = {
        "newest": "10",
        "price_asc": "15",
        "price_desc": "12",
    }
    return sort_map.get(filters.get("sort"), "10")


def _category_id(value):
    value = str(value or "all")
    if value.isdigit():
        return value
    return EBAY_CATEGORY_IDS.get(value, "")


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


def _is_phone_device_title(title_norm):
    if any(_has_term(title_norm, w) for w in PHONE_DEVICE_HINTS):
        return True
    if re.search(r"\bnubia\s+(?:z\d+|focus|red\s*magic)\b.*\bultra\b", title_norm):
        return True
    if re.search(r"\biphone\s+\d{2}\s+pro\s+max\b", title_norm):
        return True
    if re.search(r"\b(?:samsung\s+)?(?:galaxy\s+)?s\d{2}\s+ultra\b", title_norm):
        return True
    if re.search(r"\b(?:oneplus\s+(?:\d{1,2}|ace)|google\s+pixel\s+\d|pixel\s+\d)\b", title_norm):
        return True
    if re.search(r"\b(?:red\s*magic|redmagic)\s*\d{1,2}[a-z]?\b", title_norm):
        return bool(
            re.search(r"\b\d+\s*(?:gb|go|tb)\b", title_norm)
            or re.search(r"\b\d+\s*/\s*\d+\s*(?:gb|go|tb)\b", title_norm)
            or re.search(r"\b(?:red\s*magic|redmagic)\s*\d{1,2}\s*(?:pro|air|s)\b", title_norm)
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


def _matches_phone_query_model(title_norm, query_norm):
    if "nubia" in query_norm and "ultra" in query_norm:
        return re.search(r"\bnubia\s+(?:z\s*\d+|z\d+|focus(?:\s*\d+)?|red\s*magic)\b.*\bultra\b", title_norm) is not None
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
    if "redmagic" in query_norm:
        if any(_has_term(title_norm, w) for w in ("magic the gathering", "mtg", "karten", "orlando magic", "tablet")):
            return False
        return _has_term(title_norm, "redmagic") or "red magic" in title_norm
    if "red magic" in query_norm:
        if any(_has_term(title_norm, w) for w in ("magic the gathering", "mtg", "karten", "orlando magic", "tablet")):
            return False
        return "red magic" in title_norm or _has_term(title_norm, "redmagic")
    return True


def _is_phone_search_query(query_norm):
    if any(term in query_norm for term in ("iphone", "galaxy", "oneplus", "nubia", "red magic", "redmagic", "pixel")):
        return True
    return re.search(r"\b(?:samsung\s+)?s\d{2}\s+ultra\b", query_norm) is not None


def _has_accessory_term(title_norm, term):
    term_norm = _normalize(term)
    if " " in term_norm or not re.fullmatch(r"[a-z0-9]+", term_norm):
        return term_norm in title_norm
    
    words = re.findall(r'[a-z0-9]+', title_norm)
    for w in words:
        if w == term_norm:
            return True
        if len(w) > len(term_norm):
            if w.endswith(term_norm):
                return True
            if w.startswith(term_norm):
                return True
    return False


def _is_phone_accessory_title(title_norm):
    """Detect titles that are clearly accessories or spare parts.

    Hard parts (battery/lcd/digitizer/motherboard/...) are always treated as accessory
    regardless of other signals — these are never sold as working phones.
    
    Soft accessory words (case/cover/glass/transparent/zubehör) CAN appear in
    real phone listings ("iPhone mit Case", "Transparent Edition", "mit Zubehör").
    These are only treated as accessory if there's NO strong device hint AND
    no phone storage capacity mentioned.
    
    Titles starting with "für" / "fuer" / "for" are always accessories.
    """
    # Titles starting with "für/fuer/for" are always accessories
    if re.match(r"^(?:fuer|für|for)\s+", title_norm):
        return True
    
    # Hard parts — always accessory, no override possible
    has_hard_part = any(_has_accessory_term(title_norm, w) for w in PHONE_HARD_PART_WORDS)
    if has_hard_part:
        return True
    
    # Soft part/accessory words — overridden by strong device hints OR storage capacity
    # OR if the title LEADS with a phone model (not "Hülle für Galaxy..." but "Galaxy S24... mit Zubehör")
    has_soft_part = any(_has_accessory_term(title_norm, w) for w in PHONE_SOFT_ACCESSORY_WORDS)
    if has_soft_part:
        has_strong_device = (
            any(_has_term(title_norm, w) for w in PHONE_STRONG_DEVICE_HINTS)
            or _has_phone_storage(title_norm)
            or _title_leads_with_phone_model(title_norm)
        )
        if not has_strong_device:
            return True
    
    # Hard accessory words (case/cover/protector) — overridden by strong device hints OR storage
    has_acc_word = any(_has_accessory_term(title_norm, w) for w in PHONE_HARD_ACCESSORY_WORDS)
    if has_acc_word:
        has_strong_device = (
            any(_has_term(title_norm, w) for w in PHONE_STRONG_DEVICE_HINTS)
            or _has_phone_storage(title_norm)
        )
        if not has_strong_device:
            return True
    return False


def _is_for_accessory_title(title_norm, query_norm, category):
    # Detect if listing is for an accessory by checking for target compatibility phrases (e.g. "for PS5")
    # if the main device keyword/model only appears after the "for" term (or not at all).
    for_patterns = re.compile(
        r"\b(?:fuer|für|for|geeignet\s+fuer|geeignet\s+für|compatible\s+(?:with|to)?|kompatibel\s+(?:mit|zu)?)\b",
        re.IGNORECASE
    )
    for_match = for_patterns.search(title_norm)
    if not for_match:
        return False

    for_start = for_match.start()
    before_part = title_norm[:for_start]

    if query_norm:
        if category == "consoles":
            if _matches_console_query_model(before_part, query_norm):
                return False
        elif category == "phones" or _is_phone_search_query(query_norm):
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


def _is_display_replacement(text_norm):
    """Detect display/screen/oled/glass/backglass replacements in title or description."""
    p1 = r"\b(?:display|bildschirm|screen|oled|glas|glass|scheibe)\b.*\b(?<!nicht\s)(?<!kein\s)(?<!keine\s)(?<!ohne\s)(?<!no\s)(?<!not\s)(?<!without\s)(?:neu|getauscht|gewechselt|repariert|ersetzt|wechsel|wechseln|austausch|bekommen|erneuert|reparatur)\b"
    p2 = r"\b(?<!nicht\s)(?<!kein\s)(?<!keine\s)(?<!ohne\s)(?<!no\s)(?<!not\s)(?<!without\s)(?:neu|neues|neuer|getauschtes|gewechseltes|repariertes|ersetztes|erneuertes|frisches)\b.*\b(?:display|bildschirm|screen|oled|glas|glass|scheibe)\b"
    return bool(re.search(p1, text_norm, re.IGNORECASE) or re.search(p2, text_norm, re.IGNORECASE))


def _is_category_blocked_title(title_norm, category, query_norm=None):
    if any(_has_term(title_norm, w) for w in BAD_CONDITION_WORDS):
        return True
    if _is_display_replacement(title_norm):
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
    # Hard parts - always block, no bundle override
    hard_parts = CATEGORY_HARD_PART_WORDS.get(category, ())
    if any(_has_accessory_term(title_norm, w) for w in hard_parts):
        return True

    acc_words = CATEGORY_ACCESSORY_WORDS.get(category, ())
    has_acc = any(_has_accessory_term(title_norm, w) for w in acc_words)
    if has_acc:
        # Check if the title starts with "fuer", "für", "for", "geeignet" -> always block
        if re.match(r"^(?:fuer|für|for|geeignet|fits)\s+", title_norm):
            return True
        # Check if this is a bundle (main device + accessory)
        is_bundle = re.search(r"\b(?:mit|and|inkl|with|bundle)\b|\+|&", title_norm) is not None
        if is_bundle:
            device_patterns = r"\b(?:sony|playstation|ps5|xbox|nintendo|switch|meta|quest|pico|oculus|logitech|razer|superlight|g pro|iphone|samsung|pixel|redmagic|nubia|laptop|notebook|macbook|vivobook|zenbook|asus|hp|lenovo|dell)\b"
            if re.search(device_patterns, title_norm):
                # Ensure no "for/fuer/etc" precedes the device name (which indicates it's an accessory for that device)
                if re.search(r"\b(?:fuer|für|for|compatibel|kompatibel|zu|to)\b.*\b(?:sony|playstation|ps5|xbox|nintendo|switch|meta|quest|pico|oculus|logitech|razer|superlight|g pro|iphone|samsung|pixel|redmagic|nubia|laptop|notebook|macbook|vivobook|zenbook|asus|hp|lenovo|dell)\b", title_norm):
                    return True  # Block!
                return False  # Do NOT block (it's a bundle)
        return True  # Block accessory-only listings

    return False


def _effective_category(category, query_norm):
    if category and category != "all":
        return category
    if "sony wh" in query_norm or "sony ult wear" in query_norm:
        return "headphones"
    if any(w in query_norm for w in ("quest", "pico", "vive", "slimevr", "slime tracker", "full body tracking")):
        return "vr_headsets"
    if _has_term(query_norm, "pc"):
        return "computers"
    return category


def _matches_category_query(title_norm, category, query_norm):
    """Check if a title matches the intent of the search query.
    
    Philosophy: PASS everything by default, BLOCK only confirmed garbage.
    Lazy sellers write short titles — we don't want to miss good deals.
    Accessories/parts are caught separately by _is_category_blocked_title.
    """
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
        )
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
        # Block confirmed spare parts, pass everything else (including lazy titles)
        part_words = ("ersatz", "ersatzteil", "spare", "replacement", "oem",
                     "linke", "rechte", "left ear", "right ear")
        if any(_has_term(title_norm, w) for w in part_words):
            return any(term in title_norm for term in ("kopfhoerer", "headphones", "over-ear", "over ear"))
        return True

    if "playstation 5 pro" in query_norm:
        return ("playstation 5 pro" in title_norm or "ps5 pro" in title_norm) and not _is_category_blocked_title(title_norm, category, query_norm)

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
    """Natively appends standard category-specific negative keywords to exclude defects and parts."""
    query = search.get("query", "").strip()
    if query.startswith("-") or " -" in query:
        return query
    
    filters = search.get("filters", {}) or {}
    category = filters.get("category", "all")
    
    # Common defect exclusions useful for all searches (100% safe, no bundles can have these)
    excludes = [
        "defekt", "teildefekt", "ersatzteil", "reparatur",
        "broken", "cracked", "damage", "damaged", "defect", "defective",
        "repair", "spares", "parts", "wasserschaden"
    ]
    
    # Category-specific safe defect/parts exclusions
    if category == "phones":
        excludes.extend(["displayschaden", "icloud", "sperre", "gesperrt"])
        
    exclude_str = " ".join(f"-{w}" for w in excludes)
    return f"{query} {exclude_str}"


def _build_url_with_host(host, search, sub="www"):
    """Build search URL on a specific host, mapping LH_PrefLoc semantics.

    sub: 'www' (default) or 'm' for the mobile subdomain. We use 'm' as a
    retry path on ebay.de when the desktop search hits the splashui
    anti-bot challenge — the same query on m.ebay.de is served normally
    after the challenge has set its bm_sv cookie on the session.
    """
    filters = search.get("filters", {})
    params = {"_nkw": _build_smart_search_query(search)}
    sort_code = _sort_code(filters)
    if sort_code:
        params["_sop"] = str(sort_code)
    category_id = _category_id(filters.get("category"))
    if category_id:
        base = f"https://{sub}.{host}/sch/{category_id}/i.html"
    else:
        base = f"https://{sub}.{host}/sch/i.html"
    min_p = filters.get("min_price")
    max_p = filters.get("max_price")

    if min_p:
        params["_udlo"] = str(min_p)
    if max_p:
        params["_udhi"] = str(max_p)
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
            params["LH_ItemCondition"] = "1000|1500|2000|2500|3000"
    lt = filters.get("listing_type", "all")
    if lt in ("buy_now", "buy_now_offer"):
        params["LH_BIN"] = "1"
        if filters.get("best_offer"):
            params["LH_BO"] = "1"
    elif lt == "auction":
        params["LH_Auction"] = "1"
    elif lt == "offer":
        params["LH_BO"] = "1"
    st = filters.get("seller_type", "any")
    if st == "private":
        params["LH_SellerType"] = "1"
    loc = filters.get("location", "de")
    if host == "ebay.de":
        # On .de: LH_PrefLoc=1 = "Aus Deutschland", 2 = "EU"
        if loc == "de":
            params["LH_PrefLoc"] = "1"
        elif loc == "eu":
            params["LH_PrefLoc"] = "2"
    else:  # ebay.com
        if loc == "eu":
            params["LH_PrefLoc"] = "2"
    qstr = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{base}?{qstr}"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s", stream=sys.stdout, force=True)
logger = logging.getLogger()
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

config = ConfigManager()
init_db()

seen_ids = set()
process_lock = asyncio.Lock()

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


def _parse_time_left_to_minutes(time_left_str):
    t = time_left_str.lower().strip()
    
    days = 0
    m_days = re.search(r"(\d+)\s*(?:tag|d)", t)
    if m_days:
        days = int(m_days.group(1))
        
    hours = 0
    m_hours = re.search(r"(\d+)\s*(?:std|h)", t)
    if m_hours:
        hours = int(m_hours.group(1))
        
    minutes = 0
    m_minutes = re.search(r"(\d+)\s*(?:min|m\b)", t)
    if m_minutes:
        minutes = int(m_minutes.group(1))
        
    if days == 0 and hours == 0 and minutes == 0:
        if "sek" in t or "s" in t or "sec" in t:
            return 1  # 1 minute or less
            
    total_minutes = days * 1440 + hours * 60 + minutes
    return total_minutes


def _normalize(text):
    t = text.lower()
    t = t.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    t = t.replace("-", " ")  # Treat hyphens as spaces
    t = re.sub(r"\b(\d+)\s+(gb|go|tb)\b", r"\1\2", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _item_hash(seller, title, price):
    raw = f"{seller}|{title}|{price:.2f}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def load_seen_ids():
    global seen_ids
    if os.path.exists(SEEN_IDS_FILE):
        try:
            with open(SEEN_IDS_FILE, "r") as f:
                data = json.load(f)
                seen_ids = set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, IOError):
            seen_ids = set()


def save_seen_ids():
    lst = list(seen_ids)
    if len(lst) > 15000:
        lst = lst[-10000:]
    with open(SEEN_IDS_FILE, "w") as f:
        json.dump(lst, f)


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
    global seen_ids
    seen_ids.clear()
    save_seen_ids()
    logger.info("🧹 Сброс мониторинга: seen_ids очищен")


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
    category_id = _category_id(filters.get("category"))
    if category_id:
        base = f"https://www.ebay.de/sch/{category_id}/i.html"
    else:
        base = "https://www.ebay.de/sch/i.html"
    if filters.get("min_price"):
        params["_udlo"] = str(filters["min_price"])
    if filters.get("max_price"):
        params["_udhi"] = str(filters["max_price"])
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
            params["LH_ItemCondition"] = "1000|1500|2000|2500|3000"
    lt = filters.get("listing_type", "all")
    if lt in ("buy_now", "buy_now_offer"):
        params["LH_BIN"] = "1"
        if filters.get("best_offer"):
            params["LH_BO"] = "1"
    elif lt == "auction":
        params["LH_Auction"] = "1"
    elif lt == "offer":
        params["LH_BO"] = "1"
    st = filters.get("seller_type", "any")
    if st == "private":
        params["LH_SellerType"] = "1"
    loc = filters.get("location", "de")
    if loc == "de":
        params["LH_PrefLoc"] = "1"
    elif loc == "eu":
        params["LH_PrefLoc"] = "2"
    qstr = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{base}?{qstr}"


def parse_ebay_results(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    cards = soup.select("li.s-card")
    for card in cards:
        try:
            listing_id = card.get("data-listingid", "")
            if not listing_id:
                continue

            link_el = card.select_one("a.s-card__link")
            if not link_el:
                continue
            href = link_el.get("href", "")
            item_id_match = re.search(r"/itm/(\d+)", href)
            item_id = item_id_match.group(1) if item_id_match else listing_id

            title_el = card.select_one("span.su-styled-text.primary.default")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title or title.lower().startswith("shop on ebay"):
                continue

            price_el = card.select_one("span.s-card__price")
            price_text = price_el.get_text(strip=True) if price_el else ""
            is_multivariation = "bis" in price_text.lower() or "to" in price_text.lower()
            price = _parse_price(price_text)
            if price is None:
                continue

            img_el = card.select_one("img.s-card__image")
            image_url = ""
            if img_el:
                image_url = img_el.get("src", "") or img_el.get("data-defer-load", "")
                if "ebaystatic.com" in image_url and "ebayimg" not in image_url:
                    image_url = ""

            all_spans = card.select("span")
            all_texts = [s.get_text(strip=True).lower() for s in all_spans]

            is_pickup_only = False
            for txt in all_texts:
                if any(marker in txt for marker in ("nur abholung", "nur selbstabholung", "abholung: nur abholung", "kein versand", "no shipping", "collection in person", "local pickup only", "pickup only")):
                    is_pickup_only = True
                    break

            shipping_cost = 0.0
            if not is_pickup_only:
                for s in all_spans:
                    txt = s.get_text(strip=True)
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
                if "preisvorschlag" in txt or "best offer" in txt:
                    best_offer = True
                if ("gebot" in txt and "angebot" not in txt) or "bid" in txt or "ставк" in txt:
                    auction = True
                    buy_now = False
                    m_bids = re.search(r"(\d+)\s*(?:gebot|bid|ставк)", txt)
                    if m_bids:
                        try:
                            bids_count = int(m_bids.group(1))
                        except ValueError:
                            pass

            for s in all_spans:
                txt = s.get_text(strip=True)
                cls = " ".join(s.get("class", []))
                if re.match(r"\d+\s*(Std|Min|Tag|[hmd])", txt) and "secondary" in cls:
                    time_left = txt
                    if not auction:
                        auction = True
                        buy_now = False

            seller_name = ""
            rating_count = 0
            rating_percent = 0.0
            for idx, s in enumerate(all_spans):
                cls = " ".join(s.get("class", []))
                txt = s.get_text(strip=True)
                if "primary" in cls and "large" in cls and "bold" not in cls and "price" not in cls:
                    if txt and not txt.startswith(("EUR", "USD", "$", "€")) and len(txt) < 50:
                        if not re.match(r"^\d", txt) and "%" not in txt:
                            seller_name = txt
                if "positiv" in txt or "positive" in txt.lower():
                    m = re.search(r"([\d.,]+)%\s*(?:positiv|positive).*?\(([\d.,]+)\s*([kKmM]?)\)", txt)
                    if m:
                        try:
                            rating_percent = float(m.group(1).replace(",", "."))
                            count = float(m.group(2).replace(",", "."))
                            suffix = m.group(3).lower()
                            if suffix == "k":
                                count *= 1000
                            elif suffix == "m":
                                count *= 1000000
                            rating_count = int(count)
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
                "item_id": item_id,
                "title": title,
                "price": price,
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


def _parse_price(text):
    text = text.replace("\xa0", " ").strip()
    if "bis" in text.lower() or "to" in text.lower():
        parts = re.split(r"bis|to", text, flags=re.IGNORECASE)
        text = parts[0].strip()
    # Extract only the first price block to avoid commercial net price suffix (exkl. MwSt.)
    match = re.search(r'([\d.,\s]+)(?:EUR|USD|€|\$)', text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    else:
        match = re.search(r'(?:EUR|USD|€|\$)\s*([\d.,\s]+)', text, re.IGNORECASE)
        if match:
            text = match.group(1).strip()
    text = _normalize_price_number(text)
    try:
        return float(text)
    except ValueError:
        return None


def _parse_shipping(text):
    text = text.lower().strip()
    if not text or "kostenlos" in text or "free" in text or "gratis" in text:
        return 0.0
    match = re.search(r"([\d.,]+)\s*(€|\$)|(?:eur|usd|us)\s*([\d.,]+)", text, re.IGNORECASE)
    if match:
        val = _normalize_price_number(match.group(1) or match.group(3))
        try:
            return float(val)
        except ValueError:
            pass
    return 0.0


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
        return float(obj.get("value"))
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


def _build_ebay_api_params(search):
    filters = search.get("filters", {}) or {}
    params = {
        "q": _build_smart_search_query(search),
        "limit": "100",
        "sort": "newlyListed",
    }
    category_id = _category_id(filters.get("category"))
    if category_id:
        params["category_ids"] = category_id

    filter_parts = []
    currency = EBAY_API_CURRENCY_BY_MARKETPLACE.get(EBAY_MARKETPLACE_ID, "EUR")
    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    if min_price or max_price:
        lo = str(min_price) if min_price else ""
        hi = str(max_price) if max_price else ""
        filter_parts.append(f"price:[{lo}..{hi}]")
        filter_parts.append(f"priceCurrency:{currency}")

    cond = filters.get("condition", "any")
    if cond == "new":
        filter_parts.append("conditions:{NEW}")
    elif cond == "used":
        filter_parts.append("conditions:{USED}")
    elif cond == "any":
        filter_parts.append("conditions:{NEW|USED|REFURBISHED}")

    lt = filters.get("listing_type", "all")
    buying_map = {
        "buy_now": "FIXED_PRICE",
        "buy_now_offer": "FIXED_PRICE",
        "auction": "AUCTION",
        "offer": "BEST_OFFER",
    }
    if lt in buying_map:
        filter_parts.append(f"buyingOptions:{{{buying_map[lt]}}}")

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

    if filter_parts:
        params["filter"] = ",".join(filter_parts)
    return params


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

        items.append({
            "item_id": _api_item_id(summary),
            "title": title,
            "price": price,
            "shipping_cost": shipping_cost,
            "total_price": price + shipping_cost,
            "image_url": image.get("imageUrl", ""),
            "url": summary.get("itemWebUrl", ""),
            "buy_now": "FIXED_PRICE" in opts,
            "best_offer": "BEST_OFFER" in opts,
            "auction": "AUCTION" in opts,
            "condition": summary.get("condition", ""),
            "seller_name": seller.get("username", ""),
            "seller_rating_count": feedback_score,
            "seller_rating_percent": feedback_percent,
            "seller_type": "unknown",
            "top_rated": bool(summary.get("topRatedBuyingExperience")),
            "location": _api_location(summary),
            "time_left": "",
            "is_multivariation": is_multivariation,
            "is_pickup_only": is_pickup_only,
        })
    return items


def fetch_ebay_api_ex(search):
    token, err = _get_ebay_api_token()
    if err:
        return [], err
    params = _build_ebay_api_params(search)
    url = "https://api.ebay.com/buy/browse/v1/item_summary/search?" + urllib.parse.urlencode(params)
    country = EBAY_API_COUNTRY_BY_MARKETPLACE.get(EBAY_MARKETPLACE_ID, "DE")
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
                "X-EBAY-C-ENDUSERCTX": f"contextualLocation=country={country}",
            },
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT[1]) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        items = parse_ebay_api_results(data)
        logger.info("  %s -> %d items via eBay Browse API", search["query"], len(items))
        return items, None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            logger.warning("eBay API HTTP %s for '%s': %s", e.code, search["query"], body[:300])
        except Exception:
            pass
        return [], _ebay_api_http_error(e.code)
    except Exception as e:
        logger.warning("eBay API network error for '%s': %s", search["query"], e)
        return [], "api_network"


def _fetch_item_details(item_id):
    """Fetches the item details via the eBay Browse API."""
    token, err = _get_ebay_api_token()
    if err:
        logger.warning("_fetch_item_details: token error: %s", err)
        return None
    # Browse API item ID format is v1|{legacyItemId}|0
    browse_id = f"v1|{item_id}|0"
    url = f"https://api.ebay.com/buy/browse/v1/item/{urllib.parse.quote(browse_id)}"
    country = EBAY_API_COUNTRY_BY_MARKETPLACE.get(EBAY_MARKETPLACE_ID, "DE")
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
                "X-EBAY-C-ENDUSERCTX": f"contextualLocation=country={country}",
            },
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT[1]) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return data
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            logger.warning("_fetch_item_details: eBay API HTTP %s for item %s: %s", e.code, item_id, body[:300])
            if e.code == 404:
                return "__BLOCKED_404__"
        except Exception:
            pass
        return None
    except Exception as e:
        logger.warning("_fetch_item_details: eBay API network error for item %s: %s", item_id, e)
        return None


def _clean_description(html_text):
    """Strips HTML tags and unescapes HTML entities from the description."""
    if not html_text:
        return ""
    # Strip HTML tags
    text = re.sub(r'<[^>]+>', ' ', html_text)
    # Unescape HTML entities (like &amp;, &nbsp;)
    import html
    text = html.unescape(text)
    return text


def _is_description_blocked(desc_html, category):
    """Checks the description for bad condition keywords or lifting screen/backcover patterns."""
    if not desc_html:
        return False
    clean_desc = _clean_description(desc_html)
    desc_norm = _normalize(clean_desc)

    if _is_display_replacement(desc_norm):
        logger.info("Description blocked due to display/screen replacement pattern")
        return True

    # 1. Check for bad condition words/phrases
    for w in BAD_CONDITION_WORDS:
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
    return "⚠️❗"


def _is_eu(location_text):
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


def _calculate_total(item, settings):
    """Calculate total price including import duties for non-EU items.
    
    For non-EU (UK, US, China, etc.) via eBay Global Shipping:
    - 19% MwSt (VAT) on item price + shipping
    - ~4% Zoll (customs duty) for electronics
    - ~5€ GSP handling fee
    
    Real example: £419 item + £30.76 shipping → £97.98 Einfuhrabgaben → total £547.74
    That's ~21.7% on (price+shipping) + small fixed fee.
    """
    total = item["price"] + item["shipping_cost"]
    if settings.get("warn_non_eu") and item["location"]:
        if not _is_eu(item["location"]):
            # Import costs: 19% VAT + ~4% customs + ~5€ handling
            base = item["price"] + item["shipping_cost"]
            vat = base * 0.19
            customs = base * 0.04  # electronics ~3.7-4.7%
            handling = 5.0
            import_cost = vat + customs + handling
            total = base + import_cost
    item["total_price"] = round(total, 2)
    return item


def filter_results(items, search, config_obj, skip_seen=False, is_statistics=False):
    global_banned = config_obj.get_global_banned_sellers()
    banned_ids = config_obj.get_banned_item_ids()
    item_hashes = config_obj.get_item_hashes()
    filters = search.get("filters", {})
    category = filters.get("category", "all")
    query_words = _query_words(search.get("query", ""))
    exclude_words = [_normalize(w) for w in search.get("exclude_words", [])]
    include_words = [_normalize(w) for w in search.get("include_words", [])]
    exclude_sellers = [s.lower() for s in search.get("exclude_sellers", [])]
    settings = config_obj.get_settings()

    filtered = []
    seen_batch_ids = set()
    for item in items:
        if item.get("is_multivariation"):
            continue
        item_id = item["item_id"]
        if item_id in seen_batch_ids:
            continue
        if item_id in banned_ids:
            continue
        item = _calculate_total(item, settings)
        min_price = filters.get("min_price")
        if min_price is not None and item.get("total_price", 0) < min_price:
            continue
        max_price = filters.get("max_price")
        if max_price is not None and item.get("total_price", 0) > max_price:
            continue
            
        if item.get("is_pickup_only"):
            nearby = False
            if item.get("location"):
                from plz_distance import is_nearby
                nearby, _ = is_nearby(item["location"], max_km=100)
            if not nearby:
                continue

        listing_type = filters.get("listing_type", "all")
        if listing_type == "auction" and not item.get("auction"):
            continue
        if listing_type in ("buy_now", "buy_now_offer") and (item.get("auction") or not item.get("buy_now")):
            continue
        if listing_type == "offer" and not item.get("best_offer"):
            continue
        if filters.get("best_offer") and not item.get("best_offer"):
            continue
            
        # User requirement: For auction listings (unless they have Buy It Now),
        # only send if:
        # A) They accept Best Offer and have 0 bids.
        # B) They are ending in 1 hour or less.
        if not is_statistics:
            if item.get("auction") and not item.get("buy_now"):
                is_new_best_offer = item.get("best_offer") and item.get("bids_count") == 0
                is_ending_soon = False
                time_left_str = item.get("time_left", "")
                if time_left_str:
                    minutes = _parse_time_left_to_minutes(time_left_str)
                    if minutes is not None and minutes <= 60:
                        is_ending_soon = True
                if not (is_new_best_offer or is_ending_soon):
                    continue
                
        seller_lower = item["seller_name"].lower()
        if seller_lower in [s.lower() for s in global_banned]:
            continue
        if seller_lower in exclude_sellers:
            continue
        title_norm = _normalize(item["title"])
        # Block items with bad conditions (Defekt, Als Ersatzteile, etc.)
        cond_norm = _normalize(item.get("condition", ""))
        if cond_norm:
            if cond_norm in BAD_CONDITIONS or any(w in cond_norm for w in ("defekt", "ersatzteil", "parts", "not working", "salvage", "reparatur", "broken")):
                continue
        if query_words and not all(_has_query_word(title_norm, w) for w in query_words):
            continue
        query_norm = _normalize(search.get("query", ""))
        effective_category = _effective_category(category, query_norm)
        if not _matches_category_query(title_norm, effective_category, query_norm):
            continue
        if _is_category_blocked_title(title_norm, effective_category, query_norm):
            continue
        if category == "phones" or _is_phone_search_query(query_norm):
            if not _matches_phone_query_model(title_norm, query_norm):
                continue
            if _is_phone_accessory_title(title_norm):
                continue
            if not _is_phone_device_title(title_norm):
                continue
        if category == "consoles":
            if not _matches_console_query_model(title_norm, query_norm):
                continue
        if any(w in title_norm for w in exclude_words):
            continue
        if include_words and not any(w in title_norm for w in include_words):
            continue
        if not skip_seen:
            h = _item_hash(item["seller_name"], item["title"], item["price"])
            if not item.get("auction") and h in item_hashes:
                continue
        filtered.append(item)
        seen_batch_ids.add(item_id)
    return filtered


def fetch_ebay(search):
    """Returns list of items. On error returns []. For detailed status use fetch_ebay_ex."""
    items, _err = fetch_ebay_ex(search)
    return items


def _merge_items_by_id(*groups):
    merged = {}
    for group in groups:
        for item in group or []:
            item_id = item.get("item_id")
            if item_id and item_id not in merged:
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
        time.sleep(random.uniform(0.6, 1.4))
        # Touch the cell phones category like a real shopper would.
        session.get(
            f"{home}b/Cell-Phones-Smartphones/9355/bn_320094",
            timeout=HTTP_TIMEOUT,
            headers={"Referer": home},
        )
        time.sleep(random.uniform(0.4, 1.0))
    except Exception as e:
        logger.debug("warmup on %s failed (non-fatal): %s", host, e)


def _do_fetch_one(host, search, referer=None):
    """Single attempt against a specific host. Returns (items, error)."""
    global _ebay_session_warmed
    url = _build_url_with_host(host, search)
    session = _get_ebay_session()
    home = f"https://www.{host}/"
    referer = referer or home
    try:
        if not _ebay_session_warmed:
            _warmup_session(session, host)
            _ebay_session_warmed = True
        common_headers = {
            "Referer": referer,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        resp = session.get(url, timeout=HTTP_TIMEOUT, headers=common_headers)
    except Exception as e:
        # curl_cffi raises its own errors; treat all as network
        if "impersonating" in str(e).lower() and "not supported" in str(e).lower():
            logger.warning("Unsupported eBay fingerprint %s, rotating", _ebay_session_ua)
            reset_ebay_session(rotate=True)
            return [], "blocked"
        if "timeout" in str(e).lower():
            logger.error("Timeout fetching '%s' on %s: %s", search["query"], host, e)
            return [], "network"
        logger.error("Network error fetching '%s' on %s: %s", search["query"], host, e)
        return [], "network"

    sc = resp.status_code
    if sc == 429:
        logger.warning("eBay %s rate limited (429) for '%s'", host, search["query"])
        return [], "rate_limit"
    if sc in (403, 503):
        logger.warning("eBay %s blocked (%d) for '%s'", host, sc, search["query"])
        return [], "blocked"
    if sc >= 400:
        logger.error("HTTP %d on %s for '%s'", sc, host, search["query"])
        return [], f"http_{sc}"

    body = resp.text or ""
    low = body[:8000].lower()
    final_url = getattr(resp, "url", "") or ""
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
    if "/splashui/" in final_url.lower() or any(m in low for m in challenge_markers):
        # The first hit at the desktop search endpoint reliably trips eBay's
        # splashui challenge for non-browser TLS sessions, but immediately
        # repeating the same query on the mobile subdomain m.ebay.de works,
        # because the failed challenge attaches a bm_sv cookie that the
        # mobile front-end accepts. We do that retry here transparently.
        if host == "ebay.de" and "://m.ebay.de/" not in url:
            m_url = _build_url_with_host(host, search, sub="m")
            try:
                resp2 = session.get(m_url, timeout=HTTP_TIMEOUT, headers=common_headers)
            except Exception as e:
                logger.warning("eBay m.%s retry network error for '%s': %s", host, search["query"], e)
                return [], "blocked"
            sc2 = resp2.status_code
            body2 = resp2.text or ""
            low2 = body2[:8000].lower()
            final_url2 = getattr(resp2, "url", "") or ""
            if sc2 < 400 and "/splashui/" not in final_url2.lower() and not any(
                m in low2 for m in challenge_markers
            ):
                try:
                    items2 = parse_ebay_results(body2)
                except Exception as e:
                    logger.error("Parse error for '%s' on m.%s: %s", search["query"], host, e)
                    return [], "parse"
                if items2:
                    return items2, None
        logger.warning(
            "eBay %s challenge page for '%s' (impersonate=%s)",
            host, search["query"], _ebay_session_ua,
        )
        return [], "blocked"

    try:
        items = parse_ebay_results(body)
    except Exception as e:
        logger.error("Parse error for '%s' on %s: %s", search["query"], host, e)
        return [], "parse"

    if not items:
        has_result_container = (
            'class="srp-results' in body
            or "srp-river-results" in body
            or 'class="srp-list' in body
            or "data-listingid" in body
        )
        has_no_results_marker = (
            "kein ergebnis" in low
            or "no exact matches" in low
            or "0 ergebnisse" in low
            or "0 results" in low
            or "we couldn" in low
        )
        if not has_result_container and not has_no_results_marker:
            logger.warning("eBay %s empty (likely stealth block) for '%s'", host, search["query"])
            return [], "blocked"

    return items, None


def _query_cache_key(search):
    """Stable key for the search-input portion that affects eBay results."""
    filters = search.get("filters", {}) or {}
    keys = ("category", "max_price", "min_price", "condition", "condition_code", "listing_type", "best_offer", "seller_type", "location", "sort", "sort_code")
    source = EBAY_SOURCE if EBAY_SOURCE in ("auto", "html", "api") else "auto"
    parts = [f"source={source}", f"market={EBAY_MARKETPLACE_ID}", search.get("query", "").strip().lower()]
    for k in keys:
        parts.append(f"{k}={filters.get(k, '')}")
    return "|".join(parts)


def fetch_ebay_ex(search):
    """Returns (items, error). Tries host chain: remembers a working one,
    falls back to next host on block/rate_limit. After sustained blocks the
    eBay client cools down for a while so a flagged IP can recover.
    error: None | 'rate_limit' | 'blocked' | 'cooldown' | 'network' | 'http_<code>' | 'parse' | 'api_*'.
    """
    global _ebay_active_host, _ebay_block_until, _ebay_consecutive_blocks
    now = time.time()
    source = EBAY_SOURCE if EBAY_SOURCE in ("auto", "html", "api") else "auto"

    # Short per-query cache: absorbs duplicate calls from the UI ('Retry'
    # button spam, double-presses) so we don't hammer eBay.
    cache_key = _query_cache_key(search)
    cached = _ebay_query_cache.get(cache_key)
    if cached and now - cached[0] < _EBAY_QUERY_CACHE_TTL:
        items, err = cached[1], cached[2]
        logger.info("  %s -> cached (%ds old, %d items, err=%s)",
                    search["query"], int(now - cached[0]), len(items), err)
        return items, err

    if source == "api":
        items, err = fetch_ebay_api_ex(search)
        _ebay_query_cache[cache_key] = (time.time(), items, err)
        return items, err

    if now < _ebay_block_until:
        wait = int(_ebay_block_until - now)
        logger.info("eBay cooldown active, %d s left", wait)
        if source == "auto" and _ebay_api_configured():
            items, err = fetch_ebay_api_ex(search)
            if err is None:
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
        # Per-host retries: first attempt uses the current impersonation
        # profile, the second one rotates to the next profile and re-warms
        # the session. eBay sometimes flags one fingerprint while leaving
        # the next alone, so this turns a transient block into a hit.
        attempts_per_host = 2
        for host in chain:
            for attempt in range(attempts_per_host):
                its, e = _do_fetch_one(host, search, referer=referer)
                if e is None:
                    return its, None, host
                last = e
                if e in ("blocked", "rate_limit"):
                    # Last attempt for this host? Roll over to the next host.
                    if attempt == attempts_per_host - 1:
                        reset_ebay_session()
                        break
                    # Otherwise rotate fingerprint and try the same host again.
                    reset_ebay_session(rotate=True)
                    continue
                return its, e, None
        return [], last or "blocked", None

    items, err, host = _try_chain()
    if err is None:
        _ebay_active_host = host
        _ebay_consecutive_blocks = 0
        if items:
            logger.info("  %s -> %d items via %s", search["query"], len(items), host)
        _ebay_query_cache[cache_key] = (time.time(), items, None)
        return items, None

    if err not in ("blocked", "rate_limit"):
        _ebay_query_cache[cache_key] = (time.time(), items, err)
        return items, err

    if source == "auto" and _ebay_api_configured():
        _ebay_block_until = max(_ebay_block_until, time.time() + _EBAY_BLOCK_COOLDOWN_BASE)
        logger.info("eBay HTML blocked/rate-limited, trying Browse API fallback")
        api_items, api_err = fetch_ebay_api_ex(search)
        if api_err is None:
            _ebay_query_cache[cache_key] = (time.time(), api_items, None)
            return api_items, None
        logger.warning("eBay API fallback failed: %s", api_err)

    # Still blocked — exponential cooldown to stop hammering the flagged IP.
    _ebay_consecutive_blocks += 1
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


async def send_notification(bot, item, search, stats_7d=None):
    trust = _seller_trust(item["seller_rating_count"], item["seller_rating_percent"], item.get("top_rated"))
    emoji = _trust_emoji(trust)

    types = []
    if item["auction"] and not item["buy_now"]:
        # Auction-first for auction listings
        types.append("Auktion")
        if item["best_offer"]:
            types.append("🤝 Preisvorschlag")
    else:
        # Buy-now-first for buy listings
        if item["buy_now"]:
            types.append("Sofort-Kaufen")
        if item["best_offer"]:
            types.append("🤝 Preisvorschlag")
        if item["auction"]:
            types.append("Auktion")
    type_str = " + ".join(types)

    # Price display: distinguish "buy now" from "auction"
    if item["auction"] and not item["buy_now"]:
        time_info = f" · {item['time_left']}" if item.get("time_left") else ""
        price_line = f"💰 🔨 Ставка {item['price']:.0f}€{time_info}"
        type_line = f"🏷 {type_str}"
    elif item["buy_now"]:
        offer = " 🤝" if item["best_offer"] else ""
        price_line = f"💰 🛒 {item['price']:.0f}€{offer}"
        type_line = f"🏷 {type_str}"
    else:
        price_line = f"💰 {item['price']:.0f}€"
        type_line = f"🏷 {type_str}"

    location_flag = ""
    if item["location"]:
        if not _is_eu(item["location"]):
            location_flag = "⚠️🌍 "
        elif "deutschland" in item["location"].lower() or "germany" in item["location"].lower():
            location_flag = "🇩🇪 "
        else:
            location_flag = "🇪🇺 "

    if item.get("is_pickup_only"):
        shipping_str = "Nur Abholung (Без доставки)"
    else:
        shipping_str = "Бесплатная доставка" if item["shipping_cost"] == 0 else f"+{item['shipping_cost']:.0f}€ доставка"

    outlier = is_outlier(item["price"], search["id"])

    lines = []
    if item.get("is_pickup_only"):
        lines.append("⚠️ NUR ABHOLUNG ⚠️")
        lines.append("")

    if outlier:
        lines.append(f"🚨 {item['title']}")
    else:
        lines.append(f"🆕 {item['title']}")
    lines.append("")
    lines.append(price_line)
    lines.append(type_line)

    seller_info = f"{emoji} {item['seller_name']}"
    if item["seller_rating_count"] > 0:
        seller_info += f" ({item['seller_rating_count']} отзывов)"
    else:
        seller_info += " (0 отзывов)"
    lines.append(f"👤 {seller_info}")

    if item["condition"] or item["location"]:
        parts = []
        if item["condition"]:
            parts.append(item["condition"])
        if item["location"]:
            parts.append(f"{location_flag}{item['location']}")
        lines.append(f"📦 {' | '.join(parts)}")
    
    # Abholung hint: check if item is within ~100km using PLZ coordinates
    if item["location"]:
        from plz_distance import is_nearby, get_distance_from_location
        nearby, dist_km = is_nearby(item["location"], max_km=100)
        if nearby:
            if dist_km is not None:
                if dist_km > 120:
                    # Berlin exception — far but reachable
                    lines.append(f"📍 Abholung ~{dist_km:.0f}km (Berlin)")
                else:
                    lines.append(f"📍 Abholung ~{dist_km:.0f}km")
            else:
                lines.append(f"📍 Abholung möglich")
    lines.append(f"🚚 {shipping_str}")
    if item["total_price"] != item["price"] + item["shipping_cost"]:
        import_extra = item["total_price"] - item["price"] - item["shipping_cost"]
        lines.append(f"⚠️ +{import_extra:.0f}€ пошлина → итого ~{item['total_price']:.0f}€")

    if outlier:
        median = get_median_7d(search["id"])
        if median:
            lines.append(f"\n⚠️ Подозрительно низкая цена (медиана: {median:.0f}€)")
            lines.append("Не учтено в статистике")
    elif stats_7d and stats_7d.get("median"):
        median = stats_7d["median"]
        diff_pct = ((median - item["price"]) / median) * 100
        if diff_pct > 5:
            lines.append(f"\n🔥 {item['price']:.0f}€ — на {diff_pct:.0f}% ниже медианы! ({stats_7d['first_date']}–{stats_7d['last_date']})")

    caption = "\n".join(lines)
    if len(caption) > 1024:
        caption = caption[:1020] + "..."

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔗 Открыть", url=item["url"]),
            InlineKeyboardButton("❌ Скрыть", callback_data=f"hide:{item['item_id']}"),
            InlineKeyboardButton("🚫 Бан", callback_data=f"ban:{item['seller_name']}"),
        ]
    ])

    img = item.get("image_url") or ""
    if img and not img.startswith("data:"):
        # Upgrade thumbnail to s-l800: enough resolution for Telegram preview
        # but ~5x faster to fetch than s-l1600 (which is the original size,
        # often 1-3 MB and routinely trips Telegram's 30s download timeout).
        import re as _re
        img = _re.sub(r"/s-l\d+\.(jpg|jpeg|png|webp)", r"/s-l800.\1", img, flags=_re.IGNORECASE)

    logger.info("send_notification: %s", caption.replace("\n", " | "))
    try:
        sent = await safe_send_telegram(
            bot,
            TELEGRAM_CHAT_ID,
            caption,
            img=img,
            keyboard=keyboard,
            parse_mode=None
        )
        return sent
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
                await active_bot.send_photo(
                    chat_id=chat_id,
                    photo=img,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode,
                )
            else:
                await active_bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )
            return True
        except Exception as e:
            logger.warning("Failed to send message via bot: %s. Trying next...", e)
            
    return False


async def _validate_candidate(item, search):
    details = await asyncio.to_thread(_fetch_item_details, item["item_id"])
    if details == "__BLOCKED_404__":
        return False, None
    
    if details:
        # Block incorrect subcategories (accessories/parts) to prevent false positives
        cat_id = details.get("categoryId")
        search_cat = search.get("filters", {}).get("category", "all")
        if search_cat in ALLOWED_SUBCATEGORIES:
            allowed_set = ALLOWED_SUBCATEGORIES[search_cat]
            if cat_id and cat_id not in allowed_set:
                cat_path_ids = details.get("categoryIdPath", "").split("|")
                if not any(cid in allowed_set for cid in cat_path_ids):
                    return False, details

        # Block SELLER_DEFINED_VARIATIONS
        if details.get("itemGroupType") == "SELLER_DEFINED_VARIATIONS":
            return False, details
            
        # Block constructor/bait listings
        api_price_val = details.get("price", {}).get("value")
        if api_price_val:
            try:
                api_price = float(api_price_val)
                scraped_price = float(item["price"])
                if abs(api_price - scraped_price) > 1.0:
                    return False, details
            except Exception:
                pass
                
        desc = details.get("description", "")
        if desc and _is_description_blocked(desc, search_cat):
            return False, details
            
    return True, details


async def process_searches(bot, once=False):
    async with process_lock:
        searches = config.get_searches()
        if not searches:
            logger.info("No searches configured")
            return

        test_summary_mode = _is_statistics_mode(config)

        if test_summary_mode:
            is_github = os.environ.get("GITHUB_ACTIONS") == "true"
            source_str = "GitHub Автомониторинг" if is_github else "Локальный"
            logger.info(f"🔍 Statistics/Diagnostic mode active ({source_str})...")
            report_lines = [
                f"📋 <b>Диагностический отчет (eBay, {source_str})</b>"
            ]
            blocked_searches = []
            
            # Group searches by (query, max_price)
            grouped = {}
            for search in searches:
                q = search.get("query", "").strip()
                limit = search.get("filters", {}).get("max_price")
                key = (q, limit)
                if key not in grouped:
                    grouped[key] = []
                grouped[key].append(search)
            
            for (q_name, limit_val), group_searches in grouped.items():
                base_search = group_searches[0]
                relaxed_search = copy.deepcopy(base_search)
                
                # Combine exclude and include words from all searches in this group
                exclude_set = set()
                include_set = set()
                for gs in group_searches:
                    exclude_set.update(gs.get("exclude_words", []))
                    include_set.update(gs.get("include_words", []))
                relaxed_search["exclude_words"] = list(exclude_set)
                relaxed_search["include_words"] = list(include_set)
                
                orig_max_price = limit_val
                orig_min_price = base_search.get("filters", {}).get("min_price")
                
                if "filters" in relaxed_search:
                    relaxed_search["filters"].pop("max_price", None)
                    relaxed_search["filters"].pop("best_offer", None)
                    relaxed_search["filters"].pop("min_price", None)
                    
                    relaxed_search["filters"]["listing_type"] = "all"
                    relaxed_search["filters"]["sort"] = "price_asc"

                results, fetch_err = await asyncio.to_thread(fetch_ebay_ex, relaxed_search)
                
                # API retry if blocked
                if fetch_err in ("blocked", "rate_limit", "cooldown"):
                    if _ebay_api_configured():
                        api_items, api_err = await asyncio.to_thread(fetch_ebay_api_ex, relaxed_search)
                        if not api_err and api_items:
                            results = api_items
                            fetch_err = None
                        else:
                            blocked_searches.append(base_search)
                    else:
                        blocked_searches.append(base_search)
                
                sweep = _auction_sweep_search(relaxed_search)
                if sweep:
                    auction_results, auction_err = await asyncio.to_thread(fetch_ebay_ex, sweep)
                    if not auction_err:
                        results = _merge_items_by_id(results, auction_results)
                
                # Filter results passing is_statistics=True to bypass auction time/bid filters
                filtered = filter_results(results, relaxed_search, config, skip_seen=True, is_statistics=True)
                
                # Group filtered items into Buy It Now and Auction
                bin_filtered = [item for item in filtered if item.get("buy_now")]
                auc_filtered = [item for item in filtered if item.get("auction")]
                
                # Helper to find the cheapest validated candidate
                async def find_cheapest_valid(items, search_cfg):
                    for item in items[:5]:
                        is_valid, _ = await _validate_candidate(item, search_cfg)
                        if is_valid:
                            return item
                    return None
                
                # Find cheapest BIN item(s)
                sorted_bin = sorted(bin_filtered, key=lambda x: x["total_price"])
                cheapest_bin = await find_cheapest_valid(sorted_bin, base_search)
                cheapest_bin_bo = None
                if cheapest_bin and not cheapest_bin.get("best_offer"):
                    sorted_bin_bo = sorted([x for x in bin_filtered if x.get("best_offer")], key=lambda x: x["total_price"])
                    cheapest_bin_bo = await find_cheapest_valid(sorted_bin_bo, base_search)
                
                # Find cheapest Auction item(s)
                sorted_auc = sorted(auc_filtered, key=lambda x: x["total_price"])
                cheapest_auc = await find_cheapest_valid(sorted_auc, base_search)
                cheapest_auc_bo = None
                if cheapest_auc and not cheapest_auc.get("best_offer"):
                    sorted_auc_bo = sorted([x for x in auc_filtered if x.get("best_offer")], key=lambda x: x["total_price"])
                    cheapest_auc_bo = await find_cheapest_valid(sorted_auc_bo, base_search)
                
                # Emojis and verdict helper
                def get_verdict_str(price_val):
                    if orig_max_price and price_val > orig_max_price:
                        return "🔴 Слишком дорого"
                    else:
                        return "🟢 Подходит"
                
                def get_short_url(item_id):
                    return f"https://www.ebay.de/itm/{item_id}"
                
                # Build report block
                limit_str = f"{orig_max_price}€" if orig_max_price else "без лимита"
                query_esc = html.escape(q_name)
                block_lines = [f"• <b>{query_esc}</b> (лимит {limit_str})"]
                
                # 1. Format Sofort-Kauf (BIN) status
                if cheapest_bin:
                    p_bin = cheapest_bin["total_price"]
                    url_bin = get_short_url(cheapest_bin["item_id"])
                    v_bin = get_verdict_str(p_bin)
                    
                    if cheapest_bin_bo and cheapest_bin_bo["item_id"] != cheapest_bin["item_id"]:
                        p_bo = cheapest_bin_bo["total_price"]
                        url_bo = get_short_url(cheapest_bin_bo["item_id"])
                        v_bo = get_verdict_str(p_bo)
                        block_lines.append(f"  ↳ Sofort-Kauf: {p_bin}€ <a href='{url_bin}'>🔗</a> | {v_bin}")
                        block_lines.append(f"  ↳ Sofort-Kauf (Preisvorschlag): {p_bo}€ <a href='{url_bo}'>🔗</a> | {v_bo}")
                    else:
                        bo_suffix = " (Preisvorschlag)" if cheapest_bin.get("best_offer") else ""
                        block_lines.append(f"  ↳ Sofort-Kauf: {p_bin}€ <a href='{url_bin}'>🔗</a>{bo_suffix} | {v_bin}")
                else:
                    if fetch_err:
                        reason = f"❌ Ошибка запроса ({fetch_err})"
                    elif not any(x.get("buy_now") for x in results):
                        reason = "❌ Нет объявлений на eBay"
                    else:
                        reason = "❌ Отсеяно фильтрами (слова/категория/состояние)"
                    block_lines.append(f"  ↳ Sofort-Kauf: {reason}")
                
                # 2. Format Auction status
                if cheapest_auc:
                    p_auc = cheapest_auc["total_price"]
                    url_auc = get_short_url(cheapest_auc["item_id"])
                    v_auc = get_verdict_str(p_auc)
                    
                    if cheapest_auc_bo and cheapest_auc_bo["item_id"] != cheapest_auc["item_id"]:
                        p_bo = cheapest_auc_bo["total_price"]
                        url_bo = get_short_url(cheapest_auc_bo["item_id"])
                        v_bo = get_verdict_str(p_bo)
                        block_lines.append(f"  ↳ Auction: {p_auc}€ <a href='{url_auc}'>🔗</a> | {v_auc}")
                        block_lines.append(f"  ↳ Auction (Preisvorschlag): {p_bo}€ <a href='{url_bo}'>🔗</a> | {v_bo}")
                    else:
                        bo_suffix = " (Preisvorschlag)" if cheapest_auc.get("best_offer") else ""
                        block_lines.append(f"  ↳ Auction: {p_auc}€ <a href='{url_auc}'>🔗</a>{bo_suffix} | {v_auc}")
                else:
                    if fetch_err:
                        reason = f"❌ Ошибка запроса ({fetch_err})"
                    elif not any(x.get("auction") for x in results):
                        reason = "❌ Нет объявлений на eBay"
                    else:
                        reason = "❌ Отсеяно фильтрами (слова/категория/состояние)"
                    block_lines.append(f"  ↳ Auction: {reason}")
                
                report_lines.append("\n".join(block_lines))
                
                if not once:
                    await asyncio.sleep(random.uniform(2, 5))
            
            # Split report_lines into chunks of at most 3500 characters to avoid Telegram length limit
            chunks = []
            current_chunk = [report_lines[0]]  # Header line
            current_len = len(report_lines[0])
            
            for line in report_lines[1:]:
                if current_len + len(line) + 2 > 3500:
                    chunks.append("\n\n───────────────────\n\n".join(current_chunk))
                    current_chunk = [f"📋 <b>Диагностический отчет (eBay, {source_str}, продолжение)</b>", line]
                    current_len = len(current_chunk[0]) + len(line) + 2
                else:
                    current_chunk.append(line)
                    current_len += len(line) + 2
            
            if current_chunk:
                chunks.append("\n\n───────────────────\n\n".join(current_chunk))
            
            logger.info(f"📊 Отправляю диагностический отчет в Telegram ({len(chunks)} частей)...")
            
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
                if not sent:
                    logger.error(f"Ошибка отправки части {i+1} диагностического отчета")
                await asyncio.sleep(1.0)
                
            clear_monitoring_state()
            return

        total_new = 0
        blocked_searches = []  # Searches that failed due to block/rate_limit/cooldown

        for search in searches:
            results, fetch_err = await asyncio.to_thread(fetch_ebay_ex, search)
            if fetch_err:
                if fetch_err in ("blocked", "rate_limit", "cooldown"):
                    blocked_searches.append(search)
                logger.warning("  %s: fetch error %s", search["query"], fetch_err)
                continue
            sweep = _auction_sweep_search(search)
            if sweep:
                auction_results, auction_err = await asyncio.to_thread(fetch_ebay_ex, sweep)
                if auction_err:
                    logger.warning("  %s: auction sweep error %s", search["query"], auction_err)
                else:
                    before = len(results)
                    results = _merge_items_by_id(results, auction_results)
                    if len(results) > before:
                        logger.info("  %s: auction sweep added %d item(s)", search["query"], len(results) - before)
            if not results:
                logger.info("  %s: 0 results", search["query"])
                continue

            filtered = filter_results(results, search, config)

            sofort = [r for r in filtered if r["buy_now"]]
            preisvorschlag = [r for r in filtered if r["best_offer"]]
            auctions = [r for r in filtered if r["auction"]]

            sofort_prices = [r["price"] for r in sofort if not is_outlier(r["price"], search["id"])]
            pv_prices = [r["price"] for r in preisvorschlag if not is_outlier(r["price"], search["id"])]
            auction_prices = [r["price"] for r in auctions if not is_outlier(r["price"], search["id"])]
            record_snapshot(search["id"], sofort_prices, pv_prices, auction_prices, len(filtered))

            for r in filtered:
                if not is_outlier(r["price"], search["id"]):
                    record_seller_price(search["id"], r["seller_name"], r["price"], r["item_id"])

            stats_7d = get_stats_7d(search["id"])

            new_items = [r for r in filtered if r["item_id"] not in seen_ids]
            logger.info("  %s: %d results, %d new", search["query"], len(filtered), len(new_items))

            for item in sorted(new_items, key=lambda x: x["total_price"]):
                h = _item_hash(item["seller_name"], item["title"], item["price"])
                details = await asyncio.to_thread(_fetch_item_details, item["item_id"])
                if details == "__BLOCKED_404__":
                    logger.info("Skipping notification for item %s: blocked due to API 404 (sold out or variation parent)", item["item_id"])
                    seen_ids.add(item["item_id"])
                    continue
                
                desc = ""
                if details:
                    # Block incorrect subcategories (accessories/parts) to prevent false positives
                    cat_id = details.get("categoryId")
                    search_cat = search.get("filters", {}).get("category", "all")
                    if search_cat in ALLOWED_SUBCATEGORIES:
                        allowed_set = ALLOWED_SUBCATEGORIES[search_cat]
                        if cat_id and cat_id not in allowed_set:
                            cat_path_ids = details.get("categoryIdPath", "").split("|")
                            if not any(cid in allowed_set for cid in cat_path_ids):
                                logger.info("Skipping notification for item %s: category %s not allowed for search %s", item["item_id"], cat_id, search_cat)
                                seen_ids.add(item["item_id"])
                                continue

                    # Block SELLER_DEFINED_VARIATIONS
                    if details.get("itemGroupType") == "SELLER_DEFINED_VARIATIONS":
                        logger.info("Skipping notification for item %s: blocked as SELLER_DEFINED_VARIATIONS", item["item_id"])
                        seen_ids.add(item["item_id"])
                        continue
                    # Block constructor/bait listings (price mismatch between search results and API details)
                    api_price_val = details.get("price", {}).get("value")
                    if api_price_val:
                        try:
                            api_price = float(api_price_val)
                            scraped_price = float(item["price"])
                            if abs(api_price - scraped_price) > 1.0:
                                logger.info("Skipping notification for item %s: blocked due to price mismatch (scraped: %s, API: %s)", item["item_id"], scraped_price, api_price)
                                seen_ids.add(item["item_id"])
                                continue
                        except Exception as pe:
                            logger.warning("Error comparing prices for item %s: %s", item["item_id"], pe)
                    desc = details.get("description", "")

                if desc and _is_description_blocked(desc, search.get("filters", {}).get("category", "all")):
                    logger.info("Skipping notification for item %s: blocked by description check", item["item_id"])
                    seen_ids.add(item["item_id"])
                    continue
                sent = await send_notification(bot, item, search, stats_7d)
                if sent:
                    total_new += 1
                    if not item.get("auction"):
                        config.add_item_hash(h)
                    seen_ids.add(item["item_id"])
                else:
                    logger.warning("Notification failed; will retry item %s on next run", item["item_id"])
                await asyncio.sleep(0.5)

            if not once:
                import random
                await asyncio.sleep(random.uniform(2, 5))

        # === API RETRY for blocked searches ===
        # If any searches were blocked by HTML scraping, retry them NOW via API
        # so we don't miss items (especially important for GitHub Actions where
        # the next run is 15 minutes away).
        if blocked_searches and _ebay_api_configured():
            logger.info("=== API retry for %d blocked search(es) ===", len(blocked_searches))
            for search in blocked_searches:
                api_items, api_err = await asyncio.to_thread(fetch_ebay_api_ex, search)
                if api_err:
                    logger.warning("  %s: API retry failed: %s", search["query"], api_err)
                    continue
                if not api_items:
                    logger.info("  %s: API retry 0 results", search["query"])
                    continue

                filtered = filter_results(api_items, search, config)
                stats_7d = get_stats_7d(search["id"])
                new_items = [r for r in filtered if r["item_id"] not in seen_ids]
                logger.info("  %s: API retry %d results, %d new", search["query"], len(filtered), len(new_items))

                for item in sorted(new_items, key=lambda x: x["total_price"]):
                    h = _item_hash(item["seller_name"], item["title"], item["price"])
                    details = await asyncio.to_thread(_fetch_item_details, item["item_id"])
                    if details == "__BLOCKED_404__":
                        logger.info("Skipping notification for item %s: blocked due to API 404 (sold out or variation parent)", item["item_id"])
                        seen_ids.add(item["item_id"])
                        continue
                    
                    desc = ""
                    if details:
                        # Block incorrect subcategories (accessories/parts) to prevent false positives
                        cat_id = details.get("categoryId")
                        search_cat = search.get("filters", {}).get("category", "all")
                        if search_cat in ALLOWED_SUBCATEGORIES:
                            allowed_set = ALLOWED_SUBCATEGORIES[search_cat]
                            if cat_id and cat_id not in allowed_set:
                                cat_path_ids = details.get("categoryIdPath", "").split("|")
                                if not any(cid in allowed_set for cid in cat_path_ids):
                                    logger.info("Skipping notification for item %s: category %s not allowed for search %s", item["item_id"], cat_id, search_cat)
                                    seen_ids.add(item["item_id"])
                                    continue

                        # Block SELLER_DEFINED_VARIATIONS
                        if details.get("itemGroupType") == "SELLER_DEFINED_VARIATIONS":
                            logger.info("Skipping notification for item %s: blocked as SELLER_DEFINED_VARIATIONS", item["item_id"])
                            seen_ids.add(item["item_id"])
                            continue
                        # Block constructor/bait listings (price mismatch between search results and API details)
                        api_price_val = details.get("price", {}).get("value")
                        if api_price_val:
                            try:
                                api_price = float(api_price_val)
                                scraped_price = float(item["price"])
                                if abs(api_price - scraped_price) > 1.0:
                                    logger.info("Skipping notification for item %s: blocked due to price mismatch (scraped: %s, API: %s)", item["item_id"], scraped_price, api_price)
                                    seen_ids.add(item["item_id"])
                                    continue
                            except Exception as pe:
                                logger.warning("Error comparing prices for item %s: %s", item["item_id"], pe)
                        desc = details.get("description", "")

                    if desc and _is_description_blocked(desc, search.get("filters", {}).get("category", "all")):
                        logger.info("Skipping notification for item %s: blocked by description check", item["item_id"])
                        seen_ids.add(item["item_id"])
                        continue
                    sent = await send_notification(bot, item, search, stats_7d)
                    if sent:
                        total_new += 1
                        if not item.get("auction"):
                            config.add_item_hash(h)
                        seen_ids.add(item["item_id"])
                    else:
                        logger.warning("Notification failed; will retry item %s on next run", item["item_id"])
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
                    seen_ids.add(item_id)
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


async def run_once():
    load_seen_ids()
    _log_startup_banner("ONE-SHOT")
    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    await process_pending_callbacks(bot)
    await process_searches(bot, once=True)
    save_seen_ids()
    logger.info("=== Done ===")


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
    job_queue.run_repeating(
        scheduled_check,
        interval=300,
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
    try:
        await process_searches(bot, once=False)
    except Exception as e:
        logger.error("scheduled_check error: %s", e)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    data = query.data
    if data.startswith("hide:"):
        item_id = data[5:]
        config.ban_item(item_id)
        seen_ids.add(item_id)
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
