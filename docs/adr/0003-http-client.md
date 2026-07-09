# 0003. HTTP client: Axios over fetch

## Context

Every frontend request needs the same cross-cutting concerns handled
consistently: base URL, auth header, error normalization, request IDs.

## Decision

Use Axios, not `fetch`.

One interceptor layer is the single place those concerns live, instead of
being hand-rolled and re-wired at every call site.

## Alternatives considered

- **`fetch`** — can do everything Axios does, but each call site has to
  hand-roll and re-wire the same cross-cutting logic since there's no
  built-in interceptor layer.

## Consequences

Axios trades a small dependency for one choke point. See
[docs/frontend-axios-interceptors.md](../frontend-axios-interceptors.md) for
the interceptor setup.
