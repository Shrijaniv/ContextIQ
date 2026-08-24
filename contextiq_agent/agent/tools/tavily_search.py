"""
Tavily Web Search Tool - Real web search with AI-generated answers.
Uses Tavily API for current information retrieval.
"""
from strands import tool
from typing import Dict
import os
import requests


@tool
def search_web(query: str, max_results: int = 5, search_depth: str = "basic") -> Dict:
    """
    Search the web for current information.

    Args:
        query: Search query (e.g., "latest news about AI", "weather in Seattle")
        max_results: Maximum number of results to return (default: 5, max: 20)
        search_depth: Search depth - "basic" for quick results or "advanced" for comprehensive search (default: basic)

    Returns:
        Dict with search results including URLs, content, AI-generated answer, and sources
    """
    # Check if Tavily API key is configured
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        return {
            "error": "Tavily API key not configured",
            "message": (
                "Please set TAVILY_API_KEY in .env file. "
                "Register at https://tavily.com/ for free API access (1000 requests/month)."
            )
        }

    try:
        # Tavily API endpoint
        url = "https://api.tavily.com/search"

        payload = {
            "api_key": tavily_api_key,
            "query": query,
            "max_results": min(max_results, 20),  # API limit
            "search_depth": search_depth,
            "include_answer": True,
            "include_raw_content": False,
            "include_images": False
        }

        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()

        data = response.json()

        # Format results for agent
        results = []
        for item in data.get("results", []):
            results.append({
                "title": item.get("title"),
                "url": item.get("url"),
                "content": item.get("content"),
                "score": item.get("score"),
                "published_date": item.get("published_date")
            })

        return {
            "success": True,
            "answer": data.get("answer"),  # AI-generated answer
            "results": results,
            "total_found": len(results),
            "query": query,
            "message": f"Found {len(results)} results for '{query}'"
        }

    except requests.exceptions.HTTPError as e:
        error_msg = f"Tavily API error: {e}"
        try:
            error_data = e.response.json()
            error_msg = error_data.get("error", error_msg)
        except Exception:
            pass

        return {
            "error": error_msg,
            "query": query
        }

    except Exception as e:
        return {
            "error": f"Web search failed: {str(e)}",
            "query": query
        }
