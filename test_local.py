from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter
import json

def test_local():
    filter = create_filter(
        flight_data=[
            FlightData(date="2026-05-01", from_airport="DEN", to_airport="ICN")
        ],
        trip="one-way",
        passengers=Passengers(adults=1),
        seat="economy"
    )
    
    print("Testing local mode...")
    try:
        result = get_flights_from_filter(filter, mode="local")
        if result and result.flights:
            print(f"Success! Found {len(result.flights)} flights.")
            print(f"First flight price: {result.flights[0].price}")
        else:
            print("No flights found in local mode.")
    except Exception as e:
        print(f"Local mode failed: {e}")

if __name__ == "__main__":
    test_local()
