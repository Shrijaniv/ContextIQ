# Deployment Guide

This guide covers manual deployment, updating the agent, and advanced deployment scenarios.

## Table of Contents

- [Quick Deployment](#quick-deployment)
- [Manual Deployment](#manual-deployment)
- [Updating the Agent](#updating-the-agent)
- [Deployment Troubleshooting](#deployment-troubleshooting)

---

## Quick Deployment

For most users, the automated deployment script is recommended:

**Windows (PowerShell):**
```powershell
.\deploy-all.ps1
```

**macOS/Linux (Bash):**
```bash
chmod +x deploy-all.sh scripts/build-frontend.sh
./deploy-all.sh
```

**Time:** ~10 minutes (includes container build for WebSocket support)

---

## Manual Deployment

If you prefer to deploy stacks individually or need more control:

### Prerequisites

- AWS CLI v2.31.13 or later
- Node.js 22+
- AWS credentials configured
- Target region supports AgentCore ([check availability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html))

### Step 1: Bootstrap CDK (one-time setup)

```bash
cd cdk
npx cdk bootstrap --no-cli-pager
```

This sets up CDK deployment resources in your AWS account/region. Required once per account/region combination.

### Step 2: Deploy Infrastructure Stack

```bash
cd cdk
npx cdk deploy AgentCoreNovaSonicBidiInfra --no-cli-pager
```

**Creates:**
- ECR Repository for agent container
- S3 bucket for agent code storage
- CodeBuild project for container builds
- IAM roles for AgentCore runtime

**Time:** ~2 minutes

### Step 3: Deploy Authentication Stack

```bash
cd cdk
npx cdk deploy AgentCoreNovaSonicBidiAuth --no-cli-pager
```

**Creates:**
- Cognito User Pool (email/password authentication)
- User Pool Client for frontend
- Cognito Identity Pool for AWS credential vending
- Authenticated IAM Role with Bedrock AgentCore permissions

**Time:** ~2 minutes

### Step 4: Deploy Runtime Stack

```bash
cd cdk
npx cdk deploy AgentCoreNovaSonicBidiRuntime --no-cli-pager
```

**Creates:**
- Packages agent code with dependencies
- Builds ARM64 Docker container via CodeBuild
- Pushes container to ECR
- Creates AgentCore Runtime with WebSocket support
- Configures IAM authentication

**Time:** ~10 minutes (container build takes 5-10 minutes)

**Note:** This step takes the longest due to container compilation. The deployment waits for CodeBuild to complete.

### Step 5: Deploy Frontend Stack

First, build the frontend with configuration from deployed stacks:

**Windows (PowerShell):**
```powershell
$agentRuntimeArn = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" --output text --no-cli-pager
$region = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='Region'].OutputValue" --output text --no-cli-pager
$userPoolId = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text --no-cli-pager
$userPoolClientId = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text --no-cli-pager
$identityPoolId = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='IdentityPoolId'].OutputValue" --output text --no-cli-pager

.\scripts\build-frontend.ps1 -UserPoolId $userPoolId -UserPoolClientId $userPoolClientId -IdentityPoolId $identityPoolId -AgentRuntimeArn $agentRuntimeArn -Region $region

cd cdk
npx cdk deploy AgentCoreNovaSonicBidiFrontend --no-cli-pager
```

**macOS/Linux (Bash):**
```bash
AGENT_RUNTIME_ARN=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" --output text --no-cli-pager)
REGION=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='Region'].OutputValue" --output text --no-cli-pager)
USER_POOL_ID=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text --no-cli-pager)
USER_POOL_CLIENT_ID=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text --no-cli-pager)
IDENTITY_POOL_ID=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='IdentityPoolId'].OutputValue" --output text --no-cli-pager)

./scripts/build-frontend.sh "$USER_POOL_ID" "$USER_POOL_CLIENT_ID" "$IDENTITY_POOL_ID" "$AGENT_RUNTIME_ARN" "$REGION"

cd cdk
npx cdk deploy AgentCoreNovaSonicBidiFrontend --no-cli-pager
```

**Creates:**
- S3 bucket for static hosting
- CloudFront distribution with OAC
- Deploys React app with authentication UI

**Time:** ~5 minutes

### Step 6: Get Your Application URL

```bash
aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiFrontend --query "Stacks[0].Outputs[?OutputKey=='WebsiteUrl'].OutputValue" --output text --no-cli-pager
```

---

## Updating the Agent

### Updating Agent Code

To modify the agent behavior:

1. **Edit the agent code:**
   - `agent/strands_agent.py` - Agent logic, tools, system prompt
   - `agent/requirements.txt` - Python dependencies

2. **Redeploy the runtime stack:**
   ```bash
   cd cdk
   npx cdk deploy AgentCoreNovaSonicBidiRuntime --no-cli-pager
   ```

**What happens:**
- Agent code is packaged as ZIP
- New Docker container is built with updated code
- Container is pushed to ECR
- AgentCore runtime is updated with new container
- Takes ~10 minutes (container build time)

**Note:** You only need to redeploy the Runtime stack, not all stacks.

### Updating Frontend

To modify the UI:

1. **Edit frontend code:**
   - `frontend/src/App.tsx` - Main UI component
   - `frontend/src/hooks/useVoiceAgent.ts` - Voice agent logic
   - `frontend/src/components/` - Reusable components

2. **Rebuild and redeploy:**

**Windows (PowerShell):**
```powershell
$agentRuntimeArn = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" --output text --no-cli-pager
$region = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='Region'].OutputValue" --output text --no-cli-pager
$userPoolId = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text --no-cli-pager
$userPoolClientId = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text --no-cli-pager
$identityPoolId = aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='IdentityPoolId'].OutputValue" --output text --no-cli-pager

.\scripts\build-frontend.ps1 -UserPoolId $userPoolId -UserPoolClientId $userPoolClientId -IdentityPoolId $identityPoolId -AgentRuntimeArn $agentRuntimeArn -Region $region

cd cdk
npx cdk deploy AgentCoreNovaSonicBidiFrontend --no-cli-pager
```

**macOS/Linux (Bash):**
```bash
AGENT_RUNTIME_ARN=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='AgentRuntimeArn'].OutputValue" --output text --no-cli-pager)
REGION=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiRuntime --query "Stacks[0].Outputs[?OutputKey=='Region'].OutputValue" --output text --no-cli-pager)
USER_POOL_ID=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolId'].OutputValue" --output text --no-cli-pager)
USER_POOL_CLIENT_ID=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='UserPoolClientId'].OutputValue" --output text --no-cli-pager)
IDENTITY_POOL_ID=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiAuth --query "Stacks[0].Outputs[?OutputKey=='IdentityPoolId'].OutputValue" --output text --no-cli-pager)

./scripts/build-frontend.sh "$USER_POOL_ID" "$USER_POOL_CLIENT_ID" "$IDENTITY_POOL_ID" "$AGENT_RUNTIME_ARN" "$REGION"

cd cdk
npx cdk deploy AgentCoreNovaSonicBidiFrontend --no-cli-pager
```

**Time:** ~5 minutes

### Common Update Scenarios

#### Change Model

Edit `agent/strands_agent.py`:
```python
MODEL_ID = os.getenv("MODEL_ID", "amazon.nova-pro-v1:0")  # Change model
```

Then redeploy runtime:
```bash
cd cdk
npx cdk deploy AgentCoreNovaSonicBidiRuntime --no-cli-pager
```

#### Add New Tool

Edit `agent/strands_agent.py`:
```python
@tool
def my_new_tool(param: str) -> str:
    """Tool description"""
    return f"Result: {param}"

# Add to agent tools list
voice_agent = BidiAgent(
    model=sonic_model,
    tools=[calculate_expression, get_weather, my_new_tool],  # Add here
    system_prompt="..."
)
```

Then redeploy runtime:
```bash
cd cdk
npx cdk deploy AgentCoreNovaSonicBidiRuntime --no-cli-pager
```

#### Add Python Dependency

Edit `agent/requirements.txt`:
```
strands-agents
aws_sdk_bedrock_runtime
fastapi
uvicorn[standard]
websockets
prompt_toolkit
pyaudio
requests  # Add new dependency
```

Then redeploy runtime:
```bash
cd cdk
npx cdk deploy AgentCoreNovaSonicBidiRuntime --no-cli-pager
```

---

## Deployment Troubleshooting

### Stack Deployment Failed

Check the stack status:
```bash
aws cloudformation describe-stacks --stack-name <stack-name> --query "Stacks[0].StackStatus" --no-cli-pager
```

View stack events to see what failed:
```bash
aws cloudformation describe-stack-events --stack-name <stack-name> --max-items 20 --no-cli-pager
```

### Container Build Failed

Check CodeBuild logs:
```bash
# Get build project name
BUILD_PROJECT=$(aws cloudformation describe-stacks --stack-name AgentCoreNovaSonicBidiInfra --query "Stacks[0].Outputs[?OutputKey=='BuildProjectName'].OutputValue" --output text --no-cli-pager)

# Get latest build ID
BUILD_ID=$(aws codebuild list-builds-for-project --project-name $BUILD_PROJECT --max-items 1 --query "ids[0]" --output text --no-cli-pager)

# View build logs
aws codebuild batch-get-builds --ids $BUILD_ID --query "builds[0].logs" --no-cli-pager
```

### Rollback Failed Deployment

If a deployment fails and you need to rollback:

```bash
# Delete the failed stack
aws cloudformation delete-stack --stack-name <stack-name>

# Wait for deletion to complete
aws cloudformation wait stack-delete-complete --stack-name <stack-name>

# Redeploy
cd cdk
npx cdk deploy <stack-name> --no-cli-pager
```

### Clean Deployment (Start Fresh)

To completely remove and redeploy:

```bash
# Delete all stacks in reverse order
cd cdk
npx cdk destroy AgentCoreNovaSonicBidiFrontend --no-cli-pager
npx cdk destroy AgentCoreNovaSonicBidiRuntime --no-cli-pager
npx cdk destroy AgentCoreNovaSonicBidiAuth --no-cli-pager
npx cdk destroy AgentCoreNovaSonicBidiInfra --no-cli-pager

# Redeploy
cd ..
./deploy-all.ps1  # or ./deploy-all.sh
```

**Warning:** This will delete all user accounts in Cognito and all data.

---

## Advanced Deployment

### Deploy to Different Region

```bash
export AWS_DEFAULT_REGION="eu-west-1"
export AWS_REGION="eu-west-1"
./deploy-all.sh
```

### Deploy with Custom Stack Names

Edit `cdk/bin/app.ts` to customize stack names before deploying.

### Deploy Multiple Environments

Use CDK context to deploy multiple environments:

```bash
# Development
npx cdk deploy --all --context environment=dev --no-cli-pager

# Production
npx cdk deploy --all --context environment=prod --no-cli-pager
```

Then modify `cdk/bin/app.ts` to use the context value in stack names.

---

## Cleanup

To remove all deployed resources:

```bash
cd cdk
npx cdk destroy AgentCoreNovaSonicBidiFrontend --no-cli-pager
npx cdk destroy AgentCoreNovaSonicBidiRuntime --no-cli-pager
npx cdk destroy AgentCoreNovaSonicBidiAuth --no-cli-pager
npx cdk destroy AgentCoreNovaSonicBidiInfra --no-cli-pager
```

**Note:** Cognito User Pool will be deleted along with all user accounts.

**Manual cleanup may be required for:**
- ECR images (if you want to delete them)
- CloudWatch log groups (retained by default)
- S3 buckets (may need to empty first if versioning is enabled)
