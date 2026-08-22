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
    Raises ValueError if any city can only be served by the generic placeholder
    template, so we never ship fake-looking curated data to users."""
    from llm_places import load_cached
    from sources import _builtin_city_places

    # Verify every requested city has real data before building the workbook.
    unsupported = []
    for c in trip.get("cities", []):
        city = c["city"]
        country = trip.get("destination_country", "")
        has_builtin = bool(_builtin_city_places(city, country, "attractions", 1))
        cached = load_cached(city, country)
        is_generic = (
            cached and cached.get("_source") == "generic_template"
        ) or (
            cached and not cached.get("_source")
            and not any(
                p.get("lat", 0) != 0.0 and p.get("lon", 0) != 0.0
                for key, places in cached.items()
                if key != "hotels" and isinstance(places, list)
                for p in places
            )
        )
        if not has_builtin and (cached is None or is_generic):
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
