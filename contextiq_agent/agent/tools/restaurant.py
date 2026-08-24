"""Restaurant search tool — Yelp Fusion API."""

from __future__ import annotations

from strands import tool


@tool
def search_restaurants(
    location: str,
    latitude: float,
    longitude: float,
    cuisine: str = None,
    price: int = None,
    party_size: int = None,
) -> dict:
    """Search for restaurants near a location.

    Args:
        location: Human-readable location name.
        latitude: Latitude coordinate.
        longitude: Longitude coordinate.
        cuisine: Optional cuisine type (e.g. "Italian", "Japanese").
        price: Optional price level 1-4 (1=cheap, 4=expensive).
        party_size: Optional party size to accommodate.

    Returns:
        Dict with up to 5 restaurant results (name, rating, price, address, phone),
        or 'error' if search is unavailable.
    """
    from contextiq_agent.agent.config import get_config

    config = get_config()

    if not config.yelp_api_key:
        return {"error": "Yelp API key not configured"}

    try:
        import httpx

        headers = {"Authorization": f"Bearer {config.yelp_api_key}"}
        params: dict = {
            "latitude": latitude,
            "longitude": longitude,
            "term": cuisine or "restaurants",
            "limit": 5,
            "sort_by": "best_match",
        }
        if price:
            params["price"] = price

        resp = httpx.get(
            "https://api.yelp.com/v3/businesses/search",
            headers=headers,
            params=params,
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()

        results = [
            {
                "name": b["name"],
                "rating": b.get("rating"),
                "price": b.get("price", "N/A"),
                "address": ", ".join(b["location"].get("display_address", [])),
                "phone": b.get("display_phone", "N/A"),
            }
            for b in data.get("businesses", [])[:5]
        ]
        return {"location": location, "results": results}
    except Exception as exc:
        return {"error": f"Restaurant search is temporarily unavailable: {type(exc).__name__}"}
