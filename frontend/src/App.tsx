import { useCallback, useRef, useState } from 'react'
import { computeRoute, type Route } from './lib/data'
import { Nav } from './components/Nav'
import { Hero } from './components/Hero'
import { Planner } from './components/Planner'
import { RouteOverview } from './components/RouteOverview'
import { AlertBanner } from './components/AlertBanner'
import { WeatherSection } from './components/WeatherSection'
import { InsightSection } from './components/InsightSection'
import { CrashMapSection } from './components/CrashMapSection'
import { MuirQuote } from './components/MuirQuote'
import { Footer, DisclaimerPill } from './components/Footer'

export function App() {
  const [route, setRoute] = useState<Route | null>(null)
  const [dayIdx, setDayIdx] = useState(0)
  const resultsRef = useRef<HTMLDivElement | null>(null)

  const planRoute = useCallback((startIdx: number, endIdx: number) => {
    setRoute(computeRoute(startIdx, endIdx))
    setDayIdx(0)
    // scroll to results once they exist in the DOM
    window.requestAnimationFrame(() => {
      resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [])

  return (
    <>
      <div className="grain" aria-hidden="true" />
      <Nav />
      <Hero />
      <main>
        <Planner onPlan={planRoute} />
        {route && (
          <div className="results" ref={resultsRef}>
            <RouteOverview route={route} />
            <AlertBanner route={route} />
            <WeatherSection route={route} dayIdx={dayIdx} onDayChange={setDayIdx} />
            <InsightSection route={route} dayIdx={dayIdx} />
            <CrashMapSection route={route} dayIdx={dayIdx} />
          </div>
        )}
        <MuirQuote />
      </main>
      <Footer />
      {route && <DisclaimerPill />}
    </>
  )
}
