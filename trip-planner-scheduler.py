"""
Scheduler: turn fetched data into day-by-day recommendations (Morning/Afternoon/Evening/X)
and backup lists. Also assigns hotels, transport and weather text.
"""
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sources import (
    fetch_places, fetch_weather, geocode_city, weather_code_to_text,
    fetch_transit_options, _country_iso,
    _haversine_km, _format_distance,
)
from nuitee_hotels import fetch_live_hotels
from template import _fill, GREEN_FILL, SCHEDULED_VALUES


def _all_dates(start: str, end: str) -> List[str]:
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    days = []
    while s <= e:
        days.append(s.isoformat())
        s += timedelta(days=1)
    return days


def _city_for_date(dates_list: List[str], cities: List[Dict], date: str) -> Dict:
    for c in cities:
        if c["start_date"] <= date <= c["end_date"]:
            return c
    return cities[-1]


def _is_arrival(city: Dict, date: str) -> bool:
    return city["start_date"] == date


def _is_departure(city: Dict, date: str, last_date: str) -> bool:
    return city["end_date"] == date and date != last_date


def _place_latlon(place: Dict) -> Optional[Tuple[float, float]]:
    lat = place.get("lat")
    lon = place.get("lon")
    if lat is not None and lon is not None:
        try:
            return (float(lat), float(lon))
        except Exception:
            pass
    return None


def _distance_between_places(p1: Dict, p2: Dict) -> float:
    """Return distance in km between two places, or a large value if coords missing."""
    ll1 = _place_latlon(p1)
    ll2 = _place_latlon(p2)
    if ll1 and ll2:
        return _haversine_km(ll1[0], ll1[1], ll2[0], ll2[1])
    return 9999.0


def _score_place(place: Dict, weather: Dict, ages: List[int], interests: List[str],
                 slot: str, used_places: set, reference_place: Dict = None) -> float:
    score = 0.0
    if place.get("interest_match"):
        score += 3
    best = [b.lower() for b in place.get("best_time", [])]
    if slot.lower() in best:
        score += 2
    # Distance-aware clustering: if a reference place is already chosen for the
    # same day, prefer nearby places; penalise distant ones.
    if reference_place is not None:
        dist = _distance_between_places(place, reference_place)
        if dist <= 1.0:
            score += 3.0
        elif dist <= 3.0:
            score += 1.5
        elif dist <= 8.0:
            score += 0.0
        else:
            score -= (dist - 8.0) * 0.5
    precip = weather.get("precip_prob", 0) or 0
    indoor = place.get("indoor", False)
    if precip > 50:
        if indoor:
            score += 2
        else:
            score -= 2
    if not place.get("kid_friendly", True) and any(a < 18 for a in ages):
        score -= 5
    if place["name"] in used_places:
        score -= 10
    return score


def _select_place(pool: List[Dict], weather: Dict, ages: List[int], interests: List[str],
                  slot: str, used_places: set, reference_place: Dict = None,
                  allow_used_as_last_resort: bool = True) -> Optional[Dict]:
    """Pick the best place from pool, avoiding already-used places unless necessary."""
    if not pool:
        return None
    scored = [(p, _score_place(p, weather, ages, interests, slot, used_places, reference_place=reference_place))
              for p in pool]
    scored.sort(key=lambda x: x[1], reverse=True)
    best_unused = next((p for p, s in scored if p["name"] not in used_places), None)
    if best_unused:
        return best_unused
    if allow_used_as_last_resort:
        # Worst case: rotate to a different already-used place than yesterday's repeat.
        return scored[0][0]
    return None


def _best_food_for_slot(food_list: List[Dict], slot: str, used_food: set,
                        food_pref: List[str] = None) -> "Optional[Dict]":
    slot_map = {"morning": ["morning", "breakfast", "lunch"],
                "afternoon": ["afternoon", "lunch", "dinner"],
                "evening": ["evening", "dinner"]}
    allowed = slot_map.get(slot.lower(), [slot.lower()])
    pref = [p.lower() for p in (food_pref or [])]
    def score(f):
        s = 0.0
        best = [b.lower() for b in f.get("best_time", [])]
        if any(a in best for a in allowed):
            s += 2
        tags = [t.lower() for t in f.get("tags", [])]
        if pref:
            if any(p in tags for p in pref):
                s += 3
        if f["name"] in used_food:
            s -= 10
        return s
    candidates = [f for f in food_list if score(f) >= 0]
    candidates.sort(key=score, reverse=True)
    return candidates[0] if candidates else None


