import type { JourneyResponse } from '../api/types'
import { toSegmentCard } from '../lib/forecastAdapter'
import { WeatherIcon } from './WeatherIcon'
import { useReveal } from '../lib/useReveal'

const SEG_COLORS = ['#6E93A2', '#5E8C6A', '#C6902F', '#4E7E86', '#7E93A6', '#8FA05E']

interface Props {
  journey: JourneyResponse
}

// The departure the window started at, shown so the driver knows which slice of
// the day these conditions cover.
function departureLabel(iso: string): string {
  const when = new Date(iso)
  return when.toLocaleString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

// "128 min" as "2 hr 8 min" - the drive time reads better in hours.
function driveLabel(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? `${h} hr ${m} min` : `${m} min`
}

// A dash for a missing number, so a degraded (no-data) town never renders "null".
const num = (value: number | null): string => (value === null ? '-' : String(value))

export function WeatherSection({ journey }: Props) {
  const sectionRef = useReveal<HTMLElement>(journey)
  const cards = journey.stops.map(toSegmentCard)

  return (
    <section className="weather" ref={sectionRef}>
      <div className="section-head">
        <span className="kicker">Conditions along the way</span>
        <h2>Forecast along your route</h2>
        <p className="sub">
          About {Math.round(journey.totalMiles)} mi, {driveLabel(journey.totalMinutes)}. Conditions
          for the six hours from your departure ({departureLabel(journey.departureUtc)}), broken out
          by location so you can see where the drive changes character. Note: conditions in the
          Sierra shift in an instant. Always check official sources and use your own judgement.
        </p>
      </div>
      <div className="weather-grid">
        {cards.map((c, pos) => {
          const adverse = c.cond === 'Snow' || c.cond === 'Ice' || c.cond === 'Fog'
          return (
            <div className="wx-card" key={c.id} style={{ '--seg': SEG_COLORS[pos % SEG_COLORS.length] } as React.CSSProperties}>
              <div className="wx-loc">
                <b>{c.name}</b>
                <span className="mm">{c.regime.replace(/_/g, ' ')}</span>
              </div>
              <div className="wx-icon">
                <WeatherIcon cond={c.cond} size={44} />
              </div>
              <div className="wx-cond">{c.condLabel}</div>
              <div className="wx-temp">
                {num(c.hiT)}°<small> / {num(c.loT)}°F</small>
              </div>
              <div className="wx-meta">
                <div><span>Wind gust</span> {num(c.wind)} mph</div>
                <div><span>Visibility</span> {c.vis}</div>
                <div><span>Precip chance</span> {num(c.precip)}%</div>
              </div>
              {adverse && (
                <div className="wx-flag">
                  <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 3 L21 20 H3 Z" />
                    <path d="M12 10v4" />
                  </svg>{' '}
                  Plan extra time here
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
