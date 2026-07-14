/**
 * A multi-highway journey forecast (GET /api/journey). Given an origin and
 * destination town and a departure time, returns the anchor towns along the
 * drive (OSRM-routed at build time) with each town's departure-window summary.
 *
 * `departureUtc` is an ISO 8601 instant (e.g. new Date(local).toISOString()).
 */
import { api } from "./client";
import type { JourneyResponse } from "./types";

export async function getJourney(
  fromId: string,
  toId: string,
  departureUtc: string,
): Promise<JourneyResponse> {
  const response = await api.get<JourneyResponse>("/api/journey", {
    params: { from: fromId, to: toId, departure: departureUtc },
  });
  return response.data;
}
