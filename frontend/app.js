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
  os_command:      { icon: "⚡", label: "System Command" },
  browser_action:  { icon: "🌐", label: "Browser Action" },
  conversation:    { icon: "💬", label: "Conversation" },
  youtube_play:    { icon: "🎥", label: "Now Playing" },
  google_search:   { icon: "🔍", label: "Web Search" },
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
  const meta = TYPE_META[data.action_type] || { icon: "🔧", label: data.action_type };
  const statusIcon = data.execution_status === "ok" ? checkSVG : crossSVG;
  const statusClass = data.execution_status === "ok" ? "ok" : "err";

  // Build the spoken response bubble
  const spokenHTML = data.spoken_response
    ? `<div class="edith-bubble">
         <span class="edith-avatar">E</span>
         <p class="edith-speech">${escapeHTML(data.spoken_response)}</p>
       </div>`
    : "";

  // Build the action detail
  let actionDetail = "";
  if (data.action_type !== "conversation") {
    actionDetail = `
      <div class="task-item">
        ${statusIcon}
        <span>
          <span class="task-action">${meta.icon} ${meta.label}</span>
          <span class="task-target">${escapeHTML(data.action_payload)}</span>
        </span>
      </div>`;
  } else {
    actionDetail = `
      <div class="task-item conversation-item">
        ${statusIcon}
        <span>
          <span class="task-action">${meta.icon} ${meta.label}</span>
          <span class="task-target">${escapeHTML(data.action_payload)}</span>
        </span>
      </div>`;
  }

  const detailNote = data.execution_detail
    ? `<p class="exec-detail">${escapeHTML(data.execution_detail)}</p>`
    : "";

  results.innerHTML = `
    <div class="status-card is-success">
      ${spokenHTML}
      <ul class="task-list">${actionDetail}</ul>
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
