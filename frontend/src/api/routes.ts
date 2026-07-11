/**
 * The route catalogue. One typed function per endpoint. Components import this,
 * not the axios instance, so the whole API surface is listed in src/api/.
 */
import { api } from "./client";
import type { Route } from "./types";

export async function getRoutes(): Promise<Route[]> {
  const response = await api.get<Route[]>("/api/routes");
  return response.data;
}
