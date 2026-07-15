-- Tiny, hand-readable bronze fixture for CI and local dbt verification.
-- Covers each interesting shape once:
--   * a snow cluster spread over three adjacent mile bins (44/45/46) where the
--     busiest (bin 44, 8 crashes incl. one fatal) sits exactly at the
--     small-sample threshold, so pct_fatal and the >= 8 flag are exercised
--     from both sides;
--   * a crash whose report says CLEAR but a sensor reading within 2 h says
--     SNOW, so regime_source = 'sensor' is exercised;
--   * a clear-weather crash in a different bin (small_sample = true);
--   * a second route so the per-route average has more than one road;
--   * a spur-route crash with a null measure, so the null-bin exclusion path
--     (present in route_crashes, absent from the per-mile marts) is exercised;
--   * one chain-control and one incident alert for the active-alerts view.
-- Idempotent: natural-key conflicts no-op.

insert into raw_road_events
    (segment_id, segment_name, route_id, lat, lon, event_timestamp, weather_regime,
     chain_control, road_closed, snowfall_rate_in_hr, visibility_miles, wind_gust_mph,
     surface_temp_c, seismic_mag, source)
values
    ('I-80:donner-summit', 'Donner Summit', 'I-80', 39.3163, -120.3208,
     '2026-01-10 05:30:00+00', 'SNOW', 'R2', null, 0.4, 2.0, 25.0, -3.0, null, 'backfill'),
    ('I-80:donner-summit', 'Donner Summit', 'I-80', 39.3163, -120.3208,
     '2026-01-10 06:30:00+00', 'HEAVY_SNOW_LOW_VIS', 'R2', null, 0.9, 0.3, 30.0, -5.0, null, 'backfill'),
    ('US-50:echo-summit', 'Echo Summit', 'US-50', 38.8124, -120.0307,
     '2026-01-10 06:00:00+00', 'CLEAR_DRY', null, null, 0.0, 10.0, 8.0, 4.0, null, 'live')
on conflict (segment_id, event_timestamp) do nothing;

insert into crashes
    (case_id, collision_datetime, lat, lon, route_id, direction, severity,
     collision_type, primary_factor, collided_with, primary_road, lighting,
     day_of_week, weather, road_surface, weather_regime, num_injured, num_killed, measure_mi)
