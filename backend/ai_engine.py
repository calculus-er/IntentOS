"""
AI Engine — Phase 8: Multi-Action Orchestration & Smart File Router

Edith persona. The LLM returns a JSON object with:
  actions: list of { "action_type", "action_payload" }
  spoken_response: single line for TTS after all actions run

action_payload is a string for most types; for smart_file_open it must be an
object: { "folder_path": "...", "search_keyword": "..." }.
"""

import json
import os
import re

from groq import Groq

from backend.memory import load_history

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "llama-3.3-70b-versatile"

ALLOWED_ACTION_TYPES = frozenset(
    {
        "os_command",
        "browser_action",
        "conversation",
        "youtube_play",
        "google_search",
        "api_weather",
        "smart_file_open",
    }
)


def _extract_json_object(text: str) -> str:
    """Take raw LLM output and return the outermost balanced JSON object."""
    text = text.strip()
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]


def _build_system_prompt() -> str:
    """Build the Edith system prompt with memory context."""
    notes_path = os.getenv(
        "NOTES_FOLDER_PATH",
        "./mock_system_files/DSA_Notes",
    ).replace("\\", "/")

    history = load_history()
    memory_block = ""
    if history:
        lines = []
        for h in history:
            lines.append(
                f'  User: "{h["intent"]}" -> {h["action_type"]}: '
                f'{str(h["action_payload"])[:160]}'
            )
        memory_block = (
            "\n\nRECENT MEMORY (last interactions):\n" + "\n".join(lines) + "\n"
        )

    return f"""You are Edith, an ultra-competent AI assistant modeled after J.A.R.V.I.S. from Iron Man.
You operate IntentOS, a local operating system automation layer on a Windows machine.
The user's name is Rishit. Address him as "Rishit" or "Sir".

PERSONALITY:
- Tone: Crisp, formal, highly efficient. British-style dry wit when appropriate.
- Length: Extremely brief. Confirm and get out of the way. No filler.
- You are supremely capable and never flustered.

YOUR TASK:
Given the user's natural-language intent, return ONE JSON object with exactly two keys:

{{
  "actions": [ ... ],
  "spoken_response": "<what you say aloud after all actions are queued>"
}}

The "actions" value is a JSON ARRAY. Each element MUST be an object with exactly:
  "action_type": one of the allowed types below
  "action_payload": a string OR (only for smart_file_open) an object — see below

ALLOWED action_type VALUES:
- os_command
- browser_action
- conversation
- youtube_play
- google_search
- api_weather
- smart_file_open

ROUTING — use MULTIPLE actions when the user clearly wants several things at once
(e.g. open several study sites AND open the best-matching note file in a folder).

TYPE os_command:
  Local machine: volume, brightness, lock, folders, apps, focus mode, PowerShell.
  action_payload = string command (same rules as before).
  Folder: "explorer <path>"
  Volume: "set_volume:<0-100>"
  Brightness: "set_brightness:<0-100>"
  Lock: "lock_workstation"
  Focus: "focus_mode:on" / "focus_mode:off"
  Other: PowerShell string.

TYPE browser_action:
  Open a specific known site by URL. action_payload = full https URL string.
  NOT for generic search (use google_search). NOT for YouTube play (use youtube_play).

TYPE google_search:
  action_payload = raw search query string.

TYPE youtube_play:
  action_payload = natural-language video request (verbatim).

TYPE api_weather:
  action_payload = "" (empty string). Backend fills data.

TYPE conversation:
  No OS side effects for that slot. action_payload = your concise text answer.
  Use alone in "actions" when no automation is needed.

TYPE smart_file_open:
  Opens ONE file inside a folder using fuzzy filename matching (no LLM on disk).
  action_payload MUST be a JSON object (not a string) with exactly:
    "folder_path": absolute or relative path to the directory
    "search_keyword": short phrase describing the desired file (e.g. "DSA introduction")
  The backend picks the closest matching FILE name and opens it with the default app.
  Use the user's notes folder when relevant: "{notes_path}"
  You may combine smart_file_open with browser_action entries in the same array.

CRITICAL RULES:
1. Return ONLY the JSON object. No markdown, no code fences, no extra text.
2. "spoken_response" must always be a non-empty string (under 2 sentences).
3. Order "actions" in a sensible sequence (e.g. files before or after URLs — your choice).
4. Prefer several focused actions over one vague os_command when the user asks for multiple outcomes.
5. For api_weather-only requests, use a single action with action_type api_weather and action_payload "".
   Set spoken_response to a brief acknowledgement anyway (the backend may refine wording).

RESPONSE EXAMPLES:

User: "Prepare for DSA test"
{{
  "actions": [
    {{"action_type": "browser_action", "action_payload": "https://leetcode.com/problemset/all/"}},
    {{"action_type": "browser_action", "action_payload": "https://www.geeksforgeeks.org/data-structures/"}},
    {{"action_type": "smart_file_open", "action_payload": {{"folder_path": "{notes_path}", "search_keyword": "arrays trees"}}}}
  ],
  "spoken_response": "Practice platforms and your notes are open, sir. Good hunting."
}}

User: "Set volume to 30 percent"
{{
  "actions": [{{"action_type": "os_command", "action_payload": "set_volume:30"}}],
  "spoken_response": "Volume calibrated to your specifications, sir."
}}

User: "What's the weather?"
{{
  "actions": [{{"action_type": "api_weather", "action_payload": ""}}],
  "spoken_response": "Pulling live conditions now, sir."
}}

User: "What is the derivative of x squared?"
{{
  "actions": [{{"action_type": "conversation", "action_payload": "The derivative of x^2 is 2x by the power rule."}}],
  "spoken_response": "Two x, Rishit. Elementary, but correct."
}}

User: "Open LeetCode and my arrays notes"
{{
  "actions": [
    {{"action_type": "browser_action", "action_payload": "https://leetcode.com/problemset/"}},
    {{"action_type": "smart_file_open", "action_payload": {{"folder_path": "{notes_path}", "search_keyword": "arrays"}}}}
  ],
  "spoken_response": "LeetCode and your arrays note are open, sir."
}}
{memory_block}"""


