# 0009. Multi-highway journeys: precompute routes with OSRM at build time

**Status:** 2026-07-11

## Context

A route in the catalogue is one highway (ADR-0007), and a forecast is a span of
towns within it. But a real Sierra trip crosses highways: Colfax to South Lake
Tahoe runs I-80, then SR-89, then US-50. The single-route picker cannot express
that, so the forecast stopped at the edge of one road.

To forecast a whole trip we need the ordered list of our weather anchors that
lie along the drive between any two towns. That is a routing problem, and the
catalogue does not encode where highways meet: only seven town names happen to
be shared across routes, and the real interchanges (Truckee, Meyers, the I-80 /
SR-89 split) are not all catalogue towns.

## Decision

Precompute journeys at build time with OSRM and commit the result, exactly as
`build_polylines.py` already does for per-route geometry.

`pipeline/build_journeys.py` asks the public OSRM server for the driving route
between every pair of the 49 catalogue towns, keeps the anchor towns that fall
within 2.5 mi of that route (reusing `geo.project_to_polyline`), and writes
`shared/route-journeys.json`. The API loads that file into memory like the route
catalogue; `GET /api/journey?from=&to=&departure=` is then a dictionary lookup
plus the same per-town window summary a single-route stop gets. No routing, no
OSRM call, and no database touch happens at request time.

## Alternatives considered

- **Hand-built junction graph.** Model interchanges as graph edges and run
  shortest-path at request time. This is the most work and the least accurate:
  the bulk is researching and encoding ~30-50 real interchanges (and the missing
  junction towns) by hand, it needs upkeep every time a route is added, and it
  still under-performs a real router. Re-implementing routing on hand-kept data
  is exactly the over-engineering the project avoids.
- **Runtime OSRM.** Call OSRM live per request. Flexible (any coordinate), but it
  puts an external dependency on the hot path and breaks the project's rule that
  build and deploy never depend on OSRM being up (the polylines are committed for
  the same reason).
- **Live routing in a keyed service (Mapbox/ORS).** This one has a real benefit
  precomputed OSRM cannot match: a commercial router knows about live closures
  and could route around a shut pass — a common Sierra winter event. It loses
  anyway because rerouting is not this product's job: we forecast conditions
  along the drive a driver plans, and a closure should surface as information
  (the pipeline already carries Caltrans chain control and CHP incidents,
  ADR-0008) rather than as a silently different route. Against that scoped-out
  benefit, it adds a paid dependency and an external call on the request path.
  To be candid about the keyless posture: this is a portfolio project, and
  keeping running costs at zero is its main driver — storing and rotating a
  key securely is a solved problem, not the obstacle.

## Consequences

- Runtime and CI stay OSRM-free and fast; the journeys are static data, so a
  deploy can never be broken by the router being down.
- The one-time build makes ~1,176 OSRM calls (throttled, ~130 KB committed). It
  is re-run by hand only when the catalogue's towns change, which is rare.
- Coverage is exactly the catalogue town pairs, which is all the picker offers.
  Arbitrary lat/lon origins are out of scope by design.
- Each pair is routed in one direction only; the reverse trip is the forward
  journey reversed, reusing its stops, miles and minutes. A return drive can
  differ in reality (one-way couplets, interchange ramps), but at the 2.5 mi
  anchor buffer those differences do not move which towns the drive passes,
  and OSRM's car profile would return near-identical durations anyway. If a
  reverse drive ever genuinely takes a different corridor, the fix is to
  build both directions (~2,352 calls instead of ~1,176), not to route live.
- The public OSRM demo server is fine for this build-time, run-rarely use; a
  heavier cadence would self-host OSRM. Noted, not a runtime concern.
- The frontend consumes only `/api/towns` and `/api/journey`; its single-route
  fetchers were deleted with the planner rewrite. `/api/routes`, `/api/segments`
  and `/api/forecast` were first kept for the crash-history branches, then
  removed (revising the earlier version of this note): those branches work at
  the per-mile-bin grain and define their own endpoints over the crash marts
  (ADR-0007), so nothing consumed the three — and with `/api/segments` went the
  API's only database read, so the connection pool went with it. The pipeline
  side (`analytics.segments`, the polylines and journey builders) is untouched;
  it feeds the marts the crash endpoints will read. The API serves exactly what
  the UI consumes, and each future feature brings back what it needs when it
  lands.
