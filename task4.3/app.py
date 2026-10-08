"""
StayEasy - a small hotel booking web app (inspired by Booking.com)
SWE40006 Task 4.3 - Aung Si Hein

Features:
  - Search hotels by city, dates and number of guests
  - View a hotel's details and its room types
  - Real availability check (a room type can't be overbooked for overlapping dates)
  - Book a room, get a booking reference
  - Look up "My bookings" by email and cancel a booking
Data is stored in SQLite at DB_PATH (default /data/stayeasy.db, a Docker volume).
"""
import os
import random
import socket
import platform
import sqlite3
import string
from datetime import date, datetime, timedelta

from flask import Flask, g, redirect, render_template, request, url_for, flash

DB_PATH = os.environ.get("DB_PATH", "/data/stayeasy.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")  # needed for flash() messages


# ---------------------------------------------------------------- database ---

def get_db():
    """One SQLite connection per request, closed automatically afterwards."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS hotels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    city        TEXT NOT NULL,
    area        TEXT NOT NULL,
    stars       INTEGER NOT NULL,
    rating      REAL NOT NULL,
    description TEXT NOT NULL,
    amenities   TEXT NOT NULL,          -- comma-separated
    color       TEXT NOT NULL           -- used for the card banner
);
CREATE TABLE IF NOT EXISTS rooms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_id    INTEGER NOT NULL REFERENCES hotels(id),
    name        TEXT NOT NULL,
    capacity    INTEGER NOT NULL,       -- max guests
    price       REAL NOT NULL,          -- per night, MYR
    quantity    INTEGER NOT NULL        -- how many rooms of this type exist
);
CREATE TABLE IF NOT EXISTS bookings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reference   TEXT NOT NULL UNIQUE,
    room_id     INTEGER NOT NULL REFERENCES rooms(id),
    guest_name  TEXT NOT NULL,
    email       TEXT NOT NULL,
    check_in    TEXT NOT NULL,          -- YYYY-MM-DD
    check_out   TEXT NOT NULL,
    guests      INTEGER NOT NULL,
    total       REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'confirmed',
    created_at  TEXT NOT NULL
);
"""

SEED_HOTELS = [
    # name, city, area, stars, rating, description, amenities, color
    ("Petronas View Suites", "Kuala Lumpur", "KLCC", 5, 9.1,
     "Modern suites with floor-to-ceiling windows facing the Twin Towers, a short walk from KLCC Park.",
     "Free WiFi,Infinity pool,Gym,Airport shuttle,Breakfast", "#1e3a8a"),
    ("Bukit Bintang Boutique", "Kuala Lumpur", "Bukit Bintang", 4, 8.6,
     "Stylish boutique hotel in the heart of KL's shopping and food district.",
     "Free WiFi,Rooftop bar,24h reception", "#9d174d"),
    ("Chinatown Backpacker Inn", "Kuala Lumpur", "Petaling Street", 2, 7.9,
     "Friendly budget stay steps away from Petaling Street market and the LRT.",
     "Free WiFi,Shared kitchen,Lockers", "#b45309"),
    ("George Town Heritage House", "Penang", "George Town", 4, 9.3,
     "Restored 1920s shophouse in the UNESCO heritage zone, close to the street art trail.",
     "Free WiFi,Breakfast,Bicycle rental", "#047857"),
    ("Batu Ferringhi Beach Resort", "Penang", "Batu Ferringhi", 5, 8.8,
     "Beachfront resort with sea-view rooms and a large lagoon pool.",
     "Free WiFi,Beach access,Pool,Spa,Kids club", "#0e7490"),
    ("Langkawi Rainforest Lodge", "Langkawi", "Pantai Cenang", 4, 9.0,
     "Chalets surrounded by rainforest, ten minutes from Cenang beach.",
     "Free WiFi,Pool,Breakfast,Free parking", "#166534"),
    ("Old Town Bangkok Hotel", "Bangkok", "Rattanakosin", 3, 8.4,
     "Comfortable rooms near the Grand Palace and Khao San Road.",
     "Free WiFi,Rooftop terrace,Tour desk", "#7c2d12"),
    ("Sukhumvit Sky Residence", "Bangkok", "Sukhumvit", 5, 9.2,
     "High-rise residence with skyline views, connected to the BTS Skytrain.",
     "Free WiFi,Sky pool,Gym,Spa,Breakfast", "#4c1d95"),
]

