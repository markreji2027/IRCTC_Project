from flask import Flask, render_template, request, redirect, url_for, session
import mysql.connector
from datetime import datetime
import random
import string

app = Flask(__name__)
app.secret_key = "irctc_admin_secret_123"

# ── DB CONFIG ────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": "Mark@7201", 
    "database": "train_search",
}

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

CLASS_RATES = {
    "General": 0.30,
    "2S":      0.45,
    "Sleeper": 0.60,
    "3AC":     1.35,
    "2AC":     2.50,
    "1AC":     4.00,
}

TRAIN_TYPE_RATES = {
    "Express":      0.80,
    "Superfast":    0.90,
    "Duronto":      2.40,
    "Rajdhani":     2.75,
    "Shatabdi":     2.30,
    "Gatiman":      2.80,
    "Vande Bharat": 2.65,
}

# ── DB FUNCTIONS ─────────────────────────────────────────────

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def get_all_stations():
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT station_code, station_name FROM stations ORDER BY station_name;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def search_trains(from_code, to_code, day_of_week):
    query = """
        SELECT t.train_no, t.train_name, t.train_type,
               s1.station_name AS from_station,
               s2.station_name AS to_station,
               t.departs_at, t.arrives_at
        FROM   trains t
        JOIN   train_days td ON td.train_no     = t.train_no
        JOIN   stations   s1 ON s1.station_code  = t.source_code
        JOIN   stations   s2 ON s2.station_code  = t.dest_code
        WHERE  UPPER(t.source_code) = UPPER(%s)
          AND  UPPER(t.dest_code)   = UPPER(%s)
          AND  td.day_of_week       = %s
        ORDER  BY t.departs_at;
    """
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, (from_code, to_code, day_of_week))
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results

def get_distance(from_code, to_code):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT distance_km FROM route_distances WHERE source_code=%s AND dest_code=%s",
        (from_code, to_code)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else None

def get_train(train_no):
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT t.train_no, t.train_name, t.train_type,
               s1.station_name AS from_station,
               s2.station_name AS to_station,
               t.departs_at, t.arrives_at
        FROM trains t
        JOIN stations s1 ON s1.station_code = t.source_code
        JOIN stations s2 ON s2.station_code = t.dest_code
        WHERE t.train_no = %s
    """, (train_no,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row

def get_seat_availability(train_no):
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT class, available_seats FROM seats WHERE train_no = %s",
        (train_no,)
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return {row["class"]: row["available_seats"] for row in rows}

def assign_seat(train_no, cls):
    """Assign next available seat number and reduce count by 1."""
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT available_seats, total_coaches, seats_per_coach FROM seats WHERE train_no=%s AND class=%s",
        (train_no, cls)
    )
    row = cursor.fetchone()
    if not row or row["available_seats"] <= 0:
        cursor.close()
        conn.close()
        return None, None

    available = row["available_seats"]
    if cls == "General":
        seat_no = "GEN-" + str(random.randint(1, 999))
    else:
        seats_per_coach = row["seats_per_coach"]
        total_coaches   = row["total_coaches"]
        total_seats     = seats_per_coach * total_coaches
        seat_taken      = total_seats - available
        coach_num       = (seat_taken // seats_per_coach) + 1
        seat_in_coach   = (seat_taken % seats_per_coach) + 1
        prefix = {"2S": "S", "Sleeper": "SL", "3AC": "B", "2AC": "A", "1AC": "H"}.get(cls, "X")
        seat_no = f"{prefix}{coach_num}-{seat_in_coach}"

    cursor.execute(
        "UPDATE seats SET available_seats = available_seats - 1 WHERE train_no=%s AND class=%s",
        (train_no, cls)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return seat_no, available - 1

def create_booking(train_no, from_code, to_code, travel_date, cls, passengers, total_fare):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO bookings (train_no, from_code, to_code, travel_date, class, total_passengers, total_fare)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (train_no, from_code, to_code, travel_date, cls, len(passengers), total_fare))
    booking_id = cursor.lastrowid

    for p in passengers:
        seat_no, _ = assign_seat(train_no, cls)
        cursor.execute("""
            INSERT INTO passengers (booking_id, first_name, last_name, age, gender, seat_number)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (booking_id, p["first_name"], p["last_name"], p["age"], p["gender"], seat_no))

    conn.commit()
    cursor.close()
    conn.close()
    return booking_id

