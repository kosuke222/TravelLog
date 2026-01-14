from flask import Flask, render_template, request, redirect, url_for
from supabase import create_client, Client
from datetime import datetime, date
import os
import random
import uuid
import json
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")

PLACE_CATEGORIES = ["スポット", "レストラン", "居酒屋", "カフェ", "バー", "その他"]
LEGACY_CATEGORY_MAP = {
    "spot": "スポット",
    "restaurant": "レストラン",
    "izakaya": "居酒屋",
    "cafe": "カフェ",
}
ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "webp"}


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


@app.route("/")
def home():
    sb = get_supabase()
    schedules = (
        sb.table("schedules")
        .select("id, title, date, detail, created_at")
        .order("date", desc=False)
        .order("id", desc=True)
        .execute()
        .data
    )
    today = date.today()
    next_schedule = None
    for row in schedules:
        row_date = parse_date(row.get("date"))
        if row_date and row_date >= today:
            next_schedule = row
            break
    if not next_schedule:
        for row in schedules:
            if row.get("date"):
                next_schedule = row
                break
    if not next_schedule and schedules:
        next_schedule = schedules[0]
    return render_template("home.html", next_schedule=next_schedule)


@app.route("/games")
def games():
    return render_template("games_index.html")


@app.route("/games/memo", methods=["GET", "POST"])
def games_memo():
    sb = get_supabase()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()
        if title and body:
            sb.table("game_memos").insert(
                {"title": title, "body": body, "created_at": now_str()}
            ).execute()
        return redirect(url_for("games_memo"))

    memos = (
        sb.table("game_memos")
        .select("id, title, body, created_at")
        .order("id", desc=True)
        .execute()
        .data
    )
    return render_template("games_memo.html", memos=memos)


@app.post("/games/memo/<int:memo_id>/delete")
def games_memo_delete(memo_id):
    sb = get_supabase()
    sb.table("game_memos").delete().eq("id", memo_id).execute()
    return redirect(url_for("games_memo"))


@app.route("/games/lottery", methods=["GET", "POST"])
def games_lottery():
    sb = get_supabase()
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text:
            sb.table("lottery_items").insert(
                {"text": text, "created_at": now_str()}
            ).execute()
        return redirect(url_for("games_lottery"))

    draw = request.args.get("draw")
    result = None
    items = (
        sb.table("lottery_items")
        .select("id, text, created_at")
        .order("id", desc=True)
        .execute()
        .data
    )
    if draw and items:
        result = random.choice(items)["text"]
    return render_template("games_lottery.html", items=items, result=result)


@app.post("/games/lottery/<int:item_id>/delete")
def games_lottery_delete(item_id):
    sb = get_supabase()
    sb.table("lottery_items").delete().eq("id", item_id).execute()
    return redirect(url_for("games_lottery"))


