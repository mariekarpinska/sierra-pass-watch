/**
 * The towns the journey picker offers (GET /api/towns), served from the
 * in-memory journey index so it needs no database. Route-independent points, so
 * they are plain Waypoints (no routeId): a journey crosses highways.
 */
import { api } from "./client";
import type { Waypoint } from "./types";

export async function getTowns(): Promise<Waypoint[]> {
  const response = await api.get<Waypoint[]>("/api/towns");
  return response.data;
}
