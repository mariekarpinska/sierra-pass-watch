import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { App } from "./App";
import * as healthApi from "./api/health";
import * as townsApi from "./api/towns";
import * as journeyApi from "./api/journey";
import * as crashApi from "./api/crashPatterns";
import type { JourneyResponse, Waypoint } from "./api/types";

vi.mock("./api/health", { spy: true });
vi.mock("./api/towns", { spy: true });
vi.mock("./api/journey", { spy: true });
vi.mock("./api/crashPatterns", { spy: true });

// The backend status indicator (footer) calls getHealth on mount. These tests
// drive that call directly.
describe("App - backend health round-trip", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the backend health when the call succeeds", async () => {
    vi.spyOn(healthApi, "getHealth").mockResolvedValue({
      status: "healthy",
      service: "backend",
      timestampUtc: "2026-01-01T00:00:00Z",
    });

    render(<App />);

    expect(await screen.findByTestId("health-status")).toHaveTextContent("healthy");
  });

  it("renders the normalized error message when the call fails", async () => {
    vi.spyOn(healthApi, "getHealth").mockRejectedValue({
      kind: "network",
      message: "Could not reach the server. Check your connection.",
    });

    render(<App />);

    expect(await screen.findByTestId("health-error")).toHaveTextContent(
      "Could not reach the server",
    );
  });
});

const TOWNS: Waypoint[] = [
  { id: "colfax", name: "Colfax", lat: 39.1002, lon: -120.9533 },
  { id: "truckee", name: "Truckee", lat: 39.328, lon: -120.1833 },
  { id: "south-lake-tahoe", name: "South Lake Tahoe", lat: 38.9399, lon: -119.9772 },
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
    {
      id: "US-50",
      name: "Echo Summit",
      seasonal: false,
      note: "Main South Tahoe approach",
      span: null,
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

describe("App - plan a journey and show the live forecast", () => {
  beforeEach(() => {
    // Clear call history so one test's getJourney call does not leak into the
    // next (the auto-spies from vi.mock(..., {spy:true}) persist across tests).
    vi.clearAllMocks();
    // jsdom implements neither scrollIntoView (App calls it after planning) nor
    // IntersectionObserver (useReveal drives the reveal animation). Stub both.
    Element.prototype.scrollIntoView = vi.fn();
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe = vi.fn();
        unobserve = vi.fn();
        disconnect = vi.fn();
        takeRecords = vi.fn(() => []);
      },
    );
    // Keep the footer's health call pending so it never updates state here.
    vi.spyOn(healthApi, "getHealth").mockReturnValue(new Promise(() => {}));
    vi.spyOn(townsApi, "getTowns").mockResolvedValue(TOWNS);
    vi.spyOn(journeyApi, "getJourney").mockResolvedValue(JOURNEY);
    // Keep the crash-history call pending too: its loaded state (Leaflet map
    // and all) is covered by CrashHistory.test.tsx, not here.
    vi.spyOn(crashApi, "getCrashPatterns").mockReturnValue(new Promise(() => {}));
  });

  // The selects mount empty and fill in after getTowns resolves; wait for the
  // default start (first town) before interacting.
  const waitForTowns = () =>
    waitFor(() =>
      expect((screen.getByLabelText(/starting from/i) as HTMLSelectElement).value).toBe("colfax"),
    );

  it("renders the planner and shows no forecast initially", async () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: /where are you headed\?/i }),
    ).toBeInTheDocument();
    await waitForTowns();
    expect(
      screen.queryByRole("heading", { name: /forecast along your route/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the live journey forecast after planning", async () => {
    render(<App />);
    await waitForTowns();

    fireEvent.click(screen.getByRole("button", { name: /get the forecast/i }));

    expect(
      await screen.findByRole("heading", { name: /forecast along your route/i }),
    ).toBeInTheDocument();
    // The regime label is unique to the card (town names also appear as options).
    expect(screen.getByText("SNOW")).toBeInTheDocument();
    expect(journeyApi.getJourney).toHaveBeenCalledWith(
      "colfax",
      "south-lake-tahoe",
      expect.any(String),
    );
    // The crash history kicks off right below, for this journey under the
    // worst forecast regime (the one SNOW stop here).
    expect(await screen.findByText(/looking up the road/i)).toBeInTheDocument();
    expect(crashApi.getCrashPatterns).toHaveBeenCalledWith("colfax", "south-lake-tahoe", "SNOW");
  });

  it("blocks planning when start and destination are the same", async () => {
    render(<App />);
    await waitForTowns();

    const start = screen.getByLabelText(/starting from/i) as HTMLSelectElement;
    fireEvent.change(screen.getByLabelText(/driving to/i), {
      target: { value: start.value },
    });
    fireEvent.click(screen.getByRole("button", { name: /get the forecast/i }));

    expect(screen.getByText(/pick two different places/i)).toBeInTheDocument();
    expect(journeyApi.getJourney).not.toHaveBeenCalled();
  });
});
