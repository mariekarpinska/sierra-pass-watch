import { useMemo, useState, useEffect } from 'react'
import { TOWNS, hash, rng, incidentsOnRoute, townMile, segMiles, type Route, type Condition } from '../lib/data'
import { useReveal } from '../lib/useReveal'

const COND_PHRASE: Record<Condition, string> = {
  Snow: 'in snowfall',
  Ice: 'on an icy stretch',
  Fog: 'in low visibility / fog',
  Rain: 'in wet conditions',
  Wind: 'in gusty winds',
  Clear: 'in clear weather',
  'Partly Cloudy': 'under mixed skies',
  Cloudy: 'under overcast skies',
}

interface Props {
  route: Route
}

interface RecentAlert {
  mile: number
  near: string
  phrase: string
  daysAgo: number
}

export function AlertBanner({ route }: Props) {
  const sectionRef = useReveal<HTMLElement>(route)
  const [dismissed, setDismissed] = useState(false)
  useEffect(() => setDismissed(false), [route])

  const alert = useMemo<RecentAlert | null>(() => {
    // deterministic: does this route have a "recently posted" incident?
    const r = rng(hash(`alert${route.startIdx}${route.endIdx}`))
    if (r() >= 0.8) return null
    const pool = incidentsOnRoute(route)
    if (!pool.length) return null
    const pick = pool[Math.floor(r() * pool.length)]
    const near = `${TOWNS[pick.segIdx].id}–${TOWNS[pick.segIdx + 1].id}`
    const mile = Math.round(townMile(route, pick.segIdx) + pick.tFrac * segMiles(pick.segIdx))
    const daysAgo = 1 + Math.floor(r() * 4)
    return { mile, near, phrase: COND_PHRASE[pick.cond], daysAgo }
  }, [route])

  if (!alert || dismissed) return null

  return (
    <section className="alert-wrap" ref={sectionRef}>
      <div className="alert" role="status">
        <div className="alert-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 3 L21 20 H3 Z" />
            <path d="M12 10 v4" />
            <circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />
          </svg>
        </div>
        <div className="alert-body">
          <span className="alert-lead">Heads-up: a recent report on your route</span>
          An incident was logged near <strong>mile {alert.mile}</strong> ({alert.near}) {alert.phrase} —{' '}
          <span className="when">
            posted {alert.daysAgo} day{alert.daysAgo > 1 ? 's' : ''} ago
          </span>.
        </div>
        <button className="alert-dismiss" onClick={() => setDismissed(true)} aria-label="Dismiss heads-up">
          Got it
        </button>
      </div>
    </section>
  )
}
