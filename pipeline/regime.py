"""The weather-regime classifier — the product's core labelling primitive.

Instead of judging conditions (a 0-100 number), we *name* them: every reading,
forecast hour and historical crash gets one label from REGIMES. "Crashes in
weather like today's" is then an equality join on that label — descriptive,
never a verdict.

Two entry points, one vocabulary:

* ``classify_conditions`` — numeric sensor/forecast fields. Used by the
  producer (live readings), the backfill (archive weather), and imported by
  the API for its forecast endpoint — one implementation everywhere. The
  golden contract ``shared/weather-regime-cases.json`` pins its behaviour
  case by case, asserted by both the pipeline and API test suites.
* ``classify_crash_report`` — the crash report's own self-reported WEATHER /
  road-surface text. Fallback labelling for crashes that predate our sensor
  history.

Thresholds are meteorological / traffic-safety lines — snowfall 0.5 in/hr,
visibility 0.5 mi and 1 mi, gusts 40 mph, road surface -4 °C (black ice),
chain control R1/R2/R3; docs/weather-regimes.md justifies each one.

Pure functions, no I/O — trivially unit-testable, importable anywhere.
"""
from __future__ import annotations

# Worst-first. Order is the tie-break: when several conditions hold at once
# (snowing onto a frozen road in a gale) the earliest matching regime wins.
REGIMES = [
    "HEAVY_SNOW_LOW_VIS",
    "SNOW",
    "ICE_FREEZING",
    "HIGH_WIND",
    "RAIN_FOG_LOW_VIS",
    "CLEAR_DRY",
    "UNKNOWN",
]

_CHAIN_LEVELS = {"R1", "R2", "R3"}


def classify_conditions(
    snowfall_rate_in_hr: float | None = None,
    visibility_miles: float | None = None,
    wind_gust_mph: float | None = None,
    surface_temp_c: float | None = None,
    chain_control: str | None = None,
) -> str:
    """Label one point-in-time set of readings with a weather regime.

    Any input may be None — sensors go offline and forecasts omit fields.
    Only the all-None case is UNKNOWN; otherwise absent fields simply can't
    trigger their rule (known-benign data reads as clear).
    """
    chains = (chain_control or "").upper() in _CHAIN_LEVELS
    if (
        snowfall_rate_in_hr is None
        and visibility_miles is None
        and wind_gust_mph is None
        and surface_temp_c is None
        and not chains
    ):
        return "UNKNOWN"

    snowing = snowfall_rate_in_hr is not None and snowfall_rate_in_hr >= 0.1
    heavy_snow = snowfall_rate_in_hr is not None and snowfall_rate_in_hr >= 0.5
    low_vis = visibility_miles is not None and visibility_miles < 0.5

    if heavy_snow and low_vis:
        return "HEAVY_SNOW_LOW_VIS"
    # Chain control up means snow on the road even when our sensors read dry.
    if snowing or chains:
        return "SNOW"
    if surface_temp_c is not None and surface_temp_c < -4.0:
        return "ICE_FREEZING"
    if wind_gust_mph is not None and wind_gust_mph > 40.0:
        return "HIGH_WIND"
    if visibility_miles is not None and visibility_miles < 1.0:
        return "RAIN_FOG_LOW_VIS"
    return "CLEAR_DRY"


def classify_crash_report(weather: str | None, road_surface: str | None) -> str:
    """Label a historical crash from its report's own text fields.

    CCRS gives free-ish text ("CLEAR", "SNOWING", "FOG/VISIBILITY") plus a
    road-surface description ("DRY", "WET", "SNOWY/ICY"). Report text can't
    distinguish heavy from light snow, so the snow regimes collapse to SNOW;
    fog and rain likewise share RAIN_FOG_LOW_VIS — same vocabulary, coarser
    resolution. Unrecognized or missing text is UNKNOWN, never guessed.
    """
    w = (weather or "").upper()
    r = (road_surface or "").upper()

    if "SNOW" in w or "SNOW" in r:
        return "SNOW"
    if "ICE" in w or "ICY" in w or "ICY" in r or "FREEZ" in w or "FREEZ" in r:
        return "ICE_FREEZING"
    if "FOG" in w or "VISIBILITY" in w or "MIST" in w:
        return "RAIN_FOG_LOW_VIS"
    # "SNOW/SHOWERS" style combos hit the SNOW rule first; plain showers land here.
    if "RAIN" in w or "SHOWER" in w or "WET" in r or "SLIPPERY" in r:
        return "RAIN_FOG_LOW_VIS"
    if "WIND" in w:
        return "HIGH_WIND"
    if "CLEAR" in w or "CLOUD" in w or "DRY" in r:
        return "CLEAR_DRY"
    return "UNKNOWN"
