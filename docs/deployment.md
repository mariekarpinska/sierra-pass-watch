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

---

## Why scheduled batch ingestion, and not a constantly-running Kafka loop

This is the most important design question, so here it is head-on.

**The streaming loop (producer → Kafka → consumer) is a demo, not the
production path.** The project has it to show the pattern — a durable,
replayable log between "fetch data" and "store data" — and it's the right tool
*when data arrives fast and never stops*. But this data does not. The sources
are public weather and crash APIs that change slowly: new weather readings every
few minutes at most, new crash records once a year. At that pace, keeping a
Kafka broker and a consumer process running 24/7 buys you nothing — you'd be
paying (in money and in "something that has to stay up") for throughput you'll
never use. The pipeline's own consumer says this out loud in its docstring:
"a plain scheduled poller writing straight to Postgres would meet the same
dashboard need."

So the production path is the **batch path**: once a day, a job wakes up, fetches
what's new, rebuilds the tables the API serves, and exits. This is
[ADR-0006](adr/0006-data-plane.md)'s "two ingestion paths on purpose" — the
streaming one to demonstrate, the batch one to actually run.

**What running the streaming loop constantly would actually take:**

- A Kafka broker that is always on (a managed one like AWS MSK, or a container
  you keep running). That is the single biggest always-on cost, for a message
  rate a laptop could handle in its sleep.
- A consumer process that is always on, connected to both Kafka and Postgres,
  restarted automatically if it dies.
- A producer process that is always on, polling the sources on a timer.
- Monitoring, so you notice when any of those three quietly stops.

That's three long-running processes plus a broker, to move a trickle of data.
The batch job replaces all of it with one script that runs for a minute a day.

### Could we just run the stream constantly on a PC, pushing straight to the database?

Technically, yes. We can run `docker compose up` (Postgres + Kafka), start
`pipeline.producer` and `pipeline.consumer`, and it will happily stream into
Postgres for as long as the machine stays on. That's exactly what the README's
"full streaming stack" section is for, and it's the best way to *see* the
streaming path work.

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
3. runs `dbt build` — rebuilds the marts the API serves **and runs dbt's data
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
- **ECR (image storage):** cents; old images auto-expire (keep last 10).

The deliberately-not-chosen costs are the point: no always-on Kafka broker, no
always-on consumer, no Spark cluster, no orchestration server. Those were all
considered and rejected for this scale ([ADR-0006](adr/0006-data-plane.md),
[ADR-0011](adr/0011-deployment-and-cicd.md)).

---

## Related docs

- [infra/cdk/README.md](../infra/cdk/README.md) — the exact commands to stand this up
- [ADR-0011](adr/0011-deployment-and-cicd.md) — the deployment/CD decision and alternatives
- [ADR-0006](adr/0006-data-plane.md) — why batch and streaming both exist
- [architecture.md](architecture.md) — the system overview
