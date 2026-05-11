/* _legacy_compat.js — V6 : ES module remplaçant `_legacy_globals.js`
 *
 * Ce module expose les 14 helpers historiques du webview legacy (state, apiCall,
 * setStatusMessage, etc.) sous forme d'imports ESM propres, plutôt que via des
 * globals window.X comme le faisait `_legacy_globals.js`.
 *
 * Comportement : identique au shim original (stubs no-op pour la plupart) afin
 * de ne provoquer AUCUNE régression. Les implémentations réelles peuvent être
 * branchées ici plus tard si on veut restaurer les features correspondantes.
 *
 * Pourquoi : le shim global polluait `window`, masquait les dépendances réelles,
 * et empêchait le tree-shaking. Avec ce module ESM, chaque vue déclare
 * explicitement ce qu'elle utilise via `import { ... } from "./_legacy_compat.js"`.
 */

/** Singleton state partagé entre les vues v5 (anciennement window.state). */
export const state = {};

/**
 * Appel API legacy. Stub no-op résolvant un objet vide.
 * Note : préférer `apiPost` depuis `./_v5_helpers.js` pour les nouveaux appels.
 */
export function apiCall() {
  return Promise.resolve({});
}

/** Marque visuelle d'un état (pill UI). Stub no-op. */
export function setPill() {}

/** Message de statut UI. Stub no-op. */
export function setStatusMessage() {}

/** Animation flash sur un bouton d'action. Stub no-op. */
export function flashActionButton() {}

/** Définit le contexte du dernier run (pour reprises). Stub no-op. */
export function setLastRunContext() {}

/** Append des logs dans la zone log. Stub no-op. */
export function appendLogs() {}

/** Charge un tableau de données. Stub no-op. */
export function loadTable() {}

/** Affiche une vue (legacy showView). Stub no-op. */
export function showView() {}

/** Ouvre un chemin via l'OS avec feedback. Stub no-op. */
export function openPathWithFeedback() {}

/** Réinitialise l'état scoped à un run. Stub no-op. */
export function resetRunScopedState() {}

/** Format une vitesse pour affichage. Identité string par défaut. */
export function fmtSpeed(v) {
  return String(v == null ? "" : v);
}

/** Format un ETA en secondes pour affichage. Identité string par défaut. */
export function fmtEta(s) {
  return String(s == null ? "" : s);
}

/** Raccourcit un chemin pour affichage. Identité string par défaut. */
export function shortPath(p) {
  return String(p == null ? "" : p);
}

/**
 * Confirmation modale UI legacy. Fallback sur window.confirm si dispo.
 * Note : préférer un composant modal v5 pour les nouvelles UI.
 */
export function uiConfirm(msg) {
  if (typeof globalThis.confirm === "function") {
    return Promise.resolve(globalThis.confirm(msg));
  }
  return Promise.resolve(true);
}
