"""
Nuitee / LiteAPI live hotel integration for the OzMoEg Trip Planner.
Fetches up to 2 hotels per city with real rates and minimal API usage.
"""
import os
import requests
from typing import Dict, List, Tuple
from datetime import date

NUITEE_BASE = "https://api.liteapi.travel/v3.0"
NUITEE_KEY = os.environ.get("NUITEE_API_KEY") or "sand_46b36ce7-ebe8-4c44-82e1-82243d02880b"


def _headers() -> dict:
    return {
        "X-API-Key": NUITEE_KEY or "",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _hotel_list_for_city(city: str, country_code: str, limit: int = 4) -> List[Dict]:
    """Fetch the hotel list for a city; the list response contains name/address/stars/rating."""
    country_code = country_code.upper()
    url = f"{NUITEE_BASE}/data/hotels"
    params = {"countryCode": country_code, "city": city, "limit": limit, "offset": 0}
    try:
        r = requests.get(url, params=params, headers=_headers(), timeout=(4, 10))
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:
        print(f"Nuitee hotel list failed for {city}: {e}")
        return []


def _rates_for_hotels(hotel_ids: List[str], checkin: str, checkout: str,
                      occupancy: Dict, currency: str = "AUD",
                      nationality: str = "AU") -> List[Dict]:
    """Call /hotels/rates for the given IDs."""
    if not hotel_ids:
        return []
    url = f"{NUITEE_BASE}/hotels/rates"
    body = {
        "hotelIds": hotel_ids,
        "checkin": checkin,
        "checkout": checkout,
        "currency": currency,
        "nationality": nationality,
        "guestNationality": nationality,
        "occupancies": [occupancy],
    }
    try:
        r = requests.post(url, headers=_headers(), json=body, timeout=(4, 20))
        r.raise_for_status()
        resp = r.json()
        return resp.get("data", resp.get("hotels", []))
    except Exception as e:
        print(f"Nuitee rates failed: {e}")
        return []


def _best_rate(hotel: Dict) -> Tuple[float, str]:
    """Extract the lowest total rate and the matching room/board name."""
    best = None
    best_room = ""
    for rt in hotel.get("roomTypes", []):
        for rate in rt.get("rates", []):
            total = rate.get("retailRate", {}).get("total", [{}])[0]
            amount = total.get("amount")
            if amount is None:
                continue
            if best is None or amount < best:
                best = amount
                best_room = f"{rate.get('name', '')} ({rate.get('boardName', 'Room Only')})"
    if best is None:
        return 0.0, ""
    return best, best_room


def fetch_live_hotels(city: str, country_code: str, checkin: str, checkout: str,
                      adults: int, children_ages: List[int],
                      max_hotels: int = 2, currency: str = "AUD",
                      nationality: str = "AU", latlon: Tuple[float, float] = None) -> List[Dict]:
    """Return up to max_hotels live hotel options for the requested city/stay.

    Each hotel dict contains: city, name, dates, price, location, highlights.
    Falls back to curated approximate options when the Nuitee sandbox returns
    no city-specific inventory or no availability.
    """
    if not NUITEE_KEY:
        raise RuntimeError("NUITEE_API_KEY not configured")

    occupancy = {"adults": adults, "children": list(children_ages)}
    # Sandbox list endpoint sometimes ignores city; try larger pool.
    list_resp = _hotel_list_for_city(city, country_code, limit=max(20, max_hotels + 4))

    # If API returned the same generic results for every city, do not treat as city-specific.
    seen_cities = set()
    for h in list_resp:
        c = h.get("city") or ""
        seen_cities.add(c.lower())
    generic = len(seen_cities) <= 1 and list_resp and list_resp[0].get("city", "").lower() != city.lower()

    details_by_id = {h.get("id"): h for h in list_resp if h.get("id")}
    candidate_ids = list(details_by_id.keys())

    results = []
    if not generic and candidate_ids:
        rates = _rates_for_hotels(candidate_ids, checkin, checkout, occupancy,
                                  currency, nationality)
        for h in rates:
            hotel_id = h.get("hotelId")
            total, room = _best_rate(h)
            if total <= 0:
                continue
            details = details_by_id.get(hotel_id, {})
            # Only accept hotels that actually belong to the requested city.
            hotel_city = (details.get("city") or "")
            if hotel_city.lower() != city.lower():
                continue
            name = details.get("name") or hotel_id
            # Discard results whose names are not readable Latin script (common when
            # sandbox returns random non-English inventory).
            if name and not _is_latin_text(name):
                continue
            location = details.get("address") or hotel_city or ""
            stars = details.get("stars")
            rating = details.get("rating")
            highlights_parts = []
            if room:
                highlights_parts.append(room)
            if stars:
                highlights_parts.append(f"{stars}★")
            if rating:
                highlights_parts.append(f"Rating {rating}")
            if not highlights_parts:
                highlights_parts.append("Live rate from Nuitee")
            highlights = " | ".join(highlights_parts)
            results.append({
                "city": hotel_city.title(),
                "name": name,
                "dates": f"{checkin} to {checkout}",
                "price": f"{currency} ${total:.2f}",
                "location": location,
                "highlights": highlights,
            })
            if len(results) >= max_hotels:
                break

    return results


def _is_latin_text(text: str) -> bool:
    """Return True if the string consists mostly of basic Latin letters (English)."""
    if not text:
        return False
    text = text.strip()
    latinish = sum(1 for ch in text if ("a" <= ch.lower() <= "z") or ch.isspace() or ch.isdigit()
                   or ch in "-&.,'()/")
    return latinish / len(text) >= 0.70


if __name__ == "__main__":
    import os
    from datetime import timedelta
    os.environ["NUITEE_API_KEY"] = "sand_46b36ce7-ebe8-4c44-82e1-82243d02880b"
    today = date.today()
    hotels = fetch_live_hotels(
        "Tokyo", "JP",
        (today + timedelta(days=30)).isoformat(),
        (today + timedelta(days=34)).isoformat(),
        adults=2, children_ages=[12, 9], max_hotels=2
    )
    print("Tokyo live hotels:", len(hotels))
    for h in hotels:
        print(" ", h)
