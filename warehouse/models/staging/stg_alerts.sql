-- Thin lens over bronze alerts (the near-real-time change stream, ADR-0008).
-- The alert consumer already writes a display-ready row (headline, category,
-- kind), so staging only fixes the column set and names it. The recency logic
-- that the API cares about lives in mart_active_alerts, not here.

select
    alert_id,
    kind,           -- 'CHAIN_CONTROL' | 'INCIDENT'
    category,       -- STARTED/ESCALATED/EASED/LIFTED | COLLISION/HAZARD/CLOSURE/OTHER
    route_id,
    segment_id,
    headline,
    detail,
    lat,
    lon,
    measure_mi,     -- distance along route for incidents (ADR-0007), else null
    event_time,     -- when it happened upstream (UTC)
    source,         -- 'caltrans' | 'chp'
    ingested_at
from {{ source('bronze', 'alerts') }}
