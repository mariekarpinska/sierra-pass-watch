-- Grain guard: mart_hotspots must hold one row per
-- (route_id, mile_bin, weather_regime).
select route_id, mile_bin, weather_regime, count(*) as n
from {{ ref('mart_hotspots') }}
group by route_id, mile_bin, weather_regime
having count(*) > 1
