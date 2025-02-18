from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from flask_caching import Cache
import pymysql
import getOauthURL
import math
import hashlib

app = Flask(__name__)
CORS(app)

# Configure Redis Cache
app.config['CACHE_TYPE'] = 'SimpleCache'
# Comment out Redis-specific configs
# app.config['CACHE_REDIS_HOST'] = 'localhost'
# app.config['CACHE_REDIS_PORT'] = 6379
# app.config['CACHE_REDIS_DB'] = 0
# app.config['CACHE_REDIS_URL'] = 'redis://localhost:6379/0'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 minutes cache
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

@app.route('/search', methods=['GET'])
def search():
    try:
        keyword = request.args.get('q', '').strip().lower()
        latitude = request.args.get('lat', type=float)
        longitude = request.args.get('lon', type=float)
        zoom = request.args.get('zoom', type=int, default=9)
        
        print(f"Search params - keyword: {keyword}, lat: {latitude}, lon: {longitude}, zoom: {zoom}")

        if not keyword:
            return jsonify({"data": []})

        # Calculate bounds
        DEGREES_PER_PIXEL = 0.00028
        map_range = DEGREES_PER_PIXEL * (1 << (21 - zoom)) * 1000
        if zoom < 10:
            map_range *= 2

        connection = get_db_connection()
        if connection is None:
            return jsonify({"error": "Database connection failed"}), 500

        try:
            with connection.cursor() as cursor:
                query = """
                    SELECT 
                        ID, Name, Branch, Altname, Altbranch, Latitude, Longitude, Postal, Address,
                        (6371 * ACOS(
                            LEAST(1, GREATEST(-1, 
                                COS(RADIANS(%s)) * COS(RADIANS(Latitude)) * 
                                COS(RADIANS(Longitude) - RADIANS(%s)) + 
                                SIN(RADIANS(%s)) * SIN(RADIANS(Latitude))
                            ))
                        )) AS distance,
                        CASE 
                            WHEN Name = %s THEN 100
                            WHEN Branch = %s THEN 90
                            WHEN Postal = %s THEN 80
                            WHEN Name LIKE CONCAT('%%', %s, '%%') THEN 70
                            WHEN Branch LIKE CONCAT('%%', %s, '%%') THEN 60
                            WHEN Address LIKE CONCAT('%%', %s, '%%') THEN 50
                            WHEN MATCH(Name, Branch, Address) AGAINST(%s IN BOOLEAN MODE) THEN 40
                            ELSE 0
                        END as relevance
                    FROM poitbl 
                    WHERE 
                        (
                            Name LIKE CONCAT('%%', %s, '%%') OR
                            Branch LIKE CONCAT('%%', %s, '%%') OR
                            Address LIKE CONCAT('%%', %s, '%%') OR
                            Postal = %s OR
                            MATCH(Name, Branch, Address) AGAINST(%s IN BOOLEAN MODE)
                        )
                        AND Latitude BETWEEN %s - %s AND %s + %s
                        AND Longitude BETWEEN %s - %s AND %s + %s
                    HAVING relevance > 0
                    ORDER BY relevance DESC, distance ASC;
                """
                
                keywords = keyword.split()
                boolkeyword = " ".join("+" + word for word in keywords)
                
                params = (
                    latitude, longitude, latitude,  # For distance calculation
                    keyword, keyword, keyword, keyword, keyword, keyword, boolkeyword,  # For CASE relevance
                    keyword, keyword, keyword, keyword, boolkeyword,  # For WHERE conditions
                    latitude, map_range, latitude, map_range,  # For latitude bounds
                    longitude, map_range, longitude, map_range  # For longitude bounds
                )
                
                print("Executing query with params:", params)
                cursor.execute(query, params)
                results = cursor.fetchall()
                print(f"Found {len(results)} results")

                if not results:
                    return jsonify({"data": []})

                # Perform clustering with relevance consideration
                clusters = []
                processed = set()
                
                for i, point in enumerate(results):
                    if i in processed:
                        continue
                        
                    cluster = {
                        'center_lat': float(point['Latitude']),
                        'center_lon': float(point['Longitude']),
                        'points': [point],
                        'relevance': float(point['relevance'])
                    }
                    
                    # Find nearby points
                    for j, other in enumerate(results):
                        if j == i or j in processed:
                            continue
                            
                        # Calculate distance between points
                        distance = math.sqrt(
                            (float(point['Latitude']) - float(other['Latitude'])) ** 2 +
                            (float(point['Longitude']) - float(other['Longitude'])) ** 2
                        )
                        
                        # Adjust cluster radius based on zoom and relevance
                        cluster_radius = 0.01 / (2 ** (zoom - 5))
                        if distance < cluster_radius:
                            cluster['points'].append(other)
                            processed.add(j)
                            
                            # Update cluster center as weighted average
                            weight = 1.0 / len(cluster['points'])
                            cluster['center_lat'] = (float(cluster['center_lat']) * (1 - weight) + 
                                                   float(other['Latitude']) * weight)
                            cluster['center_lon'] = (float(cluster['center_lon']) * (1 - weight) + 
                                                   float(other['Longitude']) * weight)
                    
                    clusters.append(cluster)
                    processed.add(i)

                # Format response
                response_data = []
                for i, cluster in enumerate(clusters):
                    cluster_data = {
                        'cluster_id': i,
                        'center_lat': float(cluster['center_lat']),
                        'center_lon': float(cluster['center_lon']),
                        'count': len(cluster['points']),
                        'points': [{
                            'id': str(point['ID']),
                            'name': str(point['Name']),
                            'branch': str(point['Branch']) if point['Branch'] else '',
                            'altname': str(point['Altname']) if point['Altname'] else '',
                            'altbranch': str(point['Altbranch']) if point['Altbranch'] else '',
                            'latitude': float(point['Latitude']),
                            'longitude': float(point['Longitude']),
                            'postal': str(point['Postal']) if point['Postal'] else '',
                            'address': str(point['Address']) if point['Address'] else '',
                            'relevance': point['relevance']
                        } for point in cluster['points']]
                    }
                    response_data.append(cluster_data)

                return jsonify({"data": response_data})

        finally:
            connection.close()

    except Exception as e:
        print("Search error:", str(e))
        import traceback
        traceback.print_exc()
        return jsonify({"error": "An error occurred during the search operation"}), 500

@app.route('/')
def index():
    apicall = getOauthURL.getUrl()
    return render_template('index.html', api_url=apicall)

if __name__ == '__main__':
    app.run(debug=True, host='localhost', port=5000)
