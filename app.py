from flask import Flask, render_template, request, redirect, url_for, make_response
from supabase import create_client, Client
from datetime import datetime, date
import os
import uuid
import json
import re
from urllib.parse import unquote, urlencode
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

PLACE_CATEGORIES = ["スポット", "レストラン", "居酒屋", "カフェ", "その他"]
LEGACY_CATEGORY_MAP = {
    "spot": "スポット",
    "restaurant": "レストラン",
    "izakaya": "居酒屋",
    "cafe": "カフェ",
}
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "webp"}

TRIP_COOKIE = "travel_trip_id"
TRIP_TABLE = "travel_trips"
TRIP_SETTINGS_TABLE = "travel_trip_settings"
PLACE_TABLE = "travel_places"
PLACE_PHOTO_TABLE = "travel_place_photos"
SCHEDULE_TABLE = "travel_schedules"
SCHEDULE_PHOTO_TABLE = "travel_schedule_photos"
SCHEDULE_POST_TABLE = "travel_schedule_posts"
SCHEDULE_POST_PHOTO_TABLE = "travel_schedule_post_photos"
MEMO_TABLE = "travel_memos"
HOTEL_TABLE = "travel_hotels"
HOTEL_PHOTO_TABLE = "travel_hotel_photos"
FLIGHT_TABLE = "travel_flights"


def get_supabase() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set.")
    return create_client(url, key)


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def format_jp_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return f"{value.month}月{value.day}日"
    if isinstance(value, str):
        parsed = parse_date(value)
        if parsed:
            return f"{parsed.month}月{parsed.day}日"
    return None


def parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def format_jp_time(value):
    parsed = parse_datetime(value)
    if not parsed:
        return None
    return parsed.strftime("%H:%M")


def format_jp_date_from_datetime(value):
    parsed = parse_datetime(value)
    if not parsed:
        return None
    return f"{parsed.month}月{parsed.day}日"


def format_duration(start_value, end_value):
    start_dt = parse_datetime(start_value)
    end_dt = parse_datetime(end_value)
    if not start_dt or not end_dt:
        return None
    delta = end_dt - start_dt
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes <= 0:
        return None
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if minutes:
        return f"{hours}時間{minutes}分"
    return f"{hours}時間"


def parse_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def normalize_category(value):
    if not value:
        return "その他"
    if isinstance(value, str):
        value = value.strip()
    if value in PLACE_CATEGORIES:
        return value
    key = value.lower() if isinstance(value, str) else value
    if key in LEGACY_CATEGORY_MAP:
        return LEGACY_CATEGORY_MAP[key]
    return "その他"


def parse_photo_urls(value):
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str) and item]


def parse_photo_refs(value):
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str) and item]


def extract_photo_reference(url):
    if not url:
        return None
    match = re.search(r"[?&]photo_reference=([^&]+)", url)
    if match:
        return unquote(match.group(1))
    match = re.search(r"[?&]1s([^&]+)", url)
    if match:
        return unquote(match.group(1))
    return None


def normalize_photo_url(value):
    if not value:
        return None
    if isinstance(value, str) and value.startswith("google-ref:"):
        return value
    ref = extract_photo_reference(value)
    if ref:
        return f"google-ref:{ref}"
    return value


def normalize_external_url(value):
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if re.match(r"^https?://", value, re.IGNORECASE):
        return value
    return f"https://{value}"


