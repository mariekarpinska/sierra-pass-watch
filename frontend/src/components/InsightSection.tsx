import { useEffect, useMemo, useState } from 'react'
import { TOWNS, lerp, townMile, routeIncidents, type Route, type RouteIncident, type Cause } from '../lib/data'
import { useReveal } from '../lib/useReveal'

const W = 800
const H = 240
const PAD_Y = 34

interface Props {
  route: Route
  dayIdx: number
}

interface Hotspot {
  b: number
  c: number
  mile: number
}

interface ProfileModel {
  linePath: string
  areaPath: string
  townPts: Array<{ x: number; y: number }>
  bins: Array<{ x: number, yTop: number, r: number, isHot: boolean }>
  hotspots: Hotspot[]
  axisLabels: string[]
}

function buildProfile(route: Route, list: RouteIncident[]): ProfileModel {
  const order = route.order
  const miles = order.map((i) => townMile(route, i))
  const maxMile = Math.max(...miles, 1)
  const els = order.map((i) => TOWNS[i].el)
  const minEl = Math.min(...els) * 0.9
  const maxEl = Math.max(...els) * 1.05
  const x = (m: number) => (m / maxMile) * W
  const y = (e: number) => H - PAD_Y - ((e - minEl) / (maxEl - minEl)) * (H - PAD_Y * 1.6)

  const pts = order.map((i, k) => ({ x: x(miles[k]), y: y(TOWNS[i].el) }))
  const linePath = pts.map((p, k) => `${k ? 'L' : 'M'}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
  const areaPath = `${linePath} L ${W} ${H} L 0 ${H} Z`

  // interpolated elevation y at an arbitrary mile, for hotspot stems
  const yAtMile = (m: number) => {
    let e = TOWNS[order[0]].el
    for (let k = 0; k < order.length - 1; k++) {
      if (m >= miles[k] && m <= miles[k + 1]) {
        const t = (m - miles[k]) / (miles[k + 1] - miles[k] || 1)
        e = lerp(TOWNS[order[k]].el, TOWNS[order[k + 1]].el, t)
        break
      }
    }
    return y(e)
  }

  // hotspot bins (by mile) among similar-weather incidents
  const binCount = 10
  const binW = maxMile / binCount
  const counts = new Array<number>(binCount).fill(0)
  list.forEach((i) => {
    counts[Math.min(binCount - 1, Math.floor(i.mile / binW))]++
  })
  const mean = counts.reduce((a, b) => a + b, 0) / binCount
  const maxCount = Math.max(...counts, 1)
  // hotspot = bin notably above average
  const hotspots: Hotspot[] = []
  counts.forEach((c, b) => {
    if (c >= Math.max(2, mean * 1.6)) hotspots.push({ b, c, mile: Math.round((b + 0.5) * binW) })
  })
  hotspots.sort((a, b) => b.c - a.c)

  const bins = counts.flatMap((c, b) => {
    if (c === 0) return []
    const mid = (b + 0.5) * binW
    return [{
      x: x(mid),
      yTop: yAtMile(mid),
      r: 4 + (c / maxCount) * 10,
      isHot: hotspots.some((h) => h.b === b),
    }]
  })

  const maxEl2 = Math.max(...els)
  const axisLabels = order
    .map((i, k) =>
      k === 0 || k === order.length - 1 || TOWNS[i].el === maxEl2
        ? `${TOWNS[i].id} · mi ${Math.round(miles[k])}`
        : null,
    )
    .filter((s): s is string => s !== null)

  return { linePath, areaPath, townPts: pts, bins, hotspots, axisLabels }
}

function nearestTownLabel(route: Route, mile: number): string {
  let best = TOWNS[route.order[0]].id
  let bestD = Infinity
  route.order.forEach((i) => {
    const d = Math.abs(townMile(route, i) - mile)
    if (d < bestD) {
      bestD = d
      best = TOWNS[i].id
    }
  })
  return best
}

export function InsightSection({ route, dayIdx }: Props) {
  const sectionRef = useReveal<HTMLElement>(route)
  const { cond, similar, list } = useMemo(() => routeIncidents(route, dayIdx), [route, dayIdx])
  const profile = useMemo(() => buildProfile(route, list), [route, list])

  const causes = useMemo(() => {
    const tally = new Map<Cause, number>()
    list.forEach((i) => tally.set(i.cause, (tally.get(i.cause) ?? 0) + 1))
    const total = list.length || 1
    return [...tally.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([name, n]) => ({ name, pct: Math.round((n / total) * 100) }))
  }, [list])

  // animate cause bars in from 0 on data change
  const [barsIn, setBarsIn] = useState(false)
  useEffect(() => {
    setBarsIn(false)
    const id = window.requestAnimationFrame(() => window.requestAnimationFrame(() => setBarsIn(true)))
    return () => window.cancelAnimationFrame(id)
  }, [causes])

  const top = profile.hotspots[0]

  return (
    <section className="insight" ref={sectionRef}>
      <div className="section-head">
        <span className="kicker">The road's memory</span>
        <h2>
          In <em>{cond.toLowerCase()}-like</em> conditions, this is what the road remembers
        </h2>
        <p className="sub">
          Your forecast trends toward <strong>{cond.toLowerCase()}</strong> along the drive. Below
          is only the history recorded in similar weather ({similar.join(', ').toLowerCase()}).
        </p>
      </div>

      <div className="insight-grid">
        <div className="insight-col insight-profile-col">
          <h3 className="mini-h">Elevation &amp; attention hotspots</h3>
          <div className="profile-wrap">
            <svg className="profile" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
              <defs>
                <linearGradient id="elg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor="#9DB183" stopOpacity=".5" />
                  <stop offset="1" stopColor="#9DB183" stopOpacity="0" />
                </linearGradient>
              </defs>
              <path d={profile.areaPath} fill="url(#elg)" />
              <path d={profile.linePath} fill="none" stroke="#E7DFC8" strokeWidth="2.5" strokeLinejoin="round" />
              {profile.bins.map((bin, k) => (
                <g key={k} opacity={bin.isHot ? 1 : 0.5}>
                  <line
                    x1={bin.x} y1={bin.yTop} x2={bin.x} y2={H - PAD_Y}
                    stroke={bin.isHot ? '#B87C24' : '#8E9AA6'} strokeWidth="1" strokeDasharray="2 3"
                  />
                  <circle
                    cx={bin.x} cy={H - PAD_Y} r={bin.r}
                    fill={bin.isHot ? 'rgba(224,169,74,.92)' : 'rgba(173,177,151,.45)'}
                    stroke="#20261C" strokeWidth="1.5"
                  />
                </g>
              ))}
              {profile.townPts.map((p, k) => (
                <circle key={k} cx={p.x} cy={p.y} r="3.5" fill="#ECE3CE" />
              ))}
            </svg>
          </div>
          <div className="profile-axis">
            {profile.axisLabels.map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
          <p className="insight-caption">
            {top ? (
              <>
                In these conditions, incidents cluster a little more densely around{' '}
                <span className="hotspot-tag">mile {top.mile}</span> near{' '}
                {nearestTownLabel(route, top.mile)} — a good place to ease your speed and leave
                extra following distance. Marks elsewhere are more evenly spread.
              </>
            ) : list.length ? (
              <>
                History on this route is spread fairly evenly in these conditions — no single
                stretch stands out. Steady attention throughout serves you best.
              </>
            ) : (
              <>
                No comparable incidents are on record for this route in weather like your forecast.
                Enjoy the drive — and keep your usual mountain caution.
              </>
            )}
          </p>
        </div>
        <div className="insight-col">
          <h3 className="mini-h">What tends to be involved</h3>
          <ul className="causes">
            {causes.length ? (
              causes.map(({ name, pct }) => (
                <li className="cause" key={name}>
                  <div className="cause-top">
                    <span className="cause-name">{name}</span>
                    <span className="cause-pct">{pct}%</span>
                  </div>
                  <div className="cause-bar">
                    <div className="cause-fill" style={{ width: barsIn ? `${pct}%` : 0 }} />
                  </div>
                </li>
              ))
            ) : (
              <li className="insight-caption soft">
                No comparable history recorded on this route in these conditions — a quiet stretch.
              </li>
            )}
          </ul>
          <p className="insight-caption soft">
            Based on {list.length} recorded incident{list.length === 1 ? '' : 's'} on this route in
            similar weather.
          </p>
        </div>
      </div>
    </section>
  )
}
