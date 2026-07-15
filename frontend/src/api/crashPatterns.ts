/**
 * Typed fetcher for GET /api/crash-patterns — the crash record for a journey
 * under one weather regime. The journey is named by its towns, exactly like
 * /api/journey; the server resolves it against the same committed index, so
 * the roads and the mile span the drive covers on each road come from one
 * place. Same shape as every other fetcher: one thin function per endpoint
 * through the shared axios client, so components never touch the HTTP layer
 * directly.
 */
import { api } from "./client";
import type { CrashPatternsResponse, RegimeCode } from "./types";

export async function getCrashPatterns(
  fromId: string,
  toId: string,
  regime: RegimeCode,
): Promise<CrashPatternsResponse> {
  const response = await api.get<CrashPatternsResponse>("/api/crash-patterns", {
    params: { from: fromId, to: toId, regime },
  });
  return response.data;
}
