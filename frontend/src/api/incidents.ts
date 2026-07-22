/**
 * Typed fetcher for GET /api/incidents: the provisional live-collision feed
 * (ADR-0012). Named by its towns like the other journey fetchers; the server
 * resolves the roads itself. Same shape as every other fetcher: one thin
 * function per endpoint through the shared axios client.
 */
import { api } from "./client";
import type { IncidentsResponse } from "./types";

export async function getIncidents(
  fromId: string,
  toId: string,
): Promise<IncidentsResponse> {
  const response = await api.get<IncidentsResponse>("/api/incidents", {
    params: { from: fromId, to: toId },
  });
  return response.data;
}
