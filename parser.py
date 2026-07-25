"""
Natural language / chat parser for trip planner input.
Extracts structured trip request from free text or voice transcript.
"""
import json
import os
import re
from difflib import get_close_matches
from datetime import datetime, timedelta
from typing import Dict, List


# Load city/country reference data generated from cached datasets.
_REF_PATH = os.path.join(os.path.dirname(__file__), "parser_cities_reference.json")
_CITY_TO_COUNTRY = {}
_KNOWN_CITIES = []
_KNOWN_COUNTRIES = []
try:
    with open(_REF_PATH, "r", encoding="utf-8") as _f:
        _ref = json.load(_f)
    _CITY_TO_COUNTRY = {k.lower(): v for k, v in _ref.get("city_to_country", {}).items()}
    _KNOWN_CITIES = [c.lower() for c in _ref.get("cities", [])]
    _KNOWN_COUNTRIES = [c.lower() for c in _ref.get("countries", [])]
except Exception:
    pass

# Extra common misspellings / voice transcription errors
_CITY_ALIASES = {
    "instanbul": "Istanbul", "istanubl": "Istanbul", "istambul": "Istanbul",
    "antaly": "Antalya", "antalia": "Antalya",
    "bombay": "Mumbai", "calcutta": "Kolkata",
    "ny": "New York", "nyc": "New York",
    "la": "Los Angeles", "sf": "San Francisco",
    "bcn": "Barcelona", "mad": "Madrid",
    "ldn": "London", "edin": "Edinburgh",
    "cpt": "Cape Town",
    "jkt": "Jakarta",
    "hcm": "Ho Chi Minh City", "saigon": "Ho Chi Minh City",
    "kuwait": "Kuwait City", "bali": "Bali", "phuket": "Phuket",
    "milan": "Milan", "venice": "Venice", "florence": "Florence",
    "rome": "Rome", "naples": "Naples",
}

_COUNTRY_ALIASES = {
    "uae": "United Arab Emirates", "dubai": "United Arab Emirates", "abu dhabi": "United Arab Emirates",
    "usa": "United States", "us": "United States", "america": "United States",
    "uk": "United Kingdom", "britain": "United Kingdom", "england": "United Kingdom",
    "u.k": "United Kingdom", "u.s": "United States",
}


def _fuzzy_match_word(token: str, choices: List[str], cutoff: float = 0.75) -> str | None:
    token = token.lower()
    # direct or alias first
    if token in choices:
        return token
    matches = get_close_matches(token, choices, n=1, cutoff=cutoff)
    if matches:
        return matches[0]
    return None


def _extract_country(text: str, cities: List[str]) -> str:
    """Extract country from explicit mentions, aliases, or inferred from cities."""
    text_lower = text.lower()

    # Direct aliases
    for alias, country in _COUNTRY_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
            return country

    # Fuzzy country name match
    words = re.findall(r"[a-z]+", text_lower)
    # Try sliding 1-3 word windows
    for n in range(3, 0, -1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i:i+n])
            m = _fuzzy_match_word(phrase, _KNOWN_COUNTRIES, cutoff=0.85)
            if m:
                return " ".join(p.capitalize() for p in m.split())

    # Fallback: infer from cities
    for city in cities:
        country = _CITY_TO_COUNTRY.get(city.lower())
        if country and country != "Unknown Country":
            return country

    return "Unknown Country"


def _extract_cities(text: str) -> List[Dict]:
    """Extract city names with fuzzy matching and common typo/alias handling."""
    text_lower = text.lower()
    found = []
    found_lower = set()

    # Aliases and misspellings
    for alias, correct in _CITY_ALIASES.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
            cl = correct.lower()
            if cl not in found_lower:
                found.append({"city": correct})
                found_lower.add(cl)

    # Try matching all 1-3 word phrases against known cities
    words = re.findall(r"[a-z]+", text_lower)
    for n in range(3, 0, -1):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i:i+n])
            m = _fuzzy_match_word(phrase, _KNOWN_CITIES, cutoff=0.80)
            if m and m not in found_lower:
                display = _CITY_ALIASES.get(m, " ".join(p.capitalize() for p in m.split()))
                found.append({"city": display})
                found_lower.add(m)

    # Preserve order of first appearance in the text
    def _first_index(city_name: str) -> int:
        idx = text_lower.find(city_name.lower())
        return idx if idx != -1 else 9999

    found.sort(key=lambda c: _first_index(c["city"]))
    return found