values
    -- Donner Summit snow cluster, all in mile bin 44 (8 rows -> not small_sample).
    ('ci-1', '2026-01-09 07:10:00+00', 39.3170, -120.3300, 'I-80', 'EB', 'Injury',
     'Rear End', '22350 UNSAFE SPEED', 'Other Motor Vehicle', 'I-80 EASTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 2, 0, 44.10),
    ('ci-2', '2026-01-09 08:00:00+00', 39.3150, -120.3100, 'I-80', 'WB', 'Property Damage Only',
     'Sideswipe', 'UNSAFE SPEED', 'Guardrail', 'I-80 WESTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 0, 0, 44.20),
    ('ci-3', '2026-01-09 09:30:00+00', 39.3200, -120.3250, 'I-80', 'EB', 'Fatal',
     'Head-On', '21650 WRONG SIDE OF ROAD', 'Other Motor Vehicle', 'I-80 EB',
     'Dusk - Dawn', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 1, 1, 44.30),
    ('ci-4', '2026-01-09 10:00:00+00', 39.3180, -120.3220, 'I-80', 'EB', 'Injury',
     'Rear End', '21703 FOLLOWING TOO CLOSELY', 'Other Motor Vehicle', 'I-80 EASTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 1, 0, 44.40),
    ('ci-5', '2026-01-09 10:30:00+00', 39.3175, -120.3230, 'I-80', 'EB', 'Injury',
     'Rear End', '22350 UNSAFE SPEED', 'Other Motor Vehicle', 'I-80 EASTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 1, 0, 44.50),
    ('ci-6', '2026-01-09 11:00:00+00', 39.3168, -120.3240, 'I-80', 'WB', 'Injury',
     'Rear End', 'FOLLOWING TOO CLOSELY', 'Other Motor Vehicle', 'I-80 WESTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 1, 0, 44.60),
    ('ci-7', '2026-01-09 11:30:00+00', 39.3172, -120.3210, 'I-80', 'EB', 'Property Damage Only',
     'Sideswipe', 'UNSAFE LANE CHANGE', 'Other Motor Vehicle', 'I-80 EASTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 0, 0, 44.70),
    ('ci-8', '2026-01-09 12:00:00+00', 39.3169, -120.3205, 'I-80', 'EB', 'Injury',
     'Rear End', '22350 UNSAFE SPEED', 'Other Motor Vehicle', 'I-80 EASTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 1, 0, 44.80),
    -- Two lighter SNOW bins next door (45 and 46), so adjacent bins with
    -- different counts (and small_sample = true) exist alongside the dense one.
    ('ci-13', '2026-01-09 08:15:00+00', 39.3155, -120.3180, 'I-80', 'EB', 'Injury',
     'Rear End', 'UNSAFE SPEED', 'Other Motor Vehicle', 'I-80 EASTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 1, 0, 45.20),
    ('ci-14', '2026-01-09 08:45:00+00', 39.3150, -120.3150, 'I-80', 'WB', 'Property Damage Only',
     'Sideswipe', 'FOLLOWING TOO CLOSELY', 'Guardrail', 'I-80 WESTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 0, 0, 45.60),
    ('ci-15', '2026-01-09 09:10:00+00', 39.3145, -120.3120, 'I-80', 'EB', 'Injury',
     'Rear End', 'UNSAFE SPEED', 'Other Motor Vehicle', 'I-80 EASTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 1, 0, 46.10),
    ('ci-16', '2026-01-09 09:40:00+00', 39.3140, -120.3100, 'I-80', 'WB', 'Injury',
     'Rear End', 'UNSAFE LANE CHANGE', 'Other Motor Vehicle', 'I-80 WESTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 1, 0, 46.50),
    -- Sensor-window case: report says CLEAR, but two Donner Summit readings are
    -- within 2 h (05:30 SNOW, 06:30 HEAVY_SNOW_LOW_VIS). The latest wins, so
    -- regime_source = 'sensor' and weather_regime = HEAVY_SNOW_LOW_VIS. It sits
    -- in bin 44 but as its own (I-80, 44, HEAVY_SNOW_LOW_VIS) group, not part of
    -- the 8-crash SNOW cluster.
    ('ci-9', '2026-01-10 07:15:00+00', 39.3160, -120.3210, 'I-80', 'EB', 'Injury',
     'Rear End', 'UNSAFE SPEED', 'Other Motor Vehicle', 'I-80 EASTBOUND',
     'Dusk - Dawn', 'Saturday', 'CLEAR', 'Dry', 'CLEAR_DRY', 1, 0, 44.05),
    -- Clear-weather crash near Truckee, a different bin (small sample).
    ('ci-10', '2026-06-02 17:45:00+00', 39.3300, -120.1900, 'I-80', 'WB', 'Property Damage Only',
     'Rear End', 'FOLLOWING TOO CLOSELY', 'Other Motor Vehicle', 'I-80 WESTBOUND',
     'Daylight', 'Tuesday', 'CLEAR', 'Dry', 'CLEAR_DRY', 0, 0, 52.00),
    -- A second route so route-average math has more than one road.
    ('ci-11', '2026-01-09 07:40:00+00', 38.8130, -120.0300, 'US-50', 'WB', 'Injury',
     'Rear End', '22350 UNSAFE SPEED', 'Other Motor Vehicle', 'US-50 WESTBOUND',
     'Daylight', 'Friday', 'SNOWING', 'Snowy/Icy', 'SNOW', 1, 0, 40.00),
    -- Spur route (US-6 has no polyline): null measure -> null bin. Present in
    -- route_crashes, excluded from the per-mile marts (ADR-0007).
    ('ci-12', '2026-02-01 15:00:00+00', 37.3636, -118.3951, 'US-6', 'EB', 'Injury',
     'Rear End', 'UNSAFE SPEED', 'Other Motor Vehicle', 'US-6 EASTBOUND',
     'Daylight', 'Sunday', 'CLEAR', 'Dry', 'CLEAR_DRY', 1, 0, null)
on conflict (case_id) do nothing;

-- Alert fixtures. event_time is relative to now() so the 24-hour active-alerts
-- view always sees them in CI, whenever CI happens to run.
insert into alerts
    (alert_id, kind, category, route_id, segment_id, headline, detail,
     lat, lon, measure_mi, event_time, source)
values
    ('cc:I-80:CC Donner:R2:ci', 'CHAIN_CONTROL', 'STARTED', 'I-80', 'I-80:donner-summit',
     'Chain controls in effect (R2) on I-80 near Donner Summit', null,
     39.3163, -120.3208, 44.09, now() - interval '1 hour', 'caltrans'),
    ('chp:ci-collision', 'INCIDENT', 'COLLISION', 'I-80', 'I-80:donner-summit',
     'Collision reported on I-80 near Donner Summit', 'Two vehicles, right lane blocked',
     39.3172, -120.3215, 44.5, now() - interval '20 minute', 'chp')
on conflict (alert_id) do nothing;
