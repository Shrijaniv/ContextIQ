import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserAttribute,
} from 'amazon-cognito-identity-js';

const userPoolId = import.meta.env.VITE_USER_POOL_ID;
const clientId = import.meta.env.VITE_USER_POOL_CLIENT_ID;
const isLocalDev = import.meta.env.VITE_LOCAL_DEV === 'true';

// In local dev mode, Cognito is optional
if (!isLocalDev && (!userPoolId || !clientId)) {
  throw new Error('Missing Cognito configuration');
}

const userPool = (userPoolId && clientId) ? new CognitoUserPool({
  UserPoolId: userPoolId,
  ClientId: clientId,
}) : null;

export interface AuthUser {
  username: string;
  email: string;
}

export const signUp = (email: string, password: string): Promise<void> => {
  if (!userPool) {
    return Promise.reject(new Error('Authentication not available in local dev mode'));
  }
  
  return new Promise((resolve, reject) => {
    const attributeList = [
      new CognitoUserAttribute({
        Name: 'email',
        Value: email,
      }),
    ];

    userPool.signUp(email, password, attributeList, [], (err) => {
      if (err) {
        reject(err);
        return;
      }
      resolve();
    });
  });
};

export const confirmSignUp = (email: string, code: string): Promise<void> => {
  if (!userPool) {
    return Promise.reject(new Error('Authentication not available in local dev mode'));
  }
  
  return new Promise((resolve, reject) => {
    const cognitoUser = new CognitoUser({
      Username: email,
      Pool: userPool,
    });

    cognitoUser.confirmRegistration(code, true, (err) => {
      if (err) {
        reject(err);
        return;
      }
      resolve();
    });
  });
};

export const signIn = (email: string, password: string): Promise<string> => {
  if (!userPool) {
    return Promise.reject(new Error('Authentication not available in local dev mode'));
  }
  
  return new Promise((resolve, reject) => {
    const authenticationDetails = new AuthenticationDetails({
      Username: email,
      Password: password,
    });

    const cognitoUser = new CognitoUser({
      Username: email,
      Pool: userPool,
    });

    cognitoUser.authenticateUser(authenticationDetails, {
      onSuccess: (result) => {
        const idToken = result.getIdToken().getJwtToken();
        resolve(idToken);
      },
      onFailure: (err) => {
        reject(err);
      },
    });
  });
};

export const signOut = (): void => {
  if (!userPool) {
    return;
  }
  
  const cognitoUser = userPool.getCurrentUser();
  if (cognitoUser) {
    cognitoUser.signOut();
  }
  
  // Clear AWS credentials cache
  import('./aws-credentials').then(({ clearCredentials }) => {
    clearCredentials();
  });
};

export const getCurrentUser = (): Promise<AuthUser | null> => {
  if (!userPool) {
    // In local dev mode, return a mock user
    if (isLocalDev) {
      return Promise.resolve({
        username: 'local-dev-user',
        email: 'dev@localhost'
      });
    }
    return Promise.resolve(null);
  }
  
  return new Promise((resolve) => {
    const cognitoUser = userPool.getCurrentUser();

    if (!cognitoUser) {
      resolve(null);
      return;
    }

    cognitoUser.getSession((err: any, session: any) => {
      if (err || !session.isValid()) {
        resolve(null);
        return;
      }

      cognitoUser.getUserAttributes((err, attributes) => {
        if (err) {
          resolve(null);
          return;
        }

        const email = attributes?.find((attr) => attr.Name === 'email')?.Value || '';

        resolve({
          username: cognitoUser.getUsername(),
          email,
        });
      });
    });
  });
};

export const getIdToken = (): Promise<string | null> => {
  if (!userPool) {
    // In local dev mode, no token needed
    return Promise.resolve(null);
  }
  
  return new Promise((resolve) => {
    const cognitoUser = userPool.getCurrentUser();

    if (!cognitoUser) {
      resolve(null);
      return;
    }

    cognitoUser.getSession((err: any, session: any) => {
      if (err || !session.isValid()) {
        resolve(null);
        return;
      }

      // Use ID Token for AgentCore authentication (as per AWS documentation)
      resolve(session.getIdToken().getJwtToken());
    });
  });
};

export const getAccessToken = (): Promise<string | null> => {
  if (!userPool) {
    // In local dev mode, no token needed
    return Promise.resolve(null);
  }
  
  return new Promise((resolve) => {
    const cognitoUser = userPool.getCurrentUser();

    if (!cognitoUser) {
      resolve(null);
      return;
    }

    cognitoUser.getSession((err: any, session: any) => {
      if (err || !session.isValid()) {
        resolve(null);
        return;
      }

      // Return the access token
      resolve(session.getAccessToken().getJwtToken());
    });
  });
};
