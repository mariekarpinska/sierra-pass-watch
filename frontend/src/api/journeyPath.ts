/**
 * Typed fetcher for GET /api/journey-path — the drive's road line for the
 * route-overview map: the committed route polylines sliced to the miles the
 * journey actually drives. Same shape as every other fetcher: one thin
 * function per endpoint through the shared axios client.
 */
import { api } from "./client";
import type { JourneyPathResponse } from "./types";

export async function getJourneyPath(
  fromId: string,
  toId: string,
): Promise<JourneyPathResponse> {
  const response = await api.get<JourneyPathResponse>("/api/journey-path", {
    params: { from: fromId, to: toId },
  });
  return response.data;
}
