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

    Each result dict echoes the original action/target and adds a
    "status" key ("ok" or "error") plus optional detail.
    """
    results: list[dict] = []

    for task in tasks:
        action = task.get("action", "")
        target = task.get("target", "")
        handler = _HANDLERS.get(action)

        if handler is None:
            results.append({
                "action": action, "target": target,
                "status": "error", "detail": f"Unknown action: {action}",
            })
            continue

        results.append(handler(target))

    return results
