/**
 * The ONE axios instance for the whole app. Nothing else should call axios
 * (or fetch) directly — every request flows through this file so that
 * cross-cutting concerns live in exactly one place.
 *
 * WHY AN EXPLICIT "INTERCEPTOR LAYER"?
 * ------------------------------------
 * Interceptors are client-side HTTP middleware: functions that run on every
 * request before it leaves the browser, and on every response before any
 * component sees it. Frameworks often hide this layer; here it is deliberately
 * visible so it can be read, tested, and extended:
 *
 *   component → api.get('/api/…')
 *     → REQUEST interceptor  (headers, correlation id, timing start)
 *       → network
 *     → RESPONSE interceptor (success: pass through; error: normalize)
 *   ← component receives data, or a typed AppError — never a raw axios error
 */
import axios, { type InternalAxiosRequestConfig } from "axios";

/**
 * Every failure the app can see, in one normalized shape. Components never
 * branch on axios internals (err.response?.status ?? …) — the response
 * interceptor converts all failures into this type at the boundary.
 */
export interface AppError {
  /** Machine-readable category the UI can switch on. */
  kind: "network" | "timeout" | "http" | "unknown";
  /** HTTP status when kind === "http". */
  status?: number;
  /** Safe, human-readable message for display. */
  message: string;
  /** Correlation id echoed from the request, for tracing a failure in logs. */
  correlationId?: string;
}

/** Type guard so callers can do `if (isAppError(e))` in catch blocks. */
export function isAppError(e: unknown): e is AppError {
  return (
    typeof e === "object" &&
    e !== null &&
    "kind" in e &&
    "message" in e
  );
}

/** Fields the request interceptor attaches for the response side to read. */
interface RequestMeta {
  correlationId: string;
  startedAtMs: number;
}

// Module augmentation: teach axios's config type about our metadata so the
// two interceptors can share state per-request in a type-safe way.
declare module "axios" {
  export interface InternalAxiosRequestConfig {
    meta?: RequestMeta;
  }
}

/**
 * Convert any thrown value into an AppError. Exported so tests can exercise
 * the normalization table directly, without a network.
 */
export function toAppError(error: unknown): AppError {
  // isAxiosError is a type guard — inside this branch `error` is an AxiosError.
  if (axios.isAxiosError(error)) {
    const correlationId = error.config?.meta?.correlationId;

    if (error.code === "ECONNABORTED" || error.code === "ETIMEDOUT") {
      return {
        kind: "timeout",
        message: "The request timed out. Please try again.",
        correlationId,
      };
    }
    if (error.response) {
      // The server answered with a non-2xx status. Note: we intentionally do
      // NOT surface the server's error body verbatim — backend internals stay
      // out of the UI. The status code is enough for components to react.
      return {
        kind: "http",
        status: error.response.status,
        message:
          error.response.status >= 500
            ? "The server had a problem handling this request."
            : "This request could not be completed.",
        correlationId,
      };
    }
    // No response at all: DNS failure, refused connection, offline, CORS.
    return {
      kind: "network",
      message: "Could not reach the server. Check your connection.",
      correlationId,
    };
  }
  return {
    kind: "unknown",
    message: "Something unexpected went wrong.",
  };
}

/**
 * baseURL:
 *  - dev: empty string → same-origin requests, which Vite's dev-server proxy
 *    forwards to the backend (see vite.config.ts). No CORS in development.
 *  - prod: set VITE_API_BASE_URL at build time to the deployed API origin.
 */
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "",
  timeout: 10_000,
});

// ---------------------------------------------------------------------------
// REQUEST interceptor — runs before every request leaves the browser.
// ---------------------------------------------------------------------------
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  // Correlation id: sent to the server and kept locally, so one id ties
  // together the browser log line, the failed UI state, and the server log.
  // NOTE: crypto.randomUUID exists only in secure contexts (https:// or
  // localhost) — serving the app over plain http on another host would make
  // every request throw here. Deploy behind TLS.
  const correlationId = crypto.randomUUID();
  config.headers.set("X-Correlation-Id", correlationId);
  config.meta = { correlationId, startedAtMs: performance.now() };
  return config;
});

// ---------------------------------------------------------------------------
// RESPONSE interceptor — runs on every response before any component sees it.
// ---------------------------------------------------------------------------
api.interceptors.response.use(
  (response) => {
    const meta = response.config.meta;
    if (import.meta.env.DEV && meta) {
      const elapsed = Math.round(performance.now() - meta.startedAtMs);
      // Dev-only timing log; a production build strips this branch.
      console.debug(
        `[api] ${response.config.method?.toUpperCase()} ${response.config.url} ` +
          `→ ${response.status} in ${elapsed}ms (cid ${meta.correlationId})`,
      );
    }
    return response;
  },
  // Rejections become AppError here — the single exit point for failures.
  (error: unknown) => Promise.reject(toAppError(error)),
);
