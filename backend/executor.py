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
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse
import webbrowser

import screen_brightness_control as sbc


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


def _effective_hosts_path() -> str:
    """
    Path to the real hosts file on disk.

    32-bit Python on 64-bit Windows redirects ``System32`` to ``SysWOW64``;
    use ``Sysnative`` so edits apply to the same file the OS resolver uses.
    """
    if platform.system() != "Windows":
        return _HOSTS_PATH
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    if sys.maxsize <= 2**32:
        sysnative = os.path.join(windir, "Sysnative", "drivers", "etc", "hosts")
        if os.path.isfile(sysnative):
            return sysnative
    return os.path.join(windir, "System32", "drivers", "etc", "hosts")


def _ensure_hosts_writable(path: str) -> None:
    """Clear read-only attribute; hosts is often +R which blocks writes even as Admin."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass
    try:
        FILE_ATTRIBUTE_READONLY = 0x00000001
        INVALID = 0xFFFFFFFF
        attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
        if attrs != INVALID and (attrs & FILE_ATTRIBUTE_READONLY):
            ctypes.windll.kernel32.SetFileAttributesW(path, attrs & ~FILE_ATTRIBUTE_READONLY)
    except Exception:
        pass


def _lockin_hosts_write(lines: list[str]) -> None:
    """Write hosts via temp file + replace (same volume). Clears read-only first."""
    path = _effective_hosts_path()
    _ensure_hosts_writable(path)
    host_dir = os.path.dirname(path)
    tmp_path: str | None = None
    try:
        try:
            fd, tmp_path = tempfile.mkstemp(prefix="intentos_hosts_", suffix=".tmp", dir=host_dir)
        except OSError:
            fd, tmp_path = tempfile.mkstemp(prefix="intentos_hosts_", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.writelines(lines)
        tmp_abs = os.path.abspath(tmp_path)
        try:
            os.replace(tmp_abs, path)
            tmp_path = None
        except OSError:
            # Different-volume temp (rare): fall back to in-place write
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                with open(tmp_abs, "r", encoding="utf-8", errors="replace") as t:
                    f.write(t.read())
            try:
                os.unlink(tmp_abs)
            except OSError:
                pass
            tmp_path = None
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

# ---------------------------------------------------------------------------
# Phase 9 — Lock-In Protocol (os_focus_mode), separate marker from legacy focus
# ---------------------------------------------------------------------------

# Canonical marker for rows IntentOS manages (dual-stack). Legacy Lock-In rows still recognized.
_INTENTOS_BLOCK_MARKER = "# IntentOS-Block"
_LEGACY_LOCKIN_MARKER = "# IntentOS-LockIn"
_INTENTOS_HOST_MARKERS = (_INTENTOS_BLOCK_MARKER, _LEGACY_LOCKIN_MARKER)

_HOSTNAME_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)


def _line_has_intentos_host_marker(line: str) -> bool:
    return any(m in line for m in _INTENTOS_HOST_MARKERS)


def _is_valid_hostname(hostname: str) -> bool:
    h = hostname.strip().lower().rstrip(".")
    return bool(h) and bool(_HOSTNAME_RE.fullmatch(h))


# Activate preset: YouTube gets extra API host; all entries written as v4 + ::1 pairs.
_LOCKIN_BLOCKLIST = [
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "youtubei.googleapis.com",
    "instagram.com",
    "www.instagram.com",
    "reddit.com",
    "www.reddit.com",
    "twitter.com",
    "www.twitter.com",
]

_LOCKIN_UNBLOCK_GROUPS = {
    "youtube": frozenset(
        {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
            "youtubei.googleapis.com",
        }
    ),
    "instagram": frozenset({"instagram.com", "www.instagram.com"}),
    "reddit": frozenset({"reddit.com", "www.reddit.com", "old.reddit.com"}),
    "twitter": frozenset({"twitter.com", "www.twitter.com", "x.com", "mobile.twitter.com"}),
}

# block:<name> presets (service keyword → hostnames)
_BLOCK_PRESET_ALIASES: dict[str, tuple[str, ...]] = {
    "youtube": _LOCKIN_UNBLOCK_GROUPS["youtube"],
    "instagram": _LOCKIN_UNBLOCK_GROUPS["instagram"],
    "reddit": _LOCKIN_UNBLOCK_GROUPS["reddit"],
    "twitter": _LOCKIN_UNBLOCK_GROUPS["twitter"],
    "tiktok": ("tiktok.com", "www.tiktok.com"),
    "facebook": ("facebook.com", "www.facebook.com", "m.facebook.com"),
    "netflix": ("netflix.com", "www.netflix.com"),
    "twitch": ("twitch.tv", "www.twitch.tv"),
}


def _powershell_creationflags() -> int:
    if platform.system() == "Windows":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


def _run_powershell_lockin(command: str) -> tuple[bool, str]:
    try:
        cf = _powershell_creationflags()
        kwargs: dict = {
            "args": [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            "capture_output": True,
            "text": True,
            "timeout": 10,
        }
        if cf:
            kwargs["creationflags"] = cf
        r = subprocess.run(**kwargs)
        ok = r.returncode == 0
        tail = (r.stderr or r.stdout or "")[:240]
        return ok, tail.strip()
    except Exception as exc:
        return False, str(exc)[:240]


def _lockin_set_toasts_enabled(enabled: bool) -> tuple[bool, str]:
    """
    Best-effort toast / banner suppression across Windows 10/11 builds.
    Uses several HKCU keys; success if at least one Set-ItemProperty succeeds.
    """
    val = 1 if enabled else 0
    # Single script: create keys if missing, then set (SilentlyContinue per step).
    ps = f"""
