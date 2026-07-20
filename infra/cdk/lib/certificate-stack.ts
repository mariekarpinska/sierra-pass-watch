import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';

export interface CertificateStackProps extends cdk.StackProps {
  // The names the certificate must cover, apex first, e.g.
  // ['sierrapasswatch.com', 'www.sierrapasswatch.com'].
  domainNames: string[];
}

// A CloudFront distribution can only use a TLS certificate that lives in
// us-east-1, no matter what region the rest of the app runs in. Our app runs in
// us-west-2, so the certificate gets this tiny stack of its own, pinned to
// us-east-1, and the main stack references it across regions.
//
// The domain's DNS is at Cloudflare, not Route 53, so CDK can't write the
// validation record itself. `fromDns()` makes ACM wait for a DNS record we add
// by hand: `cdk deploy` prints the CNAME name and value, you add it at
// Cloudflare, and the deploy finishes once ACM sees it. See the "Custom domain"
// section of infra/cdk/README.md for the exact steps.
export class CertificateStack extends cdk.Stack {
  public readonly certificate: acm.ICertificate;

  constructor(scope: Construct, id: string, props: CertificateStackProps) {
    super(scope, id, props);

    this.certificate = new acm.Certificate(this, 'SiteCertificate', {
      domainName: props.domainNames[0],
      subjectAlternativeNames: props.domainNames.slice(1),
      validation: acm.CertificateValidation.fromDns(),
    });
  }
}
