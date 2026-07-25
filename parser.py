"""
Natural language / chat parser for trip planner input.
Extracts structured trip request from free text or voice transcript.
"""
import re
from datetime import datetime, timedelta
from typing import Dict, List


def _extract_country(text: str, cities: List[str]) -> str:
    """Naive country extraction."""
    text_lower = text.lower()
    country_hints = {
        "japan": "Japan", "france": "France", "italy": "Italy",
        "spain": "Spain", "greece": "Greece", "thailand": "Thailand",
        "vietnam": "Vietnam", "turkey": "Turkey", "morocco": "Morocco",
        "egypt": "Egypt", "uae": "United Arab Emirates", "dubai": "United Arab Emirates",
        "usa": "United States", "uk": "United Kingdom", "australia": "Australia",
    }
    for hint, country in country_hints.items():
        if hint in text_lower:
            return country

    city_country = {
        "Tokyo": "Japan", "Kyoto": "Japan", "Osaka": "Japan",
        "Paris": "France", "Lyon": "France", "Nice": "France",
        "Rome": "Italy", "Florence": "Italy", "Venice": "Italy",
        "Barcelona": "Spain", "Madrid": "Spain",
        "Athens": "Greece",
        "Bangkok": "Thailand", "Phuket": "Thailand",
        "Hanoi": "Vietnam",
        "Istanbul": "Turkey",
        "Marrakech": "Morocco",
        "Cairo": "Egypt",
        "Dubai": "United Arab Emirates",
        "New York": "United States", "Los Angeles": "United States",
        "London": "United Kingdom", "Edinburgh": "United Kingdom",
        "Sydney": "Australia", "Melbourne": "Australia", "Brisbane": "Australia",
    }
    for city in cities:
        if city in city_country:
            return city_country[city]
    return "Unknown Country"


def _extract_cities(text: str) -> List[Dict]:
    """Extract city names (case-insensitive, robust to typos)."""
    text_lower = text.lower()
    known_cities = ["tokyo", "kyoto", "osaka", "nara", "yokohama", "sapporo",
                    "paris", "lyon", "nice", "marseille",
                    "rome", "florence", "venice", "milan",
                    "barcelona", "madrid", "seville",
                    "athens", "santorini",
                    "bangkok", "phuket", "chiang mai",
                    "hanoi", "ho chi minh city", "da nang",
                    "istanbul", "antalya", "cappadocia", "izmir",
                    "marrakech", "fes", "casablanca",
                    "cairo", "luxor", "alexandria",
                    "dubai", "abu dhabi", "doha",
                    "new york", "los angeles", "san francisco", "las vegas",
                    "london", "edinburgh", "manchester",
                    "sydney", "melbourne", "brisbane",
                    "singapore", "kuala lumpur", "oslo", "bali"]
    found = []
    for city in known_cities:
        # Whole-word match; 'antalya' and 'instanbul' variants handled separately below
        if re.search(r"\b" + re.escape(city) + r"\b", text_lower):
            title = " ".join(p.capitalize() for p in city.split())
            if title not in [c["city"] for c in found]:
                found.append({"city": title})

    # Handle common misspellings of major cities
    misspellings = {
        "instanbul": "Istanbul",
        "istanubl": "Istanbul",
        "antaly": "Antalya",
        "antalia": "Antalya",
    }
    for typo, correct in misspellings.items():
        if typo in text_lower and correct not in [c["city"] for c in found]:
            found.append({"city": correct})

    return found