def _price_amount(h):
    price = h.get("price", "")
    if isinstance(price, str):
        import re
        m = re.search(r"[0-9]+(?:\.[0-9]+)?", price.replace(",", ""))
        if m:
            try:
                return float(m.group())
            except Exception:
                return 999999.0
    elif isinstance(price, (int, float)):
        return float(price)
    return 999999.0


def build_plan_data(trip: Dict, pace: str = "relaxed") -> Dict:
    country = trip["destination_country"]
    cities = trip["cities"]
    interests = [i.lower() for i in trip.get("interests", [])]
    food_pref = [f.lower() for f in trip.get("food_preferences", [])]
    ages = [t["age"] for t in trip.get("travelers", [])]
    dates = _all_dates(cities[0]["start_date"], cities[-1]["end_date"])
    last_date = dates[-1]

    city_meta = []
    coords_cache = {}
    for c in cities:
        try:
            latlon = geocode_city(c["city"], country)
        except Exception as e:
            print(f"Geocode failed for {c['city']}: {e}")
            latlon = None
        coords_cache[c["city"]] = latlon
        city_meta.append({
            "city": c["city"],
            "start_date": c["start_date"],
            "end_date": c["end_date"],
            "lat": latlon[0] if latlon else None,
            "lon": latlon[1] if latlon else None,
        })

    # Weather: per-city fetch with fallback. If a city fails, borrow from the
    # same city's other days or from the nearest previous city that has data.
    weather_by_date = {}
    weather_for_city = {}
    for c in city_meta:
        if c["lat"] is None:
            continue
        days = fetch_weather(c["lat"], c["lon"], c["start_date"], c["end_date"])
        weather_for_city[c["city"]] = days or []
        for d in (days or []):
            if d["date"] not in weather_by_date:
                weather_by_date[d["date"]] = d

    # Fill any missing date using the city's own window or the first available city.
    fallback_pool = []
    for c in city_meta:
        if weather_for_city.get(c["city"]):
            fallback_pool.extend(weather_for_city[c["city"]])
    fallback_by_date = {d["date"]: d for d in fallback_pool}
    for date in dates:
        if date not in weather_by_date:
            # Prefer the city actually assigned to this date, otherwise any available city.
            city_info = _city_for_date(dates, cities, date)
            own_days = {d["date"]: d for d in weather_for_city.get(city_info["city"], [])}
            if date in own_days:
                weather_by_date[date] = own_days[date]
            elif fallback_by_date:
                weather_by_date[date] = fallback_by_date.get(date) or next(iter(fallback_by_date.values()))

    city_candidates = {}
    for c in cities:
        city = c["city"]
        # Pull live hotels (max 2 per city) from Nuitee/LiteAPI.
        children_ages = [t["age"] for t in trip.get("travelers", []) if t["age"] < 18]
        adults = max(1, len(trip.get("travelers", [])) - len(children_ages))
        try:
            live_hotels = fetch_live_hotels(
                city, _country_iso(country), c["start_date"], c["end_date"],
                adults=adults, children_ages=children_ages, max_hotels=2
            )
        except Exception as e:
            print(f"Live hotels failed for {city}: {e}")
            live_hotels = []
        # If Nuitee has no availability for the requested dates, fetch live rates
        # for a near-future window to keep pricing realistic, then label them as
        # "Live benchmark price (date availability may vary)".
        if not live_hotels:
            try:
                from datetime import date as _date, timedelta
                bench_ci = (_date.today() + timedelta(days=30)).isoformat()
                bench_nights = max(2, (_date.fromisoformat(c["end_date"]) - _date.fromisoformat(c["start_date"])).days)
                bench_co = (_date.fromisoformat(bench_ci) + timedelta(days=bench_nights)).isoformat()
                bench = fetch_live_hotels(
                    city, _country_iso(country), bench_ci, bench_co,
                    adults=adults, children_ages=children_ages, max_hotels=2
                )
                live_hotels = [
                    {**h,
                     "dates": f"{c['start_date']} to {c['end_date']}",
                     "price": f"{h['price']} (live benchmark)",
                     "highlights": f"{h['highlights']} — benchmark rate; actual {c['start_date']} availability TBC"}
                    for h in bench
                ]
            except Exception as e:
                print(f"Live benchmark failed for {city}: {e}")
                live_hotels = []
        curated_hotels = fetch_places(city, country, "hotels", [], ages, latlon=coords_cache.get(city))
        city_candidates[city] = {
            "attractions": fetch_places(city, country, "attractions", interests, ages, latlon=coords_cache.get(city)),
            "food": fetch_places(city, country, "food", food_pref, ages, latlon=coords_cache.get(city)),
            "neighborhoods": fetch_places(city, country, "neighborhoods", interests, ages, latlon=coords_cache.get(city)),
            "museums": fetch_places(city, country, "museums", interests, ages, latlon=coords_cache.get(city)),
            "markets": fetch_places(city, country, "markets", interests, ages, latlon=coords_cache.get(city)),
            "day_trips": fetch_places(city, country, "day_trips", interests, ages, latlon=coords_cache.get(city)),
            "hotels": live_hotels if live_hotels else curated_hotels,
        }

    day_plan = []
    used_places_global = set()  # keeps every place used at most once overall
    used_food_global = set()
    # Per-city trackers so each city still gets fresh local picks even if another
    # city exhausted the global uniqueness set earlier.
    used_places_by_city = {c["city"]: set() for c in cities}
    used_food_by_city = {c["city"]: set() for c in cities}
    food_plan_by_day = []  # list of {date, breakfast, lunch, dinner}

    for date in dates:
        city_info = _city_for_date(dates, cities, date)
        city = city_info["city"]
        candidates = city_candidates.get(city, {})
        weather = weather_by_date.get(date, {})
        weather_text = ""
        if weather:
            w = weather
            weather_text = (
                f"{weather_code_to_text(w.get('weather_code'), w.get('precip_prob', 0) or 0)}; "
                f"High: {w.get('max_temp')}°C, Low: {w.get('min_temp')}°C"
            )

        arrival = _is_arrival(city_info, date)
        departure = _is_departure(city_info, date, last_date)

        all_attractions = candidates.get("attractions", [])
        all_museums = candidates.get("museums", [])
        all_daytrips = candidates.get("day_trips", [])
        all_neighborhoods = candidates.get("neighborhoods", [])

        slots = {"Morning": None, "Afternoon": None, "Evening": None}

        # COMPRESSED pace: pack the day with three different nearby attractions.
        # Never use full-day trips; fill morning, afternoon, evening explicitly.
        if pace == "compressed":
            compressed_pool = list(all_attractions) + list(all_museums) + list(all_neighborhoods)
            compressed_pool = [p for p in compressed_pool if p.get("kid_friendly", True) or not any(a < 18 for a in ages)]
            if compressed_pool:
                first_place_of_day = None
                for slot in ["Morning", "Afternoon", "Evening"]:
                    if arrival and slot == "Morning":
                        continue
                    if departure and slot == "Evening":
                        continue
                    used_set = used_places_global | used_places_by_city[city]
                    ref = first_place_of_day if slot in ("Afternoon", "Evening") else None
                    best = _select_place(
                        compressed_pool, weather, ages, interests, slot, used_set,
                        reference_place=ref, allow_used_as_last_resort=True
                    )
                    if best:
                        slots[slot] = (best["name"], best, slot)
                        used_places_global.add(best["name"])
                        used_places_by_city[city].add(best["name"])
                        if first_place_of_day is None:
                            first_place_of_day = best

        else:
            # RELAXED pace: current behaviour. Full day trips only if weather OK and enough days.
            if not arrival and not departure and len(all_daytrips) > 0:
                days_in_city = len([d for d in day_plan if d["city"] == city])
                enough_days = days_in_city >= 3
                good_weather = (weather.get("precip_prob", 0) or 0) < 40
                weekend = datetime.strptime(date, "%Y-%m-%d").weekday() in [5, 6]
                # Only schedule one full-day trip per city
                city_day_trips_used = [d for d in day_plan if d["city"] == city and d["summary"] == "Full Day"]
                if enough_days and good_weather and (weekend or not city_day_trips_used):
                    best = _select_place(all_daytrips, weather, ages, interests, "morning",
                                         used_places_global | used_places_by_city[city])
                    if best:
                        slots["Morning"] = (best["name"], best, "X")
                        slots["Afternoon"] = (best["name"], best, "X")
                        slots["Evening"] = (best["name"], best, "X")
                        used_places_global.add(best["name"])
                        used_places_by_city[city].add(best["name"])

            # Track the first chosen place of the day so later slots cluster nearby.
            first_place_of_day = None
            for slot in ["Morning", "Afternoon", "Evening"]:
                if slots[slot]:
                    if first_place_of_day is None:
                        first_place_of_day = slots[slot][1]
                    continue
                if arrival and slot == "Morning":
                    continue
                if departure and slot == "Evening":
                    continue

                # Rainy day: prefer indoor museums/culture
                pool = list(all_attractions) + list(all_neighborhoods)
                if (weather.get("precip_prob", 0) or 0) > 40:
                    pool = list(all_museums) + list(all_attractions) + list(all_neighborhoods)

                pool = [p for p in pool if p.get("kid_friendly", True) or not any(a < 18 for a in ages)]
                if not pool:
                    continue
                ref = first_place_of_day if slot in ("Afternoon", "Evening") else None
                used_set = used_places_global | used_places_by_city[city]
                best = _select_place(
                    pool, weather, ages, interests, slot, used_set,
                    reference_place=ref, allow_used_as_last_resort=True
                )
                if best:
                    slots[slot] = (best["name"], best, slot)
                    used_places_global.add(best["name"])
                    used_places_by_city[city].add(best["name"])
                    if first_place_of_day is None:
                        first_place_of_day = best

        # Food plan for the day - per-city used set so Alexandria gets its own restaurants
        food_plan = {"date": date, "Morning": None, "Afternoon": None, "Evening": None}
        used_food_today = used_food_global | used_food_by_city[city]
        for slot in ["Morning", "Afternoon", "Evening"]:
            f = _best_food_for_slot(candidates.get("food", []), slot, used_food_today, food_pref)
            if f:
                food_plan[slot] = f["name"]
                used_food_global.add(f["name"])
                used_food_by_city[city].add(f["name"])
                used_food_today.add(f["name"])
        food_plan_by_day.append(food_plan)

        day_plan.append({
            "date": date,
            "city": city,
            "weather": weather_text,
            "summary": _day_summary(arrival, departure, slots),
            "slots": {k: (v[0] if v else "") for k, v in slots.items()},
            "slot_meta": {k: (v[2] if v else None) for k, v in slots.items()},
        })

    # Sort hotels by price ascending then take at most two per city.
    from operator import itemgetter
    for city in city_candidates:
        city_candidates[city]["hotels"] = sorted(
            city_candidates[city]["hotels"],
            key=lambda h: _price_amount(h)
        )[:2]

    # Compute approximate distance from each city's accommodation origin (city center)
    # to every place that has explicit lat/lon in curated data.
    for c in cities:
        city = c["city"]
        hotel_latlon = coords_cache.get(city)
        if hotel_latlon:
            for section_items in city_candidates[city].values():
                for item in section_items:
                    if not isinstance(item, dict) or not item.get("name"):
                        continue
                    lat = item.get("lat")
                    lon = item.get("lon")
                    if lat is not None and lon is not None:
                        try:
                            dist_m = _haversine_km(hotel_latlon[0], hotel_latlon[1], float(lat), float(lon)) * 1000
                            item["distance"] = _format_distance(dist_m)
                        except Exception:
                            item.setdefault("distance", "Failed to fetch")
                    else:
                        item.setdefault("distance", "Failed to fetch")

    sections = {
        "attractions": _dedupe_rows(candidates["attractions"] for candidates in city_candidates.values()),
        "food": _dedupe_rows(candidates["food"] for candidates in city_candidates.values()),
        "neighborhoods": _dedupe_rows(candidates["neighborhoods"] for candidates in city_candidates.values()),
        "museums": _dedupe_rows(candidates["museums"] for candidates in city_candidates.values()),
        "markets": _dedupe_rows(candidates["markets"] for candidates in city_candidates.values()),
        "day_trips": _dedupe_rows(candidates["day_trips"] for candidates in city_candidates.values()),
    }

    hotel_rows = []
    for c in cities:
        city = c["city"]
        hotels = city_candidates[city]["hotels"]
        # Only keep the two cheapest options per city.
        for h in hotels[:2]:
            hotel_rows.append({
                "city": city,
                "name": h["name"],
                "dates": f"{c['start_date']} to {c['end_date']}",
                "price": h.get("price", ""),
                "location": h.get("location", ""),
                "highlights": h.get("highlights", ""),
            })

    return {
        "trip_name": trip.get("trip_name", f"{country} Trip"),
        "dates": [datetime.strptime(d, "%Y-%m-%d") for d in dates],
        "day_plan": day_plan,
        "food_plan": food_plan_by_day,
        "sections": sections,
        "cities": [c["city"] for c in cities],
        "transport_options": fetch_transit_options(cities, country),
        "hotels": hotel_rows,
        "weather_by_date": weather_by_date,
        "_coords_cache": coords_cache,
    }


