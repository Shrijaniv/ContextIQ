#!/bin/bash
# Full setup: creates all AWS resources needed for ContextIQ in a new account.
# Prerequisites: AWS credentials active, Node.js, Python 3.12, bee CLI installed + logged in
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
export AWS_DEFAULT_REGION=us-west-2
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "=== ContextIQ Setup ==="
echo "Account: $ACCOUNT_ID"
echo "Region:  $AWS_DEFAULT_REGION"
echo ""

# --- 1. Get Bee token ---
# Source order: BEE_TOKEN env var (config) → macOS keychain (bee login) → prompt.
echo "=== Step 1: Bee token ==="
if [ -z "$BEE_TOKEN" ]; then
  BEE_TOKEN=$(security find-generic-password -s "bee-cli" -w 2>/dev/null || echo "")
fi
if [ -z "$BEE_TOKEN" ]; then
  echo "No BEE_TOKEN env var and none in keychain. Make sure you've run: bee login"
  read -p "Paste your Bee token manually: " BEE_TOKEN
fi

if aws secretsmanager describe-secret --secret-id bee-api-token >/dev/null 2>&1; then
  echo "Secret bee-api-token already exists, updating..."
  aws secretsmanager put-secret-value \
    --secret-id bee-api-token \
    --secret-string "{\"bee_token\":\"$BEE_TOKEN\"}"
else
  echo "Creating secret bee-api-token..."
  aws secretsmanager create-secret \
    --name bee-api-token \
    --secret-string "{\"bee_token\":\"$BEE_TOKEN\"}"
fi
echo "OK"
echo ""

# --- 2. Install CDK CLI ---
echo "=== Step 2: CDK CLI ==="
if ! command -v cdk &>/dev/null; then
  echo "Installing CDK CLI..."
  npm install -g aws-cdk --registry https://registry.npmjs.org
else
  echo "CDK CLI already installed: $(cdk --version)"
fi
echo ""

# --- 3. Package Lambda ---
echo "=== Step 3: Package Lambda ==="
cd "$SCRIPT_DIR/../lambda"
rm -rf package && mkdir package
pip install -r requirements.txt -t package
cp handler.py bee_ca.pem package/
echo "OK"
echo ""

# --- 4. Deploy CDK stack ---
echo "=== Step 4: Deploy CDK stack ==="
cd "$SCRIPT_DIR/../cdk"
pip install -r requirements.txt
cdk bootstrap "aws://$ACCOUNT_ID/$AWS_DEFAULT_REGION"
cdk deploy --require-approval never
echo ""

# --- 5. Create Bedrock KB ---
echo "=== Step 5: Bedrock Knowledge Base ==="
BUCKET="bee-context-store-$ACCOUNT_ID-$AWS_DEFAULT_REGION"

# IAM role for KB
if aws iam get-role --role-name BedrockKBRole >/dev/null 2>&1; then
  echo "BedrockKBRole already exists"
else
  echo "Creating BedrockKBRole..."
  aws iam create-role --role-name BedrockKBRole \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"bedrock.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
  aws iam put-role-policy --role-name BedrockKBRole --policy-name BedrockKBPolicy \
    --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::$BUCKET\",\"arn:aws:s3:::$BUCKET/*\"]},{\"Effect\":\"Allow\",\"Action\":[\"bedrock:InvokeModel\"],\"Resource\":\"arn:aws:bedrock:$AWS_DEFAULT_REGION::foundation-model/amazon.titan-embed-text-v2:0\"}]}"
fi

# OpenSearch Serverless collection
COLLECTION_NAME="bee-context"
EXISTING=$(aws opensearchserverless batch-get-collection --names "$COLLECTION_NAME" --query 'collectionDetails[0].id' --output text 2>/dev/null || echo "None")

