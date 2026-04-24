"""
Voice Listener — Phase 7A: The Ear

Pipeline: Ctrl+Space → play "Listening" → Silero VAD recording → Whisper STT
Dual-mode: first press starts, second press = manual kill-switch.
"""

import json
import os
import queue
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LISTENING_WAV = ASSETS_DIR / "listening.wav"
SILERO_MODEL = ASSETS_DIR / "silero_vad.onnx"

SAMPLE_RATE = 16000
VAD_CHUNK = 512  # Silero expects 512 samples at 16 kHz


def _find_real_mic() -> int | None:
    """Find the actual physical microphone, not a virtual one."""
    import sounddevice as sd

    # Allow manual override via .env
    env_idx = os.getenv("MIC_DEVICE_INDEX")
    if env_idx is not None:
        idx = int(env_idx)
        print(f"[Edith] Using mic from MIC_DEVICE_INDEX={idx}")
        return idx

    # Auto-detect: prefer Realtek / Microphone Array, skip virtual mics
    skip_keywords = ["droidcam", "virtual", "audiorelay", "cable"]
    prefer_keywords = ["realtek", "microphone array"]

    devices = sd.query_devices()
    best = None
    for i, d in enumerate(devices):
        if d["max_input_channels"] < 1:
            continue
        name_lower = d["name"].lower()
        if any(k in name_lower for k in skip_keywords):
            continue
        if any(k in name_lower for k in prefer_keywords):
            print(f"[Edith] Auto-selected mic: {d['name']} (device {i})")
            return i
        if best is None:
            best = i

    if best is not None:
        d = sd.query_devices(best)
        print(f"[Edith] Fallback mic: {d['name']} (device {best})")
    return best

# ---------------------------------------------------------------------------
# Shared state (thread-safe)
# ---------------------------------------------------------------------------

_is_recording = False
_state_lock = threading.Lock()
_stop_event = threading.Event()


# ===================================================================
# 1. BOOT — pre-render listening.wav & download Silero VAD model
# ===================================================================

