import { useEffect, useState } from 'react'
import { getCrashPatterns } from '../api/crashPatterns'
import type { CrashPatternsResponse, JourneyResponse } from '../api/types'
import { worstRegime } from '../lib/regime'
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
 * Fetches the crash record for the journey - the server matches each stretch
 * of the drive to its own forecast regime - and renders the two history
 * sections from it. Failure here never blocks the forecast above: the
 * sections simply give way to a one-line note. worstRegime is only the gate:
 * an all-UNKNOWN forecast has no weather to match, so there is no request.
 */
export function CrashHistory({ journey }: Props) {
  const [result, setResult] = useState<Result>({ phase: 'loading' })
  const nothingToMatch = worstRegime(journey.stops) === 'UNKNOWN' || journey.via.length === 0

  useEffect(() => {
    if (nothingToMatch) return
    let cancelled = false
    setResult({ phase: 'loading' })
    getCrashPatterns(journey.fromId, journey.toId, journey.departureUtc)
      .then((data) => {
        if (!cancelled) setResult({ phase: 'ok', data })
      })
      .catch(() => {
        if (!cancelled) setResult({ phase: 'error' })
      })
    return () => {
      cancelled = true
    }
    // nothingToMatch is derived from journey; keying on journey covers it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [journey])

  if (nothingToMatch) {
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
        still stands; the history matched to it will be back when the service
        is.
      </p>
    )
  }
  return (
    <>
      <InsightSection journey={journey} data={result.data} />
      <CrashMapSection journey={journey} data={result.data} />
    </>
  )
}
