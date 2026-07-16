import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ecr from 'aws-cdk-lib/aws-ecr';

export interface RegistryStackProps extends cdk.StackProps {
  project: string;
}

// The private container registry for the backend image, in its own stack.
//
// Why separate: App Runner (in the SierraSafe stack) can't be created until an
// image already exists at :latest. Keeping the registry apart lets you deploy
// it, push one image, then deploy the app — instead of the app failing on a
// registry that has nothing in it yet.
export class RegistryStack extends cdk.Stack {
  public readonly backendRepo: ecr.Repository;

  constructor(scope: Construct, id: string, props: RegistryStackProps) {
    super(scope, id, props);

    this.backendRepo = new ecr.Repository(this, 'BackendRepo', {
      repositoryName: `${props.project}-backend`,
      // Scan each pushed image for known vulnerabilities.
      imageScanOnPush: true,
      // Old images cost money; keep the last 10 and expire the rest.
      lifecycleRules: [{ maxImageCount: 10, description: 'Keep only the 10 most recent images' }],
    });

    new cdk.CfnOutput(this, 'EcrRepositoryUri', {
      description: 'GitHub variable ECR_REPOSITORY — where the backend image is pushed.',
      value: this.backendRepo.repositoryUri,
    });
  }
}
