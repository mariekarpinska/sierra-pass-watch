import { useEffect, useState, type FormEvent } from 'react'
import { getRoutes } from '../api/routes'
import { getSegments } from '../api/segments'
import { isAppError } from '../api/client'
import type { Route, Segment } from '../api/types'

export interface Plan {
  routeId: string
  fromId: string
  toId: string
  /** Departure instant, ISO 8601 UTC (what /api/forecast reads). */
  departureUtc: string
}

interface Props {
  onPlan: (plan: Plan) => void
}

// datetime-local wants "YYYY-MM-DDTHH:MM" in the browser's local time.
function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// The route's towns in travel order (from /api/routes) carry no segment id, and
// /api/segments carries ids but not travel order, so join them by name.
function orderedSegments(route: Route, segments: Segment[]): Segment[] {
  return route.towns
    .map((town) => segments.find((s) => s.name === town.name))
    .filter((s): s is Segment => s !== undefined)
}

export function Planner({ onPlan }: Props) {
  const [routes, setRoutes] = useState<Route[]>([])
  const [routeId, setRouteId] = useState('')
  const [towns, setTowns] = useState<Segment[]>([])
  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')
  const [departure, setDeparture] = useState(() => toLocalInput(new Date()))
  const [flash, setFlash] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Load the catalogue once; default to the first route.
  useEffect(() => {
    let cancelled = false
    getRoutes()
      .then((loaded) => {
        if (cancelled) return
        setRoutes(loaded)
        if (loaded.length) setRouteId(loaded[0].id)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(isAppError(err) ? err.message : 'Could not load routes.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  // When the route changes, load its towns and default to the whole span.
  useEffect(() => {
    if (!routeId) return
    const route = routes.find((r) => r.id === routeId)
    if (!route) return
    let cancelled = false
    getSegments(routeId)
      .then((segments) => {
        if (cancelled) return
        const ordered = orderedSegments(route, segments)
        setTowns(ordered)
        setFromId(ordered[0]?.id ?? '')
        setToId(ordered[ordered.length - 1]?.id ?? '')
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(isAppError(err) ? err.message : 'Could not load towns.')
      })
    return () => {
      cancelled = true
    }
  }, [routeId, routes])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (fromId === toId) {
      setFlash('Pick two different places to draw a route.')
      window.setTimeout(() => setFlash(null), 3200)
      return
    }
    // datetime-local is local time; toISOString gives the backend a UTC instant.
    onPlan({ routeId, fromId, toId, departureUtc: new Date(departure).toISOString() })
  }

  const swap = () => {
    setFromId(toId)
    setToId(fromId)
  }

  if (error) {
    return (
      <section className="planner" id="plan">
        <p className="route-hint" role="alert">
          <strong style={{ color: 'var(--clay)' }}>{error}</strong>
        </p>
      </section>
    )
  }

  return (
    <section className="planner" id="plan">
      <div className="section-head">
        <span className="kicker">Set your line</span>
        <h2>Where are you headed?</h2>
        <p className="sub">
          Pick a route through the Sierra Nevada, a start and a destination, and when you
          are leaving. We'll pull the live forecast for the six hours from your departure.
        </p>
      </div>

      <form className="route-form" onSubmit={submit} autoComplete="off">
        <div className="field">
          <label htmlFor="routeSel">Route</label>
          <div className="select-wrap">
            <select id="routeSel" name="route" value={routeId} onChange={(e) => setRouteId(e.target.value)}>
              {routes.map((r) => (
                <option key={r.id} value={r.id}>{r.name} ({r.id})</option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label htmlFor="startSel">Starting from</label>
          <div className="select-wrap">
            <select id="startSel" name="start" value={fromId} onChange={(e) => setFromId(e.target.value)}>
              {towns.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
        </div>
        <button type="button" className="swap" onClick={swap} title="Swap start & destination" aria-label="Swap start and destination">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 4 L4 7 L7 10" />
            <path d="M4 7 H20" />
            <path d="M17 20 L20 17 L17 14" />
            <path d="M20 17 H4" />
          </svg>
        </button>
        <div className="field">
          <label htmlFor="endSel">Driving to</label>
          <div className="select-wrap">
            <select id="endSel" name="end" value={toId} onChange={(e) => setToId(e.target.value)}>
              {towns.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label htmlFor="departSel">Departing</label>
          <input
            id="departSel"
            name="departure"
            type="datetime-local"
            value={departure}
            onChange={(e) => setDeparture(e.target.value)}
          />
        </div>
        <button type="submit" className="btn btn-primary plan-btn" disabled={!fromId || !toId}>
          Get the forecast
        </button>
      </form>
      {flash && (
        <p className="route-hint">
          <strong style={{ color: 'var(--clay)' }}>{flash}</strong>
        </p>
      )}
    </section>
  )
}
