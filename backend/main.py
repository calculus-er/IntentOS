"""
IntentOS backend entrypoint.

Lightweight FastAPI server that receives natural-language intents from
the frontend, delegates to Groq for task planning, and returns a
structured action list.
"""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.ai_engine import parse_intent

# ---------------------------------------------------------------------------
# Load environment variables from .env
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="IntentOS", version="0.2.0")

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


class IntentResponse(BaseModel):
    """Payload returned to the frontend."""
    intent: str
    tasks: list[TaskAction]
    message: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def health_check():
    """Simple liveness probe."""
    return {"status": "ok", "service": "IntentOS"}


@app.post("/api/intent", response_model=IntentResponse)
async def process_intent(payload: IntentRequest):
    """
    Receive a natural-language intent string, send it to Groq for
    task decomposition, and return the resulting action list.
    """
    try:
        raw_tasks = parse_intent(payload.intent)
    except EnvironmentError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    tasks = [TaskAction(**t) for t in raw_tasks]

    return IntentResponse(
        intent=payload.intent,
        tasks=tasks,
        message=f"Planned {len(tasks)} action(s) for: {payload.intent}",
    )
