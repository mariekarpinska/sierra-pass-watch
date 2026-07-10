# Weather regimes

The pipeline labels every live reading, backfilled hour, and historical crash
with one weather regime from a fixed vocabulary. "What does the crash record say
about weather like today's?" is then an equality join on that label.

## Why a named vocabulary

A fixed set of labels beats a numeric score on three counts.

- **Comparability.** Each reading and crash carries one label, so "conditions
  like now" is `WHERE weather_regime = :today`. There is no similarity metric and
  no query-time tuning.
- **Honesty.** A label claims only what the data supports. `SNOW` asserts that
  snow is falling or chains are up. A 0–100 score implies a calibrated risk axis
  with no ground truth behind it. Partial data resolves to `UNKNOWN`, never a
  confident wrong number.
- **Operational meaning.** State DOTs already report road weather as named tiers
  rather than scores. Each regime maps to a recognized action: chain up, slow for
  ice, watch for crosswind, slow for fog.

The cost is resolution. Two `SNOW` hours can differ. The raw numbers sit beside
every label so the category stays auditable.

State DOT road-condition schemes use the same idea. The New York Thruway reports
road status, pavement condition, and weather condition as defined tiers [NYTA].
Iowa DOT grades a scale from dry through partial coverage to ice with greatly
reduced traction [IADOT]. Wisconsin 511 uses five plain-language tiers [WISDOT].
Aggregate winter-storm indices exist (NWS WSSI, Sperry-Piltz SPIA) [WSSI][SPIA],
but they score a whole storm 1 to 5. This product labels point-in-time
conditions instead, because a crash joins to the weather at its moment and place,
not to a storm's overall severity.

## The vocabulary (worst first)

| Regime | Meaning | Rule (first match wins) |
|---|---|---|
| `HEAVY_SNOW_LOW_VIS` | heavy snowfall and you can't see | snowfall ≥ 0.5 in/hr **and** visibility < 0.5 mi |
| `SNOW` | active snow / chains required | snowfall ≥ 0.1 in/hr **or** chain control R1/R2/R3 |
| `ICE_FREEZING` | black-ice territory | road surface < −4 °C |
| `HIGH_WIND` | gusts that move a vehicle | gusts > 40 mph |
| `RAIN_FOG_LOW_VIS` | rain or fog cutting visibility | visibility < 1 mi |
| `CLEAR_DRY` | nothing above applies | everything known is benign |
| `UNKNOWN` | no data | every input null |

Rules evaluate in this order, so simultaneous conditions resolve to the worse
label. The order is defined once, here and in the classifier, because the API's
forecast labelling and the frontend's regime ordering both depend on it.

## What we measure

Five signals drive `classify_conditions`. Each is collected from whichever source
measures it best and converted to one unit inside its source module. Where a road
sensor and a model both report a field, the road sensor wins.

| Input | Unit | Primary source | Fallback | What it tells us |
|---|---|---|---|---|
| snowfall rate | in/hr | Open-Meteo `snowfall` | archive uses the same field | Active vs. heavy snow, the accumulation rate that outpaces tires, then plows |
| visibility | miles | RWIS `essVisibility` | Open-Meteo `visibility` | Sight distance at speed; separates whiteout and fog from merely snowing |
| wind gust | mph | RWIS `essMaxWindGustSpeed` | Open-Meteo gusts, then NWS | Gusts, not sustained wind, push high-profile vehicles across a lane |
| road surface temp | °C | RWIS `essSurfaceTemperature` | Open-Meteo `surface_temperature` (archive) | Pavement, not air, is the black-ice signal; the road can freeze while the air is above 0 |
| chain control | R1/R2/R3 | Caltrans CWWP2 | none | Ground truth: the DOT restricts only when snow or ice is on the road |

All five are nullable. RWIS stations and forecast fields drop out routinely, so
the classifier treats an absent field as "this rule cannot fire" and reserves
`UNKNOWN` for the all-null case. The dry/wet/ice/snow surface-state taxonomy these
sensors report follows the FHWA RWIS program [FHWA].

Two collected signals stay out of the weather regime. Seismic magnitude (USGS) is
a separate hazard axis and keeps its own column. Air temperature is kept for
context, but the ice rule reads surface temperature, because a road can freeze
while the air above it does not.

## Thresholds and their sources

Snow and visibility breaks follow published meteorological and DOT definitions.
The ice and wind breaks are operational engineering choices, marked as such. The
numbers live in one place and are pinned case-by-case by the golden contract.

