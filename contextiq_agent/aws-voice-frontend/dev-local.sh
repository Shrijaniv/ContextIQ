#!/bin/bash
# Local Development Script - Start frontend and AgentCore backend locally

echo -e "\033[0;36m=== Local Development Mode ===\033[0m"

# Step 1: Verify AWS credentials
echo -e "\n\033[0;33m[1/8] Verifying AWS credentials...\033[0m"
echo -e "\033[0;90m      (Required for AWS service access when running agent locally)\033[0m"

CALLER_IDENTITY=$(aws sts get-caller-identity 2>&1)
if [ $? -ne 0 ]; then
    echo -e "\033[0;31m      ❌ AWS credentials are not configured or have expired\033[0m"
    echo -e "\n\033[0;33mPlease configure AWS credentials using one of these methods:\033[0m"
    echo -e "\033[0;36m  1. Run: aws configure\033[0m"
    echo -e "\033[0;36m  2. Set environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY\033[0m"
    echo -e "\033[0;36m  3. Use AWS SSO: aws sso login --profile <profile-name>\033[0m"
    echo -e "\n\033[0;90mFor more info: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html\033[0m"
    exit 1
fi

ACCOUNT_ID=$(echo "$CALLER_IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")
ARN=$(echo "$CALLER_IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin)['Arn'])")
echo -e "\033[0;32m      ✓ Authenticated as: $ARN\033[0m"
echo -e "\033[0;32m      AWS Account: $ACCOUNT_ID\033[0m"

