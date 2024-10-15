import pandas as pd
from flask import Flask, render_template, request
import requests
import json
from datetime import datetime
import math

app = Flask(__name__)

# Load configuration from JSON file
with open('config.json') as config_file:
    config = json.load(config_file)
    GOOGLE_MAPS_API_KEY = config['GOOGLE_MAPS_API_KEY']
    token = config['fuel_token']

# Set the headers for the requests
headers = {
    "Authorization": f"FPDAPI SubscriberToken={token}",
    "Content-Type": "application/json"
}

# Function to retrieve site details from the API
def get_site_details():
    url_site_details = "https://fppdirectapi-prod.fuelpricesqld.com.au/Subscriber/GetFullSiteDetails"
    params = {"countryId": "21", "GeoRegionLevel": "3", "GeoRegionId": "1"}
    response = requests.get(url_site_details, headers=headers, params=params)
    if response.status_code == 200:
        site_details_df = pd.json_normalize(response.json()['S'])
        site_details_df.rename(columns={'S': 'SiteId'}, inplace=True)
        return site_details_df
    return pd.DataFrame()

# Function to retrieve fuel types from the API
def get_fuel_types():
    url_fuel_types = "https://fppdirectapi-prod.fuelpricesqld.com.au/Subscriber/GetCountryFuelTypes"
    response = requests.get(url_fuel_types, headers=headers, params={"countryId": "21"})
    if response.status_code == 200:
        return pd.json_normalize(response.json()['Fuels'])
    return pd.DataFrame()

# Function to retrieve fuel prices from the API
def get_fuel_prices():
    url_site_prices = "https://fppdirectapi-prod.fuelpricesqld.com.au/Price/GetSitesPrices"
    params = {"countryId": "21", "geoRegionLevel": "3", "geoRegionId": "1"}
    response = requests.get(url_site_prices, headers=headers, params=params)
    if response.status_code == 200:
        return pd.json_normalize(response.json()['SitePrices'])
    return pd.DataFrame()

# Function to retrieve brand information
def get_brand_info():
    url_brands = "https://fppdirectapi-prod.fuelpricesqld.com.au/Subscriber/GetCountryBrands"
    response_brands = requests.get(url_brands, headers=headers, params={"countryId": "21"})
    if response_brands.status_code == 200:
        return pd.json_normalize(response_brands.json()['Brands'])
    return pd.DataFrame()  # Return empty DataFrame if fetch fails


def get_fastest_and_shortest_routes(origin, destination):
    base_url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": origin,
        "destination": destination,
        "key": GOOGLE_MAPS_API_KEY,
        "alternatives": "true"  # Request alternative routes
    }
    
    # Make request to Google Maps API
    response = requests.get(base_url, params=params)
    routes_data = response.json()

    if response.status_code == 200 and routes_data['status'] == 'OK':
        routes = routes_data.get('routes', [])

        if len(routes) < 2:
            # If fewer than 2 routes are returned, handle gracefully
            return routes[0], routes[0]  # Return the same route for both fastest and shortest if only one exists

        # Sort the routes based on duration (fastest) and distance (shortest)
        fastest_route = min(routes, key=lambda r: r['legs'][0]['duration']['value'])  # Shortest duration
        shortest_route = min(routes, key=lambda r: r['legs'][0]['distance']['value'])  # Shortest distance

        return fastest_route, shortest_route
    else:
        print("Error fetching routes:", routes_data.get('status'))
        return None, None


# Function to get routes from Google Maps API
def get_routes(origin, destination):
    base_url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": origin,
        "destination": destination,
        "key": GOOGLE_MAPS_API_KEY,
        "alternatives": "true"  # Request alternative routes
    }
    
    response = requests.get(base_url, params=params)
    routes_data = response.json()

    if response.status_code == 200 and routes_data['status'] == 'OK':
        routes = routes_data.get('routes', [])
        if not routes:
            print("No routes found.")
            return []

        # Sort routes by duration and distance
        fastest_routes = sorted(routes, key=lambda r: r['legs'][0]['duration']['value'])
        shortest_routes = sorted(routes, key=lambda r: r['legs'][0]['distance']['value'])

        # Combine and deduplicate routes based on unique criteria
        suggested_routes = []
        seen_routes = set()

        # Get up to 3 unique fastest routes
        for route in fastest_routes:
            route_key = route['overview_polyline']['points']
            if route_key not in seen_routes:
                suggested_routes.append(route)
                seen_routes.add(route_key)
            if len(suggested_routes) >= 3:
                break
        
        # If fewer than 3 routes found, fill in with shortest routes
        if len(suggested_routes) < 3:
            for route in shortest_routes:
                route_key = route['overview_polyline']['points']
                if route_key not in seen_routes:
                    suggested_routes.append(route)
                    seen_routes.add(route_key)
                if len(suggested_routes) >= 3:
                    break

        return suggested_routes
    else:
        print("Error fetching routes:", routes_data.get('status'))
        return []

# Function to calculate midpoint between two locations
def get_midpoint_between_locations(origin, destination):
    lat1, lng1 = origin
    lat2, lng2 = destination
    return (lat1 + lat2) / 2, (lng1 + lng2) / 2

