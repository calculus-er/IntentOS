# IntentOS: Project Overview & Architecture Guide

## 1. Vision & Purpose
**IntentOS** is a sophisticated, AI-driven operating system automation layer built for Windows. Modeled after the "Edith / J.A.R.V.I.S." persona from Iron Man, its goal is to seamlessly translate natural human speech into instant system-level actions. 

Instead of treating the AI as a simple chatbot, IntentOS gives the AI "hands" to control the local machine and the browser, drastically reducing friction for tasks like focusing, searching, consuming media, or adjusting system settings.

---

## 2. Core Capabilities

### 🎙️ Advanced Voice Pipeline
- **Activation:** A global, debounced hotkey (`Ctrl + Space`) triggers listening from anywhere on the PC.
- **Voice Activity Detection (VAD):** Uses a local, lightning-fast **Silero VAD (ONNX)** model to intelligently detect exactly when the user starts and stops speaking, eliminating the need to hold down a button or wait for rigid timeouts.
- **Speech-to-Text (STT):** Routes audio to **Groq's Whisper Large V3** for near-instant, highly accurate transcription. Automatically falls back to a local `faster-whisper` model if the network fails.
- **Text-to-Speech (TTS):** Powered by **Deepgram Aura 2 (`aura-2-draco-en`)**, providing a deep, movie-quality British male voice with extremely low latency (~200ms). Falls back to the native Windows `pyttsx3` voice if the API is unreachable.

### 🧠 The "Brain" (AI Routing Engine)
Every spoken intent is sent to Groq (Llama 3 70B) with strict constraints to return a specialized JSON object containing:
1. `action_type`: The category of the task.
2. `action_payload`: The specific command, URL, or search query.
3. `spoken_response`: A short, witty, in-character confirmation to be spoken aloud.

**Supported Action Types:**
- `os_command`: Controls volume, brightness, locks the screen, opens folders, or runs raw PowerShell.
- `browser_action`: Deep-links directly to specific applications (e.g., LeetCode, GitHub).
- `youtube_play`: Intelligently resolves requests like "Play MrBeast's latest video" to the exact URL.
- `google_search`: Differentiates between basic lookups and deep research tasks.
- `api_weather`: A highly specialized, parallel-execution handler for weather queries.
- `conversation`: Handles casual questions, math, or logic without system side-effects.

### 🦾 The "Hands" (OS Execution Engine)
The execution engine intercepts the JSON router and safely applies the actions to the Windows OS using native APIs:
- **Audio/Display:** `pycaw` for hardware-level volume control, `screen-brightness-control` for monitor adjustments.
- **Security:** `ctypes.windll.user32` to instantly lock the workstation.
- **Focus Mode:** A specialized feature that uses elevated PowerShell (triggering a UAC Admin prompt) to dynamically rewrite the Windows `hosts` file, blocking distracting websites like YouTube and Reddit at the network level.
- **Smart Weather:** Dynamically pings `ip-api.com` to find the user's city, hits `wttr.in` for live telemetry, parses the data, builds an Edith-style spoken response, and opens a visual Google weather widget—all seamlessly.

### 💻 The Interface
A sleek, modern web frontend served via FastAPI. It acts as a visual log of the interaction, separating the user's intent, Edith's spoken confirmation, and the technical execution details into distinct, readable UI blocks with contextual icons.

---

## 3. Codebase Structure

The project is highly modular, split between a Python/FastAPI backend and a vanilla JS/CSS frontend.

### Root Directory
- `main.py` *(inside backend/)*: The FastAPI entry point. Orchestrates the lifespan of the app (booting the mic, VAD, and TTS warmup) and exposes the `/api/intent` endpoint.
- `.env`: Stores sensitive API keys (`GROQ_API_KEY`, `DEEPGRAM_API_KEY`) and local config paths.

### Backend (`/backend`)
- **`ai_engine.py`**: The prompt engineering hub. Defines the Edith persona, injects short-term memory history, and enforces the JSON output schema from Groq.
- **`executor.py`**: The massive switchboard. Maps the AI's intended actions to actual Python/Windows system calls. Contains the complex logic for `_focus_mode`, `_fetch_weather`, and fallback PowerShell execution.
- **`voice_listener.py`**: A complex, multi-threaded audio module. Manages microphone selection, the `_SileroVAD` ONNX inference, the STT fallback chain, and the global `keyboard` hook.
- **`tts_engine.py`**: Handles asynchronous voice generation. Manages the Deepgram API connection, decodes the audio stream into PCM data via `soundfile`, and plays it securely via `sounddevice`.
- **`memory.py`**: A simple persistence layer that reads/writes conversation history to a local JSON file to give the LLM context of the last few interactions.
- **`youtube_resolver.py` & `google_search.py`**: (Phase 7 plugins) Specialized web-scraping/API logic to convert natural language queries into precise destination URLs.

### Frontend (`/frontend`)
- **`index.html` & `app.js`**: The visual chat interface. It polls or waits for the backend to push updates, renders distinct "speech bubbles" vs "execution blocks", and dynamically assigns icons based on the `action_type`.

---

## 4. Current State & Future Potential

**Phase 8 (Smart APIs)** has just been completed, marking a massive leap from a basic script-runner to a truly context-aware agent (evidenced by the Smart Weather implementation and Deepgram low-latency TTS integration).

**Next Logical Steps / Areas for Expansion:**
1. **Complex Chaining:** Allowing Edith to execute multi-step scripts (e.g., "Create a new React project on my Desktop, open it in VS Code, and start the dev server").
2. **Persistent Memory / RAG:** Upgrading `memory.py` to use a vector database so Edith can remember preferences, code snippets, or user traits forever.