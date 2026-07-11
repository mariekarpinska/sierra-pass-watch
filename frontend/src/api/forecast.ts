/**
 * The live forecast along a journey (GET /api/forecast). Open-Meteo is sampled
 * at each town from `from` to `to` (either direction), and every hour is
 * labelled by the shared regime classifier. Components import this, not the
 * axios instance, so the whole API surface is listed in src/api/.
 */
import { api } from "./client";
import type { ForecastResponse } from "./types";

export async function getForecast(
  routeId: string,
  fromSegmentId: string,
  toSegmentId: string,
): Promise<ForecastResponse> {
  const response = await api.get<ForecastResponse>("/api/forecast", {
    params: { route: routeId, from: fromSegmentId, to: toSegmentId },
  });
  return response.data;
}
