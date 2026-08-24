#!/bin/bash
# Invoke the Lambda that calls bee changed (incremental update)
set -e

# Config comes from the environment — see .env.example at the repo root.
ENV_FILE="$(cd "$(dirname "$0")/../.." && pwd)/.env"
[ -f "$ENV_FILE" ] && set -a && . "$ENV_FILE" && set +a

REGION="${AWS_REGION:-us-west-2}"
export AWS_DEFAULT_REGION="$REGION"
GRAPHRAG_KB_ID="${GRAPHRAG_KB_ID:?Set GRAPHRAG_KB_ID in .env}"
GRAPHRAG_DS_ID="${GRAPHRAG_DS_ID:?Set GRAPHRAG_DS_ID in .env}"

FUNC_NAME=$(aws lambda list-functions \
  --query "Functions[?contains(FunctionName,'BeeIngest')].FunctionName" --output text)

if [ -z "$FUNC_NAME" ]; then
  echo "ERROR: Lambda function not found. Is the CDK stack deployed?"
  exit 1
fi

echo "Invoking $FUNC_NAME..."
aws lambda invoke \
  --function-name "$FUNC_NAME" \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  /dev/stdout

echo ""
echo "Triggering GraphRAG KB re-sync..."
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "$GRAPHRAG_KB_ID" \
  --data-source-id "$GRAPHRAG_DS_ID" \
  --query 'ingestionJob.{id:ingestionJobId,status:status}' --output table
