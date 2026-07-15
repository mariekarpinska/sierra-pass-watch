import { useEffect, useState } from 'react'
import { getCrashPatterns } from '../api/crashPatterns'
import type { CrashPatternsResponse, JourneyResponse, RegimeCode } from '../api/types'
import { worstRegime, regimeProse } from '../lib/regime'
import { CrashMapSection } from './CrashMapSection'
import { InsightSection } from './InsightSection'

interface Props {
  journey: JourneyResponse
}

// Same explicit state machine as the journey request in App.tsx: the history
// area is either loading, showing data, or quietly degraded - never half of two.
type Result =
  | { phase: 'loading' }
  | { phase: 'ok'; data: CrashPatternsResponse }
  | { phase: 'error' }

/**
 * Fetches the crash record for the journey's highways under the worst
 * forecast regime along the drive, and renders the two history sections from
 * it. Failure here never blocks the forecast above: the sections simply give
 * way to a one-line note.
 */
export function CrashHistory({ journey }: Props) {
  const [result, setResult] = useState<Result>({ phase: 'loading' })
  const regime: RegimeCode = worstRegime(journey.stops)
  const routeIds = journey.via.map((leg) => leg.id)

  useEffect(() => {
    // An all-UNKNOWN forecast gives nothing to match history against, so
    // there is no request to make (the render below explains instead).
    if (regime === 'UNKNOWN' || routeIds.length === 0) return
    let cancelled = false
    setResult({ phase: 'loading' })
    getCrashPatterns(routeIds, regime)
      .then((data) => {
        if (!cancelled) setResult({ phase: 'ok', data })
      })
      .catch(() => {
        if (!cancelled) setResult({ phase: 'error' })
      })
    return () => {
      cancelled = true
    }
    // routeIds is derived from journey; keying on journey + regime covers it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [journey, regime])

  if (regime === 'UNKNOWN' || routeIds.length === 0) {
    return (
      <p className="route-hint">
        The forecast came back without data, so there is nothing to match the
        crash history against for this drive.
      </p>
    )
  }
  if (result.phase === 'loading') {
    return (
      <p className="route-hint" aria-live="polite">
        Looking up the road&apos;s history…
      </p>
    )
  }
  if (result.phase === 'error') {
    return (
      <p className="route-hint">
        The crash history could not be loaded right now. The forecast above
        still stands; history recorded in {regimeProse(regime)} conditions will
        be back when the service is.
      </p>
    )
  }
  return (
    <>
      <InsightSection journey={journey} regime={regime} data={result.data} />
      <CrashMapSection journey={journey} regime={regime} data={result.data} />
    </>
  )
}
