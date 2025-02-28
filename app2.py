from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import pymysql
import apicalling
import time
import getOauthURL
import math
from contextlib import contextmanager

app = Flask(__name__)
CORS(app)

db_config = {
    'host': 'localhost',
    'user': 'admin',
    'password': 'password',
    'db': 'poidb',
    'cursorclass': pymysql.cursors.DictCursor,
    'connect_timeout': 600,
}

@app.errorhandler(Exception)
def handle_error(error):
    print("Error2:", str(error))
    return jsonify({"error": "An internal error occurred"}), 500

def get_db_connection():
    try:
        return pymysql.connect(**db_config)
    except pymysql.MySQLError as e:
        print("Database connection error:", e)
        raise Exception("Database connection failed")

# Helper function to get results from the view
def fetch_results_from_view(limit, offset):
    connection = get_db_connection()
    if connection is None:
        return {"error": "Database connection failed"}, 500

    try:
        with connection.cursor() as cursor:
            query = """
                SELECT * FROM search_view
                LIMIT %s OFFSET %s;
            """
            cursor.execute(query, (limit, offset))
            results = cursor.fetchall()
            return results, 200
    except Exception as e:
        print("Error:", e)
        return {"error": "An error occurred"}, 500
    finally:
        connection.close()

def sanitize_search_input(keyword):
    # Remove any dangerous characters for RLIKE
    return ''.join(char for char in keyword if char.isalnum() or char.isspace())

# Route: /search
@app.route('/search', methods=['GET'])
def search():
    keyword = sanitize_search_input(request.args.get('q', '').strip().lower())
    latitude = request.args.get('lat', type=float)
    longitude = request.args.get('lon', type=float)
    start = time.time()

    natural_query = " ".join(keyword.split())
    boolean_query = " ".join([f'+{word}' for word in keyword.split()])
    rlike_query = "|".join(keyword.split())
    postal_query = tuple(keyword.split())

    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))

    if not keyword:
        return jsonify([])

    connection = get_db_connection()
    if connection is None:
        return jsonify({"error": "Database connection failed"}), 500

    try:
        with connection.cursor() as cursor:
            # Create or Replace View
            query = """
                create or replace view search_view as
                SELECT 
                    ID, Name, Branch, Latitude, Longitude, Postal, Address,
                    (6371 * ACOS(
                        LEAST(1, GREATEST(-1, 
                            COS(RADIANS(%s)) * COS(RADIANS(Latitude)) * 
                            COS(RADIANS(Longitude) - RADIANS(%s)) + 
                            SIN(RADIANS(%s)) * SIN(RADIANS(Latitude))
                        ))
                    )) AS distance,
                    MATCH(Name, Branch, Address) AGAINST(%s IN BOOLEAN MODE) AS relevance_score
                FROM poitbl
                WHERE 
                    MATCH(Name, Branch, Address) AGAINST(%s IN BOOLEAN MODE)
                    AND (
                        MATCH(Name, Branch, Address) AGAINST(%s IN NATURAL LANGUAGE MODE)
                        OR (Name RLIKE %s OR Branch RLIKE %s OR Address RLIKE %s OR Postal IN %s)
                    )
                ORDER BY relevance_score ASC, distance ASC;
            """
            cursor.execute(query, (latitude, longitude, latitude, boolean_query, boolean_query, natural_query, rlike_query, rlike_query, rlike_query, postal_query))
            connection.commit()
        with connection.cursor() as cursor:    
            count_query = "SELECT COUNT(*) AS total_count FROM search_view;"
            cursor.execute(count_query)
            total = cursor.fetchone()['total_count']
            print(total)
        # Fetch results from the view using the helper
        results, status = fetch_results_from_view(limit, offset)
        if status != 200:
            return jsonify(results), status

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": "An error occurred"}), 500
    finally:
        connection.close()

    # Format the data consistently with lowercase property names
    data = [
        {
            "id": row["ID"],
            "name": row["Name"],
            "branch": row["Branch"],
            "latitude": row["Latitude"],
            "longitude": row["Longitude"],
            "postal": row["Postal"],
            "address": row["Address"]
        }
        for row in results
    ]
        # Measure the time taken for the search operation
    end = time.time()
    print(f"Search operation took {end - start} seconds")
    return jsonify({"total": total, "results": data})

@app.route('/moreResults', methods=['GET'])
def getMoreResults():
    offset = int(request.args.get('offset', 0))
    limit = int(request.args.get('limit', 100))

    results, status = fetch_results_from_view(limit, offset)
    if status != 200:
        return jsonify(results), status

    # Format the data consistently with lowercase property names
    formatted_results = [
        {
            "id": row["ID"],
            "name": row["Name"],
            "branch": row["Branch"],
            "latitude": row["Latitude"],
            "longitude": row["Longitude"],
            "postal": row["Postal"],
            "address": row["Address"]
        }
        for row in results
    ]

    return jsonify(formatted_results)

