"""
Load IntentOS `/.env` from the repository root (parent of /backend), before GROQ or other keys
are read. Import this as the first backend import in any entrypoint.

Uses override=True so values in .env win over empty placeholder variables in the shell.
"""

from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
_ENV = _ROOT / ".env"
if _ENV.is_file():
    load_dotenv(_ENV, override=True)
else:
    # Fallback: current working directory (legacy)
    load_dotenv(override=True)
