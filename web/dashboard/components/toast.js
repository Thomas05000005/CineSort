/* components/toast.js — Toasts globaux dashboard (D5)
 *
 * Empile bottom-right, auto-dismiss apres `duration` ms (defaut 4 s).
 * Usage : import { showToast } from "../components/toast.js";
 */

let _container = null;

function _ensureContainer() {
  if (_container && document.body.contains(_container)) return _container;
  _container = document.createElement("div");
  _container.id = "toast-container";
  _container.setAttribute("aria-live", "polite");
  _container.setAttribute("aria-atomic", "false");
  document.body.appendChild(_container);
  return _container;
}

// Fix audit 2026-05-24 : alignement du type "warn" (legacy toast.js) avec
// "warning" (utilise par notification-center.js et tous les autres composants
// de la dashboard). Avant, un caller utilisant type:"warning" recevait l'icone
// info par defaut + une classe CSS .toast--warning sans style attache. On
// accepte les 2 maintenant, en preservant "warn" comme alias retro-compatible.
function _normalizeType(type) {
  if (type === "warn") return "warning";
  return type;
}

function _icon(type) {
  const t = _normalizeType(type);
  if (t === "success") return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
  if (t === "error") return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
  if (t === "warning") return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
  return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
}

// Fix audit 2026-05-25 (v1.5.3) Vague H : durees differenciees par type pour UX/A11Y.
// Les erreurs doivent rester visibles plus longtemps (l'utilisateur doit pouvoir lire le
// message technique et eventuellement l'aria-live). Les info/success sont volatiles.
const _DEFAULT_DURATIONS = {
  info: 4000,
  success: 4000,
  warning: 7000,
  error: 10000,
};

/**
 * Affiche un toast bottom-right.
 * @param {{type?:"info"|"success"|"warning"|"warn"|"error", text:string, duration?:number}} opts
 */
export function showToast(opts) {
  const { type = "info", text = "" } = opts || {};
  if (!text) return;
  // Fix audit 2026-05-24 : "warn" mappe sur "warning" pour aligner avec le
  // reste de la dashboard (notification-center, css .toast--warning, etc).
  const normalizedType = _normalizeType(type);
  // Fix audit 2026-05-25 (v1.5.3) Vague H : duree par defaut selon type, override possible
  const duration = (opts && opts.duration != null)
    ? opts.duration
    : (_DEFAULT_DURATIONS[normalizedType] || 4000);
  const root = _ensureContainer();
  const node = document.createElement("div");
  node.className = `toast toast--${normalizedType}`;
  node.setAttribute("role", "status");
  node.innerHTML = `<span class="toast__icon">${_icon(normalizedType)}</span><span class="toast__text"></span><button class="toast__close" aria-label="Fermer" type="button">×</button>`;
  node.querySelector(".toast__text").textContent = text;
  root.appendChild(node);

  const close = () => {
    node.classList.add("toast--out");
    setTimeout(() => node.remove(), 220);
  };
  node.querySelector(".toast__close").addEventListener("click", close);
  setTimeout(close, Math.max(1500, duration));
}
