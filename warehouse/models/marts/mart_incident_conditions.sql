-- One row per live CHP collision, at the grain (route_id, mile_bin,
-- weather_regime, event_time), with the weather it was collected in. This is
-- the PROVISIONAL companion to mart_crash_conditions (ADR-0012): CHP is
-- unofficial and thin, so it never feeds the authoritative crash marts.
--
-- Dedup, defence in depth. Bronze already keeps one row per CHP incident id,
-- but one physical collision can surface under more than one id (a re-filed
-- report, a nearby duplicate). So we collapse again to one row per collision:
-- earliest update within each (route, mile bin, hour) cluster. A crash off its
-- polyline has a null mile_bin and drops out of the per-mile story, exactly
-- like the CCRS marts.

with incidents as (
    select * from {{ ref('stg_incidents') }}
    where mile_bin is not null
),

-- Rank the updates in each collision cluster so the earliest wins. event_time
-- then incident_id is a total order, so the pick is stable between runs.
deduped as (
    select
        *,
        row_number() over (
            partition by route_id, mile_bin, date_trunc('hour', event_time)
            order by event_time, incident_id
        ) as cluster_rank
    from incidents
)

select
    incident_id,
    route_id,
    mile_bin,
    weather_regime,
    event_time,
    lat,
    lon,
    observed_at,
    -- Every row here is provisional; the column makes that explicit to the API
    -- and anything that reads the mart directly.
    'provisional' as data_grade
from deduped
where cluster_rank = 1
