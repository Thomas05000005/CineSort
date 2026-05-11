/* views/home.js — Accueil + scan launcher (V5bis-01 : ESM port, V6 : compat ESM)
 *
 * V5bis-01 : converti IIFE/script global -> ES module utilisant `apiPost`
 * (REST + fallback pywebview) au lieu du bridge pywebview natif direct.
 *
 * V6 : helpers historiques du webview legacy (state, apiCall, setPill,
 * setStatusMessage, flashActionButton, setLastRunContext, appendLogs,
 * loadTable, showView, openPathWithFeedback, resetRunScopedState, fmtSpeed,
 * fmtEta, shortPath, uiConfirm) sont maintenant importes en ESM depuis
 * `./_legacy_compat.js` au lieu d'etre resolus implicitement via window.
 * Comportement runtime identique (stubs no-op) mais dependances explicites.
 *
 * Pattern de reponse `apiPost` :
 *   { ok: boolean, data: any, status: number, error?: string }
 *  - `data` contient le payload metier (ce que retourne CineSortApi.X()).
 */

import {
  apiPost,
  escapeHtml,
  $,
  renderSkeleton,
  renderError,
  initView,
} from "./_v5_helpers.js";

// V6 : imports ESM des helpers legacy (remplace les references implicites a window.X)
import {
  state,
  apiCall,
  setPill,
  setStatusMessage,
  flashActionButton,
  setLastRunContext,
  appendLogs,
  loadTable,
  showView,
  openPathWithFeedback,
  resetRunScopedState,
  fmtSpeed,
  fmtEta,
  shortPath,
  uiConfirm,
} from "./_legacy_compat.js";

// V6 fix : composants v5 home pour le rendu du dashboard d'accueil (KPIs, charts, insights)
import {
  renderKpiGrid as homeRenderKpiGrid,
  renderInsights as homeRenderInsights,
  renderPosterCarousel as homeRenderPosterCarousel,
} from "../dashboard/components/home-widgets.js";
import {
  renderDonut as homeRenderDonut,
  renderLine as homeRenderLine,
} from "../dashboard/components/home-charts.js";

function formatMovieLabel(item) {
  const title = String(item?.title || "").trim();
  const year = Number(item?.year || 0);
  if (title && year > 0) return `${title} (${year})`;
  if (title) return title;
  return "—";
}

/* --- U2 Audit : helpers pour widgets globaux (Librarian + Espace disque) --- */

const _HOME_TIER_COLORS = [
  ["Platinum", "var(--success)"],
  ["Gold", "var(--accent)"],
  ["Silver", "var(--info)"],
  ["Bronze", "var(--warning)"],
  ["Reject", "var(--danger)"],
];

const _HOME_PRIO = {
  high: { color: "var(--danger)", label: "Haute" },
  medium: { color: "var(--warning)", label: "Moyenne" },
  low: { color: "var(--info)", label: "Info" },
};

function _homeFmtBytes(bytes) {
  // V6-04 : delegue a window.formatBytes (locale-aware) si dispo, sinon fallback FR local.
  if (typeof window.formatBytes === "function") {
    return window.formatBytes(bytes, 1);
  }
  const n = Number(bytes || 0);
  if (!n) return "0 o";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  let v = n;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u += 1;
  }
  return `${v.toFixed(u >= 2 ? 1 : 0)} ${units[u]}`;
}

/* --- V5A-04 V3-05 : demo wizard premier-run ---------------- */

/** Garde-fou : on ne tente l'init du mode demo qu'une seule fois par session. */
let _demoModeInitDone = false;

/**
 * V3-05 — Si premier-run (aucun root configure + aucun run effectue),
 * affiche le wizard "tester avec 15 films fictifs" + une banniere
 * persistante quand le mode demo est actif.
 *
 * Le module `demo-wizard.js` est cote dashboard (ES module).
 * On l'importe dynamiquement pour eviter de casser le script global
 * `home.js` (charge en non-module).
 *
 * @param {object} settings - payload de get_settings
 * @param {object} stats - payload de get_global_stats
 */
async function _initDemoModeIfNeeded(settings, stats) {
  if (_demoModeInitDone) return;
  _demoModeInitDone = true;
  try {
    const mod = await import("../dashboard/views/demo-wizard.js");
    if (typeof mod.showDemoWizardIfFirstRun === "function") {
      await mod.showDemoWizardIfFirstRun(settings, stats);
    }
    if (typeof mod.renderDemoBanner === "function") {
      await mod.renderDemoBanner();
    }
  } catch (err) {
    console.warn("[home v5] init demo mode", err);
    _demoModeInitDone = false; // re-essayer au prochain refresh
  }
}

/* --- V5A-04 V2-08 : skeleton loading states ---------------- */

/**
 * V2-08 — Squelettes (placeholders animes) affiches AVANT que les
 * donnees n'arrivent. Evite le "flash de contenu vide" et l'aspect
 * fige pendant les premiers fetch.
 *
 * Cible un conteneur dedie `#homeV5Skeleton` injecte une seule fois
 * en tete de la vue home. Retire de lui-meme apres le premier render
 * de donnees reelles (cf `_hideHomeSkeleton`).
 *
 * CSS attendu (a porter dans web/shared/animations.css ou styles.css) :
 *   .v5-skeleton { display: grid; gap: var(--space-md); }
 *   .v5-skeleton-card { height: 88px; border-radius: var(--radius-md);
 *     background: linear-gradient(90deg, var(--bg-raised) 25%,
 *       var(--bg-base) 50%, var(--bg-raised) 75%);
 *     background-size: 200% 100%;
 *     animation: v5-skeleton-shimmer 1.5s infinite linear; }
 *   @keyframes v5-skeleton-shimmer { from { background-position: 200% 0 } to { background-position: -200% 0 } }
 */
