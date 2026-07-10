-- Grain guard: mart_pattern_causes must hold one row per
-- (route_id, mile_bin, weather_regime, cause_rank).
select route_id, mile_bin, weather_regime, cause_rank, count(*) as n
from {{ ref('mart_pattern_causes') }}
group by route_id, mile_bin, weather_regime, cause_rank
having count(*) > 1
