/* views/status.js — Vue Etat global du dashboard distant
 *
 * V7-fix : refactor partial-update.
 *   - Premier rendu : innerHTML complet (shell + valeurs).
 *   - Polling tick suivant : si signature shell inchangee, patch les valeurs
 *     dynamiques uniquement (pas d'innerHTML, pas de flicker).
 *   - Pendant un run actif, fetch `get_status(run_id)` pour avoir le vrai
 *     compteur idx/total, vitesse et ETA — au lieu de global.total_movies
 *     qui ne bouge pas avant la fin du scan.
 */

import { $, escapeHtml } from "../core/dom.js";
import { apiGet, apiPost, invalidateSettingsCache } from "../core/api.js";
import { startPolling, stopPolling, checkEventChanged, checkSettingsChanged } from "../core/state.js";
import { getNavSignal } from "../core/nav-abort.js";
import { kpiGridHtml, kpiCardHtml } from "../components/kpi-card.js";
import { servicesGridHtml } from "../components/services-grid.js";
import { activityFeedHtml } from "../components/activity-feed.js";
import { fmtDate as _fmtDate, fmtBytes as _fmtBytes } from "../core/format.js";
import { glossaryTooltip } from "../components/glossary-tooltip.js";
// V7-fusion Phase 1 : section "Apercu V2" injectee depuis composants v5 partages.
// Ces composants existent deja (Vague 2 v7.6.0) et sont sans dependance externe.
import { renderKpiGrid as _renderV2Kpis, renderInsights as _renderV2Insights } from "../components/home-widgets.js";
import { renderDonut as _renderV2Donut, renderLine as _renderV2Line } from "../components/home-charts.js";

/* --- Etat local de la vue ---------------------------------- */

let _activeRunId = null;
let _shellSignature = null;
let _hooksAttached = false;

const _RING_R = 60;
const _RING_CIRC = 2 * Math.PI * _RING_R;

const _WORKFLOW = [
  { label: "1. Analyse", href: "/library#step-analyse" },
  { label: "2. Verification", href: "/library#step-verification" },
  { label: "3. Validation", href: "/library#step-validation" },
  { label: "4. Doublons", href: "/library#step-doublons" },
  { label: "5. Application", href: "/library#step-application" },
];

function _trendArrow(trend) {
  if (!trend) return null;
  const t = String(trend).toLowerCase();
  if (t.includes("up") || t.includes("↑") || t === "hausse") return "up";
  if (t.includes("down") || t.includes("↓") || t === "baisse") return "down";
  return "stable";
}

function _avgScoreColor(score) {
  const s = Number(score || 0);
  if (s >= 75) return "var(--success, #34D399)";
  if (s >= 54) return "var(--gold, #F59E0B)";
  return "var(--danger, #F87171)";
}

function _detectActiveStep(runStatus) {
  // Pendant le scan/plan, on est etape 1 (Analyse). L'etape "Validation" /
  // "Application" demande une UI manuelle, on ne la deduit pas du status.
  if (!runStatus) return -1;
  if (runStatus.running) return 0;
  if (runStatus.done && !runStatus.error) return 1; // analyse finie → verification dispo
  return -1;
}

/* --- Fetch consolidé --------------------------------------- */

async function _fetchAll() {
  // V2-C R4-MEM-6 : signal de nav pour abort si l'utilisateur navigate ailleurs
  // pendant que les fetchs sont en vol (le polling status fait jusqu'a 5 fetchs
  // en parallele toutes les 2-15s).
  const navSig = getNavSignal();
  const calls = [
    apiGet("/api/health"),
    apiPost("get_global_stats", { limit_runs: 10 }, { signal: navSig }),
    apiPost("get_settings", {}, { signal: navSig }),
    apiPost("get_probe_tools_status", {}, { signal: navSig }),
  ];
  // Si on sait qu'un run est actif (pre-tick), on ajoute get_status pour
  // avoir le vrai progres (idx/total/eta) sans attendre la fin.
  const wantStatus = _activeRunId;
  if (wantStatus) {
    calls.push(apiPost("get_status", { run_id: wantStatus, last_log_index: 0 }, { signal: navSig }));
  }
  const results = await Promise.allSettled(calls);
  const _val = (r) => (r && r.status === "fulfilled" && r.value ? r.value.data || {} : {});
  const out = {
    health: _val(results[0]),
    global: _val(results[1]),
    settings: _val(results[2]),
    probe: _val(results[3]),
    runStatus: wantStatus ? _val(results[4]) : null,
  };
  const failed = ["/api/health", "get_global_stats", "get_settings", "get_probe_tools_status", "get_status"]
    .filter((_, i) => i < calls.length && results[i].status !== "fulfilled");
  if (failed.length > 0) console.warn("[status] endpoints en echec (rendu partiel):", failed);
  return out;
}

/* --- ViewModel -------------------------------------------- */

