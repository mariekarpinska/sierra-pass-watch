-- Staged live collisions: the bronze `incidents` table, narrowed to what the
-- provisional mart needs and given the per-mile bin the crash marts key on.
--
-- Bronze already keeps one row per CHP incident id (ON CONFLICT), so this is a
-- thin lens: it derives mile_bin from measure_mi (floor, ADR-0007) and passes
-- the rest through. A collision off its route's polyline has a null measure and
-- so a null bin, and the mart drops it, exactly like a crash with no measure.

select
    incident_id,
    route_id,
    lat,
    lon,
    measure_mi,
    floor(measure_mi)::int as mile_bin,  -- the per-mile grain (ADR-0007), null off the line
    event_time,
    weather_regime,      -- fetched at collection, or filled by the incidents backfill
    observed_at
from {{ source('bronze', 'incidents') }}
where event_time is not null
