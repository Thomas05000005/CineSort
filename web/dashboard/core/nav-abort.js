/* core/nav-abort.js — AbortController par navigation (V2-C R4-MEM-6)
 *
 * Pourquoi ?
 *   Plusieurs vues lancent Promise.allSettled([...]) au mount avec 3-6 fetchs
 *   en parallele (status, settings, plan, validation, etc.). Si l'utilisateur
 *   navigate vite (ex: clique 4 onglets en 2s), les anciens fetchs continuent
 *   en arriere-plan et leurs handlers .then() s'executent inutilement => leak
 *   de promesses + parsing JSON en pure perte.
 *
 * Usage :
 *   import { getNavSignal } from "../core/nav-abort.js";
 *   const sig = getNavSignal();
 *   await Promise.allSettled([
 *     apiPost("get_plan", { run_id }, { signal: sig }),
 *     apiPost("get_settings", {}, { signal: sig }),
 *   ]);
 *
 * Le router appelle abortCurrent() avant chaque switch de route, ce qui
 * cancel tous les fetchs en cours qui ont passe ce signal.
 */

let _navController = null;

/**
 * Retourne le signal AbortSignal associe a la navigation courante.
 * Cree un nouveau controller si necessaire (premiere navigation ou apres
 * abortCurrent()).
 */
export function getNavSignal() {
  if (!_navController || _navController.signal.aborted) {
    _navController = new AbortController();
  }
  return _navController.signal;
}

/**
 * Abort tous les fetchs en cours associes a la navigation courante et
 * recree un nouveau controller pour la prochaine vue.
 * Appele par le router avant chaque switch.
 */
export function abortCurrent() {
  if (_navController) {
    try { _navController.abort(); }
    catch { /* noop : le browser peut throw selon le timing */ }
  }
  _navController = null;
}

/**
 * Helper : verifie si une erreur est un AbortError (resultat de abortCurrent).
 * Utile dans les catch des vues pour ignorer silencieusement.
 */
export function isAbortError(err) {
  return !!(err && (err.name === "AbortError" || err.name === "TimeoutError"));
}
