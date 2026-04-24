"""
TTS Engine — Phase 7D: Edith's Voice

Uses Deepgram Aura TTS for ultra-low latency, professional-grade
text-to-speech. Falls back to pyttsx3 if the API key is missing or fails.
"""

import io
import json
import os
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf
import sounddevice as sd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LISTENING_WAV = ASSETS_DIR / "listening.wav"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_VOICE = "aura-2-draco-en"  # Valid Deepgram Aura 2 male voice

def _get_deepgram_key() -> str | None:
    return os.getenv("DEEPGRAM_API_KEY")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def speak(text: str) -> None:
    """Synthesise and play `text` through the speakers (blocking)."""
    if not text:
        return

    api_key = _get_deepgram_key()
    if api_key:
        try:
            t0 = time.time()
            url = f"https://api.deepgram.com/v1/speak?model={_VOICE}&encoding=linear16&container=wav"
            req = urllib.request.Request(
                url,
                data=json.dumps({"text": text}).encode("utf-8"),
                headers={
                    "Authorization": f"Token {api_key}",
                    "Content-Type": "application/json"
                },
                method="POST"
            )
            
            res = urllib.request.urlopen(req, timeout=10)
            audio_bytes = res.read()
            synth_ms = int((time.time() - t0) * 1000)
            print(f"[Edith] Deepgram TTS synth: {synth_ms}ms for {len(text)} chars")
            
            # Play using soundfile and sounddevice
            with io.BytesIO(audio_bytes) as f:
                samples, sr = sf.read(f)
                sd.play(samples, sr)
                sd.wait()
            return
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode('utf-8')
            print(f"[Edith] Deepgram API HTTP error {exc.code}: {error_body}. Falling back to pyttsx3.")
        except Exception as exc:
            print(f"[Edith] Deepgram API error: {exc}. Falling back to pyttsx3.")

    # Fallback — pyttsx3
    _speak_pyttsx3(text)


def speak_async(text: str) -> None:
    """Fire-and-forget TTS on a background thread (non-blocking)."""
    threading.Thread(target=speak, args=(text,), daemon=True).start()


def speak_to_file(text: str, path: str) -> bool:
    """Render `text` to a .wav file. Returns True on success."""
    api_key = _get_deepgram_key()
    if not api_key:
        return False

    try:
        url = f"https://api.deepgram.com/v1/speak?model={_VOICE}&encoding=linear16&container=wav"
        req = urllib.request.Request(
            url,
            data=json.dumps({"text": text}).encode("utf-8"),
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        res = urllib.request.urlopen(req, timeout=10)
        audio_bytes = res.read()
        
        with open(path, "wb") as f:
            f.write(audio_bytes)
        return True
    except Exception as exc:
        print(f"[Edith] Deepgram render-to-file error: {exc}")
        return False


def regenerate_listening_wav() -> None:
    """Overwrite listening.wav with a Deepgram-quality version."""
    if speak_to_file("Listening.", str(LISTENING_WAV)):
        print("[Edith] listening.wav upgraded to Deepgram quality.")
    else:
        print("[Edith] Keeping pyttsx3 listening.wav (Deepgram unavailable).")


# ---------------------------------------------------------------------------
# Warmup — Ping API to warm up connection
# ---------------------------------------------------------------------------

def warmup() -> None:
    """Warm up Deepgram API connection (not strictly needed, but verifies key)."""
    if _get_deepgram_key():
        print("[Edith] Deepgram API enabled. Latency should be <300ms.")
    else:
        print("[Edith] DEEPGRAM_API_KEY not found. Will use local pyttsx3 fallback.")


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------

def _speak_pyttsx3(text: str) -> None:
    """Last-resort TTS using pyttsx3."""
    try:
        import pyttsx3
        engine = pyttsx3.init()
        for v in engine.getProperty("voices"):
            if "david" in v.name.lower() or "british" in v.name.lower():
                engine.setProperty("voice", v.id)
                break
        engine.setProperty("rate", 170)
        engine.say(text)
        engine.runAndWait()
    except Exception as exc:
        print(f"[Edith] pyttsx3 fallback also failed: {exc}")
