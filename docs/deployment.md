# Deployment & scheduled ingestion

This is the plain-English guide to how Sierra Pass Watch goes live and how its data
stays fresh, with no machine left switched on. The runbook — the exact commands —
lives in [infra/cdk/README.md](../infra/cdk/README.md); this file is the *why*.

Two separate things happen in the cloud, and it helps to keep them apart:

1. **Deploy** — ship the website and the API when code changes.
2. **Ingest** — refresh the data on a schedule.

They use different triggers (a code push vs. a clock) and are wired up
separately ([deploy.yml](../.github/workflows/deploy.yml) and
[ingest.yml](../.github/workflows/ingest.yml)).

---

## The shape of it

```
          ┌─────────────────────────── GitHub ───────────────────────────┐
          │                                                               │
  push to main ─▶ deploy.yml                     clock (daily) ─▶ ingest.yml
          │           │                                               │    │
          │           ├─ build API image ─▶ ECR ─▶ App Runner         │    │
          │           └─ build site ─▶ S3 ─▶ CloudFront               │    │
          │                                                           │    │
          └───────────────────────────────────────────────────────────────┘
                                      │                               │
                                      ▼                               ▼
                             users hit CloudFront            weather refresh +
                             (site) → App Runner (API)       dbt build → Postgres
                                                                     │
                                                                     ▼
                                                            Neon (Postgres) today,
                                                            AWS RDS later
```

Everything runs on **AWS**, except the database, which is on **Neon** for now
(a hosted Postgres) and moves to **AWS RDS** later. Why that split is below.

Ingestion is not shown above because it is not on GitHub's clock alone: a third
scheduled path, an **EventBridge rule firing a Lambda every ~1–2 minutes**, runs
the poll worker to collect live CHP collisions and alerts straight into Postgres
(ADR-0012). It leaves nothing switched on between firings, same as the daily
cron. See "Two schedules, no broker" below.

---

## Two schedules, no broker

There is no message broker anywhere (ADR-0012). Ingestion is two broker-free
schedules, each writing straight to Postgres with `ON CONFLICT` idempotency:

1. **A frequent poll worker**, every ~1–2 minutes, that collects live CHP
   collisions (each paired with the weather at its point) and road-state alerts.
   CHP is a *live* feed (events age out), so it has to be polled often to catch
   anything. Deployed as **EventBridge → Lambda**: a scheduled rule fires the
   worker, the Lambda runs one cycle and exits, and nothing stays switched on
   between firings. Frequency and transport are separate concerns; frequent
   collection never needed a broker.
2. **A daily batch cron** (`ingest.yml`) that refreshes recent weather, tops up
   any collision the on-collision fetch missed, and rebuilds the dbt marts over
   everything the poll worker has accumulated. It runs for about a minute a day.

Earlier this ran a Kafka producer/consumer as the streaming demonstration.
[ADR-0012](adr/0012-direct-poll-ingestion.md) removed it: at this volume the
broker never had enough to do, and the on-collision weather fetch made the poll
worker a genuinely useful pipeline rather than a health check. The
`ON CONFLICT` idempotency that made a Kafka replay safe is still on every write.

**Why not keep a long-running process (broker or not) always on?**

- A constantly-running process is a constantly-running cost and one more thing
  that has to stay up, for a trickle of data a scheduled invocation handles.
- A serverless invocation (EventBridge → Lambda for the poll worker, GitHub
  Actions for the daily build) leaves nothing switched on and restarts cleanly
  every firing.

### Could we just run ingestion constantly on a PC, pushing straight to the database?

Technically, yes. We can run `docker compose up` (Postgres), start
`python -m pipeline.poller`, and it will happily write into Postgres for as long
as the machine stays on. That's exactly what the README's "full stack" section
is for, and it's the best way to *see* the ingestion path work.

But as a way to keep a live website's data fresh, it's the wrong tool — for
reasons that have nothing to do with the code:

- **The machine has to never sleep, reboot, lose Wi-Fi, or close its lid.** The
  moment it does, the data stops refreshing and nobody knows.
