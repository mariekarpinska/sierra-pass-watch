-- One row per crash: the crash, the anchor town it sits nearest to, its
-- per-mile bin, and the weather regime it happened in. Regime prefers what our
-- sensors recorded near the time of the crash, falling back to the report's
-- own description.
--
-- Two spatial grains meet here, and they are deliberately different (ADR-0007):
--   * mile_bin  - the crash's own position along the route (floor(measure_mi)).
--                 This is the grain the aggregate marts key on.
--   * segment_id - the nearest anchor town. Weather is only sampled at anchors
--                 (the public feeds are point queries), so the sensor-regime
--                 join has to happen at anchor grain, then attach to the crash.
--
-- Distance to the anchor is squared-degrees: ordering only, no need for
-- haversine to pick the nearest of a handful of towns on one road.

with crashes as (
    select * from {{ ref('stg_crashes') }}
),

segments as (
    select * from {{ ref('segments') }}
),

-- Attribute each crash to the nearest catalogue anchor ON ITS OWN ROUTE
-- (route_id was parsed from the report's road text at load time).
nearest_segment as (
    select
        crashes.*,
        segments.segment_id,
        segments.segment_name,
        row_number() over (
            partition by crashes.case_id
            order by power(crashes.lat - segments.lat, 2) + power(crashes.lon - segments.lon, 2)
        ) as segment_rank
    from crashes
    join segments on segments.route_id = crashes.route_id
),

attributed as (
    select * from nearest_segment where segment_rank = 1
),

-- What did our sensors say at that anchor, up to two hours before the crash?
-- (Two hours: readings are 5-min live / hourly backfill; beyond that the
-- reading says little about conditions at impact.)
with_sensor_regime as (
    select
        attributed.*,
        events.weather_regime as sensor_regime,
        events.event_timestamp as conditions_timestamp,
        row_number() over (
            partition by attributed.case_id
            order by events.event_timestamp desc
        ) as reading_rank
    from attributed
    left join {{ ref('stg_road_events') }} as events
        on events.segment_id = attributed.segment_id
        and events.event_timestamp
            between attributed.collision_datetime - interval '2 hour'
            and attributed.collision_datetime
)

select
    case_id,
    collision_datetime,
    lat,
    lon,
    route_id,
    direction,
    segment_id,
    segment_name,
    measure_mi,
    mile_bin,
    severity,
    collision_type,
    primary_factor,
    collided_with,
    lighting,
    day_of_week,
    num_injured,
    num_killed,
    -- The join key of the whole product: sensor label when we have one, report
    -- label otherwise, and an honest flag saying which it was.
    coalesce(sensor_regime, weather_regime) as weather_regime,
    case when sensor_regime is not null then 'sensor' else 'report' end as regime_source,
    conditions_timestamp
from with_sensor_regime
where reading_rank = 1
