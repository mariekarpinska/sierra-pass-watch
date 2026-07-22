-- Bronze layer: raw, append-only landing tables. dbt builds everything else.
-- Applied automatically by docker-compose on first start; idempotent by hand:
--   psql "$DATABASE_URL" -f pipeline/db/schema.sql

-- One row per (waypoint, timestamp) reading, written by the weather backfill
-- (historical hours from the Open-Meteo archive). The primary key is the
-- idempotency mechanism: re-running a backfill window can only ever no-op on
-- rows that already landed (INSERT .. ON CONFLICT DO NOTHING), so a re-run is
-- always safe.
create table if not exists raw_road_events (
    segment_id          text             not null,  -- "I-80:donner-summit"
    segment_name        text             not null,  -- "Donner Summit"
    route_id            text             not null,  -- "I-80"
    lat                 double precision not null,
    lon                 double precision not null,
    event_timestamp     timestamptz      not null,  -- when the reading was taken (UTC)
    weather_regime      text             not null,  -- labelled AT INGEST by pipeline/regime.py
    chain_control       text,                       -- R1/R2/R3, null = none active
    road_closed         boolean,
    snowfall_rate_in_hr double precision,
    visibility_miles    double precision,
    wind_gust_mph       double precision,
    surface_temp_c      double precision,
    seismic_mag         double precision,           -- strongest quake within 80 km, if any
    source              text             not null default 'live',  -- 'live' | 'backfill'
    ingested_at         timestamptz      not null default now(),
    primary key (segment_id, event_timestamp)
);

-- One row per CCRS crash report, loaded by the backfill. primary_factor is
-- the report's raw violation text — normalization into the cause taxonomy is
-- dbt's job (stg_crashes), so reloading never bakes in an old mapping.
create table if not exists crashes (
    case_id             text        primary key,
    collision_datetime  timestamptz not null,
    lat                 double precision not null,
    lon                 double precision not null,
    route_id            text        not null,       -- parsed from primary_road
    direction           text,                       -- NB/SB/EB/WB when stated
    severity            text        not null,       -- Fatal / Injury / Property Damage Only
    collision_type      text,
    primary_factor      text,                       -- raw violation text from the report
    collided_with       text,
    primary_road        text,
    lighting            text,
    day_of_week         text,
    weather             text,                       -- report's self-described weather
    road_surface        text,
    weather_regime      text        not null,       -- classify_crash_report(weather, surface)
    num_injured         integer     not null default 0,
    num_killed          integer     not null default 0,
    -- Distance-along-route in miles: the crash linear-referenced onto its
    -- route's polyline (shared/route-polylines.json, 700 m buffer). Null =
    -- spur route without a polyline, or a point off the line; such crashes
    -- still belong to the route but join no per-mile bin (ADR-0007).
    measure_mi          double precision,
    loaded_at           timestamptz not null default now()
);

-- Idempotent add for databases created before measure_mi existed.
alter table crashes add column if not exists measure_mi double precision;

create index if not exists idx_road_events_route on raw_road_events (route_id, event_timestamp);
create index if not exists idx_crashes_route_regime on crashes (route_id, weather_regime);

-- One row per live CHP collision the poll worker collected, with the weather
-- fetched for its exact point at the moment it was collected (ADR-0012). This
-- is the PROVISIONAL companion to the authoritative CCRS `crashes` table: CHP
-- is unofficial and thin (no severity / injury / cause), so it never feeds the
-- authoritative crash marts; it feeds mart_incident_conditions only.
--
-- incident_id is the idempotency key. One physical collision can emit several
-- CHP updates over its life; ON CONFLICT (incident_id) DO NOTHING keeps the
-- first one we saw, so the stored weather is the weather at first sighting.
-- weather_regime is 'UNKNOWN' (with the numeric fields left null) when the
-- on-collision weather fetch failed; `pipeline.backfill incidents` fills those
-- in later.
create table if not exists incidents (
    incident_id         text        primary key,   -- CHP Log id
    category            text        not null,       -- always COLLISION here
    type_text           text,                       -- raw CHP LogType
    route_id            text        not null,       -- tracked route, parsed from the feed
    lat                 double precision not null,
    lon                 double precision not null,
    measure_mi          double precision,           -- distance along route, null off the line
    event_time          timestamptz not null,       -- when the collision happened (UTC)
    weather_regime      text        not null,       -- classified at collection; UNKNOWN if the fetch failed
    snowfall_rate_in_hr double precision,
    visibility_miles    double precision,
    wind_gust_mph       double precision,
    surface_temp_c      double precision,
    source              text        not null default 'chp',
    observed_at         timestamptz not null default now(),  -- when the poller collected it
    ingested_at         timestamptz not null default now()
);

create index if not exists idx_incidents_route_time on incidents (route_id, event_time desc);

-- Alerts (feat/near-realtime-alerts): push-worthy road-state CHANGES, not readings.
-- One row per change (chains up/down, or a new CHP incident on a route).
-- alert_id is the idempotency key, so a re-emitted alert only ever no-ops,
-- exactly like (segment_id, event_timestamp) does for raw_road_events.
create table if not exists alerts (
    alert_id     text primary key,        -- "cc:I-80:CC Donner:R2:<ts>" | "chp:241001"
    kind         text             not null,  -- 'CHAIN_CONTROL' | 'INCIDENT'
    category     text,                       -- STARTED/ESCALATED/EASED/LIFTED | COLLISION/HAZARD/CLOSURE/OTHER
    route_id     text,                       -- tracked route, if attributable
    segment_id   text,                       -- nearest catalogue waypoint, if any
    headline     text             not null,  -- one line, ready to show or notify
    detail       text,
    lat          double precision,
    lon          double precision,
    measure_mi   double precision,           -- distance-along-route (incidents only)
    event_time   timestamptz      not null,  -- when it happened upstream (UTC)
    source       text             not null,  -- 'caltrans' | 'chp'
    ingested_at  timestamptz      not null default now()
);

create index if not exists idx_alerts_route_time on alerts (route_id, event_time desc);

-- Last-known state the poll worker diffs against to detect a CHANGE. One row
-- per tracked chain-control location, and per recently-seen CHP incident id.
-- The worker rewrites this table each cycle from pipeline/alerts.derive_alerts,
-- which drops incident keys past a TTL so it can't grow without bound.
create table if not exists road_alert_state (
    state_key    text primary key,          -- "cc:I-80:CC Donner" | "chp:241001"
    state_value  text        not null,       -- last-seen status, or first-seen timestamp
    updated_at   timestamptz not null default now()
);
