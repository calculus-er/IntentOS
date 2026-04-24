# IntentOS: Intent-Based OS Layer

An intent-based operating system layer that translates natural language commands into automated workflows across local apps and browsers.

## Architecture

- **Backend** — Python (FastAPI) server running on `localhost` that handles AI inference via Groq and executes OS-level actions using native Python modules.
- **Frontend** — Lightweight vanilla JS/HTML/CSS interface providing a minimalist search bar for submitting intents.

## Getting Started

### Prerequisites

- Python 3.10+
- A [Groq](https://console.groq.com/) API key

### Setup

```bash
# Clone the repo
git clone https://github.com/calculus-er/IntentOS.git
cd IntentOS

# Create & activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

# Install backend dependencies
pip install -r backend/requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

## License

MIT
