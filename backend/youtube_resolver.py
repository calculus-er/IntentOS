"""
YouTube Resolver — IntentOS Sub-Agent

Embedded resolver called when the user wants to play a specific YouTube video.
Uses DuckDuckGo search to find real YouTube watch?v= URLs, then validates
with a Groq call using the YouTube Resolver persona.

Returns: {"video_url": str | None, "title": str | None, "channel": str | None}
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request

from groq import Groq

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "llama-3.3-70b-versatile"

_SYSTEM_PROMPT = """\
You are a YouTube video resolver embedded inside an AI operating system called IntentOS. \
You are called only when the user wants to play or open a specific video.
Your job: Take a natural language video request and search results, then return the exact YouTube video URL.
Return ONLY a raw JSON object. No markdown, no backticks, no preamble, no explanation. Just JSON.

Format:
{"video_url": "https://www.youtube.com/watch?v=VIDEO_ID", "title": "Exact Video Title", "channel": "Channel Name"}

Rules:
- Always return a direct watch?v= URL
- "latest" or "newest" = most recently uploaded by that creator
- "popular", "best", "top" = most viewed by that creator
- "trending" = currently trending on YouTube India
- Never return youtube.com/results (search page)
- Never return youtube.com/@ (channel page)
- Never return a playlist URL
- Return clean URL only: https://www.youtube.com/watch?v=VIDEO_ID
- Pick the single best match from the search results provided
- If not found: {"video_url": null, "title": null, "channel": null}

Only respond with JSON. Nothing else.
"""

# ---------------------------------------------------------------------------
# YouTube search (no API key required)
# ---------------------------------------------------------------------------

def _yt_search(query: str, max_results: int = 8) -> list[str]:
    """
    Use YouTube search to collect video URLs matching the query.
    Returns a list of raw result strings containing URLs.
    """
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.youtube.com/results?search_query={encoded}"

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
        print(f"[YouTubeResolver] YT fetch failed: {exc}")
        return []

    # Extract all video IDs from the YT HTML (it is embedded in window["ytInitialData"])
    # "videoId":"..." is a very reliable marker in the initial JSON state.
    pattern = r'"videoId":"([\w\-]{11})"'
    video_ids = re.findall(pattern, html)

    # De-duplicate while preserving order
    seen = set()
    unique_ids = []
    for vid in video_ids:
        if vid not in seen:
            seen.add(vid)
            unique_ids.append(vid)
        if len(unique_ids) >= max_results:
            break

    # Return as full URLs
    return [f"https://www.youtube.com/watch?v={vid}" for vid in unique_ids]


def _get_video_title(video_id: str) -> tuple[str, str]:
    """
    Fetch the title and channel of a YouTube video using the oEmbed API.
    Returns (title, channel). Falls back to ('Unknown Title', 'Unknown Channel').
    """
    try:
        oembed_url = (
            f"https://www.youtube.com/oembed"
            f"?url=https://www.youtube.com/watch?v={video_id}&format=json"
        )
        req = urllib.request.Request(
            oembed_url,
            headers={"User-Agent": "IntentOS/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return data.get("title", "Unknown Title"), data.get("author_name", "Unknown Channel")
    except Exception:
        return "Unknown Title", "Unknown Channel"


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------

def resolve_video(request: str) -> dict:
    """
    Resolve a natural-language video request to an exact YouTube watch URL.

    Args:
        request: e.g. "play samay raina latest video"

    Returns:
        {"video_url": str | None, "title": str | None, "channel": str | None}
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY is not set.")

    # 1. Search YouTube for candidate URLs
    candidates = _yt_search(request)
    print(f"[YouTubeResolver] Found {len(candidates)} candidate(s) for: \"{request}\"")

    # 2. Enrich candidates with titles via oEmbed (up to 5)
    enriched_lines = []
    for url in candidates[:5]:
        vid_id = url.split("v=")[-1]
        title, channel = _get_video_title(vid_id)
        enriched_lines.append(f"- URL: {url} | Title: {title} | Channel: {channel}")
        time.sleep(0.1)  # gentle throttle

    search_context = "\n".join(enriched_lines) if enriched_lines else "No results found."

    # 3. Ask Groq to pick the best match
    client = Groq(api_key=api_key)

    user_message = (
        f"User request: \"{request}\"\n\n"
        f"Search results (YouTube videos found):\n{search_context}\n\n"
        f"Pick the single best matching video and return the JSON."
    )

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
        print(f"[YouTubeResolver] Groq call failed: {exc}")
        # Best-effort fallback: return the first candidate directly
        if candidates:
            vid_id = candidates[0].split("v=")[-1]
            title, channel = _get_video_title(vid_id)
            return {"video_url": candidates[0], "title": title, "channel": channel}
        return {"video_url": None, "title": None, "channel": None}

    # Strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[YouTubeResolver] Bad JSON from Groq: {raw!r}")
        if candidates:
            vid_id = candidates[0].split("v=")[-1]
            title, channel = _get_video_title(vid_id)
            return {"video_url": candidates[0], "title": title, "channel": channel}
        return {"video_url": None, "title": None, "channel": None}

    # Safety: reject non-watch URLs
    video_url = result.get("video_url") or ""
    if video_url and "youtube.com/watch?v=" not in video_url:
        print(f"[YouTubeResolver] Rejected bad URL: {video_url}")
        result["video_url"] = candidates[0] if candidates else None

    print(f"[YouTubeResolver] Resolved: {result}")
    return result
