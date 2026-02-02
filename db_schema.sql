create table if not exists travel_trips (
  id bigserial primary key,
  name text not null,
  start_date date,
  end_date date,
  note text,
  created_at timestamp with time zone default now()
);

create table if not exists travel_trip_settings (
  id bigserial primary key,
  trip_id bigint references travel_trips(id) on delete cascade,
  warika_url text,
  updated_at timestamp with time zone default now(),
  unique (trip_id)
);

create table if not exists travel_places (
  id bigserial primary key,
  trip_id bigint references travel_trips(id) on delete cascade,
  name text,
  category text,
  notes text,
  place_id text,
  address text,
  lat double precision,
  lng double precision,
  photo_url text,
  rating double precision,
  user_ratings_total text,
  website text,
  phone text,
  google_url text,
  opening_hours text,
  created_at timestamp with time zone default now()
);

create table if not exists travel_place_photos (
  id bigserial primary key,
  place_id bigint references travel_places(id) on delete cascade,
  photo_url text,
  created_at timestamp with time zone default now()
);

create table if not exists travel_schedules (
  id bigserial primary key,
  trip_id bigint references travel_trips(id) on delete cascade,
  title text,
  date date,
  start_time time,
  end_time time,
  detail text,
  place_id text,
  address text,
  lat double precision,
  lng double precision,
  photo_url text,
  rating double precision,
  user_ratings_total text,
  website text,
  phone text,
  google_url text,
  opening_hours text,
  created_at timestamp with time zone default now()
);

create table if not exists travel_schedule_photos (
  id bigserial primary key,
  schedule_id bigint references travel_schedules(id) on delete cascade,
  photo_url text,
  created_at timestamp with time zone default now()
);

create table if not exists travel_schedule_posts (
  id bigserial primary key,
  schedule_id bigint references travel_schedules(id) on delete cascade,
  time text,
  title text,
  body text,
  created_at timestamp with time zone default now()
);

create table if not exists travel_schedule_post_photos (
  id bigserial primary key,
  post_id bigint references travel_schedule_posts(id) on delete cascade,
  photo_url text,
  created_at timestamp with time zone default now()
);

create table if not exists travel_memos (
  id bigserial primary key,
  trip_id bigint references travel_trips(id) on delete cascade,
  body text,
  created_at timestamp with time zone default now()
);

create table if not exists travel_hotels (
  id bigserial primary key,
  trip_id bigint references travel_trips(id) on delete cascade,
  name text,
  address text,
  map_url text,
  website_url text,
  checkin_date date,
  checkout_date date,
  notes text,
  created_at timestamp with time zone default now()
);

create table if not exists travel_hotel_photos (
  id bigserial primary key,
  hotel_id bigint references travel_hotels(id) on delete cascade,
  photo_url text,
  created_at timestamp with time zone default now()
);

create table if not exists travel_flights (
  id bigserial primary key,
  trip_id bigint references travel_trips(id) on delete cascade,
  airline text,
  flight_no text,
  depart_airport text,
  depart_at text,
  arrive_airport text,
  arrive_at text,
  reservation_code text,
  seat text,
  terminal text,
  gate text,
  notes text,
  created_at timestamp with time zone default now()
);
