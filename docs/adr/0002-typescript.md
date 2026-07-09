# 0002. TypeScript over JavaScript

2026-07-07

## Context

The frontend consumes a JSON API contract shared with the FastAPI backend (see
[0004](0004-backend-framework.md)). If a field gets renamed or reshaped on one
side — say the backend starts returning `crashCount` instead of `crash_count`
— plain JavaScript won't notice. The panel just renders blank, and the bug is
found by clicking around, not by the tooling.

## Decision

Use **TypeScript** instead of plain JavaScript for the frontend.

Types turn that class of bug into a compile error instead of a runtime
surprise: the API response shape is declared once, and any code that reads a
field that doesn't exist fails to build.

## Alternatives considered

- **Plain JavaScript** — no build step, but no way to catch contract drift
  between frontend and backend before the browser does.

## Consequences

TypeScript's types are erased at build time, so there's no runtime cost or
behavior change — this is a dev-time-only tradeoff. In exchange: editor
autocomplete on API responses, and refactors (renaming a field, changing a
shape) that the compiler will verify instead of a manual grep.
