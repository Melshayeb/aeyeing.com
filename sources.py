"""
Online data fetchers for the trip planner.
Uses Open-Meteo for weather, and curated fallback lists for places/hotels.
Designed so paid sources (Google Places, SerpAPI) can be dropped in later.
"""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests


DATA_DIR = Path(__file__).parent.parent / "data"

# Country name -> ISO-3166 alpha-2 for APIs that need it
COUNTRY_ISO = {
    "australia": "AU", "austria": "AT", "belgium": "BE", "canada": "CA",
    "china": "CN", "denmark": "DK", "egypt": "EG", "france": "FR",
    "germany": "DE", "greece": "GR", "hong kong": "HK", "iceland": "IS",
    "india": "IN", "indonesia": "ID", "ireland": "IE", "israel": "IL",
    "italy": "IT", "japan": "JP", "malaysia": "MY", "mexico": "MX",
    "morocco": "MA", "netherlands": "NL", "new zealand": "NZ", "norway": "NO",
    "philippines": "PH", "portugal": "PT", "russia": "RU", "singapore": "SG",
    "south africa": "ZA", "south korea": "KR", "spain": "ES", "sweden": "SE",
    "switzerland": "CH", "taiwan": "TW", "thailand": "TH", "turkey": "TR",
    "united arab emirates": "AE", "united kingdom": "GB", "united states": "US",
    "vietnam": "VN", "fiji": "FJ",
}


def _country_iso(country: str) -> str:
    return COUNTRY_ISO.get(country.lower().strip(), country[:2].upper())


def load_fallback(country: str, city: str, kind: str) -> List[Dict]:
    """Load curated fallback JSON for a country/city if available."""
    filename = DATA_DIR / f"{kind}_{country.lower().replace(' ', '_')}.json"
    if not filename.exists():
        filename = DATA_DIR / f"{kind}_generic.json"
    if filename.exists():
        with open(filename, encoding="utf-8") as f:
            data = json.load(f)
        return data.get(city, data.get("default", []))
    return []


_GEOCODE_CACHE: Dict[str, Optional[Tuple[float, float]]] = {}
_LAST_NOMINATIM_CALL = 0.0
_NOMINATIM_MIN_DELAY = 1.0  # seconds between Nominatim calls
_GEOCODE_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geocode_cache.json")


_CITY_CENTERS: Dict[str, Tuple[float, float]] = {
    "cairo": (30.0444, 31.2357),
    "alexandria": (31.2001, 29.9187),
    "melbourne": (-37.8136, 144.9631),
    "sydney": (-33.8688, 151.2093),
    "tokyo": (35.6762, 139.6503),
    "kyoto": (35.0116, 135.7681),
    "osaka": (34.6937, 135.5023),
    "new york": (40.7128, -74.0060),
    "paris": (48.8566, 2.3522),
    "london": (51.5074, -0.1278),
    "rome": (41.9028, 12.4964),
    "istanbul": (41.0082, 28.9784),
    "doha": (25.2854, 51.5310),
    "dubai": (25.2048, 55.2708),
    "bangkok": (13.7563, 100.5018),
    "singapore": (1.3521, 103.8198),
    "barcelona": (41.3851, 2.1734),
    "amsterdam": (52.3676, 4.9041),
    "prague": (50.0755, 14.4378),
    "vienna": (48.2082, 16.3738),
    "berlin": (52.5200, 13.4050),
    "los angeles": (34.0522, -118.2437),
    "san francisco": (37.7749, -122.4194),
    "toronto": (43.6532, -79.3832),
    "vancouver": (49.2827, -123.1207),
    "honolulu": (21.3069, -157.8583),
    "maui": (20.7984, -156.3319),
    "kauai": (22.0964, -159.5261),
    "big island": (19.5429, -155.6659),
    "nadi": (-17.7765, 177.4493),
    "suva": (-18.1248, 178.4501),
    "denarau": (-17.7698, 177.3807),
    "kuala lumpur": (3.1516964, 101.6942371),
    "penang": (5.4065013, 100.2559077),
    "langkawi": (6.3500, 99.8000),
    "george town": (5.4142, 100.3288),
    "chengdu": (30.5728, 104.0668),
    "marrakech": (31.6295, -7.9811),
    "casablanca": (33.5731, -7.5898),
}


# Per-city external-API safety limits so one slow API cannot block the whole trip.
# connect/read seconds; retries count. Total worst-case per call = retries * read + connect.
_OSM_TIMEOUTS = {"connect": 8, "read": 15, "retries": 1, "retry_delay": 1}
_NOMINATIM_TIMEOUTS = {"connect": 8, "read": 12, "retries": 1, "retry_delay": 2}
_OSRM_TIMEOUTS = {"connect": 5, "read": 15, "retries": 1, "retry_delay": 1}
_WEATHER_TIMEOUTS = {"connect": 8, "read": 20, "retries": 1, "retry_delay": 1}


def _load_geocode_cache():
    try:
        if os.path.exists(_GEOCODE_CACHE_FILE):
            with open(_GEOCODE_CACHE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                _GEOCODE_CACHE = {k: tuple(v) if v else None for k, v in raw.items()}
    except Exception as e:
        print(f"Failed to load geocode cache: {e}")


def _save_geocode_cache():
    try:
        with open(_GEOCODE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({k: list(v) if v else None for k, v in _GEOCODE_CACHE.items()}, f, ensure_ascii=False)
    except Exception as e:
        print(f"Failed to save geocode cache: {e}")


_load_geocode_cache()


def _cached_geocode(key: str, q: str) -> Optional[Tuple[float, float]]:
    """Rate-limited, cached geocode lookup via Nominatim with short timeouts and one retry."""
    global _LAST_NOMINATIM_CALL
    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key]
    cfg = _NOMINATIM_TIMEOUTS
    base_delay = _NOMINATIM_MIN_DELAY
    for attempt in range(cfg["retries"] + 1):
        now = time.time()
        wait = base_delay - (now - _LAST_NOMINATIM_CALL)
        if wait > 0:
            time.sleep(wait)
        try:
            _LAST_NOMINATIM_CALL = time.time()
            r = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format": "json", "limit": 1},
                headers={"User-Agent": "ozmoeg-trip-planner/1.0"},
                timeout=(cfg["connect"], cfg["read"]),
            )
            if r.status_code == 429:
                print(f"Nominatim rate limited for {q}, backing off {base_delay * 2:.1f}s")
                base_delay *= 2
                continue
            r.raise_for_status()
            results = r.json()
            if results:
                result = float(results[0]["lat"]), float(results[0]["lon"])
                _GEOCODE_CACHE[key] = result
                _save_geocode_cache()
                return result
            # Empty result — cache as None so we don't retry forever
            break
        except Exception as e:
            print(f"Geocoding failed for {q}: {e}")
            base_delay *= 2
            if attempt < cfg["retries"]:
                time.sleep(cfg["retry_delay"])
    _GEOCODE_CACHE[key] = None
    _save_geocode_cache()
    return None


def geocode_place(place_name: str, city: str, country: str) -> Optional[Tuple[float, float]]:
    """Return (lat, lon) for a named place via Nominatim."""
    q = f"{place_name}, {city}, {country}"
    return _cached_geocode(q, q)


def geocode_city(city: str, country: str) -> Optional[Tuple[float, float]]:
    """Return (lat, lon) for a city via Nominatim, falling back to hard-coded city centers."""
    lookup = city.lower()
    if lookup in _CITY_CENTERS:
        return _CITY_CENTERS[lookup]
    q = f"{city}, {country}"
    return _cached_geocode(q, q)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _format_distance(distance_m: float, duration_s: float = None) -> str:
    km = distance_m / 1000.0
    if km >= 10:
        text = f"~{int(round(km))} km"
    elif km >= 1:
        text = f"~{km:.1f} km"
    else:
        text = f"~{int(round(distance_m))} m"
    if duration_s is not None:
        minutes = int(round(duration_s / 60.0))
        hours = minutes // 60
        rem = minutes % 60
        if hours > 0:
            text += f" ({hours}h {rem}min drive)"
        else:
            text += f" ({minutes}min drive)"
    return text


