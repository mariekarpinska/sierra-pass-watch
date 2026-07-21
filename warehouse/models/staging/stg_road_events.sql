-- Thin lens over bronze road events. The pipeline writes typed columns, so
-- staging does no casting: it just fixes the column set downstream models
-- depend on and gives the readings a stable name.
--
-- This exposes the full reading on purpose, as the reusable interface to the
-- source. Only weather_regime and event_timestamp feed a mart today (the
-- sensor-regime join in mart_crash_conditions); chain_control, road_closed and
-- the raw sensor metrics are carried so a later road-conditions or weather mart
-- can select them without re-staging bronze. Marts pick what they need.

select
    segment_id,
    segment_name,
    route_id,
    lat,
    lon,
    event_timestamp,
    weather_regime,      -- labelled at ingest by pipeline/regime.py
    chain_control,
    road_closed,
    snowfall_rate_in_hr,
    visibility_miles,
    wind_gust_mph,
    surface_temp_c,
    seismic_mag,
    source               -- 'backfill' (weather history from the Open-Meteo archive)
from {{ source('bronze', 'raw_road_events') }}