function _renderSkeleton(container) {
  if (!container) return;
  if (container.querySelector(".v5-skeleton")) return; // deja present
  const sk = document.createElement("div");
  sk.id = "homeV5Skeleton";
  sk.className = "v5-skeleton v5-skeleton--home";
  sk.setAttribute("aria-hidden", "true");
  sk.innerHTML = `
    <div class="v5-skeleton-card v5-skeleton-card--kpi"></div>
    <div class="v5-skeleton-card v5-skeleton-card--kpi"></div>
    <div class="v5-skeleton-card v5-skeleton-card--kpi"></div>
    <div class="v5-skeleton-chart"></div>
  `;
  container.insertBefore(sk, container.firstChild);
}

/** Retire le skeleton apres le premier render de donnees reelles. */
function _hideHomeSkeleton() {
  const sk = document.getElementById("homeV5Skeleton");
  if (sk && sk.parentElement) sk.parentElement.removeChild(sk);
}

/* --- Home rendering ---------------------------------------- */

function renderHomeOverview() {
  const ov = state.homeOverview;
  if (!ov) return;
  const dash = ov.dashboard;

  /* Hero stats (E10) — chiffres synthetiques */
  // V-9 audit visuel 20260429 : si valeurs vides ("—"), ajouter tooltip
  // expliquant comment les remplir + classe .home-hero__stat--empty.
  const totalEl = $("homeStatTotal");
  const scoreEl = $("homeStatScore");
  if (totalEl || scoreEl) {
    const total = dash?.total_movies ?? dash?.total_rows ?? 0;
    const avg = dash?.score_avg ?? dash?.avg_score;
    const _hint = "Lancez un scan pour voir vos statistiques";
    if (totalEl) {
      const empty = !(total > 0);
      totalEl.textContent = empty ? "—" : String(total);
      totalEl.parentElement?.classList.toggle("home-hero__stat--empty", empty);
      totalEl.parentElement?.setAttribute("title", empty ? _hint : "");
    }
    if (scoreEl) {
      const hasScore = typeof avg === "number" && avg > 0;
      scoreEl.textContent = hasScore ? `${Math.round(avg)} pts` : "—";
      scoreEl.parentElement?.classList.toggle("home-hero__stat--empty", !hasScore);
      scoreEl.parentElement?.setAttribute("title", !hasScore ? _hint : "");
    }
  }

  /* Env bar */
  const s = state.settings || {};
  const tmdbOk = !!s.tmdb_enabled && !!s.tmdb_api_key;
  // C5 : source de verite = probe_tools_status_payload() retourne
  // { tools: { ffprobe: { available: bool, path, ... }, mediainfo: { available: bool, ... } } }.
  // On utilise uniquement `available` (boolean). Les branches `status === "ok"`
  // etaient un vestige — le backend n'expose pas de champ `status`.
  const _probeTools = state.probeToolsStatus?.tools || {};
  const probeOk = !!(_probeTools.ffprobe?.available || _probeTools.mediainfo?.available);
  const roots = s.roots || (s.root ? [s.root] : []);
  const rootOk = roots.length > 0;
  const env = $("homeEnvBar");
  if (env) {
    const envTmdb = $("homeEnvTmdb");
    envTmdb.className = `env-item ${tmdbOk ? "env-ok" : "env-warn"}`;
    envTmdb.innerHTML = `TMDb: ${tmdbOk ? '<span class="text-success">OK</span>' : '<span class="text-warning">Non configuré</span>'}`;
    const envProbe = $("homeEnvProbe");
    envProbe.className = `env-item ${probeOk ? "env-ok" : "env-warn"}`;
    envProbe.innerHTML = `Probe: ${probeOk ? '<span class="text-success">OK</span>' : '<span class="text-warning">Manquant</span>'}`;
    const envRoot = $("homeEnvRoot");
    envRoot.className = `env-item ${rootOk ? "env-ok" : "env-err"}`;
    envRoot.innerHTML = `Dossiers: ${rootOk ? `<span class="text-success">${roots.length} root(s)</span>` : '<span class="text-danger">Non configuré</span>'}`;
  }

  /* Multi-root status display */
  const rootsContainer = $("homeRootsStatus");
  if (rootsContainer) {
    if (!roots.length) {
      rootsContainer.innerHTML = '<span class="text-muted">Aucun dossier racine configuré.</span>';
    } else {
      rootsContainer.innerHTML = roots.map(r => `<div class="root-status-item"><span class="root-status-ok">&#9679;</span> ${escapeHtml(r)}</div>`).join("");
    }
  }

  /* Scan root label */
  if ($("homeScanRoot")) {
    $("homeScanRoot").textContent = roots.length > 1
      ? `${roots.length} dossier(s) racine`
      : `Dossier : ${roots[0] || "non configuré"}`;
  }

  /* Run card */
  if (!dash || !dash.run_id) {
    if ($("homeRunTitle")) $("homeRunTitle").textContent = "Aucun run";
    if ($("homeKpiFilms")) $("homeKpiFilms").textContent = "—";
    if ($("homeKpiScore")) $("homeKpiScore").textContent = "—";
    if ($("homeKpiAnomalies")) $("homeKpiAnomalies").textContent = "—";
    if ($("homeKpiStatus")) $("homeKpiStatus").textContent = "—";
    return;
  }

  if ($("homeRunTitle")) $("homeRunTitle").textContent = dash.run_id;
  const kpis = dash.kpis || {};
  if ($("homeKpiFilms")) $("homeKpiFilms").textContent = String(kpis.total_rows || 0);
  if ($("homeKpiScore")) $("homeKpiScore").textContent = kpis.score_avg ? `${Number(kpis.score_avg).toFixed(1)}/100` : "—";
  if ($("homeKpiAnomalies")) $("homeKpiAnomalies").textContent = String(kpis.anomalies_count || 0);

  /* Status */
  const applied = !!dash.apply_summary?.applied;
  const undoable = !!ov.undoAvailable;
  let statusText = "Analysé";
  if (applied) statusText = undoable ? "Appliqué (annulable)" : "Appliqué";
  if ($("homeKpiStatus")) $("homeKpiStatus").textContent = statusText;

  /* Signals */
  const signals = [];
  if (Number(kpis.anomalies_count || 0) > 0) {
    signals.push({ text: `${kpis.anomalies_count} anomalie(s) detectee(s)`, view: "quality" });
  }
  if (Number(kpis.probe_partial_count || 0) > 0) {
    signals.push({ text: `${kpis.probe_partial_count} analyse(s) partielle(s)`, view: "quality" });
  }
  const list = $("homeSignalsList");
  if (list) {
    if (!signals.length) {
      list.innerHTML = '<li class="signal-item text-muted">Aucun signal pour le moment.</li>';
    } else {
      list.innerHTML = signals.map(s =>
        `<li class="signal-item" data-nav="${escapeHtml(s.view)}"><span class="badge badge--warn">!</span> ${escapeHtml(s.text)}</li>`
      ).join("");
    }
  }

  /* Pills */
  setPill("pillRun", "Run: " + (dash.run_id || "—"));
}

