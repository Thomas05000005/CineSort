/* core/router.js — View navigation */

const VIEW_LABELS = {
  library:    { title: "Bibliothèque",   sub: "Workflow complet : analyse → vérification → validation → doublons → application." },
  home:       { title: "Accueil",        sub: "Point d'entree et lancement d'analyse." },
  validation: { title: "Validation",     sub: "Valider les décisions pour chaque film." },
  execution:  { title: "Application",    sub: "Appliquer les décisions et gérer l'annulation." },
  quality:    { title: "Qualité",        sub: "Scores techniques et distribution." },
  jellyfin:   { title: "Jellyfin",       sub: "Intégration Jellyfin." },
  plex:       { title: "Plex",           sub: "Intégration Plex." },
  radarr:     { title: "Radarr",         sub: "Intégration Radarr." },
  history:    { title: "Journaux",       sub: "Historique des runs et exports." },
  settings:   { title: "Paramètres",     sub: "Configuration de l'application." },
  help:       { title: "Aide",           sub: "FAQ, glossaire metier et support." },
  /* v7.6.0 Vague 1 : nouvelles routes sitemap v5 (certaines pointent encore vers les vues legacy) */
  processing: { title: "Traitement",     sub: "Scan, review, apply en parcours continu (F1)." },
  journal:    { title: "Journal",        sub: "Historique des runs et exports." },
  integrations:{ title: "Integrations",  sub: "Jellyfin, Plex, Radarr, TMDb." },
};

/* v7.6.0 Vague 1 : parsing route pattern /film/:row_id
 * Supporte hash `#film/:id` ou route plate `film/:id` pour future page Film.
 */
