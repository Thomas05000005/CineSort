/* core/api.js — pywebview API wrapper */

/* --- Indicateur de connexion bridge (E6) -------------------- */
let _connFailureStreak = 0;
const _CONN_FAIL_THRESHOLD = 2;

function _setConnDot(cls, label) {
  const dot = document.getElementById("appConnDot");
  if (!dot) return;
  dot.classList.remove("conn-dot--ok", "conn-dot--warn", "conn-dot--error", "conn-dot--unknown");
  dot.classList.add(cls);
  if (label) {
    dot.setAttribute("data-tip", label);
    dot.setAttribute("aria-label", label);
  }
}

function _noteApiSuccess() {
  if (_connFailureStreak !== 0) _connFailureStreak = 0;
  _setConnDot("conn-dot--ok", "Bridge backend OK");
}

function _noteApiFailure() {
  _connFailureStreak += 1;
  if (_connFailureStreak >= _CONN_FAIL_THRESHOLD) {
    _setConnDot("conn-dot--error", "Bridge backend deconnecte");
  } else {
    _setConnDot("conn-dot--warn", "Bridge instable");
  }
}

/**
 * Generic API call wrapper with error handling and optional status messages.
 * @param {string} name  - label for logging
 * @param {Function} fn  - async function returning the API result
 * @param {Object} opts  - { statusId, fallbackMessage }
 * @returns {Object}     - the API result or { ok: false, message }
 */
async function apiCall(name, fn, opts = {}) {
  const _t0 = performance.now();
  try {
    const result = await fn();
    if (result === undefined || result === null) {
      return { ok: false, message: `Reponse invalide pour ${name}.` };
    }
    console.log("[api] %s ok (%dms)", name, Math.round(performance.now() - _t0));
    _noteApiSuccess();
    return result;
  } catch (err) {
    const details = String(err || "Erreur inconnue");
    const fallback = String(opts.fallbackMessage || `Erreur pendant ${name}.`);
    if (opts.statusId) {
      setStatusMessage(opts.statusId, fallback, { error: true });
    }
    console.error(`[apiCall:${name}]`, err);
    _noteApiFailure();
    return { ok: false, message: details };
  }
}

/**
 * Open a path via the backend, with button feedback.
 */
async function openPathWithFeedback(path, statusId, fallbackMessage, opts = {}) {
  const res = await apiCall("open_path", () => window.pywebview.api.open_path(path), {
    statusId,
    fallbackMessage: fallbackMessage || "Impossible d'ouvrir ce dossier.",
  });
  if (!res?.ok) {
    setStatusMessage(statusId, `Impossible d'ouvrir : ${res?.message || "erreur"}`, { error: true });
    flashActionButton(opts.triggerEl || null, "error");
    return res;
  }
  if (opts.successMessage) {
    setStatusMessage(statusId, String(opts.successMessage), { success: true, clearMs: Number(opts.clearMs || 1800) });
  }
  flashActionButton(opts.triggerEl || null, "ok");
  return res;
}

/** Probe tool status formatting. */
function probeToolStatusLine(label, tool) {
  const t = (tool && typeof tool === "object") ? tool : {};
  const status = String(t.status || "missing");
  const ver = String(t.version || "").trim();
  const src = String(t.source || "none");
  const msg = String(t.message || "");
  const head = status === "ok" ? `${label}: OK` : `${label}: ${status}`;
  const suffix = ver ? `v${ver}` : "version n/d";
  return `${head} (${suffix}, source=${src})${msg ? ` — ${msg}` : ""}`;
}

/** Persist current validation decisions to backend. */
async function persistValidation() {
  if (!state.runId) return { ok: false, message: "Aucun run actif." };
  return apiCall("save_validation", () => window.pywebview.api.save_validation(state.runId, gatherDecisions()), {
    fallbackMessage: "Impossible d'enregistrer les decisions.",
  });
}
