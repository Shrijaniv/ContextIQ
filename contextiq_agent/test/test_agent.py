#!/usr/bin/env python3
"""Text-mode agent test — same tools and system prompt as the voice agent.

Usage:
    cd ~/Desktop/mitra_km/ContextIQ
    AWS_PROFILE=your-aws-profile python3 contextiq_agent/test_agent.py
    AWS_PROFILE=your-aws-profile python3 contextiq_agent/test_agent.py --debug
"""
import os
import sys
import argparse

# Path and env setup must precede local imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

# noqa: E402 — intentional late imports after path setup
import dotenv  # noqa: E402
import strands  # noqa: E402
import strands.models.bedrock  # noqa: E402
import context_engine.tools.agent_context_retrieval as hm_module  # noqa: E402
import contextiq_agent.agent.contextiq_agent as ka_module  # noqa: E402
import contextiq_agent.agent.tools as tools_module  # noqa: E402

dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

Agent = strands.Agent
BedrockModel = strands.models.bedrock.BedrockModel
retrieve_context = hm_module.retrieve_context
CONTEXTIQ_SYSTEM_PROMPT = ka_module.CONTEXTIQ_SYSTEM_PROMPT
check_weather = tools_module.check_weather
search_restaurants = tools_module.search_restaurants
save_plan_summary = tools_module.save_plan_summary
create_reminder = tools_module.create_reminder
search_web = tools_module.search_web
amazon_shopping = tools_module.amazon_shopping

BLD = "\033[1m"
GRN = "\033[92m"
BLU = "\033[94m"
YEL = "\033[93m"
DIM = "\033[2m"
RST = "\033[0m"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--debug", action="store_true", help="Show tool calls")
    args = p.parse_args()

    model = BedrockModel(
        model_id="us.amazon.nova-pro-v1:0",
        region_name="us-west-2",
    )

    callback = None
    if args.debug:
        def callback(**kwargs):
            if "tool_use" in kwargs:
                t = kwargs["tool_use"]
                print(f"\n{YEL}[tool] {t.get('name')} <- {str(t.get('input', ''))[:120]}{RST}")
            if "tool_result" in kwargs:
                r = kwargs["tool_result"]
                content = r.get("content", "")
                if isinstance(content, list):
                    content = content[0].get("text", "") if content else ""
                print(f"{DIM}[result] {str(content)[:300]}{RST}")

    agent = Agent(
        model=model,
        system_prompt=CONTEXTIQ_SYSTEM_PROMPT,
        tools=[
            retrieve_context,
            check_weather,
            search_restaurants,
            save_plan_summary,
            create_reminder,
            search_web,
            amazon_shopping,
        ],
        callback_handler=callback,
    )

    debug_label = "ON" if args.debug else "OFF, use --debug"
    print(f"{BLD}ContextIQ Text Test{RST}  (debug={debug_label})")
    print(f"{DIM}Try: 'help me order those groceries' / 'what did I commit to?' / 'plan Emma's party'{RST}")
    print("Ctrl+C to quit\n")

    while True:
        try:
            text = input(f"{BLU}You:{RST} ").strip()
            if not text:
                continue
            result = agent(text)
            import re
            response = result.message["content"][0]["text"]
            response = re.sub(r'<thinking>.*?</thinking>\s*', '', response, flags=re.DOTALL).strip()
            print(f"\n{GRN}Alexa+:{RST} {response}\n")
        except KeyboardInterrupt:
            print("\nBye.")
            break
        except Exception as e:
            print(f"\033[91mError:\033[0m {e}\n")


if __name__ == "__main__":
    main()
