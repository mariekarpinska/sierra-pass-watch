import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as apprunner from 'aws-cdk-lib/aws-apprunner';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as ssm from 'aws-cdk-lib/aws-ssm';

export interface SierraSafeStackProps extends cdk.StackProps {
  project: string;
  githubOwner: string;
  githubRepo: string;
  githubBranch: string;
  backendRepo: ecr.IRepository;
  // Custom domain, both provided together or both omitted. When set, CloudFront
  // serves these names with the given certificate; when omitted, CloudFront's
  // default *.cloudfront.net name is used. See bin/app.ts.
  domainNames?: string[];
  certificate?: acm.ICertificate;
  // Whether the distribution is enrolled in a CloudFront flat-rate pricing
  // plan (console-only enrollment). When true, the plan's WAF web ACL — whose
  // ARN lives in the SSM parameter /<project>/web_acl_arn, created out of band
  // so the account id stays out of the repo — is pinned onto the distribution.
  // It must be, or the next deploy would strip it, and the plan requires it.
  flatRatePlan?: boolean;
}

// Everything except the registry: the frontend (S3 + CloudFront), the backend
// (App Runner), and the GitHub OIDC deploy role. Plain-English background —
// why AWS, why App Runner, how OIDC works — is in docs/deployment.md.
export class SierraSafeStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: SierraSafeStackProps) {
    super(scope, id, props);
    const { project, githubOwner, githubRepo, githubBranch, backendRepo, domainNames, certificate, flatRatePlan } = props;

    // The flat-rate plan's WAF web ACL, resolved from SSM at deploy time.
    const webAclArn = flatRatePlan
      ? ssm.StringParameter.valueForStringParameter(this, `/${project}/web_acl_arn`)
      : undefined;

