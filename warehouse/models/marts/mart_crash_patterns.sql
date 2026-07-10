-- The product's central mart: for each (route, per-mile bin, weather regime),
-- what does the crash record actually say? Counts and dates only. The fatality
-- share is stated once as a number, and small samples are flagged rather than
-- hidden (the UI must show the caveat; ADR-0005). A representative point (the
-- mean crash location in the bin) lets the map draw the bin without recomputing
-- the polyline.
--
-- Grain is (route_id, mile_bin, weather_regime). Crashes with no mile_bin (spur
-- routes, or points off the polyline) carry no per-mile position, so they are
-- excluded here and a per-mile query for them answers honestly empty (ADR-0007).

-- Aggregate once; "fatal" is defined in exactly one place (fatal_count), and
-- pct_fatal / small_sample derive from the counts rather than re-scanning.
with binned as (
    select
        route_id,
        mile_bin,
        weather_regime,
        count(*)                                              as crash_count,
        count(*) filter (
            where num_killed > 0 or severity ilike '%fatal%'
        )                                                     as fatal_count,
        avg(lat)                                              as bin_lat,
        avg(lon)                                              as bin_lon,
        min(collision_datetime)::date                         as first_crash_date,
        max(collision_datetime)::date                         as last_crash_date
    from {{ ref('mart_crash_conditions') }}
    where mile_bin is not null
    group by route_id, mile_bin, weather_regime
)

select
    route_id,
    mile_bin,
    weather_regime,
    crash_count,
    fatal_count,
    round(100.0 * fatal_count / crash_count, 1)           as pct_fatal,
    bin_lat,
    bin_lon,
    first_crash_date,
    last_crash_date,
    crash_count < 8                                       as small_sample
from binned