- **Snow intensity by visibility.** The NWS defines snow intensity by visibility:
  light at 1 km or more, moderate between 0.5 and 1 km, heavy below 0.5 km
  [NWS-HS]. `HEAVY_SNOW_LOW_VIS` fires below 0.5 mi visibility with snowfall at or above
  0.5 in/hr. The half-mile line matches the NY Thruway's light-snow boundary
  (visibility above one half mile, or snowfall below one inch per hour) [NYTA].
- **Active snow.** `SNOW` fires at 0.1 in/hr or more, or on any Caltrans chain
  control (R1/R2/R3). Chain control is ground truth: Caltrans restricts only when
  snow or ice is on the road, so an active restriction forces at least `SNOW`
  even if the nearest point sensor reads dry.
- **Reduced visibility (rain or fog).** `RAIN_FOG_LOW_VIS` fires below 1 mi
  visibility. The AMS defines rain intensity by rate (light below 0.1 in/hr,
  moderate 0.1 to 0.3, heavy above 0.3) [AMS]. This regime keys on visibility
  rather than rate, because RWIS and the archive report visibility consistently
  for fog and rain while rate coverage is patchy.
- **Ice (engineering choice).** `ICE_FREEZING` fires below −4 °C pavement surface
  temperature. Water freezes at 0 °C, but brine, salt, and traffic friction
  depress the freezing point of thin road films. The −4 °C margin flags genuine
  black ice without alarming every time the road brushes 0.
- **Wind (engineering choice).** `HIGH_WIND` fires above 40 mph gusts. Gusts, not
  sustained wind, push trucks, trailers, and buses across a lane. 40 mph is an
  operational line for that hazard on exposed grades.

## Two classifiers, one vocabulary

| | `classify_conditions` | `classify_crash_report` |
|---|---|---|
| input | numeric sensor/forecast fields | the crash report's own WEATHER / road-surface text |
| used by | producer (live), backfill (archive), API (forecast) | crash loader |
| resolution | full vocabulary | coarser: text can't distinguish heavy from light snow (→ `SNOW`), or fog from rain (→ `RAIN_FOG_LOW_VIS`) |

Both live in [`pipeline/regime.py`](../pipeline/regime.py) as pure functions with
no I/O.

## The golden contract

`classify_conditions` labels live readings (producer), historical hours
(backfill), and the live forecast (the API imports the same module). One
implementation means no drift.
[`shared/weather-regime-cases.json`](../shared/weather-regime-cases.json) holds
the canonical (inputs → regime) cases, including every boundary. Both test suites
(pipeline and API) assert every case, so any behaviour change must update the
shared file. The JSON file is the spec; the table above is commentary.

## Known limits (see also [ADR-0006](adr/0006-data-plane.md))

- **Backfilled hours have no visibility.** The Open-Meteo archive doesn't publish
  it, so historical hours can't produce the two low-visibility regimes from
  numerics. Crash records still can, via their report text.
- **Crash-report text is self-reported** by the officer at the scene.
  `classify_crash_report` maps it conservatively and labels anything unrecognized
  `UNKNOWN` rather than guessing.
- **A regime is a label, not a measurement.** Two `SNOW` hours can differ. The UI
  shows the underlying numbers next to every chip so the label stays auditable.

## Sources

- **[NWS-HS]** NWS Glossary, "heavy snow": <https://forecast.weather.gov/glossary.php?word=heavy+snow>
- NWS technical paper, snow accumulation vs. visibility-derived intensity: <https://repository.library.noaa.gov/view/noaa/30378/noaa_30378_DS1.pdf>
- **[AMS]** AMS Glossary of Meteorology, "rain": <https://glossary.ametsoc.org/wiki/rain>
- **[NYTA]** New York State Thruway Authority, road/pavement/weather condition definitions: <https://www.thruway.ny.gov/travelers/map/wta-info>
- **[IADOT]** Iowa DOT, winter road condition categories: <https://iowadot.gov/travel-tools/iowa-511/about-winter-road-conditions>
- **[WISDOT]** Wisconsin DOT 511, winter road condition tiers: <https://wisconsindot.gov>
- **[FHWA]** FHWA Road Weather Information System (RWIS) FAQ: <https://ops.fhwa.dot.gov/weather/faq.htm>
- **[WSSI]** NWS Winter Storm Severity Index: <https://www.wpc.ncep.noaa.gov/wwd/wssi/wssi.php>
- **[SPIA]** Sperry-Piltz Ice Accumulation Index: <https://www.spia-index.com>
