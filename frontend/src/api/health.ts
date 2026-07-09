/**
 * One thin, typed function per endpoint. Components import these functions —
 * never the axios instance directly — so the API surface the UI depends on
 * is enumerable in src/api/.
 */
import { api } from "./client";

/** Mirrors the backend's Health model (backend/api/schemas.py). */
export interface HealthResponse {
  status: string;
  service: string;
  timestampUtc: string;
}

export async function getHealth(): Promise<HealthResponse> {
  const response = await api.get<HealthResponse>("/api/health");
  return response.data;
}
