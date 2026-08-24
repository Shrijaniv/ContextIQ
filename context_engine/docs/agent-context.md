# Agent Context Retrieval Strategy

How the ContextIQ/Alexa+ agent turns a user utterance into relevant context from
the user's Bee ambient-conversation history.

## Principle

The agent retrieves context through **exactly one path**: the Bedrock
**GraphRAG knowledge base** (`bee-graphrag-kb`, id in `GRAPHRAG_KB_ID`). There is no
separate lexical or openCypher query issued against Neptune at request time.

This matters because the GraphRAG KB and the Neptune Analytics graph
(`bee-knowledge-graph`, id in `NEPTUNE_GRAPH_ID`) are **one physical graph**, not two
stores. Neptune Analytics is the KB's vector store. A single `Retrieve` call
does both:

1. **Semantic vector search** — embeds the query with Titan Embed Text v2
   (1024-dim) and finds the nearest chunk nodes.
2. **Graph expansion** — automatically traverses the entity relationships
   Bedrock extracted at ingestion (`CHUNK_ENTITY_EXTRACTION` via Claude 3.5
   Haiku) to pull in connected chunks a pure vector match would miss.

Querying Neptune directly with openCypher (the old `_query_graph` path) is
redundant: it re-implements, less well, the traversal the KB already performs,
and it splits the ranking across two systems the agent then has to merge by
hand. So context retrieval is GraphRAG-KB-only.

## Retrieval Procedure

The agent's single memory tool, `retrieve_context(query)`, does:

1. **Over-retrieve.** Call `bedrock-agent-runtime.retrieve` with
   `numberOfResults = 15` and `overrideSearchType = "SEMANTIC"`.
   - GraphRAG requires `SEMANTIC` (`HYBRID` is rejected for this index).
   - Graph expansion scales with the result count: at `n = 5` no expanded
     chunks are returned; at `n = 15` several graph-connected chunks appear.
     A wide initial net is what makes it GraphRAG rather than plain RAG.

2. **Rerank.** Attach a `rerankingConfiguration` of type
   `BEDROCK_RERANKING_MODEL` using **Cohere Rerank 3.5**
   (`cohere.rerank-v3-5:0`) with `numberOfRerankedResults = 5`.
   - Raw vector scores at `n = 15` are nearly flat and often bury the most
     relevant chunk near the bottom, so reranking is required, not optional.
   - After reranking, scores spread cleanly and the on-topic chunk rises to the
     top.

3. **Fall back gracefully.** If the rerank call fails (e.g. missing
   `bedrock:Rerank` permission), retry once with the same query minus the
   reranking config and return the plain semantic results. The agent never
   errors out over reranking alone.

4. **Return** the reranked chunk texts (truncated) under a single
   `## Conversation Context` heading. No client-side merging of multiple
   sources.

## Configuration

| Setting | Value |
|---|---|
| KB id | `GRAPHRAG_KB_ID` (`bee-graphrag-kb`) |
| Vector store | Neptune Analytics `NEPTUNE_GRAPH_ID` (`bee-knowledge-graph`) |
| Embedding model | `amazon.titan-embed-text-v2:0` (1024-dim) |
| Entity enrichment | `anthropic.claude-3-haiku-20240307-v1:0`, `CHUNK_ENTITY_EXTRACTION` |
| Initial results | 15 |
| Search type | `SEMANTIC` |
| Reranker | `cohere.rerank-v3-5:0` → top 5 |
| Region | `us-west-2` |

## IAM

The KB assumes `BedrockKBRole`. Reranking requires an inline policy allowing
`bedrock:Rerank` (resource `*` — the rerank endpoint is not the model ARN) and
`bedrock:InvokeModel` on `cohere.rerank-v3-5:0`.

## Adopting the existing resources

The knowledge base, Neptune graph, and data source (ids in `.env` as
`GRAPHRAG_KB_ID`, `NEPTUNE_GRAPH_ID`, `GRAPHRAG_DS_ID`) already exist and hold live, ingested data. The CDK stack
does **not** recreate them — it adopts them via `cdk import`:

```bash
cd context_engine/cdk
cdk import BeeContextQueryStack
```

`cdk import` prompts for the physical id of each new resource in the stack; supply:

| Logical id | Physical id |
|---|---|
| `BeeKnowledgeGraph` | `NEPTUNE_GRAPH_ID` |
| `BeeGraphRagKb` | `GRAPHRAG_KB_ID` |
| `BeeS3DataSource` | `GRAPHRAG_KB_ID|GRAPHRAG_DS_ID` |
| `BedrockKBRole` | `BedrockKBRole` |

The three stateful resources carry `RemovalPolicy.RETAIN`, so import (or any
later rollback/stack delete) never destroys the live graph or its ingested
data. After import, `cdk diff` should be clean; if it isn't, reconcile the CDK
properties to the live config rather than letting a deploy mutate the resource.

## Non-goals

- No direct Neptune openCypher queries at request time.
- No hybrid (semantic + keyword) search — unsupported for this index.
- No preference/event lookups outside the KB retrieve path.
