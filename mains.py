import mysql.connector
from datetime import datetime

# ── DB CONFIG ────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": "Mark@7201",  # ← change this
    "database": "train_search",
}

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ── DATABASE FUNCTIONS ───────────────────────────────────────

def get_connection():
    conn = mysql.connector.connect(**DB_CONFIG)
    return conn


def get_all_stations():
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT station_code, station_name FROM stations ORDER BY station_code;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def search_trains(from_code, to_code, day_of_week):
    query = """
        SELECT
            t.train_no,
            t.train_name,
            s1.station_name  AS from_station,
            s2.station_name  AS to_station,
            t.departs_at,
            t.arrives_at,
            t.duration_hrs
        FROM   trains t
        JOIN   train_days td  ON td.train_no    = t.train_no
        JOIN   stations   s1  ON s1.station_code = t.source_code
        JOIN   stations   s2  ON s2.station_code = t.dest_code
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

# ── DISPLAY FUNCTIONS ────────────────────────────────────────

def fmt_time(t):
    """Convert timedelta (how MySQL returns TIME) to HH:MM string."""
    total_seconds = int(t.total_seconds())
    h, remainder  = divmod(total_seconds, 3600)
    m             = remainder // 60
    return f"{h:02d}:{m:02d}"


def show_stations(stations):
    print("\n  Available Stations:")
    print("  " + "-" * 35)
    for code, name in stations:
        print(f"  {code:<8}  {name}")
    print()


def show_results(trains, from_code, to_code, date_str, day_name):
    print("\n" + "=" * 62)
    print(f"  Route  : {from_code.upper()}  →  {to_code.upper()}")
    print(f"  Date   : {date_str}  ({day_name})")
    print(f"  Found  : {len(trains)} train(s)")
    print("=" * 62)

    if not trains:
        print("\n  No trains available on this route for the selected date.\n")
        return

    header = f"  {'Train No':<10}  {'Train Name':<25}  {'Departs':>7}  {'Arrives':>7}  {'Duration':>8}"
    print(header)
    print("  " + "-" * 58)

    for t in trains:
        dep = fmt_time(t["departs_at"])
        arr = fmt_time(t["arrives_at"])
        dur = f"{t['duration_hrs']}h"
        print(f"  {t['train_no']:<10}  {t['train_name']:<25}  {dep:>7}  {arr:>7}  {dur:>8}")

    print()

# ── MAIN ─────────────────────────────────────────────────────

def main():
    print("\n" + "=" * 62)
    print("          🚂  IRCTC Train Search  —  CLI")
    print("=" * 62)

    # Show stations
    stations = get_all_stations()
    show_stations(stations)

    # Input: FROM
    from_code = input("  Enter FROM station code : ").strip().upper()

    # Input: TO
    to_code = input("  Enter TO   station code : ").strip().upper()

    # Input: Date
    date_input = input("  Enter Departure Date (DD-MM-YYYY) : ").strip()
    dep_date   = datetime.strptime(date_input, "%d-%m-%Y")

    day_of_week = dep_date.weekday()          # 0=Mon … 6=Sun
    day_name    = DAY_NAMES[day_of_week]
    date_str    = dep_date.strftime("%d %b %Y")

    # Search
    trains = search_trains(from_code, to_code, day_of_week)

    # Display
    show_results(trains, from_code, to_code, date_str, day_name)

    # Search again?
    again = input("  Search again? (y/n) : ").strip().lower()
    if again == "y":
        main()
    else:
        print("\n  Goodbye! 👋\n")


if __name__ == "__main__":
    main()