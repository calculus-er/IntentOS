"""
Voice Listener — Phase 7A: The Ear

Pipeline: Ctrl+Space or "Hey Jarvis" → "Listening" → record command →
press Ctrl+E when finished (noisy rooms) or wait for silence → "Execute." cue → STT → /api/intent.
Dual-mode: first Ctrl+Space while recording (after grace) = stop without running; Ctrl+E = finish and run.

Wake word (no account required by default):
  pip install openwakeword pyaudio
  Uses openWakeWord with a built-in model (default: hey_jarvis → say "Hey Jarvis"). Models download
  once from GitHub into the openwakeword package folder.

Optional Picovoice Porcupine (only if you have an AccessKey):
  pip install pvporcupine
  Set PORCUPINE_ACCESS_KEY non-empty to use Porcupine instead of openWakeWord ("hey barista" keyword).
"""

import backend.project_env  # noqa: F401  # repo .env so Groq STT sees GROQ_API_KEY

import json
import os
import queue
import tempfile
import struct
import threading
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

# Picovoice (optional). Leave empty to use free openWakeWord instead.
PORCUPINE_ACCESS_KEY = ""

# openWakeWord — pretrained name from openwakeword.MODELS (e.g. hey_jarvis, hey_mycroft, alexa).
OPENWAKEWORD_WAKE_MODEL = "hey_jarvis"
# Lower in noisy places if needed (env OPENWAKEWORD_SCORE_THRESHOLD).
OPENWAKEWORD_SCORE_THRESHOLD = 0.4
OPENWAKEWORD_TRIGGER_COOLDOWN_SEC = 2.0

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LISTENING_WAV = ASSETS_DIR / "listening.wav"
EXECUTING_WAV = ASSETS_DIR / "executing.wav"
SILERO_MODEL = ASSETS_DIR / "silero_vad.onnx"

SAMPLE_RATE = 16000
VAD_CHUNK = 512  # Silero expects 512 samples at 16 kHz


def _pyaudio_input_device_index() -> int | None:
    """
    PyAudio input device index (not always same numbering as sounddevice's MIC_DEVICE_INDEX).
    Set OWW_DEVICE_INDEX in .env to override; else MIC_DEVICE_INDEX; else system default.
    """
    for key in ("OWW_DEVICE_INDEX", "MIC_DEVICE_INDEX"):
        raw = os.getenv(key)
        if raw is not None and str(raw).strip() != "":
            try:
                idx = int(str(raw).strip())
                print(f"[Edith] PyAudio wake mic from {key}={idx}")
                return idx
            except ValueError:
                pass
    return None


def _oww_score_threshold() -> float:
    raw = os.getenv("OWW_SCORE_THRESHOLD")
    if raw is not None and str(raw).strip() != "":
        try:
            return float(str(raw).strip())
        except ValueError:
            pass
    return float(OPENWAKEWORD_SCORE_THRESHOLD)


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
# 1. BOOT — pre-render listening / executing cues & download Silero VAD
# ===================================================================

