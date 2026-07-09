import { TOWNS, DAY_LABELS, DAY_DATES, fmtDate, townMile, weatherFor, type Route } from '../lib/data'
import { WeatherIcon } from './WeatherIcon'
import { useReveal } from '../lib/useReveal'

const SEG_COLORS = ['#6E93A2', '#5E8C6A', '#C6902F', '#4E7E86', '#7E93A6', '#8FA05E']

interface Props {
  route: Route
  dayIdx: number
  onDayChange: (dayIdx: number) => void
}

export function WeatherSection({ route, dayIdx, onDayChange }: Props) {
  const sectionRef = useReveal<HTMLElement>(route)

  return (
    <section className="weather" ref={sectionRef}>
      <div className="section-head">
        <span className="kicker">Conditions along the way</span>
        <h2>Forecast along your route</h2>
        <p className="sub">
          Forecasts are broken out by location so you can see where the drive changes character.
          Pick a day to plan ahead. Note: Conditions in the Sierra shift in an instant. Always check
          official sources and use your own judgement.
        </p>
      </div>
      <div className="day-tabs" role="tablist" aria-label="Forecast day">
        {DAY_LABELS.map((label, i) => (
          <button
            key={label}
            className="day-tab"
            role="tab"
            aria-selected={i === dayIdx}
            onClick={() => onDayChange(i)}
          >
            <span>{label}</span>
            <small>{fmtDate(DAY_DATES[i])}</small>
          </button>
        ))}
      </div>
      <div className="weather-grid">
        {route.order.map((i, pos) => {
          const t = TOWNS[i]
          const w = weatherFor(t, dayIdx)
          const adverse = w.cond === 'Snow' || w.cond === 'Ice' || w.cond === 'Fog'
          return (
            <div className="wx-card" key={t.id} style={{ '--seg': SEG_COLORS[pos % SEG_COLORS.length] } as React.CSSProperties}>
              <div className="wx-loc">
                <b>{t.id}</b>
                <span className="mm">
                  MI {Math.round(townMile(route, i))} · {t.el.toLocaleString()}′
                </span>
              </div>
              <div className="wx-icon">
                <WeatherIcon cond={w.cond} size={44} />
              </div>
              <div className="wx-cond">{w.cond}</div>
              <div className="wx-temp">
                {w.hiT}°<small> / {w.loT}°F</small>
              </div>
              <div className="wx-meta">
                <div><span>Wind</span> {w.wind} mph</div>
                <div><span>Visibility</span> {w.vis}</div>
                <div><span>Precip chance</span> {w.precip}%</div>
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
