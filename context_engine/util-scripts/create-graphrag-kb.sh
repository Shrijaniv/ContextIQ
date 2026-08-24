#!/bin/bash
# Creates GraphRAG KB + data source backed by Neptune Analytics
set -e

# Config comes from the environment — see .env.example at the repo root.
# Load .env if present so the script works after `cp .env.example .env`.
ENV_FILE="$(cd "$(dirname "$0")/../.." && pwd)/.env"
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a

REGION="${AWS_REGION:-us-west-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
NEPTUNE_ID="${NEPTUNE_GRAPH_ID:?Set NEPTUNE_GRAPH_ID in .env}"
BUCKET="${BEE_CONTEXT_BUCKET:-bee-context-store-${ACCOUNT_ID}-${REGION}}"
NEPTUNE_ARN="arn:aws:neptune-graph:${REGION}:${ACCOUNT_ID}:graph/${NEPTUNE_ID}"
KB_ROLE="arn:aws:iam::${ACCOUNT_ID}:role/BedrockKBRole"

echo "=== Creating GraphRAG Knowledge Base ==="
# Check if KB already exists
EXISTING_KB=$(aws bedrock-agent list-knowledge-bases --region "$REGION" \
  --query "knowledgeBaseSummaries[?name=='bee-graphrag-kb'].knowledgeBaseId" \
  --output text 2>/dev/null)
if [ -n "$EXISTING_KB" ] && [ "$EXISTING_KB" != "None" ]; then
  echo "KB already exists: $EXISTING_KB"
  GRAPHRAG_KB_ID="$EXISTING_KB"
else
GRAPHRAG_KB_ID=$(aws bedrock-agent create-knowledge-base \
  --region "$REGION" \
  --name "bee-graphrag-kb" \
  --role-arn "$KB_ROLE" \
  --knowledge-base-configuration '{"type":"VECTOR","vectorKnowledgeBaseConfiguration":{"embeddingModelArn":"arn:aws:bedrock:'"${REGION}"'::foundation-model/amazon.titan-embed-text-v2:0"}}' \
  --storage-configuration "{\"type\":\"NEPTUNE_ANALYTICS\",\"neptuneAnalyticsConfiguration\":{\"graphArn\":\"${NEPTUNE_ARN}\",\"fieldMapping\":{\"metadataField\":\"AMAZON_BEDROCK_METADATA\",\"textField\":\"AMAZON_BEDROCK_TEXT_CHUNK\"}}}" \
  --query 'knowledgeBase.knowledgeBaseId' --output text)
fi
echo "GraphRAG KB: $GRAPHRAG_KB_ID"
sleep 5

echo "=== Creating data source ==="
cat > /tmp/graphrag-ds.json << ENDJSON
{
  "knowledgeBaseId": "${GRAPHRAG_KB_ID}",
  "name": "bee-s3-clean-graphrag",
  "dataDeletionPolicy": "DELETE",
  "dataSourceConfiguration": {
    "type": "S3",
    "s3Configuration": {
      "bucketArn": "arn:aws:s3:::${BUCKET}",
      "inclusionPrefixes": ["clean/"]
    }
  },
  "vectorIngestionConfiguration": {
    "contextEnrichmentConfiguration": {
      "type": "BEDROCK_FOUNDATION_MODEL",
      "bedrockFoundationModelConfiguration": {
        "modelArn": "arn:aws:bedrock:${REGION}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
        "enrichmentStrategyConfiguration": {
          "method": "CHUNK_ENTITY_EXTRACTION"
        }
      }
    }
  }
}
ENDJSON

GRAPHRAG_DS_ID=$(aws bedrock-agent create-data-source \
  --region "$REGION" \
  --cli-input-json file:///tmp/graphrag-ds.json \
  --query 'dataSource.dataSourceId' --output text)
echo "GraphRAG DS: $GRAPHRAG_DS_ID"

echo "=== Triggering initial ingestion ==="
aws bedrock-agent start-ingestion-job \
  --region "$REGION" \
  --knowledge-base-id "$GRAPHRAG_KB_ID" \
  --data-source-id "$GRAPHRAG_DS_ID"

echo ""
echo "=========================================="
echo "Done! Add these to your .env:"
echo "  GRAPHRAG_KB_ID=$GRAPHRAG_KB_ID"
echo "  GRAPHRAG_DS_ID=$GRAPHRAG_DS_ID"
echo "  NEPTUNE_GRAPH_ID=$NEPTUNE_ID"
echo "=========================================="
