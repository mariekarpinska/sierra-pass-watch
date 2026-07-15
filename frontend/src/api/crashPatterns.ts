/**
 * Typed fetcher for GET /api/crash-patterns — the crash record for a journey,
 * each stretch matched to its own forecast regime. The journey is named by
 * its towns and departure time, exactly like /api/journey; the server
 * resolves the roads, the mile stretches and their forecasts itself, so the
 * client sends no weather. Same shape as every other fetcher: one thin
 * function per endpoint through the shared axios client, so components never
 * touch the HTTP layer directly.
 */
import { api } from "./client";
import type { CrashPatternsResponse } from "./types";

export async function getCrashPatterns(
  fromId: string,
  toId: string,
  departureUtc: string,
): Promise<CrashPatternsResponse> {
  const response = await api.get<CrashPatternsResponse>("/api/crash-patterns", {
    params: { from: fromId, to: toId, departure: departureUtc },
  });
  return response.data;
}
