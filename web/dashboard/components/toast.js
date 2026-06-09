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
//
// mega-hotfix frontend_ui_polish (#4) : FIFO policy documentee explicitement.
// Quand `_MAX_STACK` est atteint, la strategie d'eviction est FIFO strict :
// le toast le plus ancien (root.firstElementChild, ordre d'insertion DOM) est
// ferme via son close() (cf boucle while plus bas). Cette regle garantit
// que les nouveaux messages restent visibles tout en evitant l'accumulation
// indemontable. Lorsque la stack est saturee (drop d'un toast a cause de
// _MAX_STACK), un console.warn est emis pour faciliter le diagnostic.
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
    // Fix audit 2026-06-07 : borner la duree TOTALE d'un toast fusionne via
    // `firstShownAt` (timestamp original, jamais reset). Sans ce garde-fou,
    // un appelant qui re-emet le meme toast toutes les 1.9s prolonge le
    // dismissTimer indefiniment et le badge xN croit sans limite. On plafonne
    // donc la prochaine duree au temps restant avant _PERSISTENT_MAX_MS depuis
    // le premier affichage. Si le plafond est atteint, fermer immediatement.
    if (existing.dismissTimer != null) {
      clearTimeout(existing.dismissTimer);
      const elapsedSinceFirst = now - (existing.firstShownAt || existing.lastShownAt);
      const remainingTotal = _PERSISTENT_MAX_MS - elapsedSinceFirst;
      if (remainingTotal <= 0) {
        existing.close();
        return;
      }
      const baseDuration = persistent ? _PERSISTENT_MAX_MS : Math.max(1500, duration);
      const nextDuration = Math.min(baseDuration, remainingTotal);
      existing.dismissTimer = setTimeout(existing.close, nextDuration);
    }
    return;
  }

  // Fix audit 2026-05-30 (v1.5.9) TOAST-1 garde-fou (b) MAX-STACK : avant
  // d'ajouter un nouveau toast, si on en a deja _MAX_STACK, fermer le plus
  // ancien (root.firstElementChild = premier insere dans le DOM order).
  // mega-hotfix frontend_ui_polish (#4) : strategie d'eviction = FIFO strict.
  // On warn une seule fois par "vague de saturation" pour faciliter le diag
  // (sans flooder la console si un appelant emet 100 toasts d'affilee).
  const _initialStackSize = root.querySelectorAll(".toast").length;
  if (_initialStackSize >= _MAX_STACK) {
    try {
      console.warn(`[toast] stack saturee (${_initialStackSize}/${_MAX_STACK}) - FIFO drop du plus ancien pour afficher "${text.slice(0, 60)}"`);
    } catch (_e) { /* console inaccessible : noop */ }
  }
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
    firstShownAt: now,
    lastShownAt: now,
    dismissTimer,
    close,
  });
}

/**
 * Purge defensive de tous les toasts actifs et de leurs timers.
 *
 * Fix iter11 famille B (2026-06-08) — garde-fou unmount toast (prolonge 5b3a62c) :
 * permet a un appelant (cleanup global dashboard, navigation hash, logout) de
 * forcer la fermeture immediate de tous les toasts actifs et de nettoyer leurs
 * `setTimeout(close, duration)` pendants. Sans cette API, un toast persistent:true
 * declenche au moment T peut rester planifie jusqu'a T+20000ms (_PERSISTENT_MAX_MS)
 * meme si l'utilisateur quitte la dashboard, ce qui rappelle exactement la
 * categorie de fuite corrigee par 5b3a62c (timers/handlers non nettoyes).
 *
 * Idempotent : appelable plusieurs fois sans erreur. Si aucun toast actif, no-op.
 * Pas exportee par defaut comme API canonique — usage cleanup defensif uniquement.
 */
export function clearAllToasts() {
  // Snapshot des entries pour iteration safe (close() mute _activeToasts).
  const entries = Array.from(_activeToasts.values());
  for (const entry of entries) {
    try {
      if (entry && entry.dismissTimer != null) {
        clearTimeout(entry.dismissTimer);
        entry.dismissTimer = null;
      }
      if (entry && typeof entry.close === "function") {
        entry.close();
      } else if (entry && entry.node && entry.node.parentNode) {
        // Fallback : suppression brutale si close() indisponible.
        entry.node.remove();
      }
    } catch (_e) {
      // Cleanup defensif : aucune erreur ne doit propager.
    }
  }
  // Defense en profondeur : purger le registre meme si certains close() ont
  // echoue silencieusement (entrees orphelines avec node detache).
  _activeToasts.clear();
}