def fetch_osrm_distances(origin: Tuple[float, float], destinations: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Return [(distance_m, duration_s), ...] from origin to each destination via OSRM table API.
    Uses short timeouts so OSRM cannot block the whole trip."""
    if not destinations:
        return []
    cfg = _OSRM_TIMEOUTS
    coords = ";".join([f"{lon},{lat}" for lat, lon in [origin] + destinations])
    url = f"http://router.project-osrm.org/table/v1/driving/{coords}"
    for attempt in range(cfg["retries"] + 1):
        try:
            r = requests.get(
                url,
                params={"sources": "0", "destinations": ";".join(str(i) for i in range(1, len(destinations) + 1)), "annotations": "distance,duration"},
                timeout=(cfg["connect"], cfg["read"]),
            )
            r.raise_for_status()
            data = r.json()
            if data.get("code") != "Ok":
                return []
            distances = data.get("distances", [[]])
            durations = data.get("durations", [[]])
            out = []
            for i in range(len(destinations)):
                d = distances[0][i] if distances and len(distances[0]) > i else None
                t = durations[0][i] if durations and len(durations[0]) > i else None
                if d is None or t is None:
                    out.append((None, None))
                else:
                    out.append((float(d), float(t)))
            return out
        except Exception as e:
            print(f"OSRM table failed (attempt {attempt+1}): {e}")
            if attempt < cfg["retries"]:
                time.sleep(cfg["retry_delay"])
    return []


def fetch_weather(lat: float, lon: float, start_date: str, end_date: str) -> List[Dict]:
    """Fetch daily weather from Open-Meteo. Merges forecast (available range) with climate ensemble normals for any remaining days."""
    from datetime import date
    today = date.today().isoformat()
    today_dt = datetime.strptime(today, "%Y-%m-%d").date()
    forecast_limit_dt = today_dt + timedelta(days=15)  # Open-Meteo forecast API accepts up to ~16 days inclusive
    forecast_limit = forecast_limit_dt.isoformat()
    safe_forecast_end_dt = today_dt + timedelta(days=14)
    safe_forecast_end = safe_forecast_end_dt.isoformat()

    def _parse_range(s, e):
        return datetime.strptime(s, "%Y-%m-%d").date(), datetime.strptime(e, "%Y-%m-%d").date()

    def _fmt(d):
        return d.isoformat()

    def _build(resp, code_key="weathercode"):
        data = resp.get("daily", {})
        times = data.get("time", [])
        if not times:
            return {}
        model_keys = [k for k in data.keys() if k.startswith("temperature_2m_max_") and k != "temperature_2m_max"]
        first_model = model_keys[0].replace("temperature_2m_max_", "") if model_keys else ""
        max_key = f"temperature_2m_max_{first_model}" if first_model and f"temperature_2m_max_{first_model}" in data else "temperature_2m_max"
        min_key = f"temperature_2m_min_{first_model}" if first_model and f"temperature_2m_min_{first_model}" in data else "temperature_2m_min"
        precip_keys = [k for k in data.keys() if k.startswith("precipitation_sum_")]
        precip_key = precip_keys[0] if precip_keys else ("precipitation_probability_max" if "precipitation_probability_max" in data else "precipitation_sum")
        codes = data.get(code_key, [])
        out = {}
        for i, d in enumerate(times):
            out[d] = {
                "date": d,
                "max_temp": data.get(max_key, [])[i] if i < len(data.get(max_key, [])) else None,
                "min_temp": data.get(min_key, [])[i] if i < len(data.get(min_key, [])) else None,
                "precip_prob": data.get(precip_key, [])[i] if i < len(data.get(precip_key, [])) else 0,
                "weather_code": codes[i] if i < len(codes) else None,
            }
        return out

    def _range_dates(s, e):
        sdt = datetime.strptime(s, "%Y-%m-%d").date()
        edt = datetime.strptime(e, "%Y-%m-%d").date()
        days = []
        while sdt <= edt:
            days.append(sdt.isoformat())
            sdt += timedelta(days=1)
        return days

    try:
        result = {}
        s_dt, e_dt = _parse_range(start_date, end_date)
        cfg = _WEATHER_TIMEOUTS

        if s_dt > e_dt:
            return []

        if end_date < today:
            url = "https://archive-api.open-meteo.com/v1/archive"
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum",
                "timezone": "auto",
            }
            r = requests.get(url, params=params, timeout=(cfg["connect"], cfg["read"]))
            r.raise_for_status()
            result.update(_build(r.json()))
        elif start_date <= forecast_limit:
            # Some or all requested dates are within the forecast window.
            fc_end_dt = min(e_dt, safe_forecast_end_dt)
            fc_end = _fmt(fc_end_dt)
            url = "https://api.open-meteo.com/v1/forecast"
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": fc_end,
                "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max",
                "timezone": "auto",
            }
            r = requests.get(url, params=params, timeout=(cfg["connect"], cfg["read"]))
            r.raise_for_status()
            result.update(_build(r.json()))
            if fc_end_dt < e_dt:
                # Fetch remaining days from climate normals.
                rem_start = _fmt(fc_end_dt + timedelta(days=1))
                url = "https://climate-api.open-meteo.com/v1/climate"
                params = {
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": rem_start,
                    "end_date": end_date,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "models": "CMCC_CM2_VHR4,FGOALS_f3_H,HiRAM_SIT_HR,MRI_AGCM3_2_S,EC_Earth3P_HR,MPI_ESM1_2_XR,NICAM16_8S",
                    "timezone": "auto",
                }
                r = requests.get(url, params=params, timeout=(cfg["connect"], cfg["read"]))
                r.raise_for_status()
                result.update(_build(r.json(), code_key=""))
        else:
            # Entire range is beyond the forecast window: use climate normals.
            url = "https://climate-api.open-meteo.com/v1/climate"
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": start_date,
                "end_date": end_date,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                "models": "CMCC_CM2_VHR4,FGOALS_f3_H,HiRAM_SIT_HR,MRI_AGCM3_2_S,EC_Earth3P_HR,MPI_ESM1_2_XR,NICAM16_8S",
                "timezone": "auto",
            }
            r = requests.get(url, params=params, timeout=(cfg["connect"], cfg["read"]))
            r.raise_for_status()
            result.update(_build(r.json(), code_key=""))

        # Return the requested range in order, filling missing days with a placeholder.
        days = []
        for d in _range_dates(start_date, end_date):
            if d in result:
                days.append(result[d])
            else:
                days.append({
                    "date": d,
                    "max_temp": None,
                    "min_temp": None,
                    "precip_prob": 0,
                    "weather_code": None,
                })
        return days
    except Exception as e:
        print(f"Weather fetch failed: {e}")
        return []


def weather_code_to_text(code: Optional[int], precip_prob: float) -> str:
    """Convert WMO weather code to human-readable text."""
    mapping = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    desc = mapping.get(code or 0, "Variable")
    if precip_prob > 50:
        desc += f"; rain likely ({int(precip_prob)}%)"
    return desc


def enrich_place(place: Dict, interests: List[str], ages: List[int], city: str = "") -> Dict:
    """Tag interest match, family suitability and city for a place."""
    tags = [t.lower() for t in place.get("tags", [])]
    interests_l = [i.lower() for i in (interests or [])]
    place["interest_match"] = any(t in interests_l for t in tags)
    ages = ages or []
    place["kid_friendly"] = place.get("kid_friendly", all(a is None or a >= 6 for a in ages))
    if not place.get("city"):
        place["city"] = city
    return place


def fetch_places(city: str, country: str, kind: str, interests: List[str] = None,
                 ages: List[int] = None, limit: int = 20,
                 latlon: Optional[Tuple[float, float]] = None) -> List[Dict]:
    """Return curated or live points of interest for a city.
    Order of preference:
      1. Built-in curated lists for major cities (use these first to avoid live latency).
      2. Local curated fallback JSON.
      3. OpenStreetMap only if curated data is too short (best effort; never fail).
    """
    places = _builtin_city_places(city, country, kind, limit)
    if places:
        return [enrich_place(p, interests, ages, city) for p in places[:limit]]

    places = load_fallback(country, city, kind)
    if not places:
        places = load_fallback("generic", city, kind)
    if len(places) >= 5:
        return [enrich_place(p, interests, ages, city) for p in places[:limit]]

    # If curated list is short, supplement with live OSM (best-effort; never crash generation).
    osm = []
    try:
        if latlon is None:
            latlon = geocode_city(city, country)
        if latlon:
            osm = _osm_places(city, country, kind, limit, latlon=latlon)
    except Exception as e:
        print(f"OSM place fetch failed for {city}/{kind}: {e}")

    combined = places + osm
    if combined:
        return [enrich_place(p, interests, ages, city) for p in combined[:limit]]

    # If everything else failed, return a generic safe placeholder so the sheet still builds.
    return [enrich_place(p, interests, ages, city) for p in _generic_placeholders(city, kind)[:limit]]


def _generic_placeholders(city: str, kind: str) -> List[Dict]:
    """Last-resort human-readable placeholders so the workbook always builds."""
    if kind == "attractions":
        return [{"name": f"Explore {city} city centre", "tags": ["sightseeing"]},
                {"name": f"Walking tour of {city}", "tags": ["history & culture", "photography"]}]
    if kind == "museums":
        return [{"name": f"{city} main museum", "tags": ["museums & art", "history & culture"]},
                {"name": f"Local gallery in {city}", "tags": ["museums & art", "photography"]}]
    if kind == "markets":
        return [{"name": f"{city} central market", "tags": ["local markets", "shopping"]},
                {"name": f"{city} craft market", "tags": ["local markets", "shopping"]}]
    if kind == "food":
        return [{"name": f"Local restaurant in {city}", "tags": ["local cuisine", "dinner"], "best_time": ["evening"]},
                {"name": f"Café in {city}", "tags": ["coffee & cafés"], "best_time": ["morning"]}]
    if kind == "neighborhoods":
        return [{"name": f"{city} old town", "tags": ["history & culture", "architecture"]},
                {"name": f"{city} downtown", "tags": ["shopping", "food & drink"]}]
    if kind == "day_trips":
        return [{"name": f"Day trip from {city}", "tags": ["nature & wildlife", "photography"]},
                {"name": f"Scenic drive near {city}", "tags": ["hiking & adventure", "photography"]}]
    return []


def _builtin_city_places(city: str, country: str, kind: str, limit: int = 30) -> List[Dict]:
    """Hard-coded high-quality fallback lists for popular cities."""
    city = city.lower()
    places = {
        "melbourne": {
            "attractions": [
                {"name": "Federation Square", "tags": ["history & culture", "architecture", "photography"]},
                {"name": "Royal Botanic Gardens", "tags": ["parks & outdoors", "nature & wildlife"]},
                {"name": "Melbourne Cricket Ground (MCG)", "tags": ["sports", "history & culture"]},
                {"name": "Eureka Skydeck 88", "tags": ["photography", "architecture", "views"]},
                {"name": "Queen Victoria Market", "tags": ["local markets", "food & drink", "shopping"]},
                {"name": "St Kilda Beach", "tags": ["parks & outdoors", "beach"]},
                {"name": "Flinders Street Station", "tags": ["architecture", "history & culture"]},
                {"name": "Laneways Street Art", "tags": ["art galleries", "photography", "culture"]},
                {"name": "Melbourne Zoo", "tags": ["nature & wildlife", "kids friendly"]},
                {"name": "Southbank Promenade", "tags": ["parks & outdoors", "food & drink"]},
            ],
            "museums": [
                {"name": "National Gallery of Victoria (NGV)", "tags": ["museums & art", "art galleries"]},
                {"name": "Melbourne Museum", "tags": ["museums & art", "history & culture"]},
                {"name": "ACMI (Australian Centre for the Moving Image)", "tags": ["museums & art", "technology", "pop culture"]},
                {"name": "Scienceworks", "tags": ["museums & art", "technology", "kids friendly"]},
                {"name": "Old Melbourne Gaol", "tags": ["history & culture", "museums & art"]},
            ],
            "markets": [
                {"name": "Queen Victoria Market", "tags": ["local markets", "food & drink"]},
                {"name": "South Melbourne Market", "tags": ["local markets", "food & drink"]},
                {"name": "Prahran Market", "tags": ["local markets", "food & drink"]},
            ],
            "food": [
                {"name": "Chin Chin", "tags": ["seafood", "asian", "dinner"], "best_time": ["evening"]},
                {"name": "Attica", "tags": ["fine dining", "modern australian", "dinner"], "best_time": ["evening"]},
                {"name": "Higher Ground", "tags": ["coffee & cafés", "breakfast"], "best_time": ["morning"]},
                {"name": "Seven Seeds Coffee", "tags": ["coffee & cafés"], "best_time": ["morning", "afternoon"]},
                {"name": "Lune Croissanterie", "tags": ["sweets & desserts", "coffee & cafés"], "best_time": ["morning"]},
                {"name": "Max on Hardware", "tags": ["italian", "lunch", "dinner"], "best_time": ["afternoon", "evening"]},
                {"name": "Cumulus Inc.", "tags": ["modern australian", "lunch", "dinner"], "best_time": ["afternoon", "evening"]},
                {"name": "Tipo 00", "tags": ["italian", "pasta", "dinner"], "best_time": ["evening"]},
                {"name": "Vue de Monde", "tags": ["fine dining", "views", "dinner"], "best_time": ["evening"]},
                {"name": "Stalactites", "tags": ["greek", "budget eats", "dinner"], "best_time": ["evening"]},
            ],
            "neighborhoods": [
                {"name": "Fitzroy", "tags": ["nightlife", "local markets", "art galleries"]},
                {"name": "Brunswick", "tags": ["food & drink", "coffee & cafés", "shopping"]},
                {"name": "South Yarra", "tags": ["shopping", "parks & outdoors"]},
                {"name": "Carlton", "tags": ["history & culture", "food & drink", "italian"]},
                {"name": "Docklands", "tags": ["architecture", "waterfront"]},
            ],
            "day_trips": [
                {"name": "Great Ocean Road", "tags": ["nature & wildlife", "hiking & adventure", "photography"]},
                {"name": "Phillip Island Penguin Parade", "tags": ["nature & wildlife", "kids friendly"]},
                {"name": "Yarra Valley Wine Region", "tags": ["wine & cocktails", "food & drink", "day trip"]},
                {"name": "Dandenong Ranges", "tags": ["nature & wildlife", "hiking & adventure"]},
                {"name": "Mornington Peninsula", "tags": ["beach", "wellness & spa", "food & drink"]},
            ],
            "hotels": [
                {"name": "QT Melbourne", "price": "~AUD 280", "location": "CBD", "highlights": "Boutique design hotel in the city centre"},
                {"name": "The Langham Melbourne", "price": "~AUD 320", "location": "Southbank", "highlights": "Luxury riverside hotel"},
                {"name": "Novotel Melbourne South Wharf", "price": "~AUD 210", "location": "South Wharf", "highlights": "Modern hotel near convention centre"},
            ],
        },
        "nadi": {
            "attractions": [
                {"name": "Sri Siva Subramaniya Swami Temple", "tags": ["history & culture", "architecture", "photography"], "lat": -17.8031, "lon": 177.4207},
                {"name": "Garden of the Sleeping Giant", "tags": ["parks & outdoors", "nature & wildlife", "photography"], "lat": -17.7620, "lon": 177.4496},
                {"name": "Sabinawoods Mangroves", "tags": ["nature & wildlife", "parks & outdoors", "hiking & adventure"], "lat": -17.7970, "lon": 177.4450},
                {"name": "Nadi Produce Market", "tags": ["local markets", "food & drink", "culture"], "lat": -17.8020, "lon": 177.4166},
                {"name": "Wailoaloa Beach", "tags": ["beach", "parks & outdoors", "relaxation"], "lat": -17.7790, "lon": 177.4493},
                {"name": "Denarau Marina", "tags": ["waterfront", "photography", "food & drink"], "lat": -17.7707, "lon": 177.3802},
                {"name": "Kula Eco Park", "tags": ["nature & wildlife", "kids friendly", "parks & outdoors"], "lat": -18.1225, "lon": 177.6700},
                {"name": "Viseisei Village", "tags": ["history & culture", "village", "culture"], "lat": -17.8000, "lon": 177.4350},
            ],
            "museums": [
                {"name": "Fiji Museum (Suva)", "tags": ["museums & art", "history & culture"], "lat": -18.1496, "lon": 178.4250},
                {"name": "Nadi Handicraft Market", "tags": ["museums & art", "local markets", "crafts"], "lat": -17.8020, "lon": 177.4166},
            ],
            "markets": [
                {"name": "Nadi Produce Market", "tags": ["local markets", "food & drink", "culture"], "lat": -17.8020, "lon": 177.4166},
                {"name": "Namaka Market", "tags": ["local markets", "food & drink"], "lat": -17.8060, "lon": 177.4360},
                {"name": "Denarau Handicraft Market", "tags": ["local markets", "shopping", "crafts"], "lat": -17.7690, "lon": 177.3790},
            ],
            "food": [
                {"name": "Taste Fiji Bistro", "tags": ["seafood", "local cuisine", "dinner"], "best_time": ["evening"], "lat": -17.7790, "lon": 177.4493},
                {"name": "Cardo's Steakhouse & Cocktail Bar", "tags": ["steakhouse", "fine dining", "dinner"], "best_time": ["evening"], "lat": -17.7680, "lon": 177.3800},
                {"name": "Tu's Place", "tags": ["local cuisine", "budget eats", "lunch"], "best_time": ["afternoon"], "lat": -17.8030, "lon": 177.4180},
                {"name": "Indigo Indian Asian Restaurant", "tags": ["asian", "indian", "dinner"], "best_time": ["evening"], "lat": -17.7800, "lon": 177.4480},
                {"name": "Bounty Restaurant & Bar", "tags": ["seafood", "views", "dinner"], "best_time": ["evening"], "lat": -17.7700, "lon": 177.3800},
                {"name": "Bulaccino Café", "tags": ["coffee & cafés", "breakfast"], "best_time": ["morning"], "lat": -17.8040, "lon": 177.4150},
                {"name": "Seductress", "tags": ["local cuisine", "pizza", "dinner"], "best_time": ["evening"], "lat": -17.7800, "lon": 177.4490},
            ],
            "neighborhoods": [
                {"name": "Denarau Island", "tags": ["beach", "resorts", "waterfront"], "lat": -17.7698, "lon": 177.3807},
                {"name": "Wailoaloa", "tags": ["beach", "budget eats", "nightlife"], "lat": -17.7790, "lon": 177.4493},
                {"name": "Nadi Town", "tags": ["local markets", "shopping", "culture"], "lat": -17.7765, "lon": 177.4493},
                {"name": "Martintar", "tags": ["food & drink", "nightlife", "shopping"], "lat": -17.7760, "lon": 177.4410},
            ],
            "day_trips": [
                {"name": "Mamanuca Islands Day Cruise", "tags": ["beach", "nature & wildlife", "photography", "day trip"], "lat": -17.6500, "lon": 177.1000},
                {"name": "Yasawa Islands Day Trip", "tags": ["beach", "hiking & adventure", "snorkelling", "day trip"], "lat": -16.9000, "lon": 177.3500},
                {"name": "Sabeto Mud Pools & Hot Springs", "tags": ["wellness & spa", "nature & wildlife", "day trip"], "lat": -17.7830, "lon": 177.5200},
                {"name": "Cloud 9 Floating Platform", "tags": ["beach", "waterfront", "food & drink", "day trip"], "lat": -17.7000, "lon": 177.2200},
            ],
            "hotels": [
                {"name": "Sofitel Fiji Resort & Spa", "price": "~FJD 520", "location": "Denarau Island", "highlights": "Luxury beachfront resort with lagoon pools"},
                {"name": "Hilton Fiji Beach Resort & Spa", "price": "~FJD 480", "location": "Denarau Island", "highlights": "Beachfront villas and family-friendly pools"},
                {"name": "Radisson Blu Resort Fiji", "price": "~FJD 390", "location": "Denarau Island", "highlights": "All-ages resort with water slides and spa"},
            ],
        },
        "suva": {
            "attractions": [
                {"name": "Albert Park", "tags": ["parks & outdoors", "history & culture"], "lat": -18.1491, "lon": 178.4250},
                {"name": "Thurston Gardens", "tags": ["parks & outdoors", "nature & wildlife"], "lat": -18.1485, "lon": 178.4240},
                {"name": "Colo-i-Suva Forest Park", "tags": ["nature & wildlife", "hiking & adventure", "waterfalls"], "lat": -18.1000, "lon": 178.4400},
                {"name": "Suva Municipal Market", "tags": ["local markets", "food & drink", "culture"], "lat": -18.1416, "lon": 178.4413},
                {"name": "Parliament of Fiji", "tags": ["history & culture", "architecture"], "lat": -18.1480, "lon": 178.4240},
                {"name": "Government Buildings", "tags": ["history & culture", "architecture"], "lat": -18.1485, "lon": 178.4250},
                {"name": "My Suva Picnic Park", "tags": ["parks & outdoors", "beach", "kids friendly"], "lat": -18.1300, "lon": 178.4500},
                {"name": "Sacred Heart Cathedral", "tags": ["history & culture", "architecture"], "lat": -18.1420, "lon": 178.4250},
            ],
            "museums": [
                {"name": "Fiji Museum", "tags": ["museums & art", "history & culture"], "lat": -18.1496, "lon": 178.4250},
                {"name": "National Archives of Fiji", "tags": ["museums & art", "history & culture"], "lat": -18.1480, "lon": 178.4240},
            ],
            "markets": [
                {"name": "Suva Municipal Market", "tags": ["local markets", "food & drink", "culture"], "lat": -18.1416, "lon": 178.4413},
                {"name": "MHCC Shopping Centre", "tags": ["shopping", "local markets"], "lat": -18.1420, "lon": 178.4250},
                {"name": "TappooCity Suva", "tags": ["shopping", "local markets"], "lat": -18.1400, "lon": 178.4300},
            ],
            "food": [
                {"name": "Bad Dog Café", "tags": ["coffee & cafés", "breakfast", "local cuisine"], "best_time": ["morning"], "lat": -18.1430, "lon": 178.4250},
                {"name": "Daikoku Suva", "tags": ["asian", "japanese", "dinner"], "best_time": ["evening"], "lat": -18.1420, "lon": 178.4240},
                {"name": "Governors Museum Restaurant", "tags": ["local cuisine", "history & culture", "dinner"], "best_time": ["evening"], "lat": -18.1480, "lon": 178.4250},
                {"name": "Suva Yacht Club", "tags": ["seafood", "views", "dinner"], "best_time": ["evening"], "lat": -18.1350, "lon": 178.4300},
                {"name": "Taste Fiji (Suva)", "tags": ["local cuisine", "seafood", "dinner"], "best_time": ["evening"], "lat": -18.1400, "lon": 178.4250},
                {"name": "Maya Dhaba", "tags": ["asian", "indian", "vegetarian"], "best_time": ["afternoon", "evening"], "lat": -18.1410, "lon": 178.4230},
            ],
            "neighborhoods": [
                {"name": "Suva City Centre", "tags": ["history & culture", "shopping", "food & drink"], "lat": -18.1248, "lon": 178.4501},
                {"name": "Flagstaff", "tags": ["food & drink", "nightlife", "shopping"], "lat": -18.1200, "lon": 178.4300},
                {"name": "Domain", "tags": ["parks & outdoors", "museums & art"], "lat": -18.1450, "lon": 178.4200},
                {"name": "Lami Bay", "tags": ["beach", "food & drink", "views"], "lat": -18.1100, "lon": 178.4200},
            ],
            "day_trips": [
                {"name": "Beqa Lagoon Shark Dive", "tags": ["hiking & adventure", "nature & wildlife", "day trip"], "lat": -18.4000, "lon": 178.1500},
                {"name": "Pacific Harbour Adventure", "tags": ["hiking & adventure", "nature & wildlife", "day trip"], "lat": -18.2300, "lon": 178.5000},
                {"name": "Levuka Historical Port Town", "tags": ["history & culture", "architecture", "day trip"], "lat": -17.6833, "lon": 178.8333},
            ],
            "hotels": [
                {"name": "Grand Pacific Hotel", "price": "~FJD 360", "location": "Suva Waterfront", "highlights": "Colonial-era luxury hotel on Suva Harbour"},
                {"name": "Holiday Inn Suva", "price": "~FJD 240", "location": "Waterfront", "highlights": "Modern harbour-view rooms in the city centre"},
                {"name": "Tanoa Plaza Suva", "price": "~FJD 180", "location": "Suva City", "highlights": "Central hotel near the market and nightlife"},
            ],
        },
        "cairo": {
            "attractions": [
                {"name": "Pyramids of Giza", "tags": ["history & culture", "architecture", "photography"], "best_time": ["morning"], "lat": 29.9792, "lon": 31.1342},
                {"name": "Great Sphinx", "tags": ["history & culture", "photography"], "best_time": ["morning"], "lat": 29.9753, "lon": 31.1376},
                {"name": "Cairo Tower", "tags": ["views", "photography"], "best_time": ["evening"], "lat": 30.0458, "lon": 31.2243},
                {"name": "Tahrir Square", "tags": ["history & culture"], "best_time": ["afternoon"], "lat": 30.0444, "lon": 31.2357},
                {"name": "Al-Azhar Park", "tags": ["parks & outdoors", "views"], "best_time": ["afternoon"], "lat": 30.0411, "lon": 31.2650},
                {"name": "Coptic Cairo", "tags": ["history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 30.0059, "lon": 31.2301},
                {"name": "Islamic Cairo", "tags": ["history & culture", "architecture"], "best_time": ["morning"], "lat": 30.0450, "lon": 31.2626},
                {"name": "Khan el-Khalili", "tags": ["shopping", "local markets", "history & culture"], "best_time": ["afternoon", "evening"], "lat": 30.0477, "lon": 31.2622},
                {"name": "Nilometer", "tags": ["history & culture", "architecture"], "best_time": ["morning"], "lat": 30.0067, "lon": 31.2313},
                {"name": "Manial Palace", "tags": ["history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 30.0296, "lon": 31.2245},
            ],
            "museums": [
                {"name": "Egyptian Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning"], "lat": 30.0478, "lon": 31.2336},
                {"name": "Grand Egyptian Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning"], "lat": 29.9946, "lon": 31.1204},
                {"name": "Coptic Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 30.0057, "lon": 31.2300},
                {"name": "Islamic Art Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning"], "lat": 30.0443, "lon": 31.2524},
                {"name": "Museum of Modern Egyptian Art", "tags": ["museums & art", "art galleries"], "best_time": ["afternoon"], "lat": 30.0439, "lon": 31.2247},
            ],
            "markets": [
                {"name": "Khan el-Khalili Bazaar", "tags": ["local markets", "shopping", "history & culture"], "lat": 30.0477, "lon": 31.2622},
                {"name": "Souk al-Fustat", "tags": ["local markets", "shopping", "crafts"], "lat": 30.0120, "lon": 31.2308},
                {"name": "Wekalet el-Balah", "tags": ["local markets", "shopping"], "lat": 30.0450, "lon": 31.2500},
                {"name": "Friday Market", "tags": ["local markets", "shopping"], "lat": 30.0500, "lon": 31.2400},
            ],
            "food": [
                {"name": "Abou Tarek", "tags": ["local cuisine", "koshari", "budget eats"], "best_time": ["afternoon", "evening"], "lat": 30.0445, "lon": 31.2387},
                {"name": "Felfela", "tags": ["local cuisine", "vegetarian", "budget eats"], "best_time": ["afternoon", "evening"], "lat": 30.0450, "lon": 31.2600},
                {"name": "Sequoia", "tags": ["mediterranean", "nile view", "dinner"], "best_time": ["evening"], "lat": 30.0430, "lon": 31.2220},
                {"name": "Kebdet El Prince", "tags": ["local cuisine", "meat", "dinner"], "best_time": ["evening"], "lat": 30.0454, "lon": 31.2589},
                {"name": "Naguib Mahfouz Café", "tags": ["coffee & cafés", "tea", "local cuisine"], "best_time": ["afternoon"], "lat": 30.0478, "lon": 31.2618},
                {"name": "La Bodega", "tags": ["international", "dinner"], "best_time": ["evening"], "lat": 30.0570, "lon": 31.2140},
                {"name": "Maison Thomas", "tags": ["italian", "pizza", "dinner"], "best_time": ["evening"], "lat": 30.0570, "lon": 31.2000},
                {"name": "Crimson Bar", "tags": ["wine & cocktails", "views"], "best_time": ["evening"], "lat": 30.0415, "lon": 31.2240},
            ],
            "neighborhoods": [
                {"name": "Islamic Cairo", "tags": ["history & culture", "architecture", "local markets"], "lat": 30.0450, "lon": 31.2626},
                {"name": "Coptic Cairo", "tags": ["history & culture", "architecture"], "lat": 30.0059, "lon": 31.2301},
                {"name": "Zamalek", "tags": ["shopping", "food & drink", "nightlife"], "lat": 30.0580, "lon": 31.2180},
                {"name": "Garden City", "tags": ["history & culture", "architecture"], "lat": 30.0380, "lon": 31.2200},
                {"name": "Maadi", "tags": ["parks & outdoors", "food & drink", "nile"], "lat": 29.9600, "lon": 31.2580},
            ],
            "day_trips": [
                {"name": "Saqqara Necropolis", "tags": ["history & culture", "architecture"], "best_time": ["morning"], "lat": 29.8710, "lon": 31.2165},
                {"name": "Memphis Ancient City", "tags": ["history & culture", "architecture"], "best_time": ["morning"], "lat": 29.8490, "lon": 31.2550},
                {"name": "Dahshur Pyramids", "tags": ["history & culture", "architecture"], "best_time": ["morning"], "lat": 29.8060, "lon": 31.7440},
                {"name": "Alexandria Day Trip", "tags": ["history & culture", "beach", "mediterranean"], "lat": 31.2001, "lon": 29.9187},
                {"name": "Wadi Natrun Monasteries", "tags": ["history & culture", "architecture"], "lat": 30.4020, "lon": 30.2880},
            ],
            "hotels": [
                {"name": "Four Seasons Nile Plaza", "price": "~USD 350", "location": "Garden City", "highlights": "Luxury hotel on the Nile"},
                {"name": "Marriott Mena House", "price": "~USD 280", "location": "Giza", "highlights": "Historic hotel with pyramid views"},
                {"name": "Sofitel Cairo El Gezirah", "price": "~USD 220", "location": "Zamalek", "highlights": "Nile-side luxury on Gezira Island"},
            ],
        },
        "alexandria": {
            "attractions": [
                {"name": "Bibliotheca Alexandrina", "tags": ["history & culture", "architecture", "museums & art"], "best_time": ["morning", "afternoon"], "lat": 31.2089, "lon": 29.9092},
                {"name": "Citadel of Qaitbay", "tags": ["history & culture", "architecture", "views"], "best_time": ["morning"], "lat": 31.2140, "lon": 29.8856},
                {"name": "Montaza Palace", "tags": ["parks & outdoors", "history & culture", "views"], "best_time": ["afternoon"], "lat": 31.2876, "lon": 30.0173},
                {"name": "Stanley Bridge", "tags": ["architecture", "photography"], "best_time": ["evening"], "lat": 31.2396, "lon": 29.9630},
                {"name": "Corniche Waterfront", "tags": ["parks & outdoors", "views", "photography"], "best_time": ["evening"], "lat": 31.2014, "lon": 29.9107},
                {"name": "Pompey's Pillar", "tags": ["history & culture", "architecture"], "best_time": ["morning"], "lat": 31.1824, "lon": 29.8943},
                {"name": "Catacombs of Kom El Shoqafa", "tags": ["history & culture", "museums & art"], "best_time": ["morning", "afternoon"], "lat": 31.1784, "lon": 29.8920},
                {"name": "Alexandria National Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 31.1995, "lon": 29.9020},
            ],
            "museums": [
                {"name": "Bibliotheca Alexandrina Antiquities Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 31.2089, "lon": 29.9092},
                {"name": "Alexandria National Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 31.1995, "lon": 29.9020},
                {"name": "Royal Jewelry Museum", "tags": ["museums & art", "history & culture"], "best_time": ["afternoon"], "lat": 31.2336, "lon": 29.9604},
            ],
            "markets": [
                {"name": "Attarine Market", "tags": ["local markets", "shopping", "history & culture"], "lat": 31.1990, "lon": 29.9050},
                {"name": "Mansheya Market", "tags": ["local markets", "shopping"], "lat": 31.1980, "lon": 29.8950},
                {"name": "Bahary Fish Market", "tags": ["local markets", "food & drink", "seafood"], "lat": 31.2040, "lon": 29.8770},
            ],
            "food": [
                {"name": "TCC (The Greek Club)", "tags": ["seafood", "mediterranean", "views"], "best_time": ["evening"], "lat": 31.1980, "lon": 29.8880},
                {"name": "Farag", "tags": ["seafood", "local cuisine", "dinner"], "best_time": ["evening"], "lat": 31.2000, "lon": 29.8800},
                {"name": "Mohamed Ahmed Koshary", "tags": ["local cuisine", "koshari", "budget eats"], "best_time": ["afternoon", "evening"], "lat": 31.1990, "lon": 29.8900},
                {"name": "Délices", "tags": ["local cuisine", "pastry", "coffee & cafés"], "best_time": ["morning", "afternoon"], "lat": 31.2005, "lon": 29.9100},
                {"name": "Chez Gaby", "tags": ["italian", "pizza", "dinner"], "best_time": ["evening"], "lat": 31.1970, "lon": 29.8900},
                {"name": "Hanafi", "tags": ["local cuisine", "seafood", "dinner"], "best_time": ["evening"], "lat": 31.2000, "lon": 29.8780},
            ],
            "neighborhoods": [
                {"name": "Glymada", "tags": ["beach", "food & drink", "nightlife"], "lat": 31.2410, "lon": 29.9670},
                {"name": "Sidi Gaber", "tags": ["history & culture", "food & drink"], "lat": 31.2180, "lon": 29.9420},
                {"name": "Mansheya", "tags": ["local markets", "shopping", "history & culture"], "lat": 31.1980, "lon": 29.8940},
                {"name": "Moharam Bek", "tags": ["history & culture", "local markets"], "lat": 31.1900, "lon": 29.9100},
                {"name": "Montaza", "tags": ["parks & outdoors", "beach", "views"], "lat": 31.2876, "lon": 30.0173},
            ],
            "day_trips": [
                {"name": "El Alamein World War II Memorials", "tags": ["history & culture", "day trip"], "lat": 30.8197, "lon": 28.9497},
                {"name": "Abu Mena Monastery", "tags": ["history & culture", "architecture"], "lat": 31.1936, "lon": 29.6553},
                {"name": "Maamoura Beach", "tags": ["beach", "parks & outdoors"], "lat": 31.2764, "lon": 30.0240},
                {"name": "Borg El Arab", "tags": ["history & culture", "local markets"], "lat": 30.8580, "lon": 29.5737},
            ],
            "hotels": [
                {"name": "Four Seasons Alexandria", "price": "~USD 280", "location": "San Stefano", "highlights": "Seafront luxury in San Stefano"},
                {"name": "Hilton Alexandria Corniche", "price": "~USD 150", "location": "Corniche", "highlights": "Waterfront hotel on the Mediterranean"},
                {"name": "Steigenberger Cecil Hotel", "price": "~USD 120", "location": "Downtown", "highlights": "Historic hotel in the city centre"},
            ],
        },
        "new york": {
            "attractions": [
                {"name": "Central Park", "tags": ["parks & outdoors", "nature & wildlife", "photography"], "best_time": ["morning", "afternoon"]},
                {"name": "Times Square", "tags": ["photography", "nightlife", "culture"], "best_time": ["evening"]},
                {"name": "Brooklyn Bridge", "tags": ["architecture", "photography", "views"], "best_time": ["morning", "evening"]},
                {"name": "Statue of Liberty", "tags": ["history & culture", "photography", "views"], "best_time": ["morning"]},
                {"name": "Empire State Building", "tags": ["architecture", "views", "photography"], "best_time": ["evening"]},
                {"name": "Top of the Rock", "tags": ["views", "architecture", "photography"], "best_time": ["evening"]},
                {"name": "High Line", "tags": ["parks & outdoors", "architecture", "photography"], "best_time": ["morning", "afternoon"]},
                {"name": "One World Observatory", "tags": ["views", "history & culture"], "best_time": ["evening"]},
                {"name": "Grand Central Terminal", "tags": ["architecture", "history & culture"], "best_time": ["morning", "afternoon"]},
                {"name": "The Vessel", "tags": ["architecture", "photography"], "best_time": ["morning", "afternoon"]},
            ],
            "museums": [
                {"name": "Metropolitan Museum of Art", "tags": ["museums & art", "art galleries", "history & culture"], "best_time": ["morning", "afternoon"]},
                {"name": "MoMA", "tags": ["museums & art", "art galleries"], "best_time": ["morning", "afternoon"]},
                {"name": "American Museum of Natural History", "tags": ["museums & art", "kids friendly", "nature & wildlife"], "best_time": ["morning", "afternoon"]},
                {"name": "Solomon R. Guggenheim Museum", "tags": ["museums & art", "art galleries", "architecture"], "best_time": ["morning", "afternoon"]},
                {"name": "Whitney Museum", "tags": ["museums & art", "art galleries"], "best_time": ["afternoon"]},
            ],
            "markets": [
                {"name": "Chelsea Market", "tags": ["local markets", "food & drink", "shopping"]},
                {"name": "Grand Central Market", "tags": ["local markets", "food & drink"]},
                {"name": "Union Square Greenmarket", "tags": ["local markets", "food & drink"]},
                {"name": "Brooklyn Flea", "tags": ["local markets", "shopping", "vintage"]},
            ],
            "food": [
                {"name": "Joe's Pizza", "tags": ["pizza", "budget eats", "lunch"], "best_time": ["afternoon", "evening"]},
                {"name": "Katz's Delicatessen", "tags": ["deli", "local cuisine", "lunch"], "best_time": ["afternoon"]},
                {"name": "Peter Luger Steak House", "tags": ["steakhouse", "dinner", "fine dining"], "best_time": ["evening"]},
                {"name": "Le Bernardin", "tags": ["seafood", "fine dining", "dinner"], "best_time": ["evening"]},
                {"name": "Xi'an Famous Foods", "tags": ["asian", "noodles", "budget eats"], "best_time": ["afternoon", "evening"]},
                {"name": "Russ & Daughters", "tags": ["jewish", "breakfast", "lunch"], "best_time": ["morning", "afternoon"]},
                {"name": "Shake Shack", "tags": ["burgers", "budget eats", "lunch"], "best_time": ["afternoon", "evening"]},
                {"name": "Eleven Madison Park", "tags": ["fine dining", "dinner"], "best_time": ["evening"]},
                {"name": "Lombardi's", "tags": ["pizza", "italian", "dinner"], "best_time": ["evening"]},
                {"name": "Balthazar", "tags": ["french", "brunch", "dinner"], "best_time": ["morning", "evening"]},
            ],
            "neighborhoods": [
                {"name": "Manhattan", "tags": ["shopping", "nightlife", "museums"]},
                {"name": "Brooklyn", "tags": ["food & drink", "photography", "nightlife"]},
                {"name": "Greenwich Village", "tags": ["history & culture", "food & drink", "nightlife"]},
                {"name": "SoHo", "tags": ["shopping", "art galleries", "architecture"]},
                {"name": "Williamsburg", "tags": ["nightlife", "food & drink", "views"]},
            ],
            "day_trips": [
                {"name": "Niagara Falls Day Trip", "tags": ["nature & wildlife", "photography"]},
                {"name": "Hudson Valley", "tags": ["nature & wildlife", "wineries", "hiking & adventure"]},
                {"name": "Fire Island", "tags": ["beach", "parks & outdoors"]},
                {"name": "Princeton University", "tags": ["history & culture", "architecture"]},
                {"name": "Long Island Wineries", "tags": ["wine & cocktails", "food & drink"]},
            ],
            "hotels": [
                {"name": "The Plaza", "price": "~USD 480", "location": "Midtown", "highlights": "Iconic Fifth Avenue hotel"},
                {"name": "The Standard High Line", "price": "~USD 320", "location": "Meatpacking District", "highlights": "Modern hotel on the High Line"},
                {"name": "Arlo NoMad", "price": "~USD 200", "location": "NoMad", "highlights": "Boutique hotel near Empire State Building"},
            ],
        },
        "kuala lumpur": {
            "attractions": [
                {"name": "Petronas Towers", "tags": ["architecture", "photography", "views"], "best_time": ["morning", "evening"], "lat": 3.1583, "lon": 101.7118},
                {"name": "Batu Caves", "tags": ["history & culture", "nature & wildlife", "hiking & adventure"], "best_time": ["morning"], "lat": 3.2379, "lon": 101.6831},
                {"name": "KL Tower", "tags": ["views", "photography"], "best_time": ["evening"], "lat": 3.1528, "lon": 101.7038},
                {"name": "Merdeka Square", "tags": ["history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 3.1478, "lon": 101.6934},
                {"name": "Perdana Botanical Gardens", "tags": ["parks & outdoors", "nature & wildlife"], "best_time": ["morning", "afternoon"], "lat": 3.1440, "lon": 101.6860},
                {"name": "National Mosque", "tags": ["history & culture", "architecture", "photography"], "best_time": ["morning"], "lat": 3.1421, "lon": 101.6897},
                {"name": "Central Market Kuala Lumpur", "tags": ["local markets", "shopping", "history & culture"], "best_time": ["afternoon"], "lat": 3.1458, "lon": 101.6966},
                {"name": "Chinatown Petaling Street", "tags": ["local markets", "food & drink", "history & culture"], "best_time": ["afternoon", "evening"], "lat": 3.1446, "lon": 101.6979},
                {"name": "KL Bird Park", "tags": ["nature & wildlife", "kids friendly", "parks & outdoors"], "best_time": ["morning"], "lat": 3.1428, "lon": 101.6886},
                {"name": "Aquaria KLCC", "tags": ["nature & wildlife", "kids friendly"], "best_time": ["afternoon"], "lat": 3.1536, "lon": 101.7135},
            ],
            "museums": [
                {"name": "Islamic Arts Museum Malaysia", "tags": ["museums & art", "history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 3.1415, "lon": 101.6912},
                {"name": "National Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning"], "lat": 3.1378, "lon": 101.6871},
                {"name": "Royal Selangor Visitor Centre", "tags": ["museums & art", "shopping", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 3.1995, "lon": 101.7130},
                {"name": "National Textiles Museum", "tags": ["museums & art", "history & culture"], "best_time": ["afternoon"], "lat": 3.1475, "lon": 101.6930},
            ],
            "markets": [
                {"name": "Central Market Kuala Lumpur", "tags": ["local markets", "shopping", "crafts"], "lat": 3.1458, "lon": 101.6966},
                {"name": "Pasar Malam Taman Connaught", "tags": ["local markets", "food & drink", "nightlife"], "lat": 3.0825, "lon": 101.7453},
                {"name": "Bangsar Sunday Night Market", "tags": ["local markets", "food & drink"], "lat": 3.1300, "lon": 101.6710},
                {"name": "Kasturi Walk", "tags": ["local markets", "food & drink", "shopping"], "lat": 3.1450, "lon": 101.6970},
            ],
            "food": [
                {"name": "Jalan Alor Night Food Court", "tags": ["local cuisine", "street food", "dinner"], "best_time": ["evening"], "lat": 3.1442, "lon": 101.7160},
                {"name": "Lot 10 Hutong", "tags": ["asian", "local cuisine", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 3.1475, "lon": 101.7117},
                {"name": "Din Tai Fung Pavilion KL", "tags": ["asian", "chinese", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 3.1490, "lon": 101.7130},
                {"name": "Madam Kwan's", "tags": ["local cuisine", "malaysian", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 3.1490, "lon": 101.7125},
                {"name": "Bijan Bar & Restaurant", "tags": ["local cuisine", "fine dining", "dinner"], "best_time": ["evening"], "lat": 3.1480, "lon": 101.7100},
                {"name": "VCR Café", "tags": ["coffee & cafés", "breakfast", "sweets & desserts"], "best_time": ["morning"], "lat": 3.1465, "lon": 101.6995},
                {"name": "Canopy Rooftop Bar & Lounge", "tags": ["wine & cocktails", "views", "evening"], "best_time": ["evening"], "lat": 3.1560, "lon": 101.7105},
                {"name": "Arabic Gate Restaurant", "tags": ["halal", "middle eastern", "dinner"], "best_time": ["evening"], "lat": 3.1580, "lon": 101.7070},
            ],
            "neighborhoods": [
                {"name": "KLCC", "tags": ["shopping", "architecture", "food & drink"], "lat": 3.1583, "lon": 101.7118},
                {"name": "Bukit Bintang", "tags": ["shopping", "nightlife", "food & drink"], "lat": 3.1472, "lon": 101.7115},
                {"name": "Chinatown", "tags": ["history & culture", "local markets", "food & drink"], "lat": 3.1446, "lon": 101.6979},
                {"name": "Bangsar", "tags": ["food & drink", "nightlife", "shopping"], "lat": 3.1300, "lon": 101.6710},
                {"name": "Mont Kiara", "tags": ["food & drink", "shopping", "international"], "lat": 3.1710, "lon": 101.6540},
            ],
            "day_trips": [
                {"name": "Genting Highlands Day Trip", "tags": ["nature & wildlife", "theme parks", "views", "day trip"], "lat": 3.4239, "lon": 101.7933},
                {"name": "Kuala Selangor Fireflies", "tags": ["nature & wildlife", "photography", "day trip"], "lat": 3.3520, "lon": 101.2500},
                {"name": "Bukit Tinggi French Village", "tags": ["history & culture", "architecture", "photography", "day trip"], "lat": 3.4000, "lon": 101.8333},
                {"name": "Templer Park Rainforest", "tags": ["nature & wildlife", "hiking & adventure", "day trip"], "lat": 3.2850, "lon": 101.6330},
            ],
            "hotels": [
                {"name": "Mandarin Oriental Kuala Lumpur", "price": "~MYR 1,200", "location": "KLCC", "highlights": "Luxury hotel with Petronas Tower views"},
                {"name": "Grand Hyatt Kuala Lumpur", "price": "~MYR 950", "location": "KLCC", "highlights": "Sky lobby and floor-to-ceiling city views"},
                {"name": "Traders Hotel Kuala Lumpur", "price": "~MYR 650", "location": "KLCC", "highlights": "Rooftop SkyBar facing the Petronas Towers"},
            ],
        },
        "penang": {
            "attractions": [
                {"name": "George Town Street Art", "tags": ["art galleries", "photography", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 5.4142, "lon": 100.3288},
                {"name": "Kek Lok Si Temple", "tags": ["history & culture", "architecture", "photography"], "best_time": ["morning"], "lat": 5.3995, "lon": 100.2736},
                {"name": "Penang Hill", "tags": ["nature & wildlife", "views", "photography"], "best_time": ["morning"], "lat": 5.4160, "lon": 100.2700},
                {"name": "Chew Jetty", "tags": ["history & culture", "architecture", "photography"], "best_time": ["afternoon"], "lat": 5.4100, "lon": 100.3380},
                {"name": "Fort Cornwallis", "tags": ["history & culture", "architecture"], "best_time": ["morning"], "lat": 5.4200, "lon": 100.3410},
                {"name": "Penang Botanic Gardens", "tags": ["parks & outdoors", "nature & wildlife"], "best_time": ["morning"], "lat": 5.4380, "lon": 100.2900},
                {"name": "Clan Jetties of Penang", "tags": ["history & culture", "waterfront", "photography"], "best_time": ["afternoon"], "lat": 5.4100, "lon": 100.3380},
                {"name": "Entopia by Penang Butterfly Farm", "tags": ["nature & wildlife", "kids friendly", "parks & outdoors"], "best_time": ["morning", "afternoon"], "lat": 5.4660, "lon": 100.2150},
            ],
            "museums": [
                {"name": "Penang State Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 5.4200, "lon": 100.3330},
                {"name": "Peranakan Mansion", "tags": ["museums & art", "history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 5.4145, "lon": 100.3350},
                {"name": "Made in Penang Interactive Museum", "tags": ["museums & art", "photography", "kids friendly"], "best_time": ["afternoon"], "lat": 5.4140, "lon": 100.3300},
                {"name": "Dark Mansion Museum", "tags": ["museums & art", "photography", "kids friendly"], "best_time": ["afternoon"], "lat": 5.4160, "lon": 100.3290},
            ],
            "markets": [
                {"name": "Chowrasta Market", "tags": ["local markets", "food & drink", "culture"], "lat": 5.4150, "lon": 100.3310},
                {"name": "Pulau Tikus Market", "tags": ["local markets", "food & drink"], "lat": 5.4320, "lon": 100.3170},
                {"name": "Pasar Malam Pantai Jerjak", "tags": ["local markets", "food & drink", "nightlife"], "lat": 5.3400, "lon": 100.2900},
                {"name": "Gurney Plaza", "tags": ["shopping", "food & drink"], "lat": 5.4370, "lon": 100.3090},
            ],
            "food": [
                {"name": "Gurney Drive Hawker Centre", "tags": ["local cuisine", "street food", "dinner"], "best_time": ["evening"], "lat": 5.4380, "lon": 100.3100},
                {"name": "Tek Sen Restaurant", "tags": ["local cuisine", "chinese", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 5.4130, "lon": 100.3330},
                {"name": "Joo Hooi Café", "tags": ["local cuisine", "dessert", "coffee & cafés"], "best_time": ["afternoon"], "lat": 5.4130, "lon": 100.3335},
                {"name": "Kebaya Dining Room", "tags": ["local cuisine", "fine dining", "dinner"], "best_time": ["evening"], "lat": 5.4145, "lon": 100.3350},
                {"name": "Suffolk House Restaurant", "tags": ["local cuisine", "colonial", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 5.4200, "lon": 100.3000},
                {"name": "China House", "tags": ["sweets & desserts", "coffee & cafés", "art galleries"], "best_time": ["morning", "afternoon"], "lat": 5.4140, "lon": 100.3330},
                {"name": "The Mangii Fissino", "tags": ["seafood", "italian", "dinner"], "best_time": ["evening"], "lat": 5.4350, "lon": 100.3100},
            ],
            "neighborhoods": [
                {"name": "George Town", "tags": ["history & culture", "street art", "food & drink"], "lat": 5.4142, "lon": 100.3288},
                {"name": "Gurney Drive", "tags": ["food & drink", "beach", "views"], "lat": 5.4380, "lon": 100.3100},
                {"name": "Batu Ferringhi", "tags": ["beach", "nightlife", "food & drink"], "lat": 5.4760, "lon": 100.2460},
                {"name": "Tanjung Bungah", "tags": ["beach", "food & drink", "views"], "lat": 5.4600, "lon": 100.2800},
            ],
            "day_trips": [
                {"name": "Penang National Park", "tags": ["nature & wildlife", "hiking & adventure", "beach", "day trip"], "lat": 5.4580, "lon": 100.1900},
                {"name": "Escape Theme Park", "tags": ["kids friendly", "theme parks", "adventure", "day trip"], "lat": 5.4470, "lon": 100.2630},
                {"name": "Bukit Mertajam Recreational Forest", "tags": ["nature & wildlife", "hiking & adventure", "day trip"], "lat": 5.3650, "lon": 100.4300},
                {"name": "Balik Pulau Countryside", "tags": ["nature & wildlife", "food & drink", "day trip"], "lat": 5.3500, "lon": 100.2300},
            ],
            "hotels": [
                {"name": "Eastern & Oriental Hotel", "price": "~MYR 800", "location": "George Town", "highlights": "Historic colonial seafront hotel"},
                {"name": "G Hotel Kelawai", "price": "~MYR 500", "location": "Gurney Drive", "highlights": "Modern design hotel near Gurney Plaza"},
                {"name": "PARKROYAL Penang Resort", "price": "~MYR 650", "location": "Batu Ferringhi", "highlights": "Beachfront resort with family pools"},
            ],
        },
        "langkawi": {
            "attractions": [
                {"name": "Langkawi Sky Bridge", "tags": ["views", "nature & wildlife", "photography"], "best_time": ["morning"], "lat": 6.3670, "lon": 99.8120},
                {"name": "Pulau Payar Marine Park", "tags": ["nature & wildlife", "beach", "snorkelling", "day trip"], "best_time": ["morning", "afternoon"], "lat": 6.1000, "lon": 99.8500},
                {"name": "Underwater World Langkawi", "tags": ["nature & wildlife", "kids friendly"], "best_time": ["afternoon"], "lat": 6.2900, "lon": 99.8450},
                {"name": "Tanjung Rhu Beach", "tags": ["beach", "parks & outdoors", "photography"], "best_time": ["morning", "evening"], "lat": 6.4600, "lon": 99.8200},
                {"name": "Kilim Karst Geoforest Park", "tags": ["nature & wildlife", "hiking & adventure", "day trip"], "best_time": ["morning"], "lat": 6.4200, "lon": 99.8300},
                {"name": "Dataran Lang (Eagle Square)", "tags": ["landmark", "photography", "waterfront"], "best_time": ["morning", "evening"], "lat": 6.3200, "lon": 99.8500},
            ],
            "museums": [
                {"name": "Rice Museum (Laman Padi)", "tags": ["museums & art", "history & culture"], "best_time": ["morning"], "lat": 6.3000, "lon": 99.8200},
                {"name": "Galeria Perdana", "tags": ["museums & art", "history & culture"], "best_time": ["afternoon"], "lat": 6.3700, "lon": 99.8500},
            ],
            "markets": [
                {"name": "Langkawi Night Market", "tags": ["local markets", "food & drink", "culture"], "lat": 6.3000, "lon": 99.8500},
                {"name": "Kuah Town Duty-Free", "tags": ["shopping", "local markets"], "lat": 6.3200, "lon": 99.8500},
                {"name": "Cenang Beach Souvenir Stalls", "tags": ["local markets", "shopping", "beach"], "lat": 6.2900, "lon": 99.8500},
            ],
            "food": [
                {"name": "Scarborough Fish & Chips", "tags": ["seafood", "western", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 6.4500, "lon": 99.8100},
                {"name": "The Cliff Restaurant & Bar", "tags": ["seafood", "views", "dinner"], "best_time": ["evening"], "lat": 6.2900, "lon": 99.8500},
                {"name": "Yellow Beach Café", "tags": ["local cuisine", "western", "beach", "lunch"], "best_time": ["afternoon"], "lat": 6.2900, "lon": 99.8500},
                {"name": "Red Tomato Langkawi", "tags": ["italian", "pizza", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 6.3000, "lon": 99.8500},
                {"name": "Tide Restaurant", "tags": ["seafood", "local cuisine", "dinner"], "best_time": ["evening"], "lat": 6.3000, "lon": 99.8400},
            ],
            "neighborhoods": [
                {"name": "Kuah Town", "tags": ["shopping", "local markets", "food & drink"], "lat": 6.3200, "lon": 99.8500},
                {"name": "Pantai Cenang", "tags": ["beach", "nightlife", "food & drink"], "lat": 6.2900, "lon": 99.8500},
                {"name": "Tanjung Rhu", "tags": ["beach", "views", "luxury"], "lat": 6.4600, "lon": 99.8200},
            ],
            "day_trips": [
                {"name": "Island Hopping Langkawi", "tags": ["nature & wildlife", "beach", "snorkelling", "day trip"], "lat": 6.3500, "lon": 99.8000},
                {"name": "Mangrove River Cruise", "tags": ["nature & wildlife", "hiking & adventure", "day trip"], "lat": 6.4200, "lon": 99.8300},
                {"name": "Sunset Dinner Cruise", "tags": ["views", "food & drink", "day trip"], "lat": 6.3000, "lon": 99.8500},
            ],
            "hotels": [
                {"name": "The Datai Langkawi", "price": "~MYR 2,500", "location": "Datai Bay", "highlights": "Rainforest and beach luxury resort"},
                {"name": "Four Seasons Resort Langkawi", "price": "~MYR 1,800", "location": "Tanjung Rhu", "highlights": "Beachfront villas with Andaman Sea views"},
                {"name": "Aloft Langkawi Pantai Tengah", "price": "~MYR 500", "location": "Pantai Tengah", "highlights": "Modern resort near Cenang Beach"},
            ],
        },
        "chengdu": {
            "attractions": [
                {"name": "Chengdu Research Base of Giant Panda Breeding", "tags": ["nature & wildlife", "kids friendly", "photography"], "best_time": ["morning"], "lat": 30.7336, "lon": 104.1475},
                {"name": "Jinli Ancient Street", "tags": ["history & culture", "local markets", "food & drink"], "best_time": ["afternoon", "evening"], "lat": 30.6453, "lon": 104.0492},
                {"name": "Wuhou Shrine", "tags": ["history & culture", "architecture", "photography"], "best_time": ["morning", "afternoon"], "lat": 30.6423, "lon": 104.0436},
                {"name": "Du Fu Thatched Cottage", "tags": ["history & culture", "parks & outdoors", "museums & art"], "best_time": ["morning", "afternoon"], "lat": 30.6601, "lon": 104.0285},
                {"name": "Tianfu Square", "tags": ["photography", "history & culture", "shopping"], "best_time": ["evening"], "lat": 30.6574, "lon": 104.0642},
                {"name": "Wide and Narrow Alleys (Kuanzhai Xiangzi)", "tags": ["history & culture", "food & drink", "local markets"], "best_time": ["afternoon", "evening"], "lat": 30.6692, "lon": 104.0571},
                {"name": "Chengdu People's Park", "tags": ["parks & outdoors", "kids friendly", "local culture"], "best_time": ["morning", "afternoon"], "lat": 30.6626, "lon": 104.0553},
                {"name": "Anshun Bridge", "tags": ["architecture", "photography", "views"], "best_time": ["evening"], "lat": 30.6505, "lon": 104.0860},
                {"name": "Qingyang Palace (Green Ram Temple)", "tags": ["history & culture", "architecture", "temples"], "best_time": ["morning"], "lat": 30.6635, "lon": 104.0364},
                {"name": "Sichuan Science and Technology Museum", "tags": ["museums & art", "kids friendly", "technology"], "best_time": ["afternoon"], "lat": 30.6574, "lon": 104.0642},
            ],
            "museums": [
                {"name": "Jinsha Site Museum", "tags": ["museums & art", "history & culture", "archaeology"], "best_time": ["morning", "afternoon"], "lat": 30.6828, "lon": 104.0122},
                {"name": "Chengdu Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 30.6574, "lon": 104.0642},
                {"name": "Sichuan Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 30.6556, "lon": 104.0457},
                {"name": "Du Fu Thatched Cottage Museum", "tags": ["museums & art", "history & culture", "parks & outdoors"], "best_time": ["morning", "afternoon"], "lat": 30.6601, "lon": 104.0285},
                {"name": "Sichuan Opera Museum", "tags": ["museums & art", "history & culture", "performing arts"], "best_time": ["afternoon"], "lat": 30.6450, "lon": 104.0500},
            ],
            "markets": [
                {"name": "Chunxi Road Pedestrian Street", "tags": ["shopping", "local markets", "food & drink"], "lat": 30.6565, "lon": 104.0820},
                {"name": "Songxianqiao Curio Market", "tags": ["local markets", "shopping", "antiques"], "lat": 30.6680, "lon": 104.0480},
                {"name": "Wangping Antiques Market", "tags": ["local markets", "shopping", "antiques"], "lat": 30.6600, "lon": 104.0600},
                {"name": "Qingyang Market", "tags": ["local markets", "food & drink", "culture"], "lat": 30.6700, "lon": 104.0300},
            ],
            "food": [
                {"name": "Chen Mapo Tofu", "tags": ["local cuisine", "sichuan", "spicy", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 30.6600, "lon": 104.0550},
                {"name": "Dongzikou Zhangsengfen (Chuan Chuan Xiang)", "tags": ["local cuisine", "sichuan", "street food", "dinner"], "best_time": ["evening"], "lat": 30.6650, "lon": 104.0700},
                {"name": "Huanxixingzhe Hot Pot", "tags": ["local cuisine", "hot pot", "sichuan", "dinner"], "best_time": ["evening"], "lat": 30.6600, "lon": 104.0600},
                {"name": "Ma Wang Zi", "tags": ["local cuisine", "sichuan", "dinner"], "best_time": ["afternoon", "evening"], "lat": 30.6550, "lon": 104.0500},
                {"name": "Long Chao Shou (Chengdu Wontons)", "tags": ["local cuisine", "sichuan", "budget eats", "lunch"], "best_time": ["afternoon"], "lat": 30.6600, "lon": 104.0500},
                {"name": "Bashu Dazhaimen Hot Pot", "tags": ["local cuisine", "hot pot", "sichuan", "dinner"], "best_time": ["evening"], "lat": 30.6580, "lon": 104.0650},
                {"name": "Lan Kwai Fong Chengdu", "tags": ["food & drink", "nightlife", "international"], "best_time": ["evening"], "lat": 30.6505, "lon": 104.0860},
                {"name": "Tea House at People's Park", "tags": ["tea", "local culture", "breakfast"], "best_time": ["morning"], "lat": 30.6626, "lon": 104.0553},
                {"name": "Jinli Snack Street", "tags": ["local cuisine", "street food", "snacks"], "best_time": ["afternoon", "evening"], "lat": 30.6453, "lon": 104.0492},
            ],
            "neighborhoods": [
                {"name": "Tianfu New Area", "tags": ["modern architecture", "shopping", "business"], "lat": 30.6200, "lon": 104.0600},
                {"name": "Jinjiang District", "tags": ["shopping", "food & drink", "nightlife"], "lat": 30.6500, "lon": 104.0800},
                {"name": "Qingyang District", "tags": ["history & culture", "temples", "local markets"], "lat": 30.6700, "lon": 104.0400},
                {"name": "Wuhou District", "tags": ["history & culture", "food & drink", "nightlife"], "lat": 30.6400, "lon": 104.0500},
            ],
            "day_trips": [
                {"name": "Leshan Giant Buddha Day Trip", "tags": ["history & culture", "nature & wildlife", "day trip", "unesco"], "best_time": ["morning", "afternoon"], "lat": 29.5465, "lon": 103.7725},
                {"name": "Mount Qingcheng (Daoist Mountain)", "tags": ["nature & wildlife", "hiking & adventure", "history & culture", "day trip"], "best_time": ["morning"], "lat": 30.9085, "lon": 103.4958},
                {"name": "Dujiangyan Irrigation System", "tags": ["history & culture", "architecture", "day trip", "unesco"], "best_time": ["morning", "afternoon"], "lat": 31.0000, "lon": 103.6083},
                {"name": "Panda Valley", "tags": ["nature & wildlife", "kids friendly", "day trip"], "best_time": ["morning"], "lat": 30.7500, "lon": 103.6000},
            ],
            "hotels": [
                {"name": "Shangri-La Chengdu", "price": "~CNY 1,100", "location": "Jinjiang District", "highlights": "Luxury hotel overlooking Jinjiang River"},
                {"name": "The Ritz-Carlton Chengdu", "price": "~CNY 1,400", "location": "Tianfu Square", "highlights": "Five-star hotel in the city centre"},
                {"name": "Chengdu Tibet Hotel", "price": "~CNY 500", "location": "Jinniu District", "highlights": "Comfortable mid-range base near North Railway Station"},
                {"name": "Hello Chengdu Boutique Hotel", "price": "~CNY 280", "location": "Wuhou District", "highlights": "Budget-friendly boutique near Wuhou Shrine"},
            ],
        },
        "doha": {
            "attractions": [
                {"name": "Museum of Islamic Art", "tags": ["museum", "history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 25.2951, "lon": 51.5393},
                {"name": "National Museum of Qatar", "tags": ["museum", "history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 25.2866, "lon": 51.5334},
                {"name": "Souq Waqif", "tags": ["market", "shopping", "food & drink", "culture"], "best_time": ["afternoon", "evening"], "lat": 25.2868, "lon": 51.5330},
                {"name": "The Pearl-Qatar", "tags": ["marina", "shopping", "dining", "walks"], "best_time": ["afternoon", "evening"], "lat": 25.3702, "lon": 51.5495},
                {"name": "Katara Cultural Village", "tags": ["culture", "art", "beach", "food & drink"], "best_time": ["afternoon", "evening"], "lat": 25.3602, "lon": 51.5100},
                {"name": "Doha Corniche", "tags": ["walks", "views", "photography"], "best_time": ["morning", "evening"], "lat": 25.2854, "lon": 51.5300},
                {"name": "Aspire Park", "tags": ["park", "kids friendly", "nature & wildlife"], "best_time": ["morning", "afternoon"], "lat": 25.3094, "lon": 51.5056},
                {"name": "Villaggio Mall", "tags": ["shopping", "kids friendly", "entertainment"], "best_time": ["afternoon", "evening"], "lat": 25.2643, "lon": 51.4365},
                {"name": "Doha Festival City", "tags": ["shopping", "entertainment", "kids friendly"], "best_time": ["afternoon", "evening"], "lat": 25.3872, "lon": 51.4407},
                {"name": "Al Bidda Park", "tags": ["park", "walks", "views", "kids friendly"], "best_time": ["morning", "evening"], "lat": 25.2960, "lon": 51.5270},
                {"name": "Ras Abou Aboud Stadium 974", "tags": ["sports", "architecture", "views"], "best_time": ["morning", "afternoon"], "lat": 25.2865, "lon": 51.5650},
                {"name": "MIA Park", "tags": ["park", "views", "kids friendly"], "best_time": ["evening"], "lat": 25.2958, "lon": 51.5395},
            ],
            "museums": [
                {"name": "Museum of Islamic Art", "tags": ["islamic art", "antiques", "architecture"], "best_time": ["morning", "afternoon"], "lat": 25.2951, "lon": 51.5393},
                {"name": "National Museum of Qatar", "tags": ["qatari history", "desert rose"], "best_time": ["morning", "afternoon"], "lat": 25.2866, "lon": 51.5334},
                {"name": "Katara Art Centre", "tags": ["contemporary art", "culture"], "best_time": ["afternoon"], "lat": 25.3595, "lon": 51.5108},
                {"name": "Msheireb Museums", "tags": ["history", "heritage", "culture"], "best_time": ["morning", "afternoon"], "lat": 25.2886, "lon": 51.5237},
                {"name": "Fire Station: Artist in Residence", "tags": ["contemporary art", "gallery"], "best_time": ["afternoon"], "lat": 25.2810, "lon": 51.5140},
            ],
            "markets": [
                {"name": "Souq Waqif", "tags": ["souq", "spices", "textiles", "food & drink"], "best_time": ["afternoon", "evening"], "lat": 25.2868, "lon": 51.5330},
                {"name": "Gold Souq (Souq Waqif)", "tags": ["jewellery", "shopping", "gold"], "best_time": ["afternoon", "evening"], "lat": 25.2866, "lon": 51.5332},
                {"name": "Falcon Souq", "tags": ["falconry", "culture", "traditional"], "best_time": ["afternoon"], "lat": 25.2860, "lon": 51.5335},
                {"name": "The Pearl-Qatar Marina shops", "tags": ["boutiques", "dining", "marina"], "best_time": ["afternoon", "evening"], "lat": 25.3702, "lon": 51.5495},
                {"name": "City Centre Doha Mall", "tags": ["shopping", "family", "food court"], "best_time": ["afternoon", "evening"], "lat": 25.2758, "lon": 51.5260},
            ],
            "food": [
                {"name": "Majlis Al Ard", "tags": ["qatari", "lunch", "dinner"], "best_time": ["lunch", "dinner"], "lat": 25.2868, "lon": 51.5330},
                {"name": "Parisa Souq Waqif", "tags": ["persian", "dinner", "romantic"], "best_time": ["dinner"], "lat": 25.2865, "lon": 51.5331},
                {"name": "Layali Al Qahira", "tags": ["egyptian", "dinner", "live music"], "best_time": ["dinner"], "lat": 25.2870, "lon": 51.5328},
                {"name": "Al Mourjan", "tags": ["lebanese", "dinner", "views"], "best_time": ["dinner"], "lat": 25.2869, "lon": 51.5332},
                {"name": "The Majlis Qatar", "tags": ["qatari", "lunch", "dinner"], "best_time": ["lunch", "dinner"], "lat": 25.2867, "lon": 51.5330},
                {"name": "Boho Social", "tags": ["cafe", "breakfast", "lunch"], "best_time": ["morning", "afternoon"], "lat": 25.3650, "lon": 51.5105},
                {"name": "Ric's Kountry Kitchen", "tags": ["american", "breakfast", "family"], "best_time": ["morning"], "lat": 25.2760, "lon": 51.5265},
                {"name": "Evergreen Organics", "tags": ["healthy", "vegan", "lunch"], "best_time": ["lunch"], "lat": 25.3600, "lon": 51.5102},
                {"name": "Papa Johns Pizza", "tags": ["pizza", "kids friendly", "dinner"], "best_time": ["dinner"], "lat": 25.2680, "lon": 51.4350},
                {"name": "Spice Market", "tags": ["asian", "dinner", "fine dining"], "best_time": ["dinner"], "lat": 25.2860, "lon": 51.5260},
            ],
            "neighborhoods": [
                {"name": "West Bay", "tags": ["business", "skyline", "hotels"], "lat": 25.3286, "lon": 51.5300},
                {"name": "The Pearl-Qatar", "tags": ["luxury", "marina", "dining"], "lat": 25.3702, "lon": 51.5495},
                {"name": "Katara", "tags": ["culture", "beach", "art"], "lat": 25.3602, "lon": 51.5100},
                {"name": "Msheireb Downtown Doha", "tags": ["heritage", "modern", "walks"], "lat": 25.2886, "lon": 51.5237},
                {"name": "Al Sadd", "tags": ["local", "shopping", "food"], "lat": 25.2800, "lon": 51.5000},
                {"name": "Al Wakrah", "tags": ["heritage", "beach", "day trip"], "lat": 25.1650, "lon": 51.6000},
            ],
            "day_trips": [
                {"name": "Al Zubarah Fort & UNESCO Site", "tags": ["history", "unesco", "day trip"], "best_time": ["morning"], "lat": 25.9781, "lon": 51.0328},
                {"name": "Purple Island (Al Thakira Mangroves)", "tags": ["nature", "kayaking", "day trip"], "best_time": ["morning"], "lat": 25.9200, "lon": 51.5330},
                {"name": "Al Wakrah Souq & Beach", "tags": ["heritage", "beach", "day trip"], "best_time": ["morning", "afternoon"], "lat": 25.1650, "lon": 51.6000},
                {"name": "Khor Al Adaid (Inland Sea)", "tags": ["desert", "4x4", "day trip", "views"], "best_time": ["morning"], "lat": 24.9500, "lon": 51.5000},
                {"name": "Al Khor Mall & Coastal Town", "tags": ["coastal", "day trip", "local"], "best_time": ["morning", "afternoon"], "lat": 25.6800, "lon": 51.5000},
                {"name": "Umm Salal Muhammad Fort", "tags": ["history", "fort", "day trip"], "best_time": ["morning"], "lat": 25.4167, "lon": 51.4000},
            ],
            "hotels": [
                {"name": "Four Seasons Hotel Doha", "price": "~QAR 1,800", "location": "West Bay", "highlights": "Sea-view luxury rooms and family pool"},
                {"name": "Mondrian Doha", "price": "~QAR 900", "location": "West Bay Lagoon", "highlights": "Design hotel with rooftop dining"},
                {"name": "Souq Waqif Boutique Hotels", "price": "~QAR 600", "location": "Souq Waqif", "highlights": "Traditional-style hotels in the souq"},
                {"name": "Marriott Marquis City Center Doha", "price": "~QAR 700", "location": "West Bay", "highlights": "Connected to City Centre Mall"},
                {"name": "Retaj Al Rayyan Hotel", "price": "~QAR 450", "location": "Madinat Khalifa South", "highlights": "Budget-friendly option near Aspire Park"},
            ],
        },
        "dubai": {
            "attractions": [
                {"name": "Burj Khalifa", "tags": ["views", "architecture", "photography"], "best_time": ["morning", "evening"], "lat": 25.1972, "lon": 55.2744},
                {"name": "The Dubai Fountain", "tags": ["views", "photography", "romantic"], "best_time": ["evening"], "lat": 25.1948, "lon": 55.2745},
                {"name": "Dubai Mall", "tags": ["shopping", "kids friendly", "food & drink"], "best_time": ["afternoon", "evening"], "lat": 25.1982, "lon": 55.2790},
                {"name": "Palm Jumeirah", "tags": ["beach", "views", "architecture"], "best_time": ["morning", "afternoon"], "lat": 25.1188, "lon": 55.1387},
                {"name": "Burj Al Arab", "tags": ["architecture", "views", "photography"], "best_time": ["morning", "afternoon"], "lat": 25.1413, "lon": 55.1853},
                {"name": "Dubai Marina", "tags": ["views", "food & drink", "walking"], "best_time": ["afternoon", "evening"], "lat": 25.0777, "lon": 55.1329},
                {"name": "Global Village", "tags": ["culture", "kids friendly", "shopping"], "best_time": ["evening"], "lat": 25.0682, "lon": 55.3064},
                {"name": "Dubai Frame", "tags": ["views", "photography", "architecture"], "best_time": ["morning", "afternoon"], "lat": 25.2357, "lon": 55.2966},
                {"name": "IMG Worlds of Adventure", "tags": ["theme parks", "kids friendly", "entertainment"], "best_time": ["morning", "afternoon"], "lat": 25.0706, "lon": 55.3159},
                {"name": "Aquaventure Waterpark", "tags": ["water activities", "kids friendly", "thrill"], "best_time": ["morning", "afternoon"], "lat": 25.1290, "lon": 55.1187},
                {"name": "Dubai Miracle Garden", "tags": ["parks & outdoors", "photography", "nature & wildlife"], "best_time": ["morning", "afternoon"], "lat": 25.0877, "lon": 55.2426},
                {"name": "Souk Madinat Jumeirah", "tags": ["local markets", "shopping", "food & drink"], "best_time": ["afternoon", "evening"], "lat": 25.1316, "lon": 55.1897},
                {"name": "Gold Souk", "tags": ["local markets", "shopping", "culture"], "best_time": ["morning", "afternoon"], "lat": 25.2706, "lon": 55.2969},
                {"name": "Deira Creek", "tags": ["history & culture", "views", "food & drink"], "best_time": ["evening"], "lat": 25.2619, "lon": 55.3013},
            ],
            "museums": [
                {"name": "Museum of the Future", "tags": ["museums & art", "technology", "architecture"], "best_time": ["morning", "afternoon"], "lat": 25.2208, "lon": 55.2820},
                {"name": "Louvre Abu Dhabi", "tags": ["museums & art", "art galleries", "architecture"], "best_time": ["morning", "afternoon"], "lat": 24.5435, "lon": 54.3983},
                {"name": "Dubai Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 25.2636, "lon": 55.2972},
                {"name": "Etihad Museum", "tags": ["museums & art", "history & culture"], "best_time": ["afternoon"], "lat": 25.2107, "lon": 55.2720},
                {"name": "Coffee Museum", "tags": ["museums & art", "food & drink", "culture"], "best_time": ["afternoon"], "lat": 25.2650, "lon": 55.2980},
            ],
            "markets": [
                {"name": "Gold Souk", "tags": ["local markets", "shopping", "jewellery"], "lat": 25.2706, "lon": 55.2969},
                {"name": "Spice Souk", "tags": ["local markets", "food & drink", "culture"], "lat": 25.2695, "lon": 55.2980},
                {"name": "Dubai Mall", "tags": ["shopping", "luxury", "entertainment"], "lat": 25.1982, "lon": 55.2790},
                {"name": "Mall of the Emirates", "tags": ["shopping", "luxury", "food & drink"], "lat": 25.1180, "lon": 55.2003},
                {"name": "Souk Madinat Jumeirah", "tags": ["local markets", "shopping", "food & drink"], "lat": 25.1316, "lon": 55.1897},
                {"name": "Global Village", "tags": ["local markets", "culture", "shopping"], "lat": 25.0682, "lon": 55.3064},
            ],
            "food": [
                {"name": "Al Mallah", "tags": ["local cuisine", "lebanese", "budget eats", "lunch"], "best_time": ["afternoon"], "lat": 25.2585, "lon": 55.3165},
                {"name": "Pierchic", "tags": ["seafood", "fine dining", "views", "dinner"], "best_time": ["evening"], "lat": 25.1421, "lon": 55.1854},
                {"name": "Ravi Restaurant", "tags": ["asian", "pakistani", "budget eats", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 25.2700, "lon": 55.3100},
                {"name": "La Petite Maison", "tags": ["french", "mediterranean", "fine dining", "dinner"], "best_time": ["evening"], "lat": 25.2025, "lon": 55.2690},
                {"name": "Tom & Serg", "tags": ["coffee & cafés", "breakfast", "brunch"], "best_time": ["morning"], "lat": 25.2090, "lon": 55.2570},
                {"name": "Operation: Falafel", "tags": ["local cuisine", "street food", "lunch"], "best_time": ["afternoon"], "lat": 25.2110, "lon": 55.2770},
                {"name": "Din Tai Fung Dubai Mall", "tags": ["asian", "chinese", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 25.1982, "lon": 55.2790},
                {"name": "Pai Thai", "tags": ["asian", "thai", "dinner"], "best_time": ["evening"], "lat": 25.1316, "lon": 55.1897},
                {"name": "Baker & Spice", "tags": ["coffee & cafés", "breakfast", "lunch"], "best_time": ["morning", "afternoon"], "lat": 25.2000, "lon": 55.2660},
                {"name": "Emirates Hangout", "tags": ["local cuisine", "kebab", "budget eats", "dinner"], "best_time": ["evening"], "lat": 25.2600, "lon": 55.3000},
            ],
            "neighborhoods": [
                {"name": "Downtown Dubai", "tags": ["shopping", "architecture", "food & drink"], "lat": 25.1982, "lon": 55.2790},
                {"name": "Dubai Marina", "tags": ["waterfront", "food & drink", "nightlife"], "lat": 25.0777, "lon": 55.1329},
                {"name": "Jumeirah", "tags": ["beach", "luxury", "food & drink"], "lat": 25.2048, "lon": 55.2708},
                {"name": "Deira", "tags": ["history & culture", "local markets", "food & drink"], "lat": 25.2650, "lon": 55.3000},
                {"name": "Al Fahidi Historical Neighbourhood", "tags": ["history & culture", "architecture", "photography"], "lat": 25.2630, "lon": 55.2975},
                {"name": "Business Bay", "tags": ["modern architecture", "food & drink", "views"], "lat": 25.1860, "lon": 55.2630},
            ],
            "day_trips": [
                {"name": "Abu Dhabi Day Trip", "tags": ["culture", "architecture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 24.4539, "lon": 54.3773},
                {"name": "Desert Safari", "tags": ["nature & wildlife", "adventure", "day trip"], "best_time": ["afternoon", "evening"], "lat": 25.0000, "lon": 55.0000},
                {"name": "Hatta Heritage Village", "tags": ["history & culture", "nature & wildlife", "day trip"], "best_time": ["morning", "afternoon"], "lat": 24.7962, "lon": 56.1258},
                {"name": "Sharjah Day Trip", "tags": ["history & culture", "museums & art", "day trip"], "best_time": ["morning", "afternoon"], "lat": 25.3463, "lon": 55.4209},
                {"name": "Al Ain Oasis", "tags": ["nature & wildlife", "history & culture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 24.2248, "lon": 55.7405},
                {"name": "Dubai Desert Conservation Reserve", "tags": ["nature & wildlife", "adventure", "day trip"], "best_time": ["morning", "afternoon"], "lat": 24.8180, "lon": 55.3300},
            ],
            "hotels": [
                {"name": "Rove Downtown", "price": "~AED 450", "location": "Downtown Dubai", "highlights": "Budget-friendly base near Burj Khalifa and Dubai Mall"},
                {"name": "Vida Downtown", "price": "~AED 550", "location": "Downtown Dubai", "highlights": "Stylish hotel walking distance to the Dubai Fountain"},
                {"name": "Ibis Al Rigga", "price": "~AED 220", "location": "Deira", "highlights": "Compact, affordable rooms in the city centre"},
                {"name": "Jumeirah Beach Hotel", "price": "~AED 1,400", "location": "Jumeirah Beach", "highlights": "Family resort with direct beach access and kids club"},
                {"name": "Atlantis, The Palm", "price": "~AED 2,000", "location": "Palm Jumeirah", "highlights": "Iconic waterpark and aquarium resort"},
            ],
        },
        "abu dhabi": {
            "attractions": [
                {"name": "Sheikh Zayed Grand Mosque", "tags": ["architecture", "history & culture", "photography"], "best_time": ["morning", "afternoon"], "lat": 24.4129, "lon": 54.4751},
                {"name": "Louvre Abu Dhabi", "tags": ["museums & art", "architecture", "art galleries"], "best_time": ["morning", "afternoon"], "lat": 24.5435, "lon": 54.3983},
                {"name": "Yas Marina Circuit", "tags": ["sports", "thrill", "entertainment"], "best_time": ["morning", "afternoon"], "lat": 24.4672, "lon": 54.6031},
                {"name": "Ferrari World Abu Dhabi", "tags": ["theme parks", "thrill", "kids friendly"], "best_time": ["morning", "afternoon"], "lat": 24.4841, "lon": 54.6080},
                {"name": "Yas Waterworld", "tags": ["water activities", "kids friendly", "thrill"], "best_time": ["morning", "afternoon"], "lat": 24.4868, "lon": 54.5978},
                {"name": "Emirates Palace", "tags": ["architecture", "luxury", "food & drink"], "best_time": ["afternoon", "evening"], "lat": 24.4621, "lon": 54.3170},
                {"name": "Qasr Al Watan", "tags": ["history & culture", "architecture", "photography"], "best_time": ["morning", "afternoon"], "lat": 24.4620, "lon": 54.3320},
                {"name": "Heritage Village", "tags": ["history & culture", "culture", "shopping"], "best_time": ["afternoon"], "lat": 24.4840, "lon": 54.3270},
                {"name": "Saadiyat Beach", "tags": ["beach", "relaxation", "nature & wildlife"], "best_time": ["morning", "afternoon"], "lat": 24.5360, "lon": 54.4450},
                {"name": "Observation Deck at 300", "tags": ["views", "photography", "romantic"], "best_time": ["evening"], "lat": 24.5005, "lon": 54.3775},
                {"name": "Etihad Towers", "tags": ["architecture", "views", "food & drink"], "best_time": ["afternoon", "evening"], "lat": 24.4990, "lon": 54.3790},
            ],
            "museums": [
                {"name": "Louvre Abu Dhabi", "tags": ["museums & art", "art galleries", "architecture"], "best_time": ["morning", "afternoon"], "lat": 24.5435, "lon": 54.3983},
                {"name": "Qasr Al Hosn", "tags": ["museums & art", "history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 24.4675, "lon": 54.3707},
                {"name": "Zayed National Museum", "tags": ["museums & art", "history & culture"], "best_time": ["afternoon"], "lat": 24.4850, "lon": 54.3300},
                {"name": "Warehouse421", "tags": ["museums & art", "art galleries", "culture"], "best_time": ["afternoon"], "lat": 24.4850, "lon": 54.3550},
            ],
            "markets": [
                {"name": "Abu Dhabi Dates Market", "tags": ["local markets", "food & drink", "culture"], "lat": 24.4700, "lon": 54.3500},
                {"name": "Marina Mall", "tags": ["shopping", "food & drink", "entertainment"], "lat": 24.4768, "lon": 54.3343},
                {"name": "Yas Mall", "tags": ["shopping", "luxury", "entertainment"], "lat": 24.4954, "lon": 54.6079},
                {"name": "Souk Qaryat Al Beri", "tags": ["local markets", "shopping", "food & drink"], "lat": 24.4600, "lon": 54.3300},
            ],
            "food": [
                {"name": "Hakkasan Abu Dhabi", "tags": ["asian", "fine dining", "dinner"], "best_time": ["evening"], "lat": 24.4630, "lon": 54.3210},
                {"name": "Li Beirut", "tags": ["local cuisine", "lebanese", "fine dining", "dinner"], "best_time": ["evening"], "lat": 24.4550, "lon": 54.3210},
                {"name": "Al Fanar Restaurant", "tags": ["local cuisine", "emirati", "dinner"], "best_time": ["evening"], "lat": 24.4500, "lon": 54.3400},
                {"name": "The Third Place", "tags": ["coffee & cafés", "breakfast", "brunch"], "best_time": ["morning"], "lat": 24.5000, "lon": 54.3900},
                {"name": "Jones the Grocer", "tags": ["coffee & cafés", "breakfast", "lunch"], "best_time": ["morning", "afternoon"], "lat": 24.5050, "lon": 54.3800},
                {"name": "Zuma Abu Dhabi", "tags": ["asian", "japanese", "dinner"], "best_time": ["evening"], "lat": 24.4550, "lon": 54.3220},
                {"name": "Erth", "tags": ["local cuisine", "emirati", "fine dining", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 24.4640, "lon": 54.3300},
            ],
            "neighborhoods": [
                {"name": "Corniche", "tags": ["beach", "parks & outdoors", "food & drink"], "lat": 24.4860, "lon": 54.3500},
                {"name": "Saadiyat Island", "tags": ["beach", "luxury", "museums & art"], "lat": 24.5400, "lon": 54.4300},
                {"name": "Yas Island", "tags": ["theme parks", "entertainment", "kids friendly"], "lat": 24.4900, "lon": 54.6000},
                {"name": "Al Maryah Island", "tags": ["modern architecture", "food & drink", "shopping"], "lat": 24.5000, "lon": 54.3900},
            ],
            "day_trips": [
                {"name": "Dubai Day Trip", "tags": ["shopping", "architecture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 25.2048, "lon": 55.2708},
                {"name": "Liwa Oasis Desert Drive", "tags": ["nature & wildlife", "adventure", "day trip"], "best_time": ["morning", "afternoon"], "lat": 23.0800, "lon": 53.6200},
                {"name": "Al Ain Oasis", "tags": ["nature & wildlife", "history & culture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 24.2248, "lon": 55.7405},
                {"name": "Sir Bani Yas Island", "tags": ["nature & wildlife", "adventure", "day trip"], "best_time": ["morning", "afternoon"], "lat": 24.3333, "lon": 52.5833},
                {"name": "Jebel Hafit Mountain", "tags": ["nature & wildlife", "hiking & adventure", "views", "day trip"], "best_time": ["morning", "afternoon"], "lat": 24.0500, "lon": 55.8000},
            ],
            "hotels": [
                {"name": "Emirates Palace Mandarin Oriental", "price": "~AED 2,500", "location": "Corniche", "highlights": "Opulent beachfront palace hotel"},
                {"name": "Aloft Abu Dhabi", "price": "~AED 400", "location": "Abu Dhabi National Exhibition Centre", "highlights": "Modern, affordable rooms near the highway"},
                {"name": "Hilton Abu Dhabi Yas Island", "price": "~AED 600", "location": "Yas Island", "highlights": "Family-friendly base near theme parks"},
                {"name": "Park Inn by Radisson Yas Island", "price": "~AED 350", "location": "Yas Island", "highlights": "Budget hotel within walking distance of Ferrari World"},
            ],
        },
        "paris": {
            "attractions": [
                {"name": "Eiffel Tower", "tags": ["views", "photography", "architecture", "kids friendly"], "best_time": ["morning", "evening"], "lat": 48.8584, "lon": 2.2945},
                {"name": "Louvre Museum", "tags": ["museums & art", "history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 48.8606, "lon": 2.3376},
                {"name": "Notre-Dame Cathedral", "tags": ["history & culture", "architecture", "photography"], "best_time": ["morning", "afternoon"], "lat": 48.8530, "lon": 2.3499},
                {"name": "Arc de Triomphe", "tags": ["history & culture", "architecture", "views"], "best_time": ["morning", "evening"], "lat": 48.8738, "lon": 2.2950},
                {"name": "Sacré-Cœur Basilica", "tags": ["history & culture", "architecture", "views"], "best_time": ["morning", "afternoon"], "lat": 48.8867, "lon": 2.3431},
                {"name": "Sainte-Chapelle", "tags": ["history & culture", "architecture", "museums & art"], "best_time": ["morning", "afternoon"], "lat": 48.8514, "lon": 2.3452},
                {"name": "Musée d'Orsay", "tags": ["museums & art", "art galleries", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 48.8599, "lon": 2.3266},
                {"name": "Tuileries Garden", "tags": ["parks & outdoors", "kids friendly", "photography"], "best_time": ["morning", "afternoon"], "lat": 48.8634, "lon": 2.3275},
                {"name": "Luxembourg Gardens", "tags": ["parks & outdoors", "kids friendly", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 48.8462, "lon": 2.3372},
                {"name": "Panthéon", "tags": ["history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 48.8462, "lon": 2.3458},
                {"name": "Centre Pompidou", "tags": ["museums & art", "art galleries", "architecture"], "best_time": ["afternoon"], "lat": 48.8606, "lon": 2.3522},
                {"name": "Montmartre Village", "tags": ["photography", "art galleries", "food & drink"], "best_time": ["morning", "afternoon"], "lat": 48.8867, "lon": 2.3431},
                {"name": "Seine River Cruise", "tags": ["views", "photography", "romantic"], "best_time": ["evening"], "lat": 48.8589, "lon": 2.2932},
                {"name": "Champs-Élysées", "tags": ["shopping", "photography", "food & drink"], "best_time": ["afternoon", "evening"], "lat": 48.8698, "lon": 2.3079},
            ],
            "museums": [
                {"name": "Louvre Museum", "tags": ["museums & art", "history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 48.8606, "lon": 2.3376},
                {"name": "Musée d'Orsay", "tags": ["museums & art", "art galleries", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 48.8599, "lon": 2.3266},
                {"name": "Centre Pompidou", "tags": ["museums & art", "art galleries", "architecture"], "best_time": ["afternoon"], "lat": 48.8606, "lon": 2.3522},
                {"name": "Musée de l'Orangerie", "tags": ["museums & art", "art galleries"], "best_time": ["morning", "afternoon"], "lat": 48.8638, "lon": 2.3234},
                {"name": "Rodin Museum", "tags": ["museums & art", "sculpture", "parks & outdoors"], "best_time": ["morning", "afternoon"], "lat": 48.8553, "lon": 2.3158},
                {"name": "Picasso Museum", "tags": ["museums & art", "art galleries"], "best_time": ["afternoon"], "lat": 48.8599, "lon": 2.3624},
                {"name": "Musée de la Vie Romantique", "tags": ["museums & art", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 48.8807, "lon": 2.3318},
            ],
            "markets": [
                {"name": "Marché Bastille", "tags": ["local markets", "food & drink", "culture"], "lat": 48.8531, "lon": 2.3691},
                {"name": "Marché Saint-Germain", "tags": ["local markets", "food & drink", "shopping"], "lat": 48.8514, "lon": 2.3381},
                {"name": "Le Bon Marché", "tags": ["shopping", "department store", "luxury"], "lat": 48.8510, "lon": 2.3236},
                {"name": "Galeries Lafayette", "tags": ["shopping", "department store", "views"], "lat": 48.8736, "lon": 2.3320},
                {"name": "Marché aux Puces de Saint-Ouen", "tags": ["local markets", "vintage", "shopping"], "lat": 48.9016, "lon": 2.3306},
                {"name": "Marché d'Aligre", "tags": ["local markets", "food & drink", "culture"], "lat": 48.8500, "lon": 2.3780},
            ],
            "food": [
                {"name": "Café de Flore", "tags": ["coffee & cafés", "breakfast", "history & culture"], "best_time": ["morning"], "lat": 48.8539, "lon": 2.3326},
                {"name": "Les Deux Magots", "tags": ["coffee & cafés", "breakfast", "history & culture"], "best_time": ["morning"], "lat": 48.8540, "lon": 2.3335},
                {"name": "Le Comptoir du Relais", "tags": ["french", "bistro", "dinner"], "best_time": ["afternoon", "evening"], "lat": 48.8509, "lon": 2.3384},
                {"name": "L'Ambroisie", "tags": ["french", "fine dining", "dinner"], "best_time": ["evening"], "lat": 48.8548, "lon": 2.3576},
                {"name": "Breizh Café", "tags": ["french", "crepes", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 48.8534, "lon": 2.3575},
                {"name": "BigLove Caffè", "tags": ["italian", "pizza", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 48.8648, "lon": 2.3684},
                {"name": "Le Bouillon Chartier", "tags": ["french", "bistro", "budget eats", "dinner"], "best_time": ["afternoon", "evening"], "lat": 48.8718, "lon": 2.3322},
                {"name": "Pierre Hermé", "tags": ["sweets & desserts", "coffee & cafés", "breakfast"], "best_time": ["morning", "afternoon"], "lat": 48.8528, "lon": 2.3292},
                {"name": "Le Train Bleu", "tags": ["french", "fine dining", "dinner", "views"], "best_time": ["evening"], "lat": 48.8447, "lon": 2.3745},
                {"name": "Chez Janou", "tags": ["french", "bistro", "dinner"], "best_time": ["evening"], "lat": 48.8554, "lon": 2.3673},
            ],
            "neighborhoods": [
                {"name": "Le Marais", "tags": ["history & culture", "art galleries", "food & drink", "shopping"], "lat": 48.8570, "lon": 2.3587},
                {"name": "Saint-Germain-des-Prés", "tags": ["history & culture", "food & drink", "art galleries"], "lat": 48.8534, "lon": 2.3364},
                {"name": "Montmartre", "tags": ["photography", "art galleries", "views", "food & drink"], "lat": 48.8867, "lon": 2.3431},
                {"name": "Latin Quarter", "tags": ["history & culture", "food & drink", "nightlife"], "lat": 48.8462, "lon": 2.3458},
                {"name": "Île de la Cité", "tags": ["history & culture", "architecture", "photography"], "lat": 48.8534, "lon": 2.3488},
                {"name": "Canal Saint-Martin", "tags": ["food & drink", "nightlife", "photography"], "lat": 48.8708, "lon": 2.3700},
            ],
            "day_trips": [
                {"name": "Palace of Versailles", "tags": ["history & culture", "architecture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 48.8049, "lon": 2.1204},
                {"name": "Disneyland Paris", "tags": ["kids friendly", "theme parks", "day trip"], "best_time": ["morning", "afternoon"], "lat": 48.8724, "lon": 2.7768},
                {"name": "Giverny Monet's Gardens", "tags": ["parks & outdoors", "museums & art", "day trip"], "best_time": ["morning", "afternoon"], "lat": 49.0760, "lon": 1.5310},
                {"name": "Fontainebleau Palace", "tags": ["history & culture", "architecture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 48.4047, "lon": 2.6997},
                {"name": "Château de Chantilly", "tags": ["history & culture", "architecture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 49.1936, "lon": 2.4856},
                {"name": "Reims Champagne Region", "tags": ["food & drink", "day trip", "wineries"], "best_time": ["morning", "afternoon"], "lat": 49.2628, "lon": 4.0347},
            ],
            "hotels": [
                {"name": "Le Meurice", "price": "~EUR 1,200", "location": "Rue de Rivoli", "highlights": "Palace hotel overlooking the Tuileries"},
                {"name": "Hôtel Lutetia", "price": "~EUR 650", "location": "Saint-Germain-des-Prés", "highlights": "Historic Left Bank art deco landmark"},
                {"name": "Hotel des Grands Boulevards", "price": "~EUR 320", "location": "2nd Arrondissement", "highlights": "Boutique design hotel near Opéra"},
                {"name": "Hôtel Malte Opera", "price": "~EUR 180", "location": "Opéra", "highlights": "Central, comfortable base for sightseeing"},
            ],
        },
        "lyon": {
            "attractions": [
                {"name": "Vieux Lyon", "tags": ["history & culture", "architecture", "food & drink"], "best_time": ["morning", "afternoon"], "lat": 45.7640, "lon": 4.8357},
                {"name": "Basilique Notre-Dame de Fourvière", "tags": ["history & culture", "architecture", "views"], "best_time": ["morning", "afternoon"], "lat": 45.7623, "lon": 4.8227},
                {"name": "Place Bellecour", "tags": ["photography", "history & culture", "shopping"], "best_time": ["morning", "afternoon"], "lat": 45.7578, "lon": 4.8320},
                {"name": "Parc de la Tête d'Or", "tags": ["parks & outdoors", "nature & wildlife", "kids friendly"], "best_time": ["morning", "afternoon"], "lat": 45.7774, "lon": 4.8554},
                {"name": "Musée des Confluences", "tags": ["museums & art", "architecture", "history & culture"], "best_time": ["afternoon"], "lat": 45.7336, "lon": 4.8177},
                {"name": "Croix-Rousse", "tags": ["history & culture", "photography", "art galleries"], "best_time": ["morning", "afternoon"], "lat": 45.7760, "lon": 4.8330},
                {"name": "Traboules of Lyon", "tags": ["history & culture", "architecture", "photography"], "best_time": ["morning", "afternoon"], "lat": 45.7640, "lon": 4.8270},
            ],
            "museums": [
                {"name": "Musée des Beaux-Arts de Lyon", "tags": ["museums & art", "art galleries", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 45.7673, "lon": 4.8334},
                {"name": "Musée des Confluences", "tags": ["museums & art", "architecture", "history & culture"], "best_time": ["afternoon"], "lat": 45.7336, "lon": 4.8177},
                {"name": "Lumière Museum", "tags": ["museums & art", "history & culture", "photography"], "best_time": ["morning", "afternoon"], "lat": 45.7466, "lon": 4.8684},
                {"name": "Miniature and Cinema Museum", "tags": ["museums & art", "kids friendly", "photography"], "best_time": ["afternoon"], "lat": 45.7665, "lon": 4.8357},
            ],
            "markets": [
                {"name": "Les Halles de Lyon Paul Bocuse", "tags": ["local markets", "food & drink", "gourmet"], "lat": 45.7615, "lon": 4.8502},
                {"name": "Marché Saint-Antoine", "tags": ["local markets", "food & drink"], "lat": 45.7644, "lon": 4.8346},
                {"name": "Vieux Lyon Market", "tags": ["local markets", "food & drink", "culture"], "lat": 45.7640, "lon": 4.8270},
            ],
            "food": [
                {"name": "Paul Bocuse - L'Auberge du Pont de Collonges", "tags": ["french", "fine dining", "dinner"], "best_time": ["evening"], "lat": 45.8157, "lon": 4.8275},
                {"name": "Bouchon Comptoir Abel", "tags": ["french", "bistro", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 45.7673, "lon": 4.8285},
                {"name": "Le Bistrot de Lyon", "tags": ["french", "bistro", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 45.7662, "lon": 4.8364},
                {"name": "Archange", "tags": ["french", "fine dining", "dinner"], "best_time": ["evening"], "lat": 45.7705, "lon": 4.8310},
                {"name": "Café des Négociants", "tags": ["coffee & cafés", "breakfast", "local cuisine"], "best_time": ["morning"], "lat": 45.7690, "lon": 4.8330},
                {"name": "Daniel et Denise", "tags": ["french", "bistro", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 45.7660, "lon": 4.8270},
            ],
            "neighborhoods": [
                {"name": "Vieux Lyon", "tags": ["history & culture", "food & drink", "architecture"], "lat": 45.7640, "lon": 4.8357},
                {"name": "Presqu'île", "tags": ["shopping", "food & drink", "nightlife"], "lat": 45.7640, "lon": 4.8357},
                {"name": "Croix-Rousse", "tags": ["history & culture", "art galleries", "views"], "lat": 45.7760, "lon": 4.8330},
                {"name": "Confluence", "tags": ["modern architecture", "shopping", "food & drink"], "lat": 45.7336, "lon": 4.8177},
            ],
            "day_trips": [
                {"name": "Beaujolais Wine Region", "tags": ["food & drink", "wineries", "day trip"], "best_time": ["morning", "afternoon"], "lat": 46.0333, "lon": 4.7000},
                {"name": "Annecy Lake Town", "tags": ["parks & outdoors", "photography", "day trip"], "best_time": ["morning", "afternoon"], "lat": 45.8992, "lon": 6.1290},
                {"name": "Pérouges Medieval Village", "tags": ["history & culture", "architecture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 45.9000, "lon": 5.2000},
            ],
            "hotels": [
                {"name": "Villa Florentine", "price": "~EUR 380", "location": "Vieux Lyon", "highlights": "Renaissance villa with panoramic city views"},
                {"name": "Hotel Carlton Lyon", "price": "~EUR 180", "location": "Presqu'île", "highlights": "Belle Époque hotel near Place Bellecour"},
                {"name": "MiHotel", "price": "~EUR 140", "location": "Confluence", "highlights": "Modern boutique rooms in the Confluence district"},
            ],
        },
        "nice": {
            "attractions": [
                {"name": "Promenade des Anglais", "tags": ["beach", "views", "photography", "walking"], "best_time": ["morning", "evening"], "lat": 43.6953, "lon": 7.2656},
                {"name": "Castle Hill (Colline du Château)", "tags": ["views", "parks & outdoors", "photography"], "best_time": ["morning", "afternoon"], "lat": 43.6950, "lon": 7.2800},
                {"name": "Old Town (Vieux Nice)", "tags": ["history & culture", "food & drink", "local markets"], "best_time": ["morning", "afternoon"], "lat": 43.6955, "lon": 7.2705},
                {"name": "Place Masséna", "tags": ["photography", "history & culture", "shopping"], "best_time": ["morning", "afternoon"], "lat": 43.6964, "lon": 7.2710},
                {"name": "Cours Saleya Flower Market", "tags": ["local markets", "parks & outdoors", "food & drink"], "best_time": ["morning"], "lat": 43.6955, "lon": 7.2705},
                {"name": "Musée Matisse", "tags": ["museums & art", "art galleries"], "best_time": ["morning", "afternoon"], "lat": 43.7193, "lon": 7.2760},
                {"name": "Russian Orthodox Cathedral", "tags": ["history & culture", "architecture", "photography"], "best_time": ["morning"], "lat": 43.7032, "lon": 7.2535},
                {"name": "Mount Boron", "tags": ["nature & wildlife", "hiking & adventure", "views"], "best_time": ["morning"], "lat": 43.7050, "lon": 7.2950},
            ],
            "museums": [
                {"name": "Musée Matisse", "tags": ["museums & art", "art galleries"], "best_time": ["morning", "afternoon"], "lat": 43.7193, "lon": 7.2760},
                {"name": "Musée Marc Chagall", "tags": ["museums & art", "art galleries", "religious art"], "best_time": ["morning", "afternoon"], "lat": 43.7195, "lon": 7.2750},
                {"name": "Musée d'Art Moderne et d'Art Contemporain", "tags": ["museums & art", "art galleries", "modern art"], "best_time": ["afternoon"], "lat": 43.7010, "lon": 7.2790},
                {"name": "Archaeology Museum", "tags": ["museums & art", "history & culture"], "best_time": ["morning"], "lat": 43.6950, "lon": 7.2800},
            ],
            "markets": [
                {"name": "Cours Saleya Flower & Food Market", "tags": ["local markets", "food & drink", "culture"], "lat": 43.6955, "lon": 7.2705},
                {"name": "Libération Market", "tags": ["local markets", "food & drink"], "lat": 43.7040, "lon": 7.2700},
                {"name": "Nice Etoile", "tags": ["shopping", "department store"], "lat": 43.7025, "lon": 7.2685},
            ],
            "food": [
                {"name": "La Petite Maison", "tags": ["french", "mediterranean", "dinner"], "best_time": ["evening"], "lat": 43.6955, "lon": 7.2705},
                {"name": "Jan", "tags": ["french", "fine dining", "dinner"], "best_time": ["evening"], "lat": 43.7045, "lon": 7.2690},
                {"name": "Chez Pipo", "tags": ["local cuisine", "pizza", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 43.6960, "lon": 7.2740},
                {"name": "A Buteghinna", "tags": ["local cuisine", "niçoise", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 43.6960, "lon": 7.2705},
                {"name": "Café de Turin", "tags": ["seafood", "local cuisine", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 43.6940, "lon": 7.2720},
                {"name": "Le Safari", "tags": ["french", "bistro", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 43.6950, "lon": 7.2700},
                {"name": "Maison Auer", "tags": ["sweets & desserts", "coffee & cafés", "breakfast"], "best_time": ["morning", "afternoon"], "lat": 43.6965, "lon": 7.2705},
            ],
            "neighborhoods": [
                {"name": "Vieux Nice", "tags": ["history & culture", "food & drink", "local markets"], "lat": 43.6955, "lon": 7.2705},
                {"name": "Cimiez", "tags": ["museums & art", "parks & outdoors", "history & culture"], "lat": 43.7190, "lon": 7.2750},
                {"name": "Jean Médecin", "tags": ["shopping", "food & drink", "nightlife"], "lat": 43.7020, "lon": 7.2680},
                {"name": "Port Lympia", "tags": ["waterfront", "food & drink", "photography"], "lat": 43.6940, "lon": 7.2820},
            ],
            "day_trips": [
                {"name": "Monaco & Monte Carlo", "tags": ["luxury", "views", "day trip"], "best_time": ["morning", "afternoon"], "lat": 43.7384, "lon": 7.4246},
                {"name": "Cannes Day Trip", "tags": ["beach", "luxury", "photography", "day trip"], "best_time": ["morning", "afternoon"], "lat": 43.5528, "lon": 7.0174},
                {"name": "Èze Village", "tags": ["history & culture", "views", "day trip"], "best_time": ["morning", "afternoon"], "lat": 43.7278, "lon": 7.3618},
                {"name": "Antibes & Picasso Museum", "tags": ["museums & art", "beach", "day trip"], "best_time": ["morning", "afternoon"], "lat": 43.5804, "lon": 7.1251},
                {"name": "Saint-Paul-de-Vence", "tags": ["art galleries", "history & culture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 43.7484, "lon": 7.4460},
            ],
            "hotels": [
                {"name": "Hotel Negresco", "price": "~EUR 600", "location": "Promenade des Anglais", "highlights": "Iconic Belle Époque palace hotel"},
                {"name": "Le Méridien Nice", "price": "~EUR 280", "location": "Promenade des Anglais", "highlights": "Seafront location near Old Town"},
                {"name": "Hôtel La Pérouse", "price": "~EUR 220", "location": "Castle Hill", "highlights": "Quiet boutique hotel by the sea"},
            ],
        },
        "marrakech": {
            "attractions": [
                {"name": "Jemaa el-Fnaa Square", "tags": ["culture", "local markets", "food & drink", "evening"], "best_time": ["afternoon", "evening"], "lat": 31.6258, "lon": -7.9893},
                {"name": "Koutoubia Mosque", "tags": ["architecture", "history & culture", "photography"], "best_time": ["morning", "afternoon"], "lat": 31.6241, "lon": -7.9937},
                {"name": "Bahia Palace", "tags": ["history & culture", "architecture", "photography"], "best_time": ["morning", "afternoon"], "lat": 31.6173, "lon": -7.9816},
                {"name": "Saadian Tombs", "tags": ["history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 31.6173, "lon": -7.9896},
                {"name": "Majorelle Garden", "tags": ["parks & outdoors", "museums & art", "photography"], "best_time": ["morning", "afternoon"], "lat": 31.6418, "lon": -8.0030},
                {"name": "El Badi Palace", "tags": ["history & culture", "architecture", "photography"], "best_time": ["morning", "afternoon"], "lat": 31.6181, "lon": -7.9864},
                {"name": "Medersa Ben Youssef", "tags": ["history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 31.6328, "lon": -7.9861},
                {"name": "Dar Si Said Museum", "tags": ["museums & art", "history & culture"], "best_time": ["afternoon"], "lat": 31.6250, "lon": -7.9860},
                {"name": "Menara Gardens", "tags": ["parks & outdoors", "views", "photography"], "best_time": ["morning", "evening"], "lat": 31.6178, "lon": -8.0225},
                {"name": "Cyber Park Arsat Moulay Abdeslam", "tags": ["parks & outdoors", "relaxation"], "best_time": ["morning"], "lat": 31.6250, "lon": -8.0000},
                {"name": "Royal Palace of Marrakech", "tags": ["architecture", "history & culture"], "best_time": ["morning"], "lat": 31.6200, "lon": -7.9900},
                {"name": "Herborist of the Paradis", "tags": ["wellness & spa", "shopping", "culture"], "best_time": ["afternoon"], "lat": 31.6300, "lon": -7.9800},
            ],
            "museums": [
                {"name": "Marrakech Museum", "tags": ["museums & art", "history & culture", "architecture"], "best_time": ["morning", "afternoon"], "lat": 31.6310, "lon": -7.9860},
                {"name": "Dar Si Said Museum", "tags": ["museums & art", "history & culture", "crafts"], "best_time": ["afternoon"], "lat": 31.6250, "lon": -7.9860},
                {"name": "Musée Yves Saint Laurent Marrakech", "tags": ["museums & art", "fashion", "art galleries"], "best_time": ["afternoon"], "lat": 31.6418, "lon": -8.0030},
                {"name": "Photography Museum of Marrakech", "tags": ["museums & art", "photography", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 31.6300, "lon": -7.9850},
                {"name": "House of Photography", "tags": ["museums & art", "photography"], "best_time": ["afternoon"], "lat": 31.6325, "lon": -7.9875},
            ],
            "markets": [
                {"name": "Souk Semmarine", "tags": ["local markets", "shopping", "crafts"], "lat": 31.6280, "lon": -7.9880},
                {"name": "Rahba Kedima (Spice Square)", "tags": ["local markets", "food & drink", "culture"], "lat": 31.6300, "lon": -7.9860},
                {"name": "Marrakech Souks", "tags": ["local markets", "shopping", "crafts", "culture"], "lat": 31.6280, "lon": -7.9880},
                {"name": "Ensemble Artisanal", "tags": ["local markets", "crafts", "shopping"], "lat": 31.6150, "lon": -7.9900},
            ],
            "food": [
                {"name": "Nomad", "tags": ["local cuisine", "modern moroccan", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 31.6295, "lon": -7.9860},
                {"name": "Le Jardin", "tags": ["local cuisine", "medina", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 31.6310, "lon": -7.9850},
                {"name": "Café des Épices", "tags": ["local cuisine", "café", "lunch"], "best_time": ["afternoon"], "lat": 31.6300, "lon": -7.9865},
                {"name": "Terrasse des Épices", "tags": ["local cuisine", "views", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 31.6295, "lon": -7.9865},
                {"name": "Al Fassia", "tags": ["local cuisine", "moroccan", "fine dining", "dinner"], "best_time": ["evening"], "lat": 31.6400, "lon": -8.0100},
                {"name": "Comptoir Darna", "tags": ["local cuisine", "moroccan", "dinner", "entertainment"], "best_time": ["evening"], "lat": 31.6350, "lon": -8.0050},
                {"name": "Grand Café de la Poste", "tags": ["french", "moroccan", "breakfast", "lunch"], "best_time": ["morning", "afternoon"], "lat": 31.6305, "lon": -8.0080},
                {"name": "La Famille", "tags": ["vegetarian", "local cuisine", "lunch"], "best_time": ["afternoon"], "lat": 31.6315, "lon": -7.9860},
                {"name": "Henna Art Café", "tags": ["coffee & cafés", "culture", "breakfast", "lunch"], "best_time": ["morning", "afternoon"], "lat": 31.6320, "lon": -7.9870},
                {"name": "Café Clock", "tags": ["local cuisine", "international", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 31.6340, "lon": -7.9855},
            ],
            "neighborhoods": [
                {"name": "Medina", "tags": ["history & culture", "local markets", "food & drink"], "lat": 31.6280, "lon": -7.9880},
                {"name": "Kasbah", "tags": ["history & culture", "architecture", "food & drink"], "lat": 31.6170, "lon": -7.9880},
                {"name": "Gueliz (New Town)", "tags": ["shopping", "food & drink", "modern"], "lat": 31.6350, "lon": -8.0100},
                {"name": "Hivernage", "tags": ["luxury", "nightlife", "food & drink"], "lat": 31.6250, "lon": -8.0050},
                {"name": "Palmeraie", "tags": ["parks & outdoors", "luxury", "relaxation"], "lat": 31.6600, "lon": -7.9800},
            ],
            "day_trips": [
                {"name": "Atlas Mountains Day Trip (Imlil Valley)", "tags": ["nature & wildlife", "hiking & adventure", "day trip", "views"], "best_time": ["morning", "afternoon"], "lat": 31.1326, "lon": -7.9198},
                {"name": "Ouzoud Waterfalls", "tags": ["nature & wildlife", "hiking & adventure", "day trip"], "best_time": ["morning", "afternoon"], "lat": 32.0150, "lon": -6.7200},
                {"name": "Essaouira Day Trip", "tags": ["beach", "history & culture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 31.5085, "lon": -9.7595},
                {"name": "Ourika Valley", "tags": ["nature & wildlife", "hiking & adventure", "day trip", "culture"], "best_time": ["morning", "afternoon"], "lat": 31.3700, "lon": -7.7800},
                {"name": "Ait Benhaddou", "tags": ["history & culture", "architecture", "unesco", "day trip"], "best_time": ["morning", "afternoon"], "lat": 31.0470, "lon": -7.1300},
                {"name": "Agafay Desert", "tags": ["nature & wildlife", "adventure", "day trip"], "best_time": ["afternoon", "evening"], "lat": 31.4500, "lon": -8.1500},
            ],
            "hotels": [
                {"name": "La Mamounia", "price": "~MAD 5,500", "location": "Medina", "highlights": "Iconic palace hotel and gardens near the medina walls"},
                {"name": "Riad Yasmine", "price": "~MAD 1,200", "location": "Medina", "highlights": "Intimate boutique riad with pool"},
                {"name": "Hotel Les Jardins de la Koutoubia", "price": "~MAD 1,800", "location": "Medina", "highlights": "Spacious rooms near Jemaa el-Fnaa"},
                {"name": "Radisson Blu Marrakech", "price": "~MAD 1,400", "location": "Gueliz", "highlights": "Modern hotel close to Gueliz shops and restaurants"},
                {"name": "Ibis Marrakech Centre Gare", "price": "~MAD 550", "location": "Gueliz", "highlights": "Budget hotel near the train station"},
            ],
        },
        "casablanca": {
            "attractions": [
                {"name": "Hassan II Mosque", "tags": ["architecture", "history & culture", "photography"], "best_time": ["morning", "afternoon"], "lat": 33.6088, "lon": -7.6328},
                {"name": "Corniche Ain Diab", "tags": ["beach", "parks & outdoors", "food & drink"], "best_time": ["afternoon", "evening"], "lat": 33.5938, "lon": -7.6637},
                {"name": "Morocco Mall", "tags": ["shopping", "food & drink"], "best_time": ["afternoon"], "lat": 33.5926, "lon": -7.6506},
                {"name": "Quartier Habous", "tags": ["history & culture", "shopping", "architecture"], "best_time": ["morning", "afternoon"], "lat": 33.5831, "lon": -7.6113},
                {"name": "Mahkama du Pacha", "tags": ["history & culture", "architecture"], "best_time": ["morning"], "lat": 33.5800, "lon": -7.6150},
                {"name": "Casablanca Cathedral (Sacré-Cœur)", "tags": ["architecture", "history & culture", "photography"], "best_time": ["morning"], "lat": 33.5850, "lon": -7.6200},
                {"name": "Villa des Arts", "tags": ["art galleries", "museums & art", "culture"], "best_time": ["afternoon"], "lat": 33.5850, "lon": -7.6300},
                {"name": "Parc de la Ligue Arabe", "tags": ["parks & outdoors", "relaxation"], "best_time": ["morning", "afternoon"], "lat": 33.5775, "lon": -7.6197},
                {"name": "Casablanca Central Market (Marché Central)", "tags": ["local markets", "food & drink", "culture"], "best_time": ["morning"], "lat": 33.5890, "lon": -7.6100},
                {"name": "Twin Center", "tags": ["architecture", "views", "shopping"], "best_time": ["afternoon"], "lat": 33.5857, "lon": -7.6322},
            ],
            "museums": [
                {"name": "Museum of Moroccan Judaism", "tags": ["museums & art", "history & culture"], "best_time": ["morning", "afternoon"], "lat": 33.5700, "lon": -7.6400},
                {"name": "Villa des Arts", "tags": ["museums & art", "art galleries"], "best_time": ["afternoon"], "lat": 33.5850, "lon": -7.6300},
                {"name": "Mohammed VI Museum of Modern and Contemporary Art", "tags": ["museums & art", "art galleries"], "best_time": ["morning", "afternoon"], "lat": 33.6000, "lon": -7.6200},
            ],
            "markets": [
                {"name": "Casablanca Central Market", "tags": ["local markets", "food & drink"], "lat": 33.5890, "lon": -7.6100},
                {"name": "Quartier Habous Market", "tags": ["local markets", "shopping", "crafts"], "lat": 33.5831, "lon": -7.6113},
                {"name": "Morocco Mall", "tags": ["shopping", "food & drink"], "lat": 33.5926, "lon": -7.6506},
            ],
            "food": [
                {"name": "La Sqala", "tags": ["local cuisine", "seafood", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 33.6050, "lon": -7.6300},
                {"name": "Le Petit Roche", "tags": ["seafood", "local cuisine", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 33.6000, "lon": -7.6350},
                {"name": "Restaurant du Port de Pêche", "tags": ["seafood", "local cuisine", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 33.6030, "lon": -7.6200},
                {"name": "Café Maure", "tags": ["coffee & cafés", "sweets & desserts"], "best_time": ["morning", "afternoon"], "lat": 33.5830, "lon": -7.6100},
                {"name": "Al Mounia", "tags": ["local cuisine", "moroccan", "dinner"], "best_time": ["evening"], "lat": 33.5840, "lon": -7.6200},
                {"name": "Bondi Coffee Kitchen", "tags": ["coffee & cafés", "breakfast"], "best_time": ["morning"], "lat": 33.5900, "lon": -7.6500},
                {"name": "Taverne du Dauphin", "tags": ["seafood", "french", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 33.6020, "lon": -7.6250},
                {"name": "L'Entrecôte Café de Paris", "tags": ["steakhouse", "french", "lunch", "dinner"], "best_time": ["afternoon", "evening"], "lat": 33.5850, "lon": -7.6300},
            ],
            "neighborhoods": [
                {"name": "Quartier Habous", "tags": ["history & culture", "shopping", "architecture"], "lat": 33.5831, "lon": -7.6113},
                {"name": "Ain Diab", "tags": ["beach", "food & drink", "nightlife"], "lat": 33.5938, "lon": -7.6637},
                {"name": "City Centre", "tags": ["shopping", "architecture", "business"], "lat": 33.5731, "lon": -7.5898},
                {"name": "Anfa", "tags": ["residential", "upscale", "dining"], "lat": 33.5800, "lon": -7.6400},
            ],
            "day_trips": [
                {"name": "Rabat Day Trip", "tags": ["history & culture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 34.0209, "lon": -6.8417},
                {"name": "El Jadida Day Trip", "tags": ["beach", "history & culture", "day trip"], "best_time": ["morning", "afternoon"], "lat": 33.2540, "lon": -8.5060},
                {"name": "Azemmour Day Trip", "tags": ["history & culture", "photography", "day trip"], "best_time": ["morning", "afternoon"], "lat": 33.2890, "lon": -8.3430},
                {"name": "Bouskoura Forest", "tags": ["nature & wildlife", "parks & outdoors", "day trip"], "best_time": ["morning", "afternoon"], "lat": 33.4500, "lon": -7.6700},
            ],
            "hotels": [
                {"name": "Ibis Casablanca City Center", "price": "~MAD 700", "location": "City Centre", "highlights": "Budget-friendly hotel near Casa-Voyageurs station"},
                {"name": "Hotel Club Val d'Anfa", "price": "~MAD 1,200", "location": "Anfa", "highlights": "Beachside hotel with pool and garden"},
                {"name": "Four Seasons Hotel Casablanca", "price": "~MAD 3,500", "location": "Ain Diab", "highlights": "Luxury oceanfront resort"},
                {"name": "Movenpick Hotel Casablanca", "price": "~MAD 1,600", "location": "City Centre", "highlights": "Modern hotel near Hassan II Mosque"},
            ],
        },
    }
    data = places.get(city, {})
    return data.get(kind, [])[:limit]


def _osm_places(city: str, country: str, kind: str, limit: int = 20,
                latlon: Optional[Tuple[float, float]] = None) -> List[Dict]:
    """Fetch points of interest from OpenStreetMap Overpass API around city centre.
    Filters out generic / low-quality names and tags results for the scheduler."""
    if latlon is None:
        latlon = geocode_city(city, country)
    if not latlon:
        return []
    lat, lon = latlon
    radius = 12000
    kind_queries = {
        "attractions": """(
  node(around:{radius},{lat},{lon})["tourism"~"attraction|viewpoint|zoo|theme_park|aquarium"];
  way(around:{radius},{lat},{lon})["tourism"~"attraction|viewpoint|zoo|theme_park|aquarium"];
);""",
        "museums": """(
  node(around:{radius},{lat},{lon})["tourism"~"museum|gallery"];
  way(around:{radius},{lat},{lon})["tourism"~"museum|gallery"];
);""",
        "markets": """(
  node(around:{radius},{lat},{lon})["shop"~"mall|department_store|market"];
  node(around:{radius},{lat},{lon})["amenity"="marketplace"];
  way(around:{radius},{lat},{lon})["shop"~"mall|department_store|market"];
);""",
        "food": """(
  node(around:{radius},{lat},{lon})["amenity"~"restaurant|cafe|fast_food"]["name"];
  way(around:{radius},{lat},{lon})["amenity"~"restaurant|cafe|fast_food"]["name"];
);""",
        "neighborhoods": """(
  node(around:{radius},{lat},{lon})["place"~"suburb|neighbourhood|quarter"];
);""",
        "day_trips": """(
  node(around:80000,{lat},{lon})["tourism"~"attraction|viewpoint|zoo|theme_park"]["name"];
  way(around:80000,{lat},{lon})["tourism"~"attraction|viewpoint|zoo|theme_park"]["name"];
);""",
        "hotels": """(
  node(around:{radius},{lat},{lon})["tourism"~"hotel|guest_house"]["name"];
  way(around:{radius},{lat},{lon})["tourism"~"hotel|guest_house"]["name"];
);""",
    }
    q = kind_queries.get(kind, kind_queries["attractions"])
    query = f"[out:json][timeout:15];\n{q.format(radius=radius, lat=lat, lon=lon)}\nout center {limit};"
    cfg = _OSM_TIMEOUTS
    for attempt in range(cfg["retries"] + 1):
        try:
            r = requests.get(
                "https://overpass-api.de/api/interpreter",
                params={"data": query},
                timeout=(cfg["connect"], cfg["read"]),
                headers={"Accept": "application/json", "User-Agent": "ozmoeg-trip-planner/1.0"},
            )
            r.raise_for_status()
            break
        except Exception as e:
            print(f"OSM attempt {attempt+1} failed for {city}/{kind}: {e}")
            if attempt == cfg["retries"]:
                return []
            time.sleep(cfg["retry_delay"])
    data = r.json()
    out = []
    blocked_prefixes = ("entrance", "exit", "gate", "ticket", "information", "office", "wc", "toilet", "restroom", "parking", "access", "animal ", "aviary", "reptile house", "aquarium tank")
    blocked_words = ("house", "shop", "store", " unnamed", "unknown")
    for e in data.get("elements", []):
        t = e.get("tags", {})
        name = (t.get("name") or t.get("name:en") or "").strip()
        if not name or len(name) < 3:
            continue
        name_lower = name.lower()
        if any(name_lower.startswith(p) for p in blocked_prefixes):
            continue
        if any(w in name_lower for w in blocked_words):
            continue
        tourism = t.get("tourism", "")
        amenity = t.get("amenity", "")
        shop = t.get("shop", "")
        place = t.get("place", "")
        cuisine = t.get("cuisine", "")
        place_tags = [x for x in (tourism, amenity, shop, place, kind, cuisine) if x]
        out.append({
            "name": name,
            "city": city,
            "tags": list(set(place_tags)),
            "indoor": kind in ("museums",),
            "best_time": ["morning", "afternoon", "evening"],
            "kid_friendly": kind not in ("bar", "pub") and "pub" not in amenity.lower() and "bar" not in amenity.lower(),
        })
    return out[:limit]


def fetch_transit_options(cities: List[Dict], country: str = "") -> List[str]:
    """Return transport option labels for inter-city transfers."""
    options = []
    if len(cities) <= 1:
        return options
    country_l = (country or cities[0].get("country", "")).lower()
    if "japan" in country_l:
        options.extend(["Shinkansen 2.5Hrs", "Train 2.5Hrs", "Flight 1Hrs"])
        return options
    elif "united states" in country_l or "canada" in country_l or "australia" in country_l:
        options.extend(["Flight 2.5Hrs", "Car 5Hrs", "Train 8Hrs"])
        return options
    elif "united kingdom" in country_l or "france" in country_l or "italy" in country_l or "spain" in country_l or "germany" in country_l:
        options.extend(["Train 2.5Hrs", "Flight 1.5Hrs", "Car 4Hrs"])
        return options
    elif "malaysia" in country_l:
        options.extend(["Flight 55min", "Bus 5hrs", "Car 4hrs", "Train 4hrs"])
        return options
    elif "fiji" in country_l:
        options.extend(["Flight 35min", "Bus 4hrs", "Ferry 3hrs", "Car 3.5hrs"])
        return options
    else:
        options.extend(["Flight 2.5Hrs", "Train 4Hrs", "Bus 6Hrs", "Car 4Hrs"])
        return options

if __name__ == "__main__":
    # Smoke test
    print(geocode_city("Tokyo", "Japan"))
    print(fetch_weather(35.68, 139.76, "2025-06-12", "2025-06-16")[:3])
    print(fetch_places("Tokyo", "Japan", "attractions", ["temples", "food"], [40, 38, 12, 9])[:3])
    print(fetch_transit_options([{"city": "Tokyo"}, {"city": "Kyoto"}]))
