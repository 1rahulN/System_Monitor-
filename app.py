from flask import Flask, render_template, request, jsonify, redirect, session
import time
from datetime import datetime
import json
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'system_monitor_secret_2024')

# -----------------------------
# DATABASE SETUP (for Render)
# -----------------------------
# Try to use PostgreSQL if DATABASE_URL exists, otherwise use SQLite
try:
    import psycopg2 # type: ignore
    from urllib.parse import urlparse
    
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if DATABASE_URL:
        USE_POSTGRES = True
        print("Using PostgreSQL database")
    else:
        USE_POSTGRES = False
        print("Using SQLite database")
except ImportError:
    USE_POSTGRES = False
    print("psycopg2 not installed, using SQLite database")

def get_db_connection():
    """Get database connection based on environment"""
    if USE_POSTGRES and DATABASE_URL:
        result = urlparse(DATABASE_URL)
        conn = psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
    else:
        import sqlite3
        conn = sqlite3.connect('workstations.db')
        conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    if USE_POSTGRES:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS workstations (
                client VARCHAR(50),
                system VARCHAR(100),
                data JSONB,
                last_seen DOUBLE PRECISION,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (client, system)
            )
        ''')
    else:
        cur.execute('''
            CREATE TABLE IF NOT EXISTS workstations (
                client TEXT,
                system TEXT,
                data TEXT,
                last_seen REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (client, system)
            )
        ''')
    
    conn.commit()
    cur.close()
    conn.close()

def save_workstation_data(client, system, data):
    """Save workstation data to database"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    data_json = json.dumps(data)
    last_seen = data.get('last_seen', time.time())
    
    if USE_POSTGRES:
        cur.execute('''
            INSERT INTO workstations (client, system, data, last_seen)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (client, system) 
            DO UPDATE SET data = EXCLUDED.data, last_seen = EXCLUDED.last_seen, updated_at = CURRENT_TIMESTAMP
        ''', (client, system, data_json, last_seen))
    else:
        cur.execute('''
            INSERT OR REPLACE INTO workstations (client, system, data, last_seen)
            VALUES (?, ?, ?, ?)
        ''', (client, system, data_json, last_seen))
    
    conn.commit()
    cur.close()
    conn.close()

def load_all_workstations():
    """Load all workstation data from database"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    if USE_POSTGRES:
        cur.execute('SELECT client, system, data FROM workstations')
    else:
        cur.execute('SELECT client, system, data FROM workstations')
    
    rows = cur.fetchall()
    
    result = {"arena": {}, "test1": {}, "test2": {}}
    for row in rows:
        client = row[0]
        system = row[1]
        data_json = row[2]
        
        if client not in result:
            result[client] = {}
        
        try:
            result[client][system] = json.loads(data_json)
        except:
            result[client][system] = {}
    
    cur.close()
    conn.close()
    return result

# Initialize database
init_db()

# -----------------------------
# CLIENT USERS
# -----------------------------
users = {
    "arena": {
        "password": "1234",
        "title": "Arena System Monitor Dashboard"
    },
    "test1": {
        "password": "123",
        "title": "Lab System Monitor Dashboard"
    },
    "test2": {
        "password": "test123",
        "title": "Office System Monitor Dashboard"
    }
}

# Load initial data
workstations_data = load_all_workstations()

# -----------------------------
# LOGIN
# -----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username in users and users[username]["password"] == password:
            session["user"] = username
            return redirect("/")

    return render_template("login.html")

# -----------------------------
# LOGOUT
# -----------------------------
@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/login")

# -----------------------------
# RECEIVE DATA FROM POWERSHELL
# -----------------------------
@app.route("/update", methods=["POST"])
def update_workstation():
    try:
        data = request.get_json()
        
        if not data:
            print("No JSON data received")
            return jsonify({"error": "No data received"}), 400

        client = data.get("client")
        ws_name = data.get("system")

        if not client or not ws_name:
            print(f"Missing client or system: client={client}, system={ws_name}")
            return jsonify({"error": "Missing client or system"}), 400

        print(f"\n=== Received data from {client}/{ws_name} at {datetime.now()} ===")
        
        # Get data with defaults
        active_apps = data.get("active_apps", [])
        idle_apps = data.get("idle_apps", [])
        cpu = data.get("cpu", 0)
        ram = data.get("ram", 0)
        disk = data.get("disk", [])
        top_processes = data.get("topProcesses", [])
        
        print(f"CPU: {cpu}%, RAM: {ram}%, Active Apps: {len(active_apps)}, Idle Apps: {len(idle_apps)}")
        
        # Validate and clean disk data
        validated_disk = []
        if isinstance(disk, list):
            for disk_item in disk:
                if isinstance(disk_item, dict):
                    try:
                        clean_disk = {
                            "Drive": str(disk_item.get("Drive", "Unknown")),
                            "UsedPercent": float(disk_item.get("UsedPercent", 0)),
                            "TotalSize": float(disk_item.get("TotalSize", 0)),
                            "FreeSpace": float(disk_item.get("FreeSpace", 0)),
                            "UsedSpace": float(disk_item.get("UsedSpace", 0))
                        }
                        validated_disk.append(clean_disk)
                    except (ValueError, TypeError) as e:
                        print(f"Error processing disk: {e}")
                        continue
        
        # Validate top processes
        validated_processes = []
        if isinstance(top_processes, list):
            for proc in top_processes:
                if isinstance(proc, dict):
                    try:
                        validated_processes.append({
                            "Name": str(proc.get("Name", "Unknown")),
                            "CPU": float(proc.get("CPU", 0))
                        })
                    except (ValueError, TypeError):
                        continue
        
        # Validate and format idle apps
        validated_idle_apps = []
        if isinstance(idle_apps, list):
            for app in idle_apps:
                if isinstance(app, dict):
                    validated_idle_apps.append({
                        "name": str(app.get("name", "Unknown")),
                        "idle_time": float(app.get("idle_time", 0))
                    })
                elif isinstance(app, str):
                    validated_idle_apps.append({
                        "name": app,
                        "idle_time": 0
                    })
        
        # Validate active apps
        validated_active_apps = []
        if isinstance(active_apps, list):
            for app in active_apps:
                if app and isinstance(app, str):
                    validated_active_apps.append(app)
        
        # Prepare data to save
        workstation_data = {
            "active_apps": validated_active_apps,
            "idle_apps": validated_idle_apps,
            "cpu": float(cpu) if cpu else 0,
            "ram": float(ram) if ram else 0,
            "disk": validated_disk,
            "topProcesses": validated_processes,
            "last_seen": time.time()
        }
        
        # Save to database
        save_workstation_data(client, ws_name, workstation_data)
        
        # Update in-memory cache
        if client not in workstations_data:
            workstations_data[client] = {}
        workstations_data[client][ws_name] = workstation_data
        
        print(f"✓ Updated {ws_name} - Disk: {len(validated_disk)} drives, Processes: {len(validated_processes)}")
        
        return jsonify({
            "message": "Data updated successfully",
            "disks_received": len(validated_disk),
            "processes_received": len(validated_processes)
        }), 200
        
    except Exception as e:
        print(f"ERROR in update_workstation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# -----------------------------
# DASHBOARD (HOME WITH PAGINATION)
# -----------------------------
@app.route("/")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    username = session["user"]
    title = users[username]["title"]

    systems = workstations_data.get(username, {})

    all_data = []
    total_systems = len(systems)
    online_count = 0
    offline_count = 0

    current_time = time.time()

    for ws_name, info in systems.items():
        last_seen = info.get("last_seen", 0)

        if last_seen == 0:
            status = "Offline"
            color = "red"
            offline_count += 1
            last_seen_text = "Never"
        elif current_time - last_seen > 120:
            status = "Offline"
            color = "red"
            offline_count += 1
            last_seen_text = datetime.fromtimestamp(last_seen).strftime("%H:%M:%S")
        else:
            status = "Online"
            color = "green"
            online_count += 1
            last_seen_text = datetime.fromtimestamp(last_seen).strftime("%H:%M:%S")

        # Process idle apps with proper formatting
        idle_apps = info.get("idle_apps", [])
        formatted_idle_apps = []
        
        for app in idle_apps:
            if isinstance(app, dict):
                formatted_idle_apps.append({
                    "name": app.get("name", "Unknown"),
                    "idle_time": float(app.get("idle_time", 0))
                })
            elif isinstance(app, str):
                formatted_idle_apps.append({
                    "name": app,
                    "idle_time": 0
                })
        
        # Process active apps
        active_apps = info.get("active_apps", [])
        if not isinstance(active_apps, list):
            active_apps = []
        
        # Filter out None values and duplicates
        seen = set()
        unique_active_apps = []
        for app in active_apps:
            if app and app not in seen:
                seen.add(app)
                unique_active_apps.append(app)

        all_data.append({
            "name": ws_name,
            "active_apps": unique_active_apps[:5],  # Limit to 5 active apps
            "idle_apps": formatted_idle_apps[:5],   # Limit to 5 idle apps
            "status": status,
            "color": color,
            "last_seen": last_seen_text
        })

    # Sort by name
    all_data.sort(key=lambda x: x["name"])
    
    # Pagination
    page = int(request.args.get("page", 1))
    per_page = 10

    start = (page - 1) * per_page
    end = start + per_page

    paginated_data = all_data[start:end]
    has_next = end < len(all_data)

    return render_template(
        "index.j2",
        workstations=paginated_data,
        title=title,
        page=page,
        has_next=has_next,
        total_systems=total_systems,
        online_count=online_count,
        offline_count=offline_count
    )

# -----------------------------
# WORKSTATIONS PAGE
# -----------------------------
@app.route("/workstations")
def workstations():
    if "user" not in session:
        return redirect("/login")

    username = session["user"]
    title = users[username]["title"]

    systems = workstations_data.get(username, {})

    display_data = []
    current_time = time.time()

    for ws_name, info in systems.items():
        last_seen = info.get("last_seen", 0)

        if last_seen == 0 or current_time - last_seen > 120:
            status = "Offline"
            color = "red"
        else:
            status = "Online"
            color = "green"

        # Get disk data
        disk_data = info.get("disk", [])
        if not isinstance(disk_data, list):
            disk_data = []
        
        # Validate disk entries
        validated_disks = []
        for disk in disk_data:
            if isinstance(disk, dict):
                try:
                    validated_disks.append({
                        "Drive": disk.get("Drive", "Unknown"),
                        "UsedPercent": float(disk.get("UsedPercent", 0)),
                        "TotalSize": float(disk.get("TotalSize", 0)),
                        "FreeSpace": float(disk.get("FreeSpace", 0)),
                        "UsedSpace": float(disk.get("UsedSpace", 0))
                    })
                except (ValueError, TypeError):
                    continue
        
        # Get top processes
        top_processes = info.get("topProcesses", [])
        if not isinstance(top_processes, list):
            top_processes = []
        
        validated_processes = []
        for proc in top_processes:
            if isinstance(proc, dict):
                try:
                    validated_processes.append({
                        "Name": proc.get("Name", "Unknown"),
                        "CPU": float(proc.get("CPU", 0))
                    })
                except (ValueError, TypeError):
                    continue
        
        # Sort processes by CPU usage
        validated_processes.sort(key=lambda x: x["CPU"], reverse=True)

        display_data.append({
            "name": ws_name,
            "ram": float(info.get("ram", 0)),
            "cpu": float(info.get("cpu", 0)),
            "disk": validated_disks,
            "topProcesses": validated_processes[:10],  # Show top 10 processes
            "status": status,
            "color": color
        })
    
    # Sort by name
    display_data.sort(key=lambda x: x["name"])

    return render_template(
        "workstations.j2",
        workstations=display_data,
        title=title
    )

# -----------------------------
# DEBUG ROUTE TO VIEW RAW DATA
# -----------------------------
@app.route("/debug")
def debug():
    if "user" not in session:
        return redirect("/login")
    return jsonify(workstations_data)

# -----------------------------
# HEALTH CHECK (for Render)
# -----------------------------
@app.route("/health")
def health():
    return jsonify({"status": "healthy", "timestamp": time.time()})

# -----------------------------
# RUN SERVER
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)