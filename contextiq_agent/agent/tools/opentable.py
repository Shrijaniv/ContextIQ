"""OpenTable reservation tool — uses Playwright CLI for browser automation."""

from __future__ import annotations

import subprocess
import time
import tempfile
import os

from strands import tool


def _cli(cmd: str, session: str = "opentable") -> str:
    """Run a playwright-cli command."""
    try:
        result = subprocess.run(
            f"playwright-cli -s={session} {cmd}",
            shell=True, capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output += f"\nError: {result.stderr.strip()}"
        return output[:4000] if len(output) > 4000 else output
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except Exception as e:
        return f"Error: {e}"


def _eval(js: str) -> str:
    """Run JS via playwright-cli eval using a temp file."""
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False)
    tmp.write(js)
    tmp.close()
    try:
        result = subprocess.run(
            f'playwright-cli -s=opentable eval "$(cat {tmp.name})"',
            shell=True, capture_output=True, text=True, timeout=15,
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output += f"\nError: {result.stderr.strip()}"
        return output[:4000] if len(output) > 4000 else output
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except Exception as e:
        return f"Error: {e}"
    finally:
        os.unlink(tmp.name)


@tool
def opentable_search(restaurant_name: str, date: str, time_slot: str, party_size: int) -> str:
    """Search OpenTable for a restaurant and available reservation times.

    Args:
        restaurant_name: Name of the restaurant to search for.
        date: Date for the reservation (e.g., "2026-04-20").
        time_slot: Preferred time (e.g., "7:00 PM").
        party_size: Number of guests.

    Returns:
        Available time slots and any booking rules/fees, or error message.
    """
    # Build OpenTable search URL
    search_url = f"https://www.opentable.com/s?dateTime={date}T19%3A00&covers={party_size}&term={restaurant_name.replace(' ', '%20')}"

    _cli(f'open {search_url} --headed')
    time.sleep(4)

    # Extract search results
    result = _eval('''() => {
      const cards = document.querySelectorAll('[data-test="restaurant-card"], [class*="RestaurantCard"], [class*="restaurant-card"]');
      if (cards.length === 0) {
        const results = document.querySelectorAll('a[href*="/restaurant/"]');
        return Array.from(results).slice(0, 5).map((el, i) => {
          const name = el.textContent?.trim()?.substring(0, 80) || "Unknown";
          return (i+1) + ". " + name;
        }).join("\\n") || "No restaurants found. Try a different search.";
      }
      return Array.from(cards).slice(0, 5).map((card, i) => {
        const name = card.querySelector("h2, [class*='name'], [class*='Name']")?.textContent?.trim() || "Unknown";
        const rating = card.querySelector("[class*='rating'], [class*='Rating']")?.textContent?.trim() || "";
        const price = card.querySelector("[class*='price'], [class*='Price']")?.textContent?.trim() || "";
        const times = Array.from(card.querySelectorAll("button[class*='time'], [class*='TimeSlot']")).map(t => t.textContent?.trim()).join(", ");
        return (i+1) + ". " + name + (rating ? " — " + rating : "") + (price ? " " + price : "") + (times ? " | Available: " + times : "");
      }).join("\\n");
    }''')

    return f"OpenTable results for '{restaurant_name}' on {date}, party of {party_size}:\\n{result}"


@tool
def opentable_select_restaurant(ref_or_index: str) -> str:
    """Click on a restaurant from OpenTable search results to see details and available times.

    Args:
        ref_or_index: Element ref from snapshot or the restaurant number (e.g., "1" for first result).

    Returns:
        Restaurant details including available times, booking rules, and any fees.
    """
    # Try clicking by ref first, fall back to nth result link
    if ref_or_index.startswith("e"):
        _cli(f'click {ref_or_index}')
    else:
        idx = int(ref_or_index) - 1
        _eval(f'''() => {{
          const links = document.querySelectorAll('a[href*="/restaurant/"]');
          const unique = [...new Set(Array.from(links).map(l => l.href))];
          if (unique[{idx}]) {{ window.location.href = unique[{idx}]; return "navigated"; }}
          return "not found";
        }}''')

    time.sleep(4)

    # Extract restaurant details and booking info
    details = _eval('''() => {
      const name = document.querySelector("h1")?.textContent?.trim() || "Unknown";
      const pageText = document.body.innerText;

      // Check for fees or rules
      const feePatterns = ["deposit", "prepaid", "credit card", "cancellation fee", "no-show fee", "booking fee", "per person"];
      const fees = feePatterns.filter(p => pageText.toLowerCase().includes(p));

      // Check for booking rules
      const rulePatterns = ["dress code", "smart casual", "business casual", "formal", "minimum spend", "time limit", "maximum"];
      const rules = rulePatterns.filter(p => pageText.toLowerCase().includes(p));

      // Get available times
      const timeSlots = Array.from(document.querySelectorAll("button[data-test*='time'], [class*='TimeSlot'] button, [class*='timeslot']"))
        .map(t => t.textContent?.trim())
        .filter(t => t && t.match(/\\d/))
        .slice(0, 8);

      let result = "Restaurant: " + name + "\\n";
      if (timeSlots.length > 0) result += "Available times: " + timeSlots.join(", ") + "\\n";
      if (fees.length > 0) result += "⚠️ PAYMENT/FEES: " + fees.join(", ") + "\\n";
      if (rules.length > 0) result += "📋 RULES: " + rules.join(", ") + "\\n";
      if (fees.length === 0 && rules.length === 0) result += "No special fees or rules detected.\\n";

      return result;
    }''')

    return details


@tool
def opentable_reserve(time_slot_ref: str) -> str:
    """Click a time slot to start the reservation process on OpenTable.
    ONLY call this after the user has confirmed they want to book and
    has been informed of any fees or rules.

    Args:
        time_slot_ref: Element ref for the time slot button from the snapshot.

    Returns:
        Reservation confirmation page details or next steps needed.
    """
    _cli(f'click {time_slot_ref}')
    time.sleep(4)

    # Check what page we're on — could be confirmation form or login
    page_info = _eval('''() => {
      const title = document.title;
      const pageText = document.body.innerText.substring(0, 2000);

      // Check if we need to log in
      if (pageText.includes("Sign in") || pageText.includes("Log in") || pageText.includes("email")) {
        return "LOGIN_REQUIRED: OpenTable requires you to sign in to complete the reservation. Please log in on the browser.";
      }

      // Check for confirmation page
      if (pageText.includes("Complete reservation") || pageText.includes("Confirm")) {
        // Look for fee warnings
        const feeText = pageText.match(/deposit|prepaid|credit card|charge|fee/gi);
        let result = "READY TO CONFIRM: Reservation form is ready.\\n";
        if (feeText) result += "⚠️ Payment required: " + [...new Set(feeText)].join(", ") + "\\n";
        result += "Page: " + title;
        return result;
      }

      return "Page loaded: " + title + "\\n" + pageText.substring(0, 500);
    }''')

    return page_info


@tool
def opentable_confirm_reservation(first_name: str, last_name: str, phone: str, email: str) -> str:
    """Fill in reservation details and confirm the booking on OpenTable.
    ONLY call this after user has explicitly agreed to any fees/rules.

    Args:
        first_name: Guest's first name.
        last_name: Guest's last name.
        phone: Phone number.
        email: Email address.

    Returns:
        Confirmation result.
    """
    # Fill in the form fields
    _eval(f'''() => {{
      const inputs = document.querySelectorAll("input");
      for (const input of inputs) {{
        const name = (input.name || input.id || input.placeholder || "").toLowerCase();
        if (name.includes("first")) input.value = "{first_name}";
        else if (name.includes("last")) input.value = "{last_name}";
        else if (name.includes("phone") || name.includes("mobile")) input.value = "{phone}";
        else if (name.includes("email")) input.value = "{email}";
        input.dispatchEvent(new Event("input", {{ bubbles: true }}));
        input.dispatchEvent(new Event("change", {{ bubbles: true }}));
      }}
      return "Form filled";
    }}''')

    time.sleep(2)

    # Click the confirm/complete button
    _eval('''() => {
      const buttons = Array.from(document.querySelectorAll("button"));
      const confirm = buttons.find(b => {
        const text = b.textContent?.toLowerCase() || "";
        return text.includes("complete") || text.includes("confirm") || text.includes("reserve");
      });
      if (confirm) { confirm.click(); return "Clicked confirm"; }
      return "Confirm button not found";
    }''')

    time.sleep(4)

    # Check result
    result = _eval('''() => {
      const pageText = document.body.innerText;
      if (pageText.includes("confirmed") || pageText.includes("Confirmed") || pageText.includes("booked")) {
        return "✅ RESERVATION CONFIRMED! " + document.title;
      }
      if (pageText.includes("error") || pageText.includes("Error")) {
        return "❌ Reservation failed. " + pageText.substring(0, 300);
      }
      return "Status unclear. Page: " + document.title + "\\n" + pageText.substring(0, 500);
    }''')

    return result


OPENTABLE_TOOLS = [opentable_search, opentable_select_restaurant, opentable_reserve, opentable_confirm_reservation]
