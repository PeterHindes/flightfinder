from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter
import asyncio

def dump_html():
    filter = create_filter(
        flight_data=[
            FlightData(date="2026-05-01", from_airport="DEN", to_airport="BKK")
        ],
        trip="one-way",
        passengers=Passengers(adults=1),
        seat="economy"
    )
    
    print("Fetching HTML...")
    # Use local mode to get the full rendered HTML
    try:
        # We need to access the internal fetchers to get the raw HTML
        from fast_flights.local_playwright import local_playwright_fetch
        data = filter.as_b64()
        params = {
            "tfs": data.decode("utf-8"),
            "hl": "en",
            "tfu": "EgQIABABIgA",
        }
        res = local_playwright_fetch(params)
        with open("debug.html", "w", encoding="utf-8") as f:
            f.write(res.text)
        print("HTML dumped to debug.html")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    dump_html()
