import json
import time
import argparse
import csv
import random
import time
import re
import os
import requests
from datetime import datetime, timedelta
from dateutil import parser as date_parser
from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter
from selectolax.lexbor import LexborHTMLParser

def parse_price(price_str):
    if price_str is None:
        return None
    if isinstance(price_str, (int, float)):
        return float(price_str) if price_str != 0 else None
    try:
        clean_price = "".join(c for c in str(price_str) if c.isdigit() or c == '.')
        if not clean_price or float(clean_price) == 0:
            return None
        return float(clean_price)
    except ValueError:
        return None

def normalize_date(date_str):
    if not date_str or not date_str.strip():
        return None
    try:
        # Parse the date string
        dt = date_parser.parse(date_str)
        # If no year is provided, assume 2026 (as per user context/current year)
        if dt.year == datetime.now().year and "2026" not in date_str:
             # The system prompt says current time is 2026-01-15.
             dt = dt.replace(year=2026)
        return dt.strftime("%Y-%m-%d")
    except Exception as e:
        print(f"  Error parsing date '{date_str}': {e}")
        return None

def get_google_flights_url(filter):
    try:
        b64 = filter.as_b64().decode('utf-8')
        return f"https://www.google.com/travel/flights?tfs={b64}"
    except Exception:
        return "URL generation failed"

def fetch_with_retry(filter, max_retries=5, data_source='js'):
    retries = 0
    modes_to_try = ["common", "local"]
    
    while retries < max_retries:
        for mode in modes_to_try:
            try:
                # We'll try to get the response first
                from fast_flights.core import fetch, _merge_binary_cookies, _DEFAULT_COOKIES_BYTES, parse_response
                from fast_flights.local_playwright import local_playwright_fetch
                
                data = filter.as_b64()
                params = {
                    "tfs": data.decode("utf-8"),
                    "hl": "en",
                    "tfu": "EgQIABABIgA",
                }
                
                if mode == "common":
                    res = fetch(params)
                else:
                    res = local_playwright_fetch(params)
                
                if res:
                    try:
                        # Try parsing as JS first if requested
                        if data_source == 'js':
                            result = parse_response(res, 'js')
                            if result and (getattr(result, 'best', []) or getattr(result, 'other', [])):
                                return result, res
                    except Exception as js_e:
                        print(f"  JS parsing failed: {js_e}")
                    
                    # If JS fails or wasn't requested, return the response for HTML parsing
                    return None, res
                    
            except Exception as e:
                print(f"  Attempt {retries + 1} ({mode}) failed: {e}")
        
        retries += 1
        if retries < max_retries:
            wait_time = (2 ** retries) + random.uniform(0, 2)
            print(f"  Retrying in {wait_time:.2f} seconds...")
            time.sleep(wait_time)
    return None, None

def parse_html_results(res):
    parser = LexborHTMLParser(res.text)
    
    itineraries = []
    
    # Google Flights structure for flight items
    for item in parser.css('li.pIav2d'):
        try:
            # Price
            price_node = item.css_first(".YMlIz.FpEdX")
            if not price_node: continue
            price = parse_price(price_node.text())
            if not price: continue
            
            # Flight Numbers from travel impact URL
            flight_numbers = []
            impact_node = item.css_first("[data-travelimpactmodelwebsiteurl]")
            if impact_node:
                url = impact_node.attributes.get("data-travelimpactmodelwebsiteurl", "")
                # Format: ...itinerary=DEN-SEA-AS-785-20260501,SEA-TPE-BR-25-20260502...
                match = re.search(r"itinerary=([^&]+)", url)
                if match:
                    segments = match.group(1).split(",")
                    for seg in segments:
                        parts = seg.split("-")
                        if len(parts) >= 4:
                            airline = parts[2]
                            fnum = parts[3]
                            flight_numbers.append(f"{airline} {fnum}")
            
            # Layovers and Duration from aria-label
            layovers = []
            duration = "N/A"
            main_link = item.css_first(".JMc5Xc")
            if main_link:
                label = main_link.attributes.get("aria-label", "")
                # Extract duration: "Total duration 26 hr 30 min."
                dur_match = re.search(r"Total duration ([^.]+)\.", label)
                if dur_match:
                    duration = dur_match.group(1)
                
                # Extract layovers: "Layover (1 of 2) is a 4 hr 21 min layover at Seattle-Tacoma International Airport in Seattle."
                layover_matches = re.findall(r"Layover \(\d+ of \d+\) is a ([^.]+ layover at [^.]+)\.", label)
                for lm in layover_matches:
                    layovers.append(lm)
            
            # Airline names
            airlines = []
            airline_node = item.css_first(".sSHqwe.tPgKwe.ogfYpf span")
            if airline_node:
                airlines = [a.strip() for a in airline_node.text().split(",")]

            itineraries.append({
                "price": float(price),
                "flight_numbers": flight_numbers,
                "layovers": layovers,
                "duration": duration,
                "airlines": airlines
            })
        except Exception as e:
            print(f"  Error parsing HTML item: {e}")
            continue
            
    return itineraries

