"""
OS Execution Engine for IntentOS.

Maps parsed action dicts to real OS-level operations using Python's
native subprocess, webbrowser, and os modules.
"""

import os
import platform
import subprocess
import webbrowser


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _open_folder(target: str) -> dict:
    """Open a folder in the system's default file explorer."""
    path = os.path.normpath(target)

    if not os.path.isdir(path):
        return {"action": "open_folder", "target": target,
                "status": "error", "detail": f"Directory not found: {path}"}

    system = platform.system()
    if system == "Windows":
        subprocess.Popen(["explorer", path])
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:  # Linux and others
        subprocess.Popen(["xdg-open", path])

    return {"action": "open_folder", "target": path, "status": "ok"}


def _open_url(target: str) -> dict:
    """Open a URL in the default browser."""
    # Ensure the target looks like a URL
    if not target.startswith(("http://", "https://")):
        target = "https://" + target

    webbrowser.open(target)
    return {"action": "open_url", "target": target, "status": "ok"}


def _open_app(target: str) -> dict:
    """Launch an application by name / command."""
    try:
        # On Windows, use 'start'; on others, try direct invocation.
        if platform.system() == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "", target])
        else:
            subprocess.Popen([target])
        return {"action": "open_app", "target": target, "status": "ok"}
    except FileNotFoundError:
        return {"action": "open_app", "target": target,
                "status": "error", "detail": f"Application not found: {target}"}


def _run_command(target: str) -> dict:
    """Run an arbitrary shell command (use with caution)."""
    try:
        result = subprocess.run(
            target, shell=True, capture_output=True, text=True, timeout=15,
        )
        return {
            "action": "run_command", "target": target, "status": "ok",
            "stdout": result.stdout[:500],
            "stderr": result.stderr[:500],
        }
    except subprocess.TimeoutExpired:
        return {"action": "run_command", "target": target,
                "status": "error", "detail": "Command timed out (15 s)"}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    "open_folder": _open_folder,
    "open_url":    _open_url,
    "open_app":    _open_app,
    "run_command": _run_command,
}


def execute_tasks(tasks: list[dict]) -> list[dict]:
    """
    Execute a list of action dicts and return a results list.

    Supports two formats:
    - New (Phase 7B): {"action_type": ..., "action_payload": ...}
    - Legacy:         {"action": ..., "target": ...}
    """
    results: list[dict] = []

    for task in tasks:
        action_type = task.get("action_type", "")
        action_payload = task.get("action_payload", "")

        # ---- New Phase 7B router format ----
        if action_type == "browser_action":
            results.append(_open_url(action_payload))
            continue

        if action_type == "os_command":
            # Parse structured os_command payloads
            payload = action_payload.strip()

            if payload.startswith("explorer "):
                path = payload.replace("explorer ", "", 1).strip()
                results.append(_open_folder(path))
            elif payload.startswith("set_volume:"):
                # Placeholder — Phase 7C will implement pycaw
                results.append({"action": "set_volume", "target": payload,
                                "status": "ok", "detail": "Volume handler pending (Phase 7C)."})
            elif payload.startswith("set_brightness:"):
                results.append({"action": "set_brightness", "target": payload,
                                "status": "ok", "detail": "Brightness handler pending (Phase 7C)."})
            elif payload == "lock_workstation":
                results.append({"action": "lock_workstation", "target": payload,
                                "status": "ok", "detail": "Lock handler pending (Phase 7C)."})
            elif payload.startswith("focus_mode:"):
                results.append({"action": "focus_mode", "target": payload,
                                "status": "ok", "detail": "Focus mode handler pending (Phase 7C)."})
            else:
                # Treat as app launch or shell command
                # Check if it looks like a simple app name (no spaces, no flags)
                if " " not in payload and not payload.startswith(("-", "/")):
                    results.append(_open_app(payload))
                else:
                    results.append(_run_command(payload))
            continue

        # ---- Legacy format fallback ----
        action = task.get("action", "")
        target = task.get("target", "")
        handler = _HANDLERS.get(action)

        if handler is None:
            results.append({
                "action": action or action_type, "target": target or action_payload,
                "status": "error", "detail": f"Unknown action: {action or action_type}",
            })
            continue

        results.append(handler(target))

    return results