def _extract_dates(text: str, cities: List[Dict]) -> List[Dict]:
    """Extract dates from text (ISO, slash, dash, and natural phrases) and assign consecutive ranges to cities."""
    text_lower = text.lower()
    raw_dates = []

    # ISO/short numeric formats
    patterns = [r"(\d{4}-\d{2}-\d{2})", r"(\d{2}/\d{2}/\d{4})", r"(\d{2}-\d{2}-\d{4})"]
    for pat in patterns:
        for match in re.findall(pat, text):
            try:
                if "-" in match and len(match.split("-")[0]) == 4:
                    d = datetime.strptime(match, "%Y-%m-%d").date()
                elif "/" in match:
                    d = datetime.strptime(match, "%d/%m/%Y").date()
                else:
                    d = datetime.strptime(match, "%d-%m-%Y").date()
                raw_dates.append(d.isoformat())
            except Exception:
                pass

    # Natural-language date phrases like "1st of September" or "1st September".
    # We only parse if a year is also present nearby.
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
        "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    year_match = re.search(r"\b(20\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else datetime.today().year
    # Find all day-of-month references with month name nearby
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?([a-z]+)\b", text_lower):
        day = int(m.group(1))
        month = month_names.get(m.group(2))
        if month and 1 <= day <= 31:
            try:
                raw_dates.append(datetime(year, month, day).date().isoformat())
            except Exception:
                pass

    raw_dates = sorted(set(raw_dates))

    if len(raw_dates) >= 2 and len(cities) >= 1:
        start = datetime.strptime(raw_dates[0], "%Y-%m-%d").date()
        end = datetime.strptime(raw_dates[-1], "%Y-%m-%d").date()
        total_days = (end - start).days
        base = total_days // len(cities)
        extra = total_days % len(cities)
        cur = start
        for i, city in enumerate(cities):
            days = base + (1 if i < extra else 0)
            city_start = cur
            city_end = cur + timedelta(days=days)
            city_end = min(city_end, end)
            city["start_date"] = city_start.isoformat()
            city["end_date"] = city_end.isoformat()
            cur = city_end + timedelta(days=1)
    elif len(raw_dates) == 1 and len(cities) >= 1:
        start = datetime.strptime(raw_dates[0], "%Y-%m-%d").date()
        for i, city in enumerate(cities):
            city["start_date"] = start.isoformat()
            city["end_date"] = (start + timedelta(days=2)).isoformat()
            start = start + timedelta(days=3)
    else:
        start = datetime.today().date() + timedelta(days=30)
        for city in cities:
            city["start_date"] = start.isoformat()
            city["end_date"] = (start + timedelta(days=2)).isoformat()
            start = start + timedelta(days=3)
    return cities


def _extract_travelers(text: str) -> List[Dict]:
    """Extract number of adults/children and ages."""
    m = re.search(r"(\d+)\s*adults?", text, re.IGNORECASE)
    adults = int(m.group(1)) if m else 2
    m = re.search(r"(\d+)\s*(?:children?|kids?)", text, re.IGNORECASE)
    children = int(m.group(1)) if m else 0

    def _parse_ages_near(keyword: str, limit: int) -> List[int]:
        # Find keyword position and capture the following tokens up to punctuation or next keyword
        idx = text.lower().find(keyword)
        if idx == -1:
            return []
        segment = text[idx + len(keyword):]
        # cut at next sentence or common stop keywords
        stop = re.search(r"(?i)\.(?=\s)|we\s|interests|love|i\s+love|food|my\s+name", segment)
        if stop:
            segment = segment[:stop.start()]
        # Extract all two-digit numbers
        nums = [int(n) for n in re.findall(r"\b(\d{1,3})\b", segment)]
        # Heuristic: keep only plausible human ages (3-99)
        return [n for n in nums if 3 <= n <= 99][:limit]

    adult_ages = _parse_ages_near("adults", adults)
    child_ages = _parse_ages_near("children", children) or _parse_ages_near("kids", children)

    travelers = []
    for i in range(adults):
        travelers.append({"age": adult_ages[i] if i < len(adult_ages) else 35, "name": "Adult"})
    for i in range(children):
        travelers.append({"age": child_ages[i] if i < len(child_ages) else 10, "name": "Child"})
    return travelers if travelers else [{"age": 35, "name": "Adult"}]


def _extract_interests(text: str) -> List[str]:
    text_lower = text.lower()
    interest_keywords = ["temples", "museums", "food", "anime", "nature", "parks",
                          "hiking", "beach", "shopping", "history", "art", "nightlife",
                          "architecture", "castles", "festivals", "food tours",
                          "culture", "sakura", "cherry blossom", "kids friendly",
                          "family friendly", "children", "kids", "theme parks",
                          "zoos", "aquariums", "playgrounds"]
    found = []
    for k in interest_keywords:
        if k in text_lower:
            if k in ("kids", "children") and "kids friendly" not in text_lower and "family friendly" not in text_lower:
                # 'children age X' is already handled by travelers; don't add as interest unless explicitly friendly
                continue
            found.append(k)
    if "kids friendly" in text_lower or "family friendly" in text_lower or "kids" in text_lower:
        if "kids friendly" not in found:
            found.append("kids friendly")
    # Clean redundant 'kids' keyword if we already captured 'kids friendly'
    found = [k for k in found if not (k == "kids" and "kids friendly" in found)]
    return found


def _extract_food_preferences(text: str) -> List[str]:
    text_lower = text.lower()
    food_keywords = ["sushi", "ramen", "halal", "vegetarian", "vegan", "seafood",
                     "beef", "street food", "fine dining", "local cuisine",
                     "gluten free", "kosher", "indian", "italian", "thai",
                     "sweet", "sweets", "dessert", "desserts", "healthy", "salads",
                     "fruit", "pastry", "baklava", "turkish delight"]
    return [k for k in food_keywords if k in text_lower]


def _extract_pace(text: str) -> str:
    text_lower = text.lower()
    if "compressed" in text_lower or "tight" in text_lower or "packed" in text_lower or "intense" in text_lower:
        return "compressed"
    if "relaxed" in text_lower or "slow" in text_lower or "easy" in text_lower or "leisurely" in text_lower:
        return "relaxed"
    return "relaxed"


def _extract_name_email(text: str) -> Dict:
    name = None
    email = None
    email_match = re.search(r"[\w.-]+@[\w.-]+\.\w+", text)
    if email_match:
        email = email_match.group(0)
    # simple name extraction: "my name is X"
    name_match = re.search(r"my\s+name\s+is\s+([A-Za-z\s]+)", text, re.IGNORECASE)
    if name_match:
        name = name_match.group(1).strip()
    return {"name": name, "email": email}


def parse_request(text_or_json: str) -> Dict:
    """Main parser. Accepts a JSON string or free text / voice transcript."""
    text = text_or_json.strip()
    if text.startswith("{"):
        import json
        try:
            return json.loads(text)
        except Exception as e:
            raise ValueError(f"Invalid JSON input: {e}")
    
    cities = _extract_cities(text)
    cities = _extract_dates(text, cities)
    country = _extract_country(text, [c["city"] for c in cities])
    travelers = _extract_travelers(text)
    interests = _extract_interests(text)
    food_preferences = _extract_food_preferences(text)
    pace = _extract_pace(text)
    contact = _extract_name_email(text)

    return {
        "trip_name": f"{country} Trip" if country != "Unknown Country" else "Trip Plan",
        "destination_country": country,
        "cities": cities,
        "travelers": travelers,
        "interests": interests,
        "food_preferences": food_preferences,
        "pace": pace,
        "requester_name": contact.get("name") or "",
        "requester_email": contact.get("email") or "",
        "raw_input": text,
    }


if __name__ == "__main__":
    samples = [
        "Planning a Japan family trip from 2026-04-12 to 2026-04-21 for 2 adults age 40 and 38 and 2 children age 12 and 9. We love temples, anime, food, parks and museums. We eat sushi, ramen and need halal options. My name is OzMo Shay, email aeyeingserver@gmail.com. We want Tokyo, Kyoto and Osaka.",
    ]
    for s in samples:
        print(parse_request(s))
