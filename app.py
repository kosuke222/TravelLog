from flask import Flask, render_template, request, redirect, url_for
from supabase import create_client, Client
from datetime import datetime, date
import os
import random
import uuid
import json
import re
from urllib.parse import unquote
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")

PLACE_CATEGORIES = ["スポット", "レストラン", "居酒屋", "カフェ", "その他"]
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
        schedule_date = (form.get(f"schedule_date_{index}") or "").strip()
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


@app.route("/")
def home():
    image_dir = os.path.join(app.static_folder, "img")
    image_files = []
    if os.path.isdir(image_dir):
        for name in os.listdir(image_dir):
            if name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                image_files.append(f"img/{name}")
    image_files.sort()
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
    # If there is no upcoming schedule, keep it empty.
    return render_template(
        "home.html",
        next_schedule=next_schedule,
        hero_images=image_files,
    )


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
        photo_url = normalize_photo_url(request.form.get("photo_url") or None)
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
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
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
        sb.table("places").update(payload).eq("id", place_id).execute()
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


@app.post("/places/photo/delete")
def places_photo_delete():
    sb = get_supabase()
    photo_id = request.form.get("photo_id") or None
    place_id = request.form.get("place_id") or None
    photo_url = request.form.get("photo_url") or None
    category = request.form.get("category") or "all"
    if photo_id and str(photo_id).isdigit():
        photo_id = int(photo_id)
    if place_id and str(place_id).isdigit():
        place_id = int(place_id)
    if photo_id:
        sb.table("place_photos").delete().eq("id", photo_id).execute()
    if place_id and photo_url:
        sb.table("place_photos").delete().eq("place_id", place_id).eq("photo_url", photo_url).execute()
        sb.table("places").update({"photo_url": None}).eq("id", place_id).eq(
            "photo_url", photo_url
        ).execute()
    return redirect(url_for("places", category=category))


@app.route("/schedule", methods=["GET", "POST"])
def schedule():
    sb = get_supabase()
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if request.method == "POST":
        schedule_entries = collect_schedule_entries(request.form, request.files)
        for entry in schedule_entries:
            schedule_row = (
                sb.table("schedules")
                .insert(
                    {
                        "title": entry["title"] or "??",
                        "date": entry["date"],
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
    posts_by_schedule = {}
    post_photos_by_post = {}
    if schedule_ids:
        photos = (
            sb.table("schedule_photos")
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
            sb.table("schedule_posts")
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
                sb.table("schedule_post_photos")
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
                    sb.table("schedule_photos").delete().in_("id", excess_ids).execute()
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
    return render_template(
        "schedule_edit.html",
        schedule=data[0],
        photos=photos,
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
    )


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
    photo_url = normalize_photo_url(request.form.get("photo_url") or None)
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


@app.post("/schedule/<int:schedule_id>/posts")
def schedule_post_create(schedule_id):
    sb = get_supabase()
    post_entries = collect_post_entries(request.form, request.files, prefix="post")
    if not post_entries:
        return redirect(url_for("schedule"))
    for entry in post_entries:
        post = (
            sb.table("schedule_posts")
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
            sb.table("schedule_post_photos").insert(
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
    sb.table("schedule_post_photos").delete().eq("post_id", post_id).execute()
    sb.table("schedule_posts").delete().eq("id", post_id).execute()
    return redirect(url_for("schedule"))


@app.post("/schedule/post/photo/delete")
def schedule_post_photo_delete():
    sb = get_supabase()
    photo_id = request.form.get("photo_id") or None
    post_id = request.form.get("post_id") or None
    photo_url = request.form.get("photo_url") or None
    if photo_id and str(photo_id).isdigit():
        photo_id = int(photo_id)
    if post_id and str(post_id).isdigit():
        post_id = int(post_id)
    if photo_id:
        sb.table("schedule_post_photos").delete().eq("id", photo_id).execute()
    if post_id and photo_url:
        sb.table("schedule_post_photos").delete().eq("post_id", post_id).eq(
            "photo_url", photo_url
        ).execute()
    return redirect(url_for("schedule"))


@app.post("/schedule/<int:schedule_id>/delete")
def schedule_delete(schedule_id):
    sb = get_supabase()
    sb.table("schedules").delete().eq("id", schedule_id).execute()
    return redirect(url_for("schedule"))


@app.post("/schedule/photo/delete")
def schedule_photo_delete():
    sb = get_supabase()
    photo_id = request.form.get("photo_id") or None
    schedule_id = request.form.get("schedule_id") or None
    photo_url = request.form.get("photo_url") or None
    if photo_id and str(photo_id).isdigit():
        photo_id = int(photo_id)
    if schedule_id and str(schedule_id).isdigit():
        schedule_id = int(schedule_id)
    if photo_id:
        sb.table("schedule_photos").delete().eq("id", photo_id).execute()
    if schedule_id and photo_url:
        sb.table("schedule_photos").delete().eq("schedule_id", schedule_id).eq(
            "photo_url", photo_url
        ).execute()
        sb.table("schedules").update({"photo_url": None}).eq("id", schedule_id).eq(
            "photo_url", photo_url
        ).execute()
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
