#!/usr/bin/env python3
"""
Test Bee KB retrieval — shows exactly what the agent sees when it calls memory().

Usage:
    python contextiq_agent/test/test_kb_retrieval.py
    python contextiq_agent/test/test_kb_retrieval.py --query "what did I do yesterday"
    python contextiq_agent/test/test_kb_retrieval.py --sync   # trigger ingestion first, then test
"""
import argparse
import os
import sys
import time

import boto3
from dotenv import load_dotenv

load_dotenv()

KB_ID = os.environ.get("STRANDS_KNOWLEDGE_BASE_ID") or os.environ.get("GRAPHRAG_KB_ID")
DS_ID = os.environ.get("GRAPHRAG_DS_ID")
REGION = os.environ.get("AWS_REGION", "us-west-2")
AWS_PROFILE = os.environ.get("AWS_PROFILE")

DEFAULT_QUERIES = [
    "what did I do yesterday",
    "what are my plans or meetings",
    "what did I learn recently",
    "grocery or shopping list",
]


def get_boto_session():
    if AWS_PROFILE:
        return boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
    return boto3.Session(region_name=REGION)


def trigger_and_wait_ingestion(session):
    """Start ingestion job and poll until complete."""
    agent_client = session.client("bedrock-agent", region_name=REGION)

    print(f"Starting ingestion job for KB={KB_ID} DS={DS_ID}...")
    resp = agent_client.start_ingestion_job(
        knowledgeBaseId=KB_ID,
        dataSourceId=DS_ID,
    )
    job_id = resp["ingestionJob"]["ingestionJobId"]
    print(f"Job started: {job_id}")

    while True:
        status_resp = agent_client.get_ingestion_job(
            knowledgeBaseId=KB_ID,
            dataSourceId=DS_ID,
            ingestionJobId=job_id,
        )
        job = status_resp["ingestionJob"]
        status = job["status"]
        stats = job.get("statistics", {})
        print(
            f"  status={status}"
            f" | scanned={stats.get('numberOfDocumentsScanned', 0)}"
            f" | indexed={stats.get('numberOfNewDocumentsIndexed', 0)}"
            f" | modified={stats.get('numberOfModifiedDocumentsIndexed', 0)}"
        )
        if status in ("COMPLETE", "FAILED", "STOPPED"):
            break
        time.sleep(5)

    if status != "COMPLETE":
        print(f"Ingestion ended with status: {status}", file=sys.stderr)
        sys.exit(1)
    print("Ingestion complete.\n")


def retrieve(session, query, max_results=5):
    """Call Bedrock KB retrieve — same as strands memory tool does internally."""
    runtime = session.client("bedrock-agent-runtime", region_name=REGION)
    resp = runtime.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": max_results}
        },
    )
    return resp["retrievalResults"]


def print_results(query, chunks):
    print(f'\nQuery: "{query}"')
    print(f"Results: {len(chunks)}")
    print("=" * 60)
    if not chunks:
        print("  (no results)")
        return
    for i, chunk in enumerate(chunks):
        score = chunk.get("score", 0)
        text = chunk["content"]["text"]
        source = chunk.get("location", {}).get("s3Location", {}).get("uri", "")
        if "/clean/" in source:
            source_short = source.split("/clean/")[-1]
        else:
            source_short = source.split("/")[-1]
        print(f"\n  [{i+1}] score={score:.3f}  source={source_short}")
        preview = text[:300].strip()
        for line in preview.splitlines():
            print(f"       {line}")
        if len(text) > 300:
            print(f"       ... ({len(text)} chars total)")
    print()


def main():
    parser = argparse.ArgumentParser(description="Test Bee KB retrieval")
    parser.add_argument("--query", help="Single query to test (default: runs all)")
    parser.add_argument(
        "--sync", action="store_true",
        help="Trigger KB ingestion and wait for completion before testing"
    )
    parser.add_argument("--results", type=int, default=5, help="Max results per query")
    args = parser.parse_args()

    session = get_boto_session()

    if args.sync:
        trigger_and_wait_ingestion(session)

    queries = [args.query] if args.query else DEFAULT_QUERIES

    print(f"KB: {KB_ID}  |  Region: {REGION}  |  Profile: {AWS_PROFILE or 'default'}\n")

    for q in queries:
        chunks = retrieve(session, q, max_results=args.results)
        print_results(q, chunks)


if __name__ == "__main__":
    main()