if [ "$EXISTING" != "None" ] && [ -n "$EXISTING" ]; then
  echo "AOSS collection already exists: $EXISTING"
  COLLECTION_ARN="arn:aws:aoss:$AWS_DEFAULT_REGION:$ACCOUNT_ID:collection/$EXISTING"
  COLLECTION_ENDPOINT=$(aws opensearchserverless batch-get-collection --ids "$EXISTING" --query 'collectionDetails[0].collectionEndpoint' --output text)
else
  echo "Creating AOSS security policies..."
  aws opensearchserverless create-security-policy --name bee-kb-encryption --type encryption \
    --policy '{"Rules":[{"ResourceType":"collection","Resource":["collection/bee-context"]}],"AWSOwnedKey":true}' 2>/dev/null || true
  aws opensearchserverless create-security-policy --name bee-kb-network --type network \
    --policy '[{"Rules":[{"ResourceType":"collection","Resource":["collection/bee-context"]},{"ResourceType":"dashboard","Resource":["collection/bee-context"]}],"AllowFromPublic":true}]' 2>/dev/null || true

  CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)
  aws opensearchserverless create-access-policy --name bee-kb-access --type data \
    --policy "[{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/bee-context\"],\"Permission\":[\"aoss:*\"]},{\"ResourceType\":\"index\",\"Resource\":[\"index/bee-context/*\"],\"Permission\":[\"aoss:*\"]}],\"Principal\":[\"arn:aws:iam::$ACCOUNT_ID:role/BedrockKBRole\",\"$CALLER_ARN\"]}]" 2>/dev/null || true

  echo "Creating AOSS collection (this takes ~4 minutes)..."
  aws opensearchserverless create-collection --name "$COLLECTION_NAME" --type VECTORSEARCH
  echo "Waiting for collection to be ACTIVE..."
  for i in $(seq 1 30); do
    STATUS=$(aws opensearchserverless batch-get-collection --names "$COLLECTION_NAME" --query 'collectionDetails[0].status' --output text 2>/dev/null)
    if [ "$STATUS" = "ACTIVE" ]; then break; fi
    sleep 10
  done
  EXISTING=$(aws opensearchserverless batch-get-collection --names "$COLLECTION_NAME" --query 'collectionDetails[0].id' --output text)
  COLLECTION_ARN="arn:aws:aoss:$AWS_DEFAULT_REGION:$ACCOUNT_ID:collection/$EXISTING"
  COLLECTION_ENDPOINT=$(aws opensearchserverless batch-get-collection --ids "$EXISTING" --query 'collectionDetails[0].collectionEndpoint' --output text)

  # Add AOSS permissions to KB role
  aws iam put-role-policy --role-name BedrockKBRole --policy-name BedrockKBAOSSPolicy \
    --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"aoss:APIAccessAll\",\"Resource\":\"$COLLECTION_ARN\"}]}"

  # Create vector index
  echo "Creating vector index..."
  sleep 10
  pip install opensearch-py requests-aws4auth 2>/dev/null
  AOSS_HOST=$(echo "$COLLECTION_ENDPOINT" | sed 's|https://||')
  python3 -c "
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth
import boto3
s=boto3.Session(region_name='$AWS_DEFAULT_REGION')
c=s.get_credentials().get_frozen_credentials()
auth=AWS4Auth(c.access_key,c.secret_key,'$AWS_DEFAULT_REGION','aoss',session_token=c.token)
client=OpenSearch(hosts=[{'host':'$AOSS_HOST','port':443}],http_auth=auth,use_ssl=True,verify_certs=True,connection_class=RequestsHttpConnection)
client.indices.create(index='bee-context-index',body={'settings':{'index':{'knn':True,'knn.algo_param.ef_search':512}},'mappings':{'properties':{'bedrock-knowledge-base-default-vector':{'type':'knn_vector','dimension':1024,'method':{'engine':'faiss','name':'hnsw'}},'AMAZON_BEDROCK_TEXT_CHUNK':{'type':'text'},'AMAZON_BEDROCK_METADATA':{'type':'text'}}}})
print('OK: Vector index created')
"
fi