async function refreshHomeOverview(opts = {}) {
  try {
    // V5A-04 V2-08 : afficher le skeleton avant le 1er fetch (premier appel
    // uniquement — skip si les donnees ont deja ete rendues une fois).
    if (!state.homeOverview) {
      const _viewHome = document.getElementById("view-home");
      if (_viewHome) _renderSkeleton(_viewHome);
    }
    // V5A-04 / Audit ID-ROB-002 : Promise.allSettled (V2-04) pour qu'un endpoint
    // en echec ne casse pas le rendu de la home. Les 3 endpoints (probe / dashboard /
    // global_stats) sont independants ; on tolere des resultats partiels.
    // V5bis-01 : migre vers `apiPost` (REST) au lieu du bridge pywebview direct.
    const labels = ["probe_tools", "dashboard", "global_stats"];
    const results = await Promise.allSettled([
      state.probeToolsInFlight ? Promise.resolve(null) : apiPost("get_probe_tools_status"),
      apiPost("get_dashboard", { run_id: "latest" }),
      apiPost("get_global_stats"),
    ]);
    const _val = (r) => (r && r.status === "fulfilled" ? r.value : null);
    const [probeRes, dashRes, globalRes] = results.map(_val);
    const failed = labels.filter((_, i) => results[i].status !== "fulfilled");
    if (failed.length > 0) console.warn("[home] endpoints en echec (rendu partiel):", failed);
    // `apiPost` renvoie { ok, data, ... } — on extrait `data` pour conserver le
    // contrat historique (les renderers attendent l'objet metier directement).
    const probeData = (probeRes && probeRes.ok) ? (probeRes.data || null) : null;
    const dashData = (dashRes && dashRes.ok) ? (dashRes.data || null) : null;
    const globalData = (globalRes && globalRes.ok) ? (globalRes.data || null) : null;
    if (probeData) state.probeToolsStatus = probeData;
    state.homeGlobal = globalData;
    if (!dashData) {
      state.homeOverview = { dashboard: null, undoAvailable: false };
    } else {
      let undoAvailable = false;
      if (dashData.run_id) {
        const undoRes = await apiPost("undo_last_apply_preview", { run_id: dashData.run_id });
        undoAvailable = !!(undoRes?.ok && undoRes.data?.can_undo);
      }
      state.homeOverview = { dashboard: dashData, runId: dashData.run_id, undoAvailable };
      if (dashData.run_id && dashData.run_dir) {
        setLastRunContext(dashData.run_id, dashData.run_dir);
      }
    }
    _hideHomeSkeleton();  // V5A-04 V2-08 : retirer le squelette apres 1er render
    renderHomeOverview();
    renderHomeGlobalWidgets();
    /* v7.6.0 Vague 2 : Home overview-first V5 (KPI grid + insights + charts + posters) */
    renderHomeV5Overview(state.homeGlobal);
    /* V5A-04 V1-06 : widget integrations avec CTA "Configurer" pour les non-actives */
    renderHomeIntegrationsWidget(state.settings);
    updateProbeInstallBanner();
    /* V5A-04 V3-05 : wizard demo premier-run + banniere mode demo (best-effort) */
    _initDemoModeIfNeeded(state.settings, state.homeGlobal);
  } catch (err) {
    console.error("[refreshHomeOverview]", err);
  }
}

/**
 * v7.6.0 Vague 2 — Home overview-first.
 * Rend KPI grid V2 + insights proactifs + donut distribution + line tendance
 * + carousel posters dans un conteneur cree a la volee apres le hero.
 *
 * Detecte les nouveaux champs backend (v2_tier_distribution, trend_30days, insights).
 * Si absents (ancienne API), ne fait rien.
 */
