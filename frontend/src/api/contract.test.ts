// Tests for the typed API fetchers (getRoutes, getSegments, getForecast). They
// check that each fetcher calls the right URL, passes the right params, and
// hands back the data. There is no real backend here: we replace the axios
// client with a fake, so nothing leaves the test process.
import { describe, it, expect, vi, beforeEach } from "vitest";
import golden from "../../../shared/weather-regime-cases.json";
import { REGIME_CODES } from "./types";
import type { ForecastResponse, Route, Segment } from "./types";

// Replace the real axios client (./client) with a fake whose `get` is a spy we
// control. This line runs before the imports below, so the fetchers pick up the
// fake `api` instead of the real one.
vi.mock("./client", () => ({ api: { get: vi.fn() } }));

// Imported after the mock above so they use the fake client.
import { api } from "./client";
import { getRoutes } from "./routes";
import { getSegments } from "./segments";
import { getForecast } from "./forecast";

// Sample responses the fake will return, in the same shape the real API sends.
const ROUTES: Route[] = [
  {
    id: "I-80",
    name: "Donner Pass",
    roadNo: "80",
    seasonal: false,
    note: "Only freeway across the range",
    towns: [{ name: "Truckee", lat: 39.328, lon: -120.1833 }],
  },
];
const SEGMENTS: Segment[] = [
  { id: "I-80:truckee", routeId: "I-80", name: "Truckee", lat: 39.328, lon: -120.1833 },
];
const FORECAST: ForecastResponse = {
  routeId: "I-80",
  fromSegmentId: "I-80:truckee",
  toSegmentId: "I-80:truckee",
  departureUtc: "2026-01-12T15:00:00+00:00",
  generatedAtUtc: "2026-01-12T15:02:00+00:00",
  segments: [
    {
      segment: SEGMENTS[0],
      regime: "SNOW",
      temperatureHighF: 28.4,
      temperatureLowF: 27.5,
      windGustMph: 12,
      visibilityMiles: 2,
      precipProbabilityPct: 80,
      shortForecast: "Snow",
    },
  ],
};

// A typed handle to the fake `get`, so we can set what it returns and check how
// it was called.
const mockGet = api.get as unknown as ReturnType<typeof vi.fn>;

// Clear the fake between tests so calls from one test do not carry into the next.
beforeEach(() => mockGet.mockReset());

describe("getRoutes", () => {
  it("calls /api/routes and returns the catalogue", async () => {
    // Make the fake return our sample routes for this call.
    mockGet.mockResolvedValue({ data: ROUTES });

    const routes = await getRoutes();

    // It should have hit the right URL and returned the data unchanged.
    expect(mockGet).toHaveBeenCalledWith("/api/routes");
    expect(routes[0].id).toBe("I-80");
    expect(routes[0].towns[0].name).toBe("Truckee");
  });
});

describe("getSegments", () => {
  it("passes the route param when given one", async () => {
    mockGet.mockResolvedValue({ data: SEGMENTS });

    await getSegments("I-80");

    // A route id is sent as the `route` query param.
    expect(mockGet).toHaveBeenCalledWith("/api/segments", { params: { route: "I-80" } });
  });

  it("omits params when no route is given", async () => {
    mockGet.mockResolvedValue({ data: SEGMENTS });

    await getSegments();

    // No route id: no params, so the request asks for all segments.
    expect(mockGet).toHaveBeenCalledWith("/api/segments", { params: undefined });
  });
});

describe("getForecast", () => {
  it("sends route, from, to and departure as query params and returns the forecast", async () => {
    mockGet.mockResolvedValue({ data: FORECAST });

    const departure = "2026-01-12T15:00:00.000Z";
    const forecast = await getForecast("I-80", "I-80:colfax", "I-80:truckee", departure);

    // The segment ids and departure map to the endpoint's query params.
    expect(mockGet).toHaveBeenCalledWith("/api/forecast", {
      params: { route: "I-80", from: "I-80:colfax", to: "I-80:truckee", departure },
    });
    expect(forecast.segments[0].regime).toBe("SNOW");
    expect(forecast.segments[0].shortForecast).toBe("Snow");
  });
});

// REGIME_CODES is a hand-written mirror of pipeline/regime.py's REGIMES. The
// shared golden file exercises every regime, so set-equality against its
// expected labels catches a vocabulary change (a regime added, renamed or
// removed) that skipped this copy. Ordering is asserted on the backend side
// (test_regime_contract.py pins worst-first ends of REGIMES).
describe("regime vocabulary stays in sync with the shared contract", () => {
  it("REGIME_CODES matches the golden cases' expected labels", () => {
    expect(new Set(REGIME_CODES)).toEqual(new Set(golden.cases.map((c) => c.expected)));
  });
});

// Mirrors backend/tests/test_forbidden_keys.py on the frontend side: the
// contract stays descriptive, so no field name may look like a safety judgement
// (a score, rating, verdict, and so on).
describe("no safety judgement in the contract", () => {
  const FORBIDDEN = ["score", "rating", "recommend", "verdict", "grade"];

  // Collect every property name found in the value, including names nested
  // inside objects and arrays.
  const keys = (value: unknown): string[] => {
    if (Array.isArray(value)) return value.flatMap(keys);
    if (value && typeof value === "object") {
      return Object.entries(value).flatMap(([k, v]) => [k, ...keys(v)]);
    }
    return [];
  };

  it("routes, segments and the forecast carry no score/rating/verdict keys", () => {
    // Gather every key name from all sample payloads, lower-cased.
    const all = [...keys(ROUTES), ...keys(SEGMENTS), ...keys(FORECAST)].map((k) =>
      k.toLowerCase(),
    );

    // None of them should contain a forbidden word.
    expect(all.filter((k) => FORBIDDEN.some((word) => k.includes(word)))).toEqual([]);
  });
});
