# 0011. Deployment & CI/CD: AWS, OIDC, and scheduled batch ingestion

2026-07-15

## Context

Moving the app to a cloud deployment raises three decisions:

1. **Where the app runs** — frontend, backend, and database.
2. **How code gets there** — the deploy pipeline, and how it authenticates to
   the cloud safely.
3. **How the data refreshes** — on what trigger, using which of the two
   ingestion paths [ADR-0006](0006-data-plane.md) already defines.

Plain-English background for all of this is in
[docs/deployment.md](../deployment.md); this ADR records the decision and the
roads not taken.

## Decision

- **Cloud: AWS.** Frontend as static files in **S3**, served by **CloudFront**
  (a CDN). Backend (FastAPI) as a container on **App Runner**. Database on
  **Neon** (hosted Postgres) today, moving to **AWS RDS** later.
- **Deploy: GitHub Actions with OIDC**, no stored AWS keys. A push to protected
  `main` builds the image, pushes to **ECR**, and redeploys App Runner; builds
  the site and syncs it to S3 + invalidates CloudFront.
- **Ingestion: a scheduled GitHub Actions cron** (`ingest.yml`) running the
  **batch** path — refresh weather, `dbt build` — against the cloud Postgres.
  No Kafka, no always-on process.
- **Infrastructure as code: AWS CDK (TypeScript)** under `infra/cdk/`.

---

### Why AWS (and App Runner specifically)

The target is one cloud account with one bill and one set of access controls —
compute, storage, secrets, and identity in one place. The prior version ran on
GCP, so choosing AWS here was partly a deliberate stretch: App Runner and
S3/CloudFront deployment were new to me, and I wanted to learn AWS's native
deployment story end to end. Familiarity is a light tiebreaker, not the driver —
other clouds (GCP, Azure) were weighed, and AWS won on consolidating the whole
stack in one place. Within AWS, the backend host is the load-bearing
sub-decision:

- **App Runner (chosen).** You hand it a container image and a port; it runs it,
  scales it, gives it HTTPS and a URL. No VPC, load balancer, cluster, or task
  definitions to wire by hand. At this size that is exactly the right amount of
  machinery.
- **ECS/Fargate (rejected for now).** More control (fine-grained networking,
  sidecars), but a lot more to stand up and reason about. It's the scale-up path
  when the networking actually needs that control — not today.
- **Lambda + API Gateway (rejected).** Cheapest at true idle (scales to zero),
  but adds cold starts and a FastAPI-to-Lambda adapter (Mangum). More moving
  parts in the request path for a service that's fine staying warm.

Frontend on S3 + CloudFront is the standard, cheap, boring choice for a static
single-page app and needs no defending.

### Why AWS CDK, not Terraform

The infrastructure is written in **AWS CDK (TypeScript)** rather than Terraform.
For a single-cloud, TypeScript-leaning project it fit better on three counts: the
infra is in the **same language** as the frontend (one toolchain, shared types),
there is **no state file** to store and protect (CloudFormation, which CDK
compiles to, holds the state), and **stack outputs** are trivially readable
(`aws cloudformation describe-stacks`).

The honest trade-offs:

- **Terraform** is cloud-agnostic and can manage non-AWS things (a database
  provider, GitHub itself) in one tool; here everything is AWS, so that strength
  goes unused. It's the stronger pick the moment multi-cloud or provider-as-code
  matters.
- **CDK runs on CloudFormation**, which can be slower and its errors terser than
  Terraform's `plan`. Accepted for the consistency and no-state wins.
- **CDKTF** (Terraform written in TypeScript) would give the language win on
  Terraform's engine, but it's the least mature of the three and buys nothing here.

### Why OIDC, not access keys

Storing a long-lived AWS access key in GitHub means a credential that grants
standing account access until it's rotated — a leak waiting to happen. OIDC
replaces it with a per-run, minutes-long credential that AWS hands out only to a
token proving it came from **this repo on `main`**. Nothing long-lived is stored;
there's no key to leak. The deploy role is also scoped to the few actions a
deploy needs, on the specific resources it touches. The full token-exchange
walk-through is in [docs/deployment.md](../deployment.md).

Combined with **branch protection** on `main` (PR + review required), this means
only reviewed code can deploy, and only invited collaborators can get code onto
`main` in the first place.

### Why scheduled batch ingestion, not the streaming loop

The daily GitHub Actions cron (`ingest.yml`) runs the batch path (fetch →
Postgres → `dbt build`) with no always-on broker. It runs for about a minute a
day and leaves nothing switched on.

> **Refined by [ADR-0012](0012-direct-poll-ingestion.md) (2026-07-21):** Kafka
> is now gone entirely (this ADR originally weighed batch against a streaming
> Kafka loop). Two schedules remain, both broker-free: a frequent poll worker
> (every 1–2 minutes, EventBridge → Lambda) that collects live CHP collisions
> with their weather, and this daily cron that rebuilds the marts over what the
> poller has accumulated. CCRS crash refresh stays on-demand/annual.

### Why Neon now, RDS later

Getting live *today* on a free, zero-maintenance Postgres beats blocking on RDS
setup. The app only ever sees a `DATABASE_URL`, so the database host is invisible
to the code, and moving to RDS is a CDK addition plus a `pg_dump`/`restore` plus
swapping one secret — no application changes. See
[docs/deployment.md](../deployment.md) ("Where Postgres lives").

---

## Consequences

- **One always-on cost, on purpose.** App Runner keeps a small container warm.
  Everything else is per-request (CloudFront), scheduled (the cron), or free
  (Neon's tier, Actions on a public repo). The rejected costs — a Kafka broker,
  a Spark cluster — are the whole savings story.
- **Orchestration stays a cron.** The deployed refresh is the GitHub Actions
  cron ([ADR-0006](0006-data-plane.md)), which is enough at this cadence — no
  dedicated orchestration engine or server to run.
- **A two-phase bootstrap.** App Runner can't be created until an image exists in
  ECR, so the registry is a separate stack: deploy it, push one image, then
  deploy the app. Documented in [infra/cdk/README.md](../../infra/cdk/README.md).
  After that, deploys are fully automatic.
- **Secrets never touch the repo — or the infra code.** The database URL lives in
  an encrypted SSM SecureString created out of band; the CDK app only references
  it by ARN, and CDK keeps no local state file to protect. The ingest job reads
  the same URL from a GitHub secret.