# Step 2: Check AWS CLI version
echo -e "\n\033[0;33m[2/8] Checking AWS CLI version...\033[0m"
echo -e "\033[0;90m      (Ensuring compatibility with Bedrock service)\033[0m"
AWS_VERSION=$(aws --version 2>&1)
if [[ $AWS_VERSION =~ aws-cli/([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
    MAJOR=${BASH_REMATCH[1]}
    MINOR=${BASH_REMATCH[2]}
    PATCH=${BASH_REMATCH[3]}
    echo -e "\033[0;90m      Current version: aws-cli/$MAJOR.$MINOR.$PATCH\033[0m"

    if [ "$MAJOR" -gt 2 ] || \
       [ "$MAJOR" -eq 2 -a "$MINOR" -gt 31 ] || \
       [ "$MAJOR" -eq 2 -a "$MINOR" -eq 31 -a "$PATCH" -ge 13 ]; then
        echo -e "\033[0;32m      ✓ AWS CLI version is compatible\033[0m"
    else
        echo -e "\033[0;33m      ⚠ AWS CLI version 2.31.13 or later is recommended for Bedrock\033[0m"
        echo -e "\033[0;33m      Consider upgrading: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html\033[0m"
    fi
else
    echo -e "\033[0;33m      ⚠ Could not parse AWS CLI version, continuing anyway...\033[0m"
fi

# Step 3: Check AgentCore availability in current region
echo -e "\n\033[0;33m[3/8] Checking AgentCore availability in current region...\033[0m"
echo -e "\033[0;90m      (Verifying AgentCore service availability)\033[0m"
CURRENT_REGION=$(aws configure get region)
if [ -z "$CURRENT_REGION" ]; then
    echo -e "\033[0;31m      ❌ No AWS region configured\033[0m"
    echo ""
    echo -e "\033[0;33m      Please configure your AWS region using:\033[0m"
    echo -e "\033[0;36m        aws configure set region <your-region>\033[0m"
    echo ""
    echo -e "\033[0;90m      For supported regions, see:\033[0m"
    echo -e "\033[0;90m      https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-regions.html\033[0m"
    exit 1
fi
echo -e "\033[0;90m      Target region: $CURRENT_REGION\033[0m"

AGENTCORE_CHECK=$(aws bedrock-agentcore-control list-agent-runtimes --region "$CURRENT_REGION" --max-results 1 2>&1)
if [ $? -ne 0 ]; then
    echo -e "\033[0;31m      ❌ AgentCore is not available in region: $CURRENT_REGION\033[0m"
    echo ""
    echo -e "\033[0;90m      Error details: $AGENTCORE_CHECK\033[0m"
    echo ""
    echo -e "\033[0;90m      For supported regions, see:\033[0m"
    echo -e "\033[0;90m      https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-regions.html\033[0m"
    exit 1
fi
echo -e "\033[0;32m      ✓ AgentCore is available in $CURRENT_REGION\033[0m"

# Step 4: Check mkcert availability and generate local HTTPS certificate
echo -e "\n\033[0;33m[4/8] Checking mkcert for local HTTPS...\033[0m"
echo -e "\033[0;90m      (Required for WSS WebSocket support in local dev)\033[0m"

if ! command -v mkcert &> /dev/null; then
    echo -e "\033[0;31m      ❌ mkcert is not installed\033[0m"
    echo ""
    echo -e "\033[0;33m      Install mkcert to enable local HTTPS (required for WSS):\033[0m"
    echo -e "\033[0;36m        brew install mkcert && mkcert -install\033[0m"
    echo -e "\033[0;33m      Then re-run this script.\033[0m"
    exit 1
fi

mkcert -install 2>/dev/null

if [ ! -f "frontend/localhost.pem" ] || [ ! -f "frontend/localhost-key.pem" ]; then
    echo -e "\033[0;90m      Generating localhost certificate...\033[0m"
    mkcert -key-file frontend/localhost-key.pem -cert-file frontend/localhost.pem localhost 2>/dev/null
    echo -e "\033[0;32m      ✓ Certificate generated\033[0m"
else
    echo -e "\033[0;32m      ✓ Certificate already exists\033[0m"
fi

# Step 5: Check Python availability
echo -e "\n\033[0;33m[5/8] Checking Python installation...\033[0m"
echo -e "\033[0;90m      (Required for running the agent locally)\033[0m"
if ! command -v python3 &> /dev/null; then
    echo -e "\033[0;31m      ❌ Python 3.8+ is required but not installed\033[0m"
    echo ""
    echo -e "\033[0;33m      Please install Python 3.8 or later:\033[0m"
    echo -e "\033[0;36m        https://www.python.org/downloads/\033[0m"
    exit 1
fi
PYTHON_VERSION=$(python3 --version 2>&1)
echo -e "\033[0;32m      ✓ $PYTHON_VERSION\033[0m"

# Step 6: Check Node.js availability
echo -e "\n\033[0;33m[6/8] Checking Node.js installation...\033[0m"
echo -e "\033[0;90m      (Required for frontend development server)\033[0m"
if ! command -v node &> /dev/null; then
    echo -e "\033[0;31m      ❌ Node.js 18+ is required but not installed\033[0m"
    echo ""
    echo -e "\033[0;33m      Please install Node.js 18 or later:\033[0m"
    echo -e "\033[0;36m        https://nodejs.org/en/download/\033[0m"
    exit 1
fi
NODE_VERSION=$(node --version 2>&1)
echo -e "\033[0;32m      ✓ Node.js $NODE_VERSION\033[0m"

# Step 7: Install dependencies
echo -e "\n\033[0;33m[7/8] Installing dependencies...\033[0m"

echo -e "\033[0;90m      Installing agent dependencies...\033[0m"
echo -e "\033[0;90m      (bedrock-agentcore for local HTTP server, strands-agents framework, boto3 for AWS)\033[0m"
if [ ! -d "agent/venv" ]; then
    echo -e "\033[0;90m      Creating Python virtual environment and installing dependencies...\033[0m"
    cd agent
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cd ..
else
    echo -e "\033[0;90m      Virtual environment already exists\033[0m"
fi

echo -e "\033[0;90m      Installing frontend dependencies...\033[0m"
cd frontend
if [ ! -d "node_modules" ]; then
    npm install
else
    echo -e "\033[0;90m      Frontend dependencies already installed\033[0m"
fi
cd ..

# Create local environment file for frontend
echo -e "\033[0;90m      Setting up local environment configuration...\033[0m"

if [ -f "frontend/.env.production.local" ]; then
    rm frontend/.env.production.local
fi

cat > frontend/.env.development.local << EOF
VITE_LOCAL_DEV=true
VITE_AGENT_RUNTIME_URL=/api/ws
EOF

echo -e "\033[0;32m      ✓ Created local development environment configuration\033[0m"
echo -e "\033[0;90m      Note: .env.local preserved for debug settings (if exists)\033[0m"

# Step 8: Start services
echo -e "\n\033[0;33m[8/8] Starting local development services...\033[0m"
echo ""
echo -e "\033[0;36mBackend will be available at: http://localhost:8080\033[0m"
echo -e "\033[0;36mFrontend will be available at: https://localhost:5173\033[0m"
echo ""
echo -e "\033[0;90mNote: First visit to https://localhost:5173 is trusted via mkcert - no browser warning expected.\033[0m"
echo ""
echo -e "\033[0;33mDevelopment Workflow:\033[0m"
echo -e "\033[0;90m  • Changes to frontend/ files → Immediate hot reload\033[0m"
echo -e "\033[0;90m  • Changes to agent/ files → Restart this script (Ctrl+C then re-run)\033[0m"
echo ""
echo -e "\033[0;33mPress Ctrl+C to stop all services\033[0m"
echo ""

cleanup() {
    echo ""
    echo -e "\033[0;31mStopping services...\033[0m"
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# Start backend
cd agent
source venv/bin/activate
PYTHONIOENCODING=utf-8 python3 strands_agent.py 2>&1 | sed 's/^/[BACKEND] /' &
BACKEND_PID=$!
cd ..

sleep 2

# Start frontend
cd frontend
npm run dev 2>&1 | sed 's/^/[FRONTEND] /' &
FRONTEND_PID=$!
cd ..

wait "$BACKEND_PID" "$FRONTEND_PID"
