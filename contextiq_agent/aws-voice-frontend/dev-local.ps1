# Local Development Script - Start frontend and AgentCore backend locally

Write-Host "=== Local Development Mode ===" -ForegroundColor Cyan

# Step 1: Verify AWS credentials
Write-Host "`n[1/8] Verifying AWS credentials..." -ForegroundColor Yellow
Write-Host "      (Required for AWS service access when running agent locally)" -ForegroundColor Gray

# Check if AWS credentials are configured
$callerIdentity = aws sts get-caller-identity 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "      ❌ AWS credentials are not configured or have expired" -ForegroundColor Red
    Write-Host "`nPlease configure AWS credentials using one of these methods:" -ForegroundColor Yellow
    Write-Host "  1. Run: aws configure" -ForegroundColor Cyan
    Write-Host "  2. Set environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY" -ForegroundColor Cyan
    Write-Host "  3. Use AWS SSO: aws sso login --profile <profile-name>" -ForegroundColor Cyan
    Write-Host "`nFor more info: https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-quickstart.html" -ForegroundColor Gray
    exit 1
}

# Display current AWS identity
$accountId = ($callerIdentity | ConvertFrom-Json).Account
$arn = ($callerIdentity | ConvertFrom-Json).Arn
Write-Host "      ✓ Authenticated as: $arn" -ForegroundColor Green
Write-Host "      AWS Account: $accountId" -ForegroundColor Green

# Step 2: Check AWS CLI version
Write-Host "`n[2/8] Checking AWS CLI version..." -ForegroundColor Yellow
Write-Host "      (Ensuring compatibility with Bedrock service)" -ForegroundColor Gray
$awsVersion = aws --version 2>&1
$versionMatch = $awsVersion -match 'aws-cli/(\d+)\.(\d+)\.(\d+)'
if ($versionMatch) {
    $major = [int]$Matches[1]
    $minor = [int]$Matches[2]
    $patch = [int]$Matches[3]
    Write-Host "      Current version: aws-cli/$major.$minor.$patch" -ForegroundColor Gray
    
    # Check if version is >= 2.31.13 (recommended for Bedrock)
    $isVersionValid = ($major -gt 2) -or 
                      ($major -eq 2 -and $minor -gt 31) -or 
                      ($major -eq 2 -and $minor -eq 31 -and $patch -ge 13)
    
    if (-not $isVersionValid) {
        Write-Host "      ⚠ AWS CLI version 2.31.13 or later is recommended for Bedrock" -ForegroundColor Yellow
        Write-Host "      Your current version: aws-cli/$major.$minor.$patch" -ForegroundColor Yellow
        Write-Host "      Consider upgrading: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html" -ForegroundColor Gray
    } else {
        Write-Host "      ✓ AWS CLI version is compatible" -ForegroundColor Green
    }
} else {
    Write-Host "      ⚠ Could not parse AWS CLI version, continuing anyway..." -ForegroundColor Yellow
}

# Step 3: Check AgentCore availability in current region
Write-Host "`n[3/8] Checking AgentCore availability in current region..." -ForegroundColor Yellow
Write-Host "      (Verifying AgentCore service availability)" -ForegroundColor Gray
# Detect current region from AWS CLI configuration
$currentRegion = aws configure get region
if ([string]::IsNullOrEmpty($currentRegion)) {
    Write-Host "      ❌ No AWS region configured" -ForegroundColor Red
    Write-Host ""
    Write-Host "      Please configure your AWS region using:" -ForegroundColor Yellow
    Write-Host "        aws configure set region <your-region>" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "      For supported regions, see:" -ForegroundColor Gray
    Write-Host "      https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-regions.html" -ForegroundColor Gray
    exit 1
}
Write-Host "      Target region: $currentRegion" -ForegroundColor Gray

