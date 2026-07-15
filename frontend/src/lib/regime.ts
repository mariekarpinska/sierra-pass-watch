/**
 * Small regime helpers shared by the crash-history sections: which single
 * regime a journey's forecast amounts to, and how to say a regime in a
 * sentence.
 */
import { REGIME_CODES, type RegimeCode, type WaypointForecast } from '../api/types'

/**
 * The one regime the crash history is matched against: the worst forecast at
 * any stop along the drive. REGIME_CODES is ordered worst-first, so "worst"
 * is the lowest index. UNKNOWN sits last, so a single no-data town never
 * outranks a real forecast; only an all-UNKNOWN journey stays UNKNOWN.
 */
export function worstRegime(stops: WaypointForecast[]): RegimeCode {
  let worst: RegimeCode = 'UNKNOWN'
  for (const stop of stops) {
    if (REGIME_CODES.indexOf(stop.regime) < REGIME_CODES.indexOf(worst)) {
      worst = stop.regime
    }
  }
  return worst
}

/** How each regime reads inside a sentence ("history recorded in ... conditions"). */
const REGIME_PROSE: Record<RegimeCode, string> = {
  HEAVY_SNOW_LOW_VIS: 'heavy snow, low visibility',
  SNOW: 'snow',
  ICE_FREEZING: 'icy, freezing',
  HIGH_WIND: 'high wind',
  RAIN_FOG_LOW_VIS: 'rain and fog',
  CLEAR_DRY: 'clear, dry',
  UNKNOWN: 'unknown',
}

export function regimeProse(regime: RegimeCode): string {
  return REGIME_PROSE[regime]
}
