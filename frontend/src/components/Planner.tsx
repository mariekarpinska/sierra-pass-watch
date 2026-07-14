import { useEffect, useRef, useState, type FormEvent } from 'react'
import { getTowns } from '../api/towns'
import { isAppError } from '../api/client'
import type { Segment } from '../api/types'

export interface Plan {
  fromId: string
  toId: string
  /** Departure instant, ISO 8601 UTC (what /api/journey reads). */
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

export function Planner({ onPlan }: Props) {
  const [towns, setTowns] = useState<Segment[]>([])
  const [fromId, setFromId] = useState('')
  const [toId, setToId] = useState('')
  const [departure, setDeparture] = useState(() => toLocalInput(new Date()))
  const [flash, setFlash] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Load the town directory once; default to the two ends of the list.
  useEffect(() => {
    let cancelled = false
    getTowns()
      .then((loaded) => {
        if (cancelled) return
        setTowns(loaded)
        if (loaded.length) {
          setFromId(loaded[0].id)
          setToId(loaded[loaded.length - 1].id)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(isAppError(err) ? err.message : 'Could not load towns.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  // One flash timer at a time: a new flash cancels the previous one (an old
  // timer would otherwise wipe a newer message early), and unmount cancels
  // whatever is pending so the timeout can't fire on a gone component.
  const flashTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(flashTimer.current), [])

  const flashFor = (message: string) => {
    window.clearTimeout(flashTimer.current)
    setFlash(message)
    flashTimer.current = window.setTimeout(() => setFlash(null), 3200)
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!departure) {
      flashFor('Pick a departure time.')
      return
    }
    if (fromId === toId) {
      flashFor('Pick two different places to draw a route.')
      return
    }
    // datetime-local is local time; toISOString gives the backend a UTC instant.
    onPlan({ fromId, toId, departureUtc: new Date(departure).toISOString() })
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
          Pick where you are starting and where you are going, anywhere in the range, and
          when you are leaving. We'll trace the drive across whatever highways it takes and
          pull the live forecast for the six hours from your departure.
        </p>
      </div>

      <form className="route-form" onSubmit={submit} autoComplete="off">
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
