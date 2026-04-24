"""
Memory Manager — Phase 7B

Maintains a rolling conversation history in memory.json so the LLM has
context of recent interactions.  Keeps the last N exchanges to stay
within token budgets while preserving continuity.
"""

import json
from pathlib import Path

MEMORY_FILE = Path(__file__).resolve().parent.parent / "memory.json"
MAX_HISTORY = 5


def load_history() -> list[dict]:
    """Return the last MAX_HISTORY interactions from disk."""
    if not MEMORY_FILE.exists():
        return []
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data[-MAX_HISTORY:]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_interaction(
    intent: str,
    action_type: str,
    action_payload: str,
    spoken_response: str,
) -> None:
    """Append a new interaction and trim to MAX_HISTORY."""
    history = load_history()
    history.append({
        "intent": intent,
        "action_type": action_type,
        "action_payload": action_payload,
        "spoken_response": spoken_response,
    })
    # Keep only the most recent entries
    history = history[-MAX_HISTORY:]
    MEMORY_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
