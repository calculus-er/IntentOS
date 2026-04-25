/**
 * IntentOS — Frontend logic (Phase 7D)
 *
 * Handles both the text input form and displays Edith's spoken response
 * alongside execution results from the new JSON router format.
 */

const API_URL = "/api/intent";

// ---- DOM refs ----
const form      = document.getElementById("search-form");
const input     = document.getElementById("intent-input");
const submitBtn = document.getElementById("submit-btn");
const results   = document.getElementById("results");
const hint      = document.getElementById("hint");
const brandIcon = document.getElementById("brand-icon");

// ---- SVG helpers ----
const checkSVG = `<svg class="task-icon ok" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>`;

const crossSVG = `<svg class="task-icon err" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;

// Action type icons and labels
const TYPE_META = {
  os_command:       { icon: "⚡", label: "System Command" },
  browser_action:   { icon: "🌐", label: "Browser Action" },
  conversation:     { icon: "💬", label: "Conversation" },
  youtube_play:     { icon: "🎥", label: "Now Playing" },
  google_search:    { icon: "🔍", label: "Web Search" },
  api_weather:      { icon: "🌤️", label: "Weather" },
  smart_file_open:  { icon: "📄", label: "Smart File" },
  os_focus_mode:    { icon: "🔒", label: "Hosts / Lock-In" },
  multi:            { icon: "✨", label: "Orchestration" },
};

// ---- Render helpers ----

function showLoading() {
  results.innerHTML = `
    <div class="status-card is-loading">
      <div class="spinner"></div>
      <p class="status-label">Edith is processing…</p>
    </div>`;
  hint.style.display = "none";
}

function showResults(data) {
  const overallOk = data.execution_status === "ok";
  const overallPartial = data.execution_status === "partial";
  const spokenHTML = data.spoken_response
    ? `<div class="edith-bubble">
         <span class="edith-avatar">E</span>
         <p class="edith-speech">${escapeHTML(data.spoken_response)}</p>
       </div>`
    : "";

  let actionBlocks = "";

  if (Array.isArray(data.actions) && data.actions.length > 0) {
    actionBlocks = data.actions
      .map((row) => {
        const meta = TYPE_META[row.action_type] || { icon: "🔧", label: row.action_type };
        const rowOk = row.execution_status === "ok";
        const icon = rowOk ? checkSVG : crossSVG;
        const isConv = row.action_type === "conversation";
        const cls = isConv ? "task-item conversation-item" : "task-item";
        const detail = row.execution_detail
          ? `<p class="exec-detail sub">${escapeHTML(row.execution_detail)}</p>`
          : "";
        return `<li class="${cls}">
          ${icon}
          <span class="task-body">
            <span class="task-action">${meta.icon} ${meta.label}</span>
            <span class="task-target">${escapeHTML(row.action_payload)}</span>
            ${detail}
          </span>
        </li>`;
      })
      .join("");
  } else {
    const meta = TYPE_META[data.action_type] || { icon: "🔧", label: data.action_type };
    const statusIcon = overallOk ? checkSVG : crossSVG;
    if (data.action_type !== "conversation") {
      actionBlocks = `<li class="task-item">
        ${statusIcon}
        <span class="task-body">
          <span class="task-action">${meta.icon} ${meta.label}</span>
          <span class="task-target">${escapeHTML(data.action_payload)}</span>
        </span>
      </li>`;
    } else {
      actionBlocks = `<li class="task-item conversation-item">
        ${statusIcon}
        <span class="task-body">
          <span class="task-action">${meta.icon} ${meta.label}</span>
          <span class="task-target">${escapeHTML(data.action_payload)}</span>
        </span>
      </li>`;
    }
  }

  const cardClass =
    overallOk || overallPartial ? "status-card is-success" : "status-card is-success warn";

  const detailNote = data.execution_detail
    ? `<p class="exec-detail">${escapeHTML(data.execution_detail)}</p>`
    : "";

  results.innerHTML = `
    <div class="${cardClass}">
      ${spokenHTML}
      <ul class="task-list">${actionBlocks}</ul>
      ${detailNote}
    </div>`;

  // Pulse the brand icon on success
  brandIcon.style.animation = "none";
  void brandIcon.offsetWidth;
  brandIcon.style.animation = "scaleIn 0.4s ease-out";
}

function showError(msg) {
  results.innerHTML = `
    <div class="status-card is-error">
      <p class="error-msg">${escapeHTML(msg)}</p>
    </div>`;
}

function escapeHTML(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---- Form submission ----

form.addEventListener("submit", async (e) => {
  e.preventDefault();

  const intent = input.value.trim();
  if (!intent) return;

  submitBtn.disabled = true;
  showLoading();

  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ intent }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server error (${res.status})`);
    }

    const data = await res.json();
    showResults(data);
  } catch (err) {
    showError(err.message || "Could not reach the IntentOS backend.");
  } finally {
    submitBtn.disabled = false;
  }
});