def get_booking(booking_id):
    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT b.*, t.train_name, t.train_type,
               s1.station_name AS from_station,
               s2.station_name AS to_station,
               t.departs_at, t.arrives_at,
               rd.distance_km
        FROM bookings b
        JOIN trains t     ON t.train_no      = b.train_no
        JOIN stations s1  ON s1.station_code  = b.from_code
        JOIN stations s2  ON s2.station_code  = b.to_code
        JOIN route_distances rd ON rd.source_code = b.from_code AND rd.dest_code = b.to_code
        WHERE b.booking_id = %s
    """, (booking_id,))
    booking = cursor.fetchone()

    cursor.execute(
        "SELECT * FROM passengers WHERE booking_id = %s", (booking_id,)
    )
    booking["passengers"] = cursor.fetchall()
    cursor.close()
    conn.close()
    return booking

def fmt_time(t):
    total_seconds = int(t.total_seconds())
    h, remainder  = divmod(total_seconds, 3600)
    m             = remainder // 60
    return f"{h:02d}:{m:02d}"

# ── ROUTES ───────────────────────────────────────────────────

@app.route("/")
def index():
    stations = get_all_stations()
    return render_template("index.html", stations=stations)

@app.route("/search", methods=["POST"])
def search():
    from_code  = request.form.get("from_code").strip().upper()
    to_code    = request.form.get("to_code").strip().upper()
    date_input = request.form.get("departure_date")

    if from_code == to_code:
        stations = get_all_stations()
        return render_template("index.html", stations=stations,
                               error="From and To stations cannot be the same.")

    dep_date    = datetime.strptime(date_input, "%Y-%m-%d")
    day_of_week = dep_date.weekday()
    day_name    = DAY_NAMES[day_of_week]
    date_str    = dep_date.strftime("%d %b %Y")

    trains = search_trains(from_code, to_code, day_of_week)
    for t in trains:
        t["departs_at"] = fmt_time(t["departs_at"])
        t["arrives_at"] = fmt_time(t["arrives_at"])
        t["seats"]      = get_seat_availability(t["train_no"])

    return render_template("results.html",
                           trains=trains,
                           from_code=from_code,
                           to_code=to_code,
                           date_str=date_str,
                           day_name=day_name,
                           travel_date=date_input)

@app.route("/fare")
def fare():
    train_no       = request.args.get("train_no")
    from_code      = request.args.get("from_code")
    to_code        = request.args.get("to_code")
    selected_class = request.args.get("class")
    travel_date    = request.args.get("travel_date")

    train    = get_train(train_no)
    distance = get_distance(from_code, to_code)
    seats    = get_seat_availability(train_no)

    train["departs_at"] = fmt_time(train["departs_at"])
    train["arrives_at"] = fmt_time(train["arrives_at"])

    fare_amount = None
    if selected_class and distance:
        type_rate   = TRAIN_TYPE_RATES.get(train["train_type"], TRAIN_TYPE_RATES["Express"])
        class_rate  = CLASS_RATES.get(selected_class, CLASS_RATES["General"])
        fare_amount = round(distance * type_rate * class_rate, 2)

    return render_template("fare.html",
                           train=train,
                           from_code=from_code,
                           to_code=to_code,
                           distance=distance,
                           classes=CLASS_RATES.keys(),
                           selected_class=selected_class,
                           fare_amount=fare_amount,
                           seats=seats,
                           travel_date=travel_date)

@app.route("/booking", methods=["GET", "POST"])
def booking():
    if request.method == "GET":
        train_no    = request.args.get("train_no")
        from_code   = request.args.get("from_code")
        to_code     = request.args.get("to_code")
        cls         = request.args.get("class")
        travel_date = request.args.get("travel_date")
        fare_amount = float(request.args.get("fare"))

        train    = get_train(train_no)
        distance = get_distance(from_code, to_code)
        train["departs_at"] = fmt_time(train["departs_at"])
        train["arrives_at"] = fmt_time(train["arrives_at"])

        return render_template("booking.html",
                               train=train,
                               from_code=from_code,
                               to_code=to_code,
                               cls=cls,
                               travel_date=travel_date,
                               fare_amount=fare_amount,
                               distance=distance)

    if request.method == "POST":
        train_no    = request.form.get("train_no")
        from_code   = request.form.get("from_code")
        to_code     = request.form.get("to_code")
        cls         = request.form.get("class")
        travel_date = request.form.get("travel_date")
        fare_amount = float(request.form.get("fare_amount"))

        first_names = request.form.getlist("first_name")
        last_names  = request.form.getlist("last_name")
        ages        = request.form.getlist("age")
        genders     = request.form.getlist("gender")

        passengers = []
        for i in range(len(first_names)):
            passengers.append({
                "first_name": first_names[i],
                "last_name":  last_names[i],
                "age":        ages[i],
                "gender":     genders[i]
            })

        total_fare  = round(fare_amount * len(passengers), 2)
        booking_id  = create_booking(train_no, from_code, to_code,
                                     travel_date, cls, passengers, total_fare)

        return redirect(url_for("ticket", booking_id=booking_id))

@app.route("/ticket/<int:booking_id>")
def ticket(booking_id):
    booking = get_booking(booking_id)
    booking["departs_at"] = fmt_time(booking["departs_at"])
    booking["arrives_at"] = fmt_time(booking["arrives_at"])
    return render_template("ticket.html", booking=booking)

@app.route("/dashboard")
def dashboard():

    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)

    # ── SUMMARY CARDS ────────────────────────────────────────
    cursor.execute("SELECT COUNT(*) AS total_bookings FROM bookings")
    total_bookings = cursor.fetchone()["total_bookings"]

    cursor.execute("SELECT COALESCE(SUM(total_fare), 0) AS total_revenue FROM bookings")
    total_revenue = float(cursor.fetchone()["total_revenue"])

    cursor.execute("SELECT COALESCE(SUM(total_passengers), 0) AS total_passengers FROM bookings")
    total_passengers = cursor.fetchone()["total_passengers"]

    cursor.execute("SELECT COUNT(*) AS total_trains FROM trains")
    total_trains = cursor.fetchone()["total_trains"]

    # ── REVENUE OVER TIME ────────────────────────────────────
    cursor.execute("""
        SELECT DATE(booked_at) AS date,
               SUM(total_fare) AS revenue
        FROM bookings
        GROUP BY DATE(booked_at)
        ORDER BY DATE(booked_at)
    """)
    revenue_over_time = cursor.fetchall()
    revenue_dates    = [str(r["date"]) for r in revenue_over_time]
    revenue_values   = [float(r["revenue"]) for r in revenue_over_time]

    # ── BOOKINGS BY CLASS ────────────────────────────────────
    cursor.execute("""
        SELECT class,
               COUNT(*)            AS bookings,
               SUM(total_fare)     AS revenue,
               SUM(total_passengers) AS passengers
        FROM bookings
        GROUP BY class
        ORDER BY bookings DESC
    """)
    class_stats = cursor.fetchall()
    class_labels  = [r["class"] for r in class_stats]
    class_bookings = [int(r["bookings"]) for r in class_stats]

    # ── SEATS BOOKED VS AVAILABLE ────────────────────────────
    cursor.execute("""
        SELECT SUM(total_seats - available_seats) AS booked,
               SUM(available_seats)               AS available
        FROM seats
        WHERE class != 'General'
    """)
    seat_row      = cursor.fetchone()
    seats_booked  = int(seat_row["booked"]    or 0)
    seats_avail   = int(seat_row["available"] or 0)

    # ── PER TRAIN STATS ──────────────────────────────────────
    cursor.execute("""
        SELECT b.train_no,
               t.train_name,
               t.train_type,
               COUNT(b.booking_id)        AS total_bookings,
               SUM(b.total_passengers)    AS total_passengers,
               COALESCE(SUM(b.total_fare), 0) AS total_revenue
        FROM bookings b
        JOIN trains t ON t.train_no = b.train_no
        GROUP BY b.train_no, t.train_name, t.train_type
        ORDER BY total_revenue DESC
    """)
    train_stats = cursor.fetchall()
    for t in train_stats:
        t["total_revenue"] = float(t["total_revenue"])

    # ── BUSIEST ROUTES ───────────────────────────────────────
    cursor.execute("""
        SELECT b.from_code, b.to_code,
               s1.station_name AS from_station,
               s2.station_name AS to_station,
               COUNT(b.booking_id)            AS total_bookings,
               SUM(b.total_passengers)         AS total_passengers,
               COALESCE(SUM(b.total_fare), 0)  AS total_revenue
        FROM bookings b
        JOIN stations s1 ON s1.station_code = b.from_code
        JOIN stations s2 ON s2.station_code = b.to_code
        GROUP BY b.from_code, b.to_code, s1.station_name, s2.station_name
        ORDER BY total_bookings DESC
    """)
    route_stats = cursor.fetchall()
    for r in route_stats:
        r["total_revenue"] = float(r["total_revenue"])

    cursor.close()
    conn.close()

    return render_template("dashboard.html",
                           total_bookings=total_bookings,
                           total_revenue=total_revenue,
                           total_passengers=total_passengers,
                           total_trains=total_trains,
                           revenue_dates=revenue_dates,
                           revenue_values=revenue_values,
                           class_labels=class_labels,
                           class_bookings=class_bookings,
                           seats_booked=seats_booked,
                           seats_avail=seats_avail,
                           train_stats=train_stats,
                           route_stats=route_stats,
                           class_stats=class_stats)

# ── ADMIN CREDENTIALS ────────────────────────────────────────
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "rajdhani123"   # ← change to whatever you want

# ── ADMIN HELPER ─────────────────────────────────────────────
def admin_required():
    return session.get("admin_logged_in")

# ── ADMIN ROUTES ─────────────────────────────────────────────

@app.route("/admin")
def admin_index():
    if not admin_required():
        return redirect(url_for("admin_login"))
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if admin_required():
        return redirect(url_for("admin_dashboard"))
    error = None
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            error = "Invalid username or password."
    return render_template("admin/login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
def admin_dashboard():
    if not admin_required():
        return redirect(url_for("admin_login"))

    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS v FROM bookings")
    total_bookings = cursor.fetchone()["v"]

    cursor.execute("SELECT COALESCE(SUM(total_fare),0) AS v FROM bookings")
    total_revenue = float(cursor.fetchone()["v"])

    cursor.execute("SELECT COALESCE(SUM(total_passengers),0) AS v FROM bookings")
    total_passengers = cursor.fetchone()["v"]

    cursor.execute("SELECT COUNT(*) AS v FROM trains")
    total_trains = cursor.fetchone()["v"]

    cursor.execute("""
        SELECT DATE(booked_at) AS date, SUM(total_fare) AS revenue
        FROM bookings GROUP BY DATE(booked_at) ORDER BY DATE(booked_at)
    """)
    rot = cursor.fetchall()
    revenue_dates  = [str(r["date"]) for r in rot]
    revenue_values = [float(r["revenue"]) for r in rot]

    cursor.execute("""
        SELECT class, COUNT(*) AS bookings,
               SUM(total_fare) AS revenue,
               SUM(total_passengers) AS passengers
        FROM bookings GROUP BY class ORDER BY bookings DESC
    """)
    class_stats   = cursor.fetchall()
    class_labels  = [r["class"]    for r in class_stats]
    class_bookings= [int(r["bookings"]) for r in class_stats]

    cursor.execute("""
        SELECT SUM(total_seats - available_seats) AS booked,
               SUM(available_seats) AS available
        FROM seats WHERE class != 'General'
    """)
    sr = cursor.fetchone()
    seats_booked = int(sr["booked"]    or 0)
    seats_avail  = int(sr["available"] or 0)

    cursor.execute("""
        SELECT b.train_no, t.train_name, t.train_type,
               COUNT(b.booking_id) AS total_bookings,
               SUM(b.total_passengers) AS total_passengers,
               COALESCE(SUM(b.total_fare),0) AS total_revenue
        FROM bookings b JOIN trains t ON t.train_no = b.train_no
        GROUP BY b.train_no, t.train_name, t.train_type
        ORDER BY total_revenue DESC
    """)
    train_stats = cursor.fetchall()
    for t in train_stats:
        t["total_revenue"] = float(t["total_revenue"])

    cursor.execute("""
        SELECT b.from_code, b.to_code,
               s1.station_name AS from_station,
               s2.station_name AS to_station,
               COUNT(b.booking_id) AS total_bookings,
               SUM(b.total_passengers) AS total_passengers,
               COALESCE(SUM(b.total_fare),0) AS total_revenue
        FROM bookings b
        JOIN stations s1 ON s1.station_code = b.from_code
        JOIN stations s2 ON s2.station_code = b.to_code
        GROUP BY b.from_code, b.to_code, s1.station_name, s2.station_name
        ORDER BY total_bookings DESC
    """)
    route_stats = cursor.fetchall()
    for r in route_stats:
        r["total_revenue"] = float(r["total_revenue"])

    cursor.close()
    conn.close()

    return render_template("admin/dashboard.html",
                           active="dashboard",
                           total_bookings=total_bookings,
                           total_revenue=total_revenue,
                           total_passengers=total_passengers,
                           total_trains=total_trains,
                           revenue_dates=revenue_dates,
                           revenue_values=revenue_values,
                           class_labels=class_labels,
                           class_bookings=class_bookings,
                           seats_booked=seats_booked,
                           seats_avail=seats_avail,
                           train_stats=train_stats,
                           class_stats=class_stats)


@app.route("/admin/bookings")
def admin_bookings():
    if not admin_required():
        return redirect(url_for("admin_login"))

    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT b.*, t.train_name,
               s1.station_name AS from_station,
               s2.station_name AS to_station
        FROM bookings b
        JOIN trains t    ON t.train_no      = b.train_no
        JOIN stations s1 ON s1.station_code  = b.from_code
        JOIN stations s2 ON s2.station_code  = b.to_code
        ORDER BY b.booked_at DESC
    """)
    bookings = cursor.fetchall()

    for b in bookings:
        cursor.execute(
            "SELECT * FROM passengers WHERE booking_id = %s", (b["booking_id"],)
        )
        b["passengers"] = cursor.fetchall()

    cursor.execute("SELECT COALESCE(SUM(total_fare),0) AS v FROM bookings")
    total_revenue = float(cursor.fetchone()["v"])

    cursor.execute("SELECT COALESCE(SUM(total_passengers),0) AS v FROM bookings")
    total_passengers = cursor.fetchone()["v"]

    cursor.execute("SELECT COALESCE(AVG(total_fare),0) AS v FROM bookings")
    avg_fare = float(cursor.fetchone()["v"])

    cursor.close()
    conn.close()

    return render_template("admin/bookings.html",
                           active="bookings",
                           bookings=bookings,
                           total_revenue=total_revenue,
                           total_passengers=total_passengers,
                           avg_fare=avg_fare)


