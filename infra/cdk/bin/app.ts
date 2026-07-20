#!/usr/bin/env node
// Entry point. Reads non-secret config from CDK context (cdk.json), then builds
// two stacks:
//   1. SierraPassWatchRegistry — the ECR image registry, on its own so it can be
//      created (and an image pushed to it) BEFORE the app that pulls that image.
//   2. SierraPassWatch        — everything else: the OIDC deploy role, the App Runner
//      backend, and the S3 + CloudFront frontend.
// See infra/cdk/README.md for the deploy order and why it's split this way.
import * as cdk from 'aws-cdk-lib';
import { RegistryStack } from '../lib/registry-stack';
import { SierraPassWatchStack } from '../lib/sierra-pass-watch-stack';
import { CertificateStack } from '../lib/certificate-stack';

const app = new cdk.App();

const project = app.node.tryGetContext('project') ?? 'sierra-pass-watch';
const githubOwner = app.node.tryGetContext('githubOwner');
const githubRepo = app.node.tryGetContext('githubRepo') ?? 'sierra-pass-watch';
const githubBranch = app.node.tryGetContext('githubBranch') ?? 'main';

// Optional custom domain. Set `domainName` in cdk.json (e.g.
// "sierrapasswatch.com") to serve the site from it; leave it out and the site
// stays on CloudFront's default *.cloudfront.net name. When set, we cover both
// the bare domain and its www subdomain.
const domainName = app.node.tryGetContext('domainName');
const domainNames = domainName ? [domainName, `www.${domainName}`] : undefined;

// Whether the distribution is enrolled in a CloudFront flat-rate pricing plan
// (enrollment is console-only, so CDK can't do it — it can only account for
// it). When true, the stack pins the plan's WAF web ACL (its ARN lives in the
// SSM parameter /<project>/web_acl_arn, kept out of the repo) and skips the
// price class, which the plan forbids.
const flatRatePlan = app.node.tryGetContext('flatRatePlan') === true;

// The OIDC trust is scoped to this owner/repo/branch, so a real value is
// required. Edit cdk.json, or pass `-c githubOwner=<your-user>` on the CLI.
if (!githubOwner || githubOwner === 'REPLACE_ME') {
  throw new Error(
    'Set githubOwner in cdk.json context (or pass -c githubOwner=<your-github-username>).',
  );
}

// The account/region come from the AWS profile you deploy with (aws configure).
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? 'us-west-2',
};

const registry = new RegistryStack(app, 'SierraPassWatchRegistry', {
  project,
  env,
  description: 'Sierra Pass Watch: the ECR registry. Deploy this first, push one image, then deploy SierraPassWatch.',
});

// Only build the certificate stack when a custom domain is configured. It's
// pinned to us-east-1 (the region CloudFront requires) even though the app runs
// in `env.region`, so the main stack reads it with cross-region references.
const certificate = domainNames
  ? new CertificateStack(app, 'SierraPassWatchCertificate', {
      domainNames,
      env: { account: env.account, region: 'us-east-1' },
      crossRegionReferences: true,
      description: 'Sierra Pass Watch: the CloudFront TLS certificate, which must live in us-east-1.',
    }).certificate
  : undefined;

new SierraPassWatchStack(app, 'SierraPassWatch', {
  project,
  githubOwner,
  githubRepo,
  githubBranch,
  backendRepo: registry.backendRepo,
  domainNames,
  certificate,
  flatRatePlan,
  // Needed only to read the us-east-1 certificate from this us-west-2 stack.
  crossRegionReferences: domainNames !== undefined,
  env,
  description: 'Sierra Pass Watch: OIDC deploy role, App Runner backend, S3 + CloudFront frontend.',
});
