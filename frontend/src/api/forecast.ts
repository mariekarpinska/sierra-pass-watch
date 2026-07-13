/**
 * The live forecast along a journey (GET /api/forecast). Open-Meteo is sampled
 * at each town from `from` to `to` (either direction) over a fixed window that
 * starts at `departure`, and each town's hours are summarized by the shared
 * regime classifier. Components import this, not the axios instance, so the
 * whole API surface is listed in src/api/.
 *
 * `departureUtc` is an ISO 8601 instant (e.g. new Date(local).toISOString());
 * the backend reads it as UTC and reports conditions for that window.
 */
import { api } from "./client";
import type { ForecastResponse } from "./types";

export async function getForecast(
  routeId: string,
  fromSegmentId: string,
  toSegmentId: string,
  departureUtc: string,
): Promise<ForecastResponse> {
  const response = await api.get<ForecastResponse>("/api/forecast", {
    params: { route: routeId, from: fromSegmentId, to: toSegmentId, departure: departureUtc },
  });
  return response.data;
}
