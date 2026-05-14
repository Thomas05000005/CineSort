/* core/drop.js — Drag & drop dossiers (mode natif pywebview uniquement).
 *
 * Port desktop -> dashboard, activé si window.__CINESORT_NATIVE__.
 * Dans un navigateur distant, le drop n'a pas accès au chemin filesystem
 * (limitation HTML5). Donc on no-op silencieusement.
 */

import { apiPost } from "./api.js";

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
    alert("Le glisser-déposer de dossiers requiert le mode natif (desktop). Utilisez le bouton Parcourir dans les Paramètres.");
    return;
  }
  const result = await apiPost("validate_dropped_path", { path });
  if (!result?.data?.ok) {
    alert(result?.data?.message || "Chemin invalide.");
    return;
  }
  const resolved = result.data.path || path;
  // Charger settings courants, ajouter le root, sauver
  const sr = await apiPost("settings/get_settings");
  const s = sr?.data || {};
  const roots = Array.isArray(s.roots) ? s.roots.slice() : (s.root ? [s.root] : []);
  if (roots.some(r => String(r).toLowerCase() === resolved.toLowerCase())) {
    alert("Ce dossier est déjà dans les racines.");
    return;
  }
  roots.push(resolved);
  const newSettings = { ...s, roots, root: roots[0] };
  const save = await apiPost("settings/save_settings", { settings: newSettings });
  if (save?.data?.ok) {
    alert(`Dossier ajouté : ${resolved}`);
    // Recharger la vue courante
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else {
    alert("Impossible d'enregistrer le dossier.");
  }
}

/** Active le drag & drop si on est en mode natif (pywebview). */
export function initDropHandlers() {
  if (!window.__CINESORT_NATIVE__) {
    console.log("[dash-drop] mode non-natif, drag-drop desactive");
    return;
  }
  _createOverlay();
  document.addEventListener("dragenter", _onDragEnter);
  document.addEventListener("dragleave", _onDragLeave);
  document.addEventListener("dragover", _onDragOver);
  document.addEventListener("drop", _onDrop);
  console.log("[dash-drop] drag-drop natif active");
}
