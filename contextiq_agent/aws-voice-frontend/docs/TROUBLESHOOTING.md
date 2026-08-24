# Troubleshooting Guide

This guide helps you diagnose and fix common issues with the Nova Sonic Voice Agent.

## Table of Contents

- [Deployment Issues](#deployment-issues)
- [Authentication Issues](#authentication-issues)
- [WebSocket Connection Errors](#websocket-connection-errors)
- [Runtime Issues](#runtime-issues)
- [Frontend Issues](#frontend-issues)

---

## Deployment Issues

### ❌ "Template format error: Unrecognized resource types: [AWS::BedrockAgentCore::Runtime]"

**This is the most common deployment error.** It means you're trying to deploy to a region where AgentCore is not available.

**Solution:**

1. **Check current regional availability** - Visit [AWS AgentCore Regions Documentation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html)
2. **Set the region environment variables** to a supported region before deploying:

**Windows (PowerShell):**
```powershell
$env:AWS_DEFAULT_REGION = "your-supported-region"
$env:AWS_REGION = "your-supported-region"
.\deploy-all.ps1
```

**macOS/Linux (Bash):**
```bash
export AWS_DEFAULT_REGION="your-supported-region"
export AWS_REGION="your-supported-region"
./deploy-all.sh
```

### "CDK Bootstrap Required" or "SSM parameter not found"

If you see errors like "Has the environment been bootstrapped? Please run 'cdk bootstrap'":

This means CDK hasn't been set up in your AWS account/region yet. The deployment script now handles this automatically, but if you're doing manual deployment:

```bash
cd cdk
npx cdk bootstrap --no-cli-pager
```

**Region-specific bootstrap**: CDK bootstrap is required once per AWS account/region combination.

### Verify deployment status

Check all stack statuses:
```bash
aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiInfra-<region> --query "Stacks[0].StackStatus" --no-cli-pager
aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth-<region> --query "Stacks[0].StackStatus" --no-cli-pager
aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime-<region> --query "Stacks[0].StackStatus" --no-cli-pager
aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiFrontend-<region> --query "Stacks[0].StackStatus" --no-cli-pager
```

---

## Authentication Issues

### "Access Denied" or "Unauthorized"

If AWS credentials are not configured or have expired:

**Option 1: Configure with access keys**
```bash
aws configure
```

**Option 2: Use AWS SSO**
```bash
aws sso login --profile <profile-name>
export AWS_PROFILE=<profile-name>
```

**Option 3: Set environment variables**
```bash
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=your-region
```

**Verify credentials are working:**
```bash
aws sts get-caller-identity
```

### API returns 401 Unauthorized

If the frontend shows 401 errors:
- Make sure you're signed in (check header shows your email)
- Try signing out and back in
- Check browser console for JWT token errors

### Email verification not received

- Check spam/junk folder
- Verify email address is correct
- Wait a few minutes (can take up to 5 minutes)
- Try signing up with a different email

---

## WebSocket Connection Errors

---

### "Connection closed unexpectedly (code 1006)"

**What it means**: The WebSocket connection dropped without a proper close frame from the server. This is the browser's way of saying "the server didn't tell me why it closed."

**Common causes**:
1. **Agent container crashed on startup** (most common)
   - Missing Python dependencies
   - Import errors in agent code
   - Syntax errors

2. **Network issues**
   - Firewall blocking WebSocket connections
   - Proxy timeout
   - DNS resolution failure

#### How to diagnose

**Step 1: Check CloudWatch Logs** (this is the most important step!)

```bash
# Get your runtime ID from the stack output
RUNTIME_ARN=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" --output text --no-cli-pager)

# Extract runtime ID (format: arn:aws:bedrock-agentcore:region:account:runtime/runtime-id)
RUNTIME_ID=$(echo $RUNTIME_ARN | cut -d'/' -f2)

# Tail the logs in real-time
aws logs tail "/aws/bedrock-agentcore/runtimes/${RUNTIME_ID}-DEFAULT" --follow --region us-east-1
```

**Windows (PowerShell):**
```powershell
$runtimeArn = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" --output text --no-cli-pager
$runtimeId = $runtimeArn.Split('/')[-1]
aws logs tail "/aws/bedrock-agentcore/runtimes/${runtimeId}-DEFAULT" --follow --region us-east-1
```

**Step 2: Look for these errors in CloudWatch**:
- `ModuleNotFoundError: No module named 'xyz'` → Missing dependency in requirements.txt
- `SyntaxError` → Python syntax error in agent code
- `ImportError` → Import statement failed
- Any Python traceback → Agent code error

**Step 3: Fix the issue**:
- Add missing dependencies to `agent/requirements.txt`
- Fix syntax errors in `agent/strands_agent.py`
- Redeploy: `cd cdk && npx cdk deploy AgentCoreNovaSonicBidiRuntime --no-cli-pager`

#### Example: Missing Dependency

**CloudWatch logs show:**
```
ModuleNotFoundError: No module named 'pyaudio'
```

**Fix:**
1. Add `pyaudio` to `agent/requirements.txt`
2. Redeploy: `cd cdk && npx cdk deploy AgentCoreNovaSonicBidiRuntime --no-cli-pager`

### "Connection closed: Agent error: {error message}" (code 1011)

**What it means**: The agent encountered an error during operation and properly closed the connection with an error message.

**This is good!** The agent is working correctly and reporting errors properly. The error message tells you exactly what went wrong.

**Common causes**:
- Tool execution failed
- Model API error
- Unexpected exception in agent logic

**How to fix**: Read the error message - it tells you exactly what failed.

### Key Difference: 1006 vs 1011

| Code | Meaning | When it happens | What to do |
|------|---------|-----------------|------------|
| 1006 | Abnormal closure | Container crashes **before** accepting WebSocket | Check CloudWatch logs for startup errors |
| 1011 | Internal error | Agent crashes **during** operation | Read the error message in the UI |

**Remember**: Code 1006 means "check CloudWatch logs" - the real error is in the logs, not in the browser.

### WebSocket Close Codes Reference

For a complete reference of WebSocket close codes, see [WebSocket Close Codes](https://websocket.org/reference/close-codes/).

Common codes you might see:
- **1000**: Normal closure (user stopped conversation)
- **1001**: Server shutting down or restarting
- **1006**: Abnormal closure (check CloudWatch logs)
- **1008**: Policy violation (check IAM permissions)
- **1011**: Internal server error (check error message)

---

## Runtime Issues

### "Runtime failed to start"

Check CloudWatch logs:
```bash
aws logs tail /aws/bedrock-agentcore/runtimes/nova_sonic_bidi_agent-* --follow --no-cli-pager
```

Common issues:
- Missing dependencies in `requirements.txt`
- Syntax errors in `agent/strands_agent.py`
- Invalid model ID or region
- IAM permission issues

### "Code upload failed"

Redeploy runtime stack - it will re-upload the code:
```bash
cd cdk
npx cdk deploy AgentCoreNovaSonicBidiRuntime --no-cli-pager
```

### Agent responds slowly or times out

Check:
1. Model region matches your deployment region
2. Network connectivity to Bedrock API
3. CloudWatch logs for API errors
4. Tool execution time (if using custom tools)

---

## Frontend Issues

### Enabling Frontend Debug Logging

If you're experiencing issues with the frontend (WebSocket connections, audio processing, authentication, etc.), you can enable comprehensive debug logging in the browser console.

**Step 1: Copy the debug configuration template**

**Windows (PowerShell):**
```powershell
Copy-Item frontend/.env.local.example frontend/.env.local
```

**macOS/Linux (Bash):**
```bash
cp frontend/.env.local.example frontend/.env.local
```

**Step 2: Enable debug mode**

Edit `frontend/.env.local` and change:
```
VITE_WS_DEBUG=false
```
to:
```
VITE_WS_DEBUG=true
```

**Step 3: Rebuild and redeploy (or restart local dev)**

**For deployed version:**

**Windows (PowerShell):**
```powershell
cd frontend
npm run build
cd ..\cdk
npx cdk deploy AgentCoreNovaSonicBidiFrontend --no-cli-pager
```

**macOS/Linux (Bash):**
```bash
cd frontend
npm run build
cd ../cdk
npx cdk deploy AgentCoreNovaSonicBidiFrontend --no-cli-pager
```

**For local development:**

Just restart the `dev-local` script - the debug setting in `.env.local` is automatically applied.

**What gets logged with debug enabled:**
- AWS credential exchange and token refresh
- WebSocket presigned URL generation
- Connection lifecycle (open, close, errors)
- Session IDs and connection metadata
- Audio chunk processing and transmission
- Real-time audio buffer states

**Important notes:**
- `.env.local` is preserved by both `dev-local` and `build-frontend` scripts
- Debug settings work in both local development and production builds
- Errors always appear in the console regardless of this flag
- Debug mode adds verbose operational logging to help diagnose issues

**To disable debug logging:** Change `VITE_WS_DEBUG=true` back to `false` in `frontend/.env.local` and rebuild/redeploy (or restart local dev).

### Frontend shows blank page

1. Check browser console for errors
2. Verify CloudFront distribution is deployed
3. Check S3 bucket has files
4. Try hard refresh (Ctrl+Shift+R or Cmd+Shift+R)

### Configuration errors

Verify AgentCore Runtime ARN and Cognito config are correct:

```bash
aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" --output text --no-cli-pager
aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='Region'].OutputValue" --output text --no-cli-pager
aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text --no-cli-pager
aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text --no-cli-pager
aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='IdentityPoolId'].OutputValue" --output text --no-cli-pager
```

### Microphone not working

1. Check browser permissions (allow microphone access)
2. Try a different browser
3. Check browser console for errors
4. Verify HTTPS connection (required for microphone access)

---

## Getting Help

If you're still stuck after trying these solutions:

1. **Check CloudWatch Logs** - Most issues are visible in the logs
2. **Review AWS Documentation**:
   - [AgentCore Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-agentcore.html)
   - [WebSocket Streaming Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-websocket.html)
   - [Authentication Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-authentication.html)
3. **Open an issue** in the repository with:
   - Error message
   - CloudWatch logs
   - Steps to reproduce
   - Your AWS region
