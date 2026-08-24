#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { execSync } from 'child_process';
import { AgentCoreInfraStack } from '../lib/infra-stack';
import { AgentCoreStack } from '../lib/runtime-stack';
import { FrontendStack } from '../lib/frontend-stack';
import { AuthStack } from '../lib/auth-stack';

// Inline region detection: AWS_DEFAULT_REGION > AWS_REGION > aws configure get region > us-east-1
function getRegion(): string {
  const region = process.env.AWS_DEFAULT_REGION || process.env.AWS_REGION;
  if (region) return region;
  try {
    const r = execSync('aws configure get region', { encoding: 'utf-8' }).trim();
    if (r) return r;
  } catch { /* ignore */ }
  return 'us-east-1';
}

const region = getRegion();
const app = new cdk.App();

// Infrastructure stack (ECR, IAM, CodeBuild, S3)
new AgentCoreInfraStack(app, `AgentCoreNovaSonicBidiInfra-${region}`, {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: region,
  },
  description: 'Nova Sonic Bidi Infrastructure: S3 code bucket and IAM roles',
});

// Auth stack (Cognito User Pool)
const authStack = new AuthStack(app, `AgentCoreNovaSonicBidiAuth-${region}`, {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: region,
  },
  description: 'Nova Sonic Bidi Authentication: Cognito User Pool for API access',
});

// Runtime stack (depends on infra and auth stacks)
const agentStack = new AgentCoreStack(app, `AgentCoreNovaSonicBidiRuntime-${region}`, {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: region,
  },
  userPool: authStack.userPool,
  userPoolClient: authStack.userPoolClient,
  description: 'Nova Sonic Bidi Runtime: Voice agent with bidirectional streaming',
});

// Frontend stack (depends on runtime and auth stacks)
new FrontendStack(app, `AgentCoreNovaSonicBidiFrontend-${region}`, {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: region,
  },
  userPoolId: authStack.userPool.userPoolId,
  userPoolClientId: authStack.userPoolClient.userPoolClientId,
  identityPoolId: authStack.identityPool.ref,
  agentRuntimeArn: agentStack.agentRuntimeArn,
  region: region,
  description: 'Nova Sonic Bidi Frontend: Voice interface with WebSocket streaming',
});

app.synth();
