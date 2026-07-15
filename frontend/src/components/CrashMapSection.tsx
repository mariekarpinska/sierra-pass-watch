import L from 'leaflet'
import type { CrashPatternsResponse, JourneyResponse } from '../api/types'
import { densestBin } from '../lib/hotspot'
import { regimeProse } from '../lib/regime'
import { useReveal } from '../lib/useReveal'
import { useLeafletMap } from '../lib/useLeafletMap'

interface Props {
  journey: JourneyResponse
  data: CrashPatternsResponse
}

// The day the forecast (and so the matched history) is for.
function dayLabel(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { weekday: 'long' })
}

/**
 * The crash record on a map: one marker per occupied mile of road (ADR-0007's
 * per-mile bins), sized by how much history sits in it. Bins, not individual
 * crashes, are drawn on purpose - the product's honest resolution is the mile,
 * and a single mark per mile stays readable where hundreds of points would
 * not. The basemap itself shows the roads; the journey's stops anchor the view.
 */
export function CrashMapSection({ journey, data }: Props) {
  const sectionRef = useReveal<HTMLElement>(journey)

  const mapEl = useLeafletMap({
    mapOptions: { scrollWheelZoom: false, center: [38.78, -120.4], zoom: 9 },
    deps: [data],
    draw: (layer, map) => {
      // The drive's densest mile (same definition the insight caption uses,
      // lib/hotspot.ts) gets the ochre treatment so it is findable here too.
      const top = densestBin(data.bins)
      data.bins.forEach((bin) => {
        const n = bin.crashCount
        const isTop = bin === top
        // Tuned by eye: dense corridors occupy most consecutive miles, so the
        // marks must stay small enough not to fuse into a band that hides the
        // route - a one-crash mark at radius 3.5, the cap at 10.75.
        const radius = 1 + Math.min(9.75, Math.sqrt(n) * 2.5)
        // calm: muted sage, size = density. no red. The densest mile alone
        // borrows the caption's ochre.
        const marker = L.circleMarker([bin.lat, bin.lon], {
          radius,
          color: isTop ? '#E0A94A' : '#C3D3A9',
          weight: isTop ? 2.5 : 1.5,
          fillColor: isTop ? '#E0A94A' : '#9DB183',
          fillOpacity: Math.min(0.55, 0.26 + n * 0.05),
          opacity: isTop ? 0.95 : 0.7,
        })
        const years = `${bin.firstCrashDate.slice(0, 4)}–${bin.lastCrashDate.slice(0, 4)}`
        marker.bindPopup(
          `<span class="pop-h">${n} crash${n > 1 ? 'es' : ''} in similar weather${isTop ? ' · densest on your drive' : ''}</span>
          <div class="pop-row"><span>Where</span><b>mile ${bin.mileBin} of ${bin.routeId}</b></div>
          <div class="pop-row"><span>Forecast here</span><b>${regimeProse(bin.regime)}</b></div>
          <div class="pop-row"><span>Most common</span><b>${bin.topCause ?? 'Unknown'}</b></div>
          <div class="pop-row"><span>Years</span><b>${years}</b></div>`,
        )
        marker.addTo(layer)
      })

      // Frame the whole drive: every stop plus every marked mile.
      const points: [number, number][] = [
        ...journey.stops.map((s): [number, number] => [s.waypoint.lat, s.waypoint.lon]),
        ...data.bins.map((b): [number, number] => [b.lat, b.lon]),
      ]
      if (points.length) map.fitBounds(L.latLngBounds(points).pad(0.2))
    },
  })

  return (
    <section className="crashmap" ref={sectionRef}>
      <div className="section-head">
        <span className="kicker">The map, remembered</span>
        <h2>Where similar days have asked for extra care</h2>
        <p className="sub">
          Each mark is a mile of your route with recorded crashes in weather like that stretch&apos;s
          own forecast. Larger, denser marks mean more history clustered there, nothing more. Read
          it as a place to ease off, not a warning to turn back.
        </p>
      </div>
      <div className="crashmap-wrap">
        <div ref={mapEl} className="map map-crash" />
        <aside className="crashmap-side">
          <div className="crashmap-count">
            <strong>{data.crashCount}</strong>
            <span>crashes on record</span>
          </div>
          <div className="crashmap-cond">
            Showing history recorded in the conditions forecast for each stretch of your drive
            on <b>{dayLabel(journey.departureUtc)}</b>.
          </div>
          <div className="scale-legend">
            <span className="scale-h">Mark size</span>
            <div className="scale-row"><i className="scale-dot s1"></i><em>a few</em></div>
            <div className="scale-row"><i className="scale-dot s2"></i><em>several</em></div>
            <div className="scale-row"><i className="scale-dot s3"></i><em>many</em></div>
            <div className="scale-row"><i className="scale-dot s2 densest"></i><em>densest on your drive</em></div>
          </div>
        </aside>
      </div>
    </section>
  )
}
