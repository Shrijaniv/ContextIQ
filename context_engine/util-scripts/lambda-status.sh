#!/bin/bash
# Show Lambda + EventBridge status and recent activity
set -e
export AWS_DEFAULT_REGION=us-west-2

FUNC_NAME=$(aws lambda list-functions --query "Functions[?contains(FunctionName,'BeeIngest')].FunctionName" --output text)
LOG_GROUP="/aws/lambda/$FUNC_NAME"

echo "=== Schedule Status ==="
aws events list-rules \
  --query "Rules[?contains(Name,'BeeContext')].{Rule:Name,State:State,Schedule:ScheduleExpression}" --output table

echo ""
echo "=== Last 5 Runs ==="
aws logs filter-log-events \
  --log-group-name "$LOG_GROUP" \
  --start-time $(python3 -c "import time; print(int((time.time()-172800)*1000))") \
  --filter-pattern "Sync complete" \
  --query 'events[-5:].message' --output text 2>/dev/null | \
  python3 -c "
import sys, re, json
results = []
for line in sys.stdin.read().split('Sync complete: '):
    line = line.strip()
    if not line or not line.startswith('{'):
        continue
    try:
        d = json.loads(line.split('\t')[0].split('\n')[0])
        ts = d.get('synced_at','')[:19]
        c = d.get('conversations',0)
        ids = d.get('changed_conversation_ids',[])
        if c > 0:
            results.append(f'  {ts} — synced {c} conversation(s) {ids}')
        else:
            results.append(f'  {ts} — no new data')
    except: pass
for r in results[-5:]:
    print(r)
"

echo ""
echo "=== Last Run With New Data ==="
aws logs filter-log-events \
  --log-group-name "$LOG_GROUP" \
  --start-time $(python3 -c "import time; print(int((time.time()-604800)*1000))") \
  --filter-pattern "Sync complete" \
  --query 'events[].message' --output text 2>/dev/null | \
  python3 -c "
import sys, json
last = None
for line in sys.stdin.read().split('Sync complete: '):
    line = line.strip()
    if not line or not line.startswith('{'): continue
    try:
        d = json.loads(line.split('\t')[0].split('\n')[0])
        if d.get('conversations',0) > 0:
            last = d
    except: pass
if last:
    print(f\"  {last['synced_at'][:19]} — {last['conversations']} conversation(s) {last['changed_conversation_ids']}\")
else:
    print('  None in the last 7 days')
"

echo ""
echo "=== Uptime Range ==="
python3 -c "
import subprocess, json
from datetime import datetime, timezone

r = subprocess.run(['aws','logs','filter-log-events',
    '--log-group-name','$LOG_GROUP',
    '--filter-pattern','Starting Bee sync',
    '--query','events[].timestamp','--output','json'],
    capture_output=True, text=True)
ts = json.loads(r.stdout or '[]')
if ts:
    first = datetime.fromtimestamp(ts[0]/1000, tz=timezone.utc)
    last = datetime.fromtimestamp(ts[-1]/1000, tz=timezone.utc)
    days = (last - first).total_seconds() / 86400
    print(f'  First run: {first:%Y-%m-%d %H:%M UTC}')
    print(f'  Last run:  {last:%Y-%m-%d %H:%M UTC}')
    print(f'  Running for: {days:.1f} days')
else:
    print('  No log data found')
"