@app.route('/')
def index():
    connection = get_db_connection()
    if connection is None:
        return jsonify({"error": "Database connection failed"}), 500
    with connection.cursor() as cursor:
        cursor.execute("""
            CREATE OR REPLACE VIEW search_view AS 
            SELECT NULL AS ID, NULL AS Name, NULL AS Branch, NULL AS Latitude, NULL AS Longitude, 
                NULL AS Postal, NULL AS Address, NULL AS distance, NULL AS relevance_score 
            FROM poitbl 
            WHERE 1=0;
                       """)
    connection.close()
    api_url = getOauthURL.getUrl()
    # api_url = apicalling.apicall()
    return render_template('index2.html', api_url=api_url)

@contextmanager
def get_db_cursor():
    connection = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        yield cursor
        connection.commit()
    finally:
        if connection:
            connection.close()

def cluster_points(points, zoom_level):
    try:
        # Ensure zoom level is within reasonable bounds
        zoom_level = max(1, min(21, zoom_level))
        
        # Adjust grid size calculation to handle extreme zoom levels
        base_grid_size = 0.1  # Base grid size in degrees
        if zoom_level <= 5:
            grid_size = base_grid_size
        else:
            grid_size = base_grid_size / (2 ** (zoom_level - 5))
        
        clusters = {}
        
        for point in points:
            try:
                # Ensure coordinates are valid numbers
                lat = float(point['Latitude'])
                lon = float(point['Longitude'])
                
                # Create grid cell key based on rounded coordinates
                grid_lat = math.floor(lat / grid_size) * grid_size
                grid_lon = math.floor(lon / grid_size) * grid_size
                cell_key = f"{grid_lat},{grid_lon}"
                
                if cell_key not in clusters:
                    clusters[cell_key] = {
                        'count': 0,
                        'lat_sum': 0,
                        'lon_sum': 0,
                        'points': []
                    }
                
                clusters[cell_key]['count'] += 1
                clusters[cell_key]['lat_sum'] += lat
                clusters[cell_key]['lon_sum'] += lon
                clusters[cell_key]['points'].append(point)
                
            except (TypeError, ValueError) as e:
                print(f"Error processing point: {point}, Error: {str(e)}")
                continue
        
        # Calculate cluster centers and prepare return data
        clustered_data = []
        for cell_key, cluster in clusters.items():
            try:
                center_lat = cluster['lat_sum'] / cluster['count']
                center_lon = cluster['lon_sum'] / cluster['count']
                
                clustered_data.append({
                    'center': {
                        'Latitude': center_lat,
                        'Longitude': center_lon
                    },
                    'count': cluster['count'],
                    'points': cluster['points']
                })
            except ZeroDivisionError:
                print(f"Error calculating center for cluster: {cell_key}")
                continue
        
        return clustered_data
    except Exception as e:
        print(f"Error in cluster_points: {str(e)}")
        return []

@app.route('/getMarkers', methods=['GET'])
def get_markers():
    try:
        # Get and validate parameters
        try:
            min_lat = float(request.args.get('minLat', 0))
            max_lat = float(request.args.get('maxLat', 0))
            min_lon = float(request.args.get('minLon', 0))
            max_lon = float(request.args.get('maxLon', 0))
            zoom_level = int(request.args.get('zoom', 15))
        except (TypeError, ValueError) as e:
            return jsonify({"error": f"Invalid parameters: {str(e)}"}), 400

        # Validate coordinate ranges
        if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90 and
                -180 <= min_lon <= 180 and -180 <= max_lon <= 180):
            return jsonify({"error": "Coordinates out of valid range"}), 400

        with get_db_cursor() as cursor:
            query = """
                SELECT ID, Name, Branch, Latitude, Longitude, Postal, Address
                FROM search_view
                WHERE Latitude BETWEEN %s AND %s
                AND Longitude BETWEEN %s AND %s
            """
            cursor.execute(query, (min_lat, max_lat, min_lon, max_lon))
            points = cursor.fetchall()
            
            if not points:
                return jsonify({"clusters": []})
            
            # Apply clustering
            clustered_points = cluster_points(points, zoom_level)
            return jsonify({"clusters": clustered_points})
            
    except Exception as e:
        print(f"Error in get_markers: {str(e)}")
        return jsonify({"error": "An internal server error occurred"}), 500

if __name__ == '__main__':
    app.run(debug=True)
