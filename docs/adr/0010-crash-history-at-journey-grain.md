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
and snowing at the pass; a single label for the whole drive would show the
pass's snow record for stretches forecast clear.

## Decision

One endpoint, `GET /api/crash-patterns?from=&to=&departure=`, composes the
marts per request, **matching each stretch of the drive to its own forecast**.
The journey is named by its towns and departure time, exactly like
`/api/journey`; the server resolves it against the same committed index and
samples the same forecast service, so the roads, the mile stretches and their
regimes all come from one place, never from request input:

- the occupied bins inside each stretch under that stretch's regime from
  `mart_crash_patterns` (each with its rank-1 cause from
  `mart_pattern_causes`, for the map popup);
- the journey-level top causes with a GROUP BY over `mart_crash_conditions`,
  the one-row-per-crash mart, so the ranking sees every crash rather than
  per-bin survivors;
- totals (counts, fatality share, date bounds, the under-8 small-record flag)
  derived in code from the bins.

The stretches come from the committed journey index
(`build_journeys.leg_anchor_miles`): each on-road anchor town's mile measure
along the road's committed polyline - the same measure axis the crash bins
live on (ADR-0007). Per request, `segment_legs` cuts each road at the
midpoints between its anchors and labels each piece with its nearest anchor's
departure-window regime; adjacent same-regime pieces merge, so a
uniform-forecast road stays one leg. A road with one anchor keeps its whole
corridor under that anchor's regime; a road with none keeps it under the
journey's worst regime (over-including is the safe direction for a crash
record). A stretch whose forecast is UNKNOWN matches nothing: presenting
data gaps as weather would be a guess. Both queries scope every stretch with
one `unnest` join over the legs.

Exact regime equality, no "similar weather" blending: the classifier already
is the similarity function, one label on the forecast and on every crash.
Each bin in the response carries the regime it was matched under, so the map
can say which weather a mark's history belongs to.

This is the API's first database access since ADR-0009 deleted the last one.
Reads go through a small psycopg pool that opens on the first crash request,
so the app still boots (and every other endpoint works) without a database.
The driver is deliberately the sync one: async psycopg refuses Windows'
default Proactor event loop, so it would not run on a Windows dev machine,
and two tiny indexed reads gain nothing from being async. The endpoint is
`async def` only for the forecast await; the store reads hop to the worker
threadpool explicitly, keeping the sync driver off the event loop.

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
- Per-stretch matching is more relevant than one worst label, but no longer
  uniformly cautious: a stretch forecast clear shows clear-weather history
  even with snow at the pass, and clear-weather slices can dominate the
  journey totals simply because most driving happens in clear weather. The
  copy owns this ("matched to its own forecast").
- The crash record now depends on the forecast as well as the database: the
  endpoint samples the same fixed-host Open-Meteo client as `/api/journey`,
  whose request usually pre-warms the 5-minute cache. An upstream failure
  degrades stops to UNKNOWN, which shrinks (or empties) the matched record
  rather than erroring.
- The mock insight panel's elevation chart had no live data source (nothing in
  the stack measures elevation), so the live panel draws per-route crash
  density strips on the same mile axis instead.
- The API depends on Postgres for exactly one endpoint. If the database is
  down, the forecast still works and the crash sections degrade to a one-line
  note.