function parseRoute(hash) {
  const clean = String(hash || "").replace(/^#+/, "");
  if (!clean) return { view: null, params: {} };
  const parts = clean.split("/");
  if (parts[0] === "film" && parts[1]) {
    return { view: "film", params: { row_id: parts[1] } };
  }
  if (parts[0] === "settings" && parts[1]) {
    return { view: "settings", params: { category: parts[1] } };
  }
  return { view: parts[0], params: {} };
}

/* v7.6.0 Vague 1 : fabrique un breadcrumb a partir de la route courante.
 * Utilise par le composant breadcrumb.js si la vue est nested.
 */
function buildBreadcrumb(view, params) {
  const items = [];
  if (view === "film") {
    items.push({ label: "Bibliotheque", route: "library" });
    items.push({ label: "Film " + (params?.row_id || "?") });
  } else if (view === "settings" && params?.category) {
    items.push({ label: "Parametres", route: "settings" });
    items.push({ label: String(params.category).charAt(0).toUpperCase() + String(params.category).slice(1) });
  } else {
    items.push({ label: VIEW_LABELS[view]?.title || view });
  }
  return items;
}

/* Mapping transitoire : les nouvelles routes sitemap v5 renvoient vers les vues
 * existantes en attendant leur refonte (Vagues 2-7).
 * Vague 7 : quality-v5, integrations-v5, journal-v5 sont des vraies vues overlay.
 * Les alias ont ete retires (les routes canoniques pointent maintenant vers v5).
 */
const ROUTE_ALIASES = {};

/**
 * Switch the active view.
 */
function showView(view) {
  state.view = view;
  document.body.dataset.view = String(view || "");

  /* Update sidebar nav */
  qsa(".nav-btn").forEach((b) => {
    const active = b.dataset.view === view;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
    b.setAttribute("tabindex", active ? "0" : "-1");
  });

  /* Toggle view panels */
  qsa(".view").forEach((v) => {
    const isTarget = v.id === "view-" + view;
    v.classList.toggle("active", isTarget);
    v.setAttribute("aria-hidden", isTarget ? "false" : "true");
  });

  /* Update topbar — fallback "page inconnue" si la route n'est pas dans VIEW_LABELS (R2-2) */
  const info = VIEW_LABELS[view] || { title: "Page inconnue", sub: `La route "${view}" n'existe pas. Utilisez la sidebar ou Cmd+K.` };
  const titleEl = $("topbar-title");
  const subEl = $("topbar-sub");
  if (titleEl) titleEl.textContent = info.title;
  if (subEl) subEl.textContent = info.sub;

  /* Schedule table refresh for new view */
  scheduleTableLayoutRefresh();
}

/** Navigate to a view, with optional data pre-loading. */
async function navigateTo(view, opts = {}) {
  /* v7.6.0 Vague 4 : route /film/:row_id */
  if (typeof view === "string" && view.startsWith("film/")) {
    const rowId = view.slice("film/".length);
    return _navigateToFilm(rowId);
  }
  if (view === "film" && opts.row_id) {
    return _navigateToFilm(opts.row_id);
  }

  /* v7.6.0 Vague 5 : route processing (fusion F1 scan/review/apply) */
  if (view === "processing") {
    return _navigateToProcessing();
  }

  /* v7.6.0 Vague 6 : route settings-v5 (9 groupes + overlay) */
  if (typeof view === "string" && view.startsWith("settings-v5")) {
    const cat = view.includes("/") ? view.split("/")[1] : "sources";
    return _navigateToSettingsV5(cat);
  }
  if (view === "settings" && opts.v5) {
    return _navigateToSettingsV5(opts.category || "sources");
  }

  /* v7.6.0 Vague 7 : routes quality-v5 / integrations-v5 / journal-v5 */
  if (view === "quality-v5") return _navigateToQIJ("quality");
  if (view === "integrations-v5" || view === "integrations") return _navigateToQIJ("integrations");
  if (view === "journal-v5" || view === "journal") return _navigateToQIJ("journal");

  /* v7.6.0 Vague 10 — Wiring : les boutons sidebar legacy pointent sur les overlays v5.
     Flag opts.legacy = true pour forcer l'ancienne vue (backdoor dev). */
  if (!opts.legacy) {
    if (view === "validation" || view === "execution") {
      return _navigateToProcessing();
    }
    if (view === "settings") {
      return _navigateToSettingsV5(opts.category || "sources");
    }
    if (view === "quality") {
      return _navigateToQIJ("quality");
    }
    if (view === "history") {
      return _navigateToQIJ("journal");
    }
    if (view === "jellyfin" || view === "plex" || view === "radarr") {
      return _navigateToQIJ("integrations");
    }
  }

  /* v7.6.0 Vague 1 : aliasing transitoire */
  const resolvedView = ROUTE_ALIASES[view] || view;
  if (resolvedView !== view) {
    console.log("[router] alias %s -> %s", view, resolvedView);
    view = resolvedView;
  }
  console.log("[router] -> %s", view);

  /* v7.6.0 Vague 4 : quitter la page Film si on navigue ailleurs */
  _hideFilmDetailOverlay();
  /* v7.6.0 Vague 5 : quitter processing si on navigue ailleurs */
  _hideProcessingOverlay();
  /* v7.6.0 Vague 6 : quitter settings-v5 si on navigue ailleurs */
  _hideSettingsV5Overlay();
  /* v7.6.0 Vague 7 : quitter QIJ overlays si on navigue ailleurs */
  _hideQIJOverlay();

  // Nettoyer les pollings actifs de la vue precedente pour eviter les fuites (H5)
  if (typeof stopHomePolling === "function" && view !== "home") {
    stopHomePolling();
  }
  showView(view);

  /* View-specific data loading */
  if (view === "library" && typeof refreshLibraryView === "function") {
    await refreshLibraryView({ silent: true });
  }
  /* v7.6.0 Vague 3 : monter LibraryV5 overview en haut de la vue library */
  if (view === "library" && typeof window.LibraryV5 !== "undefined") {
    try {
      const panel = document.getElementById("view-library");
      if (panel) {
        let host = document.getElementById("library-v5-root");
        if (!host) {
          host = document.createElement("div");
          host.id = "library-v5-root";
          host.className = "library-v5-section";
          panel.insertBefore(host, panel.firstChild);
        }
        if (!host.dataset.mounted) {
          host.dataset.mounted = "1";
          await window.LibraryV5.mount(host);
        } else {
          await window.LibraryV5.refresh();
        }
      }
    } catch (e) {
      console.warn("[router] LibraryV5 mount failed:", e);
    }
  }
  if (view === "home" && typeof refreshHomeOverview === "function") {
    await refreshHomeOverview({ silent: true });
  }
  if (view === "validation" && typeof ensureValidationLoaded === "function") {
    await ensureValidationLoaded();
  }
  if (view === "quality" && typeof refreshQualityView === "function") {
    await refreshQualityView({ silent: true });
  }
  if (view === "history" && typeof refreshHistoryView === "function") {
    await refreshHistoryView({ silent: true });
  }
  if (view === "execution" && typeof refreshExecutionView === "function") {
    await refreshExecutionView({ silent: true });
  }
  if (view === "settings" && typeof loadSettings === "function") {
    await loadSettings();
  }
  /* Vues dediees integrations */
  if (view === "jellyfin" && typeof refreshJellyfinView === "function") {
    await refreshJellyfinView();
  }
  if (view === "plex" && typeof refreshPlexView === "function") {
    await refreshPlexView();
  }
  if (view === "radarr" && typeof refreshRadarrView === "function") {
    await refreshRadarrView();
  }
  /* V1-14 : Aide (FAQ + glossaire metier) — IIFE expose window.HelpView */
  if (view === "help" && window.HelpView && typeof window.HelpView.init === "function") {
    window.HelpView.init();
  }
}

/* --- Table wrap state management --------------------------- */

let tableWrapRefreshRaf = 0;
let tableWrapHandlersReady = false;

function updateTableWrapState(wrap) {
  if (!(wrap instanceof HTMLElement)) return;
  const table = wrap.querySelector("table");
  if (!(table instanceof HTMLTableElement)) return;
  const body = table.tBodies?.[0] || null;
  const rowCount = body ? body.rows.length : 0;
  const overflowX = (wrap.scrollWidth - wrap.clientWidth) > 6;
  wrap.dataset.overflowX = overflowX ? "true" : "false";
  wrap.dataset.rowCount = String(rowCount);
}

function bindTableWrapState(wrap) {
  if (!(wrap instanceof HTMLElement) || wrap.dataset.tableWrapBound === "1") return;
  wrap.dataset.tableWrapBound = "1";
  wrap.addEventListener("scroll", () => updateTableWrapState(wrap), { passive: true });
}

function refreshTableWrapStates(root) {
  const host = root instanceof HTMLElement || root instanceof Document ? root : document;
  host.querySelectorAll(".table-wrap").forEach((wrap) => {
    bindTableWrapState(wrap);
    updateTableWrapState(wrap);
  });
}

function scheduleTableLayoutRefresh(root) {
  if (tableWrapRefreshRaf) window.cancelAnimationFrame(tableWrapRefreshRaf);
  tableWrapRefreshRaf = window.requestAnimationFrame(() => {
    tableWrapRefreshRaf = 0;
    refreshTableWrapStates(root || document);
  });
}

function initTableWrapObservers() {
  if (tableWrapHandlersReady) return;
  tableWrapHandlersReady = true;
  window.addEventListener("resize", () => scheduleTableLayoutRefresh());
  window.addEventListener("load", () => scheduleTableLayoutRefresh());
}

/* --- v7.6.0 Vague 4 : Film detail overlay plein-ecran ---------------- */

function _ensureFilmDetailOverlay() {
  let overlay = document.getElementById("film-detail-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "film-detail-overlay";
    overlay.className = "v5-film-overlay";
    overlay.setAttribute("role", "region");
    overlay.setAttribute("aria-label", "Page film");
    // Mount inside .content ou fallback body
    const host = document.querySelector(".content") || document.body;
    host.appendChild(overlay);
  }
  return overlay;
}

function _hideFilmDetailOverlay() {
  const overlay = document.getElementById("film-detail-overlay");
  if (overlay && overlay.classList.contains("is-active")) {
    overlay.classList.remove("is-active");
    if (window.FilmDetail && typeof window.FilmDetail.unmount === "function") {
      window.FilmDetail.unmount();
    }
  }
}

async function _navigateToFilm(rowId) {
  if (!rowId) return;
  console.log("[router] -> film/" + rowId);
  _hideProcessingOverlay();
  const overlay = _ensureFilmDetailOverlay();
  overlay.classList.add("is-active");
  document.body.dataset.view = "film";
  // Masquer les autres vues
  qsa(".view").forEach((v) => {
    v.classList.remove("active");
    v.setAttribute("aria-hidden", "true");
  });

  if (window.FilmDetail && typeof window.FilmDetail.mount === "function") {
    await window.FilmDetail.mount(overlay, rowId);
  } else {
    overlay.innerHTML = '<div class="v5-film-loading">Composant film indisponible.</div>';
  }
}

/* --- v7.6.0 Vague 5 : Processing overlay (fusion F1) ---------------- */

function _ensureProcessingOverlay() {
  let overlay = document.getElementById("processing-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "processing-overlay";
    overlay.className = "v5-processing-overlay";
    overlay.setAttribute("role", "region");
    overlay.setAttribute("aria-label", "Traitement");
    const host = document.querySelector(".content") || document.body;
    host.appendChild(overlay);
  }
  return overlay;
}

function _hideProcessingOverlay() {
  const overlay = document.getElementById("processing-overlay");
  if (overlay && overlay.classList.contains("is-active")) {
    overlay.classList.remove("is-active");
    if (window.ProcessingV5 && typeof window.ProcessingV5.unmount === "function") {
      window.ProcessingV5.unmount();
    }
  }
}

async function _navigateToProcessing() {
  console.log("[router] -> processing");
  _hideFilmDetailOverlay();
  _hideSettingsV5Overlay();
  const overlay = _ensureProcessingOverlay();
  overlay.classList.add("is-active");
  document.body.dataset.view = "processing";
  qsa(".view").forEach((v) => {
    v.classList.remove("active");
    v.setAttribute("aria-hidden", "true");
  });

  if (window.ProcessingV5 && typeof window.ProcessingV5.mount === "function") {
    await window.ProcessingV5.mount(overlay);
  } else {
    overlay.innerHTML = '<div class="v5-processing-shell"><div class="v5-processing-panel">Composant Traitement indisponible.</div></div>';
  }
}

/* --- v7.6.0 Vague 6 : Settings V5 overlay ---------------- */

function _ensureSettingsV5Overlay() {
  let overlay = document.getElementById("settings-v5-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "settings-v5-overlay";
    overlay.className = "v5-settings-overlay";
    overlay.setAttribute("role", "region");
    overlay.setAttribute("aria-label", "Parametres");
    const host = document.querySelector(".content") || document.body;
    host.appendChild(overlay);
  }
  return overlay;
}

function _hideSettingsV5Overlay() {
  const overlay = document.getElementById("settings-v5-overlay");
  if (overlay && overlay.classList.contains("is-active")) {
    overlay.classList.remove("is-active");
    if (window.SettingsV5 && typeof window.SettingsV5.unmount === "function") {
      window.SettingsV5.unmount();
    }
  }
}

async function _navigateToSettingsV5(category) {
  console.log("[router] -> settings-v5 (" + category + ")");
  _hideFilmDetailOverlay();
  _hideProcessingOverlay();
  _hideQIJOverlay();
  const overlay = _ensureSettingsV5Overlay();
  overlay.classList.add("is-active");
  document.body.dataset.view = "settings-v5";
  qsa(".view").forEach((v) => {
    v.classList.remove("active");
    v.setAttribute("aria-hidden", "true");
  });

  if (window.SettingsV5 && typeof window.SettingsV5.mount === "function") {
    await window.SettingsV5.mount(overlay, { category });
  } else {
    overlay.innerHTML = '<div class="v5-settings-shell">Composant Settings V5 indisponible.</div>';
  }
}

/* --- v7.6.0 Vague 7 : QIJ (Quality / Integrations / Journal) overlay ---- */

function _ensureQIJOverlay() {
  let overlay = document.getElementById("qij-v5-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "qij-v5-overlay";
    overlay.className = "v5-qij-overlay";
    overlay.setAttribute("role", "region");
    const host = document.querySelector(".content") || document.body;
    host.appendChild(overlay);
  }
  return overlay;
}

function _hideQIJOverlay() {
  const overlay = document.getElementById("qij-v5-overlay");
  if (overlay && overlay.classList.contains("is-active")) {
    overlay.classList.remove("is-active");
    ["QualityV5", "IntegrationsV5", "JournalV5"].forEach((ns) => {
      if (window[ns] && typeof window[ns].unmount === "function") {
        window[ns].unmount();
      }
    });
  }
}

async function _navigateToQIJ(mode) {
  console.log("[router] -> qij/" + mode);
  _hideFilmDetailOverlay();
  _hideProcessingOverlay();
  _hideSettingsV5Overlay();
  const overlay = _ensureQIJOverlay();
  overlay.classList.add("is-active");
  overlay.setAttribute("aria-label", mode);
  document.body.dataset.view = mode + "-v5";
  qsa(".view").forEach((v) => {
    v.classList.remove("active");
    v.setAttribute("aria-hidden", "true");
  });

  const ns = { quality: "QualityV5", integrations: "IntegrationsV5", journal: "JournalV5" }[mode];
  if (ns && window[ns] && typeof window[ns].mount === "function") {
    await window[ns].mount(overlay);
  } else {
    overlay.innerHTML = '<div class="v5-qij-shell">Composant ' + mode + ' indisponible.</div>';
  }
}
