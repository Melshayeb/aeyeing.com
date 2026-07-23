"""Pre-generate curated datasets for major world cities via Ollama/cloud LLM.
Run once to populate cached_cities/ so future trip requests never hit the LLM.
"""
from llm_places import generate_city_dataset

CITIES = [
    ("New York", "United States"),
    ("Los Angeles", "United States"),
    ("San Francisco", "United States"),
    ("Chicago", "United States"),
    ("Miami", "United States"),
    ("Boston", "United States"),
    ("Las Vegas", "United States"),
    ("Seattle", "United States"),
    ("Washington", "United States"),
    ("Austin", "United States"),
    ("London", "United Kingdom"),
    ("Manchester", "United Kingdom"),
    ("Birmingham", "United Kingdom"),
    ("Edinburgh", "United Kingdom"),
    ("Glasgow", "United Kingdom"),
    ("Paris", "France"),
    ("Nice", "France"),
    ("Lyon", "France"),
    ("Marseille", "France"),
    ("Bordeaux", "France"),
    ("Strasbourg", "France"),
    ("Tokyo", "Japan"),
    ("Kyoto", "Japan"),
    ("Osaka", "Japan"),
    ("Yokohama", "Japan"),
    ("Sapporo", "Japan"),
    ("Rome", "Italy"),
    ("Milan", "Italy"),
    ("Venice", "Italy"),
    ("Florence", "Italy"),
    ("Naples", "Italy"),
    ("Barcelona", "Spain"),
    ("Madrid", "Spain"),
    ("Seville", "Spain"),
    ("Valencia", "Spain"),
    ("Berlin", "Germany"),
    ("Munich", "Germany"),
    ("Hamburg", "Germany"),
    ("Frankfurt", "Germany"),
    ("Cologne", "Germany"),
    ("Amsterdam", "Netherlands"),
    ("Rotterdam", "Netherlands"),
    ("Brussels", "Belgium"),
    ("Zurich", "Switzerland"),
    ("Geneva", "Switzerland"),
    ("Vienna", "Austria"),
    ("Prague", "Czech Republic"),
    ("Budapest", "Hungary"),
    ("Warsaw", "Poland"),
    ("Athens", "Greece"),
    ("Istanbul", "Turkey"),
    ("Dubai", "United Arab Emirates"),
    ("Abu Dhabi", "United Arab Emirates"),
    ("Doha", "Qatar"),
    ("Singapore", "Singapore"),
    ("Bangkok", "Thailand"),
    ("Phuket", "Thailand"),
    ("Kuala Lumpur", "Malaysia"),
    ("Hong Kong", "Hong Kong"),
    ("Seoul", "South Korea"),
    ("Taipei", "Taiwan"),
    ("Beijing", "China"),
    ("Shanghai", "China"),
    ("Guangzhou", "China"),
    ("Chengdu", "China"),
    ("Sydney", "Australia"),
    ("Melbourne", "Australia"),
    ("Brisbane", "Australia"),
    ("Perth", "Australia"),
    ("Auckland", "New Zealand"),
    ("Cairo", "Egypt"),
    ("Marrakech", "Morocco"),
    ("Casablanca", "Morocco"),
    ("Cape Town", "South Africa"),
    ("Johannesburg", "South Africa"),
    ("Nairobi", "Kenya"),
    ("Mumbai", "India"),
    ("Delhi", "India"),
    ("Bangalore", "India"),
    ("Jaipur", "India"),
    ("Goa", "India"),
    ("Rio de Janeiro", "Brazil"),
    ("Sao Paulo", "Brazil"),
    ("Buenos Aires", "Argentina"),
    ("Lima", "Peru"),
    ("Bogota", "Colombia"),
    ("Mexico City", "Mexico"),
    ("Cancun", "Mexico"),
    ("Toronto", "Canada"),
    ("Vancouver", "Canada"),
    ("Montreal", "Canada"),
    ("Dublin", "Ireland"),
    ("Lisbon", "Portugal"),
    ("Porto", "Portugal"),
    ("Copenhagen", "Denmark"),
    ("Stockholm", "Sweden"),
    ("Oslo", "Norway"),
    ("Helsinki", "Finland"),
    ("Reykjavik", "Iceland"),
    ("Moscow", "Russia"),
    ("Saint Petersburg", "Russia"),
    ("Dubrovnik", "Croatia"),
    ("Split", "Croatia"),
    ("Bali", "Indonesia"),
    ("Jakarta", "Indonesia"),
    ("Hanoi", "Vietnam"),
    ("Ho Chi Minh City", "Vietnam"),
    ("Manila", "Philippines"),
    ("Cebu", "Philippines"),
    ("Riyadh", "Saudi Arabia"),
    ("Jeddah", "Saudi Arabia"),
    ("Kuwait City", "Kuwait"),
    ("Muscat", "Oman"),
    ("Manama", "Bahrain"),
    ("Amman", "Jordan"),
    ("Beirut", "Lebanon"),
    ("Tel Aviv", "Israel"),
    ("Jerusalem", "Israel"),
    ("Fiji", "Nadi"),
    ("Suva", "Fiji"),
]

if __name__ == "__main__":
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from llm_places import load_cached

    def gen(pair):
        city, country = pair
        if load_cached(city, country):
            return (city, country, "already cached", 0)
        try:
            data = generate_city_dataset(city, country, ages=[40, 38, 12, 9], timeout_ollama=90, timeout_cloud=60)
            total = sum(len(v) for v in data.values())
            return (city, country, "cached", total)
        except Exception as e:
            return (city, country, f"error: {e}", 0)

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(gen, pair): pair for pair in CITIES}
        for i, fut in enumerate(as_completed(futures), 1):
            city, country, status, total = fut.result()
            print(f"[{i}/{len(CITIES)}] {city}, {country} -> {status} ({total} items)")
    print("Done.")