def format_duration(minutes):
    if minutes is None:
        return "N/A"
    h = minutes // 60
    m = minutes % 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"

def get_flight_details(itinerary):
    details = {
        "flight_numbers": [],
        "layovers": [],
        "total_duration": format_duration(getattr(itinerary, 'travel_time', None)),
        "airlines": getattr(itinerary, 'airline_names', [])
    }
    
    flights = getattr(itinerary, 'flights', [])
    if flights:
        for f in flights:
            airline = getattr(f, 'airline_name', 'Unknown')
            f_num = getattr(f, 'flight_number', '')
            details["flight_numbers"].append(f"{airline} {f_num}".strip())
        
    layovers = getattr(itinerary, 'layovers', [])
    if layovers:
        for l in layovers:
            city = getattr(l, 'departure_airport_city', getattr(l, 'departure_airport', 'Unknown'))
            duration = format_duration(getattr(l, 'minutes', None))
            details["layovers"].append(f"{duration} in {city}")
        
    return details

def get_date_range(start_date, end_date):
    if not start_date:
        return []
    if not end_date:
        return [start_date]
    
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    dates = []
    curr = start
    while curr <= end:
        dates.append(curr.strftime("%Y-%m-%d"))
        curr += timedelta(days=1)
    return dates

def get_best_price(origin, destination, date_range, trip_type="one-way", max_retries=5):
    if not date_range:
        return None
    
    best_info = None
    
    for d in date_range:
        print(f"Searching for {trip_type} from {origin} to {destination} on {d}...")
        filter = create_filter(
            flight_data=[
                FlightData(date=d, from_airport=origin, to_airport=destination)
            ],
            trip=trip_type,
            passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
            seat="economy"
        )
        
        url = get_google_flights_url(filter)
        print(f"  Link: {url}")
        
        result, res = fetch_with_retry(filter, max_retries=max_retries)
        
        all_itineraries = []
        if result and hasattr(result, 'best'):
            # Use JS results if available
            for itin in (result.best + result.other):
                details = get_flight_details(itin)
                all_itineraries.append({
                    "price": float(itin.itinerary_summary.price),
                    "flight_numbers": details["flight_numbers"],
                    "layovers": details["layovers"],
                    "duration": details["total_duration"]
                })
        elif res:
            # Fallback to HTML parsing
            all_itineraries = parse_html_results(res)
            
        for itin in all_itineraries:
            price = itin["price"]
            if price and price > 0:
                if best_info is None or price < best_info["price"]:
                    best_info = itin
                    best_info["date"] = d
                    best_info["url"] = url
    
    if best_info:
        print(f"  Best price found: ${best_info['price']} on {best_info['date']}")
        return best_info
    
    print(f"  Failed to find price for {origin}->{destination} in range {date_range[0]} to {date_range[-1]}")
    return None

def get_round_trip_price(origin, destination, depart_range, return_range, max_retries=5):
    if not depart_range or not return_range:
        return None
    
    best_info = None

    for d_dep in depart_range:
        for d_ret in return_range:
            if d_ret <= d_dep:
                continue
                
            print(f"Searching for round-trip between {origin} and {destination} ({d_dep} to {d_ret})...")
            filter = create_filter(
                flight_data=[
                    FlightData(date=d_dep, from_airport=origin, to_airport=destination),
                    FlightData(date=d_ret, from_airport=destination, to_airport=origin)
                ],
                trip="round-trip",
                passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
                seat="economy"
            )
            
            url = get_google_flights_url(filter)
            print(f"  Link: {url}")
            
            result, res = fetch_with_retry(filter, max_retries=max_retries)
            
            all_itineraries = []
            if result and hasattr(result, 'best'):
                for itin in (result.best + result.other):
                    details = get_flight_details(itin)
                    all_itineraries.append({
                        "price": float(itin.itinerary_summary.price),
                        "flight_numbers": details["flight_numbers"],
                        "layovers": details["layovers"],
                        "duration": details["total_duration"]
                    })
            elif res:
                all_itineraries = parse_html_results(res)
                
            for itin in all_itineraries:
                price = itin["price"]
                if price and price > 0:
                    if best_info is None or price < best_info["price"]:
                        best_info = itin
                        best_info["dates"] = (d_dep, d_ret)
                        best_info["url"] = url
            
    if best_info:
        print(f"  Best price found: ${best_info['price']} for {best_info['dates']}")
        return best_info

    print(f"  Failed to find price for {origin}<->{destination} in ranges")
    return None