def upload_place_photo(sb: Client, file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    filename = secure_filename(file_storage.filename)
    if "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        return None
    file_bytes = file_storage.read()
    if not file_bytes:
        return None
    bucket = os.environ.get("SUPABASE_BUCKET", "place-photos")
    key = f"places/{uuid.uuid4().hex}.{ext}"
    sb.storage.from_(bucket).upload(
        key,
        file_bytes,
        {"content-type": file_storage.mimetype or "application/octet-stream"},
    )
    return sb.storage.from_(bucket).get_public_url(key)


def upload_place_photos(sb: Client, files):
    urls = []
    for file_storage in files or []:
        url = upload_place_photo(sb, file_storage)
        if url:
            urls.append(url)
    return urls


def collect_post_entries(form, files, prefix="post"):
    indices = set()
    for key in form.keys():
        if key.startswith(f"{prefix}_") and key.rsplit("_", 1)[-1].isdigit():
            indices.add(int(key.rsplit("_", 1)[-1]))
    for key in files.keys():
        if key.startswith(f"{prefix}_photos_") and key.rsplit("_", 1)[-1].isdigit():
            indices.add(int(key.rsplit("_", 1)[-1]))
    entries = []
    for index in sorted(indices):
        time_value = form.get(f"{prefix}_time_{index}") or None
        title = (form.get(f"{prefix}_title_{index}") or "").strip()
        body = (form.get(f"{prefix}_body_{index}") or "").strip()
        photo_files = files.getlist(f"{prefix}_photos_{index}")
        if not (time_value or title or body or photo_files):
            continue
        entries.append(
            {
                "time": time_value,
                "title": title,
                "body": body,
                "files": photo_files,
            }
        )
    if entries:
        return entries
    time_value = form.get("time") or None
    title = (form.get("title") or "").strip()
    body = (form.get("body") or "").strip()
    photo_files = files.getlist("post_photos")
    if time_value or title or body or photo_files:
        return [{"time": time_value, "title": title, "body": body, "files": photo_files}]
    return []


def collect_schedule_entries(form, files):
    indices = set()
    for key in form.keys():
        if key.startswith("schedule_") and key.rsplit("_", 1)[-1].isdigit():
            indices.add(int(key.rsplit("_", 1)[-1]))
    for key in files.keys():
        if key.startswith("schedule_photos_") and key.rsplit("_", 1)[-1].isdigit():
            indices.add(int(key.rsplit("_", 1)[-1]))
    entries = []
    for index in sorted(indices):
        title = (form.get(f"schedule_title_{index}") or "").strip()
        schedule_date = (form.get(f"schedule_date_{index}") or "").strip() or None
        start_time = (form.get(f"schedule_start_time_{index}") or "").strip() or None
        end_time = (form.get(f"schedule_end_time_{index}") or "").strip() or None
        detail = (form.get(f"schedule_detail_{index}") or "").strip()
        place_id = form.get(f"schedule_place_id_{index}") or None
        address = form.get(f"schedule_address_{index}") or None
        lat = parse_float(form.get(f"schedule_lat_{index}"))
        lng = parse_float(form.get(f"schedule_lng_{index}"))
        photo_url = normalize_photo_url(form.get(f"schedule_photo_url_{index}") or None)
        rating = parse_float(form.get(f"schedule_rating_{index}"))
        user_ratings_total = form.get(f"schedule_user_ratings_total_{index}") or None
        website = form.get(f"schedule_website_{index}") or None
        phone = form.get(f"schedule_phone_{index}") or None
        google_url = form.get(f"schedule_google_url_{index}") or None
        opening_hours = form.get(f"schedule_opening_hours_{index}") or None
        photo_urls = parse_photo_urls(form.get(f"schedule_photo_urls_{index}"))
        photo_refs = parse_photo_refs(form.get(f"schedule_photo_refs_{index}"))
        photo_files = files.getlist(f"schedule_photos_{index}")
        if not (title or schedule_date or detail or address or place_id or photo_files):
            continue
        entries.append(
            {
                "title": title,
                "date": schedule_date,
                "start_time": start_time,
                "end_time": end_time,
                "detail": detail,
                "place_id": place_id,
                "address": address,
                "lat": lat,
                "lng": lng,
                "photo_url": photo_url,
                "rating": rating,
                "user_ratings_total": user_ratings_total,
                "website": website,
                "phone": phone,
                "google_url": google_url,
                "opening_hours": opening_hours,
                "photo_urls": photo_urls,
                "photo_refs": photo_refs,
                "photo_files": photo_files,
            }
        )
    return entries


def get_trip_cookie_id():
    value = request.cookies.get(TRIP_COOKIE)
    if value and value.isdigit():
        return int(value)
    return None


def fetch_trip(sb: Client, trip_id: int):
    data = (
        sb.table(TRIP_TABLE)
        .select("id, name, start_date, end_date, note, created_at")
        .eq("id", trip_id)
        .execute()
        .data
    )
    return data[0] if data else None


def get_active_trip(sb: Client):
    trip_id = get_trip_cookie_id()
    if not trip_id:
        return None
    return fetch_trip(sb, trip_id)


def get_warika_url(sb: Client, trip_id: int):
    data = (
        sb.table(TRIP_SETTINGS_TABLE)
        .select("warika_url")
        .eq("trip_id", trip_id)
        .execute()
        .data
    )
    if data:
        return data[0].get("warika_url")
    return None


def upsert_warika_url(sb: Client, trip_id: int, url):
    payload = {
        "trip_id": trip_id,
        "warika_url": url,
        "updated_at": now_str(),
    }
    sb.table(TRIP_SETTINGS_TABLE).upsert(payload, on_conflict="trip_id").execute()


@app.context_processor
def inject_global_context():
    try:
        sb = get_supabase()
    except RuntimeError:
        return {}
    trip = get_active_trip(sb)
    warika_url = get_warika_url(sb, trip["id"]) if trip else None
    return {"active_trip": trip, "warika_url": warika_url}


@app.route("/")
def home():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))

    image_dir = os.path.join(app.static_folder, "img")
    image_files = []
    if os.path.isdir(image_dir):
        for name in os.listdir(image_dir):
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                image_files.append(f"img/{name}")
    image_files.sort()

    schedules = (
        sb.table(SCHEDULE_TABLE)
        .select("id, title, date, start_time, detail, created_at")
        .eq("trip_id", trip["id"])
        .order("date", desc=False)
        .order("start_time", desc=False)
        .order("id", desc=True)
        .execute()
        .data
    )
    today = date.today()
    upcoming_by_date = {}
    for row in schedules:
        row_date = parse_date(row.get("date"))
        if not row_date or row_date < today:
            continue
        if row.get("start_time"):
            row["start_time_label"] = str(row["start_time"])[:5]
        upcoming_by_date.setdefault(row_date, []).append(row)
    next_date = min(upcoming_by_date.keys()) if upcoming_by_date else None
    next_day_schedules = upcoming_by_date.get(next_date, []) if next_date else []
    return render_template(
        "home.html",
        next_date=next_date,
        next_day_schedules=next_day_schedules,
        hero_images=image_files,
    )


@app.route("/trips", methods=["GET", "POST"])
def trips():
    sb = get_supabase()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip() or "新しい旅行"
        start_date = request.form.get("start_date") or None
        end_date = request.form.get("end_date") or None
        note = (request.form.get("note") or "").strip() or None
        created = (
            sb.table(TRIP_TABLE)
            .insert(
                {
                    "name": name,
                    "start_date": start_date,
                    "end_date": end_date,
                    "note": note,
                    "created_at": now_str(),
                }
            )
            .execute()
            .data
        )
        trip_id = created[0]["id"] if created else None
        resp = make_response(redirect(url_for("home")))
        if trip_id:
            resp.set_cookie(TRIP_COOKIE, str(trip_id), max_age=60 * 60 * 24 * 365, samesite="Lax")
        return resp

    trips_data = (
        sb.table(TRIP_TABLE)
        .select("id, name, start_date, end_date, note, created_at")
        .order("id", desc=True)
        .execute()
        .data
    )
    return render_template(
        "trips.html",
        trips=trips_data,
        selected_trip_id=get_trip_cookie_id(),
    )


