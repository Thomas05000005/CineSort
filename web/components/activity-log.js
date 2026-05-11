/* components/activity-log.js — Timeline d'evenements utilisateur (J15)
 *
 * Drawer side-right ouvert par Ctrl+L. Ecoute les evenements custom
 * `cinesort:event` dispatches par le code pour enregistrer les actions.
 * Queue limitee a 500 entrees, persistee en localStorage.
 */

(function () {
  const _LS_KEY = "cinesort.activityLog";
  const _MAX = 500;
  let _log = [];
  let _drawer = null;
  let _open = false;

  function _load() {
    try {
      const raw = localStorage.getItem(_LS_KEY);
      _log = raw ? JSON.parse(raw) : [];
    } catch { _log = []; }
  }

  function _persist() {
    try { localStorage.setItem(_LS_KEY, JSON.stringify(_log.slice(0, _MAX))); } catch { /* quota */ }
  }

  function _icon(type) {
    const map = {
      scan: "🔍", apply: "▶", undo: "↩", settings: "⚙", error: "⚠", info: "ℹ",
    };
    return map[type] || "·";
  }

  function addEvent(type, msg, meta) {
    const ts = Date.now();
    _log.unshift({ ts, type: String(type || "info"), msg: String(msg || ""), meta: meta || null });
    if (_log.length > _MAX) _log.length = _MAX;
    _persist();
    if (_open) _render();
  }

  function _formatTime(ts) {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
  }

  function _ensureDrawer() {
    if (_drawer && document.body.contains(_drawer)) return _drawer;
    _drawer = document.createElement("aside");
    _drawer.id = "activity-drawer";
    _drawer.className = "activity-drawer";
    _drawer.setAttribute("role", "log");
    _drawer.setAttribute("aria-label", "Journal d'activite");
    _drawer.innerHTML = `
      <div class="activity-drawer__header">
        <span class="activity-drawer__title">Journal d'activite</span>
        <button type="button" class="activity-drawer__clear" title="Effacer">Effacer</button>
        <button type="button" class="activity-drawer__close" aria-label="Fermer" title="Fermer (Esc)">&times;</button>
      </div>
      <div class="activity-drawer__body"></div>`;
    document.body.appendChild(_drawer);
    _drawer.querySelector(".activity-drawer__close").addEventListener("click", _toggle);
    _drawer.querySelector(".activity-drawer__clear").addEventListener("click", () => {
      _log = []; _persist(); _render();
    });
    return _drawer;
  }

  function _render() {
    const body = _drawer.querySelector(".activity-drawer__body");
    if (_log.length === 0) {
      body.innerHTML = '<p class="activity-drawer__empty">Aucun evenement. Les actions (scan, apply, undo, settings) s&rsquo;afficheront ici en temps reel.</p>';
      return;
    }
    // CodeQL js/incomplete-html-attribute-sanitization : fallback inline doit
    // couvrir aussi " et ' pour les attributs HTML (e.type dans class="...").
    const escape = window.escapeHtml || ((s) => String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;"));
    body.innerHTML = _log.map((e) => `
      <div class="activity-entry activity-entry--${escape(e.type)}">
        <span class="activity-entry__time">${_formatTime(e.ts)}</span>
        <span class="activity-entry__icon">${_icon(e.type)}</span>
        <span class="activity-entry__msg">${escape(e.msg)}</span>
      </div>`).join("");
  }

  function _toggle() {
    _ensureDrawer();
    _open = !_open;
    _drawer.classList.toggle("activity-drawer--open", _open);
    if (_open) _render();
  }

  /* Ecouter les evenements custom */
  document.addEventListener("cinesort:event", (e) => {
    const d = e.detail || {};
    addEvent(d.type, d.msg, d.meta);
  });

  /* Ctrl+L toggle drawer */
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === "l" || e.key === "L")) {
      e.preventDefault();
      _toggle();
    }
    if (e.key === "Escape" && _open) {
      _toggle();
    }
  });

  _load();

  window.cinesortLog = addEvent;
})();
