"""Amazon shopping tool — unified tool using Playwright CLI with inline JS eval."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from strands import tool


async def _cli(cmd: str, session: str = "amazon") -> str:
    """Run a playwright-cli command asynchronously and return output."""
    try:
        proc = await asyncio.create_subprocess_shell(
            f"playwright-cli -s={session} {cmd}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        output = stdout.decode().strip()

        # Extract simple success/error status from playwright-cli output
        # Most commands just need confirmation they ran
        if proc.returncode == 0:
            return "OK"

        if proc.returncode != 0 and stderr:
            output += f"\nError: {stderr.decode().strip()}"
        return output[:4000] if len(output) > 4000 else output
    except asyncio.TimeoutError:
        return "Command timed out"
    except Exception as e:
        return f"Error: {e}"


async def _ensure_browser_open() -> None:
    """Ensure browser is open with persistent Playwright profile. Reopen if closed."""
    import logging
    logger = logging.getLogger(__name__)

    # First try a simple command to check if browser is open
    result = await _cli('eval "() => true"')
    logger.info(f"Browser check result: {result}")

    # If browser is closed, open it with persistent profile
    if result != "OK" and "not open" in result.lower():
        import os
        logger.info("Browser not open, opening with persistent profile...")
        # Expand ~ properly to avoid path issues
        profile_path = os.path.expanduser("~/.playwright-data/amazon-profile")
        os.makedirs(profile_path, exist_ok=True)
        open_result = await _cli(f'open https://www.amazon.com --headed --profile={profile_path}')
        logger.info(f"Browser open result: {open_result}")
        await asyncio.sleep(5)  # Wait longer for browser to fully initialize

        # Navigate to Amazon after opening
        goto_result = await _cli('goto https://www.amazon.com')
        logger.info(f"Goto Amazon result: {goto_result}")
        await asyncio.sleep(3)


async def _eval(js: str) -> str:
    """Run JS via playwright-cli eval using a temp file to avoid escaping issues."""
    import os
    import tempfile
    import logging
    logger = logging.getLogger(__name__)

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False)
    tmp.write(js)
    tmp.close()
    try:
        proc = await asyncio.create_subprocess_shell(
            f'playwright-cli -s=amazon eval "$(cat {tmp.name})"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
        output = stdout.decode().strip()
        logger.info(f"playwright-cli output length: {len(output)}")
        logger.info(f"playwright-cli output preview: {output[:300]}")

        # Parse playwright-cli output to extract just the result
        # Format is: "### Result\n<actual result>\n### Ran Playwright code..."
        if "### Result" in output:
            lines = output.split('\n')
            logger.info(f"Found {len(lines)} lines in output")
            for i, line in enumerate(lines):
                if line.strip() == "### Result":
                    logger.info(f"Found ### Result at line {i}")
                    # Next line has the actual result (may be quoted JSON string)
                    if i + 1 < len(lines):
                        result = lines[i + 1].strip()
                        logger.info(f"Result line: {repr(result[:100])}")
                        # Remove JSON string quotes if present
                        if result.startswith('"') and result.endswith('"'):
                            result = result[1:-1]
                            # Decode JSON escape sequences (\n, \t, etc.)
                            result = result.encode().decode('unicode_escape')
                            logger.info(f"Decoded result: {repr(result[:100])}")
                        return result

        # Fallback: return full output if parsing fails
        logger.warning("Failed to parse ### Result, returning full output")
        if proc.returncode != 0 and stderr:
            output += f"\nError: {stderr.decode().strip()}"
        return output[:4000] if len(output) > 4000 else output
    except asyncio.TimeoutError:
        return "Command timed out"
    except Exception as e:
        return f"Error: {e}"
    finally:
        os.unlink(tmp.name)


_EXTRACT_JS = '''() => {
  const items = document.querySelectorAll('[data-component-type="s-search-result"]');
  const results = Array.from(items).slice(0,2).map((item, i) => {
    const t = item.querySelector('.a-text-normal')?.textContent?.trim() || 'Unknown';
    const st = t.length > 60 ? t.substring(0,60) + '...' : t;
    const p = item.querySelector('.a-price .a-offscreen')?.textContent?.trim() || 'N/A';
    const r = item.querySelector('.a-icon-alt')?.textContent?.trim() || 'N/A';
    const a = item.getAttribute('data-asin') || '';
    return {
      display: (i+1) + '. ' + st + ' -- ' + r + ', ' + p,
      asin: a
    };
  });
  return JSON.stringify(results);
}'''


@tool
async def amazon_shopping(action: str, query: str = "", asin: str = "") -> AsyncIterator[str]:
    """Search Amazon and add items to the user's cart.

    **IMPORTANT FOR ASSISTANT:**
    This tool takes 10-15 seconds to complete. Before calling this tool:
    - Tell the user what you're doing: "Let me search Amazon for that"
    - While the tool runs, consider asking clarifying questions like:
      * "Any preferred brand?"
      * "Need it by a specific date?"
      * "What's your budget?"

    This keeps the user engaged while the search completes.

    This tool helps users shop on Amazon. It provides real-time progress updates as it works.

    ## How to use this tool

    **STEP 1: Search for an item**
    Call: amazon_shopping(action="search", query="apples")

    Returns something like:
    "Found apples! Here are the top options:
    1. Gala Apples, 3 Lb -- ★4.7, $2.38
    2. Organic Fuji Apples, 2 Lb -- ★4.6, $3.99
    ...
    (Item codes for selection: 1→B0ABC123, 2→B0XYZ789, ...)"

    **STEP 2: Read results to user**
    - Tell user the product names, ratings, and prices from lines 1-5
    - NEVER mention the item codes or ASINs to the user - these are internal only
    - Wait for user to pick one

    **STEP 3: Add the item they chose**
    When user says "add the first one" or "add option 2":
    - Extract the ASIN from the item codes section (e.g., "first one" = option 1 → B0ABC123)
    - Call: amazon_shopping(action="add_to_cart", asin="B0ABC123")
    - The tool automatically navigates to the product page and adds it to cart
    - You'll get progress updates like "Opening product page...", "Adding to cart...", etc.

    ## Handling multiple items

    If user asks to order multiple items (e.g., "help me buy pasta, sauce, and cheese"):
    1. Handle items ONE AT A TIME in sequence
    2. For each item: search → let user pick → add to cart
    3. Between items, tell user: "Added [item], now searching for [next item]..."
    4. After all items: "All items added! You have X items in cart. Ready to checkout?"

    ## Important rules

    - ALWAYS provide the ASIN when calling add_to_cart (extract it from the item codes)
    - NEVER mention ASINs or "item codes" to the user - these are internal
    - ONE item at a time - don't try to add multiple items in parallel
    - Let user choose from search results - don't auto-select for them
    - The tool gives progress updates automatically - just wait for them
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"🛒 amazon_shopping called: action={action}, query={query}, asin={asin}")

    if action == "search":
        if not query:
            yield "Error: query parameter required for search action"
            return

        yield f"Searching for {query} on Amazon, hold on for a moment..."

        # Ensure browser is open with persistent profile (preserves login)
        await _ensure_browser_open()
        await asyncio.sleep(2)  # Wait for page load
        await _cli(f'fill "#twotabsearchtextbox" "{query}" --submit')
        await asyncio.sleep(3)
        result_json = await _eval(_EXTRACT_JS)
        # Debug: Log what we got
        import logging
        import json
        logger = logging.getLogger(__name__)
        logger.info(f"_eval returned: {repr(result_json[:200])}")

        if "Unknown" in result_json and result_json.count("Unknown") > 3:
            await asyncio.sleep(3)
            result_json = await _eval(_EXTRACT_JS)
            logger.info(f"_eval retry returned: {repr(result_json[:200])}")

        # Parse JSON and format output
        try:
            # Debug: Show exactly what we're trying to parse
            logger.error(f"DEBUG: result_json type={type(result_json)}, len={len(result_json)}")
            logger.error(f"DEBUG: result_json first 500 chars: {repr(result_json[:500])}")

            if not result_json or result_json.strip() == "":
                logger.error("ERROR: result_json is empty!")
                yield (
                    "Error: No results returned from Amazon search. "
                    "The page might not have loaded properly. Please try again."
                )
                return

            results = json.loads(result_json)
            display_text = "\n".join([r["display"] for r in results])
            # Include ASINs in a structured way that agent can extract
            asin_list = [f"{i+1}→{r['asin']}" for i, r in enumerate(results)]
            asin_mapping = "\n\n(Item codes for selection: " + ", ".join(asin_list) + ")"
            yield f"Found {query}! Here are the top options:\n{display_text}{asin_mapping}"
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # Fallback if JSON parsing fails
            logger.error(f"Failed to parse search results: {e}")
            logger.error(f"Raw result_json: {repr(result_json[:1000])}")
            yield f"Error: Search completed but results couldn't be parsed. Raw output: {result_json[:500]}"

    elif action == "select":
        if not asin:
            logger.error("❌ select action called without asin")
            yield "Error: asin parameter required for select action"
            return

        yield "Opening product page..."
        logger.info(f"📦 Selecting product with ASIN: {asin}")

        # Ensure browser is open with persistent profile
        await _ensure_browser_open()

        # Navigate directly to product page using ASIN (more reliable than clicking)
        product_url = f"https://www.amazon.com/dp/{asin}"
        logger.info(f"🔗 Navigating to: {product_url}")
        await _cli(f'goto {product_url}')

        # Wait for product page to load
        await asyncio.sleep(4)

        # Verify we're on a product page
        url = await _eval('() => window.location.href')
        logger.info(f"📍 Current URL: {url[:100]}")
        if asin not in url:
            logger.error(f"❌ Navigation failed. Expected {asin} but got {url[:100]}")
            yield f"Error: Navigation failed. Expected ASIN {asin} but got URL: {url[:100]}"
            return

        title = await _eval('() => document.title')
        price = await _eval(
            "() => document.querySelector('.a-price .a-offscreen')?.textContent || 'N/A'"
        )
        logger.info(f"✅ Product selected: {title[:50]} - {price}")
        yield f"Product: {title}\nPrice: {price}\nReady to add to cart."

    elif action == "add_to_cart":
        logger.info("🛒 Starting add_to_cart action")

        # Ensure browser is open with persistent profile
        await _ensure_browser_open()

        # Check current URL to see if we're on a product page
        current_url = await _eval('() => window.location.href')
        logger.info(f"📍 Current URL before add to cart: {current_url[:100]}")

        # If ASIN is provided and we're not on the product page, navigate there first
        if asin:
            if f"/dp/{asin}" not in current_url:
                yield "Opening product page..."
                logger.info(f"🔗 Not on product page, navigating to ASIN {asin}")
                product_url = f"https://www.amazon.com/dp/{asin}"
                await _cli(f'goto {product_url}')
                await asyncio.sleep(4)
                current_url = await _eval('() => window.location.href')
                logger.info(f"📍 After navigation: {current_url[:100]}")

        # If no ASIN and we're not on a product page (still on search/home), error
        elif "/dp/" not in current_url and "/gp/product/" not in current_url:
            logger.error("❌ Not on product page and no ASIN provided")
            yield "Error: Not on a product page. Please use select action first or provide ASIN to add_to_cart."
            return

        yield "Adding to cart..."
        # Wait for page to fully load
        await asyncio.sleep(2)

        # Try multiple button selectors (Amazon uses different IDs)
        add_to_cart_js = """() => {
            const selectors = [
                '#add-to-cart-button',
                'input[name="submit.add-to-cart"]',
                '#buybox-add-cart-button',
                '#add-to-cart-button-ubb'
            ];

            for (const selector of selectors) {
                const btn = document.querySelector(selector);
                if (btn) {
                    btn.click();
                    return 'clicked: ' + selector;
                }
            }
            return 'not found';
        }"""

        result = await _eval(add_to_cart_js)
        logger.info(f"🔘 Button search result: {result}")

        if "not found" in result:
            # Retry after waiting (button might still be loading)
            logger.info("⏳ Button not found, retrying after 3s...")
            await asyncio.sleep(3)
            result = await _eval(add_to_cart_js)
            logger.info(f"🔘 Retry button search result: {result}")

            if "not found" in result:
                logger.error("❌ Add to cart button not found after retry")
                yield "Error: Add to cart button not found. Product may require login or be unavailable."
                return

        # Wait for cart update (Amazon redirects to cart page)
        logger.info("⏳ Waiting for cart update...")
        await asyncio.sleep(6)
        cart = await _eval("() => document.getElementById('nav-cart-count')?.textContent || '0'")
        title = await _eval("() => document.title")
        logger.info(f"🛒 Cart count: {cart}, Page: {title[:50]}")

        if cart == '0':
            logger.warning(f"⚠️ Cart count is still 0. Button was {result}")
            yield f"Warning: Cart count is still 0. Button was {result}, but cart didn't update. Page: {title}"
            return

        logger.info(f"✅ Successfully added to cart! Count: {cart}")
        yield f"Added to cart successfully! You now have {cart} items in your cart. Would you like to place the order?"

    else:
        yield f"Error: Unknown action '{action}'. Valid actions: search, select, add_to_cart"
