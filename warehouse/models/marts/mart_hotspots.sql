-- Where crashes concentrate along a route: every occupied (route, per-mile bin,
-- regime), with the bin's crash count compared to its route's per-mile average
-- under that regime.
--
--   route_average       = route crashes (this regime) / route length in miles
--   concentration_ratio = bin crashes / route_average
--   is_hotspot          = ratio >= 1.5 AND bin count >= 8   (below 8 it's noise)
--
-- The average uses the whole route length (route_lengths seed), NOT just the
-- occupied bins, so an empty stretch of road correctly dilutes the average and
-- a genuinely busy mile stands out. That is why no zero-crash grid is
-- materialized: the denominator is a length, not a row count (ADR-0007).
--
-- Bins are only as good as the crash GPS behind them and the mile edges are
-- arbitrary, so the >= 8 floor and the caveat the UI shows both still apply.

with patterns as (
    select * from {{ ref('mart_crash_patterns') }}
),

route_totals as (
    select
        patterns.route_id,
        patterns.weather_regime,
        sum(patterns.crash_count)                              as route_crash_count,
        max(route_lengths.length_miles)                        as route_length_miles,
        sum(patterns.crash_count) / max(route_lengths.length_miles) as route_average
    from patterns
    join {{ ref('route_lengths') }} as route_lengths
        on route_lengths.route_id = patterns.route_id
    group by patterns.route_id, patterns.weather_regime
),

top_causes as (
    select route_id, mile_bin, weather_regime, cause as top_cause
    from {{ ref('mart_pattern_causes') }}
    where cause_rank = 1
)

select
    patterns.route_id,
    patterns.mile_bin,
    patterns.weather_regime,
    patterns.crash_count,
    patterns.bin_lat,
    patterns.bin_lon,
    route_totals.route_crash_count,
    round(route_totals.route_length_miles::numeric, 2)    as route_length_miles,
    case
        when route_totals.route_average > 0
            then round((patterns.crash_count / route_totals.route_average)::numeric, 2)
        else 0
    end as concentration_ratio,
    (
        route_totals.route_average > 0
        and patterns.crash_count / route_totals.route_average >= 1.5
        and patterns.crash_count >= 8
    ) as is_hotspot,
    top_causes.top_cause
from patterns
join route_totals
    on route_totals.route_id = patterns.route_id
    and route_totals.weather_regime = patterns.weather_regime
left join top_causes
    on top_causes.route_id = patterns.route_id
    and top_causes.mile_bin = patterns.mile_bin
    and top_causes.weather_regime = patterns.weather_regime
