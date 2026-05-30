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

// Fix audit 2026-05-30 (v1.5.9) TOAST-1 : defense en profondeur contre le
// flooding de toasts (5 clics rapides sur bulk-approve = 5 toasts persistants
// qui restent eternellement). Trois garde-fous independants :
//   - _MAX_STACK : jamais plus de 4 toasts simultanes ; le plus ancien est
//     ferme programmatiquement quand un nouveau arrive.
//   - _DEDUP_WINDOW_MS : 2 toasts identiques (meme type + meme texte) dans
//     les 2000ms suivants fusionnent en un badge "xN" sur le toast existant.
//   - _PERSISTENT_MAX_MS : meme un toast persistent: true se ferme apres
//     20s, safety net pour eviter qu'il reste 1h+ a l'ecran.
const _MAX_STACK = 4;
const _DEDUP_WINDOW_MS = 2000;
const _PERSISTENT_MAX_MS = 20000;

// Registre interne des toasts actifs : Map<key, entry>
//   key   = `${normalizedType}|${text}`
//   entry = { node, count, countBadge, lastShownAt, dismissTimer, close }
const _activeToasts = new Map();

/**
 * Affiche un toast bottom-right.
 * @param {{type?:"info"|"success"|"warning"|"warn"|"error", text:string, duration?:number, action?:{label:string, onClick:Function}, persistent?:boolean}} opts
 *
 * Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high UX-03 : ajout des options
 * `action` (bouton inline "Annuler", "Voir", etc.) et `persistent` (le toast
 * ne se ferme pas auto, l'utilisateur doit cliquer Annuler / close (x)).
 * Remplace les patterns setTimeout 5s + variable globale window._snapshot qui
 * cachaient l'option Undo a l'utilisateur (cf _handleBulkApprove).
 */
