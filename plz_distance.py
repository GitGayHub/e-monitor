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
    origin = _PLZ_DATA.get(USER_PLZ, (USER_LAT, USER_LON))
    return haversine_km(*origin, lat, lon)


def distance_between_plz(from_plz, to_plz):
    """An explicit search radius uses its actual center, without city exceptions."""
    _load()
    start = _PLZ_DATA.get(str(from_plz or "").zfill(5))
    end = _PLZ_DATA.get(str(to_plz or "").zfill(5))
    if start is None or end is None:
        return None
    return haversine_km(*start, *end)


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


def is_nearby(location_text, max_km=80):
    """Check if location is within max_km of user. Returns (bool, distance_km).
    Special case: Berlin is always considered 'nearby' (good train connection)."""
    if not location_text:
        return False, None
    
    # Only the actual city of Berlin, not Potsdam or the whole postal region.
    loc_lower = location_text.lower()
    if is_berlin_location(location_text):
        dist, _ = get_distance_from_location(location_text)
        return True, dist
    
    # Normal distance check
    dist, _ = get_distance_from_location(location_text)
    if dist is not None:
        return dist <= max_km, dist
    
    # A city-name guess cannot supply the required confirmed distance.
    return False, None


def is_berlin_location(text):
    """City field, not 'Bernau bei Berlin' or another city's vicinity."""
    return bool(re.match(r"^(?:(?:\d{5}|\d{2}\*{3})[\s,]+)?berlin(?:$|[,\s]+(?:de\b|deutschland\b|germany\b|\d{5}\b))", (text or "").strip().lower()))