function renderHomeV5Overview(globalStats) {
  if (!globalStats || globalStats.ok === false) return;
  const hasV5Data = globalStats.v2_tier_distribution
    || globalStats.trend_30days
    || globalStats.insights;
  if (!hasV5Data) return;

  /* Creer le conteneur si absent (first call) */
  let root = document.getElementById("home-v5-overview");
  if (!root) {
    /* V6 fix : creer un .home-hero minimal si absent (cas SPA dashboard ou
       #view-home est un mount point vide). On accroche le tableau de bord
       v5 directement sur #view-home si pas de hero existant. */
    const viewHome = document.getElementById("view-home");
    if (!viewHome) return;
    let hero = viewHome.querySelector(".home-hero");
    if (!hero) {
      hero = document.createElement("div");
      hero.className = "home-hero v5u-mb-4";
      hero.innerHTML = '<h1 class="v5u-text-xl">Accueil</h1>';
      viewHome.appendChild(hero);
    }
    root = document.createElement("div");
    root.id = "home-v5-overview";
    root.className = "home-v5-section";
    hero.insertAdjacentElement("afterend", root);
  }

  const hasInsights = Array.isArray(globalStats.insights) && globalStats.insights.length > 0;
  const hasDonut = !!globalStats.v2_tier_distribution?.counts;
  const hasLine = Array.isArray(globalStats.trend_30days) && globalStats.trend_30days.length > 0;
  const recent = Array.isArray(globalStats.librarian?.suggestions)
    ? []  /* librarian suggestions != recent films */
    : (Array.isArray(globalStats.recent_films) ? globalStats.recent_films : []);

  /* Build skeleton */
  root.innerHTML = `
    <div class="home-v5-header">
      <h2 class="home-v5-title">Aperçu V2</h2>
      <span class="home-v5-sub v5u-text-muted">${hasInsights ? globalStats.insights.length + " insight" + (globalStats.insights.length > 1 ? "s" : "") : "Tout est calme."}</span>
    </div>
    <div id="home-v5-kpis"></div>
    ${hasInsights ? '<div id="home-v5-insights"></div>' : ""}
    ${(hasDonut || hasLine) ? '<div class="home-v5-charts"><div id="home-v5-donut"></div><div id="home-v5-line"></div></div>' : ""}
    ${recent.length ? '<div id="home-v5-recent"></div>' : ""}
  `;

  /* KPIs : build les 5 KPI cards */
  if (typeof homeRenderKpiGrid === "function") {
    const dist = globalStats.v2_tier_distribution || { counts: {}, percentages: {} };
    const counts = dist.counts || {};
    const pct = dist.percentages || {};
    const totalFilms = dist.total || 0;
    const avgScore = globalStats.summary?.avg_score || 0;
    const platGoldPct = Math.round((pct.platinum || 0) + (pct.gold || 0));
    const rejectPct = Math.round(pct.reject || 0);
    const trend = globalStats.summary?.trend || "→";

    homeRenderKpiGrid(document.getElementById("home-v5-kpis"), [
      { id: "total",    label: "Total films",  value: totalFilms,    icon: "library" },
      { id: "score",    label: "Score moyen",  value: avgScore.toFixed(1), trend, icon: "bar-chart" },
      { id: "platgold", label: "Platinum+Gold", value: platGoldPct, suffix: "%",
        tier: "gold", icon: "award" },
      { id: "reject",   label: "Reject",        value: rejectPct, suffix: "%",
        tier: "reject", icon: "alert-triangle" },
      { id: "scored",   label: "Scored V2",     value: dist.scored_total || 0 },
    ]);
  }

  /* Insights */
  if (hasInsights && typeof homeRenderInsights === "function") {
    homeRenderInsights(
      document.getElementById("home-v5-insights"),
      globalStats.insights,
      (insight) => {
        console.log("[home-v5] insight action:", insight.type);
        if (insight.filter_hint?.tier && typeof navigateTo === "function") {
          navigateTo("library", { filter: insight.filter_hint });
        }
      }
    );
  }

  /* Donut + Line */
  if (typeof homeRenderDonut === "function" && hasDonut) {
    homeRenderDonut(
      document.getElementById("home-v5-donut"),
      globalStats.v2_tier_distribution
    );
  }
  if (typeof homeRenderLine === "function" && hasLine) {
    homeRenderLine(
      document.getElementById("home-v5-line"),
      globalStats.trend_30days
    );
  }

  /* Recent (si dispo plus tard) */
  if (recent.length && typeof homeRenderPosterCarousel === "function") {
    homeRenderPosterCarousel(
      document.getElementById("home-v5-recent"),
      recent
    );
  }
}

/**
 * V5A-04 V1-06 — Widget integrations avec CTA "Configurer".
 *
 * Pour chaque integration (Jellyfin / Plex / Radarr) :
 *  - si activee : carte "Connecte" (lecture seule)
 *  - sinon : carte cliquable avec lien `#/settings?focus=<id>` et CTA
 *    "Configurer ->" qui amene directement a la section concernee.
 *
 * Exemples de hrefs generes :
 *   #/settings?focus=jellyfin
 *   #/settings?focus=plex
 *   #/settings?focus=radarr
 *
 * Le widget se cree dynamiquement la premiere fois et se met a jour ensuite.
 * Ancre : juste apres `#home-v5-overview` (s'il existe), sinon apres le hero.
 */
function renderHomeIntegrationsWidget(settings) {
  const view = document.getElementById("view-home");
  if (!view) return;
  const s = settings || state.settings || {};

  const items = [
    { id: "jellyfin", label: "Jellyfin", enabled: !!s.jellyfin_enabled },
    { id: "plex",     label: "Plex",     enabled: !!s.plex_enabled },
    { id: "radarr",   label: "Radarr",   enabled: !!s.radarr_enabled },
  ];

  let widget = document.getElementById("home-v5-integrations");
  if (!widget) {
    widget = document.createElement("section");
    widget.id = "home-v5-integrations";
    widget.className = "v5-home-integrations";
    const anchor = document.getElementById("home-v5-overview")
      || view.querySelector(".home-hero")
      || view.firstElementChild;
    if (anchor && anchor.insertAdjacentElement) {
      anchor.insertAdjacentElement("afterend", widget);
    } else {
      view.appendChild(widget);
    }
  }

  widget.innerHTML = `
    <h2 class="v5-home-integrations__title">Integrations</h2>
    <div class="v5-grid v5-grid--3">
      ${items.map((it) => it.enabled ? `
        <div class="v5-card v5-card--connected" data-integration="${escapeHtml(it.id)}">
          <span class="v5-status-dot v5-status-dot--ok" aria-hidden="true"></span>
          <strong>${escapeHtml(it.label)}</strong>
          <span class="v5-text-muted">Connecte</span>
        </div>
      ` : `
        <a class="v5-card v5-card--disabled" href="#/settings?focus=${escapeHtml(it.id)}"
           data-nav-settings="${escapeHtml(it.id)}">
          <strong>${escapeHtml(it.label)}</strong>
          <span class="v5-text-muted">Non configure</span>
          <span class="v5-link-cta">Configurer &rarr;</span>
        </a>
      `).join("")}
    </div>
  `;

  // Routage SPA : interception du clic pour rester dans l'app
  widget.querySelectorAll("[data-nav-settings]").forEach((a) => {
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      const focus = a.getAttribute("data-nav-settings") || "";
      if (typeof navigateTo === "function") {
        navigateTo("settings", focus ? { focus } : undefined);
      } else {
        window.location.hash = `#/settings?focus=${encodeURIComponent(focus)}`;
      }
    });
  });
}

