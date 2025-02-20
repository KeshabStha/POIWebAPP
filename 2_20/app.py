from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_caching import Cache
import pymysql
import getOauthURL
import math

app = Flask(__name__)
CORS(app)

app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300 
cache = Cache(app)

db_config = {
    'host': 'localhost',
    'user': 'admin',
    'password': 'password',
    'db': 'poidb',
    'cursorclass': pymysql.cursors.DictCursor
}

def get_db_connection():
    try:
        return pymysql.connect(**db_config)
    except pymysql.MySQLError as e:
        print("Database connection error:", e)
        return None

def calculate_cluster_radius(zoom):
    # Base radius in degrees (roughly 1km at equator)
    base_radius = 1  
    # Adjust radius based on zoom level
    return base_radius * (2 ** (15 - zoom))

def cluster_results(results, grid_size=0.01):
    """Cluster search results based on grid size"""
    clusters = {}
    
    for point in results:
        lat = float(point['Latitude'])
        lon = float(point['Longitude'])
        
        # Create grid cell key
        grid_x = int(lat / grid_size)
        grid_y = int(lon / grid_size)
        grid_key = f"{grid_x}:{grid_y}"
        
        if grid_key not in clusters:
            clusters[grid_key] = {
                'center_lat': lat,
                'center_lon': lon,
                'points': [],
                'relevance_score': float(point['relevance_score'])
            }
        
        clusters[grid_key]['points'].append({
            'id': str(point['ID']),
            'name': str(point['Name']),
            'branch': str(point['Branch']) if point['Branch'] else '',
            'latitude': lat,
            'longitude': lon,
            'postal': str(point['Postal']) if point['Postal'] else '',
            'address': str(point['Address']) if point['Address'] else '',
            'relevance_score': float(point['relevance_score'])
        })

    # Format response
    response_data = [
        {
            'cluster_id': i,
            'center_lat': cluster['center_lat'],
            'center_lon': cluster['center_lon'],
            'count': len(cluster['points']),
            'points': sorted(cluster['points'], key=lambda x: x['relevance_score'], reverse=True)
        }
        for i, cluster in enumerate(clusters.values())
    ]

    return response_data

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points using Haversine formula"""
    R = 6371  # Earth's radius in km
    
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c

def search_database(keyword):
    """Search entire database with given parameters"""
    natural_query = " ".join(keyword.split())
    boolean_query = " ".join([f'+{word}*' for word in keyword.split()])
    rlike_query = "|".join(keyword.split())
    postal_query = keyword if keyword.isdigit() else ""
    
    connection = get_db_connection()
    if connection is None:
        raise Exception("Database connection failed")
        
    try:
        with connection.cursor() as cursor:
            query = """
                SELECT ID, Name, Branch, Latitude, Longitude, Postal, Address,
                    MATCH(Name, Branch, Address) AGAINST(%s IN NATURAL LANGUAGE MODE) AS relevance_score
                FROM poitbl
                WHERE MATCH(Name, Branch, Address) AGAINST(%s IN BOOLEAN MODE)
                AND ((Name RLIKE %s OR Branch RLIKE %s OR Address RLIKE %s) 
                     OR Postal = %s)
                ORDER BY relevance_score DESC;
            """

            params = (
                natural_query,
                boolean_query,
                rlike_query, rlike_query, rlike_query,
                postal_query
            )
            
            cursor.execute(query, params)
            return cursor.fetchall()
    finally:
        connection.close()

@app.route('/search', methods=['GET'])
def search():
    try:
        keyword = request.args.get('q', '').strip().lower()
        if not keyword:
            return jsonify({"data": []})

        # Search entire database first
        results = search_database(keyword)
        
        # Calculate distances from current center
        center_lat = request.args.get('centerLat', type=float)
        center_lon = request.args.get('centerLon', type=float)
        
        # Process all results with distances
        points_data = []
        for point in results:
            distance = calculate_distance(
                center_lat, center_lon,
                float(point['Latitude']), float(point['Longitude'])
            )
            points_data.append({
                'id': str(point['ID']),
                'name': str(point['Name']),
                'branch': str(point['Branch']) if point['Branch'] else '',
                'latitude': float(point['Latitude']),
                'longitude': float(point['Longitude']),
                'postal': str(point['Postal']) if point['Postal'] else '',
                'address': str(point['Address']) if point['Address'] else '',
                'distance': f"{distance:.1f}km" if distance >= 1 else f"{int(distance * 1000)}m",
                'distance_value': distance
            })

        # Sort by distance
        points_data.sort(key=lambda x: x['distance_value'])
        
        return jsonify({"data": points_data})

    except Exception as e:
        print("Search error:", str(e))
        import traceback
        traceback.print_exc()
        return jsonify({"error": "An error occurred"}), 500

@app.route("/")
def index():
    api_url = getOauthURL.getUrl()
    return render_template("index.html", api_url=api_url)

if __name__ == "__main__":
    app.run(debug=True, host="localhost", port=5000)
