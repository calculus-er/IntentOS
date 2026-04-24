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


def _play_youtube(request: str) -> dict:
    """Resolve a natural-language video request and open the exact YouTube URL."""
    try:
        from backend.youtube_resolver import resolve_video
        resolved = resolve_video(request)
        video_url = resolved.get("video_url")
        title = resolved.get("title") or "Unknown"
        channel = resolved.get("channel") or "Unknown"

        if video_url:
            webbrowser.open(video_url)
            return {
                "action": "youtube_play",
                "target": video_url,
                "status": "ok",
                "detail": f"Now playing: \"{title}\" by {channel}",
            }
        else:
            # Fallback: open YouTube search
            import urllib.parse
            search_url = (
                "https://www.youtube.com/results?search_query="
                + urllib.parse.quote_plus(request)
            )
            webbrowser.open(search_url)
            return {
                "action": "youtube_play",
                "target": search_url,
                "status": "ok",
                "detail": f"Exact video not found - opened YouTube search for: {request}",
            }
    except Exception as exc:
        return {
            "action": "youtube_play",
            "target": request,
            "status": "error",
            "detail": str(exc),
        }


def _search_google(query: str) -> dict:
    """Classify the search query and open deep site or basic Google search."""
    try:
        from backend.google_resolver import resolve_search
        resolved = resolve_search(query)
        url = resolved.get("url", "https://www.google.com/search?q=" + query)
        search_type = resolved.get("search_type", "basic")
        reason = resolved.get("reason", "")

        webbrowser.open(url)
        label = "Deep search" if search_type == "deep" else "Basic search"
        return {
            "action": "google_search",
            "target": url,
            "status": "ok",
            "detail": f"{label}: {reason}",
        }
    except Exception as exc:
        return {
            "action": "google_search",
            "target": query,
            "status": "error",
            "detail": str(exc),
        }


def _check_weather(query: str) -> dict:
    """Open browser immediately, fetch accurate weather via Open-Meteo, speak within 2s."""
    import urllib.request
    import urllib.parse
    import json as _json
    import threading

    try:
        from backend.weather_handler import handle_weather
        resolved = handle_weather(query)

        if resolved.get("action_type") == "not_weather":
            fallback_url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
            threading.Thread(target=webbrowser.open, args=(fallback_url,), daemon=True).start()
            return {"action": "weather_check", "target": fallback_url, "status": "ok", "detail": "Routed to Google search."}

        city = resolved.get("city") or ""
        url = resolved.get("google_weather_url", "https://www.google.com/search?q=weather+near+me")

        # ── Step 1: Open browser immediately ──
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()

        # ── Step 2: Resolve highly accurate location ──
        display_city = city
        if not city:
            # IP-based location (extremely accurate for Indian cities like BLR)
            try:
                req = urllib.request.Request("http://ip-api.com/json/", headers={"User-Agent": "curl"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = _json.loads(resp.read().decode())
                    display_city = data.get("city", "your location")
            except Exception:
                display_city = "your location"

        # ── Step 3: Fetch exact weather via Open-Meteo ──
        spoken = f"Weather for {display_city} is on screen, sir."
        try:
            search_city = city if city else display_city
            if search_city and search_city != "your location":
                # Geocode
                geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote_plus(search_city)}&count=1&format=json"
                req = urllib.request.Request(geo_url, headers={"User-Agent": "curl"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    geo_data = _json.loads(resp.read().decode())
                    if geo_data.get("results"):
                        lat = geo_data["results"][0]["latitude"]
                        lon = geo_data["results"][0]["longitude"]
                        display_city = geo_data["results"][0]["name"]  # Updates "blr" to "Bengaluru"

                        # Fetch weather
                        w_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code"
                        w_req = urllib.request.Request(w_url, headers={"User-Agent": "curl"})
                        with urllib.request.urlopen(w_req, timeout=1.5) as w_resp:
                            w_data = _json.loads(w_resp.read().decode())
                            temp = round(w_data["current"]["temperature_2m"])
                            code = w_data["current"]["weather_code"]

                            wmo_map = {
                                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                                45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
                                61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain", 71: "Slight snow", 75: "Heavy snow",
                                80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
                                95: "Thunderstorm"
                            }
                            condition = wmo_map.get(code, "Clear")
                            spoken = f"{condition}, {temp} degrees in {display_city}, sir."
        except Exception as e:
            print(f"[WeatherHandler] Open-Meteo fetch failed: {e}")

        return {
            "action": "weather_check",
            "target": url,
            "status": "ok",
            "detail": f"Weather for {display_city} opened.",
            "dynamic_speech": spoken,
        }

    except Exception as exc:
        return {
            "action": "weather_check",
            "target": query,
            "status": "error",
            "detail": str(exc),
        }

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

        if action_type == "youtube_play":
            results.append(_play_youtube(action_payload))
            continue

        if action_type == "google_search":
            results.append(_search_google(action_payload))
            continue

        if action_type == "weather_check":
            results.append(_check_weather(action_payload))
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
