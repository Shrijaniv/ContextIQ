#!/bin/bash
# Prefill: bee sync → S3 → GraphRAG KB + Neptune KG
set -e

# Config comes from the environment — see .env.example at the repo root.
ENV_FILE="$(cd "$(dirname "$0")/../.." && pwd)/.env"
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a

REGION="${AWS_REGION:-us-west-2}"
export AWS_DEFAULT_REGION="$REGION"

SYNC_DIR="${1:-$HOME/bee-data}"
ACCOUNT_ID="${2:-${BEE_ACCOUNT_ID:?Set BEE_ACCOUNT_ID in .env or pass it as arg 2}}"
GRAPHRAG_KB_ID="${GRAPHRAG_KB_ID:?Set GRAPHRAG_KB_ID in .env}"
GRAPHRAG_DS_ID="${GRAPHRAG_DS_ID:?Set GRAPHRAG_DS_ID in .env}"

echo "=== Step 1: Exporting Bee data ==="
bee sync --output "$SYNC_DIR"

echo ""
echo "=== Step 2: Ingesting into S3 + Neptune KG ==="
python3 "$(dirname "$0")/../tools/ingest_bee_sync.py" "$SYNC_DIR" --account-id "$ACCOUNT_ID"

echo ""
echo "=== Step 3: Syncing GraphRAG KB ==="
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "$GRAPHRAG_KB_ID" \
  --data-source-id "$GRAPHRAG_DS_ID" \
  --query 'ingestionJob.{id:ingestionJobId,status:status}' --output table

echo ""
echo "Waiting 60s for KB sync..."
sleep 60

aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id "$GRAPHRAG_KB_ID" \
  --data-source-id "$GRAPHRAG_DS_ID" \
  --query 'ingestionJobSummaries[0].{status:status,scanned:statistics.numberOfDocumentsScanned,indexed:statistics.numberOfNewDocumentsIndexed,failed:statistics.numberOfDocumentsFailed}' --output table

echo ""
echo "=== Done. Test with: ==="
echo "python3 tools/query_kb.py \"What activities did I plan this weekend?\""
