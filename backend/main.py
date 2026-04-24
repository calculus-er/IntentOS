"""
IntentOS backend entrypoint.

Lightweight FastAPI server that receives natural-language intents from
the frontend, delegates to Groq for task planning, executes the
resulting actions on the host OS, and returns results.
Voice input via Ctrl+Space hotkey (Phase 7A).
Edith persona + memory (Phase 7B).
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.ai_engine import parse_intent
from backend.executor import execute_tasks
from backend.memory import save_interaction

# ---------------------------------------------------------------------------
# Load environment variables from .env
# ---------------------------------------------------------------------------
load_dotenv()


# ---------------------------------------------------------------------------
# Lifespan — boot voice engine before accepting requests
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.voice_listener import boot_voice_engine, start_hotkey_listener
    from backend.tts_engine import regenerate_listening_wav
    boot_voice_engine()
    regenerate_listening_wav()
    start_hotkey_listener()
    yield


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="IntentOS", version="0.6.0", lifespan=lifespan)

# Serve frontend static files at /ui
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# Allow the local frontend (served on any localhost port) to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class IntentRequest(BaseModel):
    """Payload sent by the frontend."""
    intent: str


class IntentResponse(BaseModel):
    """Payload returned to the frontend."""
    intent: str
    action_type: str
    action_payload: str
    spoken_response: str
    execution_status: str
    execution_detail: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root_redirect():
    """Redirect root to the frontend UI."""
    return RedirectResponse(url="/ui/index.html")


@app.get("/health")
async def health_check():
    """Simple liveness probe."""
    return {"status": "ok", "service": "IntentOS", "persona": "Edith"}


@app.post("/api/intent", response_model=IntentResponse)
async def process_intent(payload: IntentRequest):
    """
    Receive a natural-language intent, route it through Edith's brain,
    execute the action, save to memory, and return the result.
    """
    # --- Step 1: AI routing ---
    try:
        routed = parse_intent(payload.intent)
    except EnvironmentError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    action_type = routed["action_type"]
    action_payload = routed["action_payload"]
    spoken_response = routed["spoken_response"]

    # --- Step 2: Execution ---
    exec_status = "ok"
    exec_detail = None

    if action_type == "conversation":
        # Nothing to execute — the payload IS the answer
        exec_detail = "No OS action required."
    else:
        # Delegate to the executor
        task_for_executor = {
            "action_type": action_type,
            "action_payload": action_payload,
        }
        results = execute_tasks([task_for_executor])
        if results:
            exec_status = results[0].get("status", "error")
            exec_detail = results[0].get("detail")
            # If the executor provides dynamic speech (like live weather), override
            dynamic_speech = results[0].get("dynamic_speech")
            if dynamic_speech:
                spoken_response = dynamic_speech

    # --- Step 3: Save to memory ---
    save_interaction(payload.intent, action_type, action_payload, spoken_response)

    return IntentResponse(
        intent=payload.intent,
        action_type=action_type,
        action_payload=action_payload,
        spoken_response=spoken_response,
        execution_status=exec_status,
        execution_detail=exec_detail,
    )
