// The crash-history container: which regime it matches history against, what
// it asks the API for, and how each outcome renders. The API module is
// spy-mocked; Leaflet's map hook is stubbed out because jsdom implements
// neither the layout nor the observers a real map needs (the hook itself is
// exercised in a real browser, not here).
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { CrashHistory } from "./CrashHistory";
import * as crashApi from "../api/crashPatterns";
import type { CrashPatternsResponse, JourneyResponse } from "../api/types";

vi.mock("../api/crashPatterns", { spy: true });
vi.mock("../lib/useLeafletMap", () => ({
  useLeafletMap: () => ({ current: null }),
}));

const JOURNEY: JourneyResponse = {
  fromId: "colfax",
  toId: "south-lake-tahoe",
  via: [
    { id: "I-80", name: "Donner Pass", seasonal: false, note: "year-round" },
    { id: "US-50", name: "Echo Summit", seasonal: false, note: "year-round" },
  ],
  departureUtc: "2026-01-12T15:00:00+00:00",
  generatedAtUtc: "2026-01-12T15:02:00+00:00",
  totalMiles: 94.2,
  totalMinutes: 130,
  stops: [
    {
      waypoint: { id: "colfax", name: "Colfax", lat: 39.1002, lon: -120.9533 },
      regime: "CLEAR_DRY",
      temperatureHighF: 40,
      temperatureLowF: 30,
      windGustMph: 5,
      visibilityMiles: 9,
      precipProbabilityPct: 5,
      shortForecast: "Clear",
    },
    {
      waypoint: { id: "donner-summit", name: "Donner Summit", lat: 39.3163, lon: -120.3208 },
      regime: "SNOW",
      temperatureHighF: 28,
      temperatureLowF: 20,
      windGustMph: 20,
      visibilityMiles: 2,
      precipProbabilityPct: 80,
      shortForecast: "Snow",
    },
  ],
};

const PATTERNS: CrashPatternsResponse = {
  regime: "SNOW",
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
      lat: 39.3163,
      lon: -120.3208,
      crashCount: 9,
      fatalCount: 1,
      topCause: "Unsafe Speed",
      firstCrashDate: "2017-01-03",
      lastCrashDate: "2025-12-20",
    },
    {
      routeId: "I-80",
      mileBin: 20,
      lat: 39.32,
      lon: -120.2,
      crashCount: 2,
      fatalCount: 0,
      topCause: "DUI",
      firstCrashDate: "2019-02-01",
      lastCrashDate: "2021-11-05",
    },
    {
      routeId: "US-50",
      mileBin: 40,
      lat: 38.81,
      lon: -120.03,
      crashCount: 5,
      fatalCount: 0,
      topCause: "Unsafe Speed",
      firstCrashDate: "2016-06-09",
      lastCrashDate: "2024-03-14",
    },
  ],
  topCauses: [
    { cause: "Unsafe Speed", crashCount: 10, pct: 62 },
    { cause: "DUI", crashCount: 3, pct: 19 },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom has no IntersectionObserver (useReveal drives the reveal animation).
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
      takeRecords = vi.fn(() => []);
    },
  );
});

describe("CrashHistory", () => {
  it("asks for the journey's highways under the worst regime and renders the record", async () => {
    vi.spyOn(crashApi, "getCrashPatterns").mockResolvedValue(PATTERNS);

    render(<CrashHistory journey={JOURNEY} />);

    // The worst stop (SNOW) wins over CLEAR_DRY as the regime to match.
    expect(crashApi.getCrashPatterns).toHaveBeenCalledWith(["I-80", "US-50"], "SNOW");
    expect(
      await screen.findByRole("heading", { name: /what the road remembers/i }),
    ).toBeInTheDocument();
    // One density strip per highway that has history.
    expect(screen.getByText(/I-80 · Donner Pass/)).toBeInTheDocument();
    expect(screen.getByText(/US-50 · Echo Summit/)).toBeInTheDocument();
    // The densest bin is called out with its nearest stop by name.
    expect(screen.getByText(/mile 12 of I-80/)).toBeInTheDocument();
    expect(screen.getByText(/near Donner Summit/)).toBeInTheDocument();
    // Cause bars and the factual footer (count and fatality share, once).
    expect(screen.getByText("Unsafe Speed")).toBeInTheDocument();
    expect(screen.getByText(/based on 16 recorded crashes/i)).toBeInTheDocument();
    expect(screen.getByText(/6\.2% were fatal/i)).toBeInTheDocument();
    // Map sidebar count.
    expect(screen.getByText("16")).toBeInTheDocument();
  });

  it("flags a thin record as context, not a pattern", async () => {
    vi.spyOn(crashApi, "getCrashPatterns").mockResolvedValue({
      ...PATTERNS,
      crashCount: 3,
      fatalCount: 0,
      pctFatal: 0,
      smallSample: true,
      bins: [PATTERNS.bins[1]],
      topCauses: [{ cause: "DUI", crashCount: 3, pct: 100 }],
    });

    render(<CrashHistory journey={JOURNEY} />);

    expect(await screen.findByText(/small record/i)).toBeInTheDocument();
  });

  it("answers an empty record honestly", async () => {
    vi.spyOn(crashApi, "getCrashPatterns").mockResolvedValue({
      ...PATTERNS,
      crashCount: 0,
      fatalCount: 0,
      pctFatal: null,
      smallSample: true,
      firstCrashDate: null,
      lastCrashDate: null,
      bins: [],
      topCauses: [],
    });

    render(<CrashHistory journey={JOURNEY} />);

    expect(await screen.findByText(/no crashes are on record/i)).toBeInTheDocument();
    expect(screen.getByText(/no comparable history/i)).toBeInTheDocument();
  });

  it("degrades to a quiet note when the request fails", async () => {
    vi.spyOn(crashApi, "getCrashPatterns").mockRejectedValue({
      kind: "http",
      status: 500,
      message: "The server had a problem handling this request.",
    });

    render(<CrashHistory journey={JOURNEY} />);

    expect(
      await screen.findByText(/crash history could not be loaded/i),
    ).toBeInTheDocument();
  });

  it("explains instead of fetching when the whole forecast is UNKNOWN", () => {
    vi.spyOn(crashApi, "getCrashPatterns").mockResolvedValue(PATTERNS);
    const noData: JourneyResponse = {
      ...JOURNEY,
      stops: JOURNEY.stops.map((stop) => ({ ...stop, regime: "UNKNOWN" as const })),
    };

    render(<CrashHistory journey={noData} />);

    expect(crashApi.getCrashPatterns).not.toHaveBeenCalled();
    expect(screen.getByText(/nothing to match the crash history against/i)).toBeInTheDocument();
  });
});
