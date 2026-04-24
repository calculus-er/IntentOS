"""
IntentOS backend entrypoint.

Lightweight FastAPI server that receives natural-language intents from
the frontend, delegates to Groq for task planning, executes the
resulting actions on the host OS, and returns results.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.ai_engine import parse_intent
from backend.executor import execute_tasks

# ---------------------------------------------------------------------------
# Load environment variables from .env
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="IntentOS", version="0.4.0")

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


class TaskAction(BaseModel):
    """A single action the OS engine should perform."""
    action: str
    target: str


class TaskResult(BaseModel):
    """Result of executing a single task on the host OS."""
    action: str
    target: str
    status: str
    detail: str | None = None


class IntentResponse(BaseModel):
    """Payload returned to the frontend."""
    intent: str
    tasks: list[TaskAction]
    results: list[TaskResult]
    message: str


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
    return {"status": "ok", "service": "IntentOS"}


@app.post("/api/intent", response_model=IntentResponse)
async def process_intent(payload: IntentRequest):
    """
    Receive a natural-language intent string, send it to Groq for
    task decomposition, execute the actions on the host OS, and
    return the results.
    """
    # --- Step 1: AI planning ---
    try:
        raw_tasks = parse_intent(payload.intent)
    except EnvironmentError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    tasks = [TaskAction(**t) for t in raw_tasks]

    # --- Step 2: OS execution ---
    raw_results = execute_tasks(raw_tasks)
    results = [TaskResult(**r) for r in raw_results]

    ok_count = sum(1 for r in results if r.status == "ok")

    return IntentResponse(
        intent=payload.intent,
        tasks=tasks,
        results=results,
        message=f"Executed {ok_count}/{len(tasks)} action(s) for: {payload.intent}",
    )