// ---- Auto-focus ----
input.focus();

// ---- Wake-word UI (/api/wake-status) — isolated styles, no changes to styles.css ----
(function setupWakeVoiceIndicator() {
  const WAKE_STATUS_URL = "/api/wake-status";
  const POLL_MS = 500;

  const styleEl = document.createElement("style");
  styleEl.setAttribute("data-intentos-wake-ui", "1");
  styleEl.textContent = `
    @keyframes intentos-wake-ring-pulse {
      0%, 100% {
        transform: scale(1);
        opacity: 0.95;
        box-shadow: 0 0 0 2px rgba(167, 139, 250, 0.55), 0 0 18px rgba(110, 231, 183, 0.22);
      }
      50% {
        transform: scale(1.015);
        opacity: 0.65;
        box-shadow: 0 0 0 10px rgba(167, 139, 250, 0.08), 0 0 28px rgba(110, 231, 183, 0.18);
      }
    }
    .search-bar.wake-ring-active::after {
      content: "";
      position: absolute;
      inset: -6px;
      border-radius: calc(var(--radius) + 8px);
      pointer-events: none;
      z-index: 4;
      border: 2px solid rgba(167, 139, 250, 0.4);
      animation: intentos-wake-ring-pulse 1.2s ease-in-out infinite;
    }
    #wake-voice-label {
      width: 100%;
      max-width: 560px;
      margin: 0.35rem 0 0;
      padding: 0;
      text-align: center;
      font-size: 0.9rem;
      font-family: var(--font, "Inter", system-ui, sans-serif);
      color: rgba(161, 161, 170, 0.95);
      min-height: 1.35em;
      display: none;
    }
  `;
  document.head.appendChild(styleEl);

  const wakeLabel = document.createElement("p");
  wakeLabel.id = "wake-voice-label";
  wakeLabel.setAttribute("aria-live", "polite");
  form.insertAdjacentElement("afterend", wakeLabel);

  function applyWakeUi(status) {
    if (status === "listening") {
      form.classList.add("wake-ring-active");
      wakeLabel.textContent = "Listening...";
      wakeLabel.style.display = "block";
      return;
    }
    if (status === "processing") {
      form.classList.add("wake-ring-active");
      wakeLabel.textContent = "Processing...";
      wakeLabel.style.display = "block";
      return;
    }
    form.classList.remove("wake-ring-active");
    wakeLabel.textContent = "";
    wakeLabel.style.display = "none";
  }

  async function pollWakeStatus() {
    try {
      const res = await fetch(WAKE_STATUS_URL);
      if (!res.ok) return;
      const data = await res.json();
      const status = data && data.status;
      if (status === "listening" || status === "processing" || status === "idle") {
        applyWakeUi(status);
      }
    } catch (_) {
      /* ignore — backend optional during dev */
    }
  }

  setInterval(pollWakeStatus, POLL_MS);
  pollWakeStatus();
})();