/**
 * U2 audit : affiche les widgets Librarian et Espace disque en bas de l'accueil,
 * + enrichit le hero avec le delta 7 derniers jours.
 * Lit state.homeGlobal (rempli par refreshHomeOverview).
 */
function renderHomeGlobalWidgets() {
  const global = state.homeGlobal || {};

  /* Hero KPI : delta 7j */
  const deltaWrap = $("homeStatDeltaWrap");
  const deltaEl = $("homeStatDelta");
  if (deltaWrap && deltaEl) {
    const delta = Number(global.delta_7d ?? global.last_7d_delta ?? 0);
    if (delta !== 0) {
      const sign = delta > 0 ? "+" : "";
      deltaEl.textContent = `${sign}${delta}`;
      deltaWrap.hidden = false;
    } else {
      deltaWrap.hidden = true;
    }
  }

  /* Librarian */
  const libCard = $("homeLibrarianCard");
  const lib = global.librarian || {};
  const suggestions = Array.isArray(lib.suggestions) ? lib.suggestions : [];
  const hs = lib.health_score ?? null;
  if (libCard) {
    if (hs === null && suggestions.length === 0) {
      libCard.classList.add("hidden");
    } else {
      libCard.classList.remove("hidden");
      const hsEl = $("homeLibHealthScore");
      if (hsEl) {
        if (hs === null) {
          hsEl.textContent = "—";
          hsEl.style.color = "";
        } else {
          hsEl.textContent = `${hs}%`;
          hsEl.style.color = hs >= 80 ? "var(--success)" : hs >= 50 ? "var(--warning)" : "var(--danger)";
        }
      }
      const listEl = $("homeLibSuggestions");
      if (listEl) {
        if (!suggestions.length) {
          listEl.innerHTML = '<p class="text-muted">Bibliothèque en excellent état.</p>';
        } else {
          listEl.innerHTML = suggestions.slice(0, 5).map((s) => {
            const p = _HOME_PRIO[s.priority] || { color: "var(--text-muted)", label: "" };
            const detailsHtml = Array.isArray(s.details) && s.details.length
              ? `<div class="suggestion-details">${s.details.map((d) => escapeHtml(d)).join(", ")}</div>`
              : "";
            return `<div class="suggestion-card" style="border-left-color:${p.color}">`
              + `<span class="badge" style="background:${p.color};color:#fff">${escapeHtml(p.label)}</span> `
              + `${escapeHtml(s.message || "")}`
              + detailsHtml
              + "</div>";
          }).join("");
        }
      }
    }
  }

  /* Espace disque */
  const spaceCard = $("homeSpaceCard");
  const space = global.space_analysis || {};
  const totalBytes = Number(space.total_bytes || 0);
  if (spaceCard) {
    if (totalBytes <= 0) {
      spaceCard.classList.add("hidden");
    } else {
      spaceCard.classList.remove("hidden");
      if ($("homeSpaceTotal")) $("homeSpaceTotal").textContent = _homeFmtBytes(totalBytes);
      if ($("homeSpaceAvg")) $("homeSpaceAvg").textContent = _homeFmtBytes(space.avg_bytes || 0);
      if ($("homeSpaceArchivable")) {
        const arch = Number(space.archivable_bytes || 0);
        const count = Number(space.archivable_count || 0);
        $("homeSpaceArchivable").textContent = arch > 0 ? `${_homeFmtBytes(arch)} (${count})` : "—";
      }
      const barsEl = $("homeSpaceBars");
      if (barsEl) {
        const byTier = space.by_tier || {};
        barsEl.innerHTML = _HOME_TIER_COLORS.map(([tier, color]) => {
          const bytes = Number(byTier[tier] || 0);
          const pct = totalBytes > 0 ? Math.round((bytes / totalBytes) * 100) : 0;
          return `<div class="space-bar-row">`
            + `<span class="space-bar-label">${escapeHtml(tier)}</span>`
            + `<div class="space-bar-track"><div class="space-bar-fill" style="width:${pct}%;background:${color}"></div></div>`
            + `<span class="space-bar-value">${_homeFmtBytes(bytes)} (${pct}%)</span>`
            + `</div>`;
        }).join("");
      }
    }
  }
}

/* --- Scan (plan) ------------------------------------------- */

