"""
Lambda that queries Bee API every hour and stores conversations, facts, todos,
and daily summaries in S3 as JSON files with metadata for Bedrock KB indexing.
"""
import json
import logging
import os
from datetime import datetime, timezone

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")
bedrock_agent = boto3.client("bedrock-agent", region_name=os.environ.get("AWS_REGION", "us-west-2"))

BUCKET = os.environ["BUCKET_NAME"]
SECRET_ARN = os.environ["BEE_SECRET_ARN"]
BEE_API_BASE = os.environ.get("BEE_API_BASE", "https://api.bee.computer")
CA_CERT_PATH = os.path.join(os.path.dirname(__file__), "bee_ca.pem")
CURSOR_KEY = "state/cursor.json"
KB_ID = os.environ.get("KB_ID")
KB_DATA_SOURCE_ID = os.environ.get("KB_DATA_SOURCE_ID")
# Comma-separated daily IDs to skip (e.g. colleagues' captured summaries)
EXCLUDED_DAILY_IDS = {
    i.strip() for i in os.environ.get("EXCLUDED_DAILY_IDS", "").split(",") if i.strip()
}


def get_bee_token():
    resp = secrets.get_secret_value(SecretId=SECRET_ARN)
    secret = json.loads(resp["SecretString"])
    return secret["bee_token"]


def bee_get(path, token, params=None):
    resp = requests.get(
        f"{BEE_API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        verify=CA_CERT_PATH,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def load_cursor():
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=CURSOR_KEY)
        return json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        return {}


def save_cursor(cursor_data):
    s3.put_object(
        Bucket=BUCKET,
        Key=CURSOR_KEY,
        Body=json.dumps(cursor_data),
        ContentType="application/json",
    )


def store_in_s3(prefix, item_id, data, bee_account_id, timestamp):
    key = f"{prefix}/{item_id}.json"
    metadata_key = f"{prefix}/{item_id}.json.metadata.json"

    if isinstance(timestamp, (int, float)) and timestamp > 0:
        date_str = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    elif isinstance(timestamp, str) and timestamp:
        date_str = timestamp[:10]
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(data, default=str),
        ContentType="application/json",
    )

    # Bedrock KB metadata for filtering
    s3.put_object(
        Bucket=BUCKET,
        Key=metadata_key,
        Body=json.dumps({
            "metadataAttributes": {
                "beeAccountId": bee_account_id,
                "dataType": prefix,
                "date": date_str,
            }
        }),
        ContentType="application/json",
    )


def extract_items(data, *keys):
    """Extract list from API response, trying known wrapper keys."""
    for key in keys:
        if isinstance(data, dict) and key in data:
            return data[key]
    if isinstance(data, list):
        return data
    return []


def epoch_to_date(ts):
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def epoch_to_datetime(ts):
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    return "unknown"


def write_clean(key, text, bee_account_id, date_str):
    """Write a clean text file + metadata for Bedrock KB."""
    s3.put_object(Bucket=BUCKET, Key=key, Body=text, ContentType="text/plain")
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{key}.metadata.json",
        Body=json.dumps({"metadataAttributes": {"beeAccountId": bee_account_id, "date": date_str}}),
        ContentType="application/json",
    )


def write_clean_conversation(data, cid, bee_account_id):
    lines = [f"# {data.get('short_summary', 'Conversation')}"]
    lines.append(f"Date: {epoch_to_datetime(data.get('start_time'))}")
    lines.append("")
    if data.get("summary"):
        lines.append(data["summary"])
        lines.append("")
    # Key takeaways and action items live in the full summary field from Bee.
    # Raw transcripts are intentionally excluded — ASR noise ("Unknown: ..."),
    # misheard words, and repeated utterances hurt embedding quality and
    # produce low-discrimination retrieval scores.
    write_clean(
        f"clean/conversations/{cid}.txt", "\n".join(lines),
        bee_account_id, epoch_to_date(data.get("start_time"))
    )


def write_clean_facts(facts, bee_account_id):
    lines = ["# Known Facts About User\n"]
    for f in facts:
        status = "confirmed" if f.get("confirmed") else "unconfirmed"
        tags = ", ".join(f.get("tags", []))
        lines.append(f"- ({status}) {f.get('text', '')} [{tags}]")
    write_clean(
        "clean/facts/all_facts.txt", "\n".join(lines),
        bee_account_id, datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )


def write_clean_daily(data, did, bee_account_id):
    date_str = epoch_to_date(data.get("date_time"))
    lines = [f"# Daily Summary — {date_str}"]
    if data.get("short_summary"):
        lines.append(f"Brief: {data['short_summary']}")
    lines.append("")
    if data.get("summary"):
        lines.append(data["summary"])
    write_clean(f"clean/daily/{did}.txt", "\n".join(lines), bee_account_id, date_str)


def sync_collection(path, prefix, token, bee_account_id, list_key="items", id_field="id"):
    """Fetch a paginated collection and store each item in S3."""
    data = bee_get(path, token)
    items = extract_items(data, list_key, "items")

    count = 0
    for item in items:
        item_id = item.get(id_field) or item.get("uuid") or item.get("id")
        timestamp = item.get("created_at") or item.get("start_time") or ""
        store_in_s3(prefix, str(item_id), item, bee_account_id, timestamp)
        count += 1

    # Write clean versions for KB
    if prefix == "facts":
        write_clean_facts(items, bee_account_id)
    elif prefix == "daily":
        for item in items:
            did = str(item.get("id") or item.get("uuid"))
            if did in EXCLUDED_DAILY_IDS:
                logger.info(f"Skipping excluded daily summary: {did}")
                continue
            write_clean_daily(item, did, bee_account_id)

    return count


def sync_conversations_detail(token, bee_account_id, conversation_ids):
    """Fetch full conversation details (with transcripts) and store."""
    count = 0
    for cid in conversation_ids:
        try:
            resp = bee_get(f"/v1/conversations/{cid}", token)
            detail = resp.get("conversation", resp) if isinstance(resp, dict) else resp
            timestamp = detail.get("start_time") or detail.get("created_at") or ""
            store_in_s3("conversations", str(cid), detail, bee_account_id, timestamp)
            write_clean_conversation(detail, str(cid), bee_account_id)
            count += 1
        except Exception as e:
            logger.warning(f"Failed to fetch conversation {cid}: {e}")
    return count


def handler(event, context):
    now = datetime.now(timezone.utc)
    logger.info(f"Starting Bee sync at {now.isoformat()}")

    token = get_bee_token()

    # Get user profile to identify account
    me = bee_get("/v1/me", token)
    bee_account_id = str(me.get("id") or me.get("uuid") or "unknown")
    logger.info(f"Bee account: {bee_account_id}")

    # Check for changes since last cursor
    cursor_state = load_cursor()
    last_cursor = cursor_state.get("cursor")

    params = {}
    if last_cursor:
        params["cursor"] = last_cursor

    changes = bee_get("/v1/changes", token, params=params)
    new_cursor = changes.get("cursor")

    # Sync facts and todos (always full sync — they're small)
    facts_count = sync_collection("/v1/facts", "facts", token, bee_account_id, list_key="facts")
    todos_count = sync_collection("/v1/todos", "todos", token, bee_account_id, list_key="todos")

    # Sync daily summaries
    daily_count = sync_collection("/v1/daily", "daily", token, bee_account_id, list_key="daily_summaries")

    # Sync changed conversations with full detail
    changed_conversations = extract_items(changes, "conversations", "items")
    conv_ids = [c.get("id") or c.get("uuid") if isinstance(c, dict) else c for c in changed_conversations if c]
    conv_count = sync_conversations_detail(token, bee_account_id, conv_ids)

    # Save cursor for next run
    if new_cursor:
        save_cursor({"cursor": new_cursor, "last_sync": now.isoformat()})

    # Trigger Bedrock KB ingestion to index new S3 files
    if KB_ID and KB_DATA_SOURCE_ID:
        bedrock_agent.start_ingestion_job(
            knowledgeBaseId=KB_ID,
            dataSourceId=KB_DATA_SOURCE_ID,
        )
        logger.info(f"Triggered KB ingestion: kb={KB_ID} ds={KB_DATA_SOURCE_ID}")

    result = {
        "status": "ok",
        "synced_at": now.isoformat(),
        "bee_account_id": bee_account_id,
        "facts": facts_count,
        "todos": todos_count,
        "daily": daily_count,
        "conversations": conv_count,
        "changed_conversation_ids": conv_ids,
    }
    logger.info(f"Sync complete: {json.dumps(result)}")
    return result
