"""
OS Execution Engine for IntentOS — Phase 7C + Phase 8

Real native handlers for volume (pycaw), brightness (screen-brightness-control),
lock workstation (ctypes), focus mode (hosts file), PowerShell fallback,
and smart_file_open (fuzzy file match + default app).
"""

import ctypes
import difflib
import json
import os
import platform
import subprocess
import urllib.parse
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
    "www.youtube.com", "youtube.com", "m.youtube.com", "youtu.be",
    "www.reddit.com", "reddit.com", "old.reddit.com",
    "www.twitter.com", "twitter.com", "x.com", "mobile.twitter.com",
    "www.instagram.com", "instagram.com",
    "www.facebook.com", "facebook.com", "m.facebook.com",
    "www.tiktok.com", "tiktok.com",
    "www.netflix.com", "netflix.com",
    "www.twitch.tv", "twitch.tv"
]

_HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
_FOCUS_MARKER = "# IntentOS-Focus"


def _focus_mode(on: bool) -> dict:
    """Toggle focus mode by editing the Windows hosts file via elevated PowerShell."""
    import tempfile
    import time as _time

    try:
        marker = _FOCUS_MARKER
        hosts = _HOSTS_PATH
        tmp = tempfile.gettempdir()
        log_path = os.path.join(tmp, "intentos_focus.log")

        # Build the PowerShell script content with error logging
        if on:
            add_cmds = "\n".join(
                f'Add-Content -Path $h -Value "127.0.0.1  {d}  {marker}"'
                for d in _FOCUS_BLOCK_LIST
            )
            core = (
                f'$content = Get-Content $h | Where-Object {{ $_ -notmatch [regex]::Escape("{marker}") }}\n'
                f'Set-Content -Path $h -Value $content -Force\n'
                f'{add_cmds}\n'
                f'ipconfig /flushdns | Out-Null\n'
            )
            mode_str = "ON"
        else:
            core = (
                f'$content = Get-Content $h | Where-Object {{ $_ -notmatch [regex]::Escape("{marker}") }}\n'
                f'Set-Content -Path $h -Value $content -Force\n'
                f'ipconfig /flushdns | Out-Null\n'
            )
            mode_str = "OFF"

        script = (
            f'$h = "{hosts}"\n'
            f'$log = "{log_path}"\n'
            f'try {{\n'
            f'{core}'
            f'"SUCCESS" | Out-File $log -Force\n'
            f'}} catch {{\n'
            f'$_.Exception.Message | Out-File $log -Force\n'
            f'}}\n'
        )

        # Write temp .ps1 script
        script_path = os.path.join(tmp, "intentos_focus.ps1")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)

        # Remove old log
        if os.path.exists(log_path):
            os.unlink(log_path)

        # Check if already admin
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()

        if is_admin:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", script_path],
                capture_output=True, text=True, timeout=15,
            )
        else:
            # ShellExecuteW with "runas" — SW_SHOWNORMAL=1 so user sees UAC
            ret = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "powershell.exe",
                f'-NoProfile -ExecutionPolicy Bypass -File "{script_path}"',
                None, 1  # SW_SHOWNORMAL
            )
            if ret <= 32:
                return {"action": "focus_mode", "target": mode_str,
                        "status": "error",
                        "detail": f"UAC elevation failed (code {ret}). Click Yes on the admin prompt."}
            # Wait for elevated process
            _time.sleep(5)

        # Check log for result
        if os.path.exists(log_path):
            with open(log_path, "r") as lf:
                log_content = lf.read().strip()
            if "SUCCESS" in log_content:
                return {"action": "focus_mode", "target": mode_str,
                        "status": "ok",
                        "detail": f"Focus mode {mode_str}. {'Distractions blocked.' if on else 'Restrictions lifted.'}"}
            else:
                return {"action": "focus_mode", "target": mode_str,
                        "status": "error", "detail": f"Script error: {log_content[:200]}"}
        else:
            return {"action": "focus_mode", "target": mode_str,
                    "status": "error",
                    "detail": "Elevated script did not run. Did you click Yes on the UAC prompt?"}

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


