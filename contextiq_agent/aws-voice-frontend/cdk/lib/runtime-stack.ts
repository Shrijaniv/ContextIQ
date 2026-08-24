import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { Construct } from 'constructs';

export interface AgentCoreStackProps extends cdk.StackProps {
  userPool: cognito.IUserPool;
  userPoolClient: cognito.IUserPoolClient;
}

export class AgentCoreStack extends cdk.Stack {
  public readonly agentRuntimeArn: string;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const region = this.region;

    // Import resources from infra stack
    const sourceBucketName = cdk.Fn.importValue(`AgentCoreNovaSonicBidiSourceBucketName-${region}`);
    const buildProjectName = cdk.Fn.importValue(`AgentCoreNovaSonicBidiBuildProjectName-${region}`);
    const buildProjectArn = cdk.Fn.importValue(`AgentCoreNovaSonicBidiBuildProjectArn-${region}`);

    const sourceBucket = s3.Bucket.fromBucketName(
      this,
      'SourceBucket',
      sourceBucketName
    );

    // Use existing ECR repository
    const agentRepository = ecr.Repository.fromRepositoryName(
      this,
      'AgentRepository',
      'nova-sonic-bidi-agent'
    );

    // Import existing IAM role
    const agentRole = iam.Role.fromRoleArn(
      this,
      'AgentRuntimeRole',
      cdk.Fn.importValue(`AgentCoreNovaSonicBidiRuntimeRoleArn-${region}`)
    );

    // Get Cognito discovery URL for inbound auth

    // Step 1: Upload only the essential agent files (exclude heavy directories)
    const agentSourceUpload = new s3deploy.BucketDeployment(this, 'AgentSourceUpload', {
      sources: [s3deploy.Source.asset('../agent', {
        exclude: [
          'venv/**',           // Python virtual environment (can be 100+ MB)
          '__pycache__/**',    // Python cache files
          '*.pyc',             // Compiled Python files
          '.git/**',           // Git files
          'node_modules/**',   // Node modules if any
          '.DS_Store',         // macOS files
          '*.log',             // Log files
          'build/**',          // Build artifacts
          'dist/**',           // Distribution files
        ]
      })],
      destinationBucket: sourceBucket,
      destinationKeyPrefix: 'agent-source/',
      prune: false,
      retainOnDelete: false,
    });

    // Step 2: Trigger CodeBuild to build the Docker image
    const buildTrigger = new cr.AwsCustomResource(this, 'TriggerCodeBuild', {
      onCreate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: buildProjectName,
        },
        physicalResourceId: cr.PhysicalResourceId.of(`build-${Date.now()}`),
      },
      onUpdate: {
        service: 'CodeBuild',
        action: 'startBuild',
        parameters: {
          projectName: buildProjectName,
        },
        physicalResourceId: cr.PhysicalResourceId.of(`build-${Date.now()}`),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['codebuild:StartBuild', 'codebuild:BatchGetBuilds'],
          resources: [buildProjectArn],
        }),
      ]),
      // Add timeout to prevent hanging
      timeout: cdk.Duration.minutes(5),
    });

    // Ensure build happens after source upload
    buildTrigger.node.addDependency(agentSourceUpload);

    // Step 3: Wait for build to complete using a custom Lambda
    const buildWaiterFunction = new lambda.Function(this, 'BuildWaiterFunction', {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, 'build-waiter-handler')),
      timeout: cdk.Duration.minutes(15), // Lambda max timeout is 15 minutes
      memorySize: 256,
    });

    buildWaiterFunction.addToRolePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['codebuild:BatchGetBuilds'],
      resources: [buildProjectArn],
    }));

    // Custom resource that invokes the waiter Lambda
    const buildWaiter = new cdk.CustomResource(this, 'BuildWaiter', {
      serviceToken: buildWaiterFunction.functionArn,
      properties: {
        BuildId: buildTrigger.getResponseField('build.id'),
      },
    });

    buildWaiter.node.addDependency(buildTrigger);

    // Create the AgentCore Runtime with WebSocket support and audio configuration
    const agentRuntime = new bedrockagentcore.CfnRuntime(this, 'AgentRuntime', {
      agentRuntimeName: 'nova_sonic_bidi_agent',
      description: 'Nova Sonic Bidi voice agent with WebSocket streaming and Cognito authentication',
      roleArn: agentRole.roleArn,

      // Container configuration
      agentRuntimeArtifact: {
        containerConfiguration: {
          containerUri: `${agentRepository.repositoryUri}:latest`,
        },
      },

      // Network configuration - PUBLIC for internet access
      networkConfiguration: {
        networkMode: 'PUBLIC',
      },

      // Protocol configuration - HTTP includes both REST (/invocations) and WebSocket (/ws) endpoints
      protocolConfiguration: 'HTTP',

      // Use default IAM authentication (SigV4) - no custom authorizer needed
      // Users authenticate via Cognito Identity Pool and get temporary AWS credentials

      // Environment variables for Nova Sonic audio configuration
      environmentVariables: {
        MODEL_ID: 'amazon.nova-2-sonic-v1:0',
        INPUT_SAMPLE_RATE: '16000',
        OUTPUT_SAMPLE_RATE: '16000',
        CHANNELS: '1',
        FORMAT: 'pcm',
        LOG_LEVEL: 'INFO',
        // BEDROCK_REGION: region where Nova Sonic model calls are made.
        // Defaults to us-east-1. Nova Sonic is only available in select regions.
        // See: https://docs.aws.amazon.com/bedrock/latest/userguide/models-regions.html
        BEDROCK_REGION: 'us-east-1',
        IMAGE_VERSION: new Date().toISOString(),
      },

      tags: {
        Environment: 'dev',
        Application: 'nova-sonic-bidi-agent',
      },
    });

    // Ensure AgentCore runtime is created after build completes
    agentRuntime.node.addDependency(buildWaiter);

    // Store runtime info for frontend
    this.agentRuntimeArn = agentRuntime.attrAgentRuntimeArn;





    new cdk.CfnOutput(this, 'AgentRuntimeArn', {
      value: agentRuntime.attrAgentRuntimeArn,
      description: 'Nova Sonic Bidi AgentCore Runtime ARN',
      exportName: `AgentCoreNovaSonicBidiRuntimeArn-${region}`,
    });

    new cdk.CfnOutput(this, 'EndpointName', {
      value: 'DEFAULT',
      description: 'Runtime Endpoint Name (DEFAULT auto-created)',
      exportName: `AgentCoreNovaSonicBidiEndpointName-${region}`,
    });

    new cdk.CfnOutput(this, 'Region', {
      value: region,
      description: 'AWS Region for AgentCore Runtime',
      exportName: `AgentCoreNovaSonicBidiRegion-${region}`,
    });


  }
}
