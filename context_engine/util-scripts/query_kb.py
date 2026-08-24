#!/usr/bin/env python3
"""Query GraphRAG KB and Neptune knowledge graph and show results side by side.

Usage:
    AWS_DEFAULT_REGION=us-west-2 python3 tools/query_kb.py "what groceries did I mention?"
    AWS_DEFAULT_REGION=us-west-2 python3 tools/query_kb.py "volleyball game time" --results 5
    AWS_DEFAULT_REGION=us-west-2 python3 tools/query_kb.py "picnic plans" --user $BEE_ACCOUNT_ID
    AWS_DEFAULT_REGION=us-west-2 python3 tools/query_kb.py "Bobby commitments" --json
"""
import sys
import os
import argparse
import json
import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from context_engine.env_config import region, require  # noqa: E402

GRAPHRAG_KB = require("GRAPHRAG_KB_ID")
NEPTUNE_GRAPH = require("NEPTUNE_GRAPH_ID")
REGION = region()


def retrieve_kb(client, kb_id, query, n, user=None):
    config = {"vectorSearchConfiguration": {"numberOfResults": n}}
    if user:
        config["vectorSearchConfiguration"]["filter"] = {
            "equals": {"key": "beeAccountId", "value": user}
        }
    return client.retrieve(
        knowledgeBaseId=kb_id,
        retrievalQuery={"text": query},
        retrievalConfiguration=config,
    )["retrievalResults"]


def query_graph(query):
    try:
        from knowledge_graph import execute_query
        words = [w for w in query.split() if len(w) > 2]
        if not words:
            return []
        conditions = " OR ".join(
            f"toLower(e.name) CONTAINS toLower('{w}')" for w in words[:5]
        )
        r = execute_query(
            f"MATCH (e:KGEntity)-[r]-(other:KGEntity) WHERE {conditions} "
            "RETURN e.name AS entity, e.type AS type, type(r) AS rel, "
            "other.name AS connected LIMIT 20"
        )
        return r.get("results", [])
    except Exception as e:
        return [{"error": str(e)}]


def show_kb_results(label, chunks, max_show=3):
    print(f"\n  {label} ({len(chunks)} results):")
    for i, c in enumerate(chunks[:max_show]):
        score = c.get("score", 0)
        text = c["content"]["text"][:150].replace("\n", " ")
        src = c.get("location", {}).get("s3Location", {}).get("uri", "?")
        src = src.split("/clean/")[-1] if "/clean/" in src else src.split("/")[-1]
        print(f"    [{i+1}] score={score:.3f} | {src}")
        print(f"        {text}...")


def show_graph_results(results):
    print(f"\n  KNOWLEDGE GRAPH ({len(results)} connections):")
    if not results:
        print("    (no matching entities found)")
        return
    if "error" in results[0]:
        print(f"    Error: {results[0]['error']}")
        return
    seen = set()
    for r in results:
        key = f"{r.get('entity')}→{r.get('connected')}"
        if key in seen:
            continue
        seen.add(key)
        etype = r.get("type") or "?"
        print(f"    {r.get('entity','')} ({etype}) --[{r.get('rel','')}]--> {r.get('connected','')}")


def main():
    p = argparse.ArgumentParser(description="Query all retrieval systems")
    p.add_argument("query", help="Search query")
    p.add_argument("--results", type=int, default=5, help="Results per KB (default: 5)")
    p.add_argument("--user", help="Filter by beeAccountId")
    p.add_argument("--json", action="store_true", help="Raw JSON output")
    args = p.parse_args()

    client = boto3.client("bedrock-agent-runtime", region_name=REGION)

    print(f"\nQuery: {args.query}")
    print("=" * 70)

    # GraphRAG KB
    graphrag_results = retrieve_kb(client, GRAPHRAG_KB, args.query, args.results, args.user)
    show_kb_results("GRAPHRAG KB", graphrag_results)

    # Knowledge Graph
    graph_results = query_graph(args.query)
    show_graph_results(graph_results)

    if args.json:
        output = {"graphrag": graphrag_results, "knowledge_graph": graph_results}
        print("\n" + json.dumps(output, indent=2, default=str))

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
