"""
IntentOS backend entrypoint.

Lightweight FastAPI server that receives natural-language intents from
the frontend and (in later phases) delegates to Groq for task planning
and to OS helpers for execution.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="IntentOS", version="0.1.0")

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
    Receive a natural-language intent string, break it into tasks, and
    return the task list.  Groq integration is wired in Phase 3; for now
    we return a hard-coded stub so the endpoint contract is testable.
    """
    stub_tasks = [
        TaskAction(action="open_folder", target="C:/Users/rishu/Desktop/DSA_Notes"),
        TaskAction(action="open_url", target="https://visualgo.net"),
    ]

    return IntentResponse(
        intent=payload.intent,
        tasks=stub_tasks,
        message=f"Planned {len(stub_tasks)} action(s) for: {payload.intent}",
    )