def _smart_file_open(payload) -> dict:
    """
    Fuzzy-pick the best file in folder_path matching search_keyword; open with
    the OS default application. Failures are non-fatal (status ok, short detail).
    """
    try:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return {
                    "action": "smart_file_open",
                    "target": "",
                    "status": "ok",
                    "detail": "Invalid smart_file_open payload (skipped).",
                }

        if not isinstance(payload, dict):
            return {
                "action": "smart_file_open",
                "target": "",
                "status": "ok",
                "detail": "Invalid payload type (skipped).",
            }

        folder_path = os.path.normpath(str(payload.get("folder_path", "")).strip())
        keyword = str(payload.get("search_keyword", "")).strip()

        if not folder_path or not keyword:
            return {
                "action": "smart_file_open",
                "target": folder_path or "(no path)",
                "status": "ok",
                "detail": "Missing folder_path or search_keyword (skipped).",
            }

        if not os.path.isdir(folder_path):
            return {
                "action": "smart_file_open",
                "target": folder_path,
                "status": "ok",
                "detail": "Folder not found (skipped).",
            }

        try:
            filenames = [
                f
                for f in os.listdir(folder_path)
                if os.path.isfile(os.path.join(folder_path, f))
            ]
        except OSError:
            return {
                "action": "smart_file_open",
                "target": folder_path,
                "status": "ok",
                "detail": "Could not read folder (skipped).",
            }

        if not filenames:
            return {
                "action": "smart_file_open",
                "target": folder_path,
                "status": "ok",
                "detail": "No files in folder (skipped).",
            }

        stems = [os.path.splitext(f)[0] for f in filenames]
        best = None
        close = difflib.get_close_matches(keyword, filenames, n=1, cutoff=0.28)
        if close:
            best = close[0]
        else:
            stem_matches = difflib.get_close_matches(keyword, stems, n=1, cutoff=0.32)
            if stem_matches:
                stem_hit = stem_matches[0]
                best = next(
                    (f for f in filenames if os.path.splitext(f)[0] == stem_hit),
                    None,
                )

        if best is None:
            kw_l = keyword.lower()
            best_ratio = 0.0
            best_name = None
            for f in filenames:
                stem = os.path.splitext(f)[0].replace("_", " ")
                ratio = max(
                    difflib.SequenceMatcher(None, kw_l, f.lower()).ratio(),
                    difflib.SequenceMatcher(None, kw_l, stem.lower()).ratio(),
                )
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_name = f
            if best_name is None or best_ratio < 0.28:
                return {
                    "action": "smart_file_open",
                    "target": folder_path,
                    "status": "ok",
                    "detail": "No matching file (skipped).",
                }
            best = best_name

        filepath = os.path.join(folder_path, best)
        system = platform.system()
        if system == "Windows":
            os.startfile(filepath)  # noqa: S606
        elif system == "Darwin":
            subprocess.Popen(["open", filepath])
        else:
            subprocess.Popen(["xdg-open", filepath])

        return {
            "action": "smart_file_open",
            "target": filepath,
            "status": "ok",
            "detail": f"Opened: {best}",
        }
    except Exception:
        return {
            "action": "smart_file_open",
            "target": "",
            "status": "ok",
            "detail": "smart_file_open failed (skipped).",
        }


def _fetch_weather() -> dict:
    """
    Phase 8 — Smart Weather Integration.
    1. IP lookup for city  2. wttr.in for live weather
    3. Construct Edith persona TTS  4. Open visual forecast
    """
    import urllib.request
    import json as _json

    fallback_spoken = "I am unable to reach the meteorological servers at this moment, sir."

    try:
        # Step 1: Dynamic location via IP
        loc_req = urllib.request.urlopen("http://ip-api.com/json/", timeout=5)
        loc_data = _json.loads(loc_req.read())
        city = loc_data.get("city", "")
        if not city:
            return {
                "action": "api_weather", "target": "weather",
                "status": "error", "detail": "Could not determine your city.",
                "spoken_response": fallback_spoken,
            }

        # Step 2: Fetch live weather from wttr.in
        weather_url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
        weather_req = urllib.request.urlopen(weather_url, timeout=5)
        weather_data = _json.loads(weather_req.read())

        current = weather_data.get("current_condition", [{}])[0]
        temp_c = current.get("FeelsLikeC", current.get("temp_C", "?"))
        condition_list = current.get("weatherDesc", [{}])
        condition = condition_list[0].get("value", "unknown") if condition_list else "unknown"

        # Short and crisp — no city name, no extras
        spoken = f"It is currently {temp_c} degrees and {condition.lower()}, sir."

        # Step 4: Open visual weather widget
        webbrowser.open(f"https://www.google.com/search?q=weather+in+{urllib.parse.quote(city)}")

        return {
            "action": "api_weather",
            "target": f"weather in {city}",
            "status": "ok",
            "detail": f"{city}: {temp_c}C, {condition}",
            "spoken_response": spoken,
        }

    except Exception as exc:
        return {
            "action": "api_weather",
            "target": "weather",
            "status": "error",
            "detail": str(exc),
            "spoken_response": fallback_spoken,
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

        if action_type == "smart_file_open":
            results.append(_smart_file_open(action_payload))
            continue

        if action_type == "conversation":
            text = action_payload if isinstance(action_payload, str) else str(action_payload)
            results.append(
                {
                    "action": "conversation",
                    "target": text[:500],
                    "status": "ok",
                    "detail": "No OS action required.",
                }
            )
            continue

        if action_type == "youtube_play":
            results.append(_play_youtube(action_payload))
            continue

        if action_type == "google_search":
            results.append(_search_google(action_payload))
            continue

        if action_type == "api_weather":
            results.append(_fetch_weather())
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
