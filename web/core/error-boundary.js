/* core/error-boundary.js — Filet de securite global JS (E7)
 *
 * Capture les erreurs JS non gerees et les rejets de Promise.
 * Affiche un toast d'alerte et logge sans bloquer l'app.
 *
 * Helper renderViewSafe(fn, viewId) : execute fn dans un try/catch ;
 * en cas d'erreur, remplace le contenu de la vue par un message + bouton retry.
 */

function _logError(prefix, err) {
  try {
    console.error(prefix, err);
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.log_api_exception === "function") {
      const msg = (err && err.message) || String(err);
      const stack = (err && err.stack) || "";
      window.pywebview.api.log_api_exception("frontend", msg, stack);
    }
  } catch { /* silencieux */ }
}

function _showFatalToast(text) {
  if (typeof window.toast === "function") {
    window.toast({ type: "error", text: `Erreur : ${text}`, duration: 6000 });
  }
}

window.addEventListener("error", (e) => {
  _logError("[error-boundary] uncaught", e.error || e.message);
  _showFatalToast(e.message || "erreur JS");
});

window.addEventListener("unhandledrejection", (e) => {
  _logError("[error-boundary] unhandled rejection", e.reason);
  _showFatalToast(String(e.reason && e.reason.message ? e.reason.message : e.reason).slice(0, 120));
});

/**
 * Wrappe un rendu de vue. Si l'execution lance, remplace le HTML par un
 * fallback minimaliste avec bouton "Recharger".
 *
 * @param {string} viewId - id du conteneur de la vue (ex: "view-home")
 * @param {Function} renderFn - fonction de rendu (sync ou async)
 */
async function renderViewSafe(viewId, renderFn) {
  try {
    return await renderFn();
  } catch (err) {
    _logError(`[error-boundary] view ${viewId}`, err);
    const el = document.getElementById(viewId);
    if (el) {
      el.innerHTML = `
        <div class="card" style="margin:24px;text-align:center">
          <h2 style="color:var(--danger,#F87171)">Erreur de rendu</h2>
          <p class="text-muted">La vue n'a pas pu s'afficher correctement.</p>
          <pre style="text-align:left;background:var(--bg-overlay);padding:8px;border-radius:6px;overflow:auto;max-height:160px">${String(err && err.message ? err.message : err).replace(/[<>&]/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" })[c])}</pre>
          <button class="btn btn-primary" onclick="location.reload()">Recharger l'application</button>
        </div>`;
    }
    return null;
  }
}

window.renderViewSafe = renderViewSafe;
