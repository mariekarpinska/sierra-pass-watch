import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { App } from "./App";
import * as healthApi from "./api/health";
import * as routesApi from "./api/routes";
import * as segmentsApi from "./api/segments";
import * as forecastApi from "./api/forecast";
import type { ForecastResponse, Route, Segment } from "./api/types";

vi.mock("./api/health", { spy: true });
vi.mock("./api/routes", { spy: true });
vi.mock("./api/segments", { spy: true });
vi.mock("./api/forecast", { spy: true });

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

    expect(await screen.findByTestId("health-status")).toHaveTextContent(
      "healthy",
    );
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

const ROUTE: Route = {
  id: "US-50",
  name: "Echo Summit",
  roadNo: "50",
  seasonal: false,
  note: "",
  towns: [
    { name: "Placerville", lat: 38.7296, lon: -120.7985 },
    { name: "Echo Summit", lat: 38.8124, lon: -120.03 },
    { name: "South Lake Tahoe", lat: 38.9399, lon: -119.9772 },
  ],
};
// /api/segments is ordered by id, not travel order: the Planner must re-order.
const SEGMENTS: Segment[] = [
  { id: "US-50:echo-summit", routeId: "US-50", name: "Echo Summit", lat: 38.8124, lon: -120.03 },
  { id: "US-50:placerville", routeId: "US-50", name: "Placerville", lat: 38.7296, lon: -120.7985 },
  { id: "US-50:south-lake-tahoe", routeId: "US-50", name: "South Lake Tahoe", lat: 38.9399, lon: -119.9772 },
];
const FORECAST: ForecastResponse = {
  routeId: "US-50",
  fromSegmentId: "US-50:placerville",
  toSegmentId: "US-50:south-lake-tahoe",
  departureUtc: "2026-01-12T15:00:00+00:00",
  generatedAtUtc: "2026-01-12T15:02:00+00:00",
  segments: [
    {
      segment: SEGMENTS[1],
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

describe("App - plan a route and show the live forecast", () => {
  beforeEach(() => {
    // Clear call history so one test's getForecast call does not leak into the
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
    vi.spyOn(routesApi, "getRoutes").mockResolvedValue([ROUTE]);
    vi.spyOn(segmentsApi, "getSegments").mockResolvedValue(SEGMENTS);
    vi.spyOn(forecastApi, "getForecast").mockResolvedValue(FORECAST);
  });

  // The selects mount empty and fill in after getRoutes/getSegments resolve;
  // wait for the default start (first town in travel order) before interacting.
  const waitForTowns = () =>
    waitFor(() =>
      expect(
        (screen.getByLabelText(/starting from/i) as HTMLSelectElement).value,
      ).toBe("US-50:placerville"),
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

  it("shows the live forecast after planning, in travel order", async () => {
    render(<App />);
    await waitForTowns();

    fireEvent.click(screen.getByRole("button", { name: /get the forecast/i }));

    expect(
      await screen.findByRole("heading", { name: /forecast along your route/i }),
    ).toBeInTheDocument();
    // The regime label is unique to the card (town names also appear as options).
    expect(screen.getByText("SNOW")).toBeInTheDocument();
    expect(forecastApi.getForecast).toHaveBeenCalledTimes(1);
  });

  it("blocks planning when start and destination are the same", async () => {
    render(<App />);
    await waitForTowns();

    const start = screen.getByLabelText(/starting from/i) as HTMLSelectElement;
    const end = screen.getByLabelText(/driving to/i) as HTMLSelectElement;
    fireEvent.change(end, { target: { value: start.value } });
    expect(end.value).toBe(start.value); // the change registered
    fireEvent.click(screen.getByRole("button", { name: /get the forecast/i }));

    expect(screen.getByText(/pick two different places/i)).toBeInTheDocument();
    expect(forecastApi.getForecast).not.toHaveBeenCalled();
  });
});
