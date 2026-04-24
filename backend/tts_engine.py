"""
TTS Engine — Phase 7D: Edith's Voice

Uses Kokoro-82M (ONNX, bm_daniel voice) for professional-grade,
British-accented text-to-speech.  Falls back to pyttsx3 if Kokoro
fails to initialise.
"""

import os
import tempfile
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
KOKORO_MODEL = ASSETS_DIR / "kokoro-v1.0.int8.onnx"
KOKORO_VOICES = ASSETS_DIR / "voices-v1.0.bin"
LISTENING_WAV = ASSETS_DIR / "listening.wav"

# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------

_kokoro = None
_kokoro_lock = threading.Lock()
_VOICE = "bm_daniel"


def _get_kokoro():
    """Lazy-load the Kokoro engine (thread-safe)."""
    global _kokoro
    if _kokoro is not None:
        return _kokoro

    with _kokoro_lock:
        if _kokoro is not None:
            return _kokoro
        try:
            from kokoro_onnx import Kokoro
            _kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
            print("[Edith] Kokoro TTS engine loaded (bm_daniel).")
            return _kokoro
        except Exception as exc:
            print(f"[Edith] Kokoro TTS failed to load: {exc}")
            return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def speak(text: str) -> None:
    """Synthesise and play `text` through the speakers (blocking)."""
    if not text:
        return

    kokoro = _get_kokoro()

    if kokoro is not None:
        try:
            samples, sr = kokoro.create(
                text, voice=_VOICE, speed=1.0, lang="en-gb",
            )
            import sounddevice as sd
            sd.play(samples, sr)
            sd.wait()
            return
        except Exception as exc:
            print(f"[Edith] Kokoro speak error: {exc}, falling back to pyttsx3.")

    # Fallback — pyttsx3
    _speak_pyttsx3(text)


def speak_to_file(text: str, path: str) -> bool:
    """Render `text` to a .wav file. Returns True on success."""
    kokoro = _get_kokoro()
    if kokoro is None:
        return False

    try:
        samples, sr = kokoro.create(
            text, voice=_VOICE, speed=1.0, lang="en-gb",
        )
        sf.write(path, samples, sr)
        return True
    except Exception as exc:
        print(f"[Edith] Kokoro render-to-file error: {exc}")
        return False


def regenerate_listening_wav() -> None:
    """Overwrite listening.wav with a Kokoro-quality version."""
    if speak_to_file("Listening.", str(LISTENING_WAV)):
        print("[Edith] listening.wav upgraded to Kokoro quality.")
    else:
        print("[Edith] Keeping pyttsx3 listening.wav (Kokoro unavailable).")


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