- **A home IP becomes the source of truth.** If the API is in the cloud but the
  data is produced from a laptop at home, the whole thing depends on that one
  router.
- **No retries, no history, no alerting.** If a nightly fetch fails at 3am, a
  scheduled cloud job records the failure and we see it in the morning. A script
  on a local PC just silently didn't run.

The scheduled GitHub Actions job (`ingest.yml`) solves all three by running on
GitHub's machines on a timer — nothing local has to be on. That is the whole
point of "hands-off."

---

## Where Postgres lives

There are **three** Postgres databases in this project's life:

| Which                   | Where it physically is                                   | When it's used                          |
| ----------------------- | -------------------------------------------------------- | --------------------------------------- |
| **Local dev**           | A Docker container on your machine, data in a Docker volume (`postgres-data`) | `docker compose up` while you develop |
| **CI**                  | A throwaway Postgres that GitHub starts and destroys per run | The `warehouse` job in `ci.yml`      |
| **Production**          | **Neon** (hosted Postgres, its own servers) today; **AWS RDS** later | The live API + the daily ingest job |

### Why Neon now, RDS later

- **Neon** is hosted Postgres with a free tier that (unlike some free tiers)
  doesn't delete your database after 90 days. It's a connection string and
  nothing to manage — perfect for getting live *today* and for a project that
  must keep working months from now. The app only ever sees a connection string
  (`DATABASE_URL`), so Neon is invisible to the code.
- **AWS RDS** is the eventual home, so the whole stack lives in one account with
  one bill and one set of IAM controls. Moving there is a small, contained
  change: add an `rds.DatabaseInstance` in the CDK app, point `DATABASE_URL` at
  the new endpoint, `cdk deploy`. **No application code changes** — `connect()` and
  the API read a connection string either way. The migration is a data copy
  (`pg_dump | pg_restore`) plus swapping one secret.

The one Postgres-specific detail that matters for a hosted DB: it requires an
encrypted connection (`sslmode=require` in the URL). Local Docker doesn't. Both
the pipeline and dbt handle this from the environment, so the same code targets
both.

---

## How the deploy works, and what OIDC actually does

**The old, bad way:** create an AWS access key + secret, paste them into GitHub
as secrets, and let the workflow use them. Those are long-lived keys. If they
ever leak (a bad log line, a compromised action), someone has standing access to
your AWS account until you notice and rotate them. You don't want them to exist.

**The way this repo does it — OIDC, no stored keys.** OIDC ("OpenID Connect") is
just a trust handshake. Here's the whole exchange in plain terms:

1. When `deploy.yml` runs, GitHub mints a short-lived **token** for that
   specific run. The token is a signed statement: *"I am run #123 of repo
   `you/sierra-pass-watch`, on branch `main`."* GitHub signs it so it can't be
   forged.
2. The workflow hands that token to AWS and says "I'd like to be the deploy
   role."
3. AWS was told once, by the CDK app, to **trust tokens from GitHub** — but only
   if the statement inside matches a rule: the repo must be *yours* and the
   branch must be *main* (see the `sub` condition in
   [lib/sierra-pass-watch-stack.ts](../infra/cdk/lib/sierra-pass-watch-stack.ts)). AWS checks GitHub's signature,
   checks the claims against the rule, and if both pass, hands back **temporary
   credentials that expire in minutes.**
4. The workflow uses those minutes-long credentials to push the image and deploy,
   then they evaporate.

Nothing long-lived is ever stored. There is no key to leak. A token from a fork,
from another branch, or from someone else's repo produces a `sub` claim that
fails the rule, so AWS refuses it. This is why the trust policy is scoped to
*exactly one repo and one branch*.

```
GitHub run ──(signed token: "repo=you/repo, branch=main")──▶ AWS STS
                                                              │
                              rule: repo must match AND branch=main
                                                              │
                                    ✓ pass ──▶ temporary creds (expire in minutes)
                                    ✗ fail ──▶ refused
```

