import { useEffect, useState } from 'react'
import { getHealth, type HealthResponse } from '../api/health'
import { isAppError } from '../api/client'

/**
 * A small, unobtrusive service indicator in the footer. It proves the frontend
 * ↔ backend plumbing end to end: the call goes through the axios interceptor
 * layer (src/api/client.ts), so a success renders the reported status and any
 * failure arrives already normalized to an AppError with a display-safe
 * message. This is the one place the mockup actually talks to the backend.
 */
type State =
  | { phase: 'loading' }
  | { phase: 'ok'; health: HealthResponse }
  | { phase: 'error'; message: string }

export function BackendStatus() {
  const [state, setState] = useState<State>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then((health) => {
        if (!cancelled) setState({ phase: 'ok', health })
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            phase: 'error',
            // The interceptor guarantees failures are AppError; the fallback
            // keeps the footer from ever crashing on an unexpected throw.
            message: isAppError(err) ? err.message : 'Unexpected error.',
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <span className="backend-status" aria-live="polite">
      {state.phase === 'loading' && <span className="dot dot-idle" aria-hidden="true" />}
      {state.phase === 'loading' && 'Checking service…'}
      {state.phase === 'ok' && (
        <>
          <span className="dot dot-ok" aria-hidden="true" />
          Service <span data-testid="health-status">{state.health.status}</span>
        </>
      )}
      {state.phase === 'error' && (
        <>
          <span className="dot dot-down" aria-hidden="true" />
          <span role="alert" data-testid="health-error">
            {state.message}
          </span>
        </>
      )}
    </span>
  )
}