SEED_ROOMS = [
    # (room name, capacity, price multiplier, quantity)
    ("Standard Double", 2, 1.0, 3),
    ("Deluxe King", 2, 1.4, 2),
    ("Family Room", 4, 1.9, 1),
]
BASE_PRICE_BY_STARS = {2: 60, 3: 120, 4: 220, 5: 380}  # MYR per night


def init_db():
    """Create tables and insert sample hotels the first time the app starts."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM hotels").fetchone()[0] == 0:
        for h in SEED_HOTELS:
            cur = conn.execute(
                "INSERT INTO hotels (name, city, area, stars, rating, description, amenities, color) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", h)
            base = BASE_PRICE_BY_STARS[h[3]]
            for name, cap, mult, qty in SEED_ROOMS:
                conn.execute(
                    "INSERT INTO rooms (hotel_id, name, capacity, price, quantity) VALUES (?, ?, ?, ?, ?)",
                    (cur.lastrowid, name, cap, round(base * mult), qty))
    conn.commit()
    conn.close()


# ----------------------------------------------------------------- helpers ---

def parse_dates(check_in, check_out):
    """Return (date, date, None) or (None, None, error message)."""
    try:
        ci = date.fromisoformat(check_in)
        co = date.fromisoformat(check_out)
    except (TypeError, ValueError):
        return None, None, "Please choose valid check-in and check-out dates."
    if ci < date.today():
        return None, None, "Check-in date can't be in the past."
    if co <= ci:
        return None, None, "Check-out must be after check-in."
    if (co - ci).days > 30:
        return None, None, "Stays are limited to 30 nights."
    return ci, co, None


def rooms_left(room_id, quantity, check_in, check_out):
    """How many rooms of this type are free for the date range.
    Two stays overlap when one starts before the other ends: a.in < b.out AND a.out > b.in."""
    booked = get_db().execute(
        "SELECT COUNT(*) FROM bookings WHERE room_id = ? AND status = 'confirmed' "
        "AND check_in < ? AND check_out > ?",
        (room_id, check_out, check_in)).fetchone()[0]
    return quantity - booked


def new_reference():
    return "SE-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


@app.context_processor
def inject_server_info():
    """Available in every template: which container/CPU served the page."""
    return {"hostname": socket.gethostname(), "arch": platform.machine()}


# ------------------------------------------------------------------ routes ---

@app.route("/")
def index():
    db = get_db()
    cities = [r["city"] for r in db.execute("SELECT DISTINCT city FROM hotels ORDER BY city")]

    tomorrow = date.today() + timedelta(days=1)
    city = request.args.get("city", "")
    check_in = request.args.get("check_in", tomorrow.isoformat())
    check_out = request.args.get("check_out", (tomorrow + timedelta(days=2)).isoformat())
    guests = request.args.get("guests", 2, type=int)

    ci, co, error = parse_dates(check_in, check_out)
    if error and request.args:
        flash(error, "error")

    query = "SELECT * FROM hotels" + (" WHERE city = ?" if city else "") + " ORDER BY rating DESC"
    hotels = db.execute(query, (city,) if city else ()).fetchall()

    results = []
    nights = (co - ci).days if ci else 0
    for h in hotels:
        # cheapest room that fits the party and is still available
        best = None
        for r in db.execute("SELECT * FROM rooms WHERE hotel_id = ? AND capacity >= ? ORDER BY price",
                            (h["id"], guests)):
            if ci is None or rooms_left(r["id"], r["quantity"], check_in, check_out) > 0:
                best = r
                break
        results.append({"hotel": h, "from_price": best["price"] if best else None})

    return render_template("index.html", results=results, cities=cities, city=city,
                           check_in=check_in, check_out=check_out, guests=guests,
                           nights=nights, today=date.today().isoformat())


@app.route("/hotel/<int:hotel_id>")
def hotel(hotel_id):
    db = get_db()
    h = db.execute("SELECT * FROM hotels WHERE id = ?", (hotel_id,)).fetchone()
    if h is None:
        return render_template("404.html"), 404

    tomorrow = date.today() + timedelta(days=1)
    check_in = request.args.get("check_in", tomorrow.isoformat())
    check_out = request.args.get("check_out", (tomorrow + timedelta(days=2)).isoformat())
    guests = request.args.get("guests", 2, type=int)
    ci, co, error = parse_dates(check_in, check_out)
    if error:
        flash(error, "error")
    nights = (co - ci).days if ci else 0

    rooms = []
    for r in db.execute("SELECT * FROM rooms WHERE hotel_id = ? ORDER BY price", (hotel_id,)):
        left = rooms_left(r["id"], r["quantity"], check_in, check_out) if ci else 0
        rooms.append({"room": r, "left": left, "fits": r["capacity"] >= guests,
                      "total": r["price"] * nights})

    return render_template("hotel.html", h=h, rooms=rooms, check_in=check_in,
                           check_out=check_out, guests=guests, nights=nights,
                           amenities=h["amenities"].split(","), today=date.today().isoformat())


@app.route("/book/<int:room_id>", methods=["GET", "POST"])
def book(room_id):
    db = get_db()
    r = db.execute("SELECT rooms.*, hotels.name AS hotel_name, hotels.city, hotels.id AS hid "
                   "FROM rooms JOIN hotels ON hotels.id = rooms.hotel_id WHERE rooms.id = ?",
                   (room_id,)).fetchone()
    if r is None:
        return render_template("404.html"), 404

    src = request.form if request.method == "POST" else request.args
    check_in, check_out = src.get("check_in", ""), src.get("check_out", "")
    guests = src.get("guests", 1, type=int)
    ci, co, error = parse_dates(check_in, check_out)
    if error:
        flash(error, "error")
        return redirect(url_for("hotel", hotel_id=r["hid"]))
    nights = (co - ci).days
    total = r["price"] * nights

    if request.method == "POST":
        name = request.form.get("guest_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        if not name or "@" not in email:
            flash("Please enter your name and a valid email.", "error")
        elif guests > r["capacity"]:
            flash(f"This room fits at most {r['capacity']} guests.", "error")
        elif rooms_left(room_id, r["quantity"], check_in, check_out) <= 0:
            flash("Sorry, this room was just booked for those dates.", "error")
        else:
            ref = new_reference()
            db.execute(
                "INSERT INTO bookings (reference, room_id, guest_name, email, check_in, check_out, "
                "guests, total, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ref, room_id, name, email, check_in, check_out, guests, total,
                 datetime.now().strftime("%Y-%m-%d %H:%M")))
            db.commit()
            return redirect(url_for("confirmation", reference=ref))

    return render_template("book.html", r=r, check_in=check_in, check_out=check_out,
                           guests=guests, nights=nights, total=total)


@app.route("/confirmation/<reference>")
def confirmation(reference):
    b = get_booking(reference)
    if b is None:
        return render_template("404.html"), 404
    return render_template("confirmation.html", b=b)


def get_booking(reference):
    return get_db().execute(
        "SELECT bookings.*, rooms.name AS room_name, hotels.name AS hotel_name, hotels.city, "
        "hotels.color FROM bookings JOIN rooms ON rooms.id = bookings.room_id "
        "JOIN hotels ON hotels.id = rooms.hotel_id WHERE reference = ?", (reference,)).fetchone()


@app.route("/my-bookings")
def my_bookings():
    email = request.args.get("email", "").strip().lower()
    bookings = []
    if email:
        bookings = get_db().execute(
            "SELECT bookings.*, rooms.name AS room_name, hotels.name AS hotel_name, hotels.city "
            "FROM bookings JOIN rooms ON rooms.id = bookings.room_id "
            "JOIN hotels ON hotels.id = rooms.hotel_id WHERE email = ? ORDER BY check_in DESC",
            (email,)).fetchall()
    return render_template("my_bookings.html", email=email, bookings=bookings)


@app.route("/cancel/<reference>", methods=["POST"])
def cancel(reference):
    db = get_db()
    db.execute("UPDATE bookings SET status = 'cancelled' WHERE reference = ?", (reference,))
    db.commit()
    b = get_booking(reference)
    flash(f"Booking {reference} has been cancelled.", "success")
    return redirect(url_for("my_bookings", email=b["email"] if b else ""))


@app.route("/health")
def health():
    """Used by Docker's HEALTHCHECK - also proves the database is reachable."""
    get_db().execute("SELECT 1")
    return {"status": "ok"}


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
