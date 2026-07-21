-- Grain guard: mart_incident_conditions must hold exactly one row per collision
-- cluster (route_id, mile_bin, and the hour of the collision). The dedup in the
-- mart is supposed to guarantee this; a singular test (returns the offending
-- rows) fails the build the moment two updates for the same collision survive.
select route_id, mile_bin, date_trunc('hour', event_time) as event_hour, count(*) as n
from {{ ref('mart_incident_conditions') }}
group by route_id, mile_bin, date_trunc('hour', event_time)
having count(*) > 1
