import pandas as pd
from flask import Flask, render_template, request
import requests
import os
import json
from datetime import datetime

app = Flask(__name__)

# Replace with your actual Google Maps API key
GOOGLE_MAPS_API_KEY = "AIzaSyBm6Y9yC8mxarLzSOr_7V9BYSXylw4XpPQ"

# Set your API token
token = "5067f5e2-7e7f-49a7-bf4e-69b069e204c4"  # Replace with your actual token

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
        
        # Rename the 'S' column to 'SiteId' for merging with fuel prices
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

def get_brand_info():
    url_brands = "https://fppdirectapi-prod.fuelpricesqld.com.au/Subscriber/GetCountryBrands"
    response_brands = requests.get(url_brands, headers=headers, params={"countryId": "21"})
    if response_brands.status_code == 200:
        brand_info_df = pd.json_normalize(response_brands.json()['Brands'])
    else:
        brand_info_df = pd.DataFrame()  # Return empty DataFrame if fetch fails
    return brand_info_df

# Divide the route into num_points equal points
def divide_route(route, total_distance, num_points):
    steps = route['steps']
    segment_distance = total_distance / num_points
    
    points = []
    distance_accumulated = 0
    for step in steps:
        step_distance = step['distance']['value'] / 1000  # Convert to km
        while distance_accumulated + step_distance >= segment_distance:
            ratio = (segment_distance - distance_accumulated) / step_distance
            lat = step['start_location']['lat'] + ratio * (step['end_location']['lat'] - step['start_location']['lat'])
            lng = step['start_location']['lng'] + ratio * (step['end_location']['lng'] - step['start_location']['lng'])
            points.append((lat, lng))
            distance_accumulated = 0  # Reset the accumulated distance for next point
            step_distance -= segment_distance
        distance_accumulated += step_distance

    return points

# Get bounding box from a list of lat/lng points
def get_bounding_box(points):
    latitudes = [p[0] for p in points]
    longitudes = [p[1] for p in points]
    return min(latitudes), max(latitudes), min(longitudes), max(longitudes)

# Get the route distance and information from origin to destination
def get_route_distance_and_info(origin, destination, waypoint=None):
    if waypoint:
        google_maps_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin}&destination={destination}&waypoints={waypoint}&key={GOOGLE_MAPS_API_KEY}"
    else:
        google_maps_url = f"https://maps.googleapis.com/maps/api/directions/json?origin={origin}&destination={destination}&key={GOOGLE_MAPS_API_KEY}"

    response = requests.get(google_maps_url)
    route_data = response.json()

    if response.status_code == 200 and route_data['status'] == 'OK':
        total_distance = sum([leg['distance']['value'] for leg in route_data['routes'][0]['legs']]) / 1000  # Convert to km
        return total_distance, route_data['routes'][0]['legs'][0]
    else:
        return None, None

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

# Function to handle different timestamp formats
def format_timestamp(timestamp):
    try:
        # Try parsing with microseconds
        return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%f').strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        # Fallback to parsing without microseconds
        return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get-route', methods=['POST'])