def _extract_dates(text: str, cities: List[Dict]) -> List[Dict]:
    """Extract dates and assign consecutive ranges to cities in logical order."""
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
                raw_dates.append(d)
            except Exception:
                pass

    # Natural-language date phrases like "1st of September" or "1st September".
    month_names = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
        "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    year_match = re.search(r"\b(20\d{2})\b", text)
    year = int(year_match.group(1)) if year_match else datetime.today().year
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?([a-z]+)\b", text_lower):
        day = int(m.group(1))
        month = month_names.get(m.group(2))
        if month and 1 <= day <= 31:
            try:
                raw_dates.append(datetime(year, month, day).date())
            except Exception:
                pass

    raw_dates = sorted(set(raw_dates))

    if len(raw_dates) >= 2 and len(cities) >= 1:
        start = raw_dates[0]
        end = raw_dates[-1]
        if end < start:
            start, end = end, start
        total_days = (end - start).days
        if total_days < 0:
            total_days = 0

        if len(cities) == 1:
            cities[0]["start_date"] = start.isoformat()
            cities[0]["end_date"] = end.isoformat()
        else:
            base = total_days // len(cities)
            extra = total_days % len(cities)
            cur = start
            for i, city in enumerate(cities):
                days = base + (1 if i < extra else 0)
                city_start = cur
                city_end = min(cur + timedelta(days=days), end)
                city["start_date"] = city_start.isoformat()
                city["end_date"] = city_end.isoformat()
                cur = city_end + timedelta(days=1)
    elif len(raw_dates) == 1 and len(cities) >= 1:
        start = raw_dates[0]
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
    """Extract number of adults/children and ages robustly."""
    text_lower = text.lower()

    # Count explicit adults / children / kids
    m = re.search(r"(\d+)\s*adults?", text, re.IGNORECASE)
    adults = int(m.group(1)) if m else None
    m = re.search(r"(\d+)\s*(?:children?|kids?)\b", text, re.IGNORECASE)
    children = int(m.group(1)) if m else None

    # Family shorthand: "family of 4" / "family of 5" / "family of four"
    family_num_map = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9, "ten": 10,
    }
    family_total = None
    fm = re.search(r"family\s+of\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)", text_lower)
    if fm:
        val = fm.group(1)
        family_total = family_num_map.get(val) or int(val)

    if family_total is not None:
        if adults is None:
            adults = 2
        inferred_children = max(0, family_total - adults)
        if children is None:
            children = inferred_children
        else:
            children = max(children, inferred_children)

    adults = adults if adults is not None else 2
    children = children if children is not None else 0

    # Build a set of integer token positions that are counts, not ages.
    count_positions = set()
    for m in re.finditer(r"\b(\d+)\s*(?:adults?|children?|kids?|family)\b", text, re.IGNORECASE):
        count_positions.add(m.start(1))
    if fm:
        count_positions.add(fm.start(1))

    # Extract ages: explicit "age NN" / "aged NN" / "NN years old", plus
    # list patterns like "ages 8, 10 and 12" or "kids aged 6 and 9".
    used_positions = set(count_positions)
    age_tokens = []

    # Pass 1: explicit age markers, plus numbers immediately following kids/children
    # patterns like "kids 6 and 9" or "children 8, 10, 12".
    for m in re.finditer(r"\b(\d{1,3})\b", text):
        pos = m.start(1)
        if pos in used_positions:
            continue
        age = int(m.group(1))
        if not (3 <= age <= 99):
            continue
        before = text[max(0, pos-35):pos].lower()
        after = text[pos:min(len(text), pos+20)].lower()
        # Strong signal: "age NN" / "ages NN" / "aged NN" / "NN years old"
        has_age_word = bool(re.search(r"\bage\s*s?\s*$", before) or re.search(r"^\s*years?\s*old", after))
        # Also accept "kids 6 and 9" / "children 8, 10 and 12" — a number directly after the person keyword.
        has_person_prefix = bool(re.search(r"\b(?:kids?|children)\s*$", before))
        if has_age_word or has_person_prefix:
            age_tokens.append((pos, age))
            used_positions.add(pos)

    # Pass 2: extend each age-token into a nearby list: "ages 8, 10 and 12"
    # We look forward from each seed for numbers separated only by spaces, commas, "and".
    extended = []
    age_tokens = sorted(age_tokens, key=lambda x: x[0])
    consumed = set()
    for seed_pos, seed_age in age_tokens:
        if seed_pos in consumed:
            continue
        cluster = [(seed_pos, seed_age)]
        consumed.add(seed_pos)
        # look up to ~70 chars forward for more numbers
        segment = text[seed_pos:seed_pos+70]
        cursor = len(str(seed_age))  # start after the seed number
        while True:
            next_num = None
            for m in re.finditer(r"\b(\d{1,3})\b", segment):
                if m.start(1) < cursor:
                    continue
                abs_pos = seed_pos + m.start(1)
                age = int(m.group(1))
                if not (3 <= age <= 99):
                    continue
                between = segment[cursor:m.start(1)].lower()
                # Valid separators: spaces, commas, "and"/"&", optionally mixed
                if re.fullmatch(r"[\s,]*(?:and|&)?\s*", between):
                    next_num = (abs_pos, age, m.end(1))
                break  # only consider the very next number
            if next_num is None:
                break
            abs_pos, age, rel_end = next_num
            cluster.append((abs_pos, age))
            used_positions.add(abs_pos)
            consumed.add(abs_pos)
            cursor = rel_end
        extended.extend(cluster)
    age_tokens = extended

    adult_ages = []
    child_ages = []
    for pos, age in age_tokens:
        before = text[max(0, pos-80):pos].lower()
        # Find the last (nearest) person keyword before this age
        last_adult = None
        last_child = None
        for m in re.finditer(r"\b(adults?|grown[-\s]?ups?|parents?)\b", before):
            last_adult = m.end()
        for m in re.finditer(r"\b(children|kids?)\b", before):
            last_child = m.end()

        if last_child is not None and (last_adult is None or last_child > last_adult):
            child_ages.append(age)
        elif last_adult is not None:
            adult_ages.append(age)
        elif re.search(r"\bfamily\b", before):
            if age <= 16 and children > 0:
                child_ages.append(age)
            else:
                adult_ages.append(age)
        else:
            if age <= 16 and len(child_ages) < children:
                child_ages.append(age)
            else:
                adult_ages.append(age)

    # Fallback: only fill missing slots with ages that haven't been used yet.
    def _fallback_ages(keywords: List[str], limit: int) -> List[int]:
        positions = []
        for kw in keywords:
            idx = text_lower.find(kw)
            if idx != -1:
                positions.append(idx)
        if not positions:
            return []
        idx = min(positions)
        segment = text[idx:]
        stop = re.search(r"(?i)\.(?=\s)|we\s|interests|love|i\s+love|food|my\s+name|attractions|places|from\s+\d", segment)
        if stop:
            segment = segment[:stop.start()]
        found = []
        for m in re.finditer(r"\b(\d{1,3})\b", segment):
            pos = m.start() + idx
            if pos in used_positions:
                continue
            age = int(m.group(1))
            if 3 <= age <= 99:
                found.append((pos, age))
        found.sort(key=lambda x: x[0])
        return [age for _, age in found[:limit]]

    # Fill missing ages from fallback
    if len(adult_ages) < adults:
        adult_ages.extend(_fallback_ages(["adults", "adult", "family"], adults - len(adult_ages)))
    if len(child_ages) < children:
        child_ages.extend(_fallback_ages(["children", "kids", "family"], children - len(child_ages)))
    # Cross-borrow if still short
    if len(adult_ages) < adults:
        adult_ages.extend(_fallback_ages(["children", "kids", "family"], adults - len(adult_ages)))
    if len(child_ages) < children:
        child_ages.extend(_fallback_ages(["adults", "adult", "family"], children - len(child_ages)))

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
                continue
            found.append(k)
    if "kids friendly" in text_lower or "family friendly" in text_lower or "kids" in text_lower:
        if "kids friendly" not in found:
            found.append("kids friendly")
    found = [k for k in found if not (k == "kids" and "kids friendly" in found)]
    return found


def _extract_food_preferences(text: str) -> List[str]:
    text_lower = text.lower()
    food_keywords = ["sushi", "ramen", "halal", "vegetarian", "vegan", "seafood",
                     "beef", "street food", "fine dining", "local cuisine",
                     "gluten free", "kosher", "indian", "italian", "thai",
                     "sweet", "sweets", "dessert", "desserts", "healthy", "salads",
                     "fruit", "pastry", "baklava", "turkish delight"]
    normalized = text_lower.replace("hala ", "halal ").replace(" hala", " halal") \
                           .replace("hala,", "halal,").replace("hala.", "halal.")
    found = [k for k in food_keywords if k in normalized]
    if "desserts" in found and "dessert" in found:
        found.remove("dessert")
    if "sweets" in found and "sweet" in found:
        found.remove("sweet")
    return found


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
    name_match = re.search(r"my\s+name\s+is\s+([A-Za-z\s]+)", text, re.IGNORECASE)
    if name_match:
        name = name_match.group(1).strip()
    return {"name": name, "email": email}


def parse_request(text_or_json: str) -> Dict:
    """Main parser. Accepts a JSON string or free text / voice transcript."""
    text = text_or_json.strip()
    if text.startswith("{"):
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
