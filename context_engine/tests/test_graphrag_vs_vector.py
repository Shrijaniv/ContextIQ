#!/usr/bin/env python3
"""Test GraphRAG KB retrieval quality with sample queries.

Usage:
    AWS_DEFAULT_REGION=us-west-2 python3 test_graphrag_vs_vector.py
    AWS_DEFAULT_REGION=us-west-2 python3 test_graphrag_vs_vector.py "your custom query"
"""
import os
import sys
import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from context_engine.env_config import region, require  # noqa: E402

GRAPHRAG_KB = require("GRAPHRAG_KB_ID")
REGION = region()

client = boto3.client('bedrock-agent-runtime', region_name=REGION)

queries = sys.argv[1:] or [
    "what activities did my friends plan for the weekend?",
    "what food preferences do people have?",
    "what commitments were made?",
    "birthday dinner plans",
]

for q in queries:
    print(f"\n{'='*70}")
    print(f"QUERY: {q}")
    print('='*70)

    resp = client.retrieve(
        knowledgeBaseId=GRAPHRAG_KB,
        retrievalQuery={'text': q},
        retrievalConfiguration={'vectorSearchConfiguration': {'numberOfResults': 5}},
    )
    chunks = resp['retrievalResults']
    print(f"\n  GRAPHRAG ({len(chunks)} results):")
    for i, c in enumerate(chunks[:3]):
        score = c.get('score', 0)
        text = c['content']['text'][:120].replace('\n', ' ')
        src = c.get('location', {}).get('s3Location', {}).get('uri', '?').split('/')[-1]
        print(f"    [{i+1}] score={score:.3f} | {src} | {text}...")
