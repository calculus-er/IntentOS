"""
IntentOS backend entrypoint.

Lightweight FastAPI server that receives natural-language intents from
the frontend, delegates to Groq for task planning, executes the
resulting actions on the host OS, and returns results.
Voice input via Ctrl+Space hotkey (Phase 7A).
Edith persona + memory (Phase 7B).
Multi-action orchestration (Phase 8).
"""

import ctypes
import json
import platform
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
from backend.tts_engine import speak_async

# ---------------------------------------------------------------------------
# Load environment variables from .env
# ---------------------------------------------------------------------------
load_dotenv()


# ---------------------------------------------------------------------------
# Lifespan — boot voice engine before accepting requests
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    if platform.system() == "Windows":
        try:
            if ctypes.windll.shell32.IsUserAnAdmin():
                print(
                    "[IntentOS] Process is elevated — hosts writes should succeed "
                    "(hosts read-only flag is cleared automatically). If blocked sites still load "
                    "in Chrome/Edge, turn off Settings → Privacy → Use secure DNS."
                )
            else:
                print(
                    "[IntentOS] WARNING: Not running as Administrator. "
                    "Lock-In hosts blocking requires elevation; volume and Focus Assist "
                    "registry changes may still apply. Run uvicorn from an elevated Command Prompt."
                )
        except Exception:
            pass

    from backend.voice_listener import boot_voice_engine, start_hotkey_listener
    from backend.tts_engine import regenerate_listening_wav, warmup

    boot_voice_engine()
    regenerate_listening_wav()
    warmup()
    start_hotkey_listener()
    yield


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="IntentOS", version="0.9.0", lifespan=lifespan)

# Serve frontend static files at /ui
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# Allow the local frontend (served on any localhost port) to call us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
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


def _payload_to_str(payload) -> str:
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, ensure_ascii=False)
    return str(payload)


class ActionResultItem(BaseModel):
    """One executed action from the orchestration array."""
    action_type: str
    action_payload: str
    execution_status: str
    execution_detail: str | None = None


class IntentResponse(BaseModel):
    """Payload returned to the frontend (Phase 8 + legacy fields)."""
    intent: str
    spoken_response: str
    execution_status: str
    execution_detail: str | None = None
    actions: list[ActionResultItem]
    # Legacy single-action shape for older UI layers
    action_type: str
    action_payload: str


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
    return {"status": "ok", "service": "IntentOS", "persona": "Edith", "phase": "multi-action"}


@app.post("/api/intent", response_model=IntentResponse)
async def process_intent(payload: IntentRequest):
    """
    Receive a natural-language intent, route through Edith (Groq),
    execute all actions in order, persist memory, speak confirmation, return results.
    """
    try:
        routed = parse_intent(payload.intent)
    except EnvironmentError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    actions = routed["actions"]
    spoken_response = routed["spoken_response"]

    # Build executor tasks (copy so executor cannot mutate router output oddly)
    exec_tasks: list[dict] = []
    for a in actions:
        exec_tasks.append(
            {
                "action_type": a["action_type"],
                "action_payload": a.get("action_payload", ""),
            }
        )

    results = execute_tasks(exec_tasks)

    # Single api_weather: allow executor to override spoken line (live telemetry)
    if (
        len(actions) == 1
        and actions[0]["action_type"] == "api_weather"
        and results
        and results[0].get("spoken_response")
    ):
        spoken_response = results[0]["spoken_response"]

    statuses = [r.get("status", "error") for r in results]
    if not statuses:
        exec_status = "ok"
    elif all(s == "ok" for s in statuses):
        exec_status = "ok"
    elif any(s == "ok" for s in statuses):
        exec_status = "partial"
    else:
        exec_status = "error"

    err_details = [
        r.get("detail", "")
        for r in results
        if r.get("status") != "ok" and r.get("detail")
    ]
    exec_detail = " | ".join(d for d in err_details if d)[:600] or None
    if exec_status == "partial" and not exec_detail:
        exec_detail = "Some steps completed; see per-action rows."

    action_rows: list[ActionResultItem] = []
    for i, act in enumerate(actions):
        res = results[i] if i < len(results) else {"status": "error", "detail": "No executor result"}
        st = res.get("status", "error")
        action_rows.append(
            ActionResultItem(
                action_type=act["action_type"],
                action_payload=_payload_to_str(act.get("action_payload", "")),
                execution_status=st,
                execution_detail=res.get("detail"),
            )
        )

    # Memory: compact summary
    summary_types = "+".join(a["action_type"] for a in actions)
    summary_payload = json.dumps(
        [
            {"action_type": a["action_type"], "action_payload": a.get("action_payload")}
            for a in actions
        ],
        ensure_ascii=False,
    )[:1800]
    save_interaction(payload.intent, summary_types, summary_payload, spoken_response)

    # Edith speaks after actions are launched (non-blocking)
    speak_async(spoken_response)

    if len(actions) == 1:
        legacy_type = actions[0]["action_type"]
        legacy_payload = _payload_to_str(actions[0].get("action_payload", ""))
    else:
        legacy_type = "multi"
        legacy_payload = f"{len(actions)} actions"

    return IntentResponse(
        intent=payload.intent,
        spoken_response=spoken_response,
        execution_status=exec_status,
        execution_detail=exec_detail,
        actions=action_rows,
        action_type=legacy_type,
        action_payload=legacy_payload,
    )