function _buildVm(data) {
  const { health, global, settings, probe, runStatus } = data;
  const isRunActive = !!health.active_run_id;
  const runs = global.runs_summary || [];
  const lastRun = runs[0] || null;
  const trend = _trendArrow(global.trend);

  // Compteur films traites : pendant un run actif on prend idx du runStatus
  // (vrai compteur live). Sinon total_movies de la BDD.
  const totalMovies = global.total_movies ?? lastRun?.total_rows ?? 0;
  const rsIdx = Number(runStatus?.idx ?? 0);
  const rsTotal = Number(runStatus?.total ?? 0);
  const heroValue = isRunActive
    ? (rsTotal > 0 ? `${rsIdx}/${rsTotal}` : (rsIdx > 0 ? String(rsIdx) : "—"))
    : (totalMovies || "—");

  // Ring : pendant un run, % progres ; sinon score moyen.
  const avgScore = global.avg_score != null ? Math.round(global.avg_score) : null;
  const ringPct = isRunActive
    ? (rsTotal > 0 ? Math.min(100, Math.round((rsIdx / rsTotal) * 100)) : 0)
    : (avgScore ?? 0);
  const ringLabel = isRunActive
    ? (rsTotal > 0 ? `${ringPct}%` : "...")
    : (avgScore != null ? String(avgScore) : "—");
  const ringSublabel = isRunActive ? "scan" : "score moyen";
  const ringOffset = (_RING_CIRC * (1 - ringPct / 100)).toFixed(2);

  // Meta items hero
  const premiumPct = global.premium_pct != null ? Math.round(global.premium_pct) : null;
  const heroMeta = isRunActive
    ? [
        { v: runStatus?.current ? _shortFolder(runStatus.current) : "—", l: "En cours" },
        { v: runStatus?.speed ? `${runStatus.speed.toFixed(1)}/s` : "—", l: "Vitesse" },
        { v: runStatus?.eta_s ? _fmtEta(runStatus.eta_s) : "—", l: "ETA restant" },
      ]
    : [
        { v: premiumPct != null ? premiumPct + "%" : "—", l: "Platinum", pos: (premiumPct ?? 0) >= 25 },
        { v: global.total_runs ?? "—", l: "Runs" },
        ...(trend
          ? [{ v: trend === "up" ? "↑" : trend === "down" ? "↓" : "→", l: "Tendance",
              pos: trend === "up", neg: trend === "down" }]
          : []),
      ];

  const workflowActive = isRunActive ? 0 : -1;

  // Probes
  const _pt = probe.tools || {};
  const mi = _pt.mediainfo || {};
  const ff = _pt.ffprobe || {};
  const miOk = !!mi.available;
  const ffOk = !!ff.available;
  const miVersion = mi.version || "";
  const ffVersion = ff.version || "";

  // Settings
  const roots = Array.isArray(settings.roots) ? settings.roots : (settings.root ? [settings.root] : []);
  const perceptualEnabled = !!settings.perceptual_enabled;
  const watchEnabled = !!settings.watch_enabled;
  const watchMin = Number(settings.watch_interval_minutes || 5);
  const namingPreset = String(settings.naming_preset || "default");
  const namingLabel = { default: "Standard", plex: "Plex", jellyfin: "Jellyfin", quality: "Qualite", custom: "Personnalise" }[namingPreset] || namingPreset;
  const namingTpl = namingPreset === "custom" ? ` (${settings.naming_movie_template || ""})` : "";

  // Services
  const services = [
    {
      key: "jellyfin", name: "Jellyfin", initial: "J",
      avatar_bg: "#00A4DC", avatar_fg: "#fff", label: "Jellyfin",
      subtitle: settings.jellyfin_enabled ? "En ligne" : "Désactivé",
      status: settings.jellyfin_enabled ? "on" : "off",
      href: settings.jellyfin_enabled ? "/jellyfin" : undefined,
    },
    {
      key: "plex", name: "Plex", initial: "P",
      avatar_bg: "#282A2D", avatar_fg: "#EBAF00", label: "Plex",
      subtitle: settings.plex_enabled ? "Connecté" : "Désactivé",
      status: settings.plex_enabled ? "on" : "off",
      href: settings.plex_enabled ? "/plex" : undefined,
    },
    {
      key: "radarr", name: "Radarr", initial: "R",
      avatar_bg: "#FFC230", avatar_fg: "#000", label: "Radarr",
      subtitle: settings.radarr_enabled ? "Synchronisé" : "Désactivé",
      status: settings.radarr_enabled ? "on" : "off",
      href: settings.radarr_enabled ? "/radarr" : undefined,
    },
    {
      key: "tmdb", name: "TMDb", initial: "T",
      avatar_bg: "#01B4E4", avatar_fg: "#fff", label: "TMDb",
      subtitle: settings.tmdb_api_key ? "Clé configurée" : "Non configuré",
      status: settings.tmdb_api_key ? "on" : "warn",
    },
  ];

  // Tier distribution
  const tierDist = global.tier_distribution || {};
  const tierPlatinum = Number(tierDist.Platinum ?? tierDist.Premium ?? 0);
  const tierGold = Number(tierDist.Gold ?? tierDist.Bon ?? 0);
  const tierSilver = Number(tierDist.Silver ?? tierDist.Moyen ?? 0);
  const tierBronze = Number(tierDist.Bronze ?? 0);
  const tierReject = Number(tierDist.Reject ?? tierDist.Mauvais ?? tierDist.Faible ?? 0);
  const tierTotal = tierPlatinum + tierGold + tierSilver + tierBronze + tierReject;
  const _pct = (n) => (tierTotal > 0 ? Math.max(1, Math.round((n / tierTotal) * 100)) : 0);
  const tiers = {
    platinum: { count: tierPlatinum, pct: _pct(tierPlatinum) },
    gold:     { count: tierGold,     pct: _pct(tierGold) },
    silver:   { count: tierSilver,   pct: _pct(tierSilver) },
    bronze:   { count: tierBronze,   pct: _pct(tierBronze) },
    reject:   { count: tierReject,   pct: _pct(tierReject) },
  };

  // Activite recente
  const activityEvents = (runs || []).slice(0, 4).map((r) => {
    const score = r.avg_score != null ? Math.round(r.avg_score) : null;
    const tier = score == null ? "info" : score >= 75 ? "ok" : score >= 54 ? "warn" : "err";
    const timeText = r.started_at ? _fmtDate(r.started_at) : "—";
    const nbFilms = r.total_rows ?? "—";
    const scoreText = score != null ? `${score}/100` : "pas de score";
    return {
      icon: tier,
      title: `Run ${escapeHtml(String(r.run_id || "").slice(0, 12))} · ${nbFilms} films · ${scoreText}`,
      time: timeText,
    };
  });

  // Banner outils manquants
  const ffAvail = !!ff.available;
  const miAvail = !!mi.available;
  const missing = [];
  if (!ffAvail) missing.push("FFprobe");
  if (!miAvail) missing.push("MediaInfo");
  const showProbeBanner = missing.length > 0;

  // Banner prudence
  const isDryRunDefault = !!settings.dry_run_default;
  const isFirstRun = !global.total_runs;
  const showPrudent = isDryRunDefault || isFirstRun;
  const prudentMsg = isDryRunDefault ? "Dry-run actif par défaut" : "Premier lancement — dry-run recommandé";

  // Espace disque
  const space = global.space_analysis || {};
  const showSpace = (space.total_bytes || 0) > 0;

  // Suggestions
  const lib = global.librarian || {};
  const suggestions = lib.suggestions || [];
  const hs = lib.health_score ?? 100;
  const showSuggestions = suggestions.length > 0 || hs < 100;

  // Tendance sante
  const ht = global.health_trend || {};
  const timelinePoints = (global.timeline || []).filter((p) => p.health_score != null);
  const showTrend = timelinePoints.length >= 2;

  // Signaux
  const signals = [];
  if (global.top_anomalies?.length) signals.push({ text: `${global.top_anomalies.length} type(s) d'anomalies`, route: "/library" });
  if (lastRun?.health_snapshot?.health_score < 70) signals.push({ text: `Santé bibliothèque : ${lastRun.health_snapshot.health_score}%`, route: "/quality" });
  if (showProbeBanner) signals.push({ text: "Outils d'analyse manquants", route: "/settings" });
  if (!settings.tmdb_api_key) signals.push({ text: "Clé TMDb non configurée", route: "/settings" });

  // Run progress (si actif)
  const progressPct = isRunActive && rsTotal > 0 ? Math.min(100, Math.round((rsIdx / rsTotal) * 100)) : 0;
  const progressText = isRunActive
    ? (rsTotal > 0
        ? `${rsIdx} / ${rsTotal} films analysés${runStatus?.current ? ` — ${_shortFolder(runStatus.current)}` : ""}`
        : "Initialisation...")
    : "";

  // V7-fusion Phase 1 : Apercu V2 (composants v5 partages)
  // Conditionnel : ne rend rien si le backend ne retourne pas les nouveaux champs.
  const v2Donut = global.v2_tier_distribution || null;
  const v2Trend = Array.isArray(global.trend_30days) ? global.trend_30days : [];
  const v2Insights = Array.isArray(global.insights) ? global.insights : [];
  const hasV2Donut = !!(v2Donut && v2Donut.scored_total);
  const hasV2Trend = v2Trend.length >= 2;
  const hasV2Insights = v2Insights.length > 0;
  const hasV2Overview = hasV2Donut || hasV2Trend || hasV2Insights;
  const v2Kpis = hasV2Donut ? [
    { label: "Films classes V2", value: String(v2Donut.scored_total || 0), icon: "library" },
    { label: "Score moyen", value: global.avg_score != null ? Math.round(global.avg_score) : "—",
      suffix: global.avg_score != null ? "/100" : "",
      trend: trend === "up" ? "↑" : trend === "down" ? "↓" : "",
      icon: "bar-chart" },
    { label: "Platinum + Gold", value: String((Number(v2Donut.percentages?.platinum || 0) + Number(v2Donut.percentages?.gold || 0)).toFixed(0)),
      suffix: "%", tier: "gold", icon: "award" },
    { label: "Reject", value: String(Number(v2Donut.percentages?.reject || 0).toFixed(0)),
      suffix: "%", tier: "reject", icon: "alert-triangle" },
  ] : [];

  return {
    isRunActive, activeRunId: health.active_run_id,
    heroLabel: isRunActive ? "RUN ACTIF — SCAN BIBLIOTHÈQUE" : "BIBLIOTHÈQUE — VUE D'ENSEMBLE",
    heroSubLabel: isRunActive ? "Films traités" : "Films analysés",
    heroValue, heroMeta,
    ringPct, ringLabel, ringSublabel, ringOffset,
    workflowActive, workflowSteps: _WORKFLOW,
    avgScoreColor: _avgScoreColor(global.avg_score),
    services,
    tiers, tierTotal,
    health: { miOk, ffOk, miVersion, ffVersion, perceptualEnabled, watchEnabled, watchMin, roots, namingLabel, namingTpl },
    activityEvents,
    showProbeBanner, missing,
    showPrudent, prudentMsg,
    space, showSpace,
    suggestions, hs, showSuggestions,
    timelinePoints, ht, showTrend,
    signals,
    progressPct, progressText,
    showRemoteAccess: !!settings.rest_api_enabled,
    // V7-fusion Phase 1 : Apercu V2
    hasV2Overview, v2Donut, v2Trend, v2Insights, v2Kpis,
  };
}

