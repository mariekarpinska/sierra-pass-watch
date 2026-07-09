import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "./App";
import * as healthApi from "./api/health";

vi.mock("./api/health", { spy: true });

describe("App — health round-trip page", () => {
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
