# ContextIQ: Ambient Context Voice Assistant

**Amazon Developer Hackathon 2026** · Team: Shrijani, Mitravinda, Robert, Jun Hyung Lee

ContextIQ gives Alexa+ a memory. The [Bee Pioneer](https://www.bee.computer/) wearable captures your conversations throughout the day. When you ask Alexa+ to help with something you already discussed, it already knows — no repetition needed.

> *"Help me plan the taco night I was talking about"*
> → Recalls guests, dietary restrictions, and plans from earlier conversations. Checks weather. Suggests rescheduling if needed. Orders missing ingredients. Creates calendar events and reminders.

---

## Setup

### Prerequisites

- Python 3.12+
- Node.js 18+
- AWS credentials with Bedrock + Neptune access
- Chrome browser (for Amazon shopping)

### Step 1 — Clone and Create Virtual Environment

```bash
git clone <repo-url>
cd ContextIQ

python3 -m venv venv
source venv/bin/activate
```

### Step 2 — Install Dependencies

```bash
pip install -r requirements.txt

cd contextiq_agent/aws-voice-frontend/frontend
npm install
cd ../../..
```

### Step 3 — Install Playwright for Amazon Shopping

```bash
npm install -g playwright-cli
playwright-cli install chromium
```

### Step 4 — Configure Environment

```bash
cp .env.example .env
```

Required variables:

```bash
# AWS
AWS_REGION=us-west-2
AWS_PROFILE=your-aws-profile
AWS_ACCOUNT_ID=your-12-digit-account-id

# Memory — GraphRAG KB + Neptune (agent runtime)
GRAPHRAG_KB_ID=your-graphrag-kb-id
NEPTUNE_GRAPH_ID=your-neptune-graph-id

# APIs
OPENWEATHERMAP_API_KEY=your-key   # https://openweathermap.org/api
TAVILY_API_KEY=your-key           # https://tavily.com
TODOIST_API_TOKEN=your-token      # https://todoist.com/app/settings/integrations/developer
YELP_API_KEY=your-key             # https://www.yelp.com/developers/v3/manage_app

# Ingestion scripts (context_engine/ only, not needed for agent runtime)
GRAPHRAG_DS_ID=your-datasource-id
BEE_CONTEXT_BUCKET=bee-context-store-<account-id>-<region>
BEE_ACCOUNT_ID=your-bee-account-id

# Optional: mock weather for demos (returns rain Wed, clear Thu)
WEATHER_MOCK=true
```

### Step 5 — Amazon Shopping: Log In Once

```bash
playwright-cli -s=amazon open https://www.amazon.com --headed
# Log in to Amazon — session is saved automatically
```

### Step 6 — Start the Voice Server

```bash
source venv/bin/activate
AWS_PROFILE=your-profile python contextiq_agent/voice_server.py
```

### Step 7 — Start the Frontend

```bash
cd contextiq_agent/aws-voice-frontend/frontend
VITE_LOCAL_DEV=true VITE_AGENT_RUNTIME_URL=ws://localhost:8080/ws npm run dev
```

Open **http://localhost:5173** in Chrome.

---

## Architecture

```
Bee Pioneer wearable
      ↓  captures ambient conversations
Bee API  (hourly Lambda sync)
      ↓
S3 (clean/ prefix)
      ↓
GraphRAG KB  (Bedrock; Neptune Analytics as vector store)
 · semantic vector search + automatic graph expansion
      ↓
      retrieve_context tool  (retrieve → Cohere rerank → top chunks)
                    ↓
        Amazon Nova Sonic 2
        (speech-to-speech via BidiAgent)
                    ↓
        FastAPI WebSocket Server
                    ↓
        React Frontend (Alexa+ Simulator)
```

### Memory: GraphRAG Retrieval

Context is retrieved through a **single path** — the Bedrock GraphRAG knowledge
base, whose vector store is one Neptune Analytics graph. A single `Retrieve`
call does both semantic vector search and automatic graph expansion over the
entity relationships Bedrock extracts at ingestion, so there is no separate
Neptune query at request time.

The `retrieve_context` tool over-retrieves 15 chunks (SEMANTIC), reranks them with
Cohere Rerank 3.5 down to the top 5, and returns the ranked conversation
context. See [`context_engine/docs/agent-context.md`](context_engine/docs/agent-context.md)
for the full strategy.

### Voice Stack

| Component | Technology |
|---|---|
| Voice model | Amazon Nova Sonic 2 (bidirectional streaming) |
| Agent framework | Strands Agents SDK — `BidiAgent` |
| Memory | `retrieve_context` — GraphRAG KB retrieval + Cohere reranking |
| Frontend | React + Cloudscape Design System |
| Server | FastAPI + WebSocket |

### Agent Tools

| Tool | What It Does |
|---|---|
| `retrieve_context` | Retrieves ranked context from the GraphRAG KB (semantic + graph expansion, reranked) |
| `check_weather` | Proactively checks weather for outdoor plans |
| `amazon_shopping` | Search → select → add to cart via browser automation |
| `create_calendar_event` | Creates events in the frontend calendar |
| `create_reminder` | Creates tasks with due dates via Todoist |
| `search_restaurants` | Finds nearby restaurants with ratings |
| `opentable_reserve` | Books restaurant reservations via OpenTable |
| `search_web` | Web search via Tavily |

### Bee Context Pipeline (`context_engine/`)

```
Bee API /v1/changes
      ↓  hourly Lambda (EventBridge)
Clean text → S3 clean/ prefix
      ↓
GraphRAG KB re-index (Bedrock ingestion job)
 · Titan v2 embeddings + Claude 3.5 Haiku entity extraction
   into the Neptune Analytics vector store
```

---

## User Stories

### Taco Night Planning

**Setup:** Bee captured a conversation where Mitra and Bobby plan a taco night on Wednesday April 22nd with Shrijani and Jun. Shrijani is vegetarian and needs black beans.

```
User:   "Help me plan the taco night"
Alexa+: "Rain on Wednesday for the waterfront walk — Thursday looks clear. Move it?"
User:   "Yes"
Alexa+: "Moved to Thursday. Memory shows you need to grab black beans. Want me to search Amazon?"
User:   "Yes"
Alexa+: "Found 365 Organic Black Beans at $3.92 and Iberia Black Beans at $6.88. First or second?"
User:   "First one"
Alexa+: "Added to your cart. Anything else from that conversation?"
```

What happened automatically:
- `retrieve_context` recalled guests, date, vegetarian requirement
- `check_weather` detected rain silently, surfaced the alert
- `create_calendar_event` booked Thursday after confirmation
- `create_reminder` created a Todoist task
- `amazon_shopping` searched and added black beans

### Commitment Detection

```
User:   "What did I commit to today?"
Alexa+: "Two commitments: report by Friday and a call this weekend. Want reminders?"
User:   "Yes"
Alexa+: "Done. Both set in Todoist."
```

### Birthday Dinner Planning

```
User:   "Help me plan Bobby's birthday dinner"
Alexa+: "Bobby's birthday is May 5th — Mitra and Shrijani are planning it for about 6 people.
         Restaurant is TBD between Luca's and a rooftop spot. Search OpenTable?"
```

---

## AWS Permissions Required

| Permission | Purpose |
|---|---|
| `bedrock:InvokeModelWithResponseStream` | Nova Sonic voice model |
| `bedrock:Retrieve` | GraphRAG KB retrieval |
| `bedrock:StartIngestionJob` | Lambda triggers KB re-index |
| `neptune-graph:ExecuteQuery` | Knowledge graph queries |
| `s3:GetObject`, `s3:PutObject` | Lambda reads/writes Bee data |
| `secretsmanager:GetSecretValue` | Lambda reads Bee API token |

---

## Context Engine (Ingestion Pipeline)

The `context_engine/` package ingests conversation data from the Bee Pioneer
wearable into S3, indexes it in the Bedrock GraphRAG Knowledge Base, and
provides the runtime `retrieve_context` tool. An hourly Lambda pulls new Bee
conversations, writes clean text to S3, and triggers a KB re-index; Bedrock's
GraphRAG configuration extracts entities into the Neptune Analytics graph that
*is* the KB's vector store — one physical graph, one retrieval path.

### AWS Resources

Resource IDs are deployment-specific and read from your `.env` — nothing is
hardcoded. `context_engine/util-scripts/setup-aws.sh` creates these and prints
the values to paste into `.env`.

| Resource | Naming / Env Var |
|---|---|
| S3 Bucket | `bee-context-store-<account-id>-<region>` → `BEE_CONTEXT_BUCKET` |
| Lambda | `BeeContextQueryStack-BeeIngestFn*` |
| EventBridge | `rate(1 hour)`, ENABLED |
| Bedrock KB (GraphRAG) | `bee-graphrag-kb` → `GRAPHRAG_KB_ID` / `GRAPHRAG_DS_ID` |
| Neptune Analytics | `bee-knowledge-graph` → `NEPTUNE_GRAPH_ID` (~$0.96/hr, pausable at 10%) |
| Secrets Manager | `bee-api-token` |
| Account / Region | `AWS_ACCOUNT_ID`, `AWS_REGION` |

### Link Your Bee Pioneer Device

The pipeline syncs whatever conversations belong to your Bee account. The token
*is* the identity — there is no device ID in the pipeline.

1. Create a Bee account and pair your Bee Pioneer wearable in the **Bee mobile
   app** (out of band — this is how the device streams conversations to your
   account).
2. **Enable Developer Mode** in the app: update to the latest Bee iOS app, open
   **Settings**, find the app **Version** row, and tap it **5 times** to unlock
   Developer Mode ([docs](https://docs.bee.computer/docs/developer-mode)).
3. Authenticate the [Bee CLI](https://docs.bee.computer/docs/cli) — `bee login`
   stores your credentials locally; `bee status` confirms authentication.
4. `setup-aws.sh` then writes the token into the `bee-api-token` secret as
   `{"bee_token": "..."}`, which the hourly Lambda reads.

```bash
# Bee CLI: install, then authenticate (opens an approval link)
npm install -g @beeai/cli
bee login          # use `bee login --no-wait` for automation
bee status         # verify: should show authenticated
```

You can also supply an existing token directly with `bee login --token <token>`
or `bee login --token-stdin`.

The token flows into AWS via `setup-aws.sh`, which reads it from (in order):
the `BEE_TOKEN` env var, the macOS keychain (`bee login`), or an interactive
prompt. To pass it explicitly as config:

```bash
BEE_TOKEN=<your-bee-token> ./context_engine/util-scripts/setup-aws.sh
```

### Package Structure

```
context_engine/
├── cdk/                            # Infrastructure (Neptune graph, GraphRAG KB, S3, Lambda, IAM)
│   └── stack.py
├── lambda/                         # Hourly data job (Bee API → S3 → KB re-index)
│   └── handler.py
├── tools/                          # Runtime agent tool
│   └── agent_context_retrieval.py  # retrieve_context: GraphRAG KB retrieval + reranking
├── docs/
│   └── agent-context.md            # Retrieval strategy spec
├── util-scripts/                   # Ops, ingestion, and dev scripts
│   ├── knowledge_graph.py          # Offline KG library (Neptune queries, entity extraction, write-back)
│   ├── chat.py                     # Text chat harness (dev)
│   ├── query_kb.py                 # Query GraphRAG KB and see scored chunks
│   ├── ingest_text.py              # Ingest raw text into KB
│   ├── generate_conversation.py    # Generate Bee-style conversations from descriptions
│   ├── ingest_bee_sync.py          # One-time backfill from bee sync export
│   ├── ingest_knowledge_graph.py   # Batch ingest all S3 docs into the KG
│   ├── create-graphrag-kb.sh       # Provision the GraphRAG KB + Neptune graph
│   ├── prefill.sh                  # bee sync → S3 → KB
│   ├── invoke-lambda.sh            # Manual Lambda trigger + KB re-index
│   ├── lambda-status.sh            # Lambda schedule status + run history
│   ├── verify-bee-api.sh           # Check Lambda + Bee API connectivity
│   └── setup-aws.sh                # First-time full AWS setup
└── tests/
    ├── test_all.py                 # Comprehensive tests for all components
    ├── test_graphrag_vs_vector.py  # GraphRAG retrieval quality test
    └── test_knowledge_graph.py     # Interactive KG test/demo
```

> The custom knowledge graph (`util-scripts/knowledge_graph.py`) is **offline
> tooling**, not on the runtime retrieval path. It maintains `KGEntity`/`KGAction`
> nodes in the same Neptune graph for entity tracking and agent write-back.
> Runtime context retrieval is GraphRAG-KB-only (see `docs/agent-context.md`).

### Query & Ingest

```bash
# Query the GraphRAG KB and see scored chunks
AWS_DEFAULT_REGION=us-west-2 python3 context_engine/util-scripts/query_kb.py "what activities did my friends plan?"
AWS_DEFAULT_REGION=us-west-2 python3 context_engine/util-scripts/query_kb.py "birthday dinner" --user "$BEE_ACCOUNT_ID" --results 15

# Ingest raw text (uploads to S3, triggers KB re-index)
AWS_DEFAULT_REGION=us-west-2 python3 context_engine/util-scripts/ingest_text.py --file transcript.txt --title "Dinner plans"

# Generate a realistic Bee-style conversation, then auto-ingest
AWS_DEFAULT_REGION=us-west-2 python3 context_engine/util-scripts/generate_conversation.py \
  --prompt "Mitra and Bobby plan a taco night for Wednesday with Shrijani and Jun"
```

### Ops Scripts

```bash
./context_engine/util-scripts/verify-bee-api.sh            # Check Lambda + Bee API auth
./context_engine/util-scripts/lambda-status.sh             # Schedule status, recent runs, uptime
./context_engine/util-scripts/invoke-lambda.sh             # Manual Lambda trigger + KB re-index
./context_engine/util-scripts/prefill.sh ~/bee-data "$BEE_ACCOUNT_ID"  # One-time backfill via bee sync
```

### Run Tests

```bash
AWS_DEFAULT_REGION=us-west-2 python3 context_engine/tests/test_all.py         # full suite
AWS_DEFAULT_REGION=us-west-2 python3 context_engine/tests/test_all.py -v      # verbose
```

### Deploy / Redeploy

```bash
# Package Lambda
cd context_engine/lambda
rm -rf package && mkdir package
pip install -r requirements.txt -t package
cp handler.py bee_ca.pem package/

# Deploy stack (adopts the existing live resources via cdk import — see docs/agent-context.md)
cd ../cdk
pip install -r requirements.txt
AWS_DEFAULT_REGION=us-west-2 cdk deploy --require-approval never
```

### Neptune Cost Management

```bash
# Pause Neptune when not in use (~$0.10/hr instead of ~$0.96/hr)
AWS_DEFAULT_REGION=us-west-2 aws neptune-graph stop-graph --graph-identifier "$NEPTUNE_GRAPH_ID"
AWS_DEFAULT_REGION=us-west-2 aws neptune-graph start-graph --graph-identifier "$NEPTUNE_GRAPH_ID"
AWS_DEFAULT_REGION=us-west-2 aws neptune-graph get-graph --graph-identifier "$NEPTUNE_GRAPH_ID" --query status --output text
```

### S3 Structure

```
s3://$BEE_CONTEXT_BUCKET/
├── state/cursor.json                       # Lambda sync cursor
├── conversations/{id}.json                 # Raw JSON (not indexed)
├── daily/{id}.json                         # Raw JSON (not indexed)
├── facts/{id}.json                         # Raw JSON (not indexed)
└── clean/                                  # ← GraphRAG KB indexes this prefix
    ├── conversations/{id}.txt              # Clean transcript text
    ├── conversations/{id}.txt.metadata.json
    ├── daily/{id}.txt                      # Clean daily summary
    ├── facts/all_facts.txt                 # All facts in one file
    └── facts/all_facts.txt.metadata.json
```

Each `.metadata.json` sidecar enables KB filtering by user:
```json
{"metadataAttributes": {"beeAccountId": "<your-bee-account-id>", "date": "2026-04-05"}}
```

---

## Troubleshooting

**Agent connects but doesn't respond**
- Verify `AWS_PROFILE` has `bedrock:InvokeModelWithResponseStream` permission
- Confirm region is `us-west-2` (Nova Sonic availability)

**Memory returns no context**
- Verify `GRAPHRAG_KB_ID` and `NEPTUNE_GRAPH_ID` are set in `.env`
- Run `AWS_PROFILE=your-profile python3 context_engine/util-scripts/query_kb.py "your query"`
- Check Neptune is running: `aws neptune-graph get-graph --graph-identifier $NEPTUNE_GRAPH_ID`

**Weather always returns error**
- Set `WEATHER_MOCK=true` in `.env` for demos (returns rain Wed, clear Thu)
- Or verify `OPENWEATHERMAP_API_KEY` is active (new keys take ~2 hours to activate)

**Amazon shopping fails**
- Re-run Playwright login: `playwright-cli -s=amazon open https://www.amazon.com --headed`

---

**Built with:** Amazon Nova Sonic 2 · Strands Agents SDK · Amazon Bedrock GraphRAG · Neptune Analytics · React · FastAPI · Bee Pioneer
