-- Thin lens over bronze road events. The pipeline writes typed columns, so
-- staging does no casting: it just fixes the column set downstream models
-- depend on and gives the readings a stable name.

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
    source               -- 'live' (Kafka consumer) or 'backfill'
from {{ source('bronze', 'raw_road_events') }}