@app.route("/admin/trains")
def admin_trains():
    if not admin_required():
        return redirect(url_for("admin_login"))

    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT t.train_no, t.train_name, t.train_type,
               t.source_code, t.dest_code,
               COALESCE(b.total_bookings, 0) AS total_bookings,
               COALESCE(b.total_revenue,  0) AS total_revenue
        FROM trains t
        LEFT JOIN (
            SELECT train_no,
                   COUNT(*)        AS total_bookings,
                   SUM(total_fare) AS total_revenue
            FROM bookings GROUP BY train_no
        ) b ON b.train_no = t.train_no
        ORDER BY total_revenue DESC
    """)
    trains = cursor.fetchall()
    for t in trains:
        t["total_revenue"] = float(t["total_revenue"])
        t["seats"] = get_seat_availability(t["train_no"])

    cursor.execute("""
        SELECT SUM(total_seats - available_seats) AS booked,
               SUM(total_seats) AS total
        FROM seats WHERE class != 'General'
    """)
    sr = cursor.fetchone()
    seats_booked = int(sr["booked"] or 0)
    total_seats  = int(sr["total"]  or 0)

    cursor.execute("""
        SELECT COUNT(DISTINCT train_no) AS v FROM bookings
    """)
    booked_trains = cursor.fetchone()["v"]

    cursor.close()
    conn.close()

    return render_template("admin/trains.html",
                           active="trains",
                           trains=trains,
                           seats_booked=seats_booked,
                           total_seats=total_seats,
                           booked_trains=booked_trains)


@app.route("/admin/routes")
def admin_routes():
    if not admin_required():
        return redirect(url_for("admin_login"))

    conn   = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT rd.source_code AS from_code, rd.dest_code AS to_code,
               s1.station_name AS from_station,
               s2.station_name AS to_station,
               rd.distance_km,
               COUNT(DISTINCT t.train_no) AS train_count,
               COALESCE(bk.total_bookings,  0) AS total_bookings,
               COALESCE(bk.total_passengers,0) AS total_passengers,
               COALESCE(bk.total_revenue,   0) AS total_revenue
        FROM route_distances rd
        JOIN stations s1 ON s1.station_code = rd.source_code
        JOIN stations s2 ON s2.station_code = rd.dest_code
        LEFT JOIN trains t ON t.source_code = rd.source_code
                           AND t.dest_code  = rd.dest_code
        LEFT JOIN (
            SELECT from_code, to_code,
                   COUNT(*)               AS total_bookings,
                   SUM(total_passengers)  AS total_passengers,
                   SUM(total_fare)        AS total_revenue
            FROM bookings GROUP BY from_code, to_code
        ) bk ON bk.from_code = rd.source_code
             AND bk.to_code   = rd.dest_code
        GROUP BY rd.source_code, rd.dest_code,
                 s1.station_name, s2.station_name, rd.distance_km,
                 bk.total_bookings, bk.total_passengers, bk.total_revenue
        ORDER BY total_bookings DESC
    """)
    routes = cursor.fetchall()
    for r in routes:
        r["total_revenue"] = float(r["total_revenue"])

    cursor.execute("SELECT AVG(distance_km) AS v FROM route_distances")
    avg_distance = round(float(cursor.fetchone()["v"] or 0))

    top_revenue_route = max(routes, key=lambda r: r["total_revenue"]) if routes else None

    route_labels = [f"{r['from_code']}→{r['to_code']}" for r in routes if r["total_bookings"] > 0]
    route_data   = [int(r["total_bookings"]) for r in routes if r["total_bookings"] > 0]

    cursor.close()
    conn.close()

    return render_template("admin/routes.html",
                           active="routes",
                           routes=routes,
                           avg_distance=avg_distance,
                           top_revenue_route=top_revenue_route,
                           route_labels=route_labels,
                           route_data=route_data)

if __name__ == "__main__":
    app.run(debug=True)