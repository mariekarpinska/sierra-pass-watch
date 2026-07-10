-- Crash-point detail per route - what the map plots when a road is selected.
-- One row per crash, already regime-labelled, with its measure and per-mile
-- bin; no aggregation here so the map can filter client-side by regime. Unlike
-- the aggregate marts, this keeps crashes with a null bin too (a spur-route
-- crash still has a real lat/lon to plot).
--
-- A view, not a table (overriding the marts default): this only projects
-- columns out of mart_crash_conditions, so a table would store a second copy of
-- every crash row. The view reads the existing table instead - no duplicated
-- data, and the projection is cheap at this volume.
{{ config(materialized='view') }}

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
