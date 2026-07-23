"""Generate curated English place datasets for unknown cities via LLM.

Three-tier fallback:
1. Local Ollama endpoint (http://192.168.1.108:11434/v1 by default).
2. Cloud OpenAI-compatible fallback if Ollama is unreachable/empty.
3. Generic safe template if both fail.

Every successful generation is cached to disk under cached_cities/ so future
requests never hit the LLM again for the same city.
"""
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

CACHE_DIR = Path(__file__).parent / "cached_cities"
CACHE_DIR.mkdir(exist_ok=True)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://192.168.1.108:11434/v1")
CLOUD_BASE_URL = os.environ.get("CLOUD_BASE_URL", "")
CLOUD_API_KEY = os.environ.get("CLOUD_API_KEY", "")
CLOUD_MODEL = os.environ.get("CLOUD_MODEL", "kimi-k2.7-code:cloud")

_LOCK = threading.Lock()


def _cached_path(city: str, country: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{country}_{city}").lower().strip("_")
    return CACHE_DIR / f"{safe}.json"


def load_cached(city: str, country: str) -> Optional[Dict]:
    path = _cached_path(city, country)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data and any(data.get(k) for k in ("attractions", "museums", "food")):
                return data
        except Exception:
            pass
    return None


def save_cached(city: str, country: str, data: Dict) -> None:
    path = _cached_path(city, country)
    try:
        with _LOCK:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to cache dataset for {city}: {e}")


def _call_openai_compatible(base_url: str, api_key: str, model: str, messages: List[Dict], timeout: int = 120, max_tokens: int = 4000) -> Optional[str]:
    import urllib.request
    import ssl

    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if isinstance(content, str):
            content = content.strip()
            # Strip markdown code fences
            if content.startswith("```"):
                content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
            return content.strip()
    except Exception as e:
        print(f"LLM call failed for {model} at {base_url}: {e}")
    return None


def _call_ollama(messages: List[Dict], timeout: int = 120, max_tokens: int = 4000) -> Optional[str]:
    return _call_openai_compatible(OLLAMA_BASE_URL, "", "kimi-k2.7-code:cloud", messages, timeout=timeout, max_tokens=max_tokens)


def _call_cloud(messages: List[Dict], timeout: int = 120, max_tokens: int = 4000) -> Optional[str]:
    if not CLOUD_BASE_URL or not CLOUD_API_KEY:
        return None
    return _call_openai_compatible(CLOUD_BASE_URL, CLOUD_API_KEY, CLOUD_MODEL, messages, timeout=timeout, max_tokens=max_tokens)


def _system_prompt() -> str:
    return (
        "You are a travel-data generator. Output strictly valid JSON only, no markdown, "
        "no explanation, no reasoning tags. Produce English names only. "
        "Every place must include realistic lat and lon coordinates (decimal degrees)."
    )


def _user_prompt(city: str, country: str, ages: List[int]) -> str:
    return (
        f"Generate a compact travel dataset for {city}, {country} as a single JSON object with these keys:\n"
        "  attractions: 8 famous sightseeing spots (name, tags list, best_time list, lat, lon).\n"
        "  museums: 3 notable museums/galleries (name, tags, best_time, lat, lon).\n"
        "  markets: 3 markets/shopping areas (name, tags, best_time, lat, lon).\n"
        "  food: 6 restaurants/cafes (name, tags, best_time, lat, lon).\n"
        "  neighborhoods: 3 well-known districts (name, tags, lat, lon).\n"
        "  day_trips: 3 day-trip destinations near the city (name, tags, best_time, lat, lon).\n"
        "  hotels: 3 realistic hotels (name, price string like '~XXX', location, highlights).\n"
        f"Ages: {ages}. Keep entries concise and output valid JSON only. Coordinates must be realistic."
    )


def _normalize_dataset(raw: Dict, city: str, country: str) -> Dict:
    """Validate shape, inject city/country, and guarantee every section exists."""
    out = {}
    for key in ("attractions", "museums", "markets", "food", "neighborhoods", "day_trips", "hotels"):
        items = raw.get(key, [])
        if not isinstance(items, list):
            items = []
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            # Strip non-English/Arabic apartment listings heuristically
            if any(ord(ch) > 0x0600 and ord(ch) < 0x06FF for ch in name):
                continue
            # Ensure lat/lon present for non-hotel items
            if key != "hotels":
                try:
                    lat = float(item.get("lat", 0))
                    lon = float(item.get("lon", 0))
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        continue
                    item["lat"] = lat
                    item["lon"] = lon
                except Exception:
                    continue
            item["city"] = city
            item["country"] = country
            cleaned.append(item)
        out[key] = cleaned
    return out


def _generic_template(city: str, country: str) -> Dict:
    """Absolute last-resort generic English template so generation never hard-fails."""
    return {
        "attractions": [
            {"name": f"{city} City Centre Walk", "tags": ["walks", "views"], "best_time": ["morning", "evening"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
            {"name": f"Historic Quarter of {city}", "tags": ["history & culture"], "best_time": ["morning", "afternoon"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
            {"name": f"{city} Main Park", "tags": ["park", "kids friendly"], "best_time": ["morning"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
            {"name": f"{city} Waterfront / Promenade", "tags": ["views", "walks"], "best_time": ["evening"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
        ],
        "museums": [
            {"name": f"{city} National Museum", "tags": ["history & culture", "museum"], "best_time": ["morning", "afternoon"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
            {"name": f"{city} Art Gallery", "tags": ["art", "culture"], "best_time": ["afternoon"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
        ],
        "markets": [
            {"name": f"{city} Central Market", "tags": ["market", "shopping", "food & drink"], "best_time": ["afternoon", "evening"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
            {"name": f"{city} Modern Mall", "tags": ["shopping", "entertainment"], "best_time": ["afternoon"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
        ],
        "food": [
            {"name": f"Local Restaurant {city}", "tags": ["local cuisine", "lunch", "dinner"], "best_time": ["lunch", "dinner"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
            {"name": f"{city} Family Cafe", "tags": ["cafe", "breakfast", "lunch"], "best_time": ["morning", "afternoon"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
            {"name": f"{city} Street Food Spot", "tags": ["street food", "dinner"], "best_time": ["dinner"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
        ],
        "neighborhoods": [
            {"name": f"Downtown {city}", "tags": ["business", "hotels", "dining"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
            {"name": f"Old Town {city}", "tags": ["history", "walks"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
        ],
        "day_trips": [
            {"name": f"Day trip from {city}", "tags": ["nature", "day trip"], "best_time": ["morning"], "lat": 0.0, "lon": 0.0, "city": city, "country": country},
        ],
        "hotels": [
            {"name": f"{city} Grand Hotel", "price": "~local rate", "location": "City centre", "highlights": "Central hotel — verify current rates"},
            {"name": f"{city} Boutique Stay", "price": "~local rate", "location": "Old town", "highlights": "Mid-range option — verify current rates"},
        ],
    }


def generate_city_dataset(city: str, country: str, ages: List[int] = None, timeout_ollama: int = 120, timeout_cloud: int = 90) -> Dict:
    """Return a full dataset for a city, using cache/LLM/generic template."""
    ages = ages or []

    cached = load_cached(city, country)
    if cached:
        # If cached is a generic zero-coord fallback, allow a retry
        non_zero = any(
            p.get("lat", 0) != 0.0 and p.get("lon", 0) != 0.0
            for key, places in cached.items()
            if key != "hotels"
            for p in places
        )
        if non_zero:
            return cached

    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": _user_prompt(city, country, ages)},
    ]

    raw_text = None
    # Tier 1: Ollama
    raw_text = _call_ollama(messages, timeout=timeout_ollama, max_tokens=8000)
    # Tier 2: Cloud fallback
    if not raw_text:
        raw_text = _call_cloud(messages, timeout=timeout_cloud, max_tokens=8000)

    if raw_text:
        try:
            # Extract JSON from possible surrounding text
            start = raw_text.find("{")
            end = raw_text.rfind("}")
            if start != -1 and end != -1 and end > start:
                raw_text = raw_text[start:end+1]
            raw = json.loads(raw_text)
            data = _normalize_dataset(raw, city, country)
            if any(data.get(k) for k in ("attractions", "museums", "food")):
                # Only cache if we got real coordinates from the LLM
                non_zero = any(
                    p.get("lat", 0) != 0.0 and p.get("lon", 0) != 0.0
                    for key, places in data.items()
                    if key != "hotels"
                    for p in places
                )
                if non_zero:
                    save_cached(city, country, data)
                return data
        except Exception as e:
            print(f"LLM dataset parse failed for {city}: {e}")

    # Tier 3: generic safe template
    data = _generic_template(city, country)
    return data


def list_cached_cities() -> List[str]:
    try:
        return sorted([p.stem for p in CACHE_DIR.glob("*.json")])
    except Exception:
        return []
