/**
 * Typed fetcher for GET /api/journey-path — the drive's road line for the
 * route-overview map: the committed route polylines sliced to the miles the
 * journey actually drives. Same shape as every other fetcher: one thin
 * function per endpoint through the shared axios client.
 */
import { api } from "./client";
import type { JourneyPathResponse } from "./types";

// The road line is immutable per deploy (both inputs are committed build
// artifacts), so cache each result by town pair. Replanning the same trip -
// e.g. only the departure time changed - then draws from memory instead of
// re-downloading the few-thousand-point line. The cache lives at module scope
// on purpose: it outlives the RouteOverview component being unmounted and
// remounted during a replan, which a component-local cache would not.
const cache = new Map<string, JourneyPathResponse>();

export async function getJourneyPath(
  fromId: string,
  toId: string,
): Promise<JourneyPathResponse> {
  const key = `${fromId}|${toId}`;
  const cached = cache.get(key);
  if (cached) return cached;

  const response = await api.get<JourneyPathResponse>("/api/journey-path", {
    params: { from: fromId, to: toId },
  });
  // Only successful responses are cached; a failed fetch is left uncached so a
  // later replan can retry it.
  cache.set(key, response.data);
  return response.data;
}
