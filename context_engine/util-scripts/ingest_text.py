#!/usr/bin/env python3
"""Ingest raw text (e.g. a Bee conversation transcript) into the KB and knowledge graph.

Writes the text to S3 as a clean document, triggers KB re-index, and extracts
entities/relationships into the Neptune knowledge graph.

Usage:
    # From a file
    AWS_DEFAULT_REGION=us-west-2 python3 tools/ingest_text.py --file transcript.txt

    # From stdin
    echo "Bobby and Kim planned a picnic at Green Lake" | AWS_DEFAULT_REGION=us-west-2 python3 tools/ingest_text.py

    # Inline
    AWS_DEFAULT_REGION=us-west-2 python3 tools/ingest_text.py --text "Bobby discussed dinner plans with Mitra"

    # With metadata
    AWS_DEFAULT_REGION=us-west-2 python3 tools/ingest_text.py \
        --file transcript.txt --title "Grocery planning call" --date 2026-04-19 --user-id $BEE_ACCOUNT_ID
"""
import argparse
import hashlib
import json
import os
import sys
import boto3
from datetime import datetime, timezone
from pathlib import Path

# Load .env from project root
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from knowledge_graph import extract_entities, store_entities  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-west-2")
ACCOUNT_ID = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
BUCKET = os.environ.get(
    "BEE_CONTEXT_BUCKET", f"bee-context-store-{ACCOUNT_ID}-{REGION}"
)
KB_ID = os.environ.get("GRAPHRAG_KB_ID")
DS_ID = os.environ.get("GRAPHRAG_DS_ID")


def ingest(text: str, title: str = None, date: str = None, user_id: str = None, doc_id: str = None):
    user_id = user_id or os.environ.get("BEE_ACCOUNT_ID")
    if not user_id:
        raise RuntimeError("Set BEE_ACCOUNT_ID in .env or pass user_id")
    s3 = boto3.client("s3", region_name=REGION)

    doc_id = doc_id or hashlib.md5(text.encode()).hexdigest()[:10]
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = title or f"Document {doc_id}"

    # Only add header if text doesn't already start with one (Bee-format docs have it)
    if text.lstrip().startswith("# "):
        clean = text
    else:
        clean = f"# {title}\nDate: {date}\n\n{text}"

    # Upload to S3
    key = f"clean/conversations/{doc_id}.txt"
    s3.put_object(Bucket=BUCKET, Key=key, Body=clean, ContentType="text/plain")
    s3.put_object(
        Bucket=BUCKET, Key=f"{key}.metadata.json",
        Body=json.dumps({"metadataAttributes": {"beeAccountId": user_id, "date": date}}),
        ContentType="application/json",
    )
    print(f"✓ Uploaded to s3://{BUCKET}/{key} ({len(clean)} bytes)")

    # Trigger GraphRAG KB re-index
    bedrock = boto3.client("bedrock-agent", region_name=REGION)
    try:
        bedrock.start_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=DS_ID)
        print("✓ GraphRAG KB re-index triggered")
    except Exception as e:
        print(f"⚠ GraphRAG KB re-index failed: {e}")

    # Extract entities into knowledge graph
    print("Extracting entities...")
    try:
        extracted = extract_entities(text)
        result = store_entities(extracted, source_id=doc_id, user_id=user_id)
        n_e, n_r = result['entities_stored'], result['relationships_stored']
        print(f"✓ Knowledge graph: {n_e} entities, {n_r} relationships")
        if extracted.get("entities"):
            for e in extracted["entities"][:8]:
                print(f"    {e.get('type', '?'):12s} | {e['name']}")
            if len(extracted["entities"]) > 8:
                print(f"    ... and {len(extracted['entities']) - 8} more")
    except Exception as e:
        print(f"⚠ Entity extraction failed: {e}")

    print(f"\nDone. Doc ID: {doc_id}")
    return doc_id


def main():
    p = argparse.ArgumentParser(description="Ingest raw text into KB + knowledge graph")
    p.add_argument("--file", help="Path to text file")
    p.add_argument("--text", help="Inline text")
    p.add_argument("--title", help="Document title")
    p.add_argument("--date", help="Date (YYYY-MM-DD)")
    p.add_argument("--user-id", default=os.environ.get("BEE_ACCOUNT_ID"))
    p.add_argument("--doc-id", help="Custom document ID")
    args = p.parse_args()

    if args.file:
        with open(args.file) as f:
            text = f.read()
    elif args.text:
        text = args.text
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        print("Enter text (Ctrl+D when done):")
        text = sys.stdin.read()

    if not text.strip():
        print("Error: no text provided")
        sys.exit(1)

    ingest(text.strip(), title=args.title, date=args.date, user_id=args.user_id, doc_id=args.doc_id)


if __name__ == "__main__":
    main()
