/* app.js — CineSort v2 bootstrap */
/* global state, $, qsa, showView, navigateTo */

let appBootstrapped = false;

/* --- Theme ------------------------------------------------- */

function toggleTheme() {
  const isLight = document.body.classList.toggle("light");
  state.theme = isLight ? "light" : "dark";
  const btn = $("btnTheme");
  if (btn) btn.textContent = isLight ? "Theme sombre" : "Theme clair";
}

/* --- Navigation -------------------------------------------- */

function hookNav() {
  qsa(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const view = btn.dataset.view;
      if (view) navigateTo(view);
    });
  });
}

/* --- Bridge for pywebview backend callbacks ----------------- */

function installAppBridge() {
  window.CineSortBridge = {
    showView,
    navigateTo,
    setLastRunContext,
    setSelectedFilmContext,
    currentContextRunId,
    currentContextRowId,
    refreshHomeOverview,
    refreshHistoryView,
    refreshQualityView,
    refreshCleanupResidualPreview,
    refreshUndoPreview,
    loadSettings,
    loadQualityPresets,
    loadQualityProfile,
    loadProbeToolsStatus,
    getStateSnapshot() {
      return {
        view: String(state.view || ""),
        runId: String(state.runId || ""),
        lastRunId: String(state.lastRunId || ""),
        selectedRunId: String(state.selectedRunId || ""),
        selectedRowId: String(state.selectedRowId || ""),
        rowsRunId: String(state.rowsRunId || ""),
        rowCount: Array.isArray(state.rows) ? state.rows.length : 0,
      };
    },
  };
}

/* --- Modal close buttons ----------------------------------- */

function hookModalCloseButtons() {
  qsa("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.dataset.close));
  });
}

/* --- Init -------------------------------------------------- */

function ready() {
  restoreContextFromStorage();
  hookNav();
  hookHomeEvents();
  hookValidationEvents();
  hookExecutionEvents();
  hookQualityEvents();
  hookHistoryEvents();
  hookSettingsEvents();
  hookModalCloseButtons();
  initModalHandlers();
  initTableWrapObservers();
  hookKeyboard();
  initDropHandlers();
  installAppBridge();

  /* Theme button */
  $("btnTheme")?.addEventListener("click", toggleTheme);
  /* V1-14 : btnHelp ouvre la vue Aide complete (FAQ + glossaire). Le modale
     "Aide rapide" reste accessible via la palette si besoin, mais la sidebar
     pointe maintenant vers la vue plein-ecran. */
  $("btnHelp")?.addEventListener("click", () => {
    if (window.HelpView && typeof window.HelpView.open === "function") {
      window.HelpView.open();
    } else {
      navigateTo("help");
    }
  });

  /* v7.6.0 Vague 10 : bouton notification center (drawer v5) */
  $("btnNotifCenter")?.addEventListener("click", () => {
    if (window.NotificationCenter && typeof window.NotificationCenter.toggle === "function") {
      window.NotificationCenter.toggle();
    }
  });
  /* Listener event badge compteur (emis par le polling) */
  document.addEventListener("v5:notif-count", (e) => {
    const count = (e && e.detail && Number(e.detail.count)) || 0;
    const label = document.getElementById("btnNotifCenterLabel");
    if (label) {
      label.textContent = count > 0 ? `Notifs (${count > 99 ? "99+" : count})` : "Notifs";
    }
    const btn = document.getElementById("btnNotifCenter");
    if (btn) {
      btn.classList.toggle("has-unread", count > 0);
      btn.setAttribute("aria-label", count > 0 ? `Notifications (${count} non lues)` : "Notifications");
    }
  });

  showView("home");
}

/* --- Startup ----------------------------------------------- */

window.addEventListener("pywebviewready", async () => {
  if (appBootstrapped) return;
  appBootstrapped = true;
  ready();

  try {
    await loadSettings();
    // Appliquer le theme des que les settings sont charges
    if (typeof _applyThemeLive === "function" && state.settings) _applyThemeLive(state.settings);
    await loadQualityPresets();
    await loadQualityProfile();
    await loadProbeToolsStatus(false);
    await refreshHomeOverview({ silent: true });
    await maybeShowWizard();
  } catch (err) {
    const msg = "Initialisation incomplete. Verifiez le backend.";
    setStatusMessage("saveMsg", msg, { error: true });
    setStatusMessage("planMsg", msg, { error: true });
    console.error("[startup]", err);
  } finally {
    window.dispatchEvent(new CustomEvent("cinesortready"));
    window.__APP_READY__ = true;
  }
});

/* Fallback if pywebviewready doesn't fire (dev/preview) */
window.addEventListener("DOMContentLoaded", () => {
  window.setTimeout(() => {
    if (!appBootstrapped) {
      appBootstrapped = true;
      ready();
    }
  }, 1500);
});

/* --- Pause animations en arriere-plan (C7) ------------------
 * Quand la fenetre CineSort passe en arriere-plan, on ajoute une
 * classe .is-background sur body ; themes.css utilise
 * animation-play-state: paused pour stopper grain/scan-line/shimmer
 * et economiser ~2-3% CPU continuous.
 */
document.addEventListener("visibilitychange", () => {
  document.body.classList.toggle("is-background", document.hidden);
});

/* --- Polling event-driven idle (parite dashboard) -----------
 * Toutes les 20 secondes, verifie si un evenement serveur a eu lieu
 * (scan termine, apply, settings changes) et rafraichit la vue active.
 * Pause si l'onglet n'est pas visible ou si un scan est en cours.
 */
(function setupEventDrivenPolling() {
  const IDLE_INTERVAL = 20000;
  async function idleCheck() {
    try {
      if (document.hidden) return;
      if (state && state.runId && state.polling) return; // scan actif => polling dedie
      if (!window.pywebview || !window.pywebview.api || typeof window.pywebview.api.get_event_ts !== "function") return;
      const r = await window.pywebview.api.get_event_ts();
      if (!r || !r.ok) return;
      const eventChanged = typeof checkEventChanged === "function" ? checkEventChanged(r.last_event_ts) : false;
      if (!eventChanged) return;
      const view = state && state.view ? state.view : null;
      if (view === "home" && typeof refreshHomeOverview === "function") {
        refreshHomeOverview({ silent: true }).catch(() => {});
      } else if (view === "quality" && typeof refreshQualityView === "function") {
        refreshQualityView({ silent: true }).catch(() => {});
      } else if (view === "history" && typeof refreshHistoryView === "function") {
        refreshHistoryView({ silent: true }).catch(() => {});
      }
    } catch { /* silencieux */ }
  }
  setInterval(idleCheck, IDLE_INTERVAL);
})();

