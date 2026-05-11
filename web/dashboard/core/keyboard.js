/* core/keyboard.js — Raccourcis clavier du dashboard (identiques desktop + distant).
 *
 * - Alt+1..8 OU 1..8 : navigation vers une vue (Alt variant : toujours actif meme dans un input)
 * - Ctrl+S : sauvegarder (emet event "cinesort:save-request")
 * - F5 : rafraichir la vue
 * - F1 / ? : aide
 * - Ctrl+K : command palette
 * - Escape : fermer modale
 */

import { navigateTo } from "./router.js";
import { showModal } from "../components/modal.js";

// 8 onglets : Accueil, Bibliothèque, Qualité, Jellyfin, Plex, Radarr, Journaux, Paramètres
const _ROUTES = ["/status", "/library", "/quality", "/jellyfin", "/plex", "/radarr", "/logs", "/settings"];

function _isInputFocused() {
  const tag = (document.activeElement?.tagName || "").toUpperCase();
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function _showHelp() {
  const body = `
    <table class="tbl shortcuts-table"><tbody>
      <tr><td><kbd>Alt</kbd>+<kbd>1</kbd>...<kbd>8</kbd></td><td>Navigation directe vers une vue</td></tr>
      <tr><td><kbd>1</kbd>...<kbd>8</kbd></td><td>Navigation (hors champ texte)</td></tr>
      <tr><td><kbd>Ctrl</kbd>+<kbd>S</kbd></td><td>Enregistrer</td></tr>
      <tr><td><kbd>Ctrl</kbd>+<kbd>K</kbd></td><td>Palette de commandes</td></tr>
      <tr><td><kbd>F5</kbd></td><td>Rafraîchir la vue</td></tr>
      <tr><td><kbd>?</kbd> ou <kbd>F1</kbd></td><td>Afficher cette aide</td></tr>
      <tr><td><kbd>Escape</kbd></td><td>Fermer la modale</td></tr>
    </tbody></table>`;
  showModal({ title: "Raccourcis clavier", body });
}

export function initKeyboard() {
  document.addEventListener("keydown", (e) => {
    // 1. Escape : fermer la modale ouverte (priorite maximale)
    if (e.key === "Escape") {
      const overlay = document.querySelector(".modal-overlay");
      if (overlay) {
        const closeBtn = overlay.querySelector(".modal-close-btn");
        if (closeBtn) closeBtn.click();
        e.preventDefault();
        return;
      }
    }

    // 2. Alt+1..8 : navigation (toujours actif, meme dans un input)
    if (e.altKey && !e.ctrlKey && !e.shiftKey && e.key >= "1" && e.key <= "8") {
      const idx = parseInt(e.key, 10);
      if (idx >= 1 && idx <= _ROUTES.length) {
        e.preventDefault();
        navigateTo(_ROUTES[idx - 1]);
        return;
      }
    }

    // 3. Ctrl+S : save (emet event pour les vues interessees)
    if (e.ctrlKey && e.key.toLowerCase() === "s" && !e.altKey && !e.shiftKey) {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent("cinesort:save-request"));
      return;
    }

    // 4. Ctrl+K : command palette
    if (e.ctrlKey && e.key.toLowerCase() === "k" && !e.altKey && !e.shiftKey) {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent("cinesort:command-palette"));
      return;
    }

    // 5. F1 : aide
    if (e.key === "F1") {
      e.preventDefault();
      _showHelp();
      return;
    }

    // 6. F5 : refresh (geré aussi dans app.js via bouton)
    if (e.key === "F5") {
      e.preventDefault();
      window.dispatchEvent(new CustomEvent("cinesort:refresh"));
      return;
    }

    // Pour les raccourcis suivants, ignore si champ texte est focus
    if (_isInputFocused()) return;

    // 7. ? : aide raccourcis
    if (e.key === "?") {
      e.preventDefault();
      _showHelp();
      return;
    }

    // 8. 1-8 : navigation directe (sans modifier, hors input)
    const num = parseInt(e.key);
    if (num >= 1 && num <= _ROUTES.length) {
      e.preventDefault();
      navigateTo(_ROUTES[num - 1]);
    }
  });
}