    // --- Frontend: private S3 bucket, served over HTTPS by CloudFront ---
    // The bucket is NOT public; only CloudFront can read it, via Origin Access
    // Control. `withOriginAccessControl` wires the OAC and the bucket policy for
    // us — the terse part CDK does well.
    const siteBucket = new s3.Bucket(this, 'FrontendBucket', {
      bucketName: `${project}-frontend-${this.account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      // A demo bucket: let `cdk destroy` empty and remove it cleanly.
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    const distribution = new cloudfront.Distribution(this, 'FrontendCdn', {
      defaultRootObject: 'index.html',
      // On the flat-rate pricing plan (webAclArn set) CloudFront rejects an
      // explicit price class — the plan governs delivery. Off-plan, pin the
      // cheapest tier: North America + Europe edges only.
      ...(webAclArn ? {} : { priceClass: cloudfront.PriceClass.PRICE_CLASS_100 }),
      // Serve the custom domain with its certificate when one is configured;
      // otherwise CloudFront keeps its default *.cloudfront.net name.
      ...(domainNames && certificate ? { domainNames, certificate } : {}),
      // Keep the flat-rate plan's WAF attached (see SierraSafeStackProps).
      ...(webAclArn ? { webAclId: webAclArn } : {}),
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
      },
      // Single-page app: the browser owns the routes, not S3. Under Origin Access
      // Control the bucket grants CloudFront GetObject only (no ListBucket), so a
      // missing key returns 403, not 404 — this rule serves index.html for it, so a
      // deep-link refresh still loads the app.
      //
      // Only 403 is remapped. CloudFront error responses are distribution-wide, so
      // remapping 404 would also swallow the /api/* behavior's real 404s (e.g. an
      // unknown town) into index.html. Leaving 404 lets API errors through as JSON.
      errorResponses: [
        { httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html', ttl: cdk.Duration.seconds(10) },
      ],
    });

    // CORS is now only a transition aid: the browser reaches the API
    // same-origin through the /api/* behavior below, which needs no CORS at
    // all. The custom domains stay allowed so a frontend built before the
    // same-origin switch keeps working; without a custom domain the list is
    // empty and the backend adds no CORS middleware. (Deliberately NOT the
    // distribution's domain here — the distribution now references the
    // backend for the /api origin, so the reverse reference would be a cycle.)
    const frontendOrigins = domainNames ? domainNames.map((d) => `https://${d}`) : [];

    // --- The database URL, referenced but not managed here ---
    // It lives in an SSM SecureString created out of band (see the README):
    // CloudFormation can't create SecureString parameters, and a secret
    // shouldn't sit in the template anyway. We only reference it by ARN.
    const dbUrlParamName = `/${project}/database_url`;
    const dbUrlParamArn = `arn:aws:ssm:${this.region}:${this.account}:parameter${dbUrlParamName}`;

    // --- The CDN origin secret, also created out of band ---
    // A random string in a plain SSM parameter (`aws ssm put-parameter --name
    // /<project>/origin_verify --type String --value "$(openssl rand -hex 32)"`).
    // CloudFront sends it to the backend on every /api/* request, and the
    // backend rejects requests without it (backend/api/middleware.py) — so a
    // flood aimed at the public App Runner URL gets ~100-byte 403s instead of
    // full JSON, and can't run up egress costs. A cost guard, not auth, so a
    // plain (non-secure) parameter is fine — and CloudFront custom headers
    // can't resolve SecureStrings anyway.
    const originVerifySecret = ssm.StringParameter.valueForStringParameter(
      this, `/${project}/origin_verify`,
    );

    // --- Backend: FastAPI container on App Runner ---
    // App Runner's L2 construct is still an alpha module, so this uses the
    // stable L1 CfnService. Everything else on this stack is L2.
    const ecrAccessRole = new iam.Role(this, 'AppRunnerEcrAccessRole', {
      assumedBy: new iam.ServicePrincipal('build.apprunner.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSAppRunnerServicePolicyForECRAccess'),
      ],
    });

    // What the running container may do: read the one database-URL parameter.
    const instanceRole = new iam.Role(this, 'AppRunnerInstanceRole', {
      assumedBy: new iam.ServicePrincipal('tasks.apprunner.amazonaws.com'),
    });
    instanceRole.addToPolicy(new iam.PolicyStatement({
      actions: ['ssm:GetParameters'],
      resources: [dbUrlParamArn],
    }));

    // Cost ceiling: App Runner's default autoscaling allows up to 25 instances,
    // which a request flood would happily reach and bill for. 3 instances at
    // 100 concurrent requests each is far more than this site needs, and caps
    // the worst-case compute spend at ~$10/week instead of ~$82/week.
    const autoScaling = new apprunner.CfnAutoScalingConfiguration(this, 'BackendAutoScaling', {
      autoScalingConfigurationName: `${project}-backend`,
      minSize: 1,
      maxSize: 3,
      maxConcurrency: 100,
    });

    const backend = new apprunner.CfnService(this, 'Backend', {
      serviceName: `${project}-backend`,
      autoScalingConfigurationArn: autoScaling.attrAutoScalingConfigurationArn,
      sourceConfiguration: {
        autoDeploymentsEnabled: false,
        authenticationConfiguration: { accessRoleArn: ecrAccessRole.roleArn },
        imageRepository: {
          imageIdentifier: `${backendRepo.repositoryUri}:latest`,
          imageRepositoryType: 'ECR',
          imageConfiguration: {
            port: '8080',
            // The frontend is a different origin (CloudFront), so the browser
            // needs the API to allow it explicitly. config.py expects a JSON
            // list, never "*".
            runtimeEnvironmentVariables: [
              { name: 'CORS_ALLOWED_ORIGINS', value: JSON.stringify(frontendOrigins) },
              // The cost guard's shared secret (see originVerifySecret above).
              { name: 'ORIGIN_VERIFY_SECRET', value: originVerifySecret },
            ],
            // App Runner injects this from SSM at runtime; the value never
            // appears in the template or the image.
            runtimeEnvironmentSecrets: [
              { name: 'DATABASE_URL', value: dbUrlParamArn },
            ],
          },
        },
      },
      instanceConfiguration: {
        cpu: '256', // 0.25 vCPU — the smallest/cheapest
        memory: '512', // MB
        instanceRoleArn: instanceRole.roleArn,
      },
      // App Runner restarts the container if this stops returning 200.
      healthCheckConfiguration: {
        protocol: 'HTTP',
        path: '/api/health',
        interval: 10,
        timeout: 5,
        healthyThreshold: 1,
        unhealthyThreshold: 5,
      },
    });

    // --- Route the API through the CDN: /api/* on the site's own origin ---
    // The browser calls /api same-origin (no CORS needed), CloudFront forwards
    // to App Runner with the origin secret attached, and the flat-rate plan's
    // WAF fronts all of it. The SPA errorResponses above rewrite only 403 to
    // index.html, not 404. A request that reaches the API through the CDN always
    // carries the origin secret, so the API never answers it with a 403 — the
    // only 403s that rule catches are missing S3 keys. That leaves every API
    // error, including its 404 for an unknown town, to pass through unchanged.
    distribution.addBehavior('/api/*', new origins.HttpOrigin(backend.attrServiceUrl, {
      protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
      customHeaders: { 'X-Origin-Verify': originVerifySecret },
    }), {
      viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      // Live data on every request: never cache, and forward query strings —
      // but not the viewer's Host header, because App Runner routes on Host
      // and must see its own domain, not sierrapasswatch.com.
      cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
      originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
      allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
    });

    // --- GitHub Actions -> AWS trust, with NO long-lived keys ---
    // The GitHub OIDC provider is ACCOUNT-LEVEL: AWS allows only one per account
    // for a given URL. Most accounts already have it, so by default we reference
    // the existing one by its (deterministic) ARN. On a brand-new account that
    // doesn't have it yet, deploy once with `-c createOidcProvider=true` and CDK
    // creates it (fetching GitHub's thumbprint automatically).
    const createOidc =
      this.node.tryGetContext('createOidcProvider') === true ||
      this.node.tryGetContext('createOidcProvider') === 'true';

    const oidcProviderArn = createOidc
      ? new iam.OpenIdConnectProvider(this, 'GithubOidc', {
          url: 'https://token.actions.githubusercontent.com',
          clientIds: ['sts.amazonaws.com'],
        }).openIdConnectProviderArn
      : `arn:aws:iam::${this.account}:oidc-provider/token.actions.githubusercontent.com`;

    // Only an OIDC token from THIS repo on THIS branch may assume the role. A
    // fork, another branch, or another repo produces a subject that fails this
    // match, so it can never assume it.
    const deployRole = new iam.Role(this, 'GithubDeployRole', {
      roleName: `${project}-github-deploy`,
      description: 'Assumed by GitHub Actions (this repo, this branch only) to deploy.',
      assumedBy: new iam.WebIdentityPrincipal(oidcProviderArn, {
        StringEquals: { 'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com' },
        StringLike: {
          'token.actions.githubusercontent.com:sub': `repo:${githubOwner}/${githubRepo}:ref:refs/heads/${githubBranch}`,
        },
      }),
    });

    // Least privilege: push the image, redeploy the service, write the bucket,
    // clear the CDN — nothing else. The grant helpers generate scoped policies.
    backendRepo.grantPullPush(deployRole); // ECR push/pull + GetAuthorizationToken
    siteBucket.grantReadWrite(deployRole); // s3 sync --delete needs get/put/delete/list
    deployRole.addToPolicy(new iam.PolicyStatement({
      actions: ['apprunner:StartDeployment', 'apprunner:DescribeService', 'apprunner:ListOperations'],
      resources: [backend.attrServiceArn],
    }));
    deployRole.addToPolicy(new iam.PolicyStatement({
      actions: ['cloudfront:CreateInvalidation'],
      resources: [`arn:aws:cloudfront::${this.account}:distribution/${distribution.distributionId}`],
    }));

    // --- Outputs: paste these into GitHub (mapping in infra/cdk/README.md) ---
    new cdk.CfnOutput(this, 'GithubDeployRoleArn', {
      description: 'GitHub secret AWS_ROLE_ARN — the role a deploy run assumes via OIDC.',
      value: deployRole.roleArn,
    });
    new cdk.CfnOutput(this, 'AppRunnerServiceArn', {
      description: 'GitHub variable APPRUNNER_SERVICE_ARN — the service a deploy redeploys.',
      value: backend.attrServiceArn,
    });
    new cdk.CfnOutput(this, 'AppRunnerServiceUrl', {
      description: 'Public HTTPS URL of the backend API.',
      value: `https://${backend.attrServiceUrl}`,
    });
    new cdk.CfnOutput(this, 'FrontendBucketName', {
      description: 'GitHub variable FRONTEND_BUCKET — the built site is synced here.',
      value: siteBucket.bucketName,
    });
    new cdk.CfnOutput(this, 'CloudFrontDistributionId', {
      description: 'GitHub variable CLOUDFRONT_DISTRIBUTION_ID — cache invalidated here after a deploy.',
      value: distribution.distributionId,
    });
    new cdk.CfnOutput(this, 'CloudFrontDomain', {
      description: 'The CloudFront name to point the custom domain at (the DNS CNAME target).',
      value: `https://${distribution.distributionDomainName}`,
    });
    new cdk.CfnOutput(this, 'SiteUrl', {
      description: 'Public URL of the site: the custom domain when set, else CloudFront.',
      value: domainNames ? `https://${domainNames[0]}` : `https://${distribution.distributionDomainName}`,
    });
  }
}
