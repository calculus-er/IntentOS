"""
Weather Handler -- IntentOS Sub-Agent

Fast local city extractor — NO LLM CALL needed.
Uses local regex to extract city from the query.
Real weather data is fetched in executor.py via wttr.in.

Returns: {"city": str|None, "google_weather_url": str,
          "spoken_response": str, "action_type": "weather"}
     or: {"action_type": "not_weather"}  -- safety fallback
"""

import re
import urllib.parse

# ---------------------------------------------------------------------------
# Weather keyword detection
# ---------------------------------------------------------------------------

_WEATHER_KEYWORDS = [
    "weather", "temperature", "temp", "forecast", "rain", "raining",
    "sunny", "cloudy", "humidity", "humid", "hot", "cold", "wind",
    "windy", "storm", "snow", "drizzle", "haze", "fog",
]

_NON_WEATHER_TRIGGERS = [
    "play", "youtube", "search", "google", "volume", "brightness",
    "lock", "open", "focus", "note",
]

# ---------------------------------------------------------------------------
# City extraction patterns (ordered most-specific first)
# ---------------------------------------------------------------------------

# Trailing words to strip from city candidates
_CITY_STRIP = {
    "right", "now", "today", "tomorrow", "tonight", "please",
    "currently", "current", "latest", "at", "the", "a", "an",
}

_CITY_PATTERNS = [
    r'weather\s+(?:in|for|at|of)\s+([a-z][a-z\s]{1,25}?)(?:\s+right|\s+today|\s+tomorrow|\s+now|\s+tonight|\?|$)',
    r'temperature\s+(?:in|for|at|of)\s+([a-z][a-z\s]{1,25}?)(?:\s+right|\s+today|\s+tomorrow|\s+now|\s+tonight|\?|$)',
    r'forecast\s+(?:for|in|at|of)\s+([a-z][a-z\s]{1,25}?)(?:\s+right|\s+today|\s+tomorrow|\s+now|\s+tonight|\?|$)',
    r'(?:rain|sunny|cloudy|fog|snow)\s+in\s+([a-z][a-z\s]{1,25}?)(?:\s+right|\s+today|\s+tomorrow|\s+now|\s+tonight|\?|$)',
    r'how\s+(?:is|are|about)\s+(?:the\s+)?weather\s+in\s+([a-z][a-z\s]{1,25}?)(?:\s+right|\s+today|\s+tomorrow|\?|$)',
    r'(?:what\'?s?|tell me|show me)\s+(?:the\s+)?weather\s+(?:in|for|at)\s+([a-z][a-z\s]{1,25}?)(?:\s+right|\?|$)',
    r'(?:what\'?s?|how\'?s?)\s+(?:the\s+)?(?:weather|temp(?:erature)?)\s+in\s+([a-z][a-z\s]{1,25}?)(?:\s+right|\?|$)',
]

# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

def handle_weather(query: str) -> dict:
    """
    Fast local city extractor — no LLM call.

    Args:
        query: e.g. "what's the weather in Mumbai"

    Returns:
        {"city": str|None, "google_weather_url": str,
         "spoken_response": str, "action_type": "weather"}
        or {"action_type": "not_weather"}
    """
    q = query.lower().strip()

    # Safety: if no weather keywords present, pass through
    has_weather = any(kw in q for kw in _WEATHER_KEYWORDS)
    if not has_weather:
        print("[WeatherHandler] No weather keywords -- returning not_weather.")
        return {"action_type": "not_weather"}

    # Safety: if it looks like an OS/YouTube/search command, pass through
    for trigger in _NON_WEATHER_TRIGGERS:
        if q.startswith(trigger) or f" {trigger} " in q:
            print(f"[WeatherHandler] Detected non-weather trigger '{trigger}' -- returning not_weather.")
            return {"action_type": "not_weather"}

    # Extract city using regex patterns
    city = None
    for pattern in _CITY_PATTERNS:
        m = re.search(pattern, q)
        if m:
            candidate = m.group(1).strip()
            # Strip trailing stopwords word by word
            words = candidate.split()
            while words and words[-1] in _CITY_STRIP:
                words.pop()
            candidate = " ".join(words)
            # Filter out empty or pure stopword results
            if candidate and candidate not in ("the", "a", "an", "my", "your", "our"):
                city = candidate.title()
                break

    # Build Google weather URL
    if city:
        url = "https://www.google.com/search?q=weather+in+" + urllib.parse.quote_plus(city)
        spoken_fallback = f"Pulling up the weather for {city}, sir."
    else:
        url = "https://www.google.com/search?q=weather+near+me"
        spoken_fallback = "Fetching weather conditions for your location, sir."

    print(f"[WeatherHandler] Resolved: city={city!r}, url={url!r}")
    return {
        "city": city,
        "google_weather_url": url,
        "spoken_response": spoken_fallback,
        "action_type": "weather",
    }