### Why "protected main" makes this safe

The rule above says *only pushes to `main` can deploy*. On its own that's not
enough — anyone who could push to `main` could deploy. Two GitHub settings close
that gap, and you set them in the repo's **Settings → Branches → Branch
protection rules** for `main`:

- **Require a pull request before merging** (and require it to be reviewed).
  Now nobody pushes straight to `main`; code only lands via a PR that was looked
  at. Since only `main` deploys, **only reviewed code can ever deploy.**
- **Restrict who can push / who the collaborators are.** A private repo is only
  visible to people you invite; branch protection controls who can merge. So
  "only people I invite can contribute, and even they go through review" is
  enforced by GitHub, and the deploy pipeline inherits that guarantee for free.

The deploy role's permissions are also deliberately tiny (see the deploy role in
`infra/cdk/lib/sierra-pass-watch-stack.ts`): push to *this one* image repo, redeploy
*this one* service, write *this one* bucket,
clear *this one* CDN. Even in the worst case, a deploy run can't touch anything
else in the account.

---

## The hands-off refresh

**The hands-off refresh** is `ingest.yml`: a scheduled GitHub Actions job that,
once a day, on GitHub's machines:

1. makes sure the database tables exist (idempotent, so it self-heals a fresh DB),
2. fetches the recent weather history,
3. fills the weather on any live collision the on-collision fetch missed
   (ADR-0012), so the mart folds in fully-labelled new rows,
4. runs `dbt build`, which rebuilds the marts the API serves **and runs dbt's data
   tests**, so a broken upstream feed fails the job loudly instead of quietly
   corrupting the dashboard.

Nothing of yours is on. If it fails, GitHub shows a red run and can email you.
That's the whole "hands-off" story: a clock, a short script, a visible history.

### Why a cron, and not a heavier orchestrator

Something has to run "fetch → load → build" in order, on a schedule — that job is
called orchestration. Here it's the GitHub Actions cron, and that's deliberate.
A dedicated orchestration engine (like Prefect or Dagster) adds first-class
retries, backfills, and a pipeline-graph UI — genuinely worth it once you have
many interdependent pipelines and a team watching them. At this project's scale
(one daily fetch-and-build) that's more machinery than the cadence needs, so the
cron is the right amount. If the pipeline count grows, adopting one becomes a
good future decision to write up ([ADR-0006](adr/0006-data-plane.md) records
this choice).

---

## What it costs

- **CloudFront + S3 (frontend):** pennies. Static files and a cheap CDN tier
  (`PriceClass_100`).
- **App Runner (backend):** the one real always-on cost — a small container that
  stays warm. Smallest size (0.25 vCPU / 0.5 GB). Roughly a few dollars a month
  at idle; more only if traffic grows.
- **Neon (database):** free tier today.
- **GitHub Actions (deploy + ingest):** free for a public repo; the daily ingest
  job runs for about a minute.
- **EventBridge + Lambda (poll worker):** negligible. A rule that fires every
  1–2 minutes and a function that runs for a second or two each time, well inside
  the free tier at this rate.
- **ECR (image storage):** cents; old images auto-expire (keep last 10).

The removed and deliberately-not-chosen costs are the point: no message broker
(the Kafka layer was removed in [ADR-0012](adr/0012-direct-poll-ingestion.md)),
no always-on consumer, no Spark cluster, no orchestration server. Those were all
considered and rejected for this scale ([ADR-0006](adr/0006-data-plane.md),
[ADR-0011](adr/0011-deployment-and-cicd.md)).

---

## Related docs

- [infra/cdk/README.md](../infra/cdk/README.md) — the exact commands to stand this up
- [ADR-0011](adr/0011-deployment-and-cicd.md) — the deployment/CD decision and alternatives
- [ADR-0012](adr/0012-direct-poll-ingestion.md): direct-poll ingestion, no broker
- [ADR-0006](adr/0006-data-plane.md): the data-plane choices (dbt, and why not Spark)
- [architecture.md](architecture.md) — the system overview
