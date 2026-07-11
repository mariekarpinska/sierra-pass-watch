/**
 * The towns the journey picker offers (GET /api/towns), served from the
 * in-memory journey index so it needs no database. Route-independent points:
 * `routeId` is blank.
 */
import { api } from "./client";
import type { Segment } from "./types";

export async function getTowns(): Promise<Segment[]> {
  const response = await api.get<Segment[]>("/api/towns");
  return response.data;
}
