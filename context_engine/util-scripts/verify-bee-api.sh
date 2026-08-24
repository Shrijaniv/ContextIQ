#!/bin/bash
# Verify the Lambda can reach the Bee API and authenticate
set -e
export AWS_DEFAULT_REGION=us-west-2

FUNC_NAME=$(aws lambda list-functions --query "Functions[?contains(FunctionName,'BeeIngest')].FunctionName" --output text)

if [ -z "$FUNC_NAME" ]; then
  echo "FAIL: Lambda function not found. Is the CDK stack deployed?"
  exit 1
fi
echo "OK: Lambda found — $FUNC_NAME"

# Invoke with a test payload that only calls /v1/me
echo ""
echo "Invoking Lambda to test Bee API connectivity..."
RESULT=$(aws lambda invoke \
  --function-name "$FUNC_NAME" \
  --payload '{}' \
  --cli-binary-format raw-in-base64-out \
  --query 'FunctionError' --output text \
  /tmp/bee-health-check.json 2>&1)

RESPONSE=$(cat /tmp/bee-health-check.json)

if echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='ok'" 2>/dev/null; then
  ACCOUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('bee_account_id','unknown'))")
  echo "OK: Bee API authenticated — account $ACCOUNT"
  echo ""
  echo "Sync result:"
  echo "$RESPONSE" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f\"  Facts: {d.get('facts',0)}\")
print(f\"  Todos: {d.get('todos',0)}\")
print(f\"  Daily: {d.get('daily',0)}\")
print(f\"  Conversations: {d.get('conversations',0)}\")
print(f\"  Changed IDs: {d.get('changed_conversation_ids',[])}\")
"
else
  echo "FAIL: Lambda returned an error"
  echo "$RESPONSE" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  print(f\"  Error: {d.get('errorMessage','unknown')}\")
  print(f\"  Type: {d.get('errorType','unknown')}\")
except: print(sys.stdin.read())
" 2>/dev/null || echo "$RESPONSE"
  exit 1
fi

rm -f /tmp/bee-health-check.json