@app.post("/trips/select")
def trips_select():
    trip_id = request.form.get("trip_id") or ""
    if not trip_id.isdigit():
        return redirect(url_for("trips"))
    resp = make_response(redirect(url_for("home")))
    resp.set_cookie(TRIP_COOKIE, trip_id, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


@app.post("/trips/clear")
def trips_clear():
    resp = make_response(redirect(url_for("trips")))
    resp.delete_cookie(TRIP_COOKIE)
    return resp


@app.post("/settings/warika")
def warika_update():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    url = normalize_external_url(request.form.get("warika_url") or "")
    upsert_warika_url(sb, trip["id"], url)
    return redirect(url_for("home"))

@app.route("/places", methods=["GET", "POST"])
def places():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))

    category = request.args.get("category", "all")
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        cat = normalize_category(request.form.get("category", "").strip())
        notes = request.form.get("notes", "").strip()
        place_id = request.form.get("place_id") or None
        address = request.form.get("address") or None
        lat = parse_float(request.form.get("lat"))
        lng = parse_float(request.form.get("lng"))
        photo_url = normalize_photo_url(request.form.get("photo_url") or None)
        rating = parse_float(request.form.get("rating"))
        user_ratings_total = request.form.get("user_ratings_total") or None
        website = request.form.get("website") or None
        phone = request.form.get("phone") or None
        google_url = request.form.get("google_url") or None
        opening_hours = request.form.get("opening_hours") or None
        if name or notes or address:
            place = (
                sb.table(PLACE_TABLE)
                .insert(
                    {
                        "trip_id": trip["id"],
                        "name": name or "行きたい場所",
                        "category": cat,
                        "notes": notes,
                        "place_id": place_id,
                        "address": address,
                        "lat": lat,
                        "lng": lng,
                        "photo_url": photo_url,
                        "rating": rating,
                        "user_ratings_total": user_ratings_total,
                        "website": website,
                        "phone": phone,
                        "google_url": google_url,
                        "opening_hours": opening_hours,
                        "created_at": now_str(),
                    }
                )
                .execute()
                .data
            )
            place_id = place[0]["id"] if place else None
            google_photo_refs = parse_photo_refs(request.form.get("photo_refs"))
            if not google_photo_refs:
                google_photo_urls = parse_photo_urls(request.form.get("photo_urls"))
                google_photo_refs = [
                    ref for ref in (extract_photo_reference(url) for url in google_photo_urls) if ref
                ]
            google_photo_entries = [f"google-ref:{ref}" for ref in google_photo_refs]
            photo_urls = upload_place_photos(sb, request.files.getlist("photos"))
            all_photo_urls = google_photo_entries + photo_urls
            if place_id and all_photo_urls:
                sb.table(PLACE_PHOTO_TABLE).insert(
                    [
                        {
                            "place_id": place_id,
                            "photo_url": url,
                            "created_at": now_str(),
                        }
                        for url in all_photo_urls
                    ]
                ).execute()
        return redirect(url_for("places", category=category))

    query = (
        sb.table(PLACE_TABLE)
        .select(
            "id, name, category, notes, place_id, address, lat, lng, "
            "photo_url, rating, user_ratings_total, website, phone, google_url, "
            "opening_hours, created_at"
        )
        .eq("trip_id", trip["id"])
        .order("id", desc=True)
    )
    rows = query.execute().data
    for row in rows:
        row["category_display"] = normalize_category(row.get("category"))
    if category != "all":
        rows = [row for row in rows if row["category_display"] == category]
    place_ids = [row["id"] for row in rows]
    photos_by_place = {}
    if place_ids:
        photos = (
            sb.table(PLACE_PHOTO_TABLE)
            .select("id, place_id, photo_url")
            .in_("place_id", place_ids)
            .order("id", desc=False)
            .execute()
            .data
        )
        for photo in photos:
            photos_by_place.setdefault(photo["place_id"], []).append(
                {"id": photo["id"], "url": photo["photo_url"]}
            )
    for row in rows:
        place_photos = photos_by_place.get(row["id"], [])
        if place_photos:
            deduped = {}
            for photo in place_photos:
                url = photo.get("url")
                if not url:
                    continue
                if url not in deduped or (deduped[url]["id"] is None and photo.get("id")):
                    deduped[url] = photo
            photos_by_place[row["id"]] = list(deduped.values())
    return render_template(
        "places.html",
        places=rows,
        photos_by_place=photos_by_place,
        active_category=category,
        categories=PLACE_CATEGORIES,
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
    )


@app.route("/places/<int:place_id>/edit")
def places_edit(place_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))

    data = (
        sb.table(PLACE_TABLE)
        .select(
            "id, name, category, notes, place_id, address, lat, lng, photo_url, "
            "rating, user_ratings_total, website, phone, google_url, opening_hours"
        )
        .eq("id", place_id)
        .eq("trip_id", trip["id"])
        .execute()
        .data
    )
    if not data:
        return redirect(url_for("places"))
    data[0]["category"] = normalize_category(data[0].get("category"))
    photos = (
        sb.table(PLACE_PHOTO_TABLE)
        .select("id, place_id, photo_url")
        .eq("place_id", place_id)
        .order("id", desc=False)
        .execute()
        .data
    )
    return render_template(
        "places_edit.html",
        place=data[0],
        photos=photos,
        categories=PLACE_CATEGORIES,
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
    )


