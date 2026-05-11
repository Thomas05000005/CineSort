/* core/drop.js — Drag & drop de dossiers avec overlay visuel
 *
 * Glisser un dossier depuis l'explorateur Windows :
 *   - Overlay "Deposer ici" apparait
 *   - Au drop : valide via backend, ajoute aux roots
 *   - Sur Home : propose de lancer un scan
 *
 * Fallback : si file.path indisponible (limitation pywebview),
 * affiche un message et propose le bouton Parcourir.
 */

let _dropOverlay = null;
let _dragCounter = 0;

/* --- Overlay ------------------------------------------------- */

function _createOverlay() {
  _dropOverlay = document.createElement("div");
  _dropOverlay.className = "drop-overlay hidden";
  _dropOverlay.setAttribute("aria-hidden", "true");
  _dropOverlay.innerHTML = [
    '<div class="drop-zone">',
    '  <div class="drop-icon">&#128193;</div>',
    '  <div class="drop-text">Deposer un dossier pour l\'ajouter aux racines</div>',
    '</div>',
  ].join("");
  document.body.appendChild(_dropOverlay);
}

function _showOverlay() {
  if (!_dropOverlay) return;
  _dropOverlay.classList.remove("hidden");
  _dropOverlay.setAttribute("aria-hidden", "false");
}

function _hideOverlay() {
  if (!_dropOverlay) return;
  _dropOverlay.classList.add("hidden");
  _dropOverlay.setAttribute("aria-hidden", "true");
}

/* --- Event handlers ------------------------------------------ */

function _onDragEnter(e) {
  e.preventDefault();
  if (state.activeModalId) return;
  _dragCounter++;
  if (_dragCounter === 1) _showOverlay();
}

function _onDragLeave() {
  _dragCounter--;
  if (_dragCounter <= 0) { _dragCounter = 0; _hideOverlay(); }
}

function _onDragOver(e) {
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
}

function _onDrop(e) {
  e.preventDefault();
  _dragCounter = 0;
  _hideOverlay();
  if (state.activeModalId) return;
  _processDrop(e);
}

/* --- Drop processing ----------------------------------------- */

async function _processDrop(e) {
  const files = e.dataTransfer?.files;
  if (!files || !files.length) return;

  const file = files[0];
  const path = file.path || file.webkitRelativePath || "";

  if (!path) {
    if (typeof uiInfo === "function") {
      await uiInfo({
        title: "Depot non supporte",
        message: "Le glisser-deposer de dossiers n'est pas disponible dans ce mode. "
               + "Utilisez le bouton Parcourir dans les Réglages pour ajouter un dossier racine.",
      });
    }
    return;
  }

  /* Valider cote backend */
  let result = null;
  if (window.pywebview?.api?.validate_dropped_path) {
    result = await apiCall("validate_drop", () => window.pywebview.api.validate_dropped_path(path));
  } else {
    result = { ok: true, path: path };
  }

  if (!result?.ok) {
    setStatusMessage("planMsg", result?.message || "Chemin invalide.", { error: true, clearMs: 3000 });
    return;
  }

  const resolvedPath = result.path || path;

  /* Verifier doublon */
  const roots = state.settings?.roots || [];
  if (roots.some(r => r.toLowerCase() === resolvedPath.toLowerCase())) {
    setStatusMessage("planMsg", "Ce dossier est deja dans les racines.", { error: false, clearMs: 2500 });
    return;
  }

  /* Action selon la vue */
  if (state.view === "home" && typeof uiConfirm === "function") {
    const scan = await uiConfirm({
      title: "Dossier depose",
      message: "Ajouter \"" + resolvedPath + "\" aux racines et lancer un scan ?",
      confirmLabel: "Scanner",
      cancelLabel: "Ajouter seulement",
    });
    _addDroppedRoot(resolvedPath);
    if (scan && typeof startPlan === "function") startPlan();
  } else {
    _addDroppedRoot(resolvedPath);
  }
}

function _addDroppedRoot(path) {
  if (!state.settings) state.settings = {};
  const roots = state.settings.roots || [];
  roots.push(path);
  state.settings.roots = roots;
  state.settings.root = roots[0] || path;
  if (typeof _renderRootsList === "function") _renderRootsList(roots);
  setStatusMessage("planMsg", "Dossier ajoute : " + path, { success: true, clearMs: 3000 });
}

/* --- Public init --------------------------------------------- */

function initDropHandlers() {
  _createOverlay();
  document.addEventListener("dragenter", _onDragEnter);
  document.addEventListener("dragleave", _onDragLeave);
  document.addEventListener("dragover", _onDragOver);
  document.addEventListener("drop", _onDrop);
}
