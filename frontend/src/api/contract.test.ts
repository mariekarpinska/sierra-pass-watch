// Tests for the typed API fetchers (getTowns, getJourney, getCrashPatterns).
// They check that each fetcher calls the right URL, passes the right params,
// and hands back the data. There is no real backend here: we replace the axios
// client with a fake, so nothing leaves the test process.
import { describe, it, expect, vi, beforeEach } from "vitest";
import golden from "../../../shared/weather-regime-cases.json";
import { REGIME_CODES } from "./types";
import type { CrashPatternsResponse, JourneyResponse, Waypoint } from "./types";

// Replace the real axios client (./client) with a fake whose `get` is a spy we
// control. This line runs before the imports below, so the fetchers pick up the
// fake `api` instead of the real one.
vi.mock("./client", () => ({ api: { get: vi.fn() } }));

// Imported after the mock above so they use the fake client.
import { api } from "./client";
import { getTowns } from "./towns";
import { getJourney } from "./journey";
import { getCrashPatterns } from "./crashPatterns";

// Sample responses the fake will return, in the same shape the real API sends.
const TOWNS: Waypoint[] = [
  { id: "colfax", name: "Colfax", lat: 39.1002, lon: -120.9533, elevationFt: 2421 },
  { id: "south-lake-tahoe", name: "South Lake Tahoe", lat: 38.9399, lon: -119.9772, elevationFt: 6270 },
];
const JOURNEY: JourneyResponse = {
  fromId: "colfax",
  toId: "south-lake-tahoe",
  via: [
    {
      id: "I-80",
      name: "Donner Pass",
      seasonal: false,
      note: "Only freeway across the range",
      span: [0, 54],
    },
  ],
  departureUtc: "2026-01-12T15:00:00+00:00",
  generatedAtUtc: "2026-01-12T15:02:00+00:00",
  totalMiles: 94.2,
  totalMinutes: 130,
  stops: [
    {
      waypoint: TOWNS[0],
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

const CRASH_PATTERNS: CrashPatternsResponse = {
  routeIds: ["I-80", "US-50"],
  crashCount: 16,
  fatalCount: 1,
  pctFatal: 6.2,
  smallSample: false,
  firstCrashDate: "2016-06-09",
  lastCrashDate: "2025-12-20",
  bins: [
    {
      routeId: "I-80",
      mileBin: 12,
      regime: "SNOW",
      lat: 39.31,
      lon: -120.32,
      crashCount: 9,
      fatalCount: 1,
      topCause: "Unsafe Speed",
      firstCrashDate: "2017-01-03",
      lastCrashDate: "2025-12-20",
    },
  ],
  topCauses: [{ cause: "Unsafe Speed", crashCount: 10, pct: 62 }],
};

// A typed handle to the fake `get`, so we can set what it returns and check how
// it was called.
const mockGet = api.get as unknown as ReturnType<typeof vi.fn>;

// Clear the fake between tests so calls from one test do not carry into the next.
beforeEach(() => mockGet.mockReset());

describe("getTowns", () => {
  it("calls /api/towns and returns the directory", async () => {
    mockGet.mockResolvedValue({ data: TOWNS });

    const towns = await getTowns();

    expect(mockGet).toHaveBeenCalledWith("/api/towns");
    expect(towns[0].id).toBe("colfax");
  });
});

describe("getJourney", () => {
  it("sends from, to and departure as query params and returns the journey", async () => {
    mockGet.mockResolvedValue({ data: JOURNEY });

    const departure = "2026-01-12T15:00:00.000Z";
    const journey = await getJourney("colfax", "south-lake-tahoe", departure);

    expect(mockGet).toHaveBeenCalledWith("/api/journey", {
      params: { from: "colfax", to: "south-lake-tahoe", departure },
    });
    expect(journey.stops[0].waypoint.name).toBe("Colfax");
    expect(journey.totalMiles).toBe(94.2);
  });
});

describe("getCrashPatterns", () => {
  it("names the journey by its towns and departure time", async () => {
    mockGet.mockResolvedValue({ data: CRASH_PATTERNS });

    const departure = "2026-01-12T15:00:00.000Z";
    const patterns = await getCrashPatterns("colfax", "south-lake-tahoe", departure);

    expect(mockGet).toHaveBeenCalledWith("/api/crash-patterns", {
      params: { from: "colfax", to: "south-lake-tahoe", departure },
    });
    expect(patterns.crashCount).toBe(16);
    expect(patterns.bins[0].mileBin).toBe(12);
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

  it("towns, the journey and the crash record carry no score/rating/verdict keys", () => {
    // Gather every key name from all sample payloads, lower-cased.
    const all = [...keys(TOWNS), ...keys(JOURNEY), ...keys(CRASH_PATTERNS)].map((k) =>
      k.toLowerCase(),
    );

    // None of them should contain a forbidden word.
    expect(all.filter((k) => FORBIDDEN.some((word) => k.includes(word)))).toEqual([]);
  });
});
