#!/usr/bin/env python3
"""Generate a realistic Bee-style document from a description, then ingest it.

Produces the full Bee Pioneer format: Summary, Atmosphere, Key Takeaways,
Action Items, and Transcript — exactly as the Bee device would output.

Usage:
    # Interactive prompt
    AWS_DEFAULT_REGION=us-west-2 python3 tools/generate_conversation.py

    # Inline description
    AWS_DEFAULT_REGION=us-west-2 python3 tools/generate_conversation.py \
        --prompt "Mitra and Bobby plan a taco night for Wednesday with Shrijani and Jun"

    # With metadata
    AWS_DEFAULT_REGION=us-west-2 python3 tools/generate_conversation.py \
        --prompt "..." --title "Taco night planning" --date 2026-04-22

    # Preview only (don't ingest)
    AWS_DEFAULT_REGION=us-west-2 python3 tools/generate_conversation.py --prompt "..." --preview
"""
import argparse
import json
import os
import sys
import boto3
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from ingest_text import ingest  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-west-2")

DEFAULT_MODEL_ID = os.environ.get(
    "GENERATION_MODEL_ID",
    "us.anthropic.claude-sonnet-4-6",
)

GENERATION_PROMPT = """\
Generate a realistic Bee Pioneer wearable recording document from the scenario below.

The Bee Pioneer is a wearable device that records ambient conversations and processes \
them into structured documents. Output the FULL document in this exact format:

### Summary
<2-3 sentence summary of what was discussed and decided>

### Atmosphere
<1 sentence describing the tone and setting>

### Key Takeaways
- <bullet point fact or decision>
- <bullet point fact or decision>
- <repeat for all important points — include names, dates, items, preferences>

### Action Items
- <person> needs to <action> [by <deadline> if mentioned]
- <repeat for all commitments and todos>

## Transcript
<realistic conversation transcript>

Transcript rules:
- Use natural, casual speech with filler words, interruptions, incomplete sentences
- Speaker labels: use real names from the scenario for the main speakers
- For background/incidental speakers (waiters, strangers) use "Unknown"
- 20-40 exchanges long
- Include specific details: times, dates, locations, item names where relevant
- Do NOT reference or acknowledge the recording device
- Start directly with dialogue

The main user is {user_name}.

Scenario:
{prompt}

Output the full document only. No preamble."""


def generate_bee_document(
    prompt: str,
    user_name: str = "Mitra",
    model_id: str = DEFAULT_MODEL_ID,
) -> str:
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    resp = bedrock.invoke_model(
        modelId=model_id,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": [{
                "role": "user",
                "content": GENERATION_PROMPT.format(prompt=prompt, user_name=user_name),
            }],
        }),
    )
    body = json.loads(resp["body"].read())
    return body["content"][0]["text"].strip()


def main():
    p = argparse.ArgumentParser(description="Generate a Bee-style document and ingest into KB + graph")
    p.add_argument("--prompt", help="Description of the conversation scenario")
    p.add_argument("--title", help="Document title")
    p.add_argument("--date", help="Date (YYYY-MM-DD)")
    p.add_argument("--user-id", default=os.environ.get("BEE_ACCOUNT_ID"))
    p.add_argument("--user-name", default="Mitra", help="Name of the main user")
    p.add_argument("--preview", action="store_true", help="Show generated document without ingesting")
    p.add_argument("--doc-id", help="Custom document ID")
    args = p.parse_args()

    prompt = args.prompt
    if not prompt:
        print("Describe the conversation scenario:")
        print("(e.g. 'Bobby and Mitra plan a taco night for Wednesday with Shrijani and Jun')")
        print()
        prompt = input("> ").strip()

    if not prompt:
        print("Error: no description provided")
        sys.exit(1)

    print(f"\nGenerating Bee document from: \"{prompt[:80]}{'...' if len(prompt) > 80 else ''}\"")
    print("...")

    document = generate_bee_document(prompt, user_name=args.user_name)

    print(f"\n{'='*60}")
    print("GENERATED DOCUMENT")
    print(f"{'='*60}\n")
    print(document)
    print(f"\n{'='*60}\n")

    if args.preview:
        print("(Preview mode — not ingested)")
        return

    title = args.title or f"Generated: {prompt[:50]}"
    print("Ingesting into KB + knowledge graph...\n")
    ingest(document, title=title, date=args.date, user_id=args.user_id, doc_id=args.doc_id)


if __name__ == "__main__":
    main()