@app.post("/places/<int:place_id>/update")
def places_update(place_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))

    name = request.form.get("name", "").strip()
    category = normalize_category(request.form.get("category", "").strip())
    notes = request.form.get("notes", "").strip()
    place_google_id = request.form.get("place_id") or None
    address = request.form.get("address") or None
    lat = parse_float(request.form.get("lat"))
    lng = parse_float(request.form.get("lng"))
    photo_url = normalize_photo_url(request.form.get("photo_url") or None)
    rating = parse_float(request.form.get("rating"))
    user_ratings_total = request.form.get("user_ratings_total") or None
    website = request.form.get("website") or None
    phone = request.form.get("phone") or None
    google_url = request.form.get("google_url") or None
    opening_hours = request.form.get("opening_hours") or None
    if name or notes or address:
        payload = {
            "name": name or "行きたい場所",
            "category": category,
            "notes": notes,
            "place_id": place_google_id,
            "address": address,
            "lat": lat,
            "lng": lng,
            "photo_url": photo_url,
            "rating": rating,
            "user_ratings_total": user_ratings_total,
            "website": website,
            "phone": phone,
            "google_url": google_url,
            "opening_hours": opening_hours,
        }
        sb.table(PLACE_TABLE).update(payload).eq("id", place_id).eq("trip_id", trip["id"]).execute()
        google_photo_refs = parse_photo_refs(request.form.get("photo_refs"))
        if not google_photo_refs:
            google_photo_urls = parse_photo_urls(request.form.get("photo_urls"))
            google_photo_refs = [
                ref for ref in (extract_photo_reference(url) for url in google_photo_urls) if ref
            ]
        google_photo_entries = [f"google-ref:{ref}" for ref in google_photo_refs]
        photo_urls = upload_place_photos(sb, request.files.getlist("photos"))
        all_photo_urls = google_photo_entries + photo_urls
        if all_photo_urls:
            sb.table(PLACE_PHOTO_TABLE).insert(
                [
                    {
                        "place_id": place_id,
                        "photo_url": url,
                        "created_at": now_str(),
                    }
                    for url in all_photo_urls
                ]
            ).execute()
    return redirect(url_for("places", category=category))