# Try to list AgentCore runtimes to verify service availability
$agentCoreCheck = aws bedrock-agentcore-control list-agent-runtimes --region $currentRegion --max-results 1 2>&1
if ($LASTEXITCODE -ne 0) {
    $errorMessage = $agentCoreCheck | Out-String
    Write-Host "      ❌ AgentCore is not available in region: $currentRegion" -ForegroundColor Red
    Write-Host ""
    Write-Host "      Error details:" -ForegroundColor Gray
    Write-Host "      $errorMessage" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "      For supported regions, see:" -ForegroundColor Gray
    Write-Host "      https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-regions.html" -ForegroundColor Gray
    exit 1
}
Write-Host "      ✓ AgentCore is available in $currentRegion" -ForegroundColor Green

# Step 4: Check mkcert availability and generate local HTTPS certificate
Write-Host "`n[4/8] Checking mkcert for local HTTPS..." -ForegroundColor Yellow
Write-Host "      (Required for WSS WebSocket support in local dev)" -ForegroundColor Gray

if (-not (Get-Command mkcert -ErrorAction SilentlyContinue)) {
    Write-Host "      ❌ mkcert is not installed" -ForegroundColor Red
    Write-Host ""
    Write-Host "      Install mkcert to enable local HTTPS (required for WSS):" -ForegroundColor Yellow
    Write-Host "        winget install FiloSottile.mkcert" -ForegroundColor Cyan
    Write-Host "        mkcert -install" -ForegroundColor Cyan
    Write-Host "      Then re-run this script." -ForegroundColor Yellow
    exit 1
}

# Install local CA if not already done
mkcert -install 2>&1 | Out-Null

# Generate cert for localhost if not present
if (-not (Test-Path "frontend/localhost.pem") -or -not (Test-Path "frontend/localhost-key.pem")) {
    Write-Host "      Generating localhost certificate..." -ForegroundColor Gray
    mkcert -key-file frontend/localhost-key.pem -cert-file frontend/localhost.pem localhost 2>&1 | Out-Null
    Write-Host "      ✓ Certificate generated" -ForegroundColor Green
} else {
    Write-Host "      ✓ Certificate already exists" -ForegroundColor Green
}

# Step 5: Check Python availability
Write-Host "`n[5/8] Checking Python installation..." -ForegroundColor Yellow
Write-Host "      (Required for running the agent locally)" -ForegroundColor Gray
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "      ❌ Python 3.8+ is required but not installed" -ForegroundColor Red
    Write-Host ""
    Write-Host "      Please install Python 3.8 or later:" -ForegroundColor Yellow
    Write-Host "        https://www.python.org/downloads/" -ForegroundColor Cyan
    exit 1
}

$pythonVersion = python --version 2>&1
Write-Host "      ✓ $pythonVersion" -ForegroundColor Green

# Step 6: Check Node.js availability
Write-Host "`n[6/8] Checking Node.js installation..." -ForegroundColor Yellow
Write-Host "      (Required for frontend development server)" -ForegroundColor Gray
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "      ❌ Node.js 18+ is required but not installed" -ForegroundColor Red
    Write-Host ""
    Write-Host "      Please install Node.js 18 or later:" -ForegroundColor Yellow
    Write-Host "        https://nodejs.org/en/download/" -ForegroundColor Cyan
    exit 1
}

$nodeVersion = node --version 2>&1
Write-Host "      ✓ Node.js $nodeVersion" -ForegroundColor Green

# Step 7: Install dependencies
Write-Host "`n[7/8] Installing dependencies..." -ForegroundColor Yellow

# Install agent dependencies if needed
Write-Host "      Installing agent dependencies..." -ForegroundColor Gray
Write-Host "      (bedrock-agentcore for local HTTP server, strands-agents framework, boto3 for AWS)" -ForegroundColor DarkGray
if (-not (Test-Path "agent/venv")) {
    Write-Host "      Creating Python virtual environment and installing dependencies..." -ForegroundColor DarkGray
    Push-Location agent
    python -m venv venv
    & "venv/Scripts/Activate.ps1"
    pip install -r requirements.txt
    Pop-Location
} else {
    Write-Host "      Virtual environment already exists" -ForegroundColor DarkGray
}

# Install frontend dependencies if needed
Write-Host "      Installing frontend dependencies..." -ForegroundColor Gray
Push-Location frontend
if (-not (Test-Path "node_modules")) {
    npm install
} else {
    Write-Host "      Frontend dependencies already installed" -ForegroundColor DarkGray
}
Pop-Location

