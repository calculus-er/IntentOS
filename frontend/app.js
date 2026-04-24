/**
 * IntentOS — Frontend logic
 *
 * Sends the user's natural-language intent to the local Python backend,
 * displays a loading state, then renders the execution results.
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

// Pretty labels for each action type
const ACTION_LABELS = {
  open_folder: "📂 Open folder",
  open_url:    "🌐 Open URL",
  open_app:    "🚀 Launch app",
  run_command: "⚡ Run command",
};

// ---- Render helpers ----

function showLoading() {
  results.innerHTML = `
    <div class="status-card is-loading">
      <div class="spinner"></div>
      <p class="status-label">Thinking & executing…</p>
    </div>`;
  hint.style.display = "none";
}

function showResults(data) {
  const taskItems = data.results
    .map((r) => {
      const icon   = r.status === "ok" ? checkSVG : crossSVG;
      const label  = ACTION_LABELS[r.action] || r.action;
      const detail = r.detail ? ` — ${r.detail}` : "";
      return `
        <li class="task-item">
          ${icon}
          <span>
            <span class="task-action">${label}</span>
            <span class="task-target">${escapeHTML(r.target)}${detail}</span>
          </span>
        </li>`;
    })
    .join("");

  results.innerHTML = `
    <div class="status-card is-success">
      <ul class="task-list">${taskItems}</ul>
      <p class="summary">${escapeHTML(data.message)}</p>
    </div>`;

  // Pulse the brand icon on success
  brandIcon.style.animation = "none";
  void brandIcon.offsetWidth;             // reflow
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