@app.route("/places", methods=["GET", "POST"])
def places():
    sb = get_supabase()
    category = request.args.get("category", "all")
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        cat = normalize_category(request.form.get("category", "").strip())
        notes = request.form.get("notes", "").strip()
        place_id = request.form.get("place_id") or None
        address = request.form.get("address") or None
        lat = parse_float(request.form.get("lat"))
        lng = parse_float(request.form.get("lng"))
        photo_url = request.form.get("photo_url") or None
        rating = parse_float(request.form.get("rating"))
        user_ratings_total = request.form.get("user_ratings_total") or None
        website = request.form.get("website") or None
        phone = request.form.get("phone") or None
        google_url = request.form.get("google_url") or None
        opening_hours = request.form.get("opening_hours") or None
        if name or notes or address:
            place = (
                sb.table("places")
                .insert(
                    {
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
            google_photo_urls = parse_photo_urls(request.form.get("photo_urls"))
            photo_urls = upload_place_photos(sb, request.files.getlist("photos"))
            all_photo_urls = google_photo_urls + photo_urls
            if place_id and all_photo_urls:
                sb.table("place_photos").insert(
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
        sb.table("places")
        .select(
            "id, name, category, notes, place_id, address, lat, lng, "
            "photo_url, rating, user_ratings_total, website, phone, google_url, "
            "opening_hours, created_at"
        )
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
            sb.table("place_photos")
            .select("id, place_id, photo_url")
            .in_("place_id", place_ids)
            .order("id", desc=False)
            .execute()
            .data
        )
        for photo in photos:
            photos_by_place.setdefault(photo["place_id"], []).append(photo["photo_url"])
    for row in rows:
        if row.get("photo_url") and not photos_by_place.get(row["id"]):
            photos_by_place[row["id"]] = [row["photo_url"]]
        if photos_by_place.get(row["id"]):
            seen = set()
            unique = []
            for url in photos_by_place[row["id"]]:
                if url and url not in seen:
                    seen.add(url)
                    unique.append(url)
            photos_by_place[row["id"]] = unique
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
    data = (
        sb.table("places")
        .select(
            "id, name, category, notes, place_id, address, lat, lng, photo_url, "
            "rating, user_ratings_total, website, phone, google_url, opening_hours"
        )
        .eq("id", place_id)
        .execute()
        .data
    )
    if not data:
        return redirect(url_for("places"))
    data[0]["category"] = normalize_category(data[0].get("category"))
    photos = (
        sb.table("place_photos")
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
    )


@app.post("/places/<int:place_id>/update")
def places_update(place_id):
    sb = get_supabase()
    name = request.form.get("name", "").strip()
    category = normalize_category(request.form.get("category", "").strip())
    notes = request.form.get("notes", "").strip()
    place_google_id = request.form.get("place_id") or None
    address = request.form.get("address") or None
    lat = parse_float(request.form.get("lat"))
    lng = parse_float(request.form.get("lng"))
    photo_url = request.form.get("photo_url") or None
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
        sb.table("places").update(payload).eq("id", place_id).execute()
        google_photo_urls = parse_photo_urls(request.form.get("photo_urls"))
        photo_urls = upload_place_photos(sb, request.files.getlist("photos"))
        all_photo_urls = google_photo_urls + photo_urls
        if all_photo_urls:
            sb.table("place_photos").insert(
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
    sb.table("places").delete().eq("id", place_id).execute()
    return redirect(url_for("places"))


@app.route("/schedule", methods=["GET", "POST"])
def schedule():
    sb = get_supabase()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        schedule_date = request.form.get("date", "").strip()
        detail = request.form.get("detail", "").strip()
        place_id = request.form.get("place_id") or None
        address = request.form.get("address") or None
        lat = parse_float(request.form.get("lat"))
        lng = parse_float(request.form.get("lng"))
        photo_url = request.form.get("photo_url") or None
        rating = parse_float(request.form.get("rating"))
        user_ratings_total = request.form.get("user_ratings_total") or None
        website = request.form.get("website") or None
        phone = request.form.get("phone") or None
        google_url = request.form.get("google_url") or None
        opening_hours = request.form.get("opening_hours") or None
        if title or schedule_date or detail or address:
            schedule_row = (
                sb.table("schedules")
                .insert(
                    {
                        "title": title or "予定",
                        "date": schedule_date,
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
                        "created_at": now_str(),
                    }
                )
                .execute()
                .data
            )
            schedule_id = schedule_row[0]["id"] if schedule_row else None
            google_photo_urls = parse_photo_urls(request.form.get("photo_urls"))
            photo_urls = upload_place_photos(sb, request.files.getlist("photos"))
            all_photo_urls = google_photo_urls + photo_urls
            if schedule_id and all_photo_urls:
                sb.table("schedule_photos").insert(
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

    schedules = (
        sb.table("schedules")
        .select(
            "id, title, date, detail, place_id, address, lat, lng, photo_url, "
            "rating, user_ratings_total, website, phone, google_url, opening_hours, created_at"
        )
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
    if schedule_ids:
        photos = (
            sb.table("schedule_photos")
            .select("id, schedule_id, photo_url")
            .in_("schedule_id", schedule_ids)
            .order("id", desc=False)
            .execute()
            .data
        )
        for photo in photos:
            photos_by_schedule.setdefault(photo["schedule_id"], []).append(photo["photo_url"])
    for row in schedules:
        if row.get("photo_url") and not photos_by_schedule.get(row["id"]):
            photos_by_schedule[row["id"]] = [row["photo_url"]]
        if photos_by_schedule.get(row["id"]):
            seen = set()
            unique = []
            for url in photos_by_schedule[row["id"]]:
                if url and url not in seen:
                    seen.add(url)
                    unique.append(url)
            photos_by_schedule[row["id"]] = unique
    return render_template(
        "schedule.html",
        upcoming_schedules=upcoming,
        past_schedules=past,
        photos_by_schedule=photos_by_schedule,
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
    )


@app.route("/schedule/<int:schedule_id>/edit")
def schedule_edit(schedule_id):
    sb = get_supabase()
    data = (
        sb.table("schedules")
        .select(
            "id, title, date, detail, place_id, address, lat, lng, photo_url, "
            "rating, user_ratings_total, website, phone, google_url, opening_hours"
        )
        .eq("id", schedule_id)
        .execute()
        .data
    )
    if not data:
        return redirect(url_for("schedule"))
    photos = (
        sb.table("schedule_photos")
        .select("id, schedule_id, photo_url")
        .eq("schedule_id", schedule_id)
        .order("id", desc=False)
        .execute()
        .data
    )
    return render_template("schedule_edit.html", schedule=data[0], photos=photos)


@app.post("/schedule/<int:schedule_id>/update")
def schedule_update(schedule_id):
    sb = get_supabase()
    title = request.form.get("title", "").strip()
    schedule_date = request.form.get("date", "").strip()
    detail = request.form.get("detail", "").strip()
    place_id = request.form.get("place_id") or None
    address = request.form.get("address") or None
    lat = parse_float(request.form.get("lat"))
    lng = parse_float(request.form.get("lng"))
    photo_url = request.form.get("photo_url") or None
    rating = parse_float(request.form.get("rating"))
    user_ratings_total = request.form.get("user_ratings_total") or None
    website = request.form.get("website") or None
    phone = request.form.get("phone") or None
    google_url = request.form.get("google_url") or None
    opening_hours = request.form.get("opening_hours") or None
    if title or schedule_date or detail or address:
        sb.table("schedules").update(
            {
                "title": title or "予定",
                "date": schedule_date,
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
        ).eq("id", schedule_id).execute()
        google_photo_urls = parse_photo_urls(request.form.get("photo_urls"))
        photo_urls = upload_place_photos(sb, request.files.getlist("photos"))
        all_photo_urls = google_photo_urls + photo_urls
        if all_photo_urls:
            sb.table("schedule_photos").insert(
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


@app.post("/schedule/<int:schedule_id>/delete")
def schedule_delete(schedule_id):
    sb = get_supabase()
    sb.table("schedules").delete().eq("id", schedule_id).execute()
    return redirect(url_for("schedule"))


@app.route("/memo", methods=["GET", "POST"])
def memo():
    sb = get_supabase()
    tab = request.args.get("tab", "all")
    if request.method == "POST":
        tab_name = request.form.get("tab_name", "").strip() or "未分類"
        body = request.form.get("body", "").strip()
        if body:
            sb.table("memos").insert(
                {
                    "tab_name": tab_name,
                    "body": body,
                    "created_at": now_str(),
                }
            ).execute()
        return redirect(url_for("memo", tab=tab_name))

    tabs_data = sb.table("memos").select("tab_name").execute().data
    tabs = sorted({row.get("tab_name") or "未分類" for row in tabs_data})
    query = sb.table("memos").select(
        "id, tab_name, body, created_at"
    ).order("id", desc=True)
    if tab != "all":
        query = query.eq("tab_name", tab)
    memos = query.execute().data
    for memo in memos:
        memo["tab_name"] = memo.get("tab_name") or "未分類"
    return render_template(
        "memo.html",
        memos=memos,
        tabs=tabs,
        active_tab=tab,
    )


@app.post("/memo/<int:memo_id>/delete")
def memo_delete(memo_id):
    sb = get_supabase()
    sb.table("memos").delete().eq("id", memo_id).execute()
    return redirect(url_for("memo"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
