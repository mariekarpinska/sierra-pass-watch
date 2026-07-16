# AWS infrastructure (CDK, TypeScript)

This folder defines the whole Sierra Safe cloud footprint as an **AWS CDK** app:
the GitHub OIDC trust that lets deploys run without stored keys, an ECR registry,
the App Runner service for the FastAPI backend, and an S3 + CloudFront site for
the React frontend.

Plain-English background — why AWS, why App Runner, how OIDC works, why CDK — is
in [docs/deployment.md](../../docs/deployment.md) and
[ADR-0011](../../docs/adr/0011-deployment-and-cicd.md). This file is the runbook.

## What you need first

- Node.js ≥ 22 and `npm`.
- The AWS CLI logged in (`aws configure` or SSO).
- A Postgres database URL (Neon today). See docs/deployment.md for creating one.

```powershell
cd infra/cdk
npm install
# Set your GitHub username in cdk.json (githubOwner), or pass -c on every command.
```

## First-time setup (the order matters)

App Runner can't be created until an image exists in ECR, so the registry is a
separate stack: deploy it, push one image, then deploy the app.

```powershell
# 0. One-time per account/region: prepare the account for CDK.
npx cdk bootstrap

# 1. Store the database URL as an encrypted SSM parameter (out of band, so the
#    secret never sits in the CDK app or its template).
aws ssm put-parameter --name "/sierra-safe/database_url" --type SecureString `
  --value "postgresql://user:pass@host/db?sslmode=require"

# 2. Create the registry FIRST.
npx cdk deploy SierraSafeRegistry

# 3. Push one backend image so App Runner has something to start. (Repo root.)
$REGION  = "us-west-2"
$ACCOUNT = (aws sts get-caller-identity --query Account --output text)
$ECR     = "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/sierra-safe-backend"
aws ecr get-login-password --region $REGION | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
docker build -f backend/Dockerfile -t "${ECR}:latest" .
docker push "${ECR}:latest"

# 4. Now deploy the rest (App Runner, S3, CloudFront, the OIDC role).
npx cdk deploy SierraSafe
```

If `domainName` is set in `cdk.json`, step 4 also brings up the certificate stack
and pauses for a DNS record. See "Custom domain" below before running it.

After step 4, the stack outputs (printed by `cdk deploy`, or `aws cloudformation
describe-stacks`) are what GitHub needs. From then on, deploys are automatic on
push to `main` — you never run these build/push commands by hand again.

## Wire the outputs into GitHub

In the GitHub repo, **Settings → Secrets and variables → Actions**:

| CDK output                 | GitHub name                  | Kind     |
| -------------------------- | ---------------------------- | -------- |
| `GithubDeployRoleArn`      | `AWS_ROLE_ARN`               | Secret   |
| `EcrRepositoryUri`         | `ECR_REPOSITORY`             | Variable |
| `AppRunnerServiceArn`      | `APPRUNNER_SERVICE_ARN`      | Variable |
| `AppRunnerServiceUrl`      | `VITE_API_BASE_URL`          | Variable |
| `FrontendBucketName`       | `FRONTEND_BUCKET`            | Variable |
| `CloudFrontDistributionId` | `CLOUDFRONT_DISTRIBUTION_ID` | Variable |
| (your region, e.g. us-west-2) | `AWS_REGION`              | Variable |

The scheduled ingestion workflow additionally needs the database URL as a secret
named `DATABASE_URL` (the same value you put in SSM above).

## Custom domain (optional)

The site runs on CloudFront's default `*.cloudfront.net` name unless you set
`domainName` in `cdk.json` (today: `sierrapasswatch.com`). When set, CDK adds a
third stack, `SierraSafeCertificate`, holding the TLS certificate. It has to live
in `us-east-1` because that's the only region CloudFront reads certificates from,
so it's a separate stack the main one references across regions.

The domain's DNS is at **Cloudflare**, not Route 53, so you add two rounds of DNS
records there by hand. Keep every record **DNS only (grey cloud)** — CloudFront
terminates HTTPS with the certificate, so Cloudflare should not proxy.

```powershell
# 1. Deploy the certificate. It pauses and prints a CNAME (name + value) to
#    prove you own the domain. Add that CNAME at Cloudflare (grey cloud). ACM
#    validates within minutes and the deploy finishes on its own.
npx cdk deploy SierraSafeCertificate

# 2. Deploy the site. `CloudFrontDomain` in the output is the CNAME target.
npx cdk deploy SierraSafe
```

Then, at Cloudflare, add the final records (DNS only / grey cloud), pointing at
the `CloudFrontDomain` value from step 2, e.g. `d123abc.cloudfront.net`:

| Type  | Name  | Target                  |
| ----- | ----- | ----------------------- |
| CNAME | `@`   | `d123abc.cloudfront.net` |
| CNAME | `www` | `d123abc.cloudfront.net` |

Cloudflare flattens the `@` (apex) CNAME automatically, so the bare domain and
`www` both resolve to CloudFront.

## Moving the database to RDS later

Today the SSM parameter points at Neon. To move to AWS RDS, add an
`rds.DatabaseInstance` in `lib/`, update the SSM parameter to the RDS endpoint,
and `cdk deploy`. Nothing in the app changes — it reads a connection string
either way. See docs/deployment.md ("Where Postgres lives").

## Everyday commands

```powershell
npx cdk diff       # what would change
npx cdk deploy     # apply (both stacks; add a stack name to scope it)
npx cdk synth      # print the CloudFormation template (no AWS needed)
npx cdk destroy    # tear it down (Neon, a separate service, is untouched)
```
