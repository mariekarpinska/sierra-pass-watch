# 0007. Spatial model: linear referencing + per-mile bins

**Status:** Accepted — 2026-07-09

## Context

"Where on this road do crashes concentrate?" needs a spatial grain. An
earlier sketch attributed each crash to its nearest catalogue town (a
waypoint catchment) — simple, but it can only ever answer "near Kirkwood",
never "two miles east of Kirkwood", and catchment sizes vary wildly with
town spacing.

Weather is a separate axis and stays at the town anchors on purpose: the
public weather sources (Open-Meteo, NWS, RWIS) are point queries, so
`raw_road_events` samples one reading per (route, town). Crashes, by
contrast, arrive with their own lat/lon, so they can carry a much finer
position — and that is where mile-level resolution belongs.

## Decision

One coordinate for the crash side of the product: **distance-along-route
(the measure)**.

- `pipeline/build_polylines.py` fetches each route's real driving geometry
  from OSRM once, projects the catalogue towns onto it, and commits the
  result (`shared/route-polylines.json`) — no build or deploy depends on
  OSRM being up.
- The crash loader (`pipeline/backfill.py`) linear-references every crash
  onto its route's polyline (700 m buffer) at load time and stores
  `measure_mi`; geometry lives in Python (`pipeline/polylines.py`,
  `pipeline/geo.py`), and SQL only ever sees a number.
- The **per-mile bin** — `floor(measure_mi)` — is the native crash grain the
  later marts (hotspots, cause taxonomies) will key on. A bin flags as a
  hotspot when it holds ≥ 1.5× its route's per-mile average under a regime
  AND ≥ 8 crashes.
- Towns are **anchors, not catchments**: labelled points at known measures,
  used for journey spans, forecast sampling and human labels ("≈2 mi E of
  Kirkwood"). Everything downstream derives from the same committed file.

Bronze keeps raw `lat`/`lon` on every crash, so `measure_mi` is a derived
convenience, not a loss of information — re-running the polyline builder can
recompute it without touching the source rows.

## Alternatives considered

- **Waypoint catchments** (the earlier sketch) — no code to write, but the
  grain is as coarse as town spacing, and "the record near {town}" and
  "where it concentrates" collapse into the same answer.
- **PostGIS** — `ST_LineLocatePoint` does linear referencing natively, but
  it drags a geometry extension into every environment (CI, Testcontainers,
  RDS) for one projection the loader does in ~40 lines of pure Python.
- **Map-matching each crash to OSM ways** — the precise answer, and far more
  machinery than the GPS scatter in public crash reports can justify.

## Consequences and owned trade-offs

- **Finer bins → smaller samples.** The ≥ 8 floor and the small-sample flag
  do more work than they did at waypoint grain; the UI must keep showing the
  caveat.
- **Bin edges are arbitrary.** A cluster straddling a mile boundary splits;
  ratios are per-bin, so a straddle can halve an apparent concentration.
- **Crash-coordinate accuracy bounds resolution.** Reports carry GPS scatter;
  the 700 m buffer accepts it, and sub-mile claims beyond the bin are not
  made anywhere in the product.
- **Four single-town spur routes have no polyline** (US-6, SR-207, SR-203,
  SR-158): no measure axis, no bins — their crash record stays at the route
  grain and any per-mile query answers honestly empty.
- **Route geometry provenance is OSRM/OSM.** Rerunning the builder can move a
  measure slightly; anchors and crashes are projected onto the SAME line, so
  labels stay consistent even if absolute measures drift.
- **Weather stays at anchors.** Mile bins are a crash-only concept; the
  forecast is sampled per anchor and a journey rolls up the bins between its
  start and end anchors.
