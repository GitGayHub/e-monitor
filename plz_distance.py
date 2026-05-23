"""PLZ distance calculator using Haversine formula.
Loads German PLZ coordinates from CSV and calculates distances."""
import os
import csv
import math
import re

_PLZ_DATA = {}  # plz_str -> (lat, lon)
_LOADED = False

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plz_geocoord.csv")

# User location (09648 Mittweida)
USER_PLZ = "09648"
USER_LAT = 50.9867
USER_LON = 12.9787


def _load():
    global _PLZ_DATA, _LOADED
    if _LOADED:
        return
    if not os.path.exists(CSV_PATH):
        _LOADED = True
        return
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) >= 3:
                plz = row[0].strip().zfill(5)
                try:
                    lat = float(row[1])
                    lon = float(row[2])
                    _PLZ_DATA[plz] = (lat, lon)
                except (ValueError, IndexError):
                    continue
    _LOADED = True


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def extract_plz(text):
    """Extract a 5-digit German PLZ from text."""
    if not text:
        return None
    m = re.search(r"\b(\d{5})\b", text)
    return m.group(1) if m else None


def get_distance_km(plz):
    """Get distance in km from USER_PLZ to given PLZ. Returns None if unknown."""
    _load()
    if not plz or plz not in _PLZ_DATA:
        return None
    lat, lon = _PLZ_DATA[plz]
    return haversine_km(USER_LAT, USER_LON, lat, lon)


def get_distance_from_location(location_text):
    """Try to extract PLZ from location text and calculate distance.
    Returns (distance_km, plz) or (None, None)."""
    if not location_text:
        return None, None
    plz = extract_plz(location_text)
    if plz:
        dist = get_distance_km(plz)
        return dist, plz
    return None, None


def is_nearby(location_text, max_km=100):
    """Check if location is within max_km of user. Returns (bool, distance_km).
    Special case: Berlin is always considered 'nearby' (good train connection)."""
    if not location_text:
        return False, None
    
    # Berlin special case — always show as reachable
    loc_lower = location_text.lower()
    berlin_markers = ("berlin", "10115", "10117", "10119", "10178", "10179",
                      "10243", "10245", "10247", "10249", "10315", "10317",
                      "10318", "10319", "10365", "10367", "10369", "10405",
                      "10407", "10409", "10435", "10437", "10439", "10551",
                      "10553", "10555", "10557", "10559", "10585", "10587",
                      "10589", "10623", "10625", "10627", "10629", "10707",
                      "10709", "10711", "10713", "10715", "10717", "10719",
                      "10777", "10779", "10781", "10783", "10785", "10787",
                      "10789", "10823", "10825", "10827", "10829", "10961",
                      "10963", "10965", "10967", "10969", "10997", "10999",
                      "potsdam")
    if any(m in loc_lower for m in berlin_markers):
        dist, _ = get_distance_from_location(location_text)
        return True, dist
    # Check PLZ range 10xxx-14xxx (Berlin + Umland)
    plz = extract_plz(location_text)
    if plz and plz[:2] in ("10", "12", "13", "14"):
        dist = get_distance_km(plz)
        return True, dist
    
    # Normal distance check
    dist, _ = get_distance_from_location(location_text)
    if dist is not None:
        return dist <= max_km, dist
    
    # Fallback: check by known city names
    nearby_cities = (
        "chemnitz", "dresden", "leipzig", "zwickau", "plauen", "freiberg",
        "mittweida", "döbeln", "glauchau", "frankenberg", "hainichen",
        "rochlitz", "burgstädt", "penig", "altenburg", "gera", "jena",
        "annaberg", "marienberg", "aue", "schwarzenberg", "schneeberg",
        "oelsnitz", "reichenbach", "crimmitschau", "werdau", "meerane",
        "limbach-oberfrohna", "flöha", "brand-erbisdorf",
    )
    if any(city in loc_lower for city in nearby_cities):
        return True, None
    return False, None
