-- Top three recorded causes per (route, per-mile bin, regime) - the "watch out
-- for these" data. Rank ties break alphabetically so rebuilds are
-- deterministic. Same per-mile grain and same null-bin exclusion as
-- mart_crash_patterns.

with cause_counts as (
    select
        route_id,
        mile_bin,
        weather_regime,
        primary_factor as cause,
        count(*) as crash_count
    from {{ ref('mart_crash_conditions') }}
    where mile_bin is not null
    group by route_id, mile_bin, weather_regime, primary_factor
),

ranked as (
    select
        *,
        row_number() over (
            partition by route_id, mile_bin, weather_regime
            order by crash_count desc, cause
        ) as cause_rank,
        sum(crash_count) over (
            partition by route_id, mile_bin, weather_regime
        ) as pattern_crash_count
    from cause_counts
)

select
    route_id,
    mile_bin,
    weather_regime,
    cause,
    crash_count,
    round(100.0 * crash_count / pattern_crash_count, 0)::int as cause_pct,
    cause_rank
from ranked
where cause_rank <= 3
