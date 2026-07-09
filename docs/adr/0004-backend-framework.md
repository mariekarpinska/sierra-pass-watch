# 0004. Backend framework: FastAPI (Python)

2026-07-08

## Context

The backend is a thin, read-mostly API: four endpoints that fan out queries
to Postgres and serve the React frontend over a typed JSON contract (see
[0002](0002-typescript.md)). The rest of the system — the Kafka consumer,
dbt orchestration, and the weather-regime classifier in
`pipeline/regime.py` — is already Python, and the API must apply the *same*
regime classification the pipeline does: two implementations of that logic
could drift.

## Decision

Use **FastAPI (Python)**, with **Pydantic** for the request/response models.

Pydantic is not incidental to this choice — it's the reason FastAPI answers
the contract-drift worry that drove the TypeScript decision ([0002](0002-typescript.md)).
Every endpoint declares its response as a Pydantic model, so a malformed
payload fails loudly at the boundary instead of reaching the browser, and
FastAPI derives the OpenAPI schema from those same models — the single
source the frontend's TypeScript types are generated against. One shape,
declared once, enforced on both sides.

The deciding factor is familiarity: I've shipped FastAPI APIs before, and
the prior codebase (`sierra-safety-index`) was Python end to end.

It also stands on its own technically:

- **One classifier, imported, not ported.** The API imports
  `pipeline/regime.py` directly, so exactly one regime implementation
  exists, and the golden file `shared/weather-regime-cases.json` is
  asserted by both the pipeline and API test suites. 
- **The workload is I/O-bound, so async covers it.** This API mostly waits rather than performs heavy compute — so async is a good fit. This API plans to mostly wait on Postgres to respond, not crunch numbers. async/await lets one process handle many of those waiting requests at the same time, without needing a separate thread for each one. People sometimes worry that Python's GIL (which stops threads from truly running Python code in parallel) would cancel out this benefit — but the GIL only gets in the way when you're doing heavy computation, and this API isn't planning to.

## Alternatives considered

- **.NET / C#** — *the original choice, later reversed.* It offered real
  advantages: the compiler checks your data contracts for you, it runs
  noticeably faster per CPU core, and it handles many requests at once
  without Python's GIL. But those trade offs aren't really seen if this pans out to be an I/O-bound four-endpoint API as expected. The costs, though, were real: I'd have to
  port the regime classifier to C# and keep two copies in sync with the
  Python original, and I'd be learning a new stack, which I love to learn new tools and stacks, but FastAPI won here.
- **Flask (Python)** — smaller and simpler, but built for synchronous code
  first (async is added on top through an ASGI adapter layer). It also
  gives you no request validation and no automatic API docs, so I'd end up
  hand-writing what FastAPI includes out of the box.
- **Django (Python)** — comes with a lot built in: a database layer, an
  admin interface, and user authentication. This project needs none of it —
  no admin screen, no user accounts, mostly-read endpoints. More framework
  than the job calls for.
- **Node.js (Express)** — genuinely tempting: it handles concurrent
  requests naturally through its event loop, and it lets me use one
  language (TypeScript) across both frontend and backend. But it splits the
  API away from the Python pipeline, bringing back the exact problem
  FastAPI avoids — maintaining a second copy of the classifier in another
  language.
- **Java (Spring Boot)** — strong static typing and true parallel
  processing on the JVM, but a slow write-compile-test cycle and a lot of
  boilerplate for a four-endpoint service; the same cross-language
  classifier cost as .NET.

## Consequences

What's given up, and how each is handled:

- **No compile-time contract check on the backend.** Mitigated three ways:
  Pydantic response models fail loudly at runtime instead of returning a
  malformed payload, type hints can be checked with mypy in CI, and the
  golden-file tests can pin the contract on both frontend and backend.
- **Lower per-core throughput than a compiled runtime.** Irrelevant at
  this scale — a single small instance serving read-mostly traffic, where
  Postgres, not the framework, is the bottleneck.
- **The GIL caps CPU-bound parallelism.** Accepted: the API plans to have no
  CPU-bound path. 
- **No "learn a new backend ecosystem" credit.** Traded deliberately for
  showcasing FastAPI familiarity.
