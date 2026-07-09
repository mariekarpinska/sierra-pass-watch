import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "./api/health";
import { isAppError } from "./api/client";
import "./App.css";

/**
 * Boilerplate landing page: proves the frontend ↔ backend plumbing by calling
 * GET /api/health through the interceptor layer (src/api/client.ts) and
 * rendering the result. Replace this page when building a real feature.
 */
type HealthState =
  | { phase: "loading" }
  | { phase: "ok"; health: HealthResponse }
  | { phase: "error"; message: string };

function App() {
  const [state, setState] = useState<HealthState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((health) => {
        if (!cancelled) setState({ phase: "ok", health });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            phase: "error",
            // The interceptor guarantees failures are AppError, but we keep a
            // defensive fallback so the page can never crash on an odd throw.
            message: isAppError(err) ? err.message : "Unexpected error.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="page">
      <h1>Full-stack boilerplate</h1>
      <p>React + TypeScript frontend · ASP.NET Core backend</p>

      <section className="card" aria-live="polite">
        <h2>Backend health</h2>
        {state.phase === "loading" && <p>Checking…</p>}
        {state.phase === "ok" && (
          <dl>
            <dt>Status</dt>
            <dd data-testid="health-status">{state.health.status}</dd>
            <dt>Service</dt>
            <dd>{state.health.service}</dd>
            <dt>Server time (UTC)</dt>
            <dd>{state.health.timestampUtc}</dd>
          </dl>
        )}
        {state.phase === "error" && (
          <p role="alert" data-testid="health-error">
            {state.message}
          </p>
        )}
      </section>
    </main>
  );
}

export default App;