def _dedupe_rows(iterables) -> List[Dict]:
    seen = set()
    rows = []
    for it in iterables:
        for item in it:
            key = item.get("name", "")
            if key not in seen:
                seen.add(key)
                rows.append({
                    "name": key,
                    "city": item.get("city", ""),
                    "distance": item.get("distance", ""),
                })
    return rows


def _day_summary(arrival: bool, departure: bool, slots: Dict[str, Tuple]) -> str:
    if arrival and departure:
        return "Travel day"
    if arrival:
        return "Arrival / Check in"
    if departure:
        return "Departure / Check out"
    if slots["Morning"] and slots["Morning"][2] == "X":
        return "Full Day"
    # Compressed/relaxed day with scheduled slots
    if any(slots[s] for s in slots):
        return "Scheduled day"
    return "Free day"


def apply_plan_to_workbook(wb, ws, plan: Dict):
    dates = plan["dates"]
    day_plan = plan["day_plan"]
    hotels = plan.get("hotels", [])

    green_fill = _fill(GREEN_FILL)

    # Build map of selected hotel (first/budget) per city to label the main-sheet hotel row.
    selected_hotel_by_city = {}
    for h in hotels:
        city = h.get("city")
        if city and city not in selected_hotel_by_city:
            selected_hotel_by_city[city] = h.get("name", city)

    for i, dp in enumerate(day_plan):
        col = 4 + i
        cell = ws.cell(row=3, column=col)
        cell.value = dp["weather"]

    for i, dp in enumerate(day_plan):
        col = 4 + i
        cell = ws.cell(row=4, column=col)
        cell.value = dp["city"]

    # Map food item names to rows in the Food section
    food_start = None
    food_end = None
    in_food = False
    for r in range(1, ws.max_row + 1):
        v = ws.cell(row=r, column=1).value
        if v == "Food & Dining Spots (Suggestions)":
            food_start = r + 1
            in_food = True
        elif in_food and v in {"Neighborhoods & Areas", "Museums & Cultural Stops", "Markets & Shopping", "Day Trip Destinations"}:
            food_end = r - 1
            in_food = False
    if in_food:
        food_end = ws.max_row

    food_rows = {}
    if food_start and food_end:
        for r in range(food_start, food_end + 1):
            name = ws.cell(row=r, column=1).value
            if name:
                food_rows[name] = r

    hotel_rows = {}
    for r in range(6, 6 + len(plan["cities"])):
        city = ws.cell(row=r, column=1).value
        if city:
            hotel_rows[city] = r

    item_rows = {}
    for r in range(1, ws.max_row + 1):
        name = ws.cell(row=r, column=1).value
        if name:
            item_rows[name] = r

    # Replace main-sheet hotel row name with selected hotel name and colour it green.
    for i, dp in enumerate(day_plan):
        col = 4 + i
        for city, hrow in hotel_rows.items():
            cell = ws.cell(row=hrow, column=1)
            if city in selected_hotel_by_city:
                cell.value = selected_hotel_by_city[city]
            cell = ws.cell(row=hrow, column=col)
            if dp["city"] != city:
                continue
            city_dates = [d["date"] for d in day_plan if d["city"] == city]
            if dp["date"] == city_dates[0]:
                cell.value = "Check in"
                cell.fill = green_fill
            elif dp["date"] == city_dates[-1]:
                cell.value = "Check out"
                cell.fill = green_fill

        transport_row = 6 + len(plan["cities"])
        for i, dp in enumerate(day_plan):
            col = 4 + i
            cell = ws.cell(row=transport_row, column=col)
            city_dates = [d["date"] for d in day_plan if d["city"] == dp["city"]]
            if dp["date"] == city_dates[-1] and i < len(day_plan) - 1:
                option = plan["transport_options"][0] if plan["transport_options"] else "Travel"
                cell.value = option
                cell.fill = green_fill

    for i, dp in enumerate(day_plan):
        col = 4 + i
        for slot, place_name in dp["slots"].items():
            if place_name == "" or place_name not in item_rows:
                continue
            row = item_rows[place_name]
            cell = ws.cell(row=row, column=col)
            # Use the stored slot marker (e.g. 'X' for full-day trips) when present.
            stored_marker = dp["slot_meta"].get(slot)
            if stored_marker:
                label = stored_marker
            else:
                label = {"Morning": "Morning", "Afternoon": "Afternoon", "Evening": "Evening"}.get(slot, "X")
            cell.value = label
            cell.fill = green_fill

        # Write food slots
        fp = plan["food_plan"][i]
        for slot, food_name in fp.items():
            if food_name and food_name in food_rows:
                fcell = ws.cell(row=food_rows[food_name], column=col)
                label = {"Morning": "Morning", "Afternoon": "Afternoon", "Evening": "Evening"}[slot]
                fcell.value = label
                fcell.fill = green_fill


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
    plan = build_plan_data(sample)
    print(plan["trip_name"], len(plan["dates"]), "days")
    for dp in plan["day_plan"]:
        print(dp["date"], dp["city"], dp["slots"], dp["weather"][:60])