def generate_markdown_report(trips, one_way_results, nested_results, total_oneways, total_nested):
    report = "# Flight Comparison Report\n\n"
    
    report += "## Summary\n"
    if total_oneways is not None and total_nested is not None:
        report += f"- **Multi-City One-Ways**: ${total_oneways:.2f}\n"
        report += f"- **Nested Round Trips**: ${total_nested:.2f}\n\n"
        if total_oneways < total_nested:
            report += f"**Verdict**: One-Ways are cheaper by ${total_nested - total_oneways:.2f}\n"
        elif total_nested < total_oneways:
            report += f"**Verdict**: Nested Round Trips are cheaper by ${total_oneways - total_nested:.2f}\n"
        else:
            report += "**Verdict**: Both strategies have the same total cost.\n"
    else:
        report += "Comparison incomplete due to missing data.\n"
    
    report += "\n## Strategy 1: Multi-City One-Ways\n"
    for i, res in enumerate(one_way_results):
        origin = trips[i]["city"]
        destination = trips[i+1]["city"]
        report += f"### {origin} -> {destination}\n"
        if res:
            report += f"- **Price**: ${res['price']}\n"
            report += f"- **Date**: {res['date']}\n"
            report += f"- **Duration**: {res['duration']}\n"
            report += f"- **Flight Numbers**: {', '.join(res['flight_numbers'])}\n"
            if res['layovers']:
                report += f"- **Layovers**: {'; '.join(res['layovers'])}\n"
            report += f"- [View on Google Flights]({res['url']})\n"
        else:
            report += "- *No flights found*\n"
        report += "\n"

    report += "## Strategy 2: Nested Round Trips\n"
    for i, res in enumerate(nested_results):
        origin = trips[i]["city"]
        destination = trips[i+1]["city"]
        report += f"### {origin} <-> {destination}\n"
        if res:
            report += f"- **Price**: ${res['price']}\n"
            report += f"- **Dates**: {res['dates'][0]} to {res['dates'][1]}\n"
            report += f"- **Duration**: {res['duration']}\n"
            report += f"- **Flight Numbers**: {', '.join(res['flight_numbers'])}\n"
            if res['layovers']:
                report += f"- **Layovers**: {'; '.join(res['layovers'])}\n"
            report += f"- [View on Google Flights]({res['url']})\n"
        else:
            report += "- *No flights found*\n"
        report += "\n"

    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report)
    print("\nMarkdown report generated: report.md")

def main():
    parser = argparse.ArgumentParser(description="Compare Multi-City vs Nested Round Trips from CSV with Date Ranges")
    parser.add_argument("--csv", type=str, default="trips.csv", help="Path to the CSV file")
    parser.add_argument("--retries", type=int, default=5, help="Number of retries per search")
    args = parser.parse_args()

    trips = []
    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                earliest = normalize_date(row.get("earliest_leave"))
                latest = normalize_date(row.get("latest_leave")) or earliest
                trips.append({
                    "city": row["city"].strip().upper(),
                    "date_range": get_date_range(earliest, latest)
                })
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return []
    return trips

def send_email(report_md, recipients=None, parent_id=None):
    if recipients is None:
        recipients = ["ph9214@gmail.com"]
        
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("Error: RESEND_API_KEY environment variable not set. Skipping email.")
        return None

    # Simple MD to HTML conversion for the email
    html_content = report_md.replace("# ", "<h1>").replace("## ", "<h2>").replace("### ", "<h3>")
    html_content = html_content.replace("\n", "<br>")
    html_content = f"<html><body>{html_content}</body></html>"

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "from": "FlightFinder <onboarding@resend.dev>",
        "to": recipients,
        "subject": f"Flight Comparison Report - {datetime.now().strftime('%Y-%m-%d')}",
        "html": html_content
    }

    if parent_id:
        data["headers"] = {
            "In-Reply-To": f"<{parent_id}>",
            "References": f"<{parent_id}>"
        }

    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200 or response.status_code == 201:
            msg_id = response.json().get("id")
            print(f"Email sent successfully to {', '.join(recipients)} (ID: {msg_id})")
            return msg_id
        else:
            print(f"Failed to send email: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error sending email: {e}")
        return None

def get_parent_id():
    path = "/app/parent_id.txt"
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read().strip()
    return None

def save_parent_id(msg_id):
    path = "/app/parent_id.txt"
    with open(path, "w") as f:
        f.write(msg_id)

