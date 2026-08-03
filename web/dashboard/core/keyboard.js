/* core/keyboard.js — Raccourcis clavier du dashboard (identiques desktop + distant).
 *
 * Phase 2-C (spec 04 §5) : raccourcis transverses du Shell 3 zones :
 * - Alt+1..7 OU 1..7 : navigation directe (Alt variant : toujours actif meme dans un input)
 * - Ctrl+B : toggle sidebar repliee / deployee
 * - Ctrl+I : toggle inspecteur droit
 * - Ctrl+, : aller a Parametres
 * - Ctrl+K : command palette
 * - Ctrl+S : sauvegarder (emet event "cinesort:save-request")
 * - F5 : rafraichir (emet event "cinesort:refresh", ecoute par app.js)
 * - F1 / ? : aide
 * - Escape : fermer modale / palette
 */

import { navigateTo } from "./router.js";
import { showModal } from "../components/modal.js";
import { toggleCollapsed as toggleSidebar } from "../components/sidebar-v5.js";
import { isExpanded as isRightPanelExpanded, setExpanded as setRightPanelExpanded } from "../components/right-panel.js";

// Phase 2-B : routes FR canoniques pour Alt+1..7 (spec 04 §2.3).
// 7 entrees : Accueil, Traitement, Bibliotheque, Qualite, Historique, Parametres, Aide.
const _ROUTES = ["/accueil", "/traitement", "/bibliotheque", "/qualite", "/historique", "/parametres", "/aide"];

function _isInputFocused() {
  const tag = (document.activeElement?.tagName || "").toUpperCase();
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function _showHelp() {
  // Cf #92 quick win #7 : la modale reste un acces rapide aux raccourcis
  // (utile pour le power user en cours de navigation) mais expose maintenant
  // un lien explicite vers /help qui contient FAQ + glossaire en plus des
  // raccourcis. Resout l'incoherence "2 portes" remontee par l'audit :
  // l'utilisateur sait desormais qu'il y a plus de contenu disponible.
  const body = `
    <table class="tbl shortcuts-table"><tbody>
      <tr><td><kbd>Alt</kbd>+<kbd>1</kbd>...<kbd>7</kbd></td><td>Navigation directe vers une vue (Accueil ... Aide)</td></tr>
      <tr><td><kbd>1</kbd>...<kbd>7</kbd></td><td>Navigation (hors champ texte)</td></tr>
      <tr><td><kbd>Ctrl</kbd>+<kbd>K</kbd></td><td>Palette de commandes (recherche globale)</td></tr>
      <tr><td><kbd>Ctrl</kbd>+<kbd>B</kbd></td><td>Replier ou deployer la sidebar</td></tr>
      <tr><td><kbd>Ctrl</kbd>+<kbd>I</kbd></td><td>Afficher ou masquer l'inspecteur droit</td></tr>
      <tr><td><kbd>Ctrl</kbd>+<kbd>,</kbd></td><td>Aller a Parametres</td></tr>
      <tr><td><kbd>Ctrl</kbd>+<kbd>S</kbd></td><td>Enregistrer</td></tr>
      <tr><td><kbd>F5</kbd></td><td>Rafraichir la vue</td></tr>
      <tr><td><kbd>?</kbd> ou <kbd>F1</kbd></td><td>Afficher cette aide</td></tr>
      <tr><td><kbd>Escape</kbd></td><td>Fermer la modale</td></tr>
    </tbody></table>
    <p class="mt-4 text-muted">Aide complete (FAQ, glossaire, raccourcis de validation) : <a href="#/aide" class="link-primary" id="kbd-help-full-link">Voir l'aide complète &rarr;</a></p>`;
  showModal({ title: "Raccourcis clavier", body });
  // Auto-ferme la modale quand l'utilisateur clique le lien (sinon le clic
  // navigue mais la modale reste affichee, masquant le contenu de /help).
  setTimeout(() => {
    const link = document.getElementById("kbd-help-full-link");
    if (link) {
      link.addEventListener("click", () => {
        const overlay = document.querySelector(".modal-overlay");
        const closeBtn = overlay?.querySelector(".modal-close-btn");
        if (closeBtn) closeBtn.click();
      });
    }
  }, 0);
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

    // 2. Alt+1..7 : navigation (toujours actif, meme dans un input)
    if (e.altKey && !e.ctrlKey && !e.shiftKey && e.key >= "1" && e.key <= "7") {
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

    // Phase 2-C (spec 04 §5) : Ctrl+B toggle sidebar (collapsed / expanded).
    if (e.ctrlKey && e.key.toLowerCase() === "b" && !e.altKey && !e.shiftKey) {
      e.preventDefault();
      try { toggleSidebar(); } catch (err) { console.warn("[keyboard] toggle sidebar failed:", err); }
      return;
    }

    // Phase 2-C : Ctrl+I toggle inspecteur droit.
    if (e.ctrlKey && e.key.toLowerCase() === "i" && !e.altKey && !e.shiftKey) {
      e.preventDefault();
      try { setRightPanelExpanded(!isRightPanelExpanded()); }
      catch (err) { console.warn("[keyboard] toggle right panel failed:", err); }
      return;
    }

    // Phase 2-C : Ctrl+, aller a Parametres.
    if (e.ctrlKey && e.key === "," && !e.altKey && !e.shiftKey) {
      e.preventDefault();
      navigateTo("/parametres");
      return;
    }

    // 4b. Ctrl+Z : SUPPRIME (ultra-audit 2026-08-03, N01/N08).
    //
    // Le raccourci (#92 quick win #3) dispatchait `cinesort:undo-shortcut`, un
    // evenement que PLUS AUCUN module n'ecoutait : son unique auditeur vivait
    // dans library/lib-apply.js, disparu a la migration ESM. Ctrl+Z consommait
    // donc la frappe (preventDefault) pour ne rien faire, pendant que la modale
    // d'aide et /aide promettaient « Annuler la derniere application ».
    //
    // On ne le recable pas non plus, pour une raison de CIBLE, pas de
    // confirmation. Correction d'une justification fausse ecrite ici lors du
    // lot NUANCES (PR #873) et relevee en relecture : invoquer la regle des
    // actions destructives etait un homme de paille. Personne ne proposait de
    // cabler une frappe nue sur `run/undo_last_apply` ; le brancher sur
    // `_onUndoExecute` (traitement.js) ou `_doUndoApply` (historique.js) aurait
    // conserve `dangerConfirmModal` et n'aurait donc rien viole. Une regle
    // projet mal invoquee dans le depot est pire que pas de justification :
    // elle finit citee ailleurs.
    //
    // Le vrai motif : l'undo n'a pas de cible non ambigue depuis un raccourci
    // GLOBAL. Il porte sur un batch precis — `_runInfo.pendingUndo` cote
    // Traitement, le run selectionne cote Historique — etat qui n'existe que
    // dans la vue montee. Depuis /parametres ou /bibliotheque, Ctrl+Z n'aurait
    // aucun batch a designer, et depuis Historique il devrait deviner lequel
    // des runs listes viser. L'undo reste donc accessible par ses deux boutons
    // dedies (Traitement etape 5, Historique -> « Annuler l'apply »), la ou la
    // cible est explicite — tous deux derriere `dangerConfirmModal`.

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

    // 8. 1-7 : navigation directe (sans modifier, hors input)
    const num = parseInt(e.key);
    if (num >= 1 && num <= _ROUTES.length) {
      e.preventDefault();
      navigateTo(_ROUTES[num - 1]);
    }
  });
}
