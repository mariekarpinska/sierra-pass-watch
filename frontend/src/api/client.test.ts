import { describe, expect, it } from "vitest";
import { AxiosError, AxiosHeaders } from "axios";
import { api, isAppError, toAppError } from "./client";

/** Build a minimal AxiosError the way axios itself would. */
function makeAxiosError(opts: {
  code?: string;
  status?: number;
}): AxiosError {
  const config = { headers: new AxiosHeaders() };
  return new AxiosError(
    "boom",
    opts.code,
    config as never,
    undefined,
    opts.status !== undefined
      ? ({
          status: opts.status,
          statusText: "",
          data: { detail: "internal stack trace — must not leak" },
          headers: {},
          config: config as never,
        } as never)
      : undefined,
  );
}

describe("toAppError — the response interceptor's normalization table", () => {
  it("maps a timeout to kind=timeout", () => {
    const err = toAppError(makeAxiosError({ code: "ECONNABORTED" }));
    expect(err.kind).toBe("timeout");
  });

  it("maps a 5xx response to kind=http with its status", () => {
    const err = toAppError(makeAxiosError({ status: 503 }));
    expect(err).toMatchObject({ kind: "http", status: 503 });
  });

  it("maps a 4xx response to kind=http with its status", () => {
    const err = toAppError(makeAxiosError({ status: 404 }));
    expect(err).toMatchObject({ kind: "http", status: 404 });
  });

  it("never leaks the server error body into the message", () => {
    const err = toAppError(makeAxiosError({ status: 500 }));
    expect(err.message).not.toContain("stack trace");
  });

  it("maps a no-response failure to kind=network", () => {
    const err = toAppError(makeAxiosError({ code: "ERR_NETWORK" }));
    expect(err.kind).toBe("network");
  });

  it("maps a non-axios throw to kind=unknown", () => {
    const err = toAppError(new Error("some bug"));
    expect(err.kind).toBe("unknown");
  });

  it("produces objects that satisfy the isAppError guard", () => {
    expect(isAppError(toAppError(new Error("x")))).toBe(true);
    expect(isAppError(new Error("x"))).toBe(false);
  });
});

describe("api instance — interceptors end to end (no real network)", () => {
  it("attaches a correlation id header to every request", async () => {
    // Swap the network layer (the adapter) for a stub; interceptors still run.
    const response = await api.get("/api/anything", {
      adapter: async (config) => ({
        data: { ok: true },
        status: 200,
        statusText: "OK",
        headers: {},
        config,
      }),
    });
    const cid = response.config.headers.get("X-Correlation-Id");
    expect(cid).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("rejects with a normalized AppError, not a raw AxiosError", async () => {
    const failure = api.get("/api/anything", {
      adapter: async () => {
        throw makeAxiosError({ status: 502 });
      },
    });
    await expect(failure).rejects.toMatchObject({ kind: "http", status: 502 });
  });
});
