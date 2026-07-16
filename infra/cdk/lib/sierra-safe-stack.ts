import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as apprunner from 'aws-cdk-lib/aws-apprunner';

export interface SierraSafeStackProps extends cdk.StackProps {
  project: string;
  githubOwner: string;
  githubRepo: string;
  githubBranch: string;
  backendRepo: ecr.IRepository;
}

// Everything except the registry: the frontend (S3 + CloudFront), the backend
// (App Runner), and the GitHub OIDC deploy role. Plain-English background —
// why AWS, why App Runner, how OIDC works — is in docs/deployment.md.
export class SierraSafeStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: SierraSafeStackProps) {
    super(scope, id, props);
    const { project, githubOwner, githubRepo, githubBranch, backendRepo } = props;

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
      // Cheapest tier: North America + Europe edges only.
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
      },
      // Single-page app: the browser owns the routes, not S3. So when S3 says
      // "no such key", hand back index.html with a 200 and let React Router
      // render the right page.
      errorResponses: [
        { httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html', ttl: cdk.Duration.seconds(10) },
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html', ttl: cdk.Duration.seconds(10) },
      ],
    });

    // --- The database URL, referenced but not managed here ---
    // It lives in an SSM SecureString created out of band (see the README):
    // CloudFormation can't create SecureString parameters, and a secret
    // shouldn't sit in the template anyway. We only reference it by ARN.
    const dbUrlParamName = `/${project}/database_url`;
    const dbUrlParamArn = `arn:aws:ssm:${this.region}:${this.account}:parameter${dbUrlParamName}`;

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

    const backend = new apprunner.CfnService(this, 'Backend', {
      serviceName: `${project}-backend`,
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
              { name: 'CORS_ALLOWED_ORIGINS', value: JSON.stringify([`https://${distribution.distributionDomainName}`]) },
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
      description: 'Public URL the frontend is served from.',
      value: `https://${distribution.distributionDomainName}`,
    });
  }
}
