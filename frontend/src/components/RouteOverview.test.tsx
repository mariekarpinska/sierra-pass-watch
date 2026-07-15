// The route overview: the drive's vital numbers and its road line, with the
// path fetch spy-mocked and Leaflet stubbed (jsdom cannot host a real map;
// the hook runs in a real browser, not here).
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { RouteOverview } from "./RouteOverview";
import * as pathApi from "../api/journeyPath";
import type { JourneyResponse } from "../api/types";

vi.mock("../api/journeyPath", { spy: true });
vi.mock("../lib/useLeafletMap", () => ({
  useLeafletMap: () => ({ current: null }),
}));

const JOURNEY: JourneyResponse = {
  fromId: "colfax",
  toId: "south-lake-tahoe",
  via: [
    { id: "I-80", name: "Donner Pass", seasonal: false, note: "year-round", span: [0, 52] },
  ],
  departureUtc: "2026-01-12T15:00:00+00:00",
  generatedAtUtc: "2026-01-12T15:02:00+00:00",
  totalMiles: 93.5,
  totalMinutes: 130,
  stops: [
    {
      waypoint: { id: "colfax", name: "Colfax", lat: 39.1002, lon: -120.9533, elevationFt: 2421 },
      regime: "CLEAR_DRY",
      temperatureHighF: 40,
      temperatureLowF: 30,
      windGustMph: 5,
      visibilityMiles: 9,
      precipProbabilityPct: 5,
      shortForecast: "Clear",
    },
    {
      waypoint: { id: "donner-summit", name: "Donner Summit", lat: 39.3163, lon: -120.3208, elevationFt: 6867 },
      regime: "SNOW",
      temperatureHighF: 28,
      temperatureLowF: 20,
      windGustMph: 20,
      visibilityMiles: 2,
      precipProbabilityPct: 80,
      shortForecast: "Snow",
    },
    {
      waypoint: { id: "south-lake-tahoe", name: "South Lake Tahoe", lat: 38.9399, lon: -119.9772, elevationFt: 6270 },
      regime: "CLEAR_DRY",
      temperatureHighF: 38,
      temperatureLowF: 28,
      windGustMph: 8,
      visibilityMiles: 9,
      precipProbabilityPct: 10,
      shortForecast: "Clear",
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
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

describe("RouteOverview", () => {
  it("shows the drive's numbers and fetches its road line", async () => {
    vi.spyOn(pathApi, "getJourneyPath").mockResolvedValue({
      paths: [[[39.1, -120.95], [39.32, -120.32]]],
    });

    render(<RouteOverview journey={JOURNEY} />);

    expect(pathApi.getJourneyPath).toHaveBeenCalledWith("colfax", "south-lake-tahoe");
    expect(screen.getByText(/your passage/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /colfax\s*→\s*south lake tahoe/i })).toBeInTheDocument();
    // The vital numbers come straight off the journey; the high point is the
    // highest stop elevation (Donner Summit here).
    expect(screen.getByText("94 mi")).toBeInTheDocument();
    expect(screen.getByText("3 stops")).toBeInTheDocument();
    expect(screen.getByText("6,867 ft")).toBeInTheDocument();
    expect(screen.getByText("130 min")).toBeInTheDocument();
    expect(screen.getByText("Start")).toBeInTheDocument();
    expect(screen.getByText("Destination")).toBeInTheDocument();
  });

  it("still shows the numbers when the road line cannot be fetched", async () => {
    vi.spyOn(pathApi, "getJourneyPath").mockRejectedValue(new Error("down"));

    render(<RouteOverview journey={JOURNEY} />);

    expect(await screen.findByText("94 mi")).toBeInTheDocument();
    expect(screen.getByText(/your passage/i)).toBeInTheDocument();
  });

  it("shows a dash when no stop carries an elevation", () => {
    vi.spyOn(pathApi, "getJourneyPath").mockReturnValue(new Promise(() => {}));
    const bare: JourneyResponse = {
      ...JOURNEY,
      stops: JOURNEY.stops.map((s) => ({
        ...s,
        waypoint: { ...s.waypoint, elevationFt: null },
      })),
    };

    render(<RouteOverview journey={bare} />);

    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
