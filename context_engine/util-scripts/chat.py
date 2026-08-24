#!/usr/bin/env python3
"""Two-stage Alexa+ text chat.

Stage 1 (Planning): LLM analyzes query → fetches context → decides what info tools to call → gathers info
Stage 2 (Response): LLM synthesizes all gathered info → responds to user → may offer actions

Usage:
    cd ~/workplace/ContextIQ && source venv/bin/activate
    AWS_DEFAULT_REGION=us-west-2 python3 context_engine/tools/chat.py
    AWS_DEFAULT_REGION=us-west-2 python3 context_engine/tools/chat.py --debug
"""
import os, sys, re, json, argparse, boto3
from botocore.config import Config

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

# Load .env from project root
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

p = argparse.ArgumentParser()
p.add_argument("--debug", action="store_true")
args = p.parse_args()

from strands import Agent
from strands.models.bedrock import BedrockModel
from tools.agent_context_retrieval import retrieve_context, _retrieve_kb, GRAPHRAG_KB, REGION
from contextiq_agent.agent.tools import (
    check_weather, search_restaurants, save_plan_summary,
    create_reminder, search_web, amazon_shopping,
)

DIM = "\033[2m"
RST = "\033[0m"
CYN = "\033[96m"
YEL = "\033[93m"
GRN = "\033[92m"
BLU = "\033[94m"
RED = "\033[91m"
BLD = "\033[1m"

model = BedrockModel(model_id="us.amazon.nova-pro-v1:0", region_name=REGION)
bedrock_rt = boto3.client("bedrock-runtime", region_name=REGION)


def llm_call(prompt, max_tokens=1024):
    """Quick LLM call for internal reasoning (no tools)."""
    resp = bedrock_rt.invoke_model(
        modelId="us.amazon.nova-pro-v1:0",
        body=json.dumps({
            "inferenceConfig": {"maxTokens": max_tokens},
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
        }),
    )
    body = json.loads(resp["body"].read())
    return body["output"]["message"]["content"][0]["text"].strip()


def fetch_context(query):
    """Fetch context from all three sources using multiple query angles."""
    client = boto3.client("bedrock-agent-runtime", region_name=REGION)

    # Primary query
    primary = _retrieve_kb(client, GRAPHRAG_KB, query, n=5)
    primary_texts = [r["text"] for r in primary if "error" not in r]

    # Secondary query: broaden to catch related details (outdoor plans, dates, people)
    # Extract key nouns and add context words
    broader_query = query + " plans activities date location walk outdoor"
    secondary = _retrieve_kb(client, GRAPHRAG_KB, broader_query, n=3)
    seen = {t[:100] for t in primary_texts}
    for r in secondary:
        if "error" not in r and r["text"][:100] not in seen:
            primary_texts.append(r["text"])
            seen.add(r["text"][:100])

    # Graph-enriched context is already folded into the KB retrieve results,
    # so there is no separate Neptune query here.
    return primary_texts, []


def stage1_analyze(user_query, context_texts, graph_lines):
    """Stage 1: LLM analyzes context and decides what info tools to call."""
    context_block = "\n\n".join(context_texts[:5])
    graph_block = "\n".join(graph_lines[:15]) if graph_lines else "(none)"

    prompt = f"""You are analyzing a user's request and the context retrieved from their conversation history.

USER QUERY: {user_query}

CONVERSATION CONTEXT:
{context_block}

KNOWLEDGE GRAPH:
{graph_block}

Extract details from the context and fill in EVERY field. Be specific.

SUMMARY: <2 sentence summary>
PEOPLE: <comma-separated names>
DATE: <specific date, e.g. "Wednesday, April 22nd 2026">
LOCATION: <city or place, default "Seattle" if not specified>
OUTDOOR_ACTIVITY: <any outdoor activity: walk, picnic, hike, run, waterfront, park, beach, etc. or "none">
ITEMS_USER_HAS: <items user already has>
ITEMS_USER_NEEDS: <items user still needs>
DIETARY_NOTES: <dietary restrictions>
INFO_TOOLS_NEEDED: <IMPORTANT: if OUTDOOR_ACTIVITY is anything other than "none", you MUST write "weather". If a restaurant is needed, write "restaurants". Comma-separate if multiple. Write "none" ONLY if no outdoor activity AND no restaurant needed.>"""

    return llm_call(prompt)


def parse_brief(brief_text):
    """Parse the structured brief into a dict."""
    result = {}
    for line in brief_text.split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip().upper().replace(" ", "_")
            result[key] = val.strip()
    return result


