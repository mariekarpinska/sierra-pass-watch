/* ============================================================
   SIERRA PASS WATCH - route awareness engine (typed, pure)
   Deterministic illustrative data, replaced by live sources
   feature by feature. What remains here backs the two sections
   that are still mockups (AlertBanner, RouteOverview) and dies
   with the branches that wire them. Not driving advice.
   ============================================================ */

/* ---------- deterministic RNG (mulberry32) ---------- */
export function rng(seed: number): () => number {
  let a = seed >>> 0
  return function () {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
export function hash(str: string): number {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/* ---------- types ---------- */
export type LatLng = [number, number]

export interface Town {
  id: string
  lat: number
  lng: number
  el: number
}

export type Condition =
  | 'Clear'
  | 'Partly Cloudy'
  | 'Cloudy'
  | 'Rain'
  | 'Fog'
  | 'Wind'
  | 'Snow'
  | 'Ice'

export type Cause =
  | 'Unsafe speed'
  | 'Head-on collision'
  | 'Object in road / off-road'
  | 'Improper turning'
  | 'Following too closely'
  | 'Impaired driving'

export interface Incident {
  segIdx: number
  tFrac: number
  lat: number
  lng: number
  cond: Condition
  cause: Cause
  year: number
}

export interface Route {
  startIdx: number
  endIdx: number
  order: number[]
  path: LatLng[]
  miles: number[]
  totalMiles: number
  estDriveMinutes: number
}

/* ---------- corridor: Highway 50 / Carson Pass ---------- */
/* Ordered west→east/south. Coordinates are approximate & illustrative. */
export const TOWNS: Town[] = [
  { id: 'Auburn', lat: 38.8966, lng: -121.0769, el: 1266 },
  { id: 'Placerville', lat: 38.7296, lng: -120.7985, el: 1867 },
  { id: 'Pollock Pines', lat: 38.7616, lng: -120.5863, el: 3934 },
  { id: 'Kyburz', lat: 38.7746, lng: -120.2996, el: 4222 },
  { id: 'Strawberry', lat: 38.7975, lng: -120.141, el: 5757 },
  { id: 'Kirkwood', lat: 38.6847, lng: -120.0655, el: 7800 },
  { id: 'South Lake Tahoe', lat: 38.9399, lng: -119.9772, el: 6237 },
]

/* extra shaping points so the drawn line follows terrain, not a ruler */
const BENDS: Record<string, LatLng[]> = {
  'Auburn|Placerville': [[38.858, -121.01], [38.792, -120.905], [38.748, -120.848]],
  'Placerville|Pollock Pines': [[38.742, -120.73], [38.76, -120.665]],
  'Pollock Pines|Kyburz': [[38.795, -120.51], [38.808, -120.42], [38.783, -120.345]],
  'Kyburz|Strawberry': [[38.786, -120.24], [38.799, -120.185]],
  'Strawberry|Kirkwood': [[38.812, -120.108], [38.76, -120.075], [38.705, -120.062]],
  'Kirkwood|South Lake Tahoe': [[38.72, -120.01], [38.82, -119.995], [38.876, -119.988]],
}

/* ---------- geo helpers ---------- */
export function haversine(a: LatLng, b: LatLng): number {
  const R = 3958.8
  const toR = Math.PI / 180
  const dLat = (b[0] - a[0]) * toR
  const dLng = (b[1] - a[1]) * toR
  const la1 = a[0] * toR
  const la2 = b[0] * toR
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

/* ---------- corridor segments ---------- */
export function segmentPath(fromIdx: number, toIdx: number): LatLng[] {
  const a = TOWNS[fromIdx]
  const b = TOWNS[toIdx]
  const key = `${a.id}|${b.id}`
  const keyRev = `${b.id}|${a.id}`
  const bends = BENDS[key] ? [...BENDS[key]] : BENDS[keyRev] ? [...BENDS[keyRev]].reverse() : []
  return [[a.lat, a.lng], ...bends, [b.lat, b.lng]]
}

export function segMiles(segIdx: number): number {
  const path = segmentPath(segIdx, segIdx + 1)
  let d = 0
  for (let p = 1; p < path.length; p++) d += haversine(path[p - 1], path[p])
  return d
}

/* ---------- historical incident dataset (deterministic) ---------- */
function buildIncidents(): Incident[] {
  const out: Incident[] = []
  for (let s = 0; s < TOWNS.length - 1; s++) {
    const path = segmentPath(s, s + 1)
    const a = TOWNS[s]
    const b = TOWNS[s + 1]
    const r = rng(hash(a.id + b.id))
    const elevAvg = (a.el + b.el) / 2
    // more history on higher, twistier segments
    const n = 8 + Math.floor(r() * 7) + Math.floor(elevAvg / 1600)
    for (let i = 0; i < n; i++) {
      // position along segment, biased into 1-2 clusters (hotspots)
      const clusterCenter = i % 3 === 0 ? 0.32 : i % 3 === 1 ? 0.68 : r()
      const t = Math.max(0.02, Math.min(0.98, clusterCenter + (r() - 0.5) * 0.22))
      // interpolate along path by segment fraction
      const fp = t * (path.length - 1)
      const pi = Math.floor(fp)
      const ft = fp - pi
      const p0 = path[Math.min(pi, path.length - 1)]
      const p1 = path[Math.min(pi + 1, path.length - 1)]
      const lat = lerp(p0[0], p1[0], ft) + (r() - 0.5) * 0.004
      const lng = lerp(p0[1], p1[1], ft) + (r() - 0.5) * 0.004
      // condition weighted by elevation (higher → more snow/ice/fog)
      const hi = Math.min(1, (elevAvg - 1200) / 6600)
      const roll = r()
      let cond: Condition
      if (roll < 0.3 + hi * 0.3) cond = r() < 0.5 ? 'Snow' : 'Ice'
      else if (roll < 0.5 + hi * 0.15) cond = r() < 0.5 ? 'Fog' : 'Rain'
      else if (roll < 0.72) cond = r() < 0.5 ? 'Cloudy' : 'Partly Cloudy'
      else if (roll < 0.9) cond = 'Clear'
      else cond = 'Wind'
      // cause weighted by condition
      const cr = r()
      let cause: Cause
      if (cond === 'Snow' || cond === 'Ice')
        cause = cr < 0.45 ? 'Unsafe speed' : cr < 0.7 ? 'Object in road / off-road' : cr < 0.85 ? 'Improper turning' : 'Following too closely'
      else if (cond === 'Fog' || cond === 'Rain')
        cause = cr < 0.4 ? 'Unsafe speed' : cr < 0.65 ? 'Head-on collision' : cr < 0.85 ? 'Following too closely' : 'Object in road / off-road'
      else
        cause = cr < 0.35 ? 'Unsafe speed' : cr < 0.55 ? 'Head-on collision' : cr < 0.72 ? 'Improper turning' : cr < 0.88 ? 'Impaired driving' : 'Following too closely'
      const year = 2015 + Math.floor(r() * 10)
      out.push({ segIdx: s, tFrac: t, lat, lng, cond, cause, year })
    }
  }
  return out
}
export const INCIDENTS: Incident[] = buildIncidents()

/* ---------- route computation ---------- */
// Drive-time model: corridor average speed plus a fixed dwell per waypoint.
const AVG_MPH = 42
const MINUTES_PER_STOP = 3

export function computeRoute(startIdx: number, endIdx: number): Route {
  const lo = Math.min(startIdx, endIdx)
  const hi = Math.max(startIdx, endIdx)
  const order: number[] = []
  for (let i = lo; i <= hi; i++) order.push(i)
  if (startIdx > endIdx) order.reverse()
  // full path + cumulative miles at each town
  const path: LatLng[] = []
  const miles: number[] = [0]
  let total = 0
  for (let k = 0; k < order.length - 1; k++) {
    const seg = segmentPath(Math.min(order[k], order[k + 1]), Math.max(order[k], order[k + 1]))
    const ordered = order[k] < order[k + 1] ? seg : [...seg].reverse()
    const startAt = k === 0 ? 0 : 1
    for (let p = startAt; p < ordered.length; p++) {
      if (path.length) total += haversine(path[path.length - 1], ordered[p])
      path.push(ordered[p])
    }
    miles.push(total)
  }
  const estDriveMinutes = Math.round((total / AVG_MPH) * 60 + order.length * MINUTES_PER_STOP)
  return { startIdx, endIdx, order, path, miles, totalMiles: total, estDriveMinutes }
}

/* mile marker at a town in the route */
export function townMile(route: Route, idx: number): number {
  const pos = route.order.indexOf(idx)
  return pos < 0 ? 0 : route.miles[pos]
}

/* incidents on the route regardless of weather (for the recent-alert pick) */
export function incidentsOnRoute(route: Route): Incident[] {
  const segs = new Set<number>()
  for (let k = 0; k < route.order.length - 1; k++) {
    segs.add(Math.min(route.order[k], route.order[k + 1]))
  }
  return INCIDENTS.filter((i) => segs.has(i.segIdx))
}