$val = {val}
$paths = @(
  @{{ Path = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications\\Settings'; Name = 'NOC_GLOBAL_SETTING_TOASTS_ENABLED' }},
  @{{ Path = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\PushNotifications'; Name = 'ToastEnabled' }},
  @{{ Path = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Notifications'; Name = 'NOC_GLOBAL_SETTING_TOASTS_ENABLED' }}
)
$ok = $false
foreach ($p in $paths) {{
  try {{
    if (-not (Test-Path $p.Path)) {{ New-Item -Path $p.Path -Force | Out-Null }}
    Set-ItemProperty -LiteralPath $p.Path -Name $p.Name -Value $val -Type DWord -Force -ErrorAction Stop
    $ok = $true
  }} catch {{ }}
}}
try {{
  $pol = 'HKCU:\\Software\\Policies\\Microsoft\\Windows\\Explorer'
  if (-not (Test-Path $pol)) {{ New-Item -Path $pol -Force | Out-Null }}
  $banner = if ($val -eq 0) {{ 1 }} else {{ 0 }}
  Set-ItemProperty -LiteralPath $pol -Name 'NoToastApplicationNotification' -Value $banner -Type DWord -Force -ErrorAction Stop
  $ok = $true
}} catch {{ }}
if ($ok) {{ exit 0 }} else {{ exit 1 }}
"""
    ok, msg = _run_powershell_lockin(ps)
    return ok, (msg or ("Toasts suppressed." if val == 0 else "Toasts restored."))


def _lockin_set_volume_20_percent() -> tuple[bool, str]:
    try:
        from pycaw.pycaw import AudioUtilities

        speakers = AudioUtilities.GetSpeakers()
        volume = speakers.EndpointVolume
        volume.SetMasterVolumeLevelScalar(0.20, None)
        return True, "Volume 20%."
    except Exception as exc:
        return False, str(exc)[:240]


def _lockin_parse_host_from_line(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if not _line_has_intentos_host_marker(stripped):
        return None
    parts = stripped.split()
    if len(parts) >= 2 and parts[0] in ("127.0.0.1", "::1"):
        return parts[1].lower().rstrip(".")
    return None


def _lockin_domains_present(lines: list[str]) -> set[str]:
    out: set[str] = set()
    for line in lines:
        h = _lockin_parse_host_from_line(line)
        if h:
            out.add(h)
    return out


def _lockin_hosts_readlines() -> list[str] | None:
    try:
        with open(_effective_hosts_path(), "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError:
        return None


def _lockin_flush_dns_async() -> None:
    if platform.system() != "Windows":
        return
    try:
        cf = _powershell_creationflags()
        kwargs: dict = {
            "args": ["ipconfig", "/flushdns"],
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if cf:
            kwargs["creationflags"] = cf
        subprocess.Popen(**kwargs)
    except Exception:
        pass


def _lockin_append_dual_stack_blocks(
    lines: list[str], domains: list[str]
) -> tuple[list[str], list[str]]:
    """Append 127.0.0.1 + ::1 rows for each domain not already blocked by IntentOS markers."""
    present = _lockin_domains_present(lines)
    added: list[str] = []
    mark = _INTENTOS_BLOCK_MARKER
    for domain in domains:
        dl = domain.lower().strip().rstrip(".")
        if not dl or dl in present:
            continue
        lines.append(f"127.0.0.1 {dl}  {mark}\n")
        lines.append(f"::1 {dl}  {mark}\n")
        present.add(dl)
        added.append(dl)
    return lines, added


def _lockin_activate_hosts() -> tuple[bool, str]:
    try:
        lines = _lockin_hosts_readlines()
        if lines is None:
            return False, "Could not read hosts file."
        lines, added = _lockin_append_dual_stack_blocks(lines, list(_LOCKIN_BLOCKLIST))
        if added:
            _lockin_hosts_write(lines)
            _lockin_flush_dns_async()
            print(
                "[IntentOS] Lock-In: hosts file updated. If sites still load in Chrome/Edge, "
                "disable Settings → Privacy and security → Use secure DNS (DNS-over-HTTPS "
                "bypasses the system hosts file)."
            )
            return True, f"Hosts: added {len(added)} block(s)."
        return True, "Hosts: blocklist already active."
    except PermissionError:
        try:
            is_adm = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            is_adm = False
        hp = _effective_hosts_path()
        print(
            f"[IntentOS] Lock-In: PermissionError writing hosts (admin={is_adm}, path={hp}). "
            "Try: clear hosts file read-only in Properties, allow Python in Windows Security → "
            "Ransomware protection → Controlled folder access, and run uvicorn from an elevated "
            "Command Prompt (not only an elevated GUI shell parent)."
        )
        return False, "Hosts not writable (need Administrator / policy exception)."
    except OSError as exc:
        return False, str(exc)[:200]


def _lockin_remove_all_marker_lines() -> tuple[bool, str]:
    try:
        lines = _lockin_hosts_readlines()
        if lines is None:
            return False, "Could not read hosts file."
        new_lines = [ln for ln in lines if not _line_has_intentos_host_marker(ln)]
        if len(new_lines) == len(lines):
            return True, "Hosts: no IntentOS block entries."
        _lockin_hosts_write(new_lines)
        _lockin_flush_dns_async()
        return True, "Hosts: all IntentOS block rules removed."
    except PermissionError:
        try:
            is_adm = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            is_adm = False
        print(
            f"[IntentOS] Lock-In: PermissionError writing hosts (admin={is_adm}, "
            f"path={_effective_hosts_path()}). See prior Lock-In log hints."
        )
        return False, "Hosts not writable (need Administrator / policy exception)."
    except OSError as exc:
        return False, str(exc)[:200]


def _lockin_resolve_unblock_key(service: str) -> str | None:
    s = service.strip().lower()
    aliases = {
        "youtube": "youtube",
        "youtube.com": "youtube",
        "www.youtube.com": "youtube",
        "m.youtube.com": "youtube",
        "youtu.be": "youtube",
        "youtubei.googleapis.com": "youtube",
        "instagram": "instagram",
        "instagram.com": "instagram",
        "www.instagram.com": "instagram",
        "reddit": "reddit",
        "reddit.com": "reddit",
        "www.reddit.com": "reddit",
        "twitter": "twitter",
        "twitter.com": "twitter",
        "www.twitter.com": "twitter",
        "x.com": "twitter",
        "tiktok": "tiktok",
        "tiktok.com": "tiktok",
        "www.tiktok.com": "tiktok",
        "facebook": "facebook",
        "facebook.com": "facebook",
        "www.facebook.com": "facebook",
        "m.facebook.com": "facebook",
        "netflix": "netflix",
        "netflix.com": "netflix",
        "www.netflix.com": "netflix",
        "twitch": "twitch",
        "twitch.tv": "twitch",
        "www.twitch.tv": "twitch",
    }
    key = aliases.get(s)
    if key:
        return key
    return s if s in _LOCKIN_UNBLOCK_GROUPS else None


def _lockin_remove_hosts_set(group: set[str]) -> tuple[bool, str]:
    group_l = {g.lower().rstrip(".") for g in group if g}
    if not group_l:
        return True, "Nothing to remove."
    try:
        lines = _lockin_hosts_readlines()
        if lines is None:
            return False, "Could not read hosts file."
        kept: list[str] = []
        removed: list[str] = []
        for ln in lines:
            host = _lockin_parse_host_from_line(ln)
            if host and host in group_l:
                removed.append(host)
                continue
            kept.append(ln)
        if not removed:
            return True, "No matching IntentOS host rows to remove."
        _lockin_hosts_write(kept)
        _lockin_flush_dns_async()
        return True, f"Removed {len(removed)} host row(s): {', '.join(sorted(set(removed))[:12])}."
    except PermissionError:
        try:
            is_adm = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            is_adm = False
        print(
            f"[IntentOS] Lock-In: PermissionError writing hosts (admin={is_adm}, "
            f"path={_effective_hosts_path()})."
        )
        return False, "Hosts not writable (need Administrator / policy exception)."
    except OSError as exc:
        return False, str(exc)[:200]


def _lockin_remove_group(service: str) -> tuple[bool, str]:
    key = _lockin_resolve_unblock_key(service)
    if key is not None:
        if key in _LOCKIN_UNBLOCK_GROUPS:
            group = set(_LOCKIN_UNBLOCK_GROUPS[key])
            return _lockin_remove_hosts_set(group)
        if key in _BLOCK_PRESET_ALIASES:
            return _lockin_remove_hosts_set(set(_BLOCK_PRESET_ALIASES[key]))

    dom = service.strip().lower().rstrip(".")
    if _is_valid_hostname(dom):
        hosts = {dom}
        if not dom.startswith("www."):
            hosts.add("www." + dom)
        else:
            bare = dom[4:]
            if bare and _is_valid_hostname(bare):
                hosts.add(bare)
        return _lockin_remove_hosts_set(hosts)

    return True, f"No unblock mapping for {service!r} (nothing changed)."


def _lockin_resolve_block_domains(rest: str) -> tuple[str, ...] | None:
    """Map block:… spec to hostnames (preset keyword or valid FQDN)."""
    s = rest.strip().lower().rstrip(".")
    if not s:
        return None
    if s in _BLOCK_PRESET_ALIASES:
        return _BLOCK_PRESET_ALIASES[s]
    ukey = _lockin_resolve_unblock_key(s)
    if ukey and ukey in _LOCKIN_UNBLOCK_GROUPS:
        return tuple(_LOCKIN_UNBLOCK_GROUPS[ukey])
    if ukey and ukey in _BLOCK_PRESET_ALIASES:
        return _BLOCK_PRESET_ALIASES[ukey]
    if _is_valid_hostname(s):
        return (s,)
    return None


def _lockin_block_from_spec(spec: str) -> tuple[bool, str]:
    domains = _lockin_resolve_block_domains(spec)
    if not domains:
        return False, f"Invalid block target {spec!r} (use e.g. block:youtube or block:news.ycombinator.com)."
    try:
        lines = _lockin_hosts_readlines()
        if lines is None:
            return False, "Could not read hosts file."
        lines, added = _lockin_append_dual_stack_blocks(lines, list(domains))
        if not added:
            return True, "All listed hosts already blocked."
        _lockin_hosts_write(lines)
        _lockin_flush_dns_async()
        print(
            "[IntentOS] Hosts block updated. If a site still loads, disable browser "
            "Secure DNS (DNS-over-HTTPS) and flush DNS (already triggered)."
        )
        return True, f"Blocked: {', '.join(added)}."
    except PermissionError:
        try:
            is_adm = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            is_adm = False
        print(
            f"[IntentOS] Lock-In: PermissionError writing hosts (admin={is_adm}, "
            f"path={_effective_hosts_path()})."
        )
        return False, "Hosts not writable (need Administrator / policy exception)."
    except OSError as exc:
        return False, str(exc)[:200]


def _os_focus_mode(payload: str) -> dict:
    """
    Lock-In Protocol: activate / deactivate / block / unblock.

    Payloads (case-insensitive):
      activate | on
      deactivate | off
      block:youtube | block:facebook.com | block tiktok — dual-stack hosts rows
      unblock:youtube | unblock youtube | unblock:reddit.com — remove preset or exact host rows
    """
    if platform.system() != "Windows":
        return {
            "action": "os_focus_mode",
            "target": str(payload),
            "status": "ok",
            "detail": "Lock-In is Windows-only (skipped).",
        }

    raw = (payload or "").strip().lower()

    if raw in ("on", "activate"):
        bits: list[str] = []
        group = {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
            "instagram.com",
            "www.instagram.com",
            "twitter.com",
            "www.twitter.com",
            "x.com",
            "www.x.com",
        }
        ok_h, msg_h = _lockin_block_from_spec("youtube")
        bits.append(msg_h if ok_h else msg_h)
        ok_h2, msg_h2 = _lockin_block_from_spec("instagram")
        bits.append(msg_h2 if ok_h2 else msg_h2)
        ok_h3, msg_h3 = _lockin_block_from_spec("twitter")
        bits.append(msg_h3 if ok_h3 else msg_h3)

        try:
            print("[Edith] Focus Mode: opening LeetCode...")
        except Exception:
            pass
        try:
            time.sleep(1)
        except Exception:
            pass
        try:
            webbrowser.open("https://leetcode.com")
        except Exception:
            pass

        st = "ok" if (ok_h and ok_h2 and ok_h3) else "partial"
        return {
            "action": "os_focus_mode",
            "target": "activate",
            "status": st,
            "detail": " ".join(bits),
        }

    if raw in ("off", "deactivate"):
        group = {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
            "youtu.be",
            "instagram.com",
            "www.instagram.com",
            "twitter.com",
            "www.twitter.com",
            "x.com",
            "www.x.com",
        }
        ok_h, msg_h = _lockin_remove_hosts_set(group)
        bits = [msg_h if ok_h else msg_h]
        st = "ok" if ok_h else "partial"
        return {
            "action": "os_focus_mode",
            "target": "deactivate",
            "status": st,
            "detail": " ".join(bits),
        }

    if raw.startswith("block"):
        rest = raw[5:].lstrip(":_- ")
        if not rest:
            return {
                "action": "os_focus_mode",
                "target": payload,
                "status": "ok",
                "detail": "Specify a target, e.g. block:youtube or block:netflix.com",
            }
        ok_h, msg_h = _lockin_block_from_spec(rest)
        return {
            "action": "os_focus_mode",
            "target": f"block:{rest}",
            "status": "ok" if ok_h else "partial",
            "detail": msg_h,
        }

    if raw.startswith("unblock"):
        rest = raw[7:].lstrip(":_- ")
        if not rest:
            return {
                "action": "os_focus_mode",
                "target": payload,
                "status": "ok",
                "detail": "Specify a service, e.g. unblock:youtube or unblock:reddit.com",
            }
        ok_h, msg_h = _lockin_remove_group(rest)
        return {
            "action": "os_focus_mode",
            "target": f"unblock:{rest}",
            "status": "ok" if ok_h else "partial",
            "detail": msg_h,
        }

    return {
        "action": "os_focus_mode",
        "target": payload,
        "status": "error",
        "detail": "Use activate, deactivate, block:<site>, or unblock:<site>.",
    }


def _focus_mode(on: bool) -> dict:
    """Toggle focus mode by editing the Windows hosts file via elevated PowerShell."""
    try:
        try:
            marker = _FOCUS_MARKER
        except Exception:
            marker = "# IntentOS-Focus"
        try:
            hosts = _effective_hosts_path()
        except Exception:
            hosts = _HOSTS_PATH
        try:
            tmp = tempfile.gettempdir()
        except Exception:
            tmp = ""
        try:
            log_path = os.path.join(tmp, "intentos_focus.log")
        except Exception:
            log_path = ""

        # Build the PowerShell script content with error logging (hosts block/unblock + flushdns)
        try:
            if on:
                try:
                    print("[Edith] Focus Mode: blocking sites in hosts...")
                except Exception:
                    pass
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
                try:
                    print("[Edith] Focus Mode: unblocking sites from hosts...")
                except Exception:
                    pass
                core = (
                    f'$content = Get-Content $h | Where-Object {{ $_ -notmatch [regex]::Escape("{marker}") }}\n'
                    f'Set-Content -Path $h -Value $content -Force\n'
                    f'ipconfig /flushdns | Out-Null\n'
                )
                mode_str = "OFF"
        except Exception as exc:
            try:
                print(f"[Edith] Focus Mode: hosts script build failed: {exc}")
            except Exception:
                pass
            core = 'ipconfig /flushdns | Out-Null\n'
            mode_str = "ON" if on else "OFF"

        try:
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
        except Exception as exc:
            try:
                print(f"[Edith] Focus Mode: script render failed: {exc}")
            except Exception:
                pass
            script = ""

        # Write temp .ps1 script
        try:
            script_path = os.path.join(tmp, "intentos_focus.ps1")
        except Exception:
            script_path = ""
        try:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script)
        except Exception as exc:
            try:
                print(f"[Edith] Focus Mode: could not write ps1: {exc}")
            except Exception:
                pass

        # Remove old log
        try:
            if log_path and os.path.exists(log_path):
                os.unlink(log_path)
        except Exception as exc:
            try:
                print(f"[Edith] Focus Mode: could not clear old log: {exc}")
            except Exception:
                pass

        # Check if already admin
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            is_admin = False

        try:
            try:
                print("[Edith] Focus Mode: flushing DNS (via existing script)...")
            except Exception:
                pass
            if is_admin:
                subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            else:
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "runas",
                    "powershell.exe",
                    f'-NoProfile -ExecutionPolicy Bypass -File "{script_path}"',
                    None,
                    1,
                )
                if ret <= 32:
                    return {
                        "action": "focus_mode",
                        "target": mode_str,
                        "status": "error",
                        "detail": f"UAC elevation failed (code {ret}). Click Yes on the admin prompt.",
                    }
                try:
                    time.sleep(5)
                except Exception:
                    pass
        except Exception as exc:
            try:
                print(f"[Edith] Focus Mode: hosts/flush script execution failed: {exc}")
            except Exception:
                pass

        if on:
            try:
                print("[Edith] Focus Mode: waiting for DNS flush...")
            except Exception:
                pass
            try:
                time.sleep(1)
            except Exception:
                pass

            try:
                print("[Edith] Focus Mode: setting brightness to 40%...")
            except Exception:
                pass
            try:
                try:
                    sbc.set_brightness(40)
                except Exception as exc1:
                    try:
                        print(f"[Edith] Focus Mode: sbc.set_brightness failed: {exc1}")
                    except Exception:
                        pass
                    try:
                        subprocess.run(
                            [
                                "powershell",
                                "-Command",
                                "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, 40)",
                            ],
                            capture_output=True,
                        )
                    except Exception as exc2:
                        try:
                            print(f"[Edith] Focus Mode: PowerShell brightness fallback failed: {exc2}")
                        except Exception:
                            pass
            except Exception as exc:
                try:
                    print(f"[Edith] Focus Mode: brightness step failed: {exc}")
                except Exception:
                    pass

            try:
                print("[Edith] Focus Mode: opening Notepad...")
            except Exception:
                pass
            try:
                try:
                    subprocess.Popen(["notepad.exe"])
                except Exception as exc1:
                    try:
                        print(f"[Edith] Focus Mode: subprocess.Popen notepad failed: {exc1}")
                    except Exception:
                        pass
                    try:
                        os.system("start notepad.exe")
                    except Exception as exc2:
                        try:
                            print(f"[Edith] Focus Mode: os.system notepad fallback failed: {exc2}")
                        except Exception:
                            pass
            except Exception as exc:
                try:
                    print(f"[Edith] Focus Mode: notepad step failed: {exc}")
                except Exception:
                    pass

            try:
                print("[Edith] Focus Mode: opening LeetCode in browser...")
            except Exception:
                pass
            try:
                webbrowser.open("https://leetcode.com")
            except Exception as exc:
                try:
                    print(f"[Edith] Focus Mode: webbrowser.open failed: {exc}")
                except Exception:
                    pass

        if not on:
            try:
                print("[Edith] Focus Mode: restoring brightness to 100%...")
            except Exception:
                pass
            try:
                try:
                    sbc.set_brightness(100)
                except Exception as exc1:
                    try:
                        print(f"[Edith] Focus Mode: sbc.set_brightness restore failed: {exc1}")
                    except Exception:
                        pass
                    try:
                        subprocess.run(
                            [
                                "powershell",
                                "-Command",
                                "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, 100)",
                            ],
                            capture_output=True,
                        )
                    except Exception as exc2:
                        try:
                            print(f"[Edith] Focus Mode: PowerShell brightness restore fallback failed: {exc2}")
                        except Exception:
                            pass
            except Exception as exc:
                try:
                    print(f"[Edith] Focus Mode: brightness restore step failed: {exc}")
                except Exception:
                    pass

            try:
                print("[Edith] Focus Mode: closing Notepad...")
            except Exception:
                pass
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "notepad.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                try:
                    print(f"[Edith] Focus Mode: taskkill notepad failed: {exc}")
                except Exception:
                    pass

        # Check log for result (original behavior)
        try:
            if log_path and os.path.exists(log_path):
                try:
                    with open(log_path, "r") as lf:
                        log_content = lf.read().strip()
                except Exception:
                    log_content = ""
                if "SUCCESS" in log_content:
                    return {
                        "action": "focus_mode",
                        "target": mode_str,
                        "status": "ok",
                        "detail": f"Focus mode {mode_str}. {'Distractions blocked.' if on else 'Restrictions lifted.'}",
                    }
                else:
                    return {
                        "action": "focus_mode",
                        "target": mode_str,
                        "status": "error",
                        "detail": f"Script error: {log_content[:200]}",
                    }
            else:
                return {
                    "action": "focus_mode",
                    "target": mode_str,
                    "status": "error",
                    "detail": "Elevated script did not run. Did you click Yes on the UAC prompt?",
                }
        except Exception as exc:
            try:
                print(f"[Edith] Focus Mode: log check failed: {exc}")
            except Exception:
                pass
            return {
                "action": "focus_mode",
                "target": "ON" if on else "OFF",
                "status": "ok",
                "detail": "Focus mode toggle skipped.",
            }
    except Exception:
        return {
            "action": "focus_mode",
            "target": "ON" if on else "OFF",
            "status": "ok",
            "detail": "Focus mode toggle skipped.",
        }


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

        if action_type == "os_focus_mode":
            pl = action_payload if isinstance(action_payload, str) else str(action_payload)
            results.append(_os_focus_mode(pl))
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
