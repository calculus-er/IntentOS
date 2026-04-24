"""
Google Search Resolver -- IntentOS Sub-Agent

Classifies search queries as 'deep' (open best authoritative site directly)
or 'basic' (open Google search results page).

Returns: {"search_type": str, "url": str, "reason": str}
"""

import json
import os
import re
import urllib.parse
import urllib.request

from groq import Groq

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "llama-3.3-70b-versatile"

_SYSTEM_PROMPT = """\
You are a Google Search Intent Classifier embedded inside an AI operating system called IntentOS. \
You are called ONLY when a user wants to search for something on Google.
You are NOT called for OS commands, volume, brightness, lock screen, focus mode, or YouTube videos.

Your job: Analyze the query and decide if it truly needs deep research (open best website directly) \
or just a basic Google search.

Return ONLY a raw JSON object. No markdown, no backticks, no explanation. Just JSON.

Format:
{"search_type": "deep" or "basic", "url": "URL to open", "reason": "one line reason"}

STRICT RULE -- Default to BASIC. Only go DEEP when the query clearly demands detailed, structured, \
long-form information that cannot be answered in a sentence or two.

DEEP only when ALL of these are true:
- The user is asking for detailed history, biography, or in-depth explanation of a complex topic
- OR asking for step-by-step technical documentation or coding tutorials
- OR asking for detailed medical condition explanation (not just "what is X")
- OR asking for in-depth legal or financial concepts
- AND the answer genuinely requires reading a full article or documentation page
- AND a quick Google snippet would NOT be enough

BASIC for everything else including:
- Simple factual questions ("what is diabetes", "who is Elon Musk")
- Sports queries ("will Dhoni play next match", "who won IPL 2024")
- Current news or events ("what happened in elections", "latest iPhone price")
- Weather, scores, schedules
- General curiosity or casual questions
- Anything answerable in 1-2 sentences
- Shopping, entertainment, browsing
- Any query with "will", "did", "is", "are", "when", "where", "who" -- these are almost always basic

URL rules:
- If BASIC: return "https://www.google.com/search?q=YOUR+QUERY+HERE"
- If DEEP: use the candidate URLs provided to find the single most relevant authoritative website
- For DEEP prefer: official docs, Wikipedia, GeeksForGeeks, WebMD, Investopedia, BBC based on topic
- FALLBACK: If no good candidate, return basic Google search URL instead of null

Safety rules:
- If query sounds like OS command -> return basic search, don't interfere
- If query is about YouTube video -> return basic search, handled separately
- When in doubt -> always return BASIC, never crash, never return null URL

Examples:
- "tell me history of Yogi Adityanath" -> deep (long-form biography needed)
- "how to implement binary search tree in python" -> deep (step by step tutorial needed)
- "explain the entire french revolution" -> deep (detailed historical analysis needed)
- "what is diabetes" -> basic (simple definition, Google snippet is enough)
- "will Dhoni play next match" -> basic (sports news, search page is enough)
- "who is Elon Musk" -> basic (simple factual, snippet is enough)
- "latest news about budget 2025" -> basic (current news, search page is enough)
- "what is quantum computing" -> basic (simple definition, snippet enough)
- "set volume to 50" -> basic (OS command, not a search)
- "play samay raina video" -> basic (YouTube query, handled separately)

Only respond with JSON. Nothing else.
"""

_FALLBACK_SAFE_DOMAINS = [
    "stackoverflow.com", "geeksforgeeks.org", "wikipedia.org",
    "webmd.com", "investopedia.com", "docs.python.org",
    "developer.mozilla.org", "bbc.com", "reuters.com",
    "ibm.com", "microsoft.com", "github.com",
]

# ---------------------------------------------------------------------------
# DuckDuckGo search — get real candidate URLs
# ---------------------------------------------------------------------------

def _ddg_search(query: str, max_results: int = 6) -> list[str]:
    """
    Use DuckDuckGo HTML search to get top non-Google URLs for the query.
    Returns a list of URLs.
    """
    encoded = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        print(f"[GoogleResolver] DDG search failed: {exc}")
        return []

    # Extract result URLs from DuckDuckGo HTML
    # DDG wraps external links via uddg= redirect param
    pattern = r'uddg=(https?[^"&]+)'
    raw_urls = re.findall(pattern, html)

    # Decode percent-encoded URLs
    decoded = []
    for u in raw_urls:
        try:
            decoded.append(urllib.parse.unquote(u))
        except Exception:
            pass

    # De-duplicate and filter out ad/DDG-internal URLs
    seen = set()
    results = []
    for u in decoded:
        if u in seen:
            continue
        seen.add(u)
        if "duckduckgo.com" in u or "google.com" in u:
            continue
        results.append(u)
        if len(results) >= max_results:
            break

    return results


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------

def resolve_search(query: str) -> dict:
    """
    Classify and resolve a search query.

    Args:
        query: e.g. "how to reverse a linked list in python"

    Returns:
        {"search_type": "deep"|"basic", "url": str, "reason": str}
    """
    api_key = os.getenv("GROQ_API_KEY")
    google_fallback = {
        "search_type": "basic",
        "url": "https://www.google.com/search?q=" + urllib.parse.quote_plus(query),
        "reason": "Fallback to basic Google search.",
    }

    if not api_key:
        print("[GoogleResolver] GROQ_API_KEY not set, using fallback.")
        return google_fallback

    # 1. Get candidate URLs from DuckDuckGo
    candidates = _ddg_search(query)
    print(f"[GoogleResolver] Found {len(candidates)} candidate(s) for: \"{query}\"")

    candidate_block = (
        "\n".join(f"- {u}" for u in candidates)
        if candidates
        else "No candidates found."
    )

    # 2. Ask Groq to classify and pick best URL
    user_message = (
        f"User search query: \"{query}\"\n\n"
        f"Candidate URLs from web search:\n{candidate_block}\n\n"
        f"Classify the query and return the best URL as JSON."
    )

    client = Groq(api_key=api_key)
    try:
        chat = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=256,
        )
        raw = chat.choices[0].message.content.strip()
    except Exception as exc:
        print(f"[GoogleResolver] Groq call failed: {exc}")
        return google_fallback

    # Strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[GoogleResolver] Bad JSON from Groq: {raw!r}")
        return google_fallback

    # Safety: never allow null URL
    if not result.get("url"):
        result["url"] = google_fallback["url"]
        result["search_type"] = "basic"

    # Safety: for deep, ensure it's not a Google search URL
    if result.get("search_type") == "deep" and "google.com/search" in result.get("url", ""):
        result["search_type"] = "basic"

    print(f"[GoogleResolver] Resolved: {result}")
    return result
