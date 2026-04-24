"""
AI Engine — Groq integration for IntentOS.

Takes a raw natural-language intent string and returns a structured list
of OS-level actions by prompting the llama-3.3-70b-versatile model.
"""

import json
import os
import re

from groq import Groq

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are IntentOS, an AI that converts a user's natural-language intent into a precise JSON action plan that a local operating system agent can execute.

RULES:
1. Return ONLY a valid JSON array — no markdown, no commentary, no code fences.
2. Each element must be an object with exactly two keys:
   - "action": one of "open_folder", "open_url", "open_app", "run_command"
   - "target": the full path, URL, application name, or shell command string
3. Choose realistic, helpful targets. For learning intents, pick well-known educational URLs (e.g., LeetCode, VisualGo, GeeksforGeeks, YouTube tutorials).
4. For folder paths on Windows, use forward slashes (e.g., "C:/Users/rishu/Desktop/DSA_Notes").
5. Return between 1 and 5 actions. Keep it focused and practical.

EXAMPLES:

User: "Prepare for DSA test"
[
  {"action": "open_folder", "target": "C:/Users/rishu/Desktop/DSA_Notes"},
  {"action": "open_url", "target": "https://visualgo.net"},
  {"action": "open_url", "target": "https://leetcode.com/problemset/"}
]

User: "Start working on my web project"
[
  {"action": "open_folder", "target": "C:/Users/rishu/Desktop/Projects/web-app"},
  {"action": "open_url", "target": "https://developer.mozilla.org"},
  {"action": "open_app", "target": "code"}
]
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_intent(intent: str) -> list[dict]:
    """
    Send the user's intent to Groq and return a list of action dicts.

    Each dict has the shape:  {"action": str, "target": str}

    Raises ValueError if the model response cannot be parsed.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY is not set. "
            "Create a .env file in the project root with your key."
        )

    client = Groq(api_key=api_key)

    chat = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": intent},
        ],
        temperature=0.2,       # low temp for deterministic JSON
        max_tokens=1024,
    )

    raw = chat.choices[0].message.content.strip()

    # --- Robust JSON extraction ---
    # The model *should* return bare JSON, but sometimes wraps it in
    # ```json ... ``` fences.  Handle both cases.
    fence_match = re.search(r"```(?:json)?\s*(\[.*?])\s*```", raw, re.DOTALL)
    if fence_match:
        raw = fence_match.group(1)

    try:
        tasks = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Groq returned unparseable JSON.\nRaw response:\n{raw}"
        ) from exc

    # Validate shape
    if not isinstance(tasks, list):
        raise ValueError(f"Expected a JSON array, got: {type(tasks).__name__}")

    validated: list[dict] = []
    for item in tasks:
        if not isinstance(item, dict):
            continue
        action = item.get("action", "")
        target = item.get("target", "")
        if action and target:
            validated.append({"action": action, "target": target})

    if not validated:
        raise ValueError("Groq returned an empty or invalid task list.")

    return validated
