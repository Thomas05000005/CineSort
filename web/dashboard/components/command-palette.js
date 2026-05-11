/* components/command-palette.js — Palette Ctrl+K (port ES module).
 *
 * Simplifiee par rapport au desktop : utilise les routes dashboard + actions REST.
 * Ctrl+K ou event "cinesort:command-palette" ouvre la palette.
 */

import { navigateTo } from "../core/router.js";

let _overlay = null;
let _input = null;
let _list = null;
let _commands = [];
let _filtered = [];
let _selectedIdx = 0;

const _MRU_KEY = "cinesort.dashboard.cmdPalette.mru";
const _MRU_LIMIT = 10;

function _loadMru() {
  try { return JSON.parse(localStorage.getItem(_MRU_KEY) || "[]"); }
  catch { return []; }
}
function _saveMru(list) {
  try { localStorage.setItem(_MRU_KEY, JSON.stringify(list.slice(0, _MRU_LIMIT))); }
  catch { /* quota */ }
}
function _noteMru(id) {
  if (!id) return;
  const list = _loadMru().filter(x => x !== id);
  list.unshift(id);
  _saveMru(list);
}

function _buildCommands() {
  const cmds = [];
  const views = [
    ["/status", "Accueil", "Dashboard principal + KPIs"],
    ["/library", "Bibliothèque", "Workflow 5 étapes"],
    ["/quality", "Qualité", "Scoring + distribution"],
    ["/jellyfin", "Jellyfin", "Intégration Jellyfin"],
    ["/plex", "Plex", "Intégration Plex"],
    ["/radarr", "Radarr", "Candidats upgrade"],
    ["/logs", "Journaux", "Logs live + historique"],
    ["/settings", "Paramètres", "Configuration"],
  ];
  for (const [route, title, hint] of views) {
    cmds.push({
      id: `nav-${route}`,
      title: `Aller vers : ${title}`,
      hint,
      run: () => navigateTo(route),
    });
  }
  cmds.push({
    id: "refresh",
    title: "Rafraîchir la vue",
    hint: "Équivalent F5",
    run: () => window.dispatchEvent(new CustomEvent("cinesort:refresh")),
  });
  cmds.push({
    id: "logout",
    title: "Se déconnecter (token)",
    hint: "Efface le token et retourne au login",
    run: async () => {
      const { clearToken } = await import("../core/state.js");
      clearToken();
      window.location.hash = "#/login";
    },
  });
  return cmds;
}

function _fuzzyScore(text, query) {
  if (!query) return 1;
  const t = text.toLowerCase();
  const q = query.toLowerCase();
  if (t.includes(q)) return 100 - t.indexOf(q);
  let qi = 0;
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi += 1;
  }
  return qi === q.length ? 50 - (t.length - q.length) / 2 : 0;
}

function _ensureOverlay() {
  if (_overlay && document.body.contains(_overlay)) return _overlay;
  _overlay = document.createElement("div");
  _overlay.id = "cmd-palette-overlay";
  _overlay.className = "cmd-palette-overlay hidden";
  _overlay.setAttribute("role", "dialog");
  _overlay.setAttribute("aria-modal", "true");
  _overlay.setAttribute("aria-label", "Palette de commandes");
  _overlay.innerHTML = `
    <div class="cmd-palette">
      <input type="text" class="cmd-palette__input" placeholder="Tapez une commande..." autocomplete="off" spellcheck="false" />
      <ul class="cmd-palette__list" role="listbox"></ul>
      <div class="cmd-palette__hint">↑↓ naviguer · Entrée exécuter · Échap fermer</div>
    </div>`;
  document.body.appendChild(_overlay);
  _input = _overlay.querySelector(".cmd-palette__input");
  _list = _overlay.querySelector(".cmd-palette__list");
  _input.addEventListener("input", _refilter);
  _input.addEventListener("keydown", _onInputKey);
  _overlay.addEventListener("click", (e) => { if (e.target === _overlay) _close(); });
  return _overlay;
}

function _refilter() {
  const q = String(_input.value || "").trim();
  if (!q) {
    const mru = _loadMru();
    const byId = new Map(_commands.map(c => [c.id, c]));
    const recent = mru.map(id => byId.get(id)).filter(Boolean);
    const others = _commands.filter(c => !mru.includes(c.id));
    _filtered = [...recent, ...others];
  } else {
    _filtered = _commands
      .map(c => ({ c, s: Math.max(_fuzzyScore(c.title, q), _fuzzyScore(c.hint || "", q) * 0.6) }))
      .filter(x => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .map(x => x.c);
  }
  _selectedIdx = 0;
  _render();
}

function _render() {
  if (!_list) return;
  if (_filtered.length === 0) {
    _list.innerHTML = '<li class="cmd-palette__empty">Aucune commande</li>';
    return;
  }
  _list.innerHTML = _filtered.map((c, i) => `
    <li class="cmd-palette__item${i === _selectedIdx ? " is-selected" : ""}" data-idx="${i}" role="option">
      <div class="cmd-palette__title"></div>
      <div class="cmd-palette__hint-line"></div>
    </li>`).join("");
  _list.querySelectorAll(".cmd-palette__item").forEach((li, i) => {
    li.querySelector(".cmd-palette__title").textContent = _filtered[i].title;
    li.querySelector(".cmd-palette__hint-line").textContent = _filtered[i].hint || "";
    li.addEventListener("click", () => _execute(i));
    li.addEventListener("mouseenter", () => { _selectedIdx = i; _updateSelection(); });
  });
}

function _updateSelection() {
  _list.querySelectorAll(".cmd-palette__item").forEach((li, i) => {
    li.classList.toggle("is-selected", i === _selectedIdx);
  });
  const sel = _list.children[_selectedIdx];
  if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: "nearest" });
}

function _onInputKey(e) {
  if (e.key === "Escape") { e.preventDefault(); _close(); return; }
  if (e.key === "ArrowDown") { e.preventDefault(); _selectedIdx = Math.min(_filtered.length - 1, _selectedIdx + 1); _updateSelection(); return; }
  if (e.key === "ArrowUp") { e.preventDefault(); _selectedIdx = Math.max(0, _selectedIdx - 1); _updateSelection(); return; }
  if (e.key === "Enter") { e.preventDefault(); _execute(_selectedIdx); return; }
}

function _execute(idx) {
  const cmd = _filtered[idx];
  if (!cmd) return;
  _noteMru(cmd.id);
  _close();
  try { cmd.run(); } catch (e) { console.error("[cmd-palette]", e); }
}

function _open() {
  _commands = _buildCommands();
  _ensureOverlay();
  _overlay.classList.remove("hidden");
  _input.value = "";
  _refilter();
  setTimeout(() => _input.focus(), 30);
}

function _close() {
  if (!_overlay) return;
  _overlay.classList.add("hidden");
}

export function initCommandPalette() {
  // Ctrl+K direct (en plus du keyboard.js qui emet l'event)
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if (_overlay && !_overlay.classList.contains("hidden")) _close();
      else _open();
    }
  });
  // Event global emis par keyboard.js
  window.addEventListener("cinesort:command-palette", _open);
  // Expose pour debug
  window.openCommandPalette = _open;
}
