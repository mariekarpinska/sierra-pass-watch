#!/usr/bin/env node
// Entry point. Reads non-secret config from CDK context (cdk.json), then builds
// two stacks:
//   1. SierraSafeRegistry — the ECR image registry, on its own so it can be
//      created (and an image pushed to it) BEFORE the app that pulls that image.
//   2. SierraSafe        — everything else: the OIDC deploy role, the App Runner
//      backend, and the S3 + CloudFront frontend.
// See infra/cdk/README.md for the deploy order and why it's split this way.
import * as cdk from 'aws-cdk-lib';
import { RegistryStack } from '../lib/registry-stack';
import { SierraSafeStack } from '../lib/sierra-safe-stack';

const app = new cdk.App();

const project = app.node.tryGetContext('project') ?? 'sierra-safe';
const githubOwner = app.node.tryGetContext('githubOwner');
const githubRepo = app.node.tryGetContext('githubRepo') ?? 'SierraSafetyIndex';
const githubBranch = app.node.tryGetContext('githubBranch') ?? 'main';

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

const registry = new RegistryStack(app, 'SierraSafeRegistry', {
  project,
  env,
  description: 'Sierra Safe: the ECR registry. Deploy this first, push one image, then deploy SierraSafe.',
});

new SierraSafeStack(app, 'SierraSafe', {
  project,
  githubOwner,
  githubRepo,
  githubBranch,
  backendRepo: registry.backendRepo,
  env,
  description: 'Sierra Safe: OIDC deploy role, App Runner backend, S3 + CloudFront frontend.',
});
