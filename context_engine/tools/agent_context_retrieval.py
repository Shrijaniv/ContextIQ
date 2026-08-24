"""Memory tool — retrieves user context from the Bedrock GraphRAG knowledge base.

Context retrieval happens exclusively through the Bedrock GraphRAG KB (Neptune
Analytics-backed). The KB's Retrieve API performs semantic vector search AND
automatic graph expansion over the same physical graph, so there is no separate
lexical/openCypher query against Neptune here. We over-retrieve (SEMANTIC) and
then rerank with Cohere Rerank 3.5 to surface the most relevant chunks.

See docs/agent-context.md for the full strategy.
"""

import os

import boto3
from strands import tool

GRAPHRAG_KB = os.environ.get("GRAPHRAG_KB_ID")
REGION = os.environ.get("AWS_REGION", "us-west-2")

# Over-retrieve this many chunks semantically, then rerank down to the top N.
RETRIEVE_N = 15
RERANK_N = 5
RERANK_MODEL_ARN = f"arn:aws:bedrock:{REGION}::foundation-model/cohere.rerank-v3-5:0"


def _retrieve_kb(client, kb_id, query, n=RETRIEVE_N, rerank_n=RERANK_N):
    """Retrieve from the GraphRAG KB with Cohere reranking.

    Falls back to a plain semantic retrieve if reranking is unavailable
    (e.g. missing bedrock:Rerank permission).
    """
    base_config = {
        "vectorSearchConfiguration": {
            "numberOfResults": n,
            "overrideSearchType": "SEMANTIC",
        }
    }
    rerank_config = {
        "vectorSearchConfiguration": {
            "numberOfResults": n,
            "overrideSearchType": "SEMANTIC",
            "rerankingConfiguration": {
                "type": "BEDROCK_RERANKING_MODEL",
                "bedrockRerankingConfiguration": {
                    "numberOfRerankedResults": rerank_n,
                    "modelConfiguration": {"modelArn": RERANK_MODEL_ARN},
                },
            },
        }
    }

    for config in (rerank_config, base_config):
        try:
            resp = client.retrieve(
                knowledgeBaseId=kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration=config,
            )
            return [{"text": r["content"]["text"], "score": r.get("score", 0)}
                    for r in resp["retrievalResults"]]
        except Exception as e:
            last_error = str(e)
            continue

    return [{"error": last_error}]


@tool
def retrieve_context(query: str) -> str:
    """Search the user's Bee conversation history for context.

    Returns the most relevant conversation excerpts and graph-enriched context
    from the GraphRAG knowledge base. Use this FIRST whenever the user references
    past info.

    Args:
        query: 2-4 keywords from the user's request.

    Returns:
        Ranked conversation and knowledge-graph context.
    """
    client = boto3.client("bedrock-agent-runtime", region_name=REGION)

    results = _retrieve_kb(client, GRAPHRAG_KB, query)

    if not results or "error" in results[0]:
        return "No relevant context found in conversation history or knowledge graph."

    parts = ["## Conversation Context"]
    for r in results:
        parts.append(r["text"][:600])

    return "\n\n".join(parts)