def get_route():
    origin = request.form.get('origin')
    destination = request.form.get('destination')

    # Step 1: Fetch both fastest and shortest routes
    fastest_route, shortest_route = get_fastest_and_shortest_routes(origin, destination)

    if not fastest_route or not shortest_route:
        return "Error calculating routes."

    # Step 2: Use the fastest route as the original route
    original_distance = sum([leg['distance']['value'] for leg in fastest_route['legs']]) / 1000  # Distance in km
    original_duration = sum([leg['duration']['value'] for leg in fastest_route['legs']]) / 3600  # Duration in hours
    original_avg_speed = original_distance / original_duration  # Average speed in km/h
    original_steps = fastest_route['legs'][0]['steps']

    # SUV fuel consumption rates by speed from the table
    fuel_consumption_suv = {
        20: 20,
        40: 12,
        60: 10,
        80: 11,
        100: 12,
        120: 14,
    }

    # Helper function to get the fuel consumption rate based on speed
    def get_fuel_consumption_rate(speed):
        closest_speed = min(fuel_consumption_suv, key=lambda x: abs(x - speed))
        return fuel_consumption_suv[closest_speed]

    # Calculate estimated fuel consumption for the fastest route (original route)
    fuel_rate_original = get_fuel_consumption_rate(original_avg_speed)
    original_fuel_consumption = (fuel_rate_original / 100) * original_distance

    # Step 3: Divide the route into 10 points based on the original distance
    points = divide_route({'steps': original_steps}, original_distance, 10)

    # Step 4: Get the bounding box
    min_lat, max_lat, min_lng, max_lng = get_bounding_box(points)

    site_details_df = get_site_details()
    # Filter stations based on the bounding box
    filtered_stations = site_details_df[
        (site_details_df['Lat'] >= min_lat) &
        (site_details_df['Lat'] <= max_lat) &
        (site_details_df['Lng'] >= min_lng) &
        (site_details_df['Lng'] <= max_lng)
    ]

    # Ensure SiteId is distinct
    filtered_stations = filtered_stations.drop_duplicates(subset='SiteId')

    # Step 5: Build route info for the original route and alternative routes via fuel stations
    route_info = [{
        'name': 'Fastest Route',
        'distance': original_distance,
        'duration': original_duration * 60,  # Duration in minutes
        'average_speed': original_avg_speed,  # Original route average speed
        'fuel_consumption': original_fuel_consumption,  # Estimated fuel consumption
        'distance_diff': 0,  # Distance difference for original route is 0
        'fuel_station': None
    }]

    # Generate routes via each distinct fuel station (without merging with price/fuel types yet)
    for idx, station in filtered_stations.iterrows():
        waypoint = f"{station['Lat']},{station['Lng']}"
        distance_with_waypoint, _ = get_route_distance_and_info(origin, destination, waypoint)

        if distance_with_waypoint:
            distance_diff = distance_with_waypoint - original_distance
            duration_with_waypoint = sum([leg['duration']['value'] for leg in fastest_route['legs']]) / 3600  # Duration in hours
            avg_speed_with_waypoint = distance_with_waypoint / duration_with_waypoint  # Average speed

            # Calculate estimated fuel consumption
            fuel_rate = get_fuel_consumption_rate(avg_speed_with_waypoint)
            fuel_consumption_with_waypoint = (fuel_rate / 100) * distance_with_waypoint

            route_info.append({
                'name': f"Route via {station['N']}",
                'distance': distance_with_waypoint,
                'duration': duration_with_waypoint * 60,  # Duration in minutes
                'average_speed': avg_speed_with_waypoint,  # Average speed
                'fuel_consumption': fuel_consumption_with_waypoint,  # Estimated fuel consumption
                'distance_diff': distance_diff,  # Distance difference
                'fuel_station': station.to_dict()  # Store station details
            })

    # Step 6: Sort the routes by distance and limit to the top 5 alternative routes
    sorted_routes = sorted(route_info[1:], key=lambda x: x['distance'])[:6]

    # Add the original route at the start
    sorted_routes.insert(0, route_info[0])

    # Step 7: Merge price and fuel type information for the top 5 routes
    fuel_prices_df = get_fuel_prices()
    fuel_types_df = get_fuel_types()

    # Apply the format_timestamp function to handle both formats
    fuel_prices_df['TransactionDateUtc'] = fuel_prices_df['TransactionDateUtc'].apply(format_timestamp)
    fuel_prices_df['Price'] = fuel_prices_df['Price'] / 1000

    unleaded_prices = []
    
    for route in sorted_routes[1:]:  # Skip the original route since it has no station
        station_data = route['fuel_station']

        # Merge fuel prices
        price_info = fuel_prices_df[fuel_prices_df['SiteId'] == station_data['SiteId']]

        if not price_info.empty:
            route['fuel_station']['PriceInfo'] = price_info.to_dict(orient='records')

            # Get unleaded price (assuming unleaded fuel has FuelId 2 or similar identifier)
            unleaded_price = price_info[price_info['FuelId'] == 2]['Price'].values
            if len(unleaded_price) > 0:
                unleaded_prices.append(unleaded_price[0])
            #    unleaded_price_per_station = unleaded_price[0]

            #    # Calculate fuel cost based on station-specific unleaded price
            #    route['fuel_cost'] = route['fuel_consumption'] * unleaded_price_per_station
            #else:
            #    route['fuel_cost'] = 0  # Set cost to 0 if no unleaded price found

        # Merge fuel types
        fuel_type_info = fuel_types_df[fuel_types_df['FuelId'].isin(price_info['FuelId'].unique())]

        if not fuel_type_info.empty:
            route['fuel_station']['FuelType'] = fuel_type_info.to_dict(orient='records')

    # Step 8: Calculate average unleaded price
    if unleaded_prices:
        average_unleaded_price = sum(unleaded_prices) / len(unleaded_prices)
    else:
        average_unleaded_price = 0

    # Step 9: Calculate fuel cost for each route
    for route in sorted_routes:
        route['fuel_cost'] = route['fuel_consumption'] * average_unleaded_price

    # Step 10: Calculate average speed for the shortest route
    shortest_distance = sum([leg['distance']['value'] for leg in shortest_route['legs']]) / 1000  # Distance in km
    shortest_duration = sum([leg['duration']['value'] for leg in shortest_route['legs']]) / 3600  # Duration in hours
    shortest_avg_speed = shortest_distance / shortest_duration  # Average speed in km/h

    # Calculate estimated fuel consumption for the shortest route
    fuel_rate_shortest = get_fuel_consumption_rate(shortest_avg_speed)
    shortest_fuel_consumption = (fuel_rate_shortest / 100) * shortest_distance
    shortest_fuel_cost = shortest_fuel_consumption * average_unleaded_price

    # Step 11: Render the distances and fuel station info on the page
    return render_template(
        'route.html',
        fastest_route={
            'distance': original_distance,  # Fastest route distance
            'duration': original_duration * 60,  # Fastest route duration in minutes
            'average_speed': original_avg_speed,  # Fastest route average speed
            'fuel_consumption': original_fuel_consumption,  # Fastest route estimated fuel consumption
            'fuel_cost': original_fuel_consumption * average_unleaded_price  # Fastest route fuel cost
        },
        shortest_route={
            'distance': shortest_distance,  # Shortest route distance in km
            'duration': shortest_duration * 60,  # Shortest route duration in minutes
            'average_speed': shortest_avg_speed,  # Shortest route average speed
            'fuel_consumption': shortest_fuel_consumption,  # Shortest route estimated fuel consumption
            'fuel_cost': shortest_fuel_cost  # Shortest route fuel cost
        },
        route_info=sorted_routes,  # Top 5 routes with fuel stations
        origin=origin,
        destination=destination
    )


application = app

if __name__ == '__main__':
    application.run(debug=True)