async function startPlan() {
  const btnStart = $("btnStartPlan");
  // H4 : desactiver le bouton AVANT toute validation asynchrone pour eviter
  // qu'un double-clic rapide declenche 2 runs en parallele. Le bouton est
  // reactive soit ici immediatement (erreur settings), soit dans pollStatus
  // quand r.done arrive.
  if (btnStart) btnStart.disabled = true;
  if (!state.settings) {
    setStatusMessage("planMsg", "Chargez d'abord les reglages.", { error: true });
    if (btnStart) btnStart.disabled = false;
    return;
  }
  if ($("btnLoadTable")) $("btnLoadTable").disabled = true;
  setStatusMessage("planMsg", "Analyse en cours...", { loading: true });
  if ($("logboxPlan")) $("logboxPlan").textContent = "";
  if ($("homeScanProgress")) $("homeScanProgress").classList.remove("hidden");

  state.logIndex = 0;
  resetRunScopedState();

  const s = state.settings;
  const roots = s.roots || (s.root ? [s.root] : []);
  const settings = {
    root: roots[0] || s.root || "",
    roots: roots,
    state_dir: $("inState")?.value || s.state_dir,
    tmdb_enabled: $("ckTmdbEnabled")?.checked ?? s.tmdb_enabled,
    tmdb_timeout_s: parseFloat($("inTimeout")?.value || s.tmdb_timeout_s || "10"),
    tmdb_api_key: $("inApiKey")?.value || s.tmdb_api_key,
    collection_folder_enabled: $("ckCollectionMove")?.checked ?? s.collection_folder_enabled,
    collection_folder_name: $("inCollectionFolderName")?.value || s.collection_folder_name,
    empty_folders_folder_name: $("inEmptyFoldersFolderName")?.value || s.empty_folders_folder_name,
    move_empty_folders_enabled: $("ckMoveEmptyFoldersEnabled")?.checked ?? s.move_empty_folders_enabled,
    cleanup_residual_folders_folder_name: $("inResidualCleanupFolderName")?.value || s.cleanup_residual_folders_folder_name,
    cleanup_residual_folders_enabled: $("ckResidualCleanupEnabled")?.checked ?? s.cleanup_residual_folders_enabled,
    cleanup_residual_folders_scope: $("selResidualCleanupScope")?.value || s.cleanup_residual_folders_scope,
    cleanup_residual_include_nfo: $("ckResidualIncludeNfo")?.checked ?? s.cleanup_residual_include_nfo,
    cleanup_residual_include_images: $("ckResidualIncludeImages")?.checked ?? s.cleanup_residual_include_images,
    cleanup_residual_include_subtitles: $("ckResidualIncludeSubtitles")?.checked ?? s.cleanup_residual_include_subtitles,
    cleanup_residual_include_texts: $("ckResidualIncludeTexts")?.checked ?? s.cleanup_residual_include_texts,
    incremental_scan_enabled: $("ckIncrementalScanEnabled")?.checked ?? s.incremental_scan_enabled,
    enable_tv_detection: $("ckEnableTvDetection")?.checked ?? s.enable_tv_detection,
    jellyfin_enabled: $("ckJellyfinEnabled")?.checked ?? s.jellyfin_enabled,
    jellyfin_url: $("inJellyfinUrl")?.value || s.jellyfin_url,
    jellyfin_api_key: $("inJellyfinApiKey")?.value || s.jellyfin_api_key,
    jellyfin_refresh_on_apply: $("ckJellyfinRefreshOnApply")?.checked ?? s.jellyfin_refresh_on_apply,
    empty_folders_scope: $("selEmptyFoldersScope")?.value || s.empty_folders_scope,
    auto_approve_enabled: $("ckAutoApproveEnabled")?.checked ?? s.auto_approve_enabled,
    auto_approve_threshold: parseInt($("inAutoApproveThreshold")?.value || s.auto_approve_threshold || "85", 10) || 85,
    probe_backend: $("selProbeBackend")?.value || s.probe_backend,
    ffprobe_path: $("inProbeFfprobePath")?.value || s.ffprobe_path,
    mediainfo_path: $("inProbeMediainfoPath")?.value || s.mediainfo_path,
  };

  // V5bis-01 : `apiPost` au lieu du bridge pywebview direct.
  // Le backend signature `start_plan(self, settings)` -> kwargs `{ settings }`.
  const res = await apiPost("start_plan", { settings });
  if (!res.ok) {
    const errMsg = res.error || res.data?.message || "Erreur de démarrage.";
    setStatusMessage("planMsg", "Erreur : " + errMsg, { error: true });
    if (btnStart) btnStart.disabled = false;
    flashActionButton(btnStart, "error");
    return;
  }
  const r = res.data || {};

  state.runId = r.run_id;
  state.runDir = r.run_dir;
  setLastRunContext(state.runId, state.runDir);
  setPill("pillRun", "Run: " + state.runId);
  setPill("pillStatus", "En cours");
  if ($("btnOpenRunDir")) $("btnOpenRunDir").disabled = false;
  flashActionButton(btnStart, "ok");

  // BUG 3/4 : reset du compteur phase et du mini-log au demarrage d'un nouveau scan
  state.scanLastTotal = 0;
  const miniLog = $("scanMiniLog");
  if (miniLog) miniLog.innerHTML = "";

  // Nettoyer tout polling precedent puis demarrer un setTimeout recursif
  stopHomePolling();
  state.pollInFlight = false;
  state.polling = setTimeout(_schedulePoll, 650);
}

/** Arrete le polling en cours (idempotent). A appeler au changement de vue. */
function stopHomePolling() {
  if (state.polling) {
    clearTimeout(state.polling);
    clearInterval(state.polling); // Compat si une ancienne instance setInterval est active
    state.polling = null;
  }
}

/**
 * BUG 3 : append les lignes de log dans le mini-log visible sous la barre.
 * Maximum 10 lignes affichees, plus recentes en haut.
 */