function _shortFolder(p) {
  if (!p) return "";
  const parts = String(p).split(/[\\/]/).filter(Boolean);
  return parts.slice(-1)[0] || p;
}

function _fmtEta(s) {
  s = Number(s || 0);
  if (s <= 0) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}min`;
  return `${Math.floor(s / 3600)}h${Math.round((s % 3600) / 60)}`;
}

/* --- Signature shell (decide rerender vs patch) ----------- */

function _shellSignatureOf(vm) {
  return JSON.stringify({
    runActive: vm.isRunActive,
    showProbeBanner: vm.showProbeBanner,
    showPrudent: vm.showPrudent,
    showSpace: vm.showSpace,
    showSuggestions: vm.showSuggestions,
    showTrend: vm.showTrend,
    signalsCount: vm.signals.length,
    showRemote: vm.showRemoteAccess,
    services: vm.services.map((s) => `${s.key}:${s.status}`).join("|"),
    suggCount: vm.suggestions.length,
    activityCount: vm.activityEvents.length,
    rootsCount: vm.health.roots.length,
    namingLabel: vm.health.namingLabel + vm.health.namingTpl,
    perceptual: vm.health.perceptualEnabled,
    watchEnabled: vm.health.watchEnabled,
    watchMin: vm.health.watchMin,
    // V7-fusion Phase 1 : presence/absence Apercu V2
    hasV2Overview: vm.hasV2Overview,
    v2InsightsCount: vm.v2Insights.length,
  });
}

/* --- Render full shell ------------------------------------ */

function _renderShell(vm, container) {
  let html = '<div class="bento">';

  // === HERO ===
  // On utilise kpiCardHtml puis on ajoute des data-* via rewrap : pour
  // garder la liberte de patcher, on construit le hero a la main ici.
  html += _renderHeroHtml(vm);

  // === V7-fusion Phase 1 : Apercu V2 (composants v5 partages) ===
  // Conditionnel : ne rend rien si le backend ne retourne pas v2_tier_distribution.
  // 4 sous-blocs : KPI grid (4 cards) + Insights (alertes) + Donut (distrib) + Line (trend 30j).
  // Les composants sont montes apres innerHTML via _mountV2Overview() (cf. _renderShell fin).
  if (vm.hasV2Overview) {
    html += `<div class="card bento-card bento-card--wide v5-overview-card">
      <h3>Aperçu V2 — vue d'ensemble bibliothèque</h3>
      <div class="v5-overview-grid" style="display:grid;gap:var(--sp-4);margin-top:var(--sp-3)">
        <div id="v2-overview-kpis" data-stat="v2-kpis"></div>
        <div id="v2-overview-insights" data-stat="v2-insights"></div>
        <div class="v5-overview-charts" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:var(--sp-4)">
          <div id="v2-overview-donut" data-stat="v2-donut"></div>
          <div id="v2-overview-line" data-stat="v2-line"></div>
        </div>
      </div>
    </div>`;
  }

  // === Services ===
  html += `<div class="card bento-card bento-card--side"><h3>Services connectés</h3>
    <div data-stat="services-grid">${servicesGridHtml(vm.services)}</div>
    <button class="btn btn-block mt-4" data-nav-route="/settings">Tester les connexions</button>
  </div>`;

  // === Distribution qualite ===
  html += `<div class="card bento-card bento-card--half">
    <h3>Distribution qualité <span class="badge" style="margin-left:auto" data-stat="tier-total">${vm.tierTotal} films</span></h3>
    <div class="quality-rows" style="margin-top:var(--sp-4)">
      ${["platinum", "gold", "silver", "bronze", "reject"].map((k) => {
        const label = k.charAt(0).toUpperCase() + k.slice(1);
        return `<div class="quality-row">
          <span class="tier-label tier-${k}"><span class="tier-dot"></span>${label}</span>
          <div class="quality-track"><div class="quality-fill tier-${k}" data-tier-fill="${k}" style="width:${vm.tiers[k].pct}%"></div></div>
          <span class="quality-value" data-tier-count="${k}">${vm.tiers[k].count}</span>
        </div>`;
      }).join("")}
    </div>
  </div>`;

  // === Run progress card (si actif) ===
  if (vm.isRunActive) {
    html += `<div id="statusRunProgress" class="card bento-card bento-card--half">
      <h3><span class="live-dot"></span> ${glossaryTooltip("Run")} en cours : <span class="text-accent">${escapeHtml(vm.activeRunId || "")}</span></h3>
      <div id="statusProgressBar" class="progress-bar mt-4">
        <div class="progress-fill" data-stat="progress-fill" style="width:${vm.progressPct}%"></div>
      </div>
      <p id="statusProgressText" class="text-muted mt-4" data-stat="progress-text">${escapeHtml(vm.progressText)}</p>
      <button id="btnCancelRun" class="btn btn-danger mt-4">Annuler</button>
    </div>`;
  }

  // === Sante ===
  html += `<div class="card bento-card bento-card--third"><h3>Santé</h3>
    <ul class="status-health-list" style="margin-top:var(--sp-3)" data-stat="health-list">
      ${_renderHealthListHtml(vm.health)}
    </ul>
  </div>`;

  // === Activite recente ===
  html += `<div class="card bento-card bento-card--third"><h3>Activite recente</h3>
    <div data-stat="activity">${activityFeedHtml(vm.activityEvents, { emptyMessage: "Aucun run pour le moment." })}</div>
  </div>`;

  // === Actions rapides ===
  html += `<div class="card bento-card bento-card--third"><h3>Actions rapides</h3>
    <div style="display:flex;flex-direction:column;gap:var(--sp-3);margin-top:var(--sp-3)">
      <button class="btn btn-primary" style="justify-content:flex-start" data-nav-route="/library#step-analyse">▶ Lancer un nouveau scan</button>
      <button class="btn" style="justify-content:flex-start" data-nav-route="/library#step-doublons">⎘ Verifier les doublons</button>
      <button class="btn" style="justify-content:flex-start" data-nav-route="/quality">▼ Voir la qualite</button>
      <button class="btn" style="justify-content:flex-start" data-nav-route="/settings">⚙ Parametres</button>
    </div>
  </div>`;

  // === Espace disque ===
  if (vm.showSpace) {
    html += _renderSpaceHtml(vm.space);
  }

  // === Suggestions ===
  if (vm.showSuggestions) {
    html += _renderSuggestionsHtml(vm.suggestions, vm.hs);
  }

  // === Tendance sante ===
  if (vm.showTrend) {
    html += _renderTrendHtml(vm.timelinePoints, vm.ht);
  }

  html += "</div>"; // /bento

  // Banners hors bento
  if (vm.showProbeBanner) {
    html += `<div class="card card--banner mt-4" id="dashProbeInstallBanner">
      <span class="text-warning" id="dashProbeInstallMsg">Outils d'analyse vidéo manquants : ${escapeHtml(vm.missing.join(", "))}.</span>
      <button id="btnDashAutoInstallProbe" class="btn btn-primary btn--compact">Installer automatiquement</button>
    </div>`;
  }
  if (vm.showPrudent) {
    html += `<div class="card card--banner mt-4" style="border-left-color:var(--warning)">
      <span class="badge badge-warning">Prudent</span>
      <span>${escapeHtml(vm.prudentMsg)}</span>
    </div>`;
  }
  if (vm.signals.length) {
    html += '<div class="card mt-4"><h3>Points d\'attention</h3><div class="mt-2">';
    for (const s of vm.signals) {
      html += `<div class="signal-item mb-2" data-nav-route="${escapeHtml(s.route)}">
        <span class="badge badge-warning">!</span> ${escapeHtml(s.text)}
      </div>`;
    }
    html += '</div></div>';
  }
  if (vm.showRemoteAccess) {
    html += `<div class="card mt-4" id="statusRemoteAccess">
      <h3>📱 Accès distant (téléphone / autre PC)</h3>
      <p class="text-muted">Ouvre CineSort depuis n'importe quel appareil du même réseau Wi-Fi.</p>
      <div id="statusRemoteAccessBody" style="margin-top:var(--sp-3)"><span class="text-muted">Chargement…</span></div>
    </div>`;
  }

  // Boutons nav
  html += `<div class="flex gap-2 mt-6">
    <button class="btn btn-primary" data-nav-route="/library">Ouvrir Bibliothèque</button>
    <button class="btn" data-nav-route="/quality">Voir Qualité</button>
    <button class="btn" data-nav-route="/logs">Ouvrir Journaux</button>
  </div>
  <div id="statusActionMsg" class="status-msg mt-4"></div>`;

  container.innerHTML = html;
}

function _renderHeroHtml(vm) {
  const cls = vm.isRunActive ? "kpi-card kpi-card--hero bento-card--hero is-run-active" : "kpi-card kpi-card--hero bento-card--hero";
  return `<div class="${cls}" style="border-left-color:${vm.avgScoreColor}" data-stat="hero-card">
    <h3><span class="live-dot"></span> <span data-stat="hero-label">${escapeHtml(vm.heroLabel)}</span></h3>
    <div class="hero-content">
      <div class="hero-primary">
        <div class="hero-label" data-stat="hero-sublabel">${escapeHtml(vm.heroSubLabel)}</div>
        <div class="hero-value" data-stat="hero-value">${escapeHtml(String(vm.heroValue))}</div>
        <div class="hero-meta" data-stat="hero-meta">${_metaItemsInner(vm.heroMeta)}</div>
      </div>
      <div class="ring" aria-label="Progression ${escapeHtml(vm.ringLabel)}">
        <svg width="140" height="140" viewBox="0 0 140 140">
          <circle cx="70" cy="70" r="60" class="ring-track"/>
          <circle cx="70" cy="70" r="60" class="ring-fill" data-stat="ring-fill"
                  stroke-dasharray="${_RING_CIRC.toFixed(2)}"
                  stroke-dashoffset="${vm.ringOffset}"/>
        </svg>
        <div class="ring-label">
          <strong data-stat="ring-label">${escapeHtml(vm.ringLabel)}</strong>
          <small data-stat="ring-sublabel">${escapeHtml(vm.ringSublabel)}</small>
        </div>
      </div>
    </div>
    <div class="workflow-strip" data-stat="workflow">
      ${vm.workflowSteps.map((s, i) => {
        const cls = ["workflow-step"];
        if (i === vm.workflowActive) cls.push("active");
        return `<div class="${cls.join(" ")}" data-workflow-step="${i}" data-nav-route="${escapeHtml(s.href)}">${escapeHtml(s.label)}</div>`;
      }).join("")}
    </div>
  </div>`;
}

function _metaItemsInner(meta) {
  if (!Array.isArray(meta) || meta.length === 0) return "";
  return meta.map((m) => {
    const cls = m.pos ? "v pos" : m.neg ? "v neg" : "v";
    return `<div class="meta-item"><span class="${cls}">${escapeHtml(String(m.v ?? "—"))}</span><span class="l">${escapeHtml(String(m.l ?? ""))}</span></div>`;
  }).join("");
}

function _renderHealthListHtml(h) {
  const items = [];
  items.push(`<li>${h.miOk ? "✅" : "❌"} MediaInfo : ${h.miOk ? "OK" + (h.miVersion ? " v" + escapeHtml(h.miVersion) : "") : "non detecte"}</li>`);
  items.push(`<li>${h.ffOk ? "✅" : "❌"} FFprobe : ${h.ffOk ? "OK" + (h.ffVersion ? " v" + escapeHtml(h.ffVersion) : "") : "non detecte"}</li>`);
  items.push(`<li>${h.perceptualEnabled ? "✅ Analyse perceptuelle activee" : "⚪ Analyse perceptuelle desactivee"}</li>`);
  items.push(`<li>${h.watchEnabled
    ? `<span class="watcher-status watcher-status--active">\u{1F50D} Veille active (${h.watchMin} min)</span>`
    : '<span class="watcher-status">⚪ Veille desactivee</span>'}</li>`);
  items.push(`<li>📁 ${h.roots.length} root(s) : ${h.roots.map((r) => escapeHtml(r)).join(", ") || "aucun"}</li>`);
  items.push(`<li>🎬 Profil : ${escapeHtml(h.namingLabel)}${escapeHtml(h.namingTpl)}</li>`);
  return items.join("");
}

function _renderSpaceHtml(space) {
  let html = '<div class="card bento-card bento-card--wide"><h3>Espace disque</h3>';
  html += kpiGridHtml([
    { icon: "folder", label: "Espace total", value: _fmtBytes(space.total_bytes), color: "var(--accent)" },
    { icon: "film", label: "Taille moyenne", value: _fmtBytes(space.avg_bytes), color: "var(--info)" },
    { icon: "tool", label: "Recuperable", value: _fmtBytes(space.archivable_bytes), suffix: `(${space.archivable_count || 0} films)`, color: "var(--danger)" },
  ]);
  const byTier = space.by_tier || {};
  const total = space.total_bytes || 1;
  const _legacy = { Platinum: "Premium", Gold: "Bon", Silver: "Moyen", Bronze: null, Reject: "Mauvais" };
  let tierChart = '<div class="mt-4"><strong class="text-muted">Par qualite</strong><div class="space-bars mt-4">';
  for (const [tier, color] of [
    ["Platinum", "var(--success)"], ["Gold", "var(--accent)"], ["Silver", "var(--info)"],
    ["Bronze", "var(--warning)"], ["Reject", "var(--danger)"],
  ]) {
    const bytes = byTier[tier] || byTier[_legacy[tier]] || 0;
    const pct = Math.round(bytes / total * 100);
    tierChart += `<div class="space-bar-row"><span class="space-bar-label">${tier}</span><div class="space-bar-track"><div class="space-bar-fill" style="width:${pct}%;background:${color}"></div></div><span class="space-bar-value">${_fmtBytes(bytes)} (${pct}%)</span></div>`;
  }
  tierChart += '</div></div>';
  html += tierChart;
  const top = (space.top_wasteful || []).slice(0, 5);
  if (top.length > 0) {
    html += '<div class="mt-4"><strong class="text-muted">Films a archiver en priorite</strong>';
    html += '<div class="table-wrap mt-4"><table><thead><tr><th>Film</th><th>Taille</th><th>Score</th><th>Gaspillage</th></tr></thead><tbody>';
    for (const f of top) {
      html += `<tr><td>${escapeHtml(f.title || f.row_id)}</td><td>${_fmtBytes(f.size_bytes)}</td><td>${f.score}</td><td>${f.waste_score}</td></tr>`;
    }
    html += '</tbody></table></div></div>';
  }
  html += "</div>";
  return html;
}

function _renderSuggestionsHtml(suggestions, hs) {
  const hsColor = hs >= 80 ? "var(--success)" : hs >= 50 ? "var(--warning)" : "var(--danger)";
  let html = '<div class="card bento-card bento-card--third"><h3>Suggestions</h3>';
  html += `<p class="mt-4">Sante : <strong style="color:${hsColor}" data-stat="health-score">${hs}%</strong></p>`;
  if (suggestions.length === 0) {
    html += '<p class="text-muted mt-4">Bibliotheque en excellent etat.</p>';
  } else {
    html += '<div class="suggestions-list mt-4">';
    const prioColors = { high: "var(--danger)", medium: "var(--warning)", low: "var(--info)" };
    const prioLabels = { high: "Haute", medium: "Moyenne", low: "Info" };
    for (const s of suggestions) {
      const c = prioColors[s.priority] || "var(--text-muted)";
      html += `<div class="suggestion-card" style="border-left-color:${c}">`;
      html += `<span class="badge" style="background:${c};color:#fff">${escapeHtml(prioLabels[s.priority] || "")}</span> `;
      html += `${escapeHtml(s.message)}`;
      if (Array.isArray(s.details) && s.details.length) {
        html += `<div class="text-muted" style="font-size:var(--fs-xs);margin-top:4px">${s.details.map((d) => escapeHtml(d)).join(", ")}</div>`;
      }
      html += "</div>";
    }
    html += "</div>";
  }
  html += "</div>";
  return html;
}

function _renderTrendHtml(timelinePoints, ht) {
  let html = '<div class="card bento-card bento-card--third"><h3>Tendance sante</h3>';
  if (ht.message) {
    const tColor = ht.delta > 0 ? "var(--success)" : ht.delta < 0 ? "var(--danger)" : "var(--text-muted)";
    html += `<p class="mt-4" style="color:${tColor};font-weight:var(--fw-semi)">${escapeHtml(ht.message)}</p>`;
  }
  const svgW = 400, svgH = 100, pad = 20;
  const n = timelinePoints.length;
  const xs = timelinePoints.map((_, i) => pad + (i / Math.max(1, n - 1)) * (svgW - 2 * pad));
  const ys = timelinePoints.map((p) => pad + (1 - (p.health_score || 0) / 100) * (svgH - 2 * pad));
  const pts = xs.map((x, i) => `${x},${ys[i]}`).join(" ");
  const fillPts = `${xs[0]},${svgH - pad} ${pts} ${xs[n - 1]},${svgH - pad}`;
  html += `<svg class="health-chart mt-4" viewBox="0 0 ${svgW} ${svgH}" xmlns="http://www.w3.org/2000/svg">`;
  html += `<polygon points="${fillPts}" fill="var(--accent-soft)" opacity="0.5"/>`;
  html += `<polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>`;
  for (let i = 0; i < n; i++) {
    const p = timelinePoints[i];
    html += `<circle cx="${xs[i]}" cy="${ys[i]}" r="3" fill="var(--accent)"><title>${p.health_score}% — ${_fmtDate(p.start_ts)}</title></circle>`;
  }
  html += "</svg></div>";
  return html;
}

/* --- Patch dynamique (zero innerHTML sur valeurs critiques) --- */

function _setText(container, sel, txt) {
  const el = container.querySelector(sel);
  if (!el) return;
  const v = String(txt ?? "");
  if (el.textContent !== v) el.textContent = v;
}

function _patchDynamic(vm, container) {
  // Hero
  _setText(container, '[data-stat="hero-label"]', vm.heroLabel);
  _setText(container, '[data-stat="hero-sublabel"]', vm.heroSubLabel);
  _setText(container, '[data-stat="hero-value"]', vm.heroValue);
  _setText(container, '[data-stat="ring-label"]', vm.ringLabel);
  _setText(container, '[data-stat="ring-sublabel"]', vm.ringSublabel);
  const ring = container.querySelector('[data-stat="ring-fill"]');
  if (ring) {
    const cur = ring.getAttribute("stroke-dashoffset");
    if (cur !== vm.ringOffset) ring.setAttribute("stroke-dashoffset", vm.ringOffset);
  }
  // Hero meta : on remplace l'innerHTML d'un container localise (3 items, leger).
  const meta = container.querySelector('[data-stat="hero-meta"]');
  if (meta) {
    const next = _metaItemsInner(vm.heroMeta);
    if (meta.innerHTML !== next) meta.innerHTML = next;
  }
  // Workflow
  container.querySelectorAll("[data-workflow-step]").forEach((el) => {
    const idx = Number(el.dataset.workflowStep);
    el.classList.toggle("active", idx === vm.workflowActive);
  });
  // Hero card border color
  const hero = container.querySelector('[data-stat="hero-card"]');
  if (hero) {
    hero.style.borderLeftColor = vm.avgScoreColor;
    hero.classList.toggle("is-run-active", vm.isRunActive);
  }

  // Run progress (si la card existe)
  const pf = container.querySelector('[data-stat="progress-fill"]');
  if (pf) pf.style.width = `${vm.progressPct}%`;
  _setText(container, '[data-stat="progress-text"]', vm.progressText);

  // Tier distribution
  for (const k of ["platinum", "gold", "silver", "bronze", "reject"]) {
    _setText(container, `[data-tier-count="${k}"]`, String(vm.tiers[k].count));
    const bar = container.querySelector(`[data-tier-fill="${k}"]`);
    if (bar) bar.style.width = `${vm.tiers[k].pct}%`;
  }
  _setText(container, '[data-stat="tier-total"]', `${vm.tierTotal} films`);

  // Sante (liste leger, full inner replace)
  const hl = container.querySelector('[data-stat="health-list"]');
  if (hl) {
    const next = _renderHealthListHtml(vm.health);
    if (hl.innerHTML !== next) hl.innerHTML = next;
  }
}

/* --- V7-fusion Phase 1 : mount Apercu V2 ------------------ */

function _mountV2Overview(vm) {
  // KPIs (4 cards)
  const kpisEl = document.getElementById("v2-overview-kpis");
  if (kpisEl) _renderV2Kpis(kpisEl, vm.v2Kpis);
  // Insights (alertes proactives, masquables)
  const insightsEl = document.getElementById("v2-overview-insights");
  if (insightsEl) {
    _renderV2Insights(insightsEl, vm.v2Insights, (insight) => {
      // Si filter_hint fourni, naviguer vers /library avec query — pour Phase 1
      // on fait juste un nav vers /library, le filter sera ignore (TBD Phase Library).
      if (insight && insight.filter_hint) {
        window.location.hash = "#/library";
      }
    });
  }
  // Donut distribution V2
  const donutEl = document.getElementById("v2-overview-donut");
  if (donutEl && vm.v2Donut) _renderV2Donut(donutEl, vm.v2Donut);
  // Line trend 30 jours
  const lineEl = document.getElementById("v2-overview-line");
  if (lineEl && vm.v2Trend.length >= 2) _renderV2Line(lineEl, vm.v2Trend);
}

/* --- Chargement principal --------------------------------- */

async function _loadAll() {
  const container = $("statusContent");
  if (!container) return;

  // V2-D (a11y) : aria-busy sur le conteneur ARIA-live pour annoncer l'etat
  // "chargement en cours" aux lecteurs d'ecran.
  container.setAttribute("aria-busy", "true");

  if (!container.innerHTML.trim()) {
    container.innerHTML = `
      <div aria-busy="true" aria-label="Chargement de l'accueil">
        <div class="skeleton-grid">
          <div class="skeleton skeleton--kpi"></div>
          <div class="skeleton skeleton--kpi"></div>
          <div class="skeleton skeleton--kpi"></div>
        </div>
        <div class="skeleton skeleton--block"></div>
      </div>`;
  }

  try {
    const data = await _fetchAll();
    _activeRunId = data.health.active_run_id || null;

    // V7-fix : NE PAS ecraser body.dataset.theme a chaque tick — sinon un click
    // recent sur Luxe/Neon (en train de save_settings async) serait reverse au
    // tick suivant si la lecture serveur revient avant la sauvegarde.
    // Le theme est applique au boot (app.js) et lors d'un click (_applyTheme).
    // Ici on synchronise SEULEMENT au premier rendu (signature null).
    if (_shellSignature === null && data.settings.theme) {
      document.documentElement.setAttribute("data-theme", data.settings.theme);
      document.body.setAttribute("data-theme", data.settings.theme);
    }

    const vm = _buildVm(data);
    const sig = _shellSignatureOf(vm);

    if (sig === _shellSignature && container.querySelector('[data-stat="hero-card"]')) {
      // Structure inchangee : patch values uniquement (zero flicker).
      _patchDynamic(vm, container);
    } else {
      // Structure changee (ou premier rendu) : full re-render.
      _shellSignature = sig;
      _renderShell(vm, container);
      _hooksAttached = false;
      _hookActions(data.settings);
      if (vm.showRemoteAccess) _renderRemoteAccessBlock(data.settings);
      // V7-fusion Phase 1 : monter les composants v5 dans les sous-conteneurs
      // (les composants utilisent innerHTML eux-memes, donc on les appelle apres
      // le _renderShell qui a cree les <div id="v2-overview-*">).
      if (vm.hasV2Overview) _mountV2Overview(vm);
    }

    // Polling
    stopPolling("status-idle");
    stopPolling("status-run");
    if (_activeRunId) {
      _startRunPolling();
    } else {
      startPolling("status-idle", _pollIdleWithEventCheck, 15_000);
    }
  } catch (err) {
    container.innerHTML = `<p class="status-msg error">Erreur de chargement : ${escapeHtml(String(err))}</p>`;
    console.error("[status]", err);
  } finally {
    // V2-D (a11y) : retombe a "false" meme en cas d'erreur ou tick polling.
    container.setAttribute("aria-busy", "false");
  }
}

/* --- Polling idle (15s) avec detection evenements --------- */

async function _pollIdleWithEventCheck() {
  try {
    const health = await apiGet("/api/health");
    if (health?.data?.last_event_ts && checkEventChanged(health.data.last_event_ts)) {
      await _loadAll();
      return;
    }
    if (health?.data?.last_settings_ts && checkSettingsChanged(health.data.last_settings_ts)) {
      console.log("[sync] settings changed, reloading theme");
      // V2-B / H13 : settings ont change cote serveur (ex: edit desktop pywebview).
      // Invalide le cache memoire avant de relire pour eviter de servir une valeur stale
      // aux autres consommateurs (sidebar features, integrations, etc.).
      invalidateSettingsCache();
      try {
        const sRes = await apiPost("get_settings");
        if (sRes.data) {
          const s = sRes.data;
          document.body.dataset.theme = s.theme || "luxe";
          document.body.dataset.animation = s.animation_level || "moderate";
        }
      } catch { /* silencieux */ }
    }
    if (health?.data?.active_run_id) {
      _activeRunId = health.data.active_run_id;
      stopPolling("status-idle");
      _startRunPolling();
      return;
    }
  } catch { /* ignore, prochain tick reessaiera */ }
}

/* --- Polling run actif (3s) ------------------------------- */

function _startRunPolling() {
  // V7-fix : 3s. Avec partial-update (zero innerHTML sauf changement struct),
  // on peut etre reactif sans flicker.
  startPolling("status-run", async () => {
    try {
      await _loadAll();
      if (!_activeRunId) stopPolling("status-run");
    } catch { /* ignore */ }
  }, 3000);
}

/* --- Hooks actions ---------------------------------------- */

function _hookActions(settings) {
  if (_hooksAttached) return;
  _hooksAttached = true;

  document.querySelectorAll("[data-nav-route]").forEach((el) => {
    el.addEventListener("click", () => {
      const route = el.dataset.navRoute;
      if (route) window.location.hash = "#" + route;
    });
    el.style.cursor = "pointer";
  });

  const btnCancel = $("btnCancelRun");
  if (btnCancel && _activeRunId) {
    btnCancel.addEventListener("click", async () => {
      btnCancel.disabled = true;
      btnCancel.textContent = "Annulation…";
      try {
        const res = await apiPost("cancel_run", { run_id: _activeRunId });
        if (res?.data?.ok) {
          btnCancel.textContent = "Annule";
        } else {
          btnCancel.disabled = false;
          btnCancel.textContent = "Annuler";
        }
      } catch {
        btnCancel.disabled = false;
        btnCancel.textContent = "Annuler";
      }
    });
  }

  const btnInstall = $("btnDashAutoInstallProbe");
  if (btnInstall) {
    btnInstall.addEventListener("click", async () => {
      btnInstall.disabled = true;
      const installMsg = $("dashProbeInstallMsg");
      if (installMsg) installMsg.textContent = "Installation en cours...";
      try {
        const res = await apiPost("auto_install_probe_tools", {});
        if (res.data?.ok) {
          if (installMsg) { installMsg.textContent = "Outils installés !"; installMsg.className = "text-success"; }
          // Force shell rerender pour faire disparaitre le banner
          _shellSignature = null;
          setTimeout(_loadAll, 1000);
        } else {
          if (installMsg) { installMsg.textContent = "Échec : " + (res.data?.message || "Erreur"); installMsg.className = "text-danger"; }
          btnInstall.disabled = false;
        }
      } catch {
        if (installMsg) { installMsg.textContent = "Erreur réseau."; installMsg.className = "text-danger"; }
        btnInstall.disabled = false;
      }
    });
  }
}

/* --- Point d'entree --------------------------------------- */

export function initStatus() {
  _activeRunId = null;
  _shellSignature = null;
  _hooksAttached = false;
  _loadAll();
}

/* --- Bloc "Accès distant" -------------------------------- */

async function _renderRemoteAccessBlock(settings) {
  const host = document.getElementById("statusRemoteAccessBody");
  if (!host) return;
  const token = String(settings.rest_api_token || "");
  if (!token) {
    host.innerHTML = '<span class="text-warning">Aucune clé d\'accès configurée. Va dans Paramètres → API REST pour en générer une.</span>';
    return;
  }
  let qrSvg = ""; let dashUrl = "";
  try {
    const qr = await apiPost("get_dashboard_qr");
    if (qr?.data?.ok) { qrSvg = qr.data.svg || ""; dashUrl = qr.data.url || ""; }
  } catch { /* noop */ }
  if (!dashUrl) {
    try {
      const si = await apiPost("get_server_info");
      if (si?.data?.ok) dashUrl = si.data.dashboard_url || "";
    } catch { /* noop */ }
  }
  const tokenMasked = token.length > 8 ? token.slice(0, 4) + "••••" + token.slice(-4) : "••••";
  host.innerHTML = `
    <div style="display:flex;gap:var(--sp-4);align-items:flex-start;flex-wrap:wrap">
      ${qrSvg ? `<div style="min-width:140px">${qrSvg}</div>` : ""}
      <div style="flex:1;min-width:260px">
        <div style="margin-bottom:var(--sp-2)">
          <div class="text-muted" style="font-size:0.85em">URL</div>
          <div style="display:flex;gap:6px;align-items:center">
            <code id="statusRemoteUrl" style="flex:1;word-break:break-all;font-family:monospace;padding:6px 10px;background:var(--bg-raised);border-radius:var(--radius-sm);border:1px solid var(--border)">${escapeHtml(dashUrl || "http://<ton-ip>:8642/dashboard/")}</code>
            <button class="btn btn--compact" id="statusCopyUrl" title="Copier l'URL">📋</button>
          </div>
        </div>
        <div>
          <div class="text-muted" style="font-size:0.85em">Clé d'accès</div>
          <div style="display:flex;gap:6px;align-items:center">
            <code id="statusRemoteToken" data-full="${escapeHtml(token)}" data-shown="0" style="flex:1;font-family:monospace;padding:6px 10px;background:var(--bg-raised);border-radius:var(--radius-sm);border:1px solid var(--border)">${escapeHtml(tokenMasked)}</code>
            <button class="btn btn--compact" id="statusShowToken" title="Afficher / masquer">👁</button>
            <button class="btn btn--compact" id="statusCopyToken" title="Copier la clé">📋</button>
          </div>
        </div>
        <div id="statusRemoteMsg" class="text-muted" style="margin-top:var(--sp-2);font-size:0.85em"></div>
      </div>
    </div>`;
  const showBtn = document.getElementById("statusShowToken");
  const copyBtn = document.getElementById("statusCopyToken");
  const copyUrlBtn = document.getElementById("statusCopyUrl");
  const tokenEl = document.getElementById("statusRemoteToken");
  const msgEl = document.getElementById("statusRemoteMsg");
  if (showBtn && tokenEl) {
    showBtn.addEventListener("click", () => {
      const shown = tokenEl.dataset.shown === "1";
      tokenEl.dataset.shown = shown ? "0" : "1";
      tokenEl.textContent = shown ? tokenMasked : (tokenEl.dataset.full || "");
    });
  }
  if (copyBtn && tokenEl) {
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(tokenEl.dataset.full || "");
        if (msgEl) { msgEl.textContent = "✓ Clé d'accès copiée"; setTimeout(() => msgEl.textContent = "", 2500); }
      } catch {
        if (msgEl) msgEl.textContent = "Copie impossible (utilise 👁 et copie manuellement).";
      }
    });
  }
  if (copyUrlBtn) {
    copyUrlBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(dashUrl || "");
        if (msgEl) { msgEl.textContent = "✓ URL copiée"; setTimeout(() => msgEl.textContent = "", 2500); }
      } catch { /* noop */ }
    });
  }
}
