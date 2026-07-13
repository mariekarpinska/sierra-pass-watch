import { useEffect, useRef, useState } from 'react'
import { Nav } from './components/Nav'
import { Hero } from './components/Hero'
import { Planner, type Plan } from './components/Planner'
import { WeatherSection } from './components/WeatherSection'
import { MuirQuote } from './components/MuirQuote'
import { Footer, DisclaimerPill } from './components/Footer'
import { getForecast } from './api/forecast'
import { isAppError } from './api/client'
import type { ForecastResponse } from './api/types'

// The forecast request has three visible outcomes; model them explicitly so the
// results area never shows a half state (mirrors components/BackendStatus.tsx).
type Result =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'ok'; forecast: ForecastResponse }
  | { phase: 'error'; message: string }

export function App() {
  const [result, setResult] = useState<Result>({ phase: 'idle' })
  const resultsRef = useRef<HTMLDivElement | null>(null)

  const plan = (p: Plan) => {
    setResult({ phase: 'loading' })
    getForecast(p.routeId, p.fromId, p.toId, p.departureUtc)
      .then((forecast) => setResult({ phase: 'ok', forecast }))
      .catch((err: unknown) =>
        setResult({
          phase: 'error',
          message: isAppError(err) ? err.message : 'Could not load the forecast.',
        }),
      )
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
            {result.phase === 'ok' && <WeatherSection forecast={result.forecast} />}
          </div>
        )}
        <MuirQuote />
      </main>
      <Footer />
      {result.phase === 'ok' && <DisclaimerPill />}
    </>
  )
}
