"""
Unified trip plan generator: fetches data, schedules, and writes an Excel file
matching the user's Japan Trip.xlsx template.
"""
import os
import sys
from pathlib import Path
from typing import Dict

# Make sibling imports work
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from scheduler import build_plan_data, apply_plan_to_workbook
from template import build_skeleton


def generate_excel(trip: Dict, output_path: str = None, pace: str = "relaxed") -> str:
    """Generate a complete trip Excel file from the trip request dict.
    For unknown cities it first tries the LLM to produce real data. Only if
    the LLM also fails does it raise ValueError, so users never receive
    fake-looking placeholder trips."""
    from llm_places import load_cached, generate_city_dataset
    from sources import _builtin_city_places

    def _has_real_data(city, country):
        if _builtin_city_places(city, country, "attractions", 1):
            return True
        cached = load_cached(city, country)
        if not cached:
            return False
        if cached.get("_source") == "generic_template":
            return False
        # Legacy cached files without _source: assume real if any non-zero coords
        if not cached.get("_source"):
            return any(
                p.get("lat", 0) != 0.0 and p.get("lon", 0) != 0.0
                for key, places in cached.items()
                if key != "hotels" and isinstance(places, list)
                for p in places
            )
        return True

    # For unknown cities, try LLM generation first before giving up.
    unsupported = []
    for c in trip.get("cities", []):
        city = c["city"]
        country = trip.get("destination_country", "")
        if _has_real_data(city, country):
            continue
        print(f"[generate] No cached data for {city}, trying LLM...")
        try:
            generate_city_dataset(city, country, ages=[t["age"] for t in trip.get("travelers", [])], timeout_ollama=60, timeout_cloud=60)
        except Exception as e:
            print(f"[generate] LLM failed for {city}: {e}")
        if not _has_real_data(city, country):
            unsupported.append(city)
    if unsupported:
        raise ValueError(
            f"Destination(s) not yet supported: {', '.join(unsupported)}. "
            "Please contact support to add this city."
        )

    plan = build_plan_data(trip, pace=pace)
    # Limit Hotels tab to top 2 live options per city to keep the sheet compact
    # and avoid overwhelming the user with choices.  Pad with curated fallbacks
    # if a city returned fewer than 2 live hotels.
    hotels_limited = []
    seen_cities = {}
    for h in plan["hotels"]:
        city = h["city"]
        seen_cities[city] = seen_cities.get(city, 0) + 1
        if seen_cities[city] <= 2:
            hotels_limited.append(h)
    # Pad any city with fewer than 2 options from curated fallback.
    for c in trip["cities"]:
        city = c["city"]
        city_count = sum(1 for h in hotels_limited if h.get("city") == city)
        if city_count < 2:
            from sources import fetch_places
            extras = fetch_places(
                city, trip["destination_country"], "hotels", [],
                [t["age"] for t in trip.get("travelers", [])],
                limit=2 - city_count,
                latlon=plan.get("_coords_cache", {}).get(city)
            )
            for h in extras:
                hotels_limited.append({
                    "city": city,
                    "name": h["name"],
                    "dates": f"{c['start_date']} to {c['end_date']}",
                    "price": h.get("price", "Contact hotel"),
                    "location": h.get("location", city),
                    "highlights": h.get("highlights", "Curated suggestion"),
                })
    plan["hotels"] = hotels_limited

    # Compute a sensible transport label for single-city trips
    transport_label = "Intercity Transfer"
    if len(plan["cities"]) == 1:
        transport_label = "Local Transport"

    wb = build_skeleton(
        plan["trip_name"],
        plan["dates"],
        plan["cities"],
        plan["sections"],
        plan["transport_options"],
        plan["hotels"],
        transport_label,
    )
    ws = wb.active
    apply_plan_to_workbook(wb, ws, plan)
    if output_path is None:
        safe_name = plan["trip_name"].replace(" ", "_")
        output_path = os.path.join(os.getcwd(), f"{safe_name}.xlsx")
    wb.save(output_path)
    return output_path


if __name__ == "__main__":
    sample = {
        "trip_name": "Japan Trip",
        "destination_country": "Japan",
        "cities": [
            {"city": "Tokyo", "start_date": "2026-04-12", "end_date": "2026-04-16"},
            {"city": "Kyoto", "start_date": "2026-04-17", "end_date": "2026-04-19"},
            {"city": "Osaka", "start_date": "2026-04-20", "end_date": "2026-04-21"},
        ],
        "travelers": [{"age": 40}, {"age": 38}, {"age": 12}, {"age": 9}],
        "interests": ["temples", "anime", "food", "parks", "museums"],
        "food_preferences": ["sushi", "ramen", "halal"],
    }
    out = generate_excel(sample, r"C:\Temp\Japan_Trip_Generated.xlsx")
    print("Generated:", out)
