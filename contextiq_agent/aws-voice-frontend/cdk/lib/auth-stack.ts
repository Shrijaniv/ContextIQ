import * as cdk from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export class AuthStack extends cdk.Stack {
    public readonly userPool: cognito.UserPool;
    public readonly userPoolClient: cognito.UserPoolClient;
    public readonly identityPool: cognito.CfnIdentityPool;
    public readonly authenticatedRole: iam.Role;

    constructor(scope: Construct, id: string, props?: cdk.StackProps) {
        super(scope, id, props);

        const region = this.region;

        // Cognito User Pool
        // NOTE: If you get "SignUp is not permitted" error, the User Pool may have been created
        // before selfSignUpEnabled was set. CDK doesn't update this on existing pools.
        // Fix: aws cognito-idp update-user-pool --user-pool-id <pool-id> --admin-create-user-config AllowAdminCreateUserOnly=false
        this.userPool = new cognito.UserPool(this, 'AgentCoreUserPool', {
            userPoolName: `nova-sonic-bidi-users-${region}`,
            selfSignUpEnabled: true, // Allows users to sign up themselves (not just admin-created)
            signInAliases: {
                email: true,
            },
            autoVerify: {
                email: true,
            },
            standardAttributes: {
                email: {
                    required: true,
                    mutable: false,
                },
            },
            passwordPolicy: {
                minLength: 8,
                requireLowercase: true,
                requireUppercase: true,
                requireDigits: true,
                requireSymbols: false,
            },
            accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
            removalPolicy: cdk.RemovalPolicy.DESTROY, // For dev - change to RETAIN for prod
        });

        // User Pool Client for frontend
        this.userPoolClient = new cognito.UserPoolClient(this, 'AgentCoreUserPoolClient', {
            userPool: this.userPool,
            userPoolClientName: 'agentcore-web-client',
            authFlows: {
                userPassword: true,
                userSrp: true,
            },
            generateSecret: false, // Public client (frontend)
            preventUserExistenceErrors: true,
        });

        // Cognito Identity Pool - provides AWS credentials for authenticated users
        // This enables users to call AgentCore with SigV4 signing after signing in
        this.identityPool = new cognito.CfnIdentityPool(this, 'AgentCoreIdentityPool', {
            identityPoolName: `nova-sonic-bidi-identity-pool-${region}`,
            allowUnauthenticatedIdentities: false, // Require authentication
            allowClassicFlow: false, // Use enhanced flow for better security
            cognitoIdentityProviders: [{
                clientId: this.userPoolClient.userPoolClientId,
                providerName: this.userPool.userPoolProviderName,
            }],
        });

        // IAM Role for AUTHENTICATED users (signed-in users)
        this.authenticatedRole = new iam.Role(this, 'AuthenticatedRole', {
            assumedBy: new iam.WebIdentityPrincipal('cognito-identity.amazonaws.com', {
                'StringEquals': {
                    'cognito-identity.amazonaws.com:aud': this.identityPool.ref,
                },
                'ForAnyValue:StringLike': {
                    'cognito-identity.amazonaws.com:amr': 'authenticated',
                },
            }),
            inlinePolicies: {
                BedrockAgentCoreAccess: new iam.PolicyDocument({
                    statements: [
                        new iam.PolicyStatement({
                            effect: iam.Effect.ALLOW,
                            actions: [
                                'bedrock-agentcore:InvokeAgentRuntime',
                                'bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream',
                                'bedrock-agentcore:InvokeRuntime',
                                'bedrock-agentcore:InvokeRuntimeWithResponseStream',
                            ],
                            resources: ['*'], // Will be restricted to specific agent in production
                        }),
                    ],
                }),
            },
        });

        // Attach authenticated role to identity pool
        new cognito.CfnIdentityPoolRoleAttachment(this, 'IdentityPoolRoleAttachment', {
            identityPoolId: this.identityPool.ref,
            roles: {
                authenticated: this.authenticatedRole.roleArn,
            },
        });

        // Outputs
        new cdk.CfnOutput(this, 'UserPoolId', {
            value: this.userPool.userPoolId,
            description: 'Cognito User Pool ID',
            exportName: `AgentCoreNovaSonicBidiUserPoolId-${region}`,
        });

        new cdk.CfnOutput(this, 'UserPoolArn', {
            value: this.userPool.userPoolArn,
            description: 'Cognito User Pool ARN',
            exportName: `AgentCoreNovaSonicBidiUserPoolArn-${region}`,
        });

        new cdk.CfnOutput(this, 'UserPoolClientId', {
            value: this.userPoolClient.userPoolClientId,
            description: 'Cognito User Pool Client ID',
            exportName: `AgentCoreNovaSonicBidiUserPoolClientId-${region}`,
        });

        new cdk.CfnOutput(this, 'IdentityPoolId', {
            value: this.identityPool.ref,
            description: 'Cognito Identity Pool ID (for AWS credentials)',
            exportName: `AgentCoreNovaSonicBidiIdentityPoolId-${region}`,
        });

        new cdk.CfnOutput(this, 'AuthenticatedRoleArn', {
            value: this.authenticatedRole.roleArn,
            description: 'IAM Role ARN for authenticated users',
            exportName: `AgentCoreNovaSonicBidiAuthenticatedRoleArn-${region}`,
        });
    }
}
