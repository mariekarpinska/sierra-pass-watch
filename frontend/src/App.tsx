import { useEffect, useRef, useState } from 'react'
import { Nav } from './components/Nav'
import { Hero } from './components/Hero'
import { Planner, type Plan } from './components/Planner'
import { WeatherSection } from './components/WeatherSection'
import { RouteOverview } from './components/RouteOverview'
import { CrashHistory } from './components/CrashHistory'
import { IncidentsSection } from './components/IncidentsSection'
import { MuirQuote } from './components/MuirQuote'
import { Footer, DisclaimerPill } from './components/Footer'
import { getJourney } from './api/journey'
import { isAppError } from './api/client'
import type { JourneyResponse } from './api/types'

// The journey request has three visible outcomes; model them explicitly so the
// results area never shows a half state (mirrors components/BackendStatus.tsx).
type Result =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'ok'; journey: JourneyResponse }
  | { phase: 'error'; message: string }

export function App() {
  const [result, setResult] = useState<Result>({ phase: 'idle' })
  const resultsRef = useRef<HTMLDivElement | null>(null)
  // Monotonic id so a slow response from an abandoned plan can't overwrite a
  // newer one (the user can resubmit before the first request resolves).
  const latestRequest = useRef(0)

  const plan = (p: Plan) => {
    const requestId = ++latestRequest.current
    setResult({ phase: 'loading' })
    getJourney(p.fromId, p.toId, p.departureUtc)
      .then((journey) => {
        if (requestId === latestRequest.current) setResult({ phase: 'ok', journey })
      })
      .catch((err: unknown) => {
        if (requestId !== latestRequest.current) return
        setResult({
          phase: 'error',
          message: isAppError(err) ? err.message : 'Could not load the forecast.',
        })
      })
  }

  // Scroll to the results once they render. Keying on the phase runs this after
  // the commit that mounts the results div has attached the ref.
  useEffect(() => {
    if (result.phase !== 'idle') {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [result.phase])

  return (
    <>
      <div className="grain" aria-hidden="true" />
      <Nav />
      <Hero />
      <main>
        <Planner onPlan={plan} />
        {result.phase !== 'idle' && (
          <div className="results" ref={resultsRef}>
            {result.phase === 'loading' && (
              <p className="route-hint" aria-live="polite">Pulling the forecast…</p>
            )}
            {result.phase === 'error' && (
              <p className="route-hint" role="alert">
                <strong style={{ color: 'var(--clay)' }}>{result.message}</strong>
              </p>
            )}
            {result.phase === 'ok' && (
              <>
                <WeatherSection journey={result.journey} />
                <RouteOverview journey={result.journey} />
                <CrashHistory journey={result.journey} />
                <IncidentsSection journey={result.journey} />
              </>
            )}
          </div>
        )}
        <MuirQuote />
      </main>
      <Footer />
      {result.phase === 'ok' && <DisclaimerPill />}
    </>
  )
}
