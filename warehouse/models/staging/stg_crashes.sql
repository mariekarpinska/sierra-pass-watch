-- Staged crash records. Two jobs:
--
-- 1. Normalize the raw primary_factor text into a stable, human-readable cause
--    taxonomy. The mapping handles both CCRS vintages (California Vehicle Code
--    numbers like "22350" and violation text like "UNSAFE SPEED"). The
--    taxonomy is the vocabulary the whole product speaks: mart_pattern_causes
--    ranks these labels and the frontend maps them to cause-tied cautions.
--
-- 2. Derive the per-mile bin from measure_mi (ADR-0007). measure_mi is the
--    crash's distance along its route, set at load time; floor() of it is the
--    native spatial grain the crash marts key on. A null measure (spur route
--    with no polyline, or a point off the line) yields a null bin, and every
--    per-mile mart drops those rows so a per-mile query answers honestly empty
--    rather than inventing a location.

select
    case_id,
    collision_datetime,
    lat,
    lon,
    route_id,
    direction,
    severity,
    collision_type,
    case
        when upper(primary_factor) ~ '2235[0O]|UNSAFE SPEED'                          then 'Unsafe Speed'
        when upper(primary_factor) ~ '22107|UNSAFE TURN'                              then 'Unsafe Turn / No Signal'
        when upper(primary_factor) ~ '21658|UNSAFE LANE CHANGE|LANED ROADWAY'         then 'Unsafe Lane Change'
        when upper(primary_factor) ~ '23152|23153|DRIVING UNDER INFLUENCE|UNDER THE INFLUENCE' then 'DUI'
        when upper(primary_factor) ~ '21453|STEADY CIRCULAR RED|RED LIGHT|RED ARROW'  then 'Red Light Violation'
        when upper(primary_factor) ~ '21804|ENTERING OR CROSSING'                     then 'Failure to Yield (Entering Hwy)'
        when upper(primary_factor) ~ '21802|FAIL TO STOP AT STOP|STOP SIGN'           then 'Failure to Yield (Stop Sign)'
        when upper(primary_factor) ~ '21801'                                          then 'Failure to Yield (Left Turn)'
        when upper(primary_factor) ~ '21800|21803|FAIL.*YIELD|FAILURE.*YIELD'         then 'Failure to Yield (Intersection)'
        when upper(primary_factor) ~ '21703|FOLLOWING TOO CLOS'                       then 'Following Too Closely'
        when upper(primary_factor) ~ '22106|UNSAFE START'                             then 'Unsafe Start from Stopped'
        when upper(primary_factor) ~ '2175[0-9]|UNSAFE PASS'                          then 'Unsafe Passing'
        when upper(primary_factor) ~ '21650|21651|WRONG SIDE|WRONG WAY'               then 'Wrong Side of Road'
        when upper(primary_factor) ~ '22450|FAIL TO STOP AT SIGN|FAILING TO STOP'     then 'Stop Sign Violation'
        when upper(primary_factor) ~ 'UNSAFE BACK|BACKING'                            then 'Unsafe Backing'
        when upper(coalesce(primary_factor, '')) in ('UNKNOWN', 'OTHER', '')          then 'Unknown'
        else 'Other'
    end as primary_factor,
    collided_with,
    primary_road,
    lighting,
    day_of_week,
    weather,
    road_surface,
    weather_regime,      -- from the report's own text (classify_crash_report)
    num_injured,
    num_killed,
    measure_mi,                        -- distance along route in miles, or null
    floor(measure_mi)::int as mile_bin -- the per-mile crash grain (ADR-0007), null off the line
from {{ source('bronze', 'crashes') }}
where collision_datetime is not null
  and lat is not null
  and lon is not null
