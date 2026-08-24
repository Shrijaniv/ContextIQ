param(
    [Parameter(Mandatory=$true)]
    [string]$UserPoolId,
    
    [Parameter(Mandatory=$true)]
    [string]$UserPoolClientId,
    
    [Parameter(Mandatory=$true)]
    [string]$IdentityPoolId,
    
    [Parameter(Mandatory=$true)]
    [string]$AgentRuntimeArn,
    
    [Parameter(Mandatory=$true)]
    [string]$Region
)

Write-Host "Building frontend with:"
Write-Host "  User Pool ID: $UserPoolId"
Write-Host "  User Pool Client ID: $UserPoolClientId"
Write-Host "  Identity Pool ID: $IdentityPoolId"
Write-Host "  Agent Runtime ARN: $AgentRuntimeArn"
Write-Host "  Region: $Region"

# Create production environment file
Set-Location frontend

# Note: .env.local is preserved if it exists (used for debug settings like VITE_WS_DEBUG)
# Vite build precedence: .env.local > .env.production.local > .env.production > .env
# This allows debug settings to persist across builds without being overwritten

# Create production environment file
@"
VITE_USER_POOL_ID=$UserPoolId
VITE_USER_POOL_CLIENT_ID=$UserPoolClientId
VITE_IDENTITY_POOL_ID=$IdentityPoolId
VITE_AGENT_RUNTIME_ARN=$AgentRuntimeArn
VITE_REGION=$Region
VITE_LOCAL_DEV=false
"@ | Out-File -FilePath ".env.production.local" -Encoding UTF8

Write-Host "Created production environment configuration"

# Build frontend
npm run build

Set-Location ..
Write-Host "Frontend build complete"