# Create local environment file for frontend
Write-Host "      Setting up local environment configuration..." -ForegroundColor Gray

# Remove any production environment file
if (Test-Path "frontend/.env.production.local") {
    Remove-Item "frontend/.env.production.local"
}

@"
VITE_LOCAL_DEV=true
VITE_AGENT_RUNTIME_URL=/api/ws
"@ | Out-File -FilePath "frontend/.env.development.local" -Encoding UTF8

Write-Host "      ✓ Created local development environment configuration" -ForegroundColor Green
Write-Host "      Note: .env.local preserved for debug settings (if exists)" -ForegroundColor DarkGray

# Step 8: Start services
Write-Host "`n[8/8] Starting local development services..." -ForegroundColor Yellow

Write-Host ""
Write-Host "Backend will be available at: http://localhost:8080" -ForegroundColor Cyan
Write-Host "Frontend will be available at: https://localhost:5173" -ForegroundColor Cyan
Write-Host ""
Write-Host "Note: First visit to https://localhost:5173 is trusted via mkcert - no browser warning expected." -ForegroundColor Gray
Write-Host ""
Write-Host "Development Workflow:" -ForegroundColor Yellow
Write-Host "  • Changes to frontend\ files → Immediate hot reload" -ForegroundColor Gray
Write-Host "  • Changes to agent\ files → Restart this script (Ctrl+C then re-run)" -ForegroundColor Gray
Write-Host ""
Write-Host "Press Ctrl+C to stop all services" -ForegroundColor Yellow
Write-Host ""
Write-Host "=== Backend Output (Green) ===" -ForegroundColor Green
Write-Host "=== Frontend Output (Blue) ===" -ForegroundColor Blue
Write-Host ""

# Start AgentCore backend in background
Push-Location agent
& "venv/Scripts/Activate.ps1"
$backendJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    & "venv/Scripts/Activate.ps1"
    # Set UTF-8 encoding for Python to handle Unicode characters properly on Windows
    $env:PYTHONIOENCODING = "utf-8"
    python strands_agent.py 2>&1
}
Pop-Location

# Wait a moment for backend to start
Start-Sleep -Seconds 2

# Start frontend dev server in background
Push-Location frontend
$frontendJob = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    npm run dev 2>&1
}
Pop-Location

# Function to cleanup
function Cleanup {
    Write-Host ""
    Write-Host "`nStopping services..." -ForegroundColor Red
    Stop-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
    Remove-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
}

# Register cleanup on Ctrl+C
Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Cleanup }

try {
    # Wait for jobs and show output with better formatting
    $lastBackendOutput = ""
    $lastFrontendOutput = ""
    
    while ($backendJob.State -eq "Running" -or $frontendJob.State -eq "Running") {
        # Get backend output
        $backendOutput = Receive-Job $backendJob -ErrorAction SilentlyContinue
        if ($backendOutput -and $backendOutput -ne $lastBackendOutput) {
            $backendOutput | ForEach-Object {
                Write-Host "[BACKEND] $_" -ForegroundColor Green
            }
            $lastBackendOutput = $backendOutput
        }
        
        # Get frontend output
        $frontendOutput = Receive-Job $frontendJob -ErrorAction SilentlyContinue
        if ($frontendOutput -and $frontendOutput -ne $lastFrontendOutput) {
            $frontendOutput | ForEach-Object {
                Write-Host "[FRONTEND] $_" -ForegroundColor Cyan
            }
            $lastFrontendOutput = $frontendOutput
        }
        
        # Check if jobs failed
        if ($backendJob.State -eq "Failed") {
            Write-Host "`n❌ Backend job failed!" -ForegroundColor Red
            Receive-Job $backendJob -ErrorAction SilentlyContinue | Write-Host -ForegroundColor Red
            break
        }
        if ($frontendJob.State -eq "Failed") {
            Write-Host "`n❌ Frontend job failed!" -ForegroundColor Red
            Receive-Job $frontendJob -ErrorAction SilentlyContinue | Write-Host -ForegroundColor Red
            break
        }
        
        Start-Sleep -Milliseconds 500
    }
} finally {
    Cleanup
}