def boot_voice_engine():
    """Called once at server startup."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    _render_listening_wav()
    _render_executing_wav()
    _download_silero_vad()


def _tts_render_short_wav(out_path: Path, phrase: str, label: str) -> None:
    """One-shot pyttsx3 render; same voice heuristics as the listening cue."""
    if out_path.exists():
        print(f"[Edith] {label} present.")
        return
    import pyttsx3

    engine = pyttsx3.init()
    for v in engine.getProperty("voices"):
        if "david" in v.name.lower() or "british" in v.name.lower():
            engine.setProperty("voice", v.id)
            break
    engine.setProperty("rate", 170)
    engine.save_to_file(phrase, str(out_path))
    engine.runAndWait()
    print(f"[Edith] Bootstrap {label} rendered.")


def _render_listening_wav():
    _tts_render_short_wav(LISTENING_WAV, "Listening", "listening.wav")


def _render_executing_wav():
    """Played after the mic closes: confirms Edith is executing your command (regenerate after phrase change)."""
    _tts_render_short_wav(EXECUTING_WAV, "Execute.", "executing.wav")


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
    try:
        import soundfile as sf
        import sounddevice as sd
        data, fs = sf.read(str(LISTENING_WAV))
        sd.play(data, fs)
        sd.wait()
    except Exception as exc:
        print(f"[Edith] Failed to play listening.wav: {exc}")


def _play_executing_cue():
    """Play after the mic closes (silence, max time, or Ctrl+E): confirms run is starting."""
    try:
        import soundfile as sf
        import sounddevice as sd
        if not EXECUTING_WAV.exists():
            _render_executing_wav()
        data, fs = sf.read(str(EXECUTING_WAV))
        sd.play(data, fs)
        sd.wait()
    except Exception as exc:
        print(f"[Edith] Failed to play executing.wav: {exc}")


def _record_with_vad(
    max_duration: float = 12.0,
    silence_timeout: float | None = None,
    speech_threshold: float = 0.5,
    min_speech_secs: float = 0.5,
    warmup_secs: float = 0.3,
) -> str | None:
    """
    Stream from the mic, use Silero VAD to detect speech boundaries.
    Returns path to a temp .wav or None if nothing was captured.
    Respects _stop_event: Ctrl+E (execute now), or second Ctrl+Space after grace (cancel-style stop).
    """
    import sounddevice as sd

    if silence_timeout is None:
        try:
            silence_timeout = float(os.getenv("VOICE_SILENCE_TIMEOUT_SEC", "2.0"))
        except ValueError:
            silence_timeout = 2.0

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

    if not os.getenv("GROQ_API_KEY"):
        try:
            from dotenv import load_dotenv

            load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
        except Exception:
            pass

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


def _sync_wake_status(value: str) -> None:
    """Push voice phase to main.wake_status for /api/wake-status (best-effort, never raises)."""
    try:
        import backend.main as _main

        _main.wake_status = value
    except Exception:
        pass


def _try_start_voice_pipeline() -> bool:
    """
    If debounce allows, start the voice session thread. Returns True only when a thread was started
    (used by wake word after releasing the mic; do not start if False).
    """
    now = time.time()
    if now - _last_trigger_time < _DEBOUNCE_SECS and not _is_recording:
        return False
    threading.Thread(target=_voice_pipeline, daemon=True).start()
    return True


def _trigger_voice_pipeline() -> None:
    """Debounce + start voice thread — shared by Ctrl+Space and wake word (ignores return value)."""
    _try_start_voice_pipeline()


def _wait_for_voice_session_idle(max_wait: float = 120.0) -> None:
    """Wait until the voice session started from wake has finished (mic free again)."""
    t_end = time.time() + max_wait
    # Wait for session to go active
    while time.time() < t_end:
        with _state_lock:
            if _is_recording:
                break
        time.sleep(0.02)
    # Wait for idle
    while time.time() < t_end:
        with _state_lock:
            if not _is_recording:
                return
        time.sleep(0.05)


def _signal_execute_now() -> None:
    """End recording and run the command (use in noisy places when silence detection is unreliable)."""
    with _state_lock:
        if not _is_recording:
            return
    _stop_event.set()
    print("[Edith] Ctrl+E — closing mic and executing.")


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
        _sync_wake_status("listening")
        print("[Edith] Listening …")
        _play_listening()

        wav_path = _record_with_vad()
        if not wav_path:
            print("[Edith] No audio captured.")
            return

        _play_executing_cue()
        _sync_wake_status("processing")
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
            # TTS is handled by the FastAPI handler (speak_async) to avoid double playback.
        except Exception as exc:
            print(f"[Edith] API call failed: {exc}")
    finally:
        with _state_lock:
            _is_recording = False
        _sync_wake_status("idle")


def _oww_pyaudio_close(stream, pa) -> None:
    try:
        if stream is not None:
            stream.stop_stream()
    except Exception:
        pass
    try:
        if stream is not None:
            stream.close()
    except Exception:
        pass
    try:
        if pa is not None:
            pa.terminate()
    except Exception:
        pass


def _wake_word_thread_openwakeword() -> None:
    """
    Always-on openWakeWord listener (daemon). No Picovoice account; ONNX + first-run model download.

    Releases the PyAudio input before starting the normal voice session so Windows can open the
    mic again for recording (shared-mode conflicts otherwise).
    """
    try:
        import pyaudio
        from openwakeword import utils as oww_utils
        from openwakeword.model import Model
    except Exception as exc:
        print(f"[Edith] Wake word disabled (openWakeWord import): {exc}")
        return

    model_key = (OPENWAKEWORD_WAKE_MODEL or "hey_jarvis").strip()
    oww_chunk = 1280
    oww_rate = 16000
    oww_device = _pyaudio_input_device_index()
    score_threshold = _oww_score_threshold()

    try:
        oww_utils.download_models(model_names=[model_key])
    except Exception as exc:
        print(f"[Edith] openWakeWord model download failed ({exc}). Wake word off; Ctrl+Space still works.")
        return

    try:
        oww = Model(wakeword_models=[model_key], inference_framework="onnx")
    except Exception as exc:
        print(f"[Edith] openWakeWord model load failed ({exc}). Wake word off; Ctrl+Space still works.")
        return

    def _reopen_oww_stream():
        p = pyaudio.PyAudio()
        kw = dict(
            format=pyaudio.paInt16,
            channels=1,
            rate=oww_rate,
            input=True,
            frames_per_buffer=oww_chunk,
        )
        if oww_device is not None:
            kw["input_device_index"] = oww_device
        s = p.open(**kw)
        return p, s

    pa = None
    stream = None
    last_fire = 0.0
    try:
        pa, stream = _reopen_oww_stream()
    except Exception as exc:
        print(f"[Edith] openWakeWord PyAudio failed ({exc}). Ctrl+Space still works.")
        return

    _oww_phrase = {
        "hey_jarvis": "Hey Jarvis",
        "hey_mycroft": "Hey Mycroft",
        "hey_rhasspy": "Hey Rhasspy",
        "alexa": "Alexa",
        "timer": "timer",
        "weather": "weather",
    }.get(model_key, model_key.replace("_", " "))
    print(
        f'[Edith] Wake word active (openWakeWord) — say "{_oww_phrase}" to wake. '
        f"Threshold={score_threshold}. If it misses, set OWW_SCORE_THRESHOLD in .env (e.g. 0.3)."
    )
    try:
        while True:
            try:
                raw = stream.read(oww_chunk, exception_on_overflow=False)
            except Exception as exc:
                print(f"[Edith] openWakeWord mic read error: {exc}")
                time.sleep(0.2)
                continue
            if len(raw) < oww_chunk * 2:
                continue
            try:
                audio = np.frombuffer(raw, dtype=np.int16)
                scores = oww.predict(audio)
            except Exception as exc:
                print(f"[Edith] openWakeWord predict error: {exc}")
                time.sleep(0.05)
                continue
            try:
                peak = max(float(v) for v in scores.values())
            except Exception:
                peak = 0.0
            if peak >= score_threshold:
                now = time.time()
                if now - last_fire < OPENWAKEWORD_TRIGGER_COOLDOWN_SEC:
                    continue
                last_fire = now
                # Must release the mic *before* the main pipeline opens sounddevice (Windows).
                _oww_pyaudio_close(stream, pa)
                stream, pa = None, None
                try:
                    started = _try_start_voice_pipeline()
                except Exception as exc:
                    print(f"[Edith] Wake word handoff error: {exc}")
                    started = False
                if not started:
                    time.sleep(0.15)
                    try:
                        pa, stream = _reopen_oww_stream()
                        oww.reset()
                    except Exception as exc2:
                        print(f"[Edith] openWakeWord could not reopen mic ({exc2}). Retrying in 1s…")
                        time.sleep(1.0)
                        pa, stream = _reopen_oww_stream()
                        oww.reset()
                    continue
                _wait_for_voice_session_idle()
                time.sleep(0.2)
                try:
                    oww.reset()
                    pa, stream = _reopen_oww_stream()
                except Exception as exc2:
                    print(f"[Edith] openWakeWord could not reopen mic after session ({exc2}). Retrying in 1s…")
                    time.sleep(1.0)
                    try:
                        pa, stream = _reopen_oww_stream()
                        oww.reset()
                    except Exception as exc3:
                        print(f"[Edith] openWakeWord mic recovery failed: {exc3}. Wake loop exit.")
                        return
    finally:
        _oww_pyaudio_close(stream, pa)


def _wake_word_thread_porcupine() -> None:
    """Porcupine path when PORCUPINE_ACCESS_KEY is set."""
    try:
        import pyaudio
        import pvporcupine
    except Exception as exc:
        print(f"[Edith] Porcupine wake disabled (import error): {exc}")
        return

    porcupine = None
    pa = None
    audio_stream = None
    try:
        try:
            porcupine = pvporcupine.create(
                access_key=PORCUPINE_ACCESS_KEY.strip(),
                keywords=["hey barista"],
            )
        except Exception as exc:
            print(f"[Edith] Porcupine failed to load ({exc}). Wake word off; Ctrl+Space still works.")
            return

        pdevice = _pyaudio_input_device_index()

        def _p_open():
            p = pyaudio.PyAudio()
            kws = dict(
                rate=porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=porcupine.frame_length,
            )
            if pdevice is not None:
                kws["input_device_index"] = pdevice
            s = p.open(**kws)
            return p, s

        pa, audio_stream = _p_open()

        flen = porcupine.frame_length
        nbytes = flen * 2
        print(
            '[Edith] Wake word active — say "hey barista" (built-in placeholder for "Hey Edith"; see file header).'
        )
        while True:
            try:
                pcm_bytes = audio_stream.read(nbytes, exception_on_overflow=False)
            except Exception as exc:
                print(f"[Edith] Wake word mic read error: {exc}")
                time.sleep(0.2)
                continue
            if len(pcm_bytes) < nbytes:
                continue
            try:
                pcm = struct.unpack_from("<" + "h" * flen, pcm_bytes, 0)
                kw_index = porcupine.process(pcm)
            except Exception as exc:
                print(f"[Edith] Porcupine process error: {exc}")
                time.sleep(0.1)
                continue
            if kw_index >= 0:
                _oww_pyaudio_close(audio_stream, pa)
                audio_stream, pa = None, None
                try:
                    started = _try_start_voice_pipeline()
                except Exception as exc:
                    print(f"[Edith] Wake word handoff error: {exc}")
                    started = False
                if not started:
                    time.sleep(0.15)
                    try:
                        pa, audio_stream = _p_open()
                    except Exception as exc2:
                        print(f"[Edith] Porcupine could not reopen mic: {exc2}")
                        return
                    continue
                _wait_for_voice_session_idle()
                time.sleep(0.2)
                try:
                    pa, audio_stream = _p_open()
                except Exception as exc2:
                    print(f"[Edith] Porcupine could not reopen mic after session: {exc2}")
                    return
    finally:
        try:
            if audio_stream is not None:
                audio_stream.close()
        except Exception:
            pass
        try:
            if pa is not None:
                pa.terminate()
        except Exception:
            pass
        try:
            if porcupine is not None:
                porcupine.delete()
        except Exception:
            pass


def _wake_word_thread() -> None:
    """Porcupine if key set; otherwise openWakeWord (free, no Picovoice login)."""
    if (PORCUPINE_ACCESS_KEY or "").strip():
        _wake_word_thread_porcupine()
    else:
        _wake_word_thread_openwakeword()


def start_hotkey_listener():
    """Register Ctrl+Space on a background daemon thread."""
    import keyboard

    keyboard.add_hotkey("ctrl+space", _trigger_voice_pipeline, suppress=True)
    keyboard.add_hotkey("ctrl+e", _signal_execute_now, suppress=True)
    print("[Edith] Voice: Ctrl+Space (or Hey Jarvis) to speak · Ctrl+E when done to execute in noise.")

    try:
        threading.Thread(
            target=_wake_word_thread,
            name="wake_word_thread",
            daemon=True,
        ).start()
    except Exception as exc:
        print(f"[Edith] Wake word thread not started ({exc}). Ctrl+Space unchanged.")

