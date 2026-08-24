#!/usr/bin/env python3
"""Ingest S3 conversation data into the Neptune knowledge graph.

Extracts entities and relationships from clean text files using Claude Haiku,
then stores them in Neptune Analytics.

Usage:
    AWS_DEFAULT_REGION=us-west-2 python3 ingest_knowledge_graph.py
    AWS_DEFAULT_REGION=us-west-2 python3 ingest_knowledge_graph.py --user-id $BEE_ACCOUNT_ID
"""
import argparse, os, sys, boto3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from knowledge_graph import extract_entities, store_entities

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from context_engine.env_config import bucket, region, require  # noqa: E402

BUCKET = bucket()
REGION = region()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--user-id", default=os.environ.get("BEE_ACCOUNT_ID"))
    p.add_argument("--prefix", default="clean/", help="S3 prefix to scan")
    args = p.parse_args()

    if not args.user_id:
        raise SystemExit("Set BEE_ACCOUNT_ID in .env or pass --user-id")

    s3 = boto3.client('s3', region_name=REGION)
    paginator = s3.get_paginator('list_objects_v2')

    files = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=args.prefix):
        for obj in page.get('Contents', []):
            if obj['Key'].endswith('.txt'):
                files.append(obj['Key'])

    print(f"Found {len(files)} text files to process\n")
    total_e, total_r = 0, 0

    for f in files:
        doc_id = f.split('/')[-1].replace('.txt', '')
        obj = s3.get_object(Bucket=BUCKET, Key=f)
        text = obj['Body'].read().decode('utf-8')
        print(f"  {doc_id} ({len(text):,} chars)...", end=" ", flush=True)
        try:
            extracted = extract_entities(text)
            result = store_entities(extracted, source_id=doc_id, user_id=args.user_id)
            print(f"entities:{result['entities_stored']} rels:{result['relationships_stored']}")
            total_e += result['entities_stored']
            total_r += result['relationships_stored']
        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\nDone. Total: {total_e} entities, {total_r} relationships stored.")


if __name__ == "__main__":
    main()
