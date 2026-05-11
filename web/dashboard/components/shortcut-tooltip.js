/* components/shortcut-tooltip.js — V3-08 : kbd hints sur boutons principaux.
 *
 * Decouvrabilite des raccourcis clavier : la sidebar v5 expose deja `data-shortcut`
 * et le selecteur sidebar legacy ne montre rien. Ce module fournit deux primitives :
 *
 *   - kbdHint(keys)         : genere `<span class="kbd-hint"><kbd>...</kbd></span>`
 *   - decorateWithKbd(t, k) : injecte ce span a la fin d'un bouton existant
 *
 * Idempotent : si le bouton porte deja un `.kbd-hint`, on ne re-injecte rien.
 * Les composants v5 (sidebar v5) ont leur propre rendu et n'utilisent pas ces
 * helpers : on ne touche que la sidebar legacy + boutons globaux topbar.
 */

import { escapeHtml } from "../core/dom.js";

/**
 * Genere le HTML d'un indicateur "raccourci clavier".
 * @param {string} keys - Combinaison ex. "Ctrl+K", "Alt+3", "?"
 * @returns {string} HTML serialise (vide si keys falsy)
 */
export function kbdHint(keys) {
  if (!keys) return "";
  const parts = String(keys).split("+").map((k) => `<kbd>${escapeHtml(k)}</kbd>`).join("+");
  return `<span class="kbd-hint" aria-hidden="true" data-shortcut="${escapeHtml(keys)}">${parts}</span>`;
}

/**
 * Decore un bouton existant avec son raccourci clavier (idempotent).
 * @param {HTMLElement|string} target - element ou selecteur CSS
 * @param {string} keys
 */
export function decorateWithKbd(target, keys) {
  if (!keys) return;
  const el = typeof target === "string" ? document.querySelector(target) : target;
  if (!el || el.querySelector(":scope > .kbd-hint")) return;
  el.insertAdjacentHTML("beforeend", " " + kbdHint(keys));
}

/* --- Catalogue des raccourcis decores ------------------------ */

/** Raccourcis dispatches par dashboard/core/keyboard.js (Alt+1..8). */
const SIDEBAR_SHORTCUTS = [
  { selector: '.nav-btn[data-route="/status"]',   keys: "Alt+1" },
  { selector: '.nav-btn[data-route="/library"]',  keys: "Alt+2" },
  { selector: '.nav-btn[data-route="/quality"]',  keys: "Alt+3" },
  { selector: '.nav-btn[data-route="/jellyfin"]', keys: "Alt+4" },
  { selector: '.nav-btn[data-route="/plex"]',     keys: "Alt+5" },
  { selector: '.nav-btn[data-route="/radarr"]',   keys: "Alt+6" },
  { selector: '.nav-btn[data-route="/logs"]',     keys: "Alt+7" },
  { selector: '.nav-btn[data-route="/settings"]', keys: "Alt+8" },
];

/**
 * Decoration globale au boot du dashboard : ajoute les `<kbd>` aux boutons de
 * navigation principaux (sidebar legacy). La topbar a deja un `<kbd>Ctrl+K</kbd>`
 * codé en dur dans index.html, et la sidebar v5 expose son propre rendu.
 */
export function decorateMainButtons() {
  for (const it of SIDEBAR_SHORTCUTS) {
    const btn = document.querySelector(it.selector);
    if (!btn) continue;
    // Cible : on injecte dans le bouton, en fin (apres l'icone et le label)
    decorateWithKbd(btn, it.keys);
  }
}