def boot_voice_engine():
    """Called once at server startup."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    _render_listening_wav()
    _download_silero_vad()


def _render_listening_wav():
    if LISTENING_WAV.exists():
        print("[Edith] listening.wav present.")
        return
    import pyttsx3
    engine = pyttsx3.init()
    # Prefer a British-sounding voice
    for v in engine.getProperty("voices"):
        if "david" in v.name.lower() or "british" in v.name.lower():
            engine.setProperty("voice", v.id)
            break
    engine.setProperty("rate", 170)
    engine.save_to_file("Listening", str(LISTENING_WAV))
    engine.runAndWait()
    print("[Edith] Bootstrap listening.wav rendered.")


_SILERO_URL = (
    "https://github.com/snakers4/silero-vad/raw/master/"
    "src/silero_vad/data/silero_vad.onnx"
)

def _download_silero_vad():
    if SILERO_MODEL.exists():
        print("[Edith] Silero VAD model present.")
        return
    print("[Edith] Downloading Silero VAD model …")
    urllib.request.urlretrieve(_SILERO_URL, str(SILERO_MODEL))
    print("[Edith] Silero VAD model ready.")


# ===================================================================
# 2. SILERO VAD — ONNX wrapper
# ===================================================================

class _SileroVAD:
    """Lightweight ONNX wrapper for Silero VAD v5."""

    def __init__(self):
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._sess = ort.InferenceSession(str(SILERO_MODEL), sess_options=opts)
        self.reset()

    def reset(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)

    def __call__(self, chunk: np.ndarray) -> float:
        """Return speech probability for a 512-sample chunk."""
        x = chunk.astype(np.float32).reshape(1, -1)
        outs = self._sess.run(
            None,
            {"input": x, "state": self._state, "sr": self._sr},
        )
        prob, self._state = outs[0], outs[1]
        return float(np.squeeze(prob))


# ===================================================================
# 3. AUDIO RECORDING with Silero VAD
# ===================================================================

def _play_listening():
    """Play the pre-rendered listening.wav (blocking, ~0.5 s)."""
    import winsound
    winsound.PlaySound(str(LISTENING_WAV), winsound.SND_FILENAME)


def _record_with_vad(
    max_duration: float = 12.0,
    silence_timeout: float = 2.0,
    speech_threshold: float = 0.5,
    min_speech_secs: float = 0.5,
    warmup_secs: float = 0.3,
) -> str | None:
    """
    Stream from the mic, use Silero VAD to detect speech boundaries.
    Returns path to a temp .wav or None if nothing was captured.
    Respects _stop_event for the manual kill-switch.
    """
    import sounddevice as sd

    vad = _SileroVAD()
    audio_q: queue.Queue[np.ndarray] = queue.Queue()

    def _cb(indata, _frames, _time, _status):
        audio_q.put(indata[:, 0].copy())  # mono

    frames: list[np.ndarray] = []
    speech_frames = 0
    silence_start: float | None = None

    _stop_event.clear()

    mic_device = _find_real_mic()

    with sd.InputStream(
        device=mic_device,
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=VAD_CHUNK,
        callback=_cb,
    ):
        t0 = time.time()
        while not _stop_event.is_set():
            elapsed = time.time() - t0
            if elapsed > max_duration:
                break

            try:
                chunk = audio_q.get(timeout=0.05)
            except queue.Empty:
                continue

            frames.append(chunk)

            # Skip VAD during warmup (avoids echo from "Listening" WAV)
            if elapsed < warmup_secs:
                continue

            prob = vad(chunk)

            if prob >= speech_threshold:
                speech_frames += 1
                silence_start = None
            else:
                # Only start silence detection after enough speech was heard
                speech_duration = speech_frames * (VAD_CHUNK / SAMPLE_RATE)
                if speech_duration >= min_speech_secs:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start > silence_timeout:
                        break  # natural endpoint

    if not frames:
        return None

    audio = np.concatenate(frames)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes((audio * 32767).astype(np.int16).tobytes())
    return tmp.name


# ===================================================================
# 4. STT — Groq Whisper (3 s timeout) → faster-whisper fallback
# ===================================================================

_local_whisper = None  # lazy singleton


def _transcribe(wav_path: str) -> str | None:
    """Transcribe audio; Groq first, faster-whisper fallback."""
    global _local_whisper

    # ---- Groq (fast, cloud) ----
    try:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=3.0)
        with open(wav_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
                response_format="text",
            )
        text = (result if isinstance(result, str) else result.text).strip()
        if text:
            print(f"[Edith] Groq STT : \"{text}\"")
            return text
    except Exception as exc:
        print(f"[Edith] Groq STT failed ({exc}), trying local …")

    # ---- faster-whisper (local fallback) ----
    try:
        from faster_whisper import WhisperModel
        if _local_whisper is None:
            print("[Edith] Loading local whisper-base model (CPU) …")
            # Force CPU to avoid cublas64_12.dll issues in hackathon environments
            _local_whisper = WhisperModel("base", device="cpu", compute_type="int8")
        segs, _ = _local_whisper.transcribe(wav_path)
        text = " ".join(s.text for s in segs).strip()
        if text:
            print(f"[Edith] Local STT : \"{text}\"")
            return text
    except Exception as exc:
        print(f"[Edith] Local STT also failed: {exc}")

    return None


# ===================================================================
# 5. HOTKEY HANDLER — dual-mode Ctrl+Space with debounce
# ===================================================================

_last_trigger_time = 0.0
_DEBOUNCE_SECS = 1.5      # ignore re-triggers within this window
_GRACE_BEFORE_STOP = 2.0  # min seconds of recording before manual stop works


def _voice_pipeline():
    """Play sound : record with VAD : transcribe : POST to /api/intent."""
    global _is_recording, _last_trigger_time

    now = time.time()

    # -- Second press = kill-switch (only after grace period) --
    with _state_lock:
        if _is_recording:
            if now - _last_trigger_time >= _GRACE_BEFORE_STOP:
                _stop_event.set()
                print("[Edith] Manual stop.")
            return
        _is_recording = True
        _last_trigger_time = now

    try:
        print("[Edith] Listening …")
        _play_listening()

        wav_path = _record_with_vad()
        if not wav_path:
            print("[Edith] No audio captured.")
            return

        text = _transcribe(wav_path)

        # clean up temp file
        try:
            os.unlink(wav_path)
        except OSError:
            pass

        if not text:
            print("[Edith] I heard nothing. I assume you changed your mind.")
            return

        print(f"[Edith] Intent : \"{text}\"")

        # Forward to the existing API endpoint
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/intent",
            data=json.dumps({"intent": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            res = urllib.request.urlopen(req, timeout=30)
            body = json.loads(res.read())
            spoken = body.get("spoken_response", body.get("message", "Done."))
            print(f"[Edith] {spoken}")

            # Speak the response aloud via Kokoro TTS
            from backend.tts_engine import speak
            speak(spoken)
        except Exception as exc:
            print(f"[Edith] API call failed: {exc}")
    finally:
        with _state_lock:
            _is_recording = False


def start_hotkey_listener():
    """Register Ctrl+Space on a background daemon thread."""
    import keyboard

    def _on_trigger():
        now = time.time()
        # Debounce: ignore rapid-fire triggers from key repeat
        if now - _last_trigger_time < _DEBOUNCE_SECS and not _is_recording:
            return
        threading.Thread(target=_voice_pipeline, daemon=True).start()

    keyboard.add_hotkey("ctrl+space", _on_trigger, suppress=True)
    print("[Edith] Voice hotkey active — press Ctrl+Space to speak.")