echo "Collection: $COLLECTION_ARN"
echo "Endpoint: $COLLECTION_ENDPOINT"
echo ""

# Create Bedrock KB
EXISTING_KB=$(aws bedrock-agent list-knowledge-bases --query "knowledgeBaseSummaries[?name=='bee-context-kb'].knowledgeBaseId" --output text 2>/dev/null)
AOSS_HOST=$(echo "$COLLECTION_ENDPOINT" | sed 's|https://||')

if [ -n "$EXISTING_KB" ] && [ "$EXISTING_KB" != "None" ]; then
  echo "KB already exists: $EXISTING_KB"
  KB_ID="$EXISTING_KB"
else
  echo "Creating Bedrock Knowledge Base..."
  sleep 10
  KB_ID=$(aws bedrock-agent create-knowledge-base \
    --name "bee-context-kb" \
    --role-arn "arn:aws:iam::$ACCOUNT_ID:role/BedrockKBRole" \
    --knowledge-base-configuration '{"type":"VECTOR","vectorKnowledgeBaseConfiguration":{"embeddingModelArn":"arn:aws:bedrock:'$AWS_DEFAULT_REGION'::foundation-model/amazon.titan-embed-text-v2:0"}}' \
    --storage-configuration "{\"type\":\"OPENSEARCH_SERVERLESS\",\"opensearchServerlessConfiguration\":{\"collectionArn\":\"$COLLECTION_ARN\",\"fieldMapping\":{\"metadataField\":\"AMAZON_BEDROCK_METADATA\",\"textField\":\"AMAZON_BEDROCK_TEXT_CHUNK\",\"vectorField\":\"bedrock-knowledge-base-default-vector\"},\"vectorIndexName\":\"bee-context-index\"}}" \
    --query 'knowledgeBase.knowledgeBaseId' --output text)
  echo "KB created: $KB_ID"
  sleep 5
fi

# Create data source
EXISTING_DS=$(aws bedrock-agent list-data-sources --knowledge-base-id "$KB_ID" --query "dataSourceSummaries[0].dataSourceId" --output text 2>/dev/null)

if [ -n "$EXISTING_DS" ] && [ "$EXISTING_DS" != "None" ]; then
  echo "Data source already exists: $EXISTING_DS"
  DS_ID="$EXISTING_DS"
else
  echo "Creating data source..."
  DS_ID=$(aws bedrock-agent create-data-source \
    --knowledge-base-id "$KB_ID" \
    --name "bee-s3-clean" \
    --data-source-configuration "{\"type\":\"S3\",\"s3Configuration\":{\"bucketArn\":\"arn:aws:s3:::$BUCKET\",\"inclusionPrefixes\":[\"clean/\"]}}" \
    --query 'dataSource.dataSourceId' --output text)
  echo "Data source created: $DS_ID"
fi

