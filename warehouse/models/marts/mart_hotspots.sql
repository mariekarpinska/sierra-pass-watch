-- Where crashes concentrate along a route: every occupied (route, per-mile bin,
-- regime), with the bin's crash count compared to the per-mile average of its
-- route's crash-bearing span under that regime.
--
--   covered_miles       = first to last occupied bin, inclusive (the active corridor)
--   route_average       = route crashes (this regime) / covered_miles
--   concentration_ratio = bin crashes / route_average
--   is_hotspot          = ratio >= 1.5 AND bin count >= 8   (below 8 it's noise)
--
-- The denominator is the crash-bearing span, NOT the full route length. Sierra
-- passes are mostly empty approach miles; averaging over the whole road drives
-- the per-mile average near zero and makes every populated bin look extreme, so
-- the ratio would never bind and is_hotspot would collapse to "count >= 8".
-- Measuring over the active corridor instead gives an honest "this mile has N
-- times the crashes of the typical mile where crashes actually happen on this
-- road" (ADR-0007). A lone cluster (one occupied bin) is its own average, so it
-- scores 1.0 and is not a relative hotspot; the raw crash_count is still exposed
-- for any "high volume" signal the UI wants independent of concentration.
--
-- The empty miles between clusters DO count toward covered_miles, so a gap
-- correctly dilutes the average; only the long approaches outside the span are
-- excluded. Route length for display (the route picker's "Distance") comes from
-- the route_lengths seed, not from this mart.

with patterns as (
    select * from {{ ref('mart_crash_patterns') }}
),

route_totals as (
    select
        route_id,
        weather_regime,
        sum(crash_count)                                    as route_crash_count,
        (max(mile_bin) - min(mile_bin) + 1)                 as covered_miles,
        sum(crash_count)::numeric
            / nullif(max(mile_bin) - min(mile_bin) + 1, 0)  as route_average
    from patterns
    group by route_id, weather_regime
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
    route_totals.covered_miles,
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
