-- The near-real-time alert feed the API serves (ADR-0008): recent chain-control
-- transitions and CHP incidents, newest first.
--
-- This mart is a VIEW, not a table, on purpose. Every other mart is a batch
-- table rebuilt on the pipeline's schedule, but the alerts arrive on a
-- ~1-2-minute clock (the poll worker writes the bronze `alerts` table
-- continuously). A table would only be as fresh as the last `dbt run`; a view
-- reads bronze at query time, so `now()` below is evaluated per request and the
-- feed is always current. This is the one place the batch warehouse yields to
-- the real-time path.
{{ config(materialized='view') }}

with recent as (
    select *
    from {{ ref('stg_alerts') }}
    -- 24 hours: long enough that a chain-control change stays visible across a
    -- driver's planning window, short enough that the feed is "what is
    -- happening now", not a history (that lives in the bronze table).
    where event_time >= now() - interval '24 hour'
)

select
    alert_id,
    kind,
    category,
    route_id,
    segment_id,
    headline,
    detail,
    lat,
    lon,
    measure_mi,
    event_time,
    source,
    -- Ordering hint for the UI: a new chain control or collision outranks an
    -- easing or a lift. Kept as a number so the API sorts without re-deriving.
    case
        when kind = 'INCIDENT' and category = 'COLLISION'       then 1
        when kind = 'CHAIN_CONTROL' and category = 'STARTED'    then 2
        when kind = 'CHAIN_CONTROL' and category = 'ESCALATED'  then 2
        when kind = 'INCIDENT' and category = 'CLOSURE'         then 2
        when kind = 'INCIDENT' and category = 'HAZARD'          then 3
        else 4
    end as severity_rank,
    -- The most recent alert for each tracked location, so the API can collapse
    -- a noisy change log to "the current state here" when it wants to.
    row_number() over (
        partition by kind, route_id, segment_id
        -- alert_id breaks ties when two alerts share an event_time, so the flag
        -- is stable per request (this is a view, evaluated on every read).
        order by event_time desc, alert_id desc
    ) = 1 as is_latest_for_location
from recent