function _appendScanMiniLog(logs) {
  if (!Array.isArray(logs) || !logs.length) return;
  const box = $("scanMiniLog");
  if (!box) return;
  // Normaliser les entrees en {level, msg}
  const newLines = logs.map(e => {
    if (typeof e === "string") return { level: "info", msg: e };
    if (e && typeof e === "object") {
      return { level: String(e.level || "info").toLowerCase(), msg: String(e.msg || e.message || "") };
    }
    return { level: "info", msg: String(e) };
  }).filter(x => x.msg);

  for (const line of newLines) {
    const div = document.createElement("div");
    div.className = "scan-log-line";
    if (line.level === "warning" || line.level === "warn") div.classList.add("scan-log-line--warn");
    else if (line.level === "error" || line.level === "err") div.classList.add("scan-log-line--err");
    else if (line.level === "ok" || line.level === "success") div.classList.add("scan-log-line--ok");
    div.textContent = line.msg;
    div.title = line.msg;
    // Les plus recentes en haut : prepend
    box.insertBefore(div, box.firstChild);
  }
  // Limiter a 10 lignes
  while (box.children.length > 10) {
    box.removeChild(box.lastChild);
  }
}

/** Boucle de polling non-chevauchante : re-arme apres la fin de la precedente. */
function _schedulePoll() {
  if (!state.polling) return;
  pollStatus().finally(() => {
    if (state.polling) {
      state.polling = setTimeout(_schedulePoll, 650);
    }
  });
}

async function pollStatus() {
  if (!state.runId || state.pollInFlight) return;
  state.pollInFlight = true;
  try {
    // V5bis-01 : signature backend `get_status(self, run_id, last_log_index=0)`.
    const res = await apiPost("get_status", { run_id: state.runId, last_log_index: state.logIndex });
    if (!res.ok) {
      setStatusMessage("planMsg", "Impossible de recuperer l'etat.", { error: true });
      return;
    }
    const r = res.data || {};
    const idx = r.idx || 0;
    const total = r.total || 0;
    const fill = $("progressFill");

    // BUG 4 : phase decouverte vs phase analyse.
    // Heuristique : si le total a augmente depuis le dernier poll, on est encore
    // en phase de decouverte → barre shimmer + compteur "X dossiers trouves".
    // Sinon on est en phase d'analyse → barre deterministe avec %.
    if (state.scanLastTotal === undefined) state.scanLastTotal = 0;
    const totalGrew = total > state.scanLastTotal;
    state.scanLastTotal = total;
    const inDiscovery = totalGrew || (total > 0 && idx === 0);

    /* K18 : activer la pellicule pendant toute la duree du scan (bar parent). */
    const progBar = fill ? fill.parentElement : null;
    if (progBar) progBar.classList.add("progress-bar--filmstrip");

    if (fill) {
      if (inDiscovery || total === 0) {
        fill.classList.add("progress-fill--shimmer");
      } else {
        fill.classList.remove("progress-fill--shimmer");
        const pct = Math.floor((idx / total) * 100);
        fill.style.width = pct + "%";
      }
    }
    if ($("progCount")) {
      if (inDiscovery || total === 0) {
        $("progCount").textContent = total > 0
          ? `Découverte en cours... ${total} dossiers trouvés`
          : `${idx} films trouvés...`;
      } else {
        const pct = Math.floor((idx / total) * 100);
        $("progCount").textContent = `Analyse : ${idx}/${total} (${pct}%)`;
      }
    }
    if ($("progSpeed")) $("progSpeed").textContent = fmtSpeed(r.speed || 0);
    if ($("progEta")) $("progEta").textContent = inDiscovery ? "—" : fmtEta(r.eta_s || 0);
    if ($("progCurrent")) {
      const cur = r.current || "—";
      $("progCurrent").textContent = "📂 " + shortPath(cur, 150);
      $("progCurrent").title = String(cur);
    }
    // BUG 3 : mini-log visible en permanence, 10 dernieres lignes en haut
    _appendScanMiniLog(r.logs || []);
    appendLogs("logboxPlan", r.logs);
    state.logIndex = r.next_log_index || state.logIndex;

    if (r.error) {
      setPill("pillStatus", "Erreur");
      setStatusMessage("planMsg", "Erreur : " + r.error, { error: true });
      $("btnStartPlan").disabled = false;
      stopHomePolling();
      /* K18 : retirer la pellicule quand le scan est termine ou en erreur. */
      const _barEl = document.getElementById("progressBar") || document.querySelector(".progress-bar");
      if (_barEl) _barEl.classList.remove("progress-bar--filmstrip");
      return;
    }
    if (r.done) {
      setPill("pillStatus", "Termine");
      setStatusMessage("planMsg", total > 0 ? "Analyse terminée. Chargez la table de validation." : "Aucun dossier vidéo détecté.");
      $("btnStartPlan").disabled = false;
      if ($("btnLoadTable")) $("btnLoadTable").disabled = false;
      stopHomePolling();
      /* K18 : retirer la pellicule quand le scan est termine ou en erreur. */
      const _barEl = document.getElementById("progressBar") || document.querySelector(".progress-bar");
      if (_barEl) _barEl.classList.remove("progress-bar--filmstrip");
      // C1 : rafraichir l'accueil (KPIs, Dernier Run, signaux) apres un scan.
      // Sans ca, l'utilisateur reste sur l'ancien etat jusqu'a la prochaine navigation.
      try {
        await refreshHomeOverview({ silent: true });
      } catch (err) {
        console.error("[home] post-scan refresh", err);
      }
    }
  } finally {
    state.pollInFlight = false;
  }
}

/* --- Auto-install probe tools ------------------------------ */

