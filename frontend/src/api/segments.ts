/**
 * Anchor waypoints, optionally for one route. Passing no route returns them all;
 * an unknown route is an empty list, not an error (the backend returns []).
 */
import { api } from "./client";
import type { Segment } from "./types";

export async function getSegments(route?: string): Promise<Segment[]> {
  const response = await api.get<Segment[]>("/api/segments", {
    params: route ? { route } : undefined,
  });
  return response.data;
}
