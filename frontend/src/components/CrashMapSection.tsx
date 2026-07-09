import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import { DAY_LABELS, routeIncidents, type Route, type RouteIncident, type Cause } from '../lib/data'
import { useReveal } from '../lib/useReveal'

const TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const TILE_OPTS: L.TileLayerOptions = {
  attribution: '&copy; OpenStreetMap &copy; CARTO',
  subdomains: 'abcd',
  maxZoom: 16,
}

interface Props {
  route: Route
  dayIdx: number
}

interface Cluster {
  lat: number
  lng: number
  items: RouteIncident[]
}

export function CrashMapSection({ route, dayIdx }: Props) {
  const sectionRef = useReveal<HTMLElement>(route)
  const mapEl = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)

  const { cond, similar, list } = useMemo(() => routeIncidents(route, dayIdx), [route, dayIdx])

  useEffect(() => {
    if (!mapEl.current) return
    if (!mapRef.current) {
      mapRef.current = L.map(mapEl.current, { scrollWheelZoom: false }).setView([38.78, -120.4], 9)
      L.tileLayer(TILE_URL, TILE_OPTS).addTo(mapRef.current)
    }
    const map = mapRef.current
    layerRef.current?.remove()
    const layer = L.layerGroup().addTo(map)
    layerRef.current = layer

    // route line, faint underneath
    L.polyline(route.path, { color: '#9DB183', weight: 3, opacity: 0.4 }).addTo(layer)

    // cluster incidents by rounded coordinate to size markers by density
    const clusters = new Map<string, Cluster>()
    list.forEach((inc) => {
      const key = `${inc.lat.toFixed(2)},${inc.lng.toFixed(2)}`
      const c = clusters.get(key) ?? { lat: 0, lng: 0, items: [] }
      c.items.push(inc)
      clusters.set(key, c)
    })
    clusters.forEach((c) => {
      const n = c.items.length
      const lat = c.items.reduce((s, i) => s + i.lat, 0) / n
      const lng = c.items.reduce((s, i) => s + i.lng, 0) / n
      const radius = 7 + Math.min(26, Math.sqrt(n) * 7)
      // calm: muted sage, size = density. no red.
      const m = L.circleMarker([lat, lng], {
        radius,
        color: '#C3D3A9',
        weight: 1.5,
        fillColor: '#9DB183',
        fillOpacity: Math.min(0.55, 0.26 + n * 0.05),
        opacity: 0.7,
      })
      const causeTally = new Map<Cause, number>()
      c.items.forEach((i) => causeTally.set(i.cause, (causeTally.get(i.cause) ?? 0) + 1))
      const topCause = [...causeTally.entries()].sort((a, b) => b[1] - a[1])[0][0]
      const miles = c.items.map((i) => i.mile)
      const years = c.items.map((i) => i.year)
      m.bindPopup(
        `<span class="pop-h">${n} incident${n > 1 ? 's' : ''} in similar weather</span>
        <div class="pop-row"><span>Mile range</span><b>${Math.min(...miles)}–${Math.max(...miles)}</b></div>
        <div class="pop-row"><span>Most common</span><b>${topCause}</b></div>
        <div class="pop-row"><span>Years</span><b>${Math.min(...years)}–${Math.max(...years)}</b></div>`,
      )
      m.addTo(layer)
    })

    map.fitBounds(L.polyline(route.path).getBounds().pad(0.2))
    const id = window.setTimeout(() => map.invalidateSize(), 200)
    return () => window.clearTimeout(id)
  }, [route, list])

  // tear the map down only on unmount
  useEffect(
    () => () => {
      mapRef.current?.remove()
      mapRef.current = null
    },
    [],
  )

  return (
    <section className="crashmap" ref={sectionRef}>
      <div className="section-head">
        <span className="kicker">The map, remembered</span>
        <h2>Where similar days have asked for extra care</h2>
        <p className="sub">
          Each mark is a recorded incident along your route in weather like your forecast. Larger,
          denser marks mean more history clustered there — nothing more. Read it as a place to ease
          off, not a warning to turn back.
        </p>
      </div>
      <div className="crashmap-wrap">
        <div ref={mapEl} className="map map-crash" />
        <aside className="crashmap-side">
          <div className="crashmap-count">
            <strong>{list.length}</strong>
            <span>incidents shown</span>
          </div>
          <div className="crashmap-cond">
            Showing history recorded in <b>{cond.toLowerCase()}-like</b> weather (
            {similar.join(', ').toLowerCase()}), matched to your forecast for{' '}
            <b>{DAY_LABELS[dayIdx].toLowerCase()}</b>.
          </div>
          <div className="scale-legend">
            <span className="scale-h">Cluster size</span>
            <div className="scale-row"><i className="scale-dot s1"></i><em>a few</em></div>
            <div className="scale-row"><i className="scale-dot s2"></i><em>several</em></div>
            <div className="scale-row"><i className="scale-dot s3"></i><em>many</em></div>
          </div>
        </aside>
      </div>
    </section>
  )
}