def run_comparison(trips, retries):
    if len(trips) < 2:
        print("Error: CSV must contain at least an origin and a destination.")
        return None

    print(f"=== Comparing Multi-City One-Ways vs Nested Round Trips for {len(trips)} cities ===")
    print(f"Retries: {retries}\n")

    # Strategy 1: Multi-City One-Ways
    print("--- Strategy 1: Multi-City One-Ways ---")
    one_way_results = []
    total_oneways = 0
    all_oneways_found = True

    for i in range(len(trips) - 1):
        origin = trips[i]["city"]
        destination = trips[i+1]["city"]
        date_range = trips[i]["date_range"]
        
        res = get_best_price(origin, destination, date_range, max_retries=retries)
        one_way_results.append(res)
        if res:
            total_oneways += res["price"]
        else:
            all_oneways_found = False

    if all_oneways_found:
        print(f"\nSummary Strategy 1: Total One-Ways: ${total_oneways:.2f}")
    else:
        print("\nSummary Strategy 1: N/A (Some legs failed)")
        total_oneways = None

    # Strategy 2: Nested Round Trips
    print("\n--- Strategy 2: Nested Round Trips ---")
    nested_results = []
    total_nested = 0
    all_nested_found = True
    
    # The final return date is determined by the last valid departure range in the CSV
    final_return_range = None
    for t in reversed(trips):
        if t["date_range"]:
            final_return_range = t["date_range"]
            break
            
    if not final_return_range:
        print("Error: No valid return date range found in CSV.")
        return None

    for i in range(len(trips) - 1):
        origin = trips[i]["city"]
        destination = trips[i+1]["city"]
        depart_range = trips[i]["date_range"]
        
        res = get_round_trip_price(origin, destination, depart_range, final_return_range, max_retries=retries)
        nested_results.append(res)
        if res:
            total_nested += res["price"]
        else:
            all_nested_found = False

    if all_nested_found:
        print(f"\nSummary Strategy 2:")
        for i, res in enumerate(nested_results):
            print(f"  {trips[i]['city']}<->{trips[i+1]['city']}: ${res['price']}")
        print(f"  Total Nested: ${total_nested:.2f}")
    else:
        print("\nSummary Strategy 2: N/A (Some legs failed)")
        total_nested = None

    print("\n=== Final Comparison ===")
    if total_oneways is not None and total_nested is not None:
        print(f"Multi-City One-Ways: ${total_oneways:.2f}")
        print(f"Nested Round Trips:  ${total_nested:.2f}")
        if total_oneways < total_nested:
            print(f"\nOne-Ways are cheaper by ${total_nested - total_oneways:.2f}")
        elif total_nested < total_oneways:
            print(f"\nNested Round Trips are cheaper by ${total_oneways - total_nested:.2f}")
        else:
            print("\nBoth strategies have the same total cost.")
    else:
        print("Comparison incomplete due to missing data.")

    report_md = generate_markdown_report(trips, one_way_results, nested_results, total_oneways, total_nested)
    with open("report.md", "w") as f:
        f.write(report_md)
    print("\nMarkdown report generated: report.md")
    return report_md

def main():
    parser = argparse.ArgumentParser(description="Compare flight strategies.")
    parser.add_argument("--csv", default="trips.csv", help="Path to trips CSV file")
    parser.add_argument("--retries", type=int, default=5, help="Number of retries for fetching")
    parser.add_argument("--email", action="store_true", help="Send report via email")
    parser.add_argument("--sanity", action="store_true", help="Send a sanity check email and exit")
    parser.add_argument("--startup", action="store_true", help="Send sanity email, save ID, and run full search")
    args = parser.parse_args()

    if args.sanity:
        print("Sending sanity check email...")
        send_email("This is a sanity check email from FlightFinder. If you receive this, the email system is working correctly!")
        return

    if args.startup:
        print("Running startup sequence...")
        # 1. Send sanity email and save its ID as the parent
        parent_id = send_email("This is the main thread for your FlightFinder reports. All future reports will be sent as replies to this email.")
        if parent_id:
            save_parent_id(parent_id)
            print(f"Saved parent ID: {parent_id}")
        
        # 2. Run full search immediately
        print("Running initial flight search...")
        trips = read_trips_csv(args.csv)
        report_md = run_comparison(trips, args.retries)
        
        # 3. Send report as a reply
        if report_md:
            send_email(report_md, parent_id=parent_id)
        return

    trips = read_trips_csv(args.csv)
    report_md = run_comparison(trips, args.retries)
    
    if args.email and report_md:
        parent_id = get_parent_id()
        if not parent_id:
            print("No parent ID found. Sending as a new thread and saving ID.")
            parent_id = send_email("Initializing FlightFinder report thread.")
            if parent_id:
                save_parent_id(parent_id)
        
        send_email(report_md, parent_id=parent_id)
    elif not args.email and report_md:
        print(report_md)

if __name__ == "__main__":
    main()
