/**
 * AWS Credentials Helper
 * 
 * Exchanges Cognito User Pool JWT tokens for temporary AWS credentials
 * via Cognito Identity Pool. These credentials are used to sign requests
 * to AgentCore with SigV4.
 */

import { CognitoIdentityClient, GetIdCommand, GetCredentialsForIdentityCommand } from '@aws-sdk/client-cognito-identity';
import { getIdToken } from './auth';

const region = import.meta.env.VITE_REGION || 'us-east-1';
const userPoolId = import.meta.env.VITE_USER_POOL_ID;
const identityPoolId = import.meta.env.VITE_IDENTITY_POOL_ID;

// Set to true to enable verbose credentials debug logging in the browser console
const DEBUG = (import.meta as any).env.VITE_WS_DEBUG === 'true';
const log = (...args: any[]) => DEBUG && console.log(...args);

export interface AWSCredentials {
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken: string;
  expiration?: Date;
}

// Cache credentials to avoid repeated auth calls
let cachedCredentials: AWSCredentials | null = null;
let credentialsExpiry: Date | null = null;

/**
 * Get AWS credentials by exchanging Cognito JWT token for temporary credentials
 * via Cognito Identity Pool
 */
export async function getAWSCredentials(): Promise<AWSCredentials> {
  // Return cached credentials if still valid (with 5 min buffer)
  if (cachedCredentials && credentialsExpiry) {
    const now = new Date();
    const bufferMs = 5 * 60 * 1000;
    if (credentialsExpiry.getTime() - now.getTime() > bufferMs) {
      return cachedCredentials;
    }
  }

  // Get JWT token from Cognito User Pool
  const idToken = await getIdToken();
  if (!idToken) {
    throw new Error('Not authenticated - please sign in');
  }

  if (!identityPoolId) {
    throw new Error('Identity Pool ID not configured');
  }

  const cognitoClient = new CognitoIdentityClient({ region });

  // Step 1: Get identity ID from Identity Pool using JWT token
  const providerName = `cognito-idp.${region}.amazonaws.com/${userPoolId}`;
  const getIdResponse = await cognitoClient.send(new GetIdCommand({
    IdentityPoolId: identityPoolId,
    Logins: {
      [providerName]: idToken,
    },
  }));

  const identityId = getIdResponse.IdentityId;
  if (!identityId) {
    throw new Error('Failed to get identity ID from Cognito Identity Pool');
  }

  log('Got identity ID:', identityId);

  // Step 2: Get AWS credentials for the identity
  const getCredsResponse = await cognitoClient.send(new GetCredentialsForIdentityCommand({
    IdentityId: identityId,
    Logins: {
      [providerName]: idToken,
    },
  }));

  const creds = getCredsResponse.Credentials;
  if (!creds?.AccessKeyId || !creds?.SecretKey || !creds?.SessionToken) {
    throw new Error('Failed to get AWS credentials from Cognito Identity Pool');
  }

  log('Got AWS credentials via Cognito Identity Pool');

  cachedCredentials = {
    accessKeyId: creds.AccessKeyId,
    secretAccessKey: creds.SecretKey,
    sessionToken: creds.SessionToken,
    expiration: creds.Expiration,
  };
  credentialsExpiry = creds.Expiration || null;

  return cachedCredentials;
}

/**
 * Clear cached credentials (call on sign out)
 */
export function clearCredentials(): void {
  cachedCredentials = null;
  credentialsExpiry = null;
}
