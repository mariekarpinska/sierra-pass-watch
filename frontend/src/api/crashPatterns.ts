/**
 * Typed fetcher for GET /api/crash-patterns — the crash record for a journey's
 * highways under one weather regime. Same shape as every other fetcher: one
 * thin function per endpoint through the shared axios client, so components
 * never touch the HTTP layer directly.
 */
import { api } from "./client";
import type { CrashPatternsResponse, RegimeCode } from "./types";

export async function getCrashPatterns(
  routeIds: string[],
  regime: RegimeCode,
): Promise<CrashPatternsResponse> {
  const response = await api.get<CrashPatternsResponse>("/api/crash-patterns", {
    // The API takes the routes as one comma-separated param (they are
    // catalogue ids like "I-80", which never contain commas).
    params: { routes: routeIds.join(","), regime },
  });
  return response.data;
}
