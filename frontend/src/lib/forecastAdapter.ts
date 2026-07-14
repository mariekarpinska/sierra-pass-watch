/**
 * Bridges the API's forecast shape to what the weather card renders. The card
 * predates the live endpoint and speaks in a Condition enum plus a visibility
 * string; the API speaks in a regime label plus numbers. This adapter maps one
 * to the other in a single place, so the card component stays as it was and
 * nothing else has to know the API shape.
 *
 * Every numeric field can be null (a town degrades to no-data when Open-Meteo
 * is down), so the card formats them null-safely; here we only translate.
 */
import type { RegimeCode, WaypointForecast } from '../api/types'
import type { Condition } from './data'

export interface WaypointCard {
  id: string
  name: string
  regime: RegimeCode
  /** Drives the weather icon. */
  cond: Condition
  /** The words under the icon: the API's short text, or a regime fallback. */
  condLabel: string
  hiT: number | null
  loT: number | null
  wind: number | null
  vis: string
  precip: number | null
}

// The card icon set has no "unknown", so a no-data town shows a neutral cloud;
// its condLabel says "No data" and its numbers render as placeholders.
const REGIME_CONDITION: Record<RegimeCode, Condition> = {
  HEAVY_SNOW_LOW_VIS: 'Snow',
  SNOW: 'Snow',
  ICE_FREEZING: 'Ice',
  HIGH_WIND: 'Wind',
  RAIN_FOG_LOW_VIS: 'Fog',
  CLEAR_DRY: 'Clear',
  UNKNOWN: 'Cloudy',
}

function condition(stop: WaypointForecast): Condition {
  // Refine the regime's default with the short text where it adds detail the
  // regime label alone does not carry (rain vs fog, clear vs cloudy).
  const text = stop.shortForecast?.toLowerCase() ?? ''
  if (stop.regime === 'RAIN_FOG_LOW_VIS') {
    return text.includes('rain') || text.includes('drizzle') ? 'Rain' : 'Fog'
  }
  if (stop.regime === 'CLEAR_DRY') {
    if (text.includes('overcast')) return 'Cloudy'
    if (text.includes('partly')) return 'Partly Cloudy'
    return 'Clear'
  }
  return REGIME_CONDITION[stop.regime]
}

// Buckets a single visibility number into the qualitative range the card shows.
function visLabel(miles: number | null): string {
  if (miles === null) return '-'
  if (miles < 0.5) return 'under 0.5 mi'
  if (miles < 1) return '0.5-1 mi'
  if (miles < 3) return '1-3 mi'
  if (miles < 6) return '3-6 mi'
  return '6+ mi'
}

export function toWaypointCard(stop: WaypointForecast): WaypointCard {
  const cond = condition(stop)
  return {
    id: stop.waypoint.id,
    name: stop.waypoint.name,
    regime: stop.regime,
    cond,
    condLabel: stop.shortForecast ?? (stop.regime === 'UNKNOWN' ? 'No data' : cond),
    hiT: stop.temperatureHighF,
    loT: stop.temperatureLowF,
    wind: stop.windGustMph,
    vis: visLabel(stop.visibilityMiles),
    precip: stop.precipProbabilityPct,
  }
}
