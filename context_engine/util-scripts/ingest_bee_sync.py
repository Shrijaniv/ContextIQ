#!/usr/bin/env python3
"""
Ingest data from `bee sync` local output into S3 for Bedrock KB indexing.

This script reads markdown files from a `bee sync` output directory and uploads
them to S3 in the format expected by the existing Lambda/Bedrock KB setup.

Usage:
    # Sync from Bee CLI first
    bee sync --output ~/bee-data

    # Then ingest into S3
    AWS_DEFAULT_REGION=us-west-2 python3 ingest_bee_sync.py ~/bee-data

    # Or specify a custom bucket
    AWS_DEFAULT_REGION=us-west-2 python3 ingest_bee_sync.py ~/bee-data --bucket my-bucket

    # Specify account ID (extracted from path or defaulted)
    AWS_DEFAULT_REGION=us-west-2 python3 ingest_bee_sync.py ~/bee-data --account-id 12345
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import boto3

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from context_engine.env_config import bucket as default_bucket  # noqa: E402


def get_s3_client():
    return boto3.client("s3")


def parse_facts_md(filepath: Path) -> list[dict]:
    """Parse facts.md into structured fact objects."""
    facts = []
    if not filepath.exists():
        return facts

    content = filepath.read_text()
    # Pattern: - Fact text [tag1, tag2] (2024-01-15T10:30:00.000Z, id 42)
    # Or: - (confirmed) Fact text [tag1, tag2] (2024-01-15T10:30:00.000Z, id 42)
    pattern = r"^- (?:\((\w+)\) )?(.+?)(?: \[([^\]]*)\])? \((\d{4}-\d{2}-\d{2}T[\d:.]+Z), id (\d+)\)$"

    for line in content.split("\n"):
        line = line.strip()
        match = re.match(pattern, line)
        if match:
            status, text, tags_str, created_at, fact_id = match.groups()
            tags = [t.strip() for t in (tags_str or "").split(",") if t.strip()]
            facts.append({
                "id": int(fact_id),
                "text": text.strip(),
                "confirmed": status == "confirmed" if status else True,
                "tags": tags,
                "created_at": created_at,
            })

    return facts


def parse_todos_md(filepath: Path) -> list[dict]:
    """Parse todos.md into structured todo objects."""
    todos = []
    if not filepath.exists():
        return todos

    content = filepath.read_text()
    # Pattern: - Todo text (id 10, created 2024-01-15T09:00:00.000Z, alarm 2024-01-16T18:00:00.000Z)
    # Or: - Todo text (id 10, created 2024-01-15T09:00:00.000Z)
    pattern = r"^- (.+?) \(id (\d+), created (\d{4}-\d{2}-\d{2}T[\d:.]+Z)(?:, alarm (\d{4}-\d{2}-\d{2}T[\d:.]+Z))?\)$"

    current_section = None
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("## Open"):
            current_section = "open"
        elif line.startswith("## Completed"):
            current_section = "completed"
        else:
            match = re.match(pattern, line)
            if match:
                text, todo_id, created_at, alarm_at = match.groups()
                todos.append({
                    "id": int(todo_id),
                    "text": text.strip(),
                    "completed": current_section == "completed",
                    "created_at": created_at,
                    "alarm_at": alarm_at,
                })

    return todos


def parse_daily_summary_md(filepath: Path) -> dict:
    """Parse a daily summary.md file into structured data."""
    if not filepath.exists():
        return {}

    content = filepath.read_text()
    data = {}

    # Extract metadata from YAML-like frontmatter
    lines = content.split("\n")
    for line in lines:
        if line.startswith("- id:"):
            data["id"] = int(line.split(":", 1)[1].strip())
        elif line.startswith("- date_time:"):
            data["date_time"] = line.split(":", 1)[1].strip()
        elif line.startswith("- created_at:"):
            data["created_at"] = line.split(":", 1)[1].strip()
        elif line.startswith("- conversations_count:"):
            val = line.split(":", 1)[1].strip()
            data["conversations_count"] = int(val) if val.isdigit() else 0

    # Extract sections
    sections = re.split(r"\n## ", content)
    for section in sections[1:]:  # Skip header
        section_lines = section.split("\n")
        section_name = section_lines[0].strip()
        section_content = "\n".join(section_lines[1:]).strip()

        if section_name == "Short Summary":
            data["short_summary"] = section_content
        elif section_name == "Summary":
            data["summary"] = section_content
        elif section_name == "Email Summary":
            data["email_summary"] = section_content
        elif section_name == "Calendar Summary":
            data["calendar_summary"] = section_content

    return data


def parse_conversation_md(filepath: Path) -> dict:
    """Parse a conversation markdown file into structured data."""
    if not filepath.exists():
        return {}

    content = filepath.read_text()
    data = {"transcriptions": []}

    # Extract conversation ID from filename
    conv_id = filepath.stem
    data["id"] = int(conv_id) if conv_id.isdigit() else conv_id

    lines = content.split("\n")
    for line in lines:
        if line.startswith("- start_time:"):
            data["start_time"] = line.split(":", 1)[1].strip()
        elif line.startswith("- end_time:"):
            data["end_time"] = line.split(":", 1)[1].strip()
        elif line.startswith("- device_type:"):
            data["device_type"] = line.split(":", 1)[1].strip()
        elif line.startswith("- state:"):
            data["state"] = line.split(":", 1)[1].strip()
        elif line.startswith("- created_at:"):
            data["created_at"] = line.split(":", 1)[1].strip()
        elif line.startswith("- updated_at:"):
            data["updated_at"] = line.split(":", 1)[1].strip()

    # Extract sections
    sections = re.split(r"\n## ", content)
    for section in sections[1:]:
        section_lines = section.split("\n")
        section_name = section_lines[0].strip()
        section_content = "\n".join(section_lines[1:]).strip()

        if section_name == "Short Summary":
            data["short_summary"] = section_content
        elif section_name == "Summary":
            data["summary"] = section_content
        elif section_name == "Transcriptions":
            # Parse utterances - two formats:
            # With timestamps: - Speaker: Text (2026-01-15T10:30:00.000Z - 2026-01-15T10:30:05.000Z)
            # Without timestamps: - Speaker: Text
            utterances = []
            for line in section_content.split("\n"):
                line = line.strip()
                if not line.startswith("- ") or ": " not in line:
                    continue
                line = line[2:]  # strip "- "
                # Skip metadata lines like "- realtime: true"
                if line.startswith("realtime:") or line.startswith("###"):
                    continue
                speaker, _, text = line.partition(": ")
                if text:
                    # Strip trailing timestamp if present
                    text = re.sub(r'\s*\(\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*-\s*\d{4}-\d{2}-\d{2}T[\d:.]+Z\)$', '', text)
                    utterances.append({"speaker": speaker.strip(), "text": text.strip()})
            if utterances:
                data["transcriptions"].append({"utterances": utterances})

    return data


def iso_to_epoch(iso_str: str) -> int:
    """Convert ISO 8601 string to epoch milliseconds."""
    if not iso_str:
        return 0
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except (ValueError, AttributeError):
        return 0


def store_in_s3(s3, bucket: str, prefix: str, item_id: str, data: dict, bee_account_id: str, date_str: str):
    """Store item and metadata in S3."""
    key = f"{prefix}/{item_id}.json"
    metadata_key = f"{prefix}/{item_id}.json.metadata.json"

    logger.info(f"Uploading {key}")
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, default=str),
        ContentType="application/json",
    )

    s3.put_object(
        Bucket=bucket,
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


def write_clean(s3, bucket: str, key: str, text: str, bee_account_id: str, date_str: str):
    """Write clean text file + metadata for Bedrock KB."""
    logger.info(f"Uploading {key}")
    s3.put_object(Bucket=bucket, Key=key, Body=text, ContentType="text/plain")
    s3.put_object(
        Bucket=bucket,
        Key=f"{key}.metadata.json",
        Body=json.dumps({"metadataAttributes": {"beeAccountId": bee_account_id, "date": date_str}}),
        ContentType="application/json",
    )


def ingest_facts(s3, bucket: str, sync_dir: Path, bee_account_id: str) -> int:
    """Ingest facts.md into S3."""
    facts_file = sync_dir / "facts.md"
    facts = parse_facts_md(facts_file)

    if not facts:
        logger.info("No facts found")
        return 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Store each fact individually
    for fact in facts:
        date_str = fact.get("created_at", "")[:10] or today
        store_in_s3(s3, bucket, "facts", str(fact["id"]), fact, bee_account_id, date_str)

    # Write clean facts file for KB
    lines = ["# Known Facts About User\n"]
    for f in facts:
        status = "confirmed" if f.get("confirmed") else "unconfirmed"
        tags = ", ".join(f.get("tags", []))
        lines.append(f"- ({status}) {f.get('text', '')} [{tags}]")

    write_clean(s3, bucket, "clean/facts/all_facts.txt", "\n".join(lines), bee_account_id, today)

    return len(facts)


def ingest_todos(s3, bucket: str, sync_dir: Path, bee_account_id: str) -> int:
    """Ingest todos.md into S3."""
    todos_file = sync_dir / "todos.md"
    todos = parse_todos_md(todos_file)

    if not todos:
        logger.info("No todos found")
        return 0

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for todo in todos:
        date_str = todo.get("created_at", "")[:10] or today
        store_in_s3(s3, bucket, "todos", str(todo["id"]), todo, bee_account_id, date_str)

    return len(todos)


def ingest_daily_and_conversations(s3, bucket: str, sync_dir: Path, bee_account_id: str) -> tuple[int, int]:
    """Ingest daily summaries and conversations from daily/ directory."""
    daily_dir = sync_dir / "daily"
    if not daily_dir.exists():
        logger.info("No daily/ directory found")
        return 0, 0

    daily_count = 0
    conv_count = 0

    # Iterate over date directories
    for date_dir in sorted(daily_dir.iterdir()):
        if not date_dir.is_dir():
            continue

        date_str = date_dir.name  # YYYY-MM-DD

        # Process daily summary
        summary_file = date_dir / "summary.md"
        if summary_file.exists():
            daily_data = parse_daily_summary_md(summary_file)
            if daily_data and daily_data.get("id"):
                # Convert ISO dates to epoch for consistency
                if daily_data.get("date_time"):
                    daily_data["date_time"] = iso_to_epoch(daily_data["date_time"])
                if daily_data.get("created_at"):
                    daily_data["created_at"] = iso_to_epoch(daily_data["created_at"])

                store_in_s3(s3, bucket, "daily", str(daily_data["id"]), daily_data, bee_account_id, date_str)

                # Write clean daily summary
                lines = [f"# Daily Summary — {date_str}"]
                if daily_data.get("short_summary"):
                    lines.append(f"Brief: {daily_data['short_summary']}")
                lines.append("")
                if daily_data.get("summary"):
                    lines.append(daily_data["summary"])

                write_clean(s3, bucket, f"clean/daily/{daily_data['id']}.txt", "\n".join(lines), bee_account_id, date_str)
                daily_count += 1

        # Process conversations
        conv_dir = date_dir / "conversations"
        if conv_dir.exists():
            for conv_file in conv_dir.glob("*.md"):
                conv_data = parse_conversation_md(conv_file)
                if conv_data and conv_data.get("id"):
                    conv_id = str(conv_data["id"])

                    # Convert ISO dates to epoch
                    if conv_data.get("start_time") and isinstance(conv_data["start_time"], str):
                        conv_data["start_time"] = iso_to_epoch(conv_data["start_time"])
                    if conv_data.get("end_time") and isinstance(conv_data["end_time"], str):
                        conv_data["end_time"] = iso_to_epoch(conv_data["end_time"])
                    if conv_data.get("created_at") and isinstance(conv_data["created_at"], str):
                        conv_data["created_at"] = iso_to_epoch(conv_data["created_at"])

                    store_in_s3(s3, bucket, "conversations", conv_id, conv_data, bee_account_id, date_str)

                    # Write clean conversation
                    lines = [f"# {conv_data.get('short_summary', 'Conversation')}"]
                    lines.append(f"Date: {date_str}")
                    lines.append("")
                    if conv_data.get("summary"):
                        lines.append(conv_data["summary"])
                        lines.append("")
                    lines.append("## Transcript\n")
                    for t in conv_data.get("transcriptions", []):
                        for u in t.get("utterances", []):
                            text = u.get("text", "").strip()
                            if text:
                                lines.append(f"{u.get('speaker', 'Unknown')}: {text}")

                    write_clean(s3, bucket, f"clean/conversations/{conv_id}.txt", "\n".join(lines), bee_account_id, date_str)
                    conv_count += 1

    return daily_count, conv_count


def ingest_conversations(s3, bucket: str, sync_dir: Path, bee_account_id: str) -> int:
    """Ingest conversations from top-level conversations/ directory."""
    conv_dir = sync_dir / "conversations"
    if not conv_dir.exists():
        return 0

    count = 0
    for date_dir in sorted(conv_dir.iterdir()):
        if not date_dir.is_dir():
            continue
        date_str = date_dir.name
        for conv_file in date_dir.glob("*.md"):
            conv_data = parse_conversation_md(conv_file)
            if conv_data and conv_data.get("id"):
                conv_id = str(conv_data["id"])
                for field in ("start_time", "end_time", "created_at"):
                    if conv_data.get(field) and isinstance(conv_data[field], str):
                        conv_data[field] = iso_to_epoch(conv_data[field])
                store_in_s3(s3, bucket, "conversations", conv_id, conv_data, bee_account_id, date_str)

                lines = [f"# {conv_data.get('short_summary', 'Conversation')}"]
                lines.append(f"Date: {date_str}")
                lines.append("")
                if conv_data.get("summary"):
                    lines.append(conv_data["summary"])
                    lines.append("")
                lines.append("## Transcript\n")
                for t in conv_data.get("transcriptions", []):
                    for u in t.get("utterances", []):
                        text = u.get("text", "").strip()
                        if text:
                            lines.append(f"{u.get('speaker', 'Unknown')}: {text}")
                write_clean(s3, bucket, f"clean/conversations/{conv_id}.txt", "\n".join(lines), bee_account_id, date_str)
                count += 1
    return count


def try_get_account_id_from_cli() -> Optional[str]:
    """Try to get account ID from bee CLI."""
    try:
        result = subprocess.run(
            ["bee", "me", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return str(data.get("id") or data.get("uuid") or "")
    except (subprocess.SubprocessError, json.JSONDecodeError, FileNotFoundError):
        pass
    return None


def extract_account_from_path(sync_dir: Path) -> Optional[str]:
    """Try to extract account identifier from a path like <alias>/bee-data."""
    parts = sync_dir.parts
    for i, part in enumerate(parts):
        if part in ("bee-data", "bee-sync") and i > 0:
            return parts[i - 1]
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Ingest bee sync output into S3 for Bedrock KB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic usage
    python3 ingest_bee_sync.py ~/bee-sync

    # Custom output directory from bee sync
    python3 ingest_bee_sync.py ~/bee-data

    # Specify account ID explicitly
    python3 ingest_bee_sync.py ~/bee-sync --account-id $BEE_ACCOUNT_ID

    # Use different S3 bucket
    python3 ingest_bee_sync.py ~/bee-sync --bucket my-custom-bucket
        """,
    )
    parser.add_argument("sync_dir", type=Path, help="Path to bee sync output directory")
    parser.add_argument(
        "--bucket",
        help="S3 bucket name (default: BEE_CONTEXT_BUCKET, or derived from AWS_ACCOUNT_ID)",
    )
    parser.add_argument("--account-id", help="Bee account ID (auto-detected if not provided)")
    parser.add_argument("--dry-run", action="store_true", help="Parse files but don't upload to S3")

    args = parser.parse_args()

    if not args.sync_dir.exists():
        logger.error(f"Directory not found: {args.sync_dir}")
        return 1

    if not args.bucket:
        args.bucket = default_bucket()

    # Determine account ID
    bee_account_id = args.account_id or os.environ.get("BEE_ACCOUNT_ID")
    if not bee_account_id:
        bee_account_id = try_get_account_id_from_cli()
    if not bee_account_id:
        bee_account_id = extract_account_from_path(args.sync_dir)
    if not bee_account_id:
        bee_account_id = "unknown"
        logger.warning("Could not determine bee account ID, using 'unknown'")

    logger.info(f"Ingesting from: {args.sync_dir}")
    logger.info(f"Target bucket: {args.bucket}")
    logger.info(f"Bee account ID: {bee_account_id}")

    if args.dry_run:
        logger.info("DRY RUN - parsing only, not uploading")
        # Just parse and show what would be uploaded
        facts = parse_facts_md(args.sync_dir / "facts.md")
        todos = parse_todos_md(args.sync_dir / "todos.md")
        logger.info(f"Would upload {len(facts)} facts, {len(todos)} todos")
        return 0

    s3 = get_s3_client()

    # Ingest all data types
    facts_count = ingest_facts(s3, args.bucket, args.sync_dir, bee_account_id)
    todos_count = ingest_todos(s3, args.bucket, args.sync_dir, bee_account_id)
    daily_count, conv_count = ingest_daily_and_conversations(s3, args.bucket, args.sync_dir, bee_account_id)
    conv_count += ingest_conversations(s3, args.bucket, args.sync_dir, bee_account_id)

    logger.info("=" * 50)
    logger.info("Ingestion complete!")
    logger.info(f"  Facts: {facts_count}")
    logger.info(f"  Todos: {todos_count}")
    logger.info(f"  Daily summaries: {daily_count}")
    logger.info(f"  Conversations: {conv_count}")
    logger.info("=" * 50)
    logger.info("Run this to re-sync the Bedrock Knowledge Base:")
    logger.info("  aws bedrock-agent start-ingestion-job \\")
    logger.info("    --knowledge-base-id $GRAPHRAG_KB_ID --data-source-id $GRAPHRAG_DS_ID")

    return 0


if __name__ == "__main__":
    exit(main())