function updateProbeInstallBanner() {
  const banner = $("homeProbeInstallBanner");
  if (!banner) return;
  // V5A-04 V1-07 : marquer le banner avec la classe V5 pour la hierarchie
  // visuelle (alert--warning + outils manquants + bouton auto-install). La
  // classe v5-home-probe-banner sert d'ancre stylistique et de selecteur
  // pour les tests structurels (cf get_probe_tools_status / auto_install_probe_tools).
  banner.classList.add("v5-alert", "v5-alert--warning", "v5-home-probe-banner");
  banner.setAttribute("role", "alert");
  // C5 : structure { tools: { ffprobe: { available }, mediainfo: { available } } }
  const ps = state.probeToolsStatus?.tools || {};
  const ffOk = !!ps.ffprobe?.available;
  const miOk = !!ps.mediainfo?.available;
  if (ffOk && miOk) {
    banner.classList.add("hidden");
  } else {
    banner.classList.remove("hidden");
    const msg = $("probeInstallMsg");
    if (msg) {
      const missing = [];
      if (!ffOk) missing.push("FFprobe");
      if (!miOk) missing.push("MediaInfo");
      msg.textContent = `Outils d'analyse video manquants : ${missing.join(", ")}. `
        + "L'analyse qualite sera limitee tant que ces outils ne sont pas installes.";
    }
  }
}

async function autoInstallProbeTools() {
  const btn = $("btnAutoInstallProbe");
  const msg = $("probeInstallMsg");
  if (btn) btn.disabled = true;
  if (msg) msg.textContent = "Installation en cours...";

  try {
    // V5bis-01 : `apiPost` REST + fallback pywebview.
    const res = await apiPost("auto_install_probe_tools");
    if (res.ok) {
      if (msg) { msg.textContent = "Outils installes avec succes !"; msg.className = "text-success"; }
      /* Rafraichir le statut probe */
      const probeRes = await apiPost("recheck_probe_tools");
      if (probeRes && probeRes.ok) state.probeToolsStatus = probeRes.data || null;
      renderHomeOverview();
      updateProbeInstallBanner();
    } else {
      const errMsg = res.error || res.data?.message || "Erreur inconnue";
      if (msg) { msg.textContent = "Echec : " + errMsg; msg.className = "text-danger"; }
      if (btn) btn.disabled = false;
    }
  } catch (err) {
    if (msg) { msg.textContent = "Erreur reseau. Verifiez la connexion internet."; msg.className = "text-danger"; }
    if (btn) btn.disabled = false;
  }
}

/* --- Event hookup ------------------------------------------ */

function hookHomeEvents() {
  $("btnStartPlan")?.addEventListener("click", startPlan);
  $("btnAutoInstallProbe")?.addEventListener("click", autoInstallProbeTools);
  $("btnLoadTable")?.addEventListener("click", async () => {
    await loadTable();
    showView("validation");
  });
  $("btnOpenRunDir")?.addEventListener("click", () => {
    if (state.runDir) openPathWithFeedback(state.runDir, "planMsg");
  });
  /* BUG 1 : bouton "Forcer le rescan complet" — purge le cache incremental
     puis relance un scan. Utile quand les regles de scoring ont ete modifiees
     ou que le cache semble retourner des resultats obsoletes. */
  $("btnForceFullRescan")?.addEventListener("click", async () => {
    const confirmed = await (window.uiConfirm
      ? window.uiConfirm(
          "Forcer un rescan complet ?",
          "Cela purge le cache incrémental et relance une analyse complète. Le prochain scan sera plus long."
        )
      : Promise.resolve(confirm("Forcer un rescan complet ? Cela purge le cache incremental.")));
    if (!confirmed) return;
    setStatusMessage("planMsg", "Purge du cache incrémental…", { loading: true });
    // V5bis-01 : `apiPost` REST + fallback pywebview.
    const res = await apiPost("reset_incremental_cache");
    if (res && res.ok) {
      const okMsg = res.data?.message || "Cache purgé.";
      setStatusMessage("planMsg", okMsg, { success: true });
      await startPlan();
    } else {
      const errMsg = res?.error || res?.data?.message || "Purge du cache impossible.";
      setStatusMessage("planMsg", errMsg, { error: true });
    }
  });
  $("btnHomeGoValidation")?.addEventListener("click", () => navigateTo("validation"));
  $("btnHomeGoQuality")?.addEventListener("click", () => navigateTo("quality"));
  $("btnHomeGoExecution")?.addEventListener("click", () => navigateTo("execution"));

  /* Signals list: click to navigate */
  $("homeSignalsList")?.addEventListener("click", (e) => {
    const item = e.target.closest("[data-nav]");
    if (item) navigateTo(item.dataset.nav);
  });
}

/* --- V5bis-01 : entry point standardise pour les vues v5 portees --- */

/** Garde-fou : `hookHomeEvents` ne doit etre appele qu'une fois pour eviter
 *  les listeners dupliques en cas de re-mount. */
let _homeEventsHooked = false;

/**
 * V5bis-01 — Point d'entree standard pour la vue Home portee.
 *
 * Wrappe `refreshHomeOverview` (loader) + `renderHomeOverview` (renderer)
 * via `initView` du helper (skeleton -> load -> render | error retry).
 * Branche les listeners DOM une seule fois (`_homeEventsHooked`).
 *
 * @param {HTMLElement} container - conteneur DOM (usuellement #view-home)
 * @param {object} [opts] - reserve pour usage futur (filtres, focus, etc.)
 */
export async function initHome(container, opts = {}) {
  void opts;
  // Branche les listeners une seule fois (idempotent).
  if (!_homeEventsHooked) {
    hookHomeEvents();
    _homeEventsHooked = true;
  }
  // `initView` gere le pattern skeleton -> load -> render | error retry.
  // On adapte l'API : `refreshHomeOverview` ne retourne pas de donnees a
  // injecter (il met a jour `state.homeOverview` puis declenche les
  // renderers internes), donc le renderer recoit `null` et ne fait rien
  // de plus que ce que le loader a deja declenche.
  await initView(
    container,
    async () => { await refreshHomeOverview(); return null; },
    () => { /* le rendu est realise dans refreshHomeOverview */ },
    { skeletonType: "default" }
  );
}
