"""
OS Execution Engine for IntentOS — Phase 7C

Real native handlers for volume (pycaw), brightness (screen-brightness-control),
lock workstation (ctypes), focus mode (hosts file), and PowerShell fallback
with -ExecutionPolicy Bypass.
"""

import ctypes
import os
import platform
import subprocess
import webbrowser


# ---------------------------------------------------------------------------
# Action handlers — legacy (open_folder, open_url, open_app, run_command)
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
    if not target.startswith(("http://", "https://")):
        target = "https://" + target

    webbrowser.open(target)
    return {"action": "open_url", "target": target, "status": "ok"}


def _open_app(target: str) -> dict:
    """Launch an application by name / command."""
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["cmd", "/c", "start", "", target])
        else:
            subprocess.Popen([target])
        return {"action": "open_app", "target": target, "status": "ok"}
    except FileNotFoundError:
        return {"action": "open_app", "target": target,
                "status": "error", "detail": f"Application not found: {target}"}


def _run_command(target: str) -> dict:
    """Run an arbitrary shell command."""
    try:
        result = subprocess.run(
            target, shell=True, capture_output=True, text=True, timeout=15,
        )
        return {
            "action": "run_command", "target": target, "status": "ok",
            "detail": (result.stdout[:200] or result.stderr[:200] or "Done.").strip(),
        }
    except subprocess.TimeoutExpired:
        return {"action": "run_command", "target": target,
                "status": "error", "detail": "Command timed out (15 s)"}


# ---------------------------------------------------------------------------
# Phase 7C handlers — native OS control
# ---------------------------------------------------------------------------

def _set_volume(level: int) -> dict:
    """Set system volume using pycaw (Windows Core Audio API)."""
    try:
        from pycaw.pycaw import AudioUtilities

        speakers = AudioUtilities.GetSpeakers()
        volume = speakers.EndpointVolume

        # pycaw uses a scalar 0.0-1.0 range
        scalar = max(0.0, min(1.0, level / 100.0))
        volume.SetMasterVolumeLevelScalar(scalar, None)

        return {"action": "set_volume", "target": f"{level}%",
                "status": "ok", "detail": f"Volume set to {level}%."}
    except Exception as exc:
        return {"action": "set_volume", "target": f"{level}%",
                "status": "error", "detail": str(exc)}


def _set_brightness(level: int) -> dict:
    """Set display brightness using screen-brightness-control."""
    try:
        import screen_brightness_control as sbc
        sbc.set_brightness(max(0, min(100, level)))
        return {"action": "set_brightness", "target": f"{level}%",
                "status": "ok", "detail": f"Brightness set to {level}%."}
    except Exception as exc:
        return {"action": "set_brightness", "target": f"{level}%",
                "status": "error", "detail": str(exc)}


def _lock_workstation() -> dict:
    """Lock the Windows workstation."""
    try:
        ctypes.windll.user32.LockWorkStation()
        return {"action": "lock_workstation", "target": "lock",
                "status": "ok", "detail": "Workstation locked."}
    except Exception as exc:
        return {"action": "lock_workstation", "target": "lock",
                "status": "error", "detail": str(exc)}


# Domains to block in focus mode
_FOCUS_BLOCK_LIST = [
    "www.youtube.com", "youtube.com",
    "www.reddit.com", "reddit.com",
    "www.twitter.com", "twitter.com", "x.com",
    "www.instagram.com", "instagram.com",
    "www.facebook.com", "facebook.com",
    "www.tiktok.com", "tiktok.com",
]

_HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
_FOCUS_MARKER = "# IntentOS-Focus"


def _focus_mode(on: bool) -> dict:
    """Toggle focus mode by editing the Windows hosts file."""
    try:
        with open(_HOSTS_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if on:
            # Remove any old focus entries, then add fresh ones
            lines = [l for l in lines if _FOCUS_MARKER not in l]
            for domain in _FOCUS_BLOCK_LIST:
                lines.append(f"127.0.0.1  {domain}  {_FOCUS_MARKER}\n")
            mode_str = "ON"
        else:
            # Remove focus entries
            lines = [l for l in lines if _FOCUS_MARKER not in l]
            mode_str = "OFF"

        with open(_HOSTS_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)

        # Flush DNS cache so changes take effect immediately
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", "ipconfig /flushdns"],
            capture_output=True, timeout=5,
        )

        return {"action": "focus_mode", "target": mode_str,
                "status": "ok", "detail": f"Focus mode {mode_str}. {'Distractions blocked.' if on else 'Restrictions lifted.'}"}
    except PermissionError:
        return {"action": "focus_mode", "target": "on" if on else "off",
                "status": "error", "detail": "Permission denied. Run server as Administrator."}
    except Exception as exc:
        return {"action": "focus_mode", "target": "on" if on else "off",
                "status": "error", "detail": str(exc)}


def _run_powershell(command: str) -> dict:
    """Execute a PowerShell command with -ExecutionPolicy Bypass."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", command],
            capture_output=True, text=True, timeout=15,
        )
        output = (result.stdout[:200] or result.stderr[:200] or "Done.").strip()
        return {"action": "powershell", "target": command,
                "status": "ok", "detail": output}
    except subprocess.TimeoutExpired:
        return {"action": "powershell", "target": command,
                "status": "error", "detail": "PowerShell command timed out (15 s)"}
    except Exception as exc:
        return {"action": "powershell", "target": command,
                "status": "error", "detail": str(exc)}


# ---------------------------------------------------------------------------
# Legacy dispatcher
# ---------------------------------------------------------------------------

_HANDLERS = {
    "open_folder": _open_folder,
    "open_url":    _open_url,
    "open_app":    _open_app,
    "run_command": _run_command,
}


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------

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

        # ---- Phase 7B router format ----
        if action_type == "browser_action":
            results.append(_open_url(action_payload))
            continue

        if action_type == "os_command":
            payload = action_payload.strip()

            if payload.startswith("explorer "):
                path = payload.replace("explorer ", "", 1).strip()
                results.append(_open_folder(path))

            elif payload.startswith("set_volume:"):
                try:
                    level = int(payload.split(":")[1])
                except (IndexError, ValueError):
                    level = 50
                results.append(_set_volume(level))

            elif payload.startswith("set_brightness:"):
                try:
                    level = int(payload.split(":")[1])
                except (IndexError, ValueError):
                    level = 50
                results.append(_set_brightness(level))

            elif payload == "lock_workstation":
                results.append(_lock_workstation())

            elif payload.startswith("focus_mode:"):
                mode = payload.split(":")[1].strip().lower()
                results.append(_focus_mode(mode == "on"))

            else:
                # Heuristic: simple word = app launch, otherwise PowerShell
                if " " not in payload and not payload.startswith(("-", "/")):
                    results.append(_open_app(payload))
                else:
                    results.append(_run_powershell(payload))
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
