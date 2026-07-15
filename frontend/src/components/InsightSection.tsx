import { useEffect, useMemo, useState } from 'react'
import type { CrashBin, CrashPatternsResponse, JourneyResponse, RegimeCode } from '../api/types'
import { haversine } from '../lib/data'
import { regimeProse } from '../lib/regime'
import { useReveal } from '../lib/useReveal'

const W = 800
const H = 96
const BASE_Y = 76 // the strip's ground line; stems grow up from here
const MAX_STEM = 56

interface Props {
  journey: JourneyResponse
  regime: RegimeCode
  data: CrashPatternsResponse
}

interface StripDot {
  x: number
  stemTop: number
  r: number
  isHot: boolean
  bin: CrashBin
}

interface Strip {
  routeId: string
  routeName: string
  span: number // miles drawn, route start to the last occupied bin
  dots: StripDot[]
}

/**
 * One density strip per highway of the journey: each occupied mile of road is
 * a stem on the route's own mile axis (measure from the route start,
 * ADR-0007), taller and larger where more history sits. Bins notably above
 * the drive's average marked mile are accented - a deliberately simple
 * display heuristic, relative to the journey's own matched record.
 */
function buildStrips(journey: JourneyResponse, bins: CrashBin[]): { strips: Strip[]; top: CrashBin | null } {
  const maxCount = Math.max(...bins.map((b) => b.crashCount), 1)
  const mean = bins.length ? bins.reduce((s, b) => s + b.crashCount, 0) / bins.length : 0
  const isHot = (b: CrashBin) => b.crashCount >= Math.max(2, mean * 1.6)

  const strips = journey.via.flatMap((leg) => {
    const routeBins = bins.filter((b) => b.routeId === leg.id)
    if (!routeBins.length) return []
    const span = Math.max(...routeBins.map((b) => b.mileBin)) + 1
    return [{
      routeId: leg.id,
      routeName: leg.name,
      span,
      dots: routeBins.map((bin) => {
        const t = bin.crashCount / maxCount
        return {
          x: ((bin.mileBin + 0.5) / span) * W,
          stemTop: BASE_Y - (6 + t * MAX_STEM),
          r: 3.5 + t * 7,
          isHot: isHot(bin),
          bin,
        }
      }),
    }]
  })

  // The densest accented bin anywhere on the drive, for the caption.
  const hot = bins.filter(isHot).sort((a, b) => b.crashCount - a.crashCount)
  return { strips, top: hot[0] ?? null }
}

/** The stop nearest to a bin, to say "near Donner Summit" instead of a number. */
function nearestStopName(journey: JourneyResponse, bin: CrashBin): string {
  let best = journey.stops[0].waypoint
  let bestMi = Infinity
  journey.stops.forEach(({ waypoint }) => {
    const d = haversine([bin.lat, bin.lon], [waypoint.lat, waypoint.lon])
    if (d < bestMi) {
      bestMi = d
      best = waypoint
    }
  })
  return best.name
}

export function InsightSection({ journey, regime, data }: Props) {
  const sectionRef = useReveal<HTMLElement>(journey)
  const { strips, top } = useMemo(() => buildStrips(journey, data.bins), [journey, data.bins])
  const prose = regimeProse(regime)

  // animate cause bars in from 0 on data change
  const [barsIn, setBarsIn] = useState(false)
  useEffect(() => {
    setBarsIn(false)
    const id = window.requestAnimationFrame(() => window.requestAnimationFrame(() => setBarsIn(true)))
    return () => window.cancelAnimationFrame(id)
  }, [data])

  const sinceYear = data.firstCrashDate?.slice(0, 4)

  return (
    <section className="insight" ref={sectionRef}>
      <div className="section-head">
        <span className="kicker">The road's memory</span>
        <h2>
          In <em>{prose}</em> conditions, this is what the road remembers
        </h2>
        <p className="sub">
          Your forecast trends toward <strong>{prose}</strong> along the drive. Below is only the
          history recorded in those conditions on the highways you travel.
        </p>
      </div>

      <div className="insight-grid">
        <div className="insight-col insight-profile-col">
          <h3 className="mini-h">Crash density, mile by mile</h3>
          {strips.map((strip) => (
            <div className="route-strip" key={strip.routeId}>
              <span className="strip-name">
                {strip.routeId} · {strip.routeName}
              </span>
              <div className="profile-wrap">
                <svg className="profile" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
                  <line x1="0" y1={BASE_Y} x2={W} y2={BASE_Y} stroke="#E7DFC8" strokeWidth="1.5" opacity="0.5" />
                  {strip.dots.map((dot) => (
                    <g key={dot.bin.mileBin} opacity={dot.isHot ? 1 : 0.55}>
                      <line
                        x1={dot.x} y1={dot.stemTop} x2={dot.x} y2={BASE_Y}
                        stroke={dot.isHot ? '#B87C24' : '#8E9AA6'} strokeWidth="1" strokeDasharray="2 3"
                      />
                      <circle
                        cx={dot.x} cy={dot.stemTop} r={dot.r}
                        fill={dot.isHot ? 'rgba(224,169,74,.92)' : 'rgba(173,177,151,.45)'}
                        stroke="#20261C" strokeWidth="1.5"
                      />
                    </g>
                  ))}
                </svg>
              </div>
              <div className="profile-axis">
                <span>mi 0</span>
                <span>mi {strip.span}</span>
              </div>
            </div>
          ))}
          <p className="insight-caption">
            {top ? (
              <>
                In these conditions, crashes cluster a little more densely around{' '}
                <span className="hotspot-tag">mile {top.mileBin} of {top.routeId}</span> near{' '}
                {nearestStopName(journey, top)}, a good place to ease your speed and leave extra
                following distance. Marks elsewhere are more evenly spread.
              </>
            ) : data.bins.length ? (
              <>
                History on these roads is spread fairly evenly in these conditions; no single
                stretch stands out. Steady attention throughout serves you best.
              </>
            ) : (
              <>
                No crashes are on record for these highways in weather like your forecast. Enjoy
                the drive, and keep your usual mountain caution.
              </>
            )}
          </p>
        </div>
        <div className="insight-col">
          <h3 className="mini-h">What tends to be involved</h3>
          <ul className="causes">
            {data.topCauses.length ? (
              data.topCauses.map(({ cause, pct }) => (
                <li className="cause" key={cause}>
                  <div className="cause-top">
                    <span className="cause-name">{cause}</span>
                    <span className="cause-pct">{pct}%</span>
                  </div>
                  <div className="cause-bar">
                    <div className="cause-fill" style={{ width: barsIn ? `${pct}%` : 0 }} />
                  </div>
                </li>
              ))
            ) : (
              <li className="insight-caption soft">
                No comparable history recorded on these roads in these conditions: a quiet stretch.
              </li>
            )}
          </ul>
          <p className="insight-caption soft">
            Based on {data.crashCount} recorded crash{data.crashCount === 1 ? '' : 'es'} on these
            highways in similar weather{sinceYear ? ` since ${sinceYear}` : ''}
            {data.pctFatal !== null ? `; ${data.pctFatal}% were fatal` : ''}.
            {data.smallSample && data.crashCount > 0 && (
              <> That is a small record, so read it as context rather than a pattern.</>
            )}
          </p>
        </div>
      </div>
    </section>
  )
}