export function showToast(opts) {
  const { type = "info", text = "", action = null, persistent = false } = opts || {};
  if (!text) return;
  // Fix audit 2026-05-24 : "warn" mappe sur "warning" pour aligner avec le
  // reste de la dashboard (notification-center, css .toast--warning, etc).
  const normalizedType = _normalizeType(type);
  // Fix audit 2026-05-25 (v1.5.3) Vague H : duree par defaut selon type, override possible
  const duration = (opts && opts.duration != null)
    ? opts.duration
    : (_DEFAULT_DURATIONS[normalizedType] || 4000);
  const root = _ensureContainer();

  // Fix audit 2026-05-30 (v1.5.9) TOAST-1 garde-fou (a) DEDUP : si un toast
  // identique a ete affiche dans les _DEDUP_WINDOW_MS, ne pas creer de
  // nouveau node : incrementer le compteur, mettre a jour le badge "xN",
  // reset le timer de close. Retourner sans creer de nouveau node.
  const dedupKey = `${normalizedType}|${text}`;
  const existing = _activeToasts.get(dedupKey);
  const now = Date.now();
  if (existing && (now - existing.lastShownAt) < _DEDUP_WINDOW_MS && document.body.contains(existing.node)) {
    existing.count += 1;
    existing.lastShownAt = now;
    let badge = existing.countBadge;
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "toast__count";
      // Style minimal inline en fallback si le CSS .toast__count n'existe pas.
      badge.style.marginLeft = "auto";
      badge.style.opacity = "0.7";
      badge.style.fontSize = "0.8em";
      // Insertion avant le bouton close (dernier enfant).
      const closeBtn = existing.node.querySelector(".toast__close");
      if (closeBtn) existing.node.insertBefore(badge, closeBtn);
      else existing.node.appendChild(badge);
      existing.countBadge = badge;
    }
    badge.textContent = `x${existing.count}`;
    // Reset du timer de close pour prolonger la visibilite du toast fusionne.
    if (existing.dismissTimer != null) {
      clearTimeout(existing.dismissTimer);
      const nextDuration = persistent ? _PERSISTENT_MAX_MS : Math.max(1500, duration);
      existing.dismissTimer = setTimeout(existing.close, nextDuration);
    }
    return;
  }

  // Fix audit 2026-05-30 (v1.5.9) TOAST-1 garde-fou (b) MAX-STACK : avant
  // d'ajouter un nouveau toast, si on en a deja _MAX_STACK, fermer le plus
  // ancien (root.firstElementChild = premier insere dans le DOM order).
  while (root.querySelectorAll(".toast").length >= _MAX_STACK) {
    const oldest = root.firstElementChild;
    if (!oldest) break;
    // Trouver son entree dans _activeToasts pour invoquer son close() propre.
    let oldestEntry = null;
    for (const [, entry] of _activeToasts) {
      if (entry.node === oldest) { oldestEntry = entry; break; }
    }
    if (oldestEntry && typeof oldestEntry.close === "function") {
      oldestEntry.close();
    } else {
      // Fallback : suppression brutale si pas d'entree (toast oublie).
      oldest.classList.add("toast--out");
      const stale = oldest;
      setTimeout(() => stale.remove(), 220);
      // Eviter une boucle infinie si la suppression est asynchrone.
      stale.remove();
    }
  }

  const node = document.createElement("div");
  node.className = `toast toast--${normalizedType}${action ? " toast--has-action" : ""}${persistent ? " toast--persistent" : ""}`;
  node.setAttribute("role", "status");
  // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high UX-03 : bouton action
  // inline rendu via DOM (pas innerHTML) pour eviter l'echappement HTML du label.
  node.innerHTML = `<span class="toast__icon">${_icon(normalizedType)}</span><span class="toast__text"></span><button class="toast__close" aria-label="Fermer" type="button">×</button>`;
  node.querySelector(".toast__text").textContent = text;

  const close = () => {
    node.classList.add("toast--out");
    setTimeout(() => node.remove(), 220);
    // Fix audit 2026-05-30 (v1.5.9) TOAST-1 : nettoyer le registre interne
    // pour eviter qu'un dedupKey reste lie a un node detache du DOM.
    const entry = _activeToasts.get(dedupKey);
    if (entry && entry.node === node) {
      if (entry.dismissTimer != null) clearTimeout(entry.dismissTimer);
      _activeToasts.delete(dedupKey);
    }
  };

  // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high UX-03 : insertion du
  // bouton d'action AVANT le close (×), apres le texte. Sur clic : execute
  // le callback puis ferme le toast.
  if (action && typeof action.onClick === "function" && action.label) {
    const actionBtn = document.createElement("button");
    actionBtn.type = "button";
    actionBtn.className = "toast__action v5-btn v5-btn--sm v5-btn--ghost";
    actionBtn.textContent = String(action.label);
    actionBtn.addEventListener("click", () => {
      try { action.onClick(); } finally { close(); }
    });
    // Insertion avant le bouton de fermeture (dernier enfant).
    node.insertBefore(actionBtn, node.querySelector(".toast__close"));
  }

  root.appendChild(node);
  node.querySelector(".toast__close").addEventListener("click", close);
  // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high UX-03 : si persistent,
  // pas d'auto-dismiss standard. Fix audit 2026-05-30 (v1.5.9) TOAST-1
  // garde-fou (c) : meme persistent, on plafonne a _PERSISTENT_MAX_MS pour
  // qu'un toast ne reste jamais coince eternellement (safety net).
  let dismissTimer = null;
  if (persistent) {
    dismissTimer = setTimeout(close, _PERSISTENT_MAX_MS);
  } else {
    dismissTimer = setTimeout(close, Math.max(1500, duration));
  }

  // Fix audit 2026-05-30 (v1.5.9) TOAST-1 : enregistrer ce toast pour le
  // dedup window suivant.
  _activeToasts.set(dedupKey, {
    node,
    count: 1,
    countBadge: null,
    lastShownAt: now,
    dismissTimer,
    close,
  });
}
