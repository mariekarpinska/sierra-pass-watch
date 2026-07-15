# 0010. Crash history at journey grain: compose the marts per request

**Status:** Accepted 2026-07-14

## Context

The warehouse stores the crash record at (route, per-mile bin, weather regime)
grain (ADR-0007). The UI's unit of display is a journey: a request-time set of
highways (the `via` legs of ADR-0009) under one weather regime. Something has
to bridge the two, and it has to answer two questions the marts do not
pre-answer: the totals across all of a journey's roads, and the top recorded
causes across them (per-bin top-3 lists cannot be summed into an honest
journey-level ranking, because everything below rank 3 is already gone).

The regime to match is also a choice. A drive can be clear in the foothills
and snowing at the pass; the record shown has to pick one label.

## Decision

One endpoint, `GET /api/crash-patterns?from=&to=&regime=`, composes the marts
per request. The journey is named by its towns, exactly like `/api/journey`;
the server resolves it against the same committed index, so the roads and the
mile span the drive covers on each road come from one place, never from
request input:

- the occupied bins inside the journey's leg spans under that regime from
  `mart_crash_patterns` (each with its rank-1 cause from
  `mart_pattern_causes`, for the map popup);
- the journey-level top causes with a GROUP BY over `mart_crash_conditions`,
  the one-row-per-crash mart, so the ranking sees every crash rather than
  per-bin survivors;
- totals (counts, fatality share, date bounds, the under-8 small-record flag)
  derived in code from the bins.

Leg spans are computed at build time (`build_journeys.leg_spans`): each
travelled road's span is the [first, last] mile bounded by the journey's own
anchor towns, projected onto the road's committed polyline - the same measure
axis the crash bins live on (ADR-0007). Both queries scope each road with one
`unnest` join over the legs; a leg without a span matches its whole corridor.

The frontend matches history against the **worst forecast regime along the
journey** (REGIME_CODES is ordered worst-first), stated plainly in the copy.
Exact regime equality, no "similar weather" blending: the classifier already
is the similarity function, one label on the forecast and on every crash.

This is the API's first database access since ADR-0009 deleted the last one.
Reads go through a small psycopg pool that opens on the first crash request,
so the app still boots (and every other endpoint works) without a database.
The driver is deliberately the sync one, with the endpoint declared `def` so
FastAPI runs it on a worker thread: async psycopg refuses Windows' default
Proactor event loop, so it would not run on a Windows dev machine, and two
tiny indexed reads gain nothing from being async.

## Alternatives considered

- **Precompute a journey-grain mart.** dbt could materialize crash patterns
  for every journey, but that is ~1,176 town pairs x 7 regimes rebuilt
  whenever the catalogue moves, to save two indexed queries per request. It
  also teaches the warehouse the UI's unit of display, which is the wrong
  direction of coupling.
- **A route x regime x cause mart for the causes panel.** Correct and simple,
  but the API must still sum it across the journey's routes per request, so
  it saves one GROUP BY over a few thousand rows at the cost of another model,
  tests and doc rows. Not worth a mart.
- **Sum `mart_pattern_causes` across bins.** No extra query, but wrong:
  the per-bin top-3 truncation biases the journey ranking.
- **Serve individual crashes for the map.** `mart_route_crashes` has the
  points, but the product's honest spatial resolution is the mile bin
  (ADR-0007): one mark per occupied mile stays readable and does not imply
  precision the linear referencing does not have.

## Consequences

- The record covers the stretch of each highway the journey actually drives,
  and the copy says so ("the stretch of each highway your route covers").
  Spans are anchor-bounded, which sets their limits: a road needs two anchor
  towns of the drive on it to have a span at all, so about half the legs (the
  sparse southern corridors especially) carry none and honestly fall back to
  the whole corridor - over-including is the safe direction for a crash
  record. The mile or two between a leg's last anchor and the actual
  interchange is likewise uncounted. If the fallback ever misleads, the fix is
  spans measured from the OSRM drive geometry instead of the anchors, at the
  cost of retaining that geometry through the build.
- One regime for the whole drive errs on the cautious side: snow at the pass
  shows the snow record for every leg, including legs forecast clear.
- The mock insight panel's elevation chart had no live data source (nothing in
  the stack measures elevation), so the live panel draws per-route crash
  density strips on the same mile axis instead.
- The API depends on Postgres for exactly one endpoint. If the database is
  down, the forecast still works and the crash sections degrade to a one-line
  note.