# Function to filter stations by radius
def filter_stations_by_radius(midpoint, radius):
    min_lat = midpoint[0] - (radius / 110.574)  # Approximation for km to lat
    max_lat = midpoint[0] + (radius / 110.574)
    min_lng = midpoint[1] - (radius / (111.32 * abs(math.cos(math.radians(midpoint[0])))))  # Adjust for longitude
    max_lng = midpoint[1] + (radius / (111.32 * abs(math.cos(math.radians(midpoint[0])))))

    site_details_df = get_site_details()
    filtered_stations = site_details_df[
        (site_details_df['Lat'] >= min_lat) &
        (site_details_df['Lat'] <= max_lat) &
        (site_details_df['Lng'] >= min_lng) &
        (site_details_df['Lng'] <= max_lng)
    ]

    return filtered_stations.drop_duplicates(subset='SiteId')  # Ensure distinct stations

@app.route('/')
def home():
    return render_template('index.html',
                           google_maps_api_key=GOOGLE_MAPS_API_KEY
                           )

@app.route('/get-route', methods=['POST'])
def get_route():
    origin = request.form.get('origin')
    destination = request.form.get('destination')

    # Helper function to get the fuel consumption rate based on speed
    fuel_consumption_suv = {
        20: 20,
        40: 12,
        60: 10,
        80: 11,
        100: 12,
        120: 14,
    }

    def get_fuel_consumption_rate(speed):
        closest_speed = min(fuel_consumption_suv, key=lambda x: abs(x - speed))
        return fuel_consumption_suv[closest_speed]

    # Step 1: Fetch three routes
    routes = get_routes(origin, destination)
    #routes = get_fastest_and_shortest_routes(origin, destination)

    if not routes:
        return "Error calculating routes."

    # Ensure we have exactly three routes
    routes = routes[:5]

    # Extract coordinates from the first route
    origin_lat = routes[0]['legs'][0]['start_location']['lat']
    origin_lng = routes[0]['legs'][0]['start_location']['lng']
    destination_lat = routes[0]['legs'][0]['end_location']['lat']
    destination_lng = routes[0]['legs'][0]['end_location']['lng']

    # Step 3: Calculate midpoint
    midpoint = get_midpoint_between_locations((origin_lat, origin_lng), (destination_lat, destination_lng))

    # Step 5: Define a radius (in km) to find fuel stations around the midpoint
    radius_km = routes[0]['legs'][0]['distance']['value'] / 1000  # Convert to km
    print(radius_km)

    # Step 6: Get all fuel stations within the defined radius of the midpoint
    nearby_stations = filter_stations_by_radius(midpoint, radius_km)

    # Step 8: Fetch fuel prices for the nearby stations
    fuel_prices_df = get_fuel_prices()
    fuel_types_df = get_fuel_types()

    # Apply the format_timestamp function to handle both formats
    fuel_prices_df['TransactionDateUtc'] = fuel_prices_df['TransactionDateUtc'].apply(format_timestamp)
    fuel_prices_df['Price'] = fuel_prices_df['Price'] / 1000  # Convert price to dollars

    unleaded_prices = []

    for idx, station in nearby_stations.iterrows():
        price_info = fuel_prices_df[fuel_prices_df['SiteId'] == station['SiteId']]
        if not price_info.empty:
            station['PriceInfo'] = price_info.to_dict(orient='records')
            unleaded_price = price_info[price_info['FuelId'] == 2]['Price'].values
            if len(unleaded_price) > 0:
                unleaded_prices.append(unleaded_price[0])

    # Step 9: Calculate average unleaded price
    average_unleaded_price = sum(unleaded_prices) / len(unleaded_prices) if unleaded_prices else 0

    # Extract details for each route
    route_details = []
    for i, route in enumerate(routes):
        distance = sum(leg['distance']['value'] for leg in route['legs']) / 1000  # Distance in km
        duration = sum(leg['duration']['value'] for leg in route['legs']) / 60  # Duration in minutes
        average_speed = distance / (duration / 60) if duration > 0 else 0  # Average speed in km/h

        # Calculate estimated fuel consumption
        fuel_rate = get_fuel_consumption_rate(average_speed)
        fuel_consumption = (fuel_rate * distance) / 100  # Fuel consumption in liters

        # Calculate estimated fuel cost
        fuel_cost = fuel_consumption * average_unleaded_price  # Fuel cost in AUD

        route_details.append({
            'distance': distance,
            'duration': duration,
            'average_speed': average_speed,
            'fuel_consumption': fuel_consumption,
            'fuel_cost': fuel_cost,  # Include fuel cost here
            'average_unleaded_price': average_unleaded_price
        })

    # Define a list of colors to distinguish routes
    colors = ['#FF0000', '#0000FF', '#00FF00', '#FFA500', '#800080']  # Add more colors if needed

    return render_template('route.html',
                           routes=route_details,
                           origin_lat=origin_lat,
                           origin_lng=origin_lng,
                           destination_lat=destination_lat,
                           destination_lng=destination_lng,
                           google_maps_api_key=GOOGLE_MAPS_API_KEY,
                           colors=colors
                           )

# Function to format timestamps for the dataframe
def format_timestamp(timestamp):
    # Check if timestamp is in the expected format
    try:
        if isinstance(timestamp, str):
            if len(timestamp) == 10:  # Date only
                return datetime.strptime(timestamp, '%Y-%m-%d').date()
            elif len(timestamp) == 20:  # Full timestamp
                return datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        return timestamp
    except Exception as e:
        print("Error formatting timestamp:", e)
        return timestamp

if __name__ == '__main__':
    app.run(debug=True)