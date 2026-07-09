import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { App } from "./App";
import * as healthApi from "./api/health";

// Route sections render Leaflet maps, which need real DOM measurements jsdom
// does not provide. Stub Leaflet with a chainable no-op so those components can
// mount; the map rendering itself is out of scope for these tests.
vi.mock("leaflet", () => {
  const chain: Record<string, unknown> = {};
  const self = () => chain;
  for (const method of [
    "addTo",
    "setView",
    "remove",
    "bindPopup",
    "bindTooltip",
    "getBounds",
    "pad",
    "fitBounds",
    "invalidateSize",
  ]) {
    chain[method] = self;
  }
  const factory = () => chain;
  return {
    default: {
      map: factory,
      tileLayer: factory,
      layerGroup: factory,
      polyline: factory,
      circleMarker: factory,
      marker: factory,
      divIcon: factory,
    },
  };
});

vi.mock("./api/health", { spy: true });

// The backend status indicator (footer) calls getHealth on mount. These tests
// drive that call directly.
describe("App — backend health round-trip", () => {
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

describe("App — Sierra Pass Watch mockup", () => {
  beforeEach(() => {
    // jsdom implements none of scrollIntoView (App calls it after planning),
    // IntersectionObserver (useReveal drives scroll-reveal animations), or
    // ResizeObserver (useLeafletMap re-measures the map container). Stub all
    // three so the route sections mount; none is what these tests verify.
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
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe = vi.fn();
        unobserve = vi.fn();
        disconnect = vi.fn();
      },
    );
    // Keep the footer's health call pending so it never updates state during
    // these tests — the backend round-trip is covered above, not here.
    vi.spyOn(healthApi, "getHealth").mockReturnValue(new Promise(() => {}));
  });

  it("renders the planner and shows no route results initially", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: /where are you headed\?/i }),
    ).toBeInTheDocument();
    // The route overview only exists once a route has been planned.
    expect(
      screen.queryByRole("heading", { name: /your passage/i }),
    ).not.toBeInTheDocument();
  });

  it("reveals the route results after planning a route", () => {
    render(<App />);

    // Default selection is Auburn -> Kirkwood (two different towns).
    fireEvent.click(screen.getByRole("button", { name: /draw the route/i }));

    // The overview heading renders the chosen start and destination.
    expect(
      screen.getByRole("heading", { name: /auburn.*kirkwood/i }),
    ).toBeInTheDocument();
  });

  it("keeps results hidden when start and destination are the same", () => {
    render(<App />);

    const start = screen.getByLabelText(/starting from/i) as HTMLSelectElement;
    const end = screen.getByLabelText(/driving to/i);
    // Force both selects to the same town.
    fireEvent.change(end, { target: { value: start.value } });
    fireEvent.click(screen.getByRole("button", { name: /draw the route/i }));

    expect(
      screen.queryByRole("heading", { name: /your passage/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/pick two different places/i),
    ).toBeInTheDocument();
  });
});
