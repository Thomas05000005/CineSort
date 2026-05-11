/* core/keyboard.js — Dispatcher central raccourcis clavier
 *
 * Priorite :
 *   1. Modal ouverte → ne rien faire (modal.js gere Escape/Tab)
 *   2. Modifier keys (Alt+N, Ctrl+S, F5) → toujours actifs, meme dans un input
 *   3. Focus dans input/select/textarea → ne rien faire (laisser taper)
 *   4. Vue specifique → dispatch selon state.view
 *   5. Global sans modifier (?, F1) → executer
 */

// Sidebar restauree : Accueil, Validation, Application, Qualite,
// Jellyfin, Plex, Radarr, Journaux, Parametres (9 onglets)
const _KB_VIEWS = ["home", "validation", "execution", "quality", "jellyfin", "plex", "radarr", "history", "settings"];

function _isInputFocused() {
  return !!document.activeElement?.closest("input,select,textarea");
}

/* --- Refresh helpers ----------------------------------------- */

function _refreshCurrentView() {
  const v = state.view;
  if (v === "home" && typeof refreshHomeOverview === "function") refreshHomeOverview();
  else if (v === "validation" && typeof ensureValidationLoaded === "function") ensureValidationLoaded();
  else if (v === "quality" && typeof refreshQualityView === "function") refreshQualityView();
  else if (v === "history" && typeof refreshHistoryView === "function") refreshHistoryView();
  else if (v === "execution" && typeof refreshExecutionView === "function") refreshExecutionView();
  else if (v === "jellyfin" && typeof refreshJellyfinView === "function") refreshJellyfinView();
  else if (v === "plex" && typeof refreshPlexView === "function") refreshPlexView();
  else if (v === "radarr" && typeof refreshRadarrView === "function") refreshRadarrView();
  else if (v === "settings" && typeof loadSettings === "function") loadSettings();
}

/* --- Validation-specific keys -------------------------------- */

function _handleValidationKey(e) {
  const filtered = typeof getFilteredRows === "function" ? getFilteredRows() : [];
  if (!filtered.length) return;
  const idx = filtered.findIndex(r => r.row_id === state.selectedRowId);

  if (e.key === "ArrowDown" || e.key === "j") {
    e.preventDefault();
    const next = filtered[idx + 1];
    if (next && typeof selectValidationRow === "function") selectValidationRow(next);
  } else if (e.key === "ArrowUp" || e.key === "k") {
    e.preventDefault();
    const prev = filtered[idx - 1];
    if (prev && typeof selectValidationRow === "function") selectValidationRow(prev);
  } else if (e.key === " " || e.key === "a" || e.key === "A") {
    e.preventDefault();
    if (idx >= 0) {
      const dec = currentDecision(filtered[idx]);
      dec.ok = !dec.ok;
      if (typeof renderTable === "function") renderTable();
    }
  } else if (e.key === "r" || e.key === "R") {
    if (idx >= 0) {
      currentDecision(filtered[idx]).ok = false;
      if (typeof renderTable === "function") renderTable();
    }
  } else if (e.key === "i" || e.key === "I") {
    /* Scroll vers l'inspecteur */
    const inspector = $("inspectorBody");
    if (inspector) inspector.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } else if (e.ctrlKey && (e.key === "a" || e.key === "A")) {
    /* Ctrl+A : approuver tout le filtre */
    e.preventDefault();
    for (const row of filtered) { currentDecision(row).ok = true; }
    if (typeof renderTable === "function") renderTable();
  } else if (e.key === "Escape") {
    state.selectedRowId = "";
    if (typeof renderTable === "function") renderTable();
    if (typeof renderInspector === "function") renderInspector(null);
  }
}

/* --- Central dispatcher -------------------------------------- */

function _dispatchKeydown(e) {
  /* 1. Modal ouverte → laisser modal.js gerer */
  if (state.activeModalId) return;

  /* 2. Alt+1-9 : navigation (toujours, meme dans un input) — 9 vues depuis V4 */
  if (e.altKey && !e.ctrlKey && !e.shiftKey && e.key >= "1" && e.key <= "9") {
    const idx = parseInt(e.key, 10) - 1;
    if (idx < _KB_VIEWS.length) {
      e.preventDefault();
      navigateTo(_KB_VIEWS[idx]);
      return;
    }
  }

  /* 3. Ctrl+S : sauvegarder decisions */
  if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "s" || e.key === "S")) {
    e.preventDefault();
    if (typeof persistValidation === "function") persistValidation();
    return;
  }

  /* 4. F5 : rafraichir vue courante */
  if (e.key === "F5") {
    e.preventDefault();
    _refreshCurrentView();
    return;
  }

  /* 5. Skip si focus dans input (pour les raccourcis sans modifier) */
  if (_isInputFocused()) return;

  /* 6. ? ou F1 : modale raccourcis */
  if (e.key === "?" || e.key === "F1") {
    e.preventDefault();
    if (typeof openModal === "function") openModal("modalShortcuts");
    return;
  }

  /* F : toggle focus mode (valable dans validation uniquement) */
  if ((e.key === "f" || e.key === "F") && !e.ctrlKey && !e.altKey && state.view === "validation") {
    if (typeof toggleFocusMode === "function") {
      e.preventDefault();
      toggleFocusMode();
      return;
    }
  }

  /* Escape sort du focus mode */
  if (e.key === "Escape" && document.body.classList.contains("focus-mode")) {
    if (typeof toggleFocusMode === "function") {
      e.preventDefault();
      toggleFocusMode();
      return;
    }
  }

  /* 7. Dispatch vue specifique */
  if (state.view === "validation") _handleValidationKey(e);
}

/* --- Public hook --------------------------------------------- */

function hookKeyboard() {
  document.addEventListener("keydown", _dispatchKeydown);
}