@app.post("/places/<int:place_id>/delete")
def places_delete(place_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    sb.table(PLACE_TABLE).delete().eq("id", place_id).eq("trip_id", trip["id"]).execute()
    return redirect(url_for("places"))


@app.post("/places/photo/delete")
def places_photo_delete():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    photo_id = request.form.get("photo_id") or None
    place_id = request.form.get("place_id") or None
    photo_url = request.form.get("photo_url") or None
    category = request.form.get("category") or "all"
    if photo_id and str(photo_id).isdigit():
        photo_id = int(photo_id)
    if place_id and str(place_id).isdigit():
        place_id = int(place_id)
    if photo_id:
        sb.table(PLACE_PHOTO_TABLE).delete().eq("id", photo_id).execute()
    if place_id and photo_url:
        sb.table(PLACE_PHOTO_TABLE).delete().eq("place_id", place_id).eq("photo_url", photo_url).execute()
        sb.table(PLACE_TABLE).update({"photo_url": None}).eq("id", place_id).eq(
            "photo_url", photo_url
        ).execute()
    return redirect(url_for("places", category=category))

@app.route("/schedule", methods=["GET", "POST"])
def schedule():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if request.method == "POST":
        schedule_entries = collect_schedule_entries(request.form, request.files)
        for entry in schedule_entries:
            schedule_row = (
                sb.table(SCHEDULE_TABLE)
                .insert(
                    {
                        "trip_id": trip["id"],
                        "title": entry["title"] or "予定",
                        "date": entry["date"],
                        "start_time": entry["start_time"],
                        "end_time": entry["end_time"],
                        "detail": entry["detail"],
                        "place_id": entry["place_id"],
                        "address": entry["address"],
                        "lat": entry["lat"],
                        "lng": entry["lng"],
                        "photo_url": entry["photo_url"],
                        "rating": entry["rating"],
                        "user_ratings_total": entry["user_ratings_total"],
                        "website": entry["website"],
                        "phone": entry["phone"],
                        "google_url": entry["google_url"],
                        "opening_hours": entry["opening_hours"],
                        "created_at": now_str(),
                    }
                )
                .execute()
                .data
            )
            schedule_id = schedule_row[0]["id"] if schedule_row else None
            if not schedule_id:
                continue
            google_photo_refs = entry["photo_refs"]
            if not google_photo_refs:
                google_photo_refs = [
                    ref for ref in (extract_photo_reference(url) for url in entry["photo_urls"]) if ref
                ]
            google_photo_entries = [f"google-ref:{ref}" for ref in google_photo_refs]
            photo_urls = upload_place_photos(sb, entry["photo_files"])
            all_photo_urls = (google_photo_entries + photo_urls)[:3]
            if all_photo_urls:
                sb.table(SCHEDULE_PHOTO_TABLE).insert(
                    [
                        {
                            "schedule_id": schedule_id,
                            "photo_url": url,
                            "created_at": now_str(),
                        }
                        for url in all_photo_urls
                    ]
                ).execute()
        return redirect(url_for("schedule"))

    def post_sort_key(post):
        time_value = post.get("time")
        if time_value:
            return (0, time_value, post.get("id") or 0)
        return (1, post.get("id") or 0)

    def group_schedules_by_date(schedules):
        groups = []
        by_key = {}
        for item in schedules:
            date_value = item.get("date") or ""
            if date_value:
                date_key = date_value
                date_label = date_value
            else:
                date_key = "undated"
                date_label = "日付未設定"
            if date_key not in by_key:
                group = {
                    "date_key": date_key,
                    "date_label": date_label,
                    "items": [],
                    "schedule_ids": [],
                    "timeline_schedule_id": None,
                    "form_id": "",
                }
                by_key[date_key] = group
                groups.append(group)
            group = by_key[date_key]
            group["items"].append(item)
            if item.get("id") is not None:
                group["schedule_ids"].append(item["id"])
        for group in groups:
            if group["schedule_ids"]:
                timeline_id = group["schedule_ids"][0]
                group["timeline_schedule_id"] = timeline_id
                group["form_id"] = f"{group['date_key'].replace('-', '')}-{timeline_id}"
            else:
                group["form_id"] = group["date_key"].replace("-", "") or "undated"
        return groups

    schedules = (
        sb.table(SCHEDULE_TABLE)
        .select(
            "id, title, date, start_time, end_time, detail, place_id, address, lat, lng, photo_url, "
            "rating, user_ratings_total, website, phone, google_url, opening_hours, created_at"
        )
        .eq("trip_id", trip["id"])
        .order("date", desc=False)
        .order("id", desc=True)
        .execute()
        .data
    )

    today = date.today()
    upcoming = []
    past = []
    for row in schedules:
        row_date = parse_date(row.get("date"))
        if row_date and row_date < today:
            past.append(row)
        else:
            upcoming.append(row)

    upcoming.sort(key=lambda r: (parse_date(r.get("date")) or date.max, r.get("id") or 0))
    past.sort(key=lambda r: (parse_date(r.get("date")) or date.min, r.get("id") or 0), reverse=True)

    schedule_ids = [row["id"] for row in (upcoming + past)]
    photos_by_schedule = {}
    posts_by_schedule = {}
    post_photos_by_post = {}
    if schedule_ids:
        photos = (
            sb.table(SCHEDULE_PHOTO_TABLE)
            .select("id, schedule_id, photo_url")
            .in_("schedule_id", schedule_ids)
            .order("id", desc=False)
            .execute()
            .data
        )

        def build_schedule_photo_entry(photo_row):
            raw_url = photo_row.get("photo_url") or ""
            ref = ""
            if raw_url.startswith("google-ref:"):
                ref = raw_url[11:]
            else:
                ref = extract_photo_reference(raw_url)
            is_google = bool(ref) or ("googleusercontent.com" in raw_url or "maps.googleapis.com" in raw_url)
            display_url = raw_url
            if ref and api_key:
                display_url = (
                    "https://maps.googleapis.com/maps/api/place/photo"
                    f"?maxwidth=600&photo_reference={ref}&key={api_key}"
                )
            return {
                "id": photo_row.get("id"),
                "url": raw_url,
                "display_url": display_url,
                "is_google": is_google,
            }

        for photo in photos:
            photos_by_schedule.setdefault(photo["schedule_id"], []).append(
                build_schedule_photo_entry(photo)
            )
        posts = (
            sb.table(SCHEDULE_POST_TABLE)
            .select("id, schedule_id, time, title, body, created_at")
            .in_("schedule_id", schedule_ids)
            .order("id", desc=False)
            .execute()
            .data
        )
        for post in posts:
            posts_by_schedule.setdefault(post["schedule_id"], []).append(post)
        post_ids = [post["id"] for post in posts]
        if post_ids:
            post_photos = (
                sb.table(SCHEDULE_POST_PHOTO_TABLE)
                .select("id, post_id, photo_url")
                .in_("post_id", post_ids)
                .order("id", desc=False)
                .execute()
                .data
            )
            for photo in post_photos:
                post_photos_by_post.setdefault(photo["post_id"], []).append(photo)
    for row in schedules:
        schedule_photos = photos_by_schedule.get(row["id"], [])
        if schedule_photos:
            deduped = {}
            for photo in schedule_photos:
                url = photo.get("url")
                if not url:
                    continue
                if url not in deduped or (deduped[url]["id"] is None and photo.get("id")):
                    deduped[url] = photo
            ordered = list(deduped.values())
            if len(ordered) > 3:
                excess_ids = [photo["id"] for photo in ordered[3:] if photo.get("id")]
                if excess_ids:
                    sb.table(SCHEDULE_PHOTO_TABLE).delete().in_("id", excess_ids).execute()
                ordered = ordered[:3]
            photos_by_schedule[row["id"]] = ordered
        schedule_posts = posts_by_schedule.get(row["id"], [])
        if schedule_posts:
            posts_by_schedule[row["id"]] = sorted(schedule_posts, key=post_sort_key)

    upcoming_groups = group_schedules_by_date(upcoming)
    past_groups = group_schedules_by_date(past)
    posts_by_date = {}
    for group in upcoming_groups + past_groups:
        group_posts = []
        for schedule_id in group["schedule_ids"]:
            group_posts.extend(posts_by_schedule.get(schedule_id, []))
        if group_posts:
            group_posts = sorted(group_posts, key=post_sort_key)
        posts_by_date[group["date_key"]] = group_posts
    return render_template(
        "schedule.html",
        upcoming_groups=upcoming_groups,
        past_groups=past_groups,
        photos_by_schedule=photos_by_schedule,
        posts_by_schedule=posts_by_schedule,
        posts_by_date=posts_by_date,
        post_photos_by_post=post_photos_by_post,
        google_maps_api_key=api_key,
    )


@app.route("/schedule/<int:schedule_id>/edit")
def schedule_edit(schedule_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    data = (
        sb.table(SCHEDULE_TABLE)
        .select(
            "id, title, date, start_time, end_time, detail, place_id, address, lat, lng, photo_url, "
            "rating, user_ratings_total, website, phone, google_url, opening_hours"
        )
        .eq("id", schedule_id)
        .eq("trip_id", trip["id"])
        .execute()
        .data
    )
    if not data:
        return redirect(url_for("schedule"))
    photos = (
        sb.table(SCHEDULE_PHOTO_TABLE)
        .select("id, schedule_id, photo_url")
        .eq("schedule_id", schedule_id)
        .order("id", desc=False)
        .execute()
        .data
    )
    return render_template(
        "schedule_edit.html",
        schedule=data[0],
        photos=photos,
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
    )


@app.post("/schedule/<int:schedule_id>/update")
def schedule_update(schedule_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    title = request.form.get("title", "").strip()
    schedule_date = request.form.get("date", "").strip()
    start_time = (request.form.get("start_time") or "").strip() or None
    end_time = (request.form.get("end_time") or "").strip() or None
    detail = request.form.get("detail", "").strip()
    place_id = request.form.get("place_id") or None
    address = request.form.get("address") or None
    lat = parse_float(request.form.get("lat"))
    lng = parse_float(request.form.get("lng"))
    photo_url = normalize_photo_url(request.form.get("photo_url") or None)
    rating = parse_float(request.form.get("rating"))
    user_ratings_total = request.form.get("user_ratings_total") or None
    website = request.form.get("website") or None
    phone = request.form.get("phone") or None
    google_url = request.form.get("google_url") or None
    opening_hours = request.form.get("opening_hours") or None
    if title or schedule_date or detail or address:
        sb.table(SCHEDULE_TABLE).update(
            {
                "title": title or "予定",
                "date": schedule_date,
                "start_time": start_time,
                "end_time": end_time,
                "detail": detail,
                "place_id": place_id,
                "address": address,
                "lat": lat,
                "lng": lng,
                "photo_url": photo_url,
                "rating": rating,
                "user_ratings_total": user_ratings_total,
                "website": website,
                "phone": phone,
                "google_url": google_url,
                "opening_hours": opening_hours,
            }
        ).eq("id", schedule_id).eq("trip_id", trip["id"]).execute()
        google_photo_refs = parse_photo_refs(request.form.get("photo_refs"))
        if not google_photo_refs:
            google_photo_urls = parse_photo_urls(request.form.get("photo_urls"))
            google_photo_refs = [
                ref for ref in (extract_photo_reference(url) for url in google_photo_urls) if ref
            ]
        google_photo_entries = [f"google-ref:{ref}" for ref in google_photo_refs]
        photo_urls = upload_place_photos(sb, request.files.getlist("photos"))
        all_photo_urls = google_photo_entries + photo_urls
        if all_photo_urls:
            sb.table(SCHEDULE_PHOTO_TABLE).insert(
                [
                    {
                        "schedule_id": schedule_id,
                        "photo_url": url,
                        "created_at": now_str(),
                    }
                    for url in all_photo_urls
                ]
            ).execute()
    return redirect(url_for("schedule"))

@app.post("/schedule/<int:schedule_id>/posts")
def schedule_post_create(schedule_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    post_entries = collect_post_entries(request.form, request.files, prefix="post")
    if not post_entries:
        return redirect(url_for("schedule"))
    for entry in post_entries:
        post = (
            sb.table(SCHEDULE_POST_TABLE)
            .insert(
                {
                    "schedule_id": schedule_id,
                    "time": entry["time"],
                    "title": entry["title"],
                    "body": entry["body"],
                    "created_at": now_str(),
                }
            )
            .execute()
            .data
        )
        post_id = post[0]["id"] if post else None
        photo_urls = upload_place_photos(sb, entry["files"])
        if post_id and photo_urls:
            sb.table(SCHEDULE_POST_PHOTO_TABLE).insert(
                [
                    {
                        "post_id": post_id,
                        "photo_url": url,
                        "created_at": now_str(),
                    }
                    for url in photo_urls
                ]
            ).execute()
    return redirect(url_for("schedule"))


@app.post("/schedule/post/<int:post_id>/delete")
def schedule_post_delete(post_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    sb.table(SCHEDULE_POST_PHOTO_TABLE).delete().eq("post_id", post_id).execute()
    sb.table(SCHEDULE_POST_TABLE).delete().eq("id", post_id).execute()
    return redirect(url_for("schedule"))


@app.post("/schedule/post/photo/delete")
def schedule_post_photo_delete():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    photo_id = request.form.get("photo_id") or None
    post_id = request.form.get("post_id") or None
    photo_url = request.form.get("photo_url") or None
    if photo_id and str(photo_id).isdigit():
        photo_id = int(photo_id)
    if post_id and str(post_id).isdigit():
        post_id = int(post_id)
    if photo_id:
        sb.table(SCHEDULE_POST_PHOTO_TABLE).delete().eq("id", photo_id).execute()
    if post_id and photo_url:
        sb.table(SCHEDULE_POST_PHOTO_TABLE).delete().eq("post_id", post_id).eq(
            "photo_url", photo_url
        ).execute()
    return redirect(url_for("schedule"))


@app.post("/schedule/<int:schedule_id>/delete")
def schedule_delete(schedule_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    sb.table(SCHEDULE_TABLE).delete().eq("id", schedule_id).eq("trip_id", trip["id"]).execute()
    return redirect(url_for("schedule"))


@app.post("/schedule/photo/delete")
def schedule_photo_delete():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    photo_id = request.form.get("photo_id") or None
    schedule_id = request.form.get("schedule_id") or None
    photo_url = request.form.get("photo_url") or None
    if photo_id and str(photo_id).isdigit():
        photo_id = int(photo_id)
    if schedule_id and str(schedule_id).isdigit():
        schedule_id = int(schedule_id)
    if photo_id:
        sb.table(SCHEDULE_PHOTO_TABLE).delete().eq("id", photo_id).execute()
    if schedule_id and photo_url:
        sb.table(SCHEDULE_PHOTO_TABLE).delete().eq("schedule_id", schedule_id).eq(
            "photo_url", photo_url
        ).execute()
        sb.table(SCHEDULE_TABLE).update({"photo_url": None}).eq("id", schedule_id).eq(
            "photo_url", photo_url
        ).execute()
    return redirect(url_for("schedule"))


@app.route("/memo", methods=["GET", "POST"])
def memo():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    if request.method == "POST":
        body = request.form.get("body", "").strip()
        if body:
            sb.table(MEMO_TABLE).insert(
                {
                    "trip_id": trip["id"],
                    "body": body,
                    "created_at": now_str(),
                }
            ).execute()
        return redirect(url_for("memo"))

    memos = (
        sb.table(MEMO_TABLE)
        .select("id, body, created_at")
        .eq("trip_id", trip["id"])
        .order("id", desc=True)
        .execute()
        .data
    )
    return render_template(
        "memo.html",
        memos=memos,
    )


@app.post("/memo/<int:memo_id>/delete")
def memo_delete(memo_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    sb.table(MEMO_TABLE).delete().eq("id", memo_id).eq("trip_id", trip["id"]).execute()
    return redirect(url_for("memo"))

@app.route("/hotels", methods=["GET", "POST"])
def hotels():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        address = request.form.get("address", "").strip()
        map_url = normalize_external_url(request.form.get("map_url") or "")
        website_url = normalize_external_url(request.form.get("website_url") or "")
        checkin_date = request.form.get("checkin_date") or None
        checkout_date = request.form.get("checkout_date") or None
        notes = request.form.get("notes", "").strip()
        if name or address or notes:
            created = (
                sb.table(HOTEL_TABLE)
                .insert(
                    {
                        "trip_id": trip["id"],
                        "name": name or "ホテル",
                        "address": address,
                        "map_url": map_url,
                        "website_url": website_url,
                        "checkin_date": checkin_date,
                        "checkout_date": checkout_date,
                        "notes": notes,
                        "created_at": now_str(),
                    }
                )
                .execute()
                .data
            )
            hotel_id = created[0]["id"] if created else None
            if hotel_id:
                photo_urls = upload_place_photos(sb, request.files.getlist("photos"))
                if photo_urls:
                    sb.table(HOTEL_PHOTO_TABLE).insert(
                        [
                            {
                                "hotel_id": hotel_id,
                                "photo_url": url,
                                "created_at": now_str(),
                            }
                            for url in photo_urls
                        ]
                    ).execute()
        return redirect(url_for("hotels"))

    hotels_data = (
        sb.table(HOTEL_TABLE)
        .select("id, name, address, map_url, website_url, checkin_date, checkout_date, notes, created_at")
        .eq("trip_id", trip["id"])
        .order("id", desc=True)
        .execute()
        .data
    )
    for row in hotels_data:
        row["checkin_label"] = format_jp_date(row.get("checkin_date"))
        row["checkout_label"] = format_jp_date(row.get("checkout_date"))
    hotel_ids = [row["id"] for row in hotels_data]
    photos_by_hotel = {}
    if hotel_ids:
        photos = (
            sb.table(HOTEL_PHOTO_TABLE)
            .select("id, hotel_id, photo_url")
            .in_("hotel_id", hotel_ids)
            .order("id", desc=False)
            .execute()
            .data
        )
        for photo in photos:
            photos_by_hotel.setdefault(photo["hotel_id"], []).append(photo)
    return render_template(
        "hotels.html",
        hotels=hotels_data,
        photos_by_hotel=photos_by_hotel,
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
    )


@app.route("/hotels/<int:hotel_id>/edit")
def hotels_edit(hotel_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    data = (
        sb.table(HOTEL_TABLE)
        .select("id, name, address, map_url, website_url, checkin_date, checkout_date, notes, created_at")
        .eq("id", hotel_id)
        .eq("trip_id", trip["id"])
        .execute()
        .data
    )
    if not data:
        return redirect(url_for("hotels"))
    photos = (
        sb.table(HOTEL_PHOTO_TABLE)
        .select("id, hotel_id, photo_url")
        .eq("hotel_id", hotel_id)
        .order("id", desc=False)
        .execute()
        .data
    )
    return render_template(
        "hotels_edit.html",
        hotel=data[0],
        photos=photos,
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
    )


@app.post("/hotels/<int:hotel_id>/update")
def hotels_update(hotel_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    name = request.form.get("name", "").strip()
    address = request.form.get("address", "").strip()
    map_url = normalize_external_url(request.form.get("map_url") or "")
    website_url = normalize_external_url(request.form.get("website_url") or "")
    checkin_date = request.form.get("checkin_date") or None
    checkout_date = request.form.get("checkout_date") or None
    notes = request.form.get("notes", "").strip()
    if name or address or notes:
        payload = {
            "name": name or "ホテル",
            "address": address,
            "map_url": map_url,
            "website_url": website_url,
            "checkin_date": checkin_date,
            "checkout_date": checkout_date,
            "notes": notes,
        }
        sb.table(HOTEL_TABLE).update(payload).eq("id", hotel_id).eq("trip_id", trip["id"]).execute()
        photo_urls = upload_place_photos(sb, request.files.getlist("photos"))
        if photo_urls:
            sb.table(HOTEL_PHOTO_TABLE).insert(
                [
                    {
                        "hotel_id": hotel_id,
                        "photo_url": url,
                        "created_at": now_str(),
                    }
                    for url in photo_urls
                ]
            ).execute()
    return redirect(url_for("hotels"))


@app.post("/hotels/<int:hotel_id>/delete")
def hotels_delete(hotel_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    sb.table(HOTEL_TABLE).delete().eq("id", hotel_id).eq("trip_id", trip["id"]).execute()
    return redirect(url_for("hotels"))


@app.post("/hotels/photo/delete")
def hotels_photo_delete():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    photo_id = request.form.get("photo_id") or None
    hotel_id = request.form.get("hotel_id") or None
    if photo_id and str(photo_id).isdigit():
        photo_id = int(photo_id)
    if hotel_id and str(hotel_id).isdigit():
        hotel_id = int(hotel_id)
    if photo_id:
        sb.table(HOTEL_PHOTO_TABLE).delete().eq("id", photo_id).execute()
    if hotel_id:
        sb.table(HOTEL_PHOTO_TABLE).delete().eq("hotel_id", hotel_id).execute()
    return redirect(url_for("hotels"))


@app.route("/flights", methods=["GET", "POST"])
def flights():
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    if request.method == "POST":
        payload = {
            "trip_id": trip["id"],
            "airline": (request.form.get("airline") or "").strip(),
            "flight_no": (request.form.get("flight_no") or "").strip(),
            "depart_airport": (request.form.get("depart_airport") or "").strip(),
            "depart_at": request.form.get("depart_at") or None,
            "arrive_airport": (request.form.get("arrive_airport") or "").strip(),
            "arrive_at": request.form.get("arrive_at") or None,
            "reservation_code": (request.form.get("reservation_code") or "").strip(),
            "seat": (request.form.get("seat") or "").strip(),
            "terminal": (request.form.get("terminal") or "").strip(),
            "gate": (request.form.get("gate") or "").strip(),
            "notes": (request.form.get("notes") or "").strip(),
            "created_at": now_str(),
        }
        has_any = any(
            payload.get(key)
            for key in [
                "airline",
                "flight_no",
                "depart_airport",
                "depart_at",
                "arrive_airport",
                "arrive_at",
                "reservation_code",
                "seat",
                "terminal",
                "gate",
                "notes",
            ]
        )
        if has_any:
            sb.table(FLIGHT_TABLE).insert(payload).execute()
        return redirect(url_for("flights"))

    flights_data = (
        sb.table(FLIGHT_TABLE)
        .select(
            "id, airline, flight_no, depart_airport, depart_at, arrive_airport, arrive_at, "
            "reservation_code, seat, terminal, gate, notes, created_at"
        )
        .eq("trip_id", trip["id"])
        .order("depart_at", desc=False)
        .order("id", desc=True)
        .execute()
        .data
    )
    for row in flights_data:
        row["depart_time_label"] = format_jp_time(row.get("depart_at"))
        row["arrive_time_label"] = format_jp_time(row.get("arrive_at"))
        row["depart_date_label"] = format_jp_date_from_datetime(row.get("depart_at"))
        row["duration_label"] = format_duration(row.get("depart_at"), row.get("arrive_at"))
    return render_template(
        "flights.html",
        flights=flights_data,
    )


@app.route("/flights/<int:flight_id>/edit")
def flights_edit(flight_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    data = (
        sb.table(FLIGHT_TABLE)
        .select(
            "id, airline, flight_no, depart_airport, depart_at, arrive_airport, arrive_at, "
            "reservation_code, seat, terminal, gate, notes, created_at"
        )
        .eq("id", flight_id)
        .eq("trip_id", trip["id"])
        .execute()
        .data
    )
    if not data:
        return redirect(url_for("flights"))
    return render_template("flights_edit.html", flight=data[0])


@app.post("/flights/<int:flight_id>/update")
def flights_update(flight_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    payload = {
        "airline": (request.form.get("airline") or "").strip(),
        "flight_no": (request.form.get("flight_no") or "").strip(),
        "depart_airport": (request.form.get("depart_airport") or "").strip(),
        "depart_at": request.form.get("depart_at") or None,
        "arrive_airport": (request.form.get("arrive_airport") or "").strip(),
        "arrive_at": request.form.get("arrive_at") or None,
        "reservation_code": (request.form.get("reservation_code") or "").strip(),
        "seat": (request.form.get("seat") or "").strip(),
        "terminal": (request.form.get("terminal") or "").strip(),
        "gate": (request.form.get("gate") or "").strip(),
        "notes": (request.form.get("notes") or "").strip(),
    }
    has_any = any(
        payload.get(key)
        for key in [
            "airline",
            "flight_no",
            "depart_airport",
            "depart_at",
            "arrive_airport",
            "arrive_at",
            "reservation_code",
            "seat",
            "terminal",
            "gate",
            "notes",
        ]
    )
    if has_any:
        sb.table(FLIGHT_TABLE).update(payload).eq("id", flight_id).eq("trip_id", trip["id"]).execute()
    return redirect(url_for("flights"))


@app.post("/flights/<int:flight_id>/delete")
def flights_delete(flight_id):
    sb = get_supabase()
    trip = get_active_trip(sb)
    if not trip:
        return redirect(url_for("trips"))
    sb.table(FLIGHT_TABLE).delete().eq("id", flight_id).eq("trip_id", trip["id"]).execute()
    return redirect(url_for("flights"))


if __name__ == "__main__":
    app.run(debug=True, port=5002)

