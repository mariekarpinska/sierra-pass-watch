import { useEffect, useState } from 'react'
import L from 'leaflet'
import { getJourneyPath } from '../api/journeyPath'
import type { JourneyResponse } from '../api/types'
import { useReveal } from '../lib/useReveal'
import { useLeafletMap } from '../lib/useLeafletMap'

interface Props {
  journey: JourneyResponse
}

// The same explicit state machine CrashHistory (below) and the journey request
// in App.tsx use: the road line is loading, loaded, or failed - never an
// ambiguous null that stands for two of those at once. A loaded-but-empty
// `paths` is its own honest case: a drive that is all local spurs, with no
// mapped road line to draw.
type PathState =
  | { phase: 'loading' }
  | { phase: 'ok'; paths: [number, number][][] }
  | { phase: 'error' }

/**
 * "Your passage": the drive itself, before any weather or history. The map
 * draws the real road line (the committed route polylines sliced to the
 * journey's driven miles, from /api/journey-path) with the anchor towns that
 * everything below keys on; the panel gives the drive's vital numbers.
 * Deliberately free of crash data: this section says where you are going,
 * the sections after it say what the road remembers there.
 */
export function RouteOverview({ journey }: Props) {
  const sectionRef = useReveal<HTMLElement>(journey)
  // The road line arrives separately (it is a few thousand points, so it is
  // not part of the journey payload); the stops mark the map while it loads.
  const [pathState, setPathState] = useState<PathState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    setPathState({ phase: 'loading' })
    getJourneyPath(journey.fromId, journey.toId)
      .then((response) => {
        if (!cancelled) setPathState({ phase: 'ok', paths: response.paths })
      })
      .catch(() => {
        if (!cancelled) setPathState({ phase: 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [journey])

  const paths = pathState.phase === 'ok' ? pathState.paths : []

  const mapEl = useLeafletMap({
    mapOptions: { scrollWheelZoom: false, zoomControl: true },
    deps: [journey, pathState],
    draw: (layer, map) => {
      const points: [number, number][] = journey.stops.map((s) => [
        s.waypoint.lat,
        s.waypoint.lon,
      ])
      for (const path of paths) {
        L.polyline(path, { color: '#E0A94A', weight: 5, opacity: 0.95, lineCap: 'round' }).addTo(layer)
        L.polyline(path, { color: '#ECE3CE', weight: 5, opacity: 0.28, dashArray: '1 12', lineCap: 'round' }).addTo(layer)
        points.push(...path)
      }
      journey.stops.forEach((stop, pos) => {
        const isStart = pos === 0
        const isEnd = pos === journey.stops.length - 1
        const color = isStart ? '#9DB183' : isEnd ? '#E0A94A' : '#7FA6B4'
        const elevation =
          stop.waypoint.elevationFt != null
            ? `<div class="pop-row"><span>Elevation</span><b>${stop.waypoint.elevationFt.toLocaleString()} ft</b></div>`
            : ''
        L.circleMarker([stop.waypoint.lat, stop.waypoint.lon], {
          radius: isStart || isEnd ? 9 : 6,
          color: '#151912',
          weight: 2.5,
          fillColor: color,
          fillOpacity: 1,
        })
          .addTo(layer)
          .bindPopup(`<span class="pop-h">${stop.waypoint.name}</span>${elevation}`)
      })
      if (points.length) map.fitBounds(L.latLngBounds(points).pad(0.18))
    },
  })

  if (journey.stops.length === 0) return null
  const start = journey.stops[0].waypoint
  const end = journey.stops[journey.stops.length - 1].waypoint
  const elevations = journey.stops
    .map((s) => s.waypoint.elevationFt)
    .filter((e): e is number => e != null)
  const peak = elevations.length ? Math.max(...elevations) : null
  const stats: Array<[string, string]> = [
    ['Distance', `${Math.round(journey.totalMiles)} mi`],
    ['Waypoints', `${journey.stops.length} stops`],
    ['High point', peak !== null ? `${peak.toLocaleString()} ft` : '—'],
    ['Est. drive', `${journey.totalMinutes} min`],
  ]

  return (
    <section className="route-overview" ref={sectionRef}>
      <div className="overview-panel">
        <span className="kicker">Your passage</span>
        <h2>
          {start.name} <span className="arrow">→</span> {end.name}
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
          The line is the road your drive follows, and only the miles it follows. Everything on
          this page — the forecast above, the history below — is matched to <em>this</em> drive
          only.
        </p>
        {pathState.phase === 'error' && (
          <p className="route-hint">
            The road line could not be loaded right now; the stops still mark the drive.
          </p>
        )}
        {pathState.phase === 'ok' && pathState.paths.length === 0 && (
          <p className="route-hint">
            This drive stays on local roads we have no mapped line for; the stops still mark it.
          </p>
        )}
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