def call_weather_if_needed(brief):
    """Call weather API directly if the brief says it's needed."""
    tools_needed = brief.get("INFO_TOOLS_NEEDED", "").lower()
    if "weather" not in tools_needed:
        return None

    location = brief.get("LOCATION", "Seattle")
    if not location or location.lower() in ["not specified", "none", ""]:
        location = "Seattle"

    api_key = os.environ.get("OPENWEATHERMAP_API_KEY", "")
    if not api_key:
        return "Weather API key not configured."

    try:
        import httpx
        # Use free 5-day forecast API (no subscription needed, works with city name)
        resp = httpx.get(
            "https://api.openweathermap.org/data/2.5/forecast",
            params={"q": location, "appid": api_key, "units": "imperial", "cnt": 40},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        # Parse date from brief
        date_str = brief.get("DATE", "")
        # Build daily summary from 3-hour forecasts
        days = {}
        for item in data.get("list", []):
            day = item["dt_txt"][:10]
            if day not in days:
                days[day] = {"temps": [], "conditions": [], "rain": False}
            days[day]["temps"].append(item["main"]["temp"])
            desc = item["weather"][0]["description"]
            days[day]["conditions"].append(desc)
            if "rain" in desc.lower() or "storm" in desc.lower() or "drizzle" in desc.lower():
                days[day]["rain"] = True

        # Format forecast
        lines = []
        for day, info in sorted(days.items()):
            avg_temp = sum(info["temps"]) / len(info["temps"])
            main_condition = max(set(info["conditions"]), key=info["conditions"].count)
            rain_flag = "🌧 RAIN" if info["rain"] else "☀"
            lines.append(f"{day}: {avg_temp:.0f}°F, {main_condition} {rain_flag}")

        return f"Weather forecast for {location}:\n" + "\n".join(lines)
    except Exception as e:
        return f"Weather check failed: {e}"


def stage2_respond(user_query, brief_text, brief, weather_info):
    """Stage 2: Synthesize everything into a natural response."""
    weather_section = f"\nWEATHER FORECAST:\n{weather_info}" if weather_info else ""

    prompt = f"""You are Alexa+, a concise voice assistant. Respond to the user using the gathered information.

USER SAID: {user_query}

GATHERED INFO:
{brief_text}
{weather_section}

RULES:
- 1-2 sentences max. Sound natural, like Alexa.
- PRIORITY: If weather shows rain/storms for an outdoor activity:
  1. Lead with the weather problem and suggest the FIRST clear/sunny day from the forecast.
  2. Example: "Heads up — rain on Wednesday for the waterfront walk. Thursday looks clear. Want to move it?"
  3. Do NOT mention missing items or groceries yet — resolve the date first.
- If weather is fine or not checked: mention missing items and end with one offer to help.
- Do NOT call any tools. Just respond with text."""

    return llm_call(prompt)


# ── Action Agent for confirmations ──
action_agent = Agent(
    model=model,
    system_prompt="You are Alexa+. Execute what the user asked. For Amazon: search one item at a time, show name/price/rating, wait for user to pick. Keep responses to 1-2 sentences.",
    tools=[amazon_shopping, create_reminder, save_plan_summary, search_web, search_restaurants],
    callback_handler=None,
)

# ── Main Loop ──
print(f"{BLD}Alexa+ Text Chat (2-Stage Pipeline){RST}")
print(f"Debug: {'ON' if args.debug else 'OFF (use --debug)'}")
print(f"Ctrl+C to quit\n")

last_brief = None
last_brief_text = None

while True:
    try:
        text = input(f"{BLU}You:{RST} ")
        if not text.strip():
            continue

        # Check if this is a confirmation to a previous offer
        is_confirm = last_brief and any(w in text.lower() for w in
            ["yes", "yeah", "sure", "go ahead", "do it", "please", "order", "add", "book"])

        if is_confirm:
            if args.debug:
                print(f"{DIM}── Action agent ──{RST}")
            action_input = f"Context:\n{last_brief_text}\n\nUser: {text}"
            result = action_agent(action_input)
            response = result.message["content"][0]["text"]
        else:
            # Stage 1a: Fetch context
            if args.debug:
                print(f"\n{DIM}── Fetching context ──{RST}")
            context_texts, graph_lines = fetch_context(text)

            if args.debug:
                print(f"{DIM}  KB chunks: {len(context_texts)}, Graph entities: {len(graph_lines)}{RST}")

            # Stage 1b: Analyze and decide what tools to call
            if args.debug:
                print(f"{DIM}── Stage 1: analyzing ──{RST}")
            brief_text = stage1_analyze(text, context_texts, graph_lines)
            brief = parse_brief(brief_text)
            last_brief = brief
            last_brief_text = brief_text

            if args.debug:
                print(f"{YEL}{brief_text}{RST}")

            # Stage 1c: Call info tools if needed
            # Deterministic override: if outdoor activity found, force weather check
            outdoor = brief.get("OUTDOOR_ACTIVITY", "none").lower()
            tools_needed = brief.get("INFO_TOOLS_NEEDED", "none").lower()
            if outdoor != "none" and "weather" not in tools_needed:
                tools_needed = "weather"
                if args.debug:
                    print(f"{YEL}  ⚠ Override: outdoor activity '{outdoor}' detected but LLM said no weather. Forcing weather check.{RST}")

            weather_info = None
            if "weather" in tools_needed:
                if args.debug:
                    location = brief.get("LOCATION", "Seattle")
                    date = brief.get("DATE", "unknown")
                    print(f"{DIM}── Calling weather for {location} on {date} ──{RST}")
                weather_info = call_weather_if_needed(brief)
                if args.debug:
                    print(f"{CYN}  Weather result: {weather_info[:200] if weather_info else 'None'}{RST}")

            # Stage 2: Respond
            if args.debug:
                print(f"{DIM}── Stage 2: responding ──{RST}")
            response = stage2_respond(text, brief_text, brief, weather_info)

        response = re.sub(r'<thinking>.*?</thinking>\s*', '', response, flags=re.DOTALL).strip()
        print(f"{GRN}Alexa+:{RST} {response}\n")

    except KeyboardInterrupt:
        print("\nBye.")
        break
    except Exception as e:
        print(f"{RED}Error:{RST} {e}\n")
