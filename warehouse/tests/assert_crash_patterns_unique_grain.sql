-- Grain guard: mart_crash_patterns must hold exactly one row per
-- (route_id, mile_bin, weather_regime). A singular test (returns the offending
-- rows) keeps us off the dbt_utils dependency for a one-line check.
select route_id, mile_bin, weather_regime, count(*) as n
from {{ ref('mart_crash_patterns') }}
group by route_id, mile_bin, weather_regime
having count(*) > 1
