/* core/drop.js — Drag & drop dossiers (mode natif pywebview uniquement).
 *
 * Port desktop -> dashboard, activé si window.__CINESORT_NATIVE__.
 * Dans un navigateur distant, le drop n'a pas accès au chemin filesystem
 * (limitation HTML5). Donc on no-op silencieusement.
 */

import { apiPost } from "./api.js";
// Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplacer alert() natifs
// par showToast pour notifications non destructives (drop & drop est informatif).
import { showToast } from "../components/toast.js";

let _overlay = null;
let _counter = 0;

function _createOverlay() {
  _overlay = document.createElement("div");
  _overlay.className = "drop-overlay hidden";
  _overlay.setAttribute("aria-hidden", "true");
  _overlay.innerHTML = `
    <div class="drop-zone">
      <div class="drop-icon">&#128193;</div>
      <div class="drop-text">Déposer un dossier pour l'ajouter aux racines</div>
    </div>`;
  document.body.appendChild(_overlay);
}

function _show() { _overlay?.classList.remove("hidden"); _overlay?.setAttribute("aria-hidden", "false"); }
function _hide() { _overlay?.classList.add("hidden"); _overlay?.setAttribute("aria-hidden", "true"); }

function _onDragEnter(e) {
  e.preventDefault();
  if (document.querySelector(".modal-overlay:not(.hidden)")) return;
  _counter++;
  if (_counter === 1) _show();
}
function _onDragLeave() { _counter--; if (_counter <= 0) { _counter = 0; _hide(); } }
function _onDragOver(e) { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = "copy"; }
function _onDrop(e) {
  e.preventDefault();
  _counter = 0;
  _hide();
  _processDrop(e);
}

async function _processDrop(e) {
  const files = e.dataTransfer?.files;
  if (!files || !files.length) return;
  const file = files[0];
  const path = file.path || file.webkitRelativePath || "";
  if (!path) {
    // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
    showToast({ type: "warning", text: "Le glisser-déposer de dossiers requiert le mode natif (desktop). Utilisez le bouton Parcourir dans les Paramètres." });
    return;
  }
  const result = await apiPost("runtime/validate_dropped_path", { path });
  if (!result?.data?.ok) {
    // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
    showToast({ type: "error", text: result?.data?.message || "Chemin invalide." });
    return;
  }
  const resolved = result.data.path || path;
  // Charger settings courants, ajouter le root, sauver
  const sr = await apiPost("settings/get_settings");
  const s = sr?.data || {};
  const roots = Array.isArray(s.roots) ? s.roots.slice() : (s.root ? [s.root] : []);
  if (roots.some(r => String(r).toLowerCase() === resolved.toLowerCase())) {
    // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
    showToast({ type: "info", text: "Ce dossier est déjà dans les racines." });
    return;
  }
  roots.push(resolved);
  const newSettings = { ...s, roots, root: roots[0] };
  const save = await apiPost("settings/save_settings", { settings: newSettings });
  if (save?.data?.ok) {
    // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
    showToast({ type: "success", text: `Dossier ajouté : ${resolved}` });
    // Recharger la vue courante
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else {
    // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace alert() natif
    showToast({ type: "error", text: "Impossible d'enregistrer le dossier." });
  }
}

/** Active le drag & drop si on est en mode natif (pywebview). */
export function initDropHandlers() {
  if (!window.__CINESORT_NATIVE__) {
    return;
  }
  _createOverlay();
  document.addEventListener("dragenter", _onDragEnter);
  document.addEventListener("dragleave", _onDragLeave);
  document.addEventListener("dragover", _onDragOver);
  document.addEventListener("drop", _onDrop);
}
