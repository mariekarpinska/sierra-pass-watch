# 0001. Frontend framework: React

2026-07-07

## Context

The frontend renders an interactive UI: 
- the user can select their start and end location and pick their route
- they see a forecast strip with weather forecast along their route
- they see crash hot spots along the route with a leaflet hotspot map in similar weather to today
- a table breaks down the top crash causes to watch out for

All four panels react to one shared selection (the chosen route and date), so
state has to be lifted and synchronized across sibling components, not just
local to one widget.

The earlier prototype was a Streamlit dashboard, and it worked: it answered
the product question. So the bar here is not "can this be built" — it's "does
the choice demonstrate the full-stack engineering this repo exists to show."
A single Streamlit script hides the frontend/backend boundary. A real SPA
talking to a separate FastAPI backend over a typed contract *is* the demonstration:
API design, client-side data-fetching and cache, and an explicit HTTP layer
are all skills a dashboard script never exercises.

## Decision

Use **React** (with Vite + TypeScript).

I'm comfortable with it, so the effort goes into building the UI, data layer, and
the API contract rather than learning a new framework, although I love learning new tools. React's ecosystem also
covers this app's exact needs directly — `react-leaflet` for the map,
`Recharts` for breakdowns, TanStack Query for server-state — so integration is
off-the-shelf, not bespoke.

## Alternatives considered

- **Streamlit** (the earlier prototype) — fastest to a chart, but no real
  component model, no client-side routing, and a server round-trip per
  interaction. Decisively, it collapses the client/server split into one
  Python process, so it can't showcase full-stack work — the reason for the
  rebuild.
- **Vue** — comparable component model with a gentler template syntax, but its US-market and third-party ecosystem (map, charts,
  data-fetching) is thinner than React's. 
- **Angular** — batteries-included (router, DI, forms, RxJS), which is exactly
  the weight this single-view SPA doesn't need. The opinionated framework tax
  and steeper ramp buy structure the app is too small to use.
- **Svelte / SvelteKit** — less boilerplate and no runtime shipped, genuinely
  appealing, but a smaller ecosystem for Leaflet/charts and another framework
  to learn.
- **Astro** — excellent for content-first, mostly-static sites with islands of
  interactivity. This is the inverse: a stateful, fully interactive app where
  every panel reacts to the same selection. Astro's MPA/islands model would
  fight that shared client state.

## Consequences

React trades Streamlit's quick-start for control: more upfront setup, but the
component model, routing, and coupled client-side interaction the UI needs are
native instead of worked around. It also commits us to the SPA + separate API
architecture — to show case full stack development skills, and which the rest of these ADRs
(TypeScript, the axios layer, the FastAPI backend) build on.
