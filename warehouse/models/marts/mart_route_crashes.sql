-- Crash-point detail per route - what the map plots when a road is selected.
-- One row per crash, already regime-labelled, with its measure and per-mile
-- bin; no aggregation here so the map can filter client-side by regime. Unlike
-- the aggregate marts, this keeps crashes with a null bin too (a spur-route
-- crash still has a real lat/lon to plot).

select
    case_id,
    route_id,
    direction,
    segment_id,
    segment_name,
    lat,
    lon,
    measure_mi,
    mile_bin,
    collision_datetime,
    severity,
    weather_regime,
    regime_source,
    primary_factor,
    collision_type,
    num_injured,
    num_killed
from {{ ref('mart_crash_conditions') }}
