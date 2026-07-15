/**
 * The API contract, mirrored from backend/api/schemas.py. camelCase, exactly as
 * it comes off the wire. Components import these types; the fetchers in
 * towns.ts / journey.ts / crashPatterns.ts return them. The API serves exactly
 * what the UI consumes (ADR-0007, ADR-0009).
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

/**
 * A point where weather is sampled: a town or pass, with its coordinates. This
 * is all a forecast needs — every WaypointForecast wraps a Waypoint. The id is
 * the bare town slug (e.g. "donner-summit"), route-independent on purpose: a
 * journey crosses highways, so no single route owns a stop.
 */
export interface Waypoint {
  /** The town slug, e.g. "donner-summit". */
  id: string;
  /** Human name, e.g. "Donner Summit". */
  name: string;
  lat: number;
  lon: number;
}

/**
 * Forecast for one town over the departure window (a fixed number of hours from
 * the driver's start time). The values summarize that window so the card can
 * show conditions for the drive, not one instant: the worst regime, the
 * temperature range, and the roughest wind/visibility/precip any hour reaches.
 * Any field is null when no hour supplied it (e.g. the upstream was down).
 */
export interface WaypointForecast {
  waypoint: Waypoint;
  /** Worst regime across the window: what the card keys its condition on. */
  regime: RegimeCode;
  temperatureHighF: number | null;
  temperatureLowF: number | null;
  windGustMph: number | null;
  visibilityMiles: number | null;
  precipProbabilityPct: number | null;
  /** Descriptive short text for the worst hour, e.g. "Snow". Never a judgement. */
  shortForecast: string | null;
}

/**
 * One highway of a journey, with the catalogue's seasonal context so the UI
 * can warn when the trip crosses a pass that closes for the winter.
 */
export interface JourneyLeg {
  /** Route id, e.g. "SR-120". */
  id: string;
  /** Crossing / corridor name, e.g. "Tioga Pass". */
  name: string;
  /** True if the pass closes seasonally. */
  seasonal: boolean;
  /** Short context, e.g. "closed ~Nov-May". */
  note: string;
  /**
   * The [first, last] mile the drive covers on this road (the road's own mile
   * axis, ADR-0007), bounded by the journey's anchor towns at build time.
   * Null when the build could not bound it (fewer than two anchors on the
   * road, or a spur with no polyline); the crash record then covers the
   * road's whole corridor.
   */
  span: [number, number] | null;
}

/**
 * One recorded cause and its share of the matched crashes. `cause` is the
 * warehouse's normalized taxonomy label, e.g. "Unsafe Speed".
 */
export interface CauseStat {
  cause: string;
  crashCount: number;
  /** Share of all matched crashes, 0-100, whole number. */
  pct: number;
}

/**
 * One occupied per-mile bin (ADR-0007): mile `mileBin` of `routeId`, with what
 * the record says happened there under the requested regime. The lat/lon is
 * the mean crash location inside the bin: a representative point for the map,
 * not an exact crash site.
 */
export interface CrashBin {
  routeId: string;
  mileBin: number;
  lat: number;
  lon: number;
  crashCount: number;
  fatalCount: number;
  /** The bin's most common recorded cause. */
  topCause: string | null;
  /** ISO dates bounding this bin's record. */
  firstCrashDate: string;
  lastCrashDate: string;
}

/**
 * GET /api/crash-patterns?from=&to=&regime=
 *
 * The crash record for a journey under one weather regime: journey-level
 * totals, the occupied per-mile bins for the map, and the top recorded
 * causes. Scoped to the mile span the drive covers on each highway (a leg
 * with a null span keeps its whole corridor). Descriptive only, like
 * everything else in this contract.
 */
export interface CrashPatternsResponse {
  regime: RegimeCode;
  routeIds: string[];
  crashCount: number;
  fatalCount: number;
  /** 0-100, one decimal. Null when crashCount is 0. */
  pctFatal: number | null;
  /** True under 8 matched crashes: the UI must present the record as context,
   *  not a pattern. */
  smallSample: boolean;
  /** ISO dates bounding the whole matched record, null when it is empty. */
  firstCrashDate: string | null;
  lastCrashDate: string | null;
  bins: CrashBin[];
  topCauses: CauseStat[];
}

/**
 * GET /api/journey?from=&to=&departure= (may cross several highways).
 * The anchor towns along the OSRM-routed drive, each with the same
 * departure-window summary as a single-route stop, plus the highways
 * travelled (`via`), in order.
 */
export interface JourneyResponse {
  fromId: string;
  toId: string;
  via: JourneyLeg[];
  departureUtc: string;
  generatedAtUtc: string;
  totalMiles: number;
  totalMinutes: number;
  stops: WaypointForecast[];
}
