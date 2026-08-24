# Architecture Guide

This guide explains the technical architecture, design decisions, and project structure.

## Table of Contents

- [System Architecture](#system-architecture)
- [Stack Architecture](#stack-architecture)
- [Project Structure](#project-structure)
- [Design Decisions](#design-decisions)
- [Request Flow](#request-flow)

---

## System Architecture

### Voice Pipeline

1. **Authentication**: User signs in → Cognito User Pool → Identity Pool exchanges JWT for AWS credentials
2. **Browser → AgentCore**: Microphone captures audio → AudioWorklet converts to PCM 16kHz mono → WebSocket with SigV4 signing sends to AgentCore
3. **AgentCore → Nova Sonic**: AgentCore receives PCM → Strands BidiAgent streams to Nova Sonic (voice: tiffany)
4. **Nova Sonic → Browser**: Agent responds with PCM audio + transcripts → Browser decodes and plays audio
5. **Real-Time Transcripts**: Both user and assistant speech transcribed and displayed as ChatBubbles
6. **Tool Execution**: Nova Sonic can invoke `calculate_expression` and `get_weather` tools asynchronously

### Architecture Diagram

![Architecture Diagram](../img/architecture_diagram.svg)

---

## Stack Architecture

The application is deployed as four CloudFormation stacks:

| Stack Name | Purpose | Key Resources | Update Frequency |
|------------|---------|---------------|------------------|
| **AgentCoreNovaSonicBidiInfra** | Build infrastructure | ECR Repository, S3 Code Bucket, CodeBuild Project, IAM Roles | Rarely (initial setup) |
| **AgentCoreNovaSonicBidiAuth** | Authentication | Cognito User Pool, User Pool Client, Identity Pool, Authenticated IAM Role | Rarely (auth config changes) |
| **AgentCoreNovaSonicBidiRuntime** | Agent runtime with WebSocket | AgentCore Runtime with Container Deployment, WebSocket Protocol, IAM Authentication | Frequently (agent code updates) |
| **AgentCoreNovaSonicBidiFrontend** | Web UI | S3 Bucket, CloudFront Distribution, React Voice UI | Frequently (UI updates) |

### Why Four Stacks?

**Separation of Concerns:**
- **Infrastructure stack** contains resources that rarely change (ECR, S3, IAM roles)
- **Auth stack** contains authentication resources that rarely change (Cognito)
- **Runtime stack** changes when agent code updates
- **Frontend stack** changes when UI updates

**Benefits:**
- Independent updates without rebuilding everything
- Faster deployment cycles (only update what changed)
- Easier rollback (rollback specific stack without affecting others)
- Better resource organization and management

---

## Project Structure

```
project-root/
├── agent/                              # Agent runtime code
│   ├── strands_agent.py                # BidiAgent implementation (Strands framework)
│   ├── requirements.txt                # Python dependencies
│   ├── Dockerfile                      # ARM64 container definition
│   └── venv/                           # Python virtual environment (gitignored)
│
├── cdk/                                # Infrastructure as Code
│   ├── bin/
│   │   └── app.ts                      # CDK app entry point
│   ├── lib/
│   │   ├── infra-stack.ts              # Build infrastructure (S3, IAM)
│   │   ├── auth-stack.ts               # Cognito User Pool, Identity Pool, IAM roles
│   │   ├── runtime-stack.ts            # AgentCore runtime with WebSocket
│   │   ├── build-trigger-stack.ts      # CodeBuild trigger Lambda
│   │   ├── build-waiter-function.ts    # Build completion waiter
│   │   └── frontend-stack.ts           # CloudFront + S3
│   ├── cdk.json                        # CDK configuration
│   ├── cdk.out/                        # CDK synthesis output (gitignored)
│   ├── tsconfig.json                   # TypeScript configuration
│   ├── package.json                    # CDK dependencies
│   └── node_modules/                   # CDK dependencies (gitignored)
│
├── frontend/                           # React voice UI (Vite)
│   ├── src/
│   │   ├── App.tsx                     # Main voice UI component
│   │   ├── App.css                     # Main component styles
│   │   ├── index.css                   # Global styles
│   │   ├── favicon.ico                 # Application favicon
│   │   ├── AuthModal.tsx               # Sign in/sign up modal
│   │   ├── hooks/
│   │   │   └── useVoiceAgent.ts        # Voice agent WebSocket hook
│   │   ├── components/                 # Reusable UI components
│   │   ├── websocket-presigned.ts      # WebSocket with SigV4 presigned URLs
│   │   ├── aws-credentials.ts          # Cognito Identity Pool credential management
│   │   ├── auth.ts                     # Cognito User Pool authentication
│   │   ├── audio-processor.worklet.ts  # Audio processing worklet
│   │   └── main.tsx                    # React entry point
│   ├── index.html                      # HTML entry point
│   ├── debug.html                      # Debug console for local testing
│   ├── vite.config.ts                  # Vite configuration
│   ├── tsconfig.json                   # TypeScript configuration
│   ├── package.json                    # Frontend dependencies (includes AWS SDK)
│   ├── dist/                           # Build output (gitignored)
│   └── node_modules/                   # Frontend dependencies (gitignored)
│
├── docs/                               # Documentation
│   ├── TROUBLESHOOTING.md              # Troubleshooting guide
│   ├── DEPLOYMENT.md                   # Deployment guide
│   ├── ARCHITECTURE.md                 # This file
│   └── CUSTOMIZATION.md                # UI customization guide
│
├── img/                                # Architecture diagrams
│   ├── architecture_diagram.drawio     # Draw.io source file
│   └── architecture_diagram.svg        # Architecture diagram
│
├── scripts/
│   ├── build-frontend.ps1              # Builds React app with config injection (Windows)
│   └── build-frontend.sh               # Builds React app with config injection (macOS/Linux)
│
├── deploy-all.ps1                      # Full deployment orchestration (Windows)
├── deploy-all.sh                       # Full deployment orchestration (macOS/Linux)
├── dev-local.ps1                       # Local development mode (Windows)
├── dev-local.sh                        # Local development mode (macOS/Linux)
└── README.md                           # Quick start guide
```

---

## Design Decisions

### CDK vs AgentCore CLI

This project uses AWS CDK to replicate the functionality of the AgentCore CLI's `agentcore launch` command.

**AgentCore CLI Approach:**
```bash
# Simple CLI commands handle everything
agentcore configure -e agent.py
agentcore launch
```

**Our CDK Approach:**
```bash
# Infrastructure as Code with same end result
./deploy-all.ps1  # or ./deploy-all.sh
```

**Why CDK Instead of CLI?**
- **Full-stack deployment**: Includes authentication, frontend, and infrastructure
- **Reproducible infrastructure**: Version-controlled, declarative infrastructure
- **Team collaboration**: Shared infrastructure definitions
- **Integration flexibility**: Easy to extend with additional AWS services
- **Production readiness**: Proper IAM roles, security groups, and resource tagging

Both approaches create the same AgentCore runtime, but CDK provides more control over the complete application stack.

### Why Container Deployment?

AgentCore supports two deployment methods: container-based (ECR) and direct code upload (S3 ZIP). This demo uses container deployment for WebSocket support:

**Benefits:**
- **WebSocket Protocol**: Required for real-time bidirectional voice streaming
- **Production-ready**: Suitable for voice applications requiring low latency
- **Consistent environment**: Container ensures dependencies are pre-installed
- **Better for voice**: Real-time audio requires persistent connections
- **Reproducible builds**: Same container works everywhere

**Trade-offs:**
- Longer deployment time (~10 minutes vs ~30 seconds for direct code)
- Requires CodeBuild for container compilation
- More complex infrastructure

**When to use direct code upload:**
- Simple text-based agents
- HTTP request/response pattern
- Rapid prototyping
- No WebSocket requirements

**Architecture Note:** This demo uses WebSocket protocol for real-time bidirectional voice streaming with Amazon Nova 2 Sonic, requiring container deployment. Direct code upload (S3 ZIP) is not supported for WebSocket-based agents.

### Why ARM64?

AgentCore natively supports ARM64 architecture, providing:
- **Better performance**: ARM64 processors optimized for AI workloads
- **Cost efficiency**: Lower compute costs compared to x86_64
- **Native support**: No emulation overhead
- **Future-proof**: Industry trend toward ARM architecture

### Why Cognito Identity Pool?

**Authentication Flow:**
1. User signs in with email/password → Cognito User Pool
2. User Pool returns JWT access token
3. Frontend exchanges JWT for AWS credentials → Cognito Identity Pool
4. Identity Pool returns temporary AWS credentials (access key, secret key, session token)
5. Frontend uses credentials to sign WebSocket requests with SigV4

**Benefits:**
- **No API Gateway needed**: Direct WebSocket connection to AgentCore
- **IAM-based authorization**: Leverage AWS IAM for fine-grained permissions
- **Temporary credentials**: Credentials expire automatically (1 hour default)
- **Secure**: No long-lived credentials in browser
- **Scalable**: Cognito handles credential vending at scale

**Alternative approaches:**
- Custom authorizer Lambda (more complex, higher latency)
- API Gateway with Cognito authorizer (adds extra hop)
- Direct IAM credentials (not recommended for browser apps)

---

## Request Flow

### Deployment Flow

The `deploy-all.ps1` script orchestrates the complete deployment:

1. **Verify AWS credentials** (checks AWS CLI configuration)
2. **Check AWS CLI version** (requires v2.31.13+ for AgentCore support)
3. **Check AgentCore availability** (verifies service is available in your configured region)
4. **Install CDK dependencies** (cdk/node_modules)
5. **Install frontend dependencies** (frontend/node_modules, includes AWS SDK for Cognito Identity and Bedrock AgentCore)
6. **Create placeholder frontend build** (for initial deployment)
7. **Bootstrap CDK environment** (sets up CDK deployment resources in your AWS account/region)
8. **Deploy AgentCoreNovaSonicBidiInfra** - Creates infrastructure resources:
   - S3 bucket for agent code storage
   - IAM role for AgentCore runtime
9. **Deploy AgentCoreNovaSonicBidiAuth** - Creates authentication resources:
    - Cognito User Pool (email/password)
    - User Pool Client for frontend
    - Cognito Identity Pool for AWS credentials
    - Authenticated IAM Role with Bedrock AgentCore permissions
    - Password policy (min 8 chars, uppercase, lowercase, digit)
10. **Deploy AgentCoreNovaSonicBidiRuntime** - Deploys agent with IAM authentication:
    - Packages agent code as ZIP with ARM64 dependencies
    - Uploads ZIP to S3
    - Triggers CodeBuild to build Docker container
    - Waits for build completion
    - Creates AgentCore runtime with container image
    - Uses default IAM SigV4 authentication (~10 minutes)
11. **Build frontend with AgentCore ARN and Cognito config, then deploy AgentCoreNovaSonicBidiFrontend**:
    - Retrieves AgentCore Runtime ARN and Cognito config (User Pool, Identity Pool) from stack outputs
    - Builds React app with injected configuration
    - S3 bucket for static hosting
    - CloudFront distribution with OAC
    - Deploys React app with authentication UI

### Runtime Request Flow

1. User signs in via Cognito User Pool (email verification required)
2. Frontend receives JWT access token from Cognito User Pool
3. Frontend exchanges JWT for AWS credentials via Cognito Identity Pool
4. User initiates voice conversation in React UI
5. Frontend establishes WebSocket connection to AgentCore with SigV4 signing using AWS credentials
6. AgentCore validates IAM credentials (SigV4 signature)
7. AgentCore executes agent in isolated container (microVM)
8. Agent processes audio using Strands framework + Amazon Nova Sonic
9. Bidirectional audio streaming between browser and agent via WebSocket

---

## Key Components

### 1. Authentication (`AgentCoreNovaSonicBidiAuth` stack)
- **Cognito User Pool** for user management
- Email-based authentication with verification
- Password policy: min 8 chars, uppercase, lowercase, digit
- **Cognito Identity Pool** for AWS credential vending
- **Authenticated IAM Role** with Bedrock AgentCore permissions
- **Frontend integration** via AWS SDK for JavaScript v3
- Sign in/sign up modal with email confirmation flow
- **IAM SigV4 Authentication**: Uses AWS Signature Version 4 for WebSocket authentication (see [AgentCore Authentication Guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-authentication.html))

### 2. Agent (`agent/strands_agent.py`)
- Built with Strands Agents framework
- Uses Amazon Nova 2 Sonic (bidirectional voice model)
- Includes `calculate_expression` and `get_weather` tools
- FastAPI WebSocket server for real-time voice streaming

### 3. WebSocket Deployment
- ARM64 architecture (native AgentCore support)
- Python 3.13 runtime
- Container-based deployment for WebSocket support
- FastAPI server with bidirectional streaming
- Real-time audio processing with Nova Sonic

### 4. IAM SigV4 Authentication
- Frontend obtains AWS credentials from Cognito Identity Pool
- WebSocket connections signed with AWS Signature Version 4
- Authenticated IAM role grants Bedrock AgentCore permissions
- Credentials automatically refreshed when expired
- Session management handled by AWS SDK

### 5. IAM Permissions
The execution role includes:
- Bedrock model invocation
- ECR image access
- CloudWatch Logs & Metrics
- X-Ray tracing
- AgentCore Identity (workload access tokens)

### 6. Built-in Observability
- **CloudWatch Logs:** `/aws/bedrock-agentcore/runtimes/nova_sonic_bidi_agent-*`
- **X-Ray Tracing:** Distributed tracing enabled
- **CloudWatch Metrics:** Custom metrics in `bedrock-agentcore` namespace

---

## Security Architecture

### Authentication & Authorization

**Multi-layer security:**
1. **User authentication**: Cognito User Pool with email verification
2. **Credential vending**: Cognito Identity Pool provides temporary AWS credentials
3. **Request signing**: WebSocket requests signed with SigV4
4. **IAM authorization**: AgentCore validates IAM credentials
5. **Least privilege**: Authenticated role has minimal Bedrock AgentCore permissions

### Network Security

- Frontend served via HTTPS (CloudFront)
- WebSocket connections use WSS (secure WebSocket)
- Origin Access Control (OAC) for S3/CloudFront
- No public S3 bucket access

### Runtime Security

- AgentCore Runtime runs in isolated microVMs
- Container images stored securely in ECR
- Code stored securely in S3 with encryption
- CloudWatch logs for audit trail

### Credential Management

- Temporary credentials (1 hour expiration)
- Credentials never exposed to browser (managed by AWS SDK)
- Automatic credential refresh
- No long-lived credentials in frontend code

---

## Performance Considerations

### Latency

**WebSocket connection:**
- Direct connection to AgentCore (no API Gateway hop)
- Low-latency bidirectional streaming
- Real-time audio processing

**Cold start:**
- Container-based deployment has ~2-3 second cold start
- Subsequent requests are fast (container stays warm)

### Scalability

- AgentCore automatically scales based on demand
- Cognito handles authentication at scale
- CloudFront provides global CDN
- No server management required

### Cost Optimization

- ARM64 architecture reduces compute costs
- Consumption-based pricing (only pay for active processing)
- CloudFront free tier covers light usage
- Cognito free tier covers first 10,000 MAUs

---

## Monitoring & Observability

### CloudWatch Logs

**Runtime logs:**
```bash
/aws/bedrock-agentcore/runtimes/{runtime-id}-DEFAULT
```

**What's logged:**
- Agent startup and initialization
- WebSocket connection events
- Tool execution
- Errors and exceptions
- Model API calls

### CloudWatch Metrics

**Namespace:** `bedrock-agentcore`

**Key metrics:**
- Request count
- Error rate
- Latency (p50, p99)
- Token usage

### X-Ray Tracing

- Distributed tracing enabled by default
- Trace requests across services
- Identify performance bottlenecks
- Debug errors in production

---

## Future Enhancements

Potential improvements to the architecture:

1. **Multi-region deployment**: Deploy to multiple regions for global availability
2. **Custom domain**: Add Route53 and ACM certificate
3. **Advanced monitoring**: CloudWatch alarms, dashboards
4. **Memory integration**: Add AgentCore Memory for persistent context
5. **MFA**: Enable multi-factor authentication in Cognito
6. **Social login**: Add Google/Facebook OAuth
7. **API Gateway**: Add REST API for non-WebSocket clients
8. **CI/CD pipeline**: Automated testing and deployment
