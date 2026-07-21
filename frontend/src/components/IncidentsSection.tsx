import { useEffect, useState } from 'react'
import { getIncidents } from '../api/incidents'
import type { IncidentsResponse, JourneyResponse } from '../api/types'
import { regimeProse } from '../lib/regime'
import { useReveal } from '../lib/useReveal'

interface Props {
  journey: JourneyResponse
}

// Its own small state machine, like CrashHistory: the live feed loads
// independently of the forecast and crash history above it.
type Result =
  | { phase: 'loading' }
  | { phase: 'ok'; data: IncidentsResponse }
  | { phase: 'error' }

// "Sat, Jan 11, 8:05 AM": when the collision was reported, in the reader's
// local time.
function whenLabel(iso: string): string {
  return new Date(iso).toLocaleString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function IncidentsSection({ journey }: Props) {
  const sectionRef = useReveal<HTMLElement>(journey)
  const [result, setResult] = useState<Result>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    setResult({ phase: 'loading' })
    getIncidents(journey.fromId, journey.toId)
      .then((data) => {
        if (!cancelled) setResult({ phase: 'ok', data })
      })
      .catch(() => {
        if (!cancelled) setResult({ phase: 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [journey])

  // The live feed is a bonus, not the main event. If it fails, stay quiet
  // rather than showing an error where the crash history already spoke.
  if (result.phase === 'error') return null

  return (
    <section className="incidents" ref={sectionRef}>
      <div className="section-head">
        <span className="kicker">Live on these roads</span>
        <h2>
          Recent collisions <span className="prov-tag">provisional</span>
        </h2>
        <p className="sub">
          Collisions collected live from the CHP dispatch feed on the roads you're driving,
          each paired with the weather where and when it was reported. This is an unofficial,
          incomplete feed, a look at the live pipeline, not the verified crash history above.
          Collisions on these mountain roads are rare, so this is usually empty.
        </p>
      </div>

      {result.phase === 'loading' && (
        <p className="route-hint" aria-live="polite">
          Checking the live feed…
        </p>
      )}
      {result.phase === 'ok' && result.data.count === 0 && (
        <p className="route-hint">No live-collected collisions on these roads right now.</p>
      )}
      {result.phase === 'ok' && result.data.count > 0 && (
        <div className="incident-grid">
          {result.data.incidents.map((inc, i) => (
            <div
              className="incident-card"
              key={`${inc.routeId}-${inc.mileBin}-${inc.eventTime}-${i}`}
            >
              <div className="incident-where">
                {inc.routeId} · mile {inc.mileBin}
              </div>
              <div className="incident-when">{whenLabel(inc.eventTime)}</div>
              <div className="incident-regime">{regimeProse(inc.regime)}</div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
