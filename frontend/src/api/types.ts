/**
 * The API contract, mirrored from backend/api/schemas.py. camelCase, exactly as
 * it comes off the wire. Components import these types; the fetchers in
 * routes.ts / segments.ts return them.
 *
 * Deliberate contract rule: everything here is historical or descriptive. There
 * is no score, rating, or drive/do-not-drive field, and contract.test.ts guards
 * that on this side just as backend/tests/test_forbidden_keys.py does on the
 * server.
 */

/**
 * Weather regimes, ordered worst-first for display. ONE classifier
 * (pipeline/regime.py, imported by both the pipeline and the API) produces
 * these labels on the live forecast and on each historical crash;
 * shared/weather-regime-cases.json pins its behaviour case by case.
 */
export const REGIME_CODES = [
  "HEAVY_SNOW_LOW_VIS",
  "SNOW",
  "ICE_FREEZING",
  "HIGH_WIND",
  "RAIN_FOG_LOW_VIS",
  "CLEAR_DRY",
  "UNKNOWN",
] as const;

export type RegimeCode = (typeof REGIME_CODES)[number];

/** A forecast point / populated place along a route. */
export interface Town {
  name: string;
  lat: number;
  lon: number;
}

/** One tracked Sierra Nevada road, from the route catalogue (GET /api/routes). */
export interface Route {
  /** Canonical id, e.g. "I-80", "SR-120". */
  id: string;
  /** Crossing / corridor name, e.g. "Donner Pass". */
  name: string;
  /** Caltrans road number, for closure lookups. */
  roadNo: string;
  /** True if the pass closes seasonally. */
  seasonal: boolean;
  /** Short context shown in the UI. */
  note: string;
  /** Towns in travel order along the route. */
  towns: Town[];
}

/**
 * An anchor waypoint (GET /api/segments): a town where weather is sampled.
 * Crashes are located by per-mile bin (ADR-0007); the anchor is only the
 * weather point.
 */
export interface Segment {
  /** "{routeId}:{town-slug}", e.g. "I-80:donner-summit". */
  id: string;
  routeId: string;
  /** Human name, e.g. "Donner Summit". */
  name: string;
  lat: number;
  lon: number;
}

/** One forecast sample for a segment at a point in time. */
export interface ForecastPoint {
  validTimeUtc: string;
  temperatureF: number | null;
  windGustMph: number | null;
  snowfallRateInHr: number | null;
  visibilityMiles: number | null;
  /** Descriptive short text, e.g. "Snow". Never a judgement. */
  shortForecast: string | null;
  regime: RegimeCode;
}

/** Forecast for one segment over the requested window. */
export interface SegmentForecast {
  segment: Segment;
  /** Worst regime across `points`: what the journey view keys on. */
  regime: RegimeCode;
  points: ForecastPoint[];
}

/** GET /api/forecast?route=&from=&to= */
export interface ForecastResponse {
  routeId: string;
  fromSegmentId: string;
  toSegmentId: string;
  generatedAtUtc: string;
  segments: SegmentForecast[];
}