def _normalize_router_payload(data: dict) -> dict:
    """Convert legacy single-action shape to Phase 8 multi-action shape."""
    if "actions" in data and isinstance(data.get("actions"), list):
        return data
    if "action_type" in data:
        return {
            "actions": [
                {
                    "action_type": data["action_type"],
                    "action_payload": data.get("action_payload", ""),
                }
            ],
            "spoken_response": data.get("spoken_response", "Done, sir."),
        }
    raise ValueError("JSON must include 'actions' array or legacy 'action_type'.")


def _validate_actions(actions: list) -> None:
    if not isinstance(actions, list) or len(actions) == 0:
        raise ValueError("'actions' must be a non-empty array.")

    for i, item in enumerate(actions):
        if not isinstance(item, dict):
            raise ValueError(f"actions[{i}] must be an object.")
        at = item.get("action_type", "")
        if at not in ALLOWED_ACTION_TYPES:
            raise ValueError(f"Unknown action_type at actions[{i}]: {at}")
        ap = item.get("action_payload", None)

        if at == "smart_file_open":
            if isinstance(ap, str):
                try:
                    ap = json.loads(ap)
                    item["action_payload"] = ap
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"smart_file_open at actions[{i}] needs object or JSON string."
                    ) from exc
            if not isinstance(ap, dict):
                raise ValueError(
                    f"smart_file_open at actions[{i}] requires an object payload."
                )
            fp = str(ap.get("folder_path", "")).strip()
            sk = str(ap.get("search_keyword", "")).strip()
            if not fp or not sk:
                raise ValueError(
                    f"smart_file_open at actions[{i}] needs folder_path and search_keyword."
                )
            continue

        if at == "api_weather":
            if ap is None or ap == "":
                item["action_payload"] = ""
            elif isinstance(ap, str):
                item["action_payload"] = ap
            else:
                raise ValueError("api_weather action_payload must be a string (use '').")
            continue

        if at == "conversation":
            if not isinstance(ap, str) or not ap.strip():
                raise ValueError("conversation requires non-empty string action_payload.")
            continue

        if not isinstance(ap, str) or not ap.strip():
            raise ValueError(
                f"actions[{i}] ({at}) requires a non-empty string action_payload."
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_intent(intent: str) -> dict:
    """
    Send the user's intent to Groq and return orchestration dict:

    Returns:
      {
        "actions": [ {"action_type": str, "action_payload": str|dict}, ... ],
        "spoken_response": str,
      }
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
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": intent},
        ],
        temperature=0.2,
        max_tokens=1024,
    )

    raw = chat.choices[0].message.content.strip()

    fence_match = re.search(r"```(?:json)?\s*(\{.*)", raw, re.DOTALL)
    if fence_match:
        raw = fence_match.group(1)
        if "```" in raw:
            raw = raw.split("```", 1)[0]

    raw = _extract_json_object(raw)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Groq returned unparseable JSON.\nRaw response:\n{raw}") from exc

    if not isinstance(result, dict):
        raise ValueError(f"Expected a JSON object, got: {type(result).__name__}")

    result = _normalize_router_payload(result)
    actions = result.get("actions", [])
    spoken_response = result.get("spoken_response", "").strip()

    _validate_actions(actions)

    if not spoken_response:
        spoken_response = "Done, sir."

    return {
        "actions": actions,
        "spoken_response": spoken_response,
    }
