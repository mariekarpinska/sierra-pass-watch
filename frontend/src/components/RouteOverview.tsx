import L from 'leaflet'
import { TOWNS, townMile, type Route } from '../lib/data'
import { useReveal } from '../lib/useReveal'
import { useLeafletMap } from '../lib/useLeafletMap'

interface Props {
  route: Route
}

export function RouteOverview({ route }: Props) {
  const sectionRef = useReveal<HTMLElement>(route)

  const mapEl = useLeafletMap({
    mapOptions: { scrollWheelZoom: false, zoomControl: true },
    deps: [route],
    draw: (layer, map) => {
      const line = L.polyline(route.path, { color: '#E0A94A', weight: 5, opacity: 0.95, lineCap: 'round' }).addTo(layer)
      L.polyline(route.path, { color: '#ECE3CE', weight: 5, opacity: 0.28, dashArray: '1 12', lineCap: 'round' }).addTo(layer)
      route.order.forEach((i, pos) => {
        const t = TOWNS[i]
        const isStart = pos === 0
        const isEnd = pos === route.order.length - 1
        const color = isStart ? '#9DB183' : isEnd ? '#E0A94A' : '#7FA6B4'
        L.circleMarker([t.lat, t.lng], {
          radius: isStart || isEnd ? 9 : 6,
          color: '#151912',
          weight: 2.5,
          fillColor: color,
          fillOpacity: 1,
        })
          .addTo(layer)
          .bindPopup(
            `<span class="pop-h">${t.id}</span><div class="pop-row"><span>Mile ${Math.round(townMile(route, i))}</span><b>${t.el.toLocaleString()} ft</b></div>`,
          )
      })
      map.fitBounds(line.getBounds().pad(0.18))
    },
  })

  const start = TOWNS[route.startIdx]
  const end = TOWNS[route.endIdx]
  const peak = Math.max(...route.order.map((i) => TOWNS[i].el))
  const stats: Array<[string, string]> = [
    ['Distance', `${Math.round(route.totalMiles)} mi`],
    ['Waypoints', `${route.order.length} stops`],
    ['High point', `${peak.toLocaleString()} ft`],
    ['Est. drive', `${Math.round((route.totalMiles / 42) * 60 + route.order.length * 3)} min`],
  ]

  return (
    <section className="route-overview" ref={sectionRef}>
      <div className="overview-panel">
        <span className="kicker">Your passage</span>
        <h2>
          {start.id} <span className="arrow">→</span> {end.id}
        </h2>
        <div className="route-stats">
          {stats.map(([label, value]) => (
            <div className="stat" key={label}>
              <b>{value}</b>
              <span>{label}</span>
            </div>
          ))}
        </div>
        <p className="overview-note">
          Distances and mile-markers below are measured along this line. Everything that follows —
          weather, history, hotspots — is filtered to <em>this</em> route only.
        </p>
      </div>
      <div className="overview-map">
        <div ref={mapEl} className="map map-route" />
        <div className="map-legend map-legend-route">
          <span><i className="dot dot-start"></i> Start</span>
          <span><i className="dot dot-stop"></i> Waypoint</span>
          <span><i className="dot dot-end"></i> Destination</span>
        </div>
      </div>
    </section>
  )
}