echo ""
echo "=== Step 6: Neptune Analytics (knowledge graph) ==="
GRAPH_NAME="bee-knowledge-graph"
EXISTING_GRAPH=$(aws neptune-graph list-graphs \
  --query "graphs[?name=='$GRAPH_NAME'].id" --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_GRAPH" ] && [ "$EXISTING_GRAPH" != "None" ] && [ "$EXISTING_GRAPH" != "" ]; then
  echo "Neptune graph already exists: $EXISTING_GRAPH"
  NEPTUNE_GRAPH_ID="$EXISTING_GRAPH"
else
  echo "Creating Neptune Analytics graph (this takes 5-10 minutes)..."
  # dimension 1024 matches amazon.titan-embed-text-v2:0 used by Bedrock KB
  NEPTUNE_GRAPH_ID=$(aws neptune-graph create-graph \
    --graph-name "$GRAPH_NAME" \
    --provisioned-memory 128 \
    --public-connectivity \
    --replica-count 0 \
    --no-deletion-protection \
    --vector-search-configuration '{"dimension": 1024}' \
    --query 'id' --output text)
  echo "Graph created: $NEPTUNE_GRAPH_ID"
  echo "Waiting for Neptune graph to be AVAILABLE..."
  for i in $(seq 1 60); do
    STATUS=$(aws neptune-graph get-graph \
      --graph-identifier "$NEPTUNE_GRAPH_ID" \
      --query 'status' --output text 2>/dev/null)
    echo "  status=$STATUS ($i/60)..."
    if [ "$STATUS" = "AVAILABLE" ]; then break; fi
    sleep 10
  done
fi
NEPTUNE_ARN="arn:aws:neptune-graph:$AWS_DEFAULT_REGION:$ACCOUNT_ID:graph/$NEPTUNE_GRAPH_ID"
echo "Neptune ARN: $NEPTUNE_ARN"
echo ""

# --- 7. Create GraphRAG Knowledge Base (uses Neptune as vector + graph store) ---
echo "=== Step 7: GraphRAG Knowledge Base ==="

# Add Neptune permissions to KB role
aws iam put-role-policy --role-name BedrockKBRole --policy-name BedrockKBNeptunePolicy \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"neptune-graph:GetGraph\",\"neptune-graph:ReadDataViaQuery\",\"neptune-graph:WriteDataViaQuery\",\"neptune-graph:DeleteDataViaQuery\"],\"Resource\":\"$NEPTUNE_ARN\"}]}" 2>/dev/null || true

EXISTING_GRAPHRAG_KB=$(aws bedrock-agent list-knowledge-bases \
  --query "knowledgeBaseSummaries[?name=='bee-graphrag-kb'].knowledgeBaseId" \
  --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_GRAPHRAG_KB" ] && [ "$EXISTING_GRAPHRAG_KB" != "None" ] && [ "$EXISTING_GRAPHRAG_KB" != "" ]; then
  echo "GraphRAG KB already exists: $EXISTING_GRAPHRAG_KB"
  GRAPHRAG_KB_ID="$EXISTING_GRAPHRAG_KB"
else
  echo "Creating GraphRAG Knowledge Base (backed by Neptune Analytics)..."
  sleep 5
  GRAPHRAG_KB_ID=$(aws bedrock-agent create-knowledge-base \
    --name "bee-graphrag-kb" \
    --role-arn "arn:aws:iam::$ACCOUNT_ID:role/BedrockKBRole" \
    --knowledge-base-configuration "{\"type\":\"VECTOR\",\"vectorKnowledgeBaseConfiguration\":{\"embeddingModelArn\":\"arn:aws:bedrock:$AWS_DEFAULT_REGION::foundation-model/amazon.titan-embed-text-v2:0\"}}" \
    --storage-configuration "{\"type\":\"NEPTUNE_ANALYTICS\",\"neptuneAnalyticsConfiguration\":{\"graphArn\":\"$NEPTUNE_ARN\",\"fieldMapping\":{\"metadataField\":\"AMAZON_BEDROCK_METADATA\",\"textField\":\"AMAZON_BEDROCK_TEXT_CHUNK\"}}}" \
    --query 'knowledgeBase.knowledgeBaseId' --output text)
  echo "GraphRAG KB created: $GRAPHRAG_KB_ID"
  sleep 5
fi

EXISTING_GRAPHRAG_DS=$(aws bedrock-agent list-data-sources \
  --knowledge-base-id "$GRAPHRAG_KB_ID" \
  --query "dataSourceSummaries[0].dataSourceId" --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_GRAPHRAG_DS" ] && [ "$EXISTING_GRAPHRAG_DS" != "None" ] && [ "$EXISTING_GRAPHRAG_DS" != "" ]; then
  echo "GraphRAG data source already exists: $EXISTING_GRAPHRAG_DS"
  GRAPHRAG_DS_ID="$EXISTING_GRAPHRAG_DS"
else
  # Add Claude Haiku invocation permission to KB role (needed for entity extraction)
  aws iam put-role-policy --role-name BedrockKBRole --policy-name BedrockKBHaikuPolicy \
    --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"bedrock:InvokeModel\",\"Resource\":\"arn:aws:bedrock:$AWS_DEFAULT_REGION::foundation-model/us.anthropic.claude-sonnet-4-6\"}]}" 2>/dev/null || true

  echo "Creating GraphRAG data source..."
  GRAPHRAG_DS_ID=$(aws bedrock-agent create-data-source \
    --knowledge-base-id "$GRAPHRAG_KB_ID" \
    --name "bee-s3-clean-graphrag" \
    --data-deletion-policy DELETE \
    --data-source-configuration "{\"type\":\"S3\",\"s3Configuration\":{\"bucketArn\":\"arn:aws:s3:::$BUCKET\",\"inclusionPrefixes\":[\"clean/\"]}}" \
    --context-enrichment-configuration "{\"type\":\"BEDROCK_FOUNDATION_MODEL\",\"bedrockFoundationModelConfiguration\":{\"modelArn\":\"arn:aws:bedrock:$AWS_DEFAULT_REGION::foundation-model/us.anthropic.claude-sonnet-4-6\",\"enrichmentStrategyConfiguration\":{\"method\":\"CHUNK_ENTITY_EXTRACTION\"}}}" \
    --query 'dataSource.dataSourceId' --output text)
  echo "GraphRAG data source created: $GRAPHRAG_DS_ID"
fi
echo ""

# --- 8. Initial data load ---
echo "=== Step 8: Initial data load ==="
echo "Running prefill..."
cd "$PROJECT_DIR"
BEE_ACCOUNT_ID=$(bee me --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('id','unknown'))" 2>/dev/null || echo "unknown")
bee sync --output /tmp/bee-setup-data
python3 "$SCRIPT_DIR/util-scripts/ingest_bee_sync.py" /tmp/bee-setup-data --account-id "$BEE_ACCOUNT_ID"

echo ""
echo "Syncing KBs..."
aws bedrock-agent start-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" >/dev/null
aws bedrock-agent start-ingestion-job --knowledge-base-id "$GRAPHRAG_KB_ID" --data-source-id "$GRAPHRAG_DS_ID" >/dev/null
echo "Waiting 60s for KB sync..."
sleep 60

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Resources created:"
echo "  S3 Bucket:      $BUCKET"
echo "  Lambda:         BeeContextQueryStack-BeeIngestFn*"
echo "  EventBridge:    rate(1 hour), ENABLED"
echo "  Vector KB:      $KB_ID  (data source: $DS_ID)"
echo "  GraphRAG KB:    $GRAPHRAG_KB_ID  (data source: $GRAPHRAG_DS_ID)"
echo "  Neptune Graph:  $NEPTUNE_GRAPH_ID"
echo "  AOSS:           $EXISTING"
echo ""
echo "Add these to your .env:"
echo "  STRANDS_KNOWLEDGE_BASE_ID=$KB_ID"
echo "  GRAPHRAG_KB_ID=$GRAPHRAG_KB_ID"
echo "  GRAPHRAG_DS_ID=$GRAPHRAG_DS_ID"
echo "  NEPTUNE_GRAPH_ID=$NEPTUNE_GRAPH_ID"
echo "  BEE_CONTEXT_BUCKET=$BUCKET"
echo ""
echo "Neptune cost management (~\$0.96/hr when running):"
echo "  Pause:  aws neptune-graph stop-graph --graph-identifier $NEPTUNE_GRAPH_ID"
echo "  Resume: aws neptune-graph start-graph --graph-identifier $NEPTUNE_GRAPH_ID"
echo ""
echo "Test with:"
echo "  ./util-scripts/verify-bee-api.sh"
echo "  ./util-scripts/lambda-status.sh"
echo "  AWS_DEFAULT_REGION=us-west-2 python3 tools/query_kb.py \"what did I talk about today?\""
echo "  AWS_DEFAULT_REGION=us-west-2 python3 tools/generate_conversation.py --prompt \"Mitra plans tacos Tuesday\""
