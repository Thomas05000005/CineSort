/* views/accueil.js — Phase 3.1 (spec 05-accueil.md) — Accueil refondu.
 *
 * Vue de synthese editoriale. 3 PRs incrementales :
 * - PR 3.1-A : Hero + Dernier run + Activite recente (sections 2 + 6).
 * - PR 3.1-B : CTA Scan + Sante biblio + Suggestions (sections 3 + 4 + 5).
 * - PR 3.1-C (cette version) : Environment bar (section 1) + Inspecteur
 *   droit content (rappels operateur + raccourcis) + etat "scan en cours".
 *
 * Toutes les sections de la spec 05 sont desormais couvertes.
 *
 * Source backend : get_dashboard("latest") + get_global_stats() + settings.
 * Route cible : /accueil (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { navigateTo } from "../core/router.js";
import * as rightPanel from "../components/right-panel.js";

/* --- Format dates relatives -------------------------------------------- */

const _ONE_DAY_MS = 86400000;

/** "Aujourd'hui 15:11", "Hier 13:13", "Il y a 3 jours", "12/05 14:30" sinon. */
export function formatRelativeTime(isoOrEpoch) {
  if (!isoOrEpoch) return "—";
  const d = isoOrEpoch instanceof Date ? isoOrEpoch : new Date(isoOrEpoch);
  if (Number.isNaN(d.getTime())) return "—";
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dayOfTarget = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((today.getTime() - dayOfTarget.getTime()) / _ONE_DAY_MS);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  if (diffDays === 0) return `Aujourd'hui ${hh}:${mm}`;
  if (diffDays === 1) return `Hier ${hh}:${mm}`;
  if (diffDays > 1 && diffDays < 7) return `Il y a ${diffDays} jours`;
  const dd = String(d.getDate()).padStart(2, "0");
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  return `${dd}/${mo} ${hh}:${mm}`;
}

/* --- Resume dynamique du Hero (spec 05 §2 Hero) ------------------------ */

/** Determine la phrase de resume selon l'etat agrege.
 *  Retourne { greeting, summary } pour le hero editorial.
 */
export function computeHeroSummary(state) {
  const hasActiveRun = !!state.active_run_id;
  const hasAnyRun = !!state.latest_run;
  const errorCritical = !!state.error_critical;
  const alertCount = Number(state.alert_count || 0);
  const alertSeverity = String(state.alert_severity || "info");

  if (errorCritical) {
    return { summary: "Problème : la base de données n'est pas accessible." };
  }
  if (hasActiveRun) {
    const total = state.active_total || 0;
    const eta = state.active_eta_min;
    const etaTxt = eta != null ? ` ~${eta} min restant.` : "";
    return { summary: `Scan en cours sur ${total} films.${etaTxt}` };
  }
  if (!hasAnyRun) {
    return { summary: "Bienvenue. Lance ton premier scan pour commencer." };
  }
  if (alertCount === 0) {
    return { summary: "Ta bibliothèque va bien." };
  }
  if (alertCount <= 3 && alertSeverity !== "danger") {
    return { summary: "Ta bibliothèque va bien, quelques points à voir." };
  }
  return { summary: "Ta bibliothèque demande ton attention." };
}

/* --- HTML rendering ---------------------------------------------------- */

function _renderSkeleton() {
  return `
    <section class="accueil-view accueil-view--loading" aria-busy="true">
      <div class="accueil-hero">
        <div class="v5-skeleton accueil-hero-greeting-skel"></div>
        <div class="v5-skeleton accueil-hero-summary-skel"></div>
      </div>
      <div class="accueil-section v5-skeleton accueil-section-skel"></div>
      <div class="accueil-section v5-skeleton accueil-section-skel"></div>
    </section>
  `;
}

function _renderError(message) {
  return `
    <section class="accueil-view accueil-view--error" role="alert">
      <h2 class="accueil-error-title">L'accueil n'a pas pu se charger.</h2>
      <p class="accueil-error-message">${escapeHtml(message || "Erreur inconnue")}</p>
      <button type="button" class="v5-btn v5-btn--primary" data-accueil-retry>Réessayer</button>
    </section>
  `;
}

function _renderHero(heroState) {
  const { summary } = computeHeroSummary(heroState);
  return `
    <header class="accueil-hero">
      <h1 class="accueil-hero-greeting">Bonjour Thomas</h1>
      <p class="accueil-hero-summary">${escapeHtml(summary)}</p>
    </header>
  `;
}

function _renderLastRunCard(latestRun, kpis) {
  if (!latestRun || !latestRun.run_id) {
    return `
      <section class="accueil-section accueil-last-run accueil-last-run--empty" aria-label="Dernier run">
        <h2 class="accueil-section-title">Dernier run</h2>
        <p class="accueil-empty-msg">Aucun run encore. Lance ton premier scan pour commencer.</p>
        <div class="accueil-actions">
          <button type="button" class="v5-btn v5-btn--primary" data-accueil-action="start-scan">▶ Démarrer un scan</button>
        </div>
      </section>
    `;
  }
  // Source backend get_dashboard : runs_history[i] expose started_ts (float epoch),
  // total_rows, applied_rows, errors_count, anomalies_count. Pas de avg_score
  // par run dans runs_history -> on lit le score moyen du run actif via payload.kpis.
  const startedTs = latestRun.started_ts || latestRun.started_at;
  const startedDate = typeof startedTs === "number" ? new Date(startedTs * 1000) : startedTs;
  const date = formatRelativeTime(startedDate);
  const total = latestRun.total_rows != null ? Number(latestRun.total_rows) : null;
  const avgScore = kpis && kpis.score_avg != null ? Number(kpis.score_avg) : (latestRun.avg_score_v2 != null ? Number(latestRun.avg_score_v2) : null);
  const avgConfidence = latestRun.avg_confidence_pct;
  const scoreTxt = avgScore != null && avgScore > 0 ? `${Math.round(avgScore)}/100` : "— (pas calculé)";
  const confTxt = avgConfidence != null ? `${Math.round(avgConfidence)}%` : "—";
  const totalTxt = total != null ? `${total} films analysés` : "— films";
  const showResume = String(latestRun.status || "").toUpperCase() === "AWAITING_VALIDATION";
  return `
    <section class="accueil-section accueil-last-run" aria-labelledby="accueil-last-run-title">
      <h2 id="accueil-last-run-title" class="accueil-section-title">Dernier run</h2>
      <div class="accueil-last-run-meta">
        <span class="accueil-last-run-id">${escapeHtml(latestRun.run_id)}</span>
        <span class="accueil-last-run-sep">·</span>
        <time class="accueil-last-run-date" datetime="${escapeHtml(String(startedTs || ""))}">${escapeHtml(date)}</time>
      </div>
      <dl class="accueil-last-run-stats">
        <div><dt>Films</dt><dd>${escapeHtml(totalTxt)}</dd></div>
        <div><dt>Score moyen</dt><dd>${escapeHtml(scoreTxt)}</dd></div>
        <div><dt>Confiance moyenne</dt><dd>${escapeHtml(confTxt)}</dd></div>
      </dl>
      <div class="accueil-actions">
        ${showResume ? '<button type="button" class="v5-btn v5-btn--primary" data-accueil-action="resume-validation" data-run-id="' + escapeHtml(latestRun.run_id) + '">▶ Reprendre la validation</button>' : ""}
        <button type="button" class="v5-btn v5-btn--secondary" data-accueil-action="view-run-detail" data-run-id="${escapeHtml(latestRun.run_id)}">📊 Voir le détail</button>
      </div>
    </section>
  `;
}

/* Phase 3.1-C : Environment bar (section 1 spec 05).
 * Slim 32px, affiche les roots actifs (max 3) + 5 pastilles integrations.
 * Une integration peut etre : configuree+OK ☑, non configuree ☐, ou
 * configuree mais hors ligne ⚠.
 */
const _INTEGRATIONS = [
  { key: "tmdb", label: "TMDb", settingKey: "tmdb_api_key" },
  { key: "jellyfin", label: "Jellyfin", settingKey: "jellyfin_enabled" },
  { key: "plex", label: "Plex", settingKey: "plex_enabled" },
  { key: "radarr", label: "Radarr", settingKey: "radarr_enabled" },
  { key: "omdb", label: "OMDb", settingKey: "omdb_enabled" },
];

function _integrationState(integration, settings) {
  const settingsObj = settings || {};
  const val = settingsObj[integration.settingKey];
  const configured = (typeof val === "string" && val.trim() !== "") || val === true;
  // Pour la PR 3.1-C, on ne ping pas les services : on indique juste configure
  // ou non. La detection hors-ligne (etat "warn") sera Phase 3.1-D ou plus tard.
  return configured ? "ok" : "off";
}

function _renderEnvironmentBar(roots, settings) {
  const rootsList = Array.isArray(roots) ? roots : [];
  const rootsTxt = rootsList.length === 0
    ? "<em class=\"accueil-env-empty\">Aucun root configuré</em>"
    : rootsList.slice(0, 2).map((r) => escapeHtml(String(r))).join(", ") + (rootsList.length > 2 ? `, <span class="accueil-env-more">+${rootsList.length - 2}</span>` : "");
  const pastilles = _INTEGRATIONS.map((it) => {
    const state = _integrationState(it, settings);
    const symbol = state === "ok" ? "☑" : "☐";
    const stateClass = state === "ok" ? "is-ok" : "is-off";
    const title = state === "ok" ? `${it.label} configuré` : `${it.label} non configuré — clique pour le configurer`;
    return `<button type="button" class="accueil-env-pill ${stateClass}" data-integration="${escapeHtml(it.key)}" title="${escapeHtml(title)}">
      <span class="accueil-env-pill-sym" aria-hidden="true">${symbol}</span>${escapeHtml(it.label)}
    </button>`;
  }).join("");
  return `
    <div class="accueil-env-bar" role="status" aria-label="Environment et integrations">
      <span class="accueil-env-roots" aria-label="Dossiers racines actifs">📂 ${rootsTxt}</span>
      <span class="accueil-env-pills">${pastilles}</span>
    </div>
  `;
}

/* Phase 3.1-C : Etat "scan en cours" — section CTA Scan transformee en
 * compteur de progression. Le polling de mise a jour sera dans initAccueil.
 */
function _renderScanInProgress(progress) {
  const total = progress.total != null ? Number(progress.total) : 0;
  const current = progress.current != null ? Number(progress.current) : 0;
  const phase = String(progress.phase || "");
  const phaseLabel = progress.phase_label || phase || "Scan en cours";
  const etaMin = progress.eta_min;
  const pct = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
  const etaTxt = etaMin != null ? `~${etaMin} min restant` : "";
  return `
    <section class="accueil-section accueil-cta-scan accueil-cta-scan--running" aria-labelledby="accueil-cta-title">
      <h2 id="accueil-cta-title" class="accueil-cta-scan-title">🔄 Scan en cours sur ${escapeHtml(String(total))} films</h2>
      <p class="accueil-cta-scan-phase">${escapeHtml(phaseLabel)} (${escapeHtml(String(current))}/${escapeHtml(String(total))})</p>
      <div class="accueil-cta-scan-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
        <span class="accueil-cta-scan-fill" style="width: ${pct}%"></span>
      </div>
      ${etaTxt ? `<p class="accueil-cta-scan-eta">${escapeHtml(etaTxt)}</p>` : ""}
      <div class="accueil-actions">
        <button type="button" class="v5-btn v5-btn--secondary" data-accueil-action="open-traitement">→ Voir le détail</button>
      </div>
    </section>
  `;
}

function _renderCtaScan(roots, scanProgress) {
  if (scanProgress && scanProgress.active) {
    return _renderScanInProgress(scanProgress);
  }
  const rootsList = Array.isArray(roots) ? roots : [];
  const rootsLabel = rootsList.length > 0
    ? rootsList.slice(0, 3).map((r) => escapeHtml(String(r))).join(" + ")
    : "<em class=\"text-muted\">Aucun root configuré. Va dans Paramètres > Sources.</em>";
  return `
    <section class="accueil-section accueil-cta-scan" aria-labelledby="accueil-cta-title">
      <div class="accueil-cta-scan-content">
        <h2 id="accueil-cta-title" class="accueil-cta-scan-title">🚀 Lancer un nouveau scan</h2>
        <p class="accueil-cta-scan-targets">Sur ${rootsLabel}</p>
      </div>
      <div class="accueil-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-accueil-action="start-scan">▶ Démarrer</button>
        <button type="button" class="v5-btn v5-btn--secondary" data-accueil-action="open-scan-options">⚙ Options…</button>
      </div>
    </section>
  `;
}

const _TIER_ORDER = ["platinum", "gold", "silver", "bronze", "reject"];
const _TIER_LABELS = {
  platinum: "Platinum",
  gold: "Gold",
  silver: "Silver",
  bronze: "Bronze",
  reject: "Reject",
};

function _renderTierBar(tier, count, total) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  // Spec : barre proportionnelle. On garde la largeur en % CSS.
  return `
    <div class="accueil-health-row" data-tier="${escapeHtml(tier)}">
      <span class="accueil-health-label">${escapeHtml(_TIER_LABELS[tier] || tier)}</span>
      <div class="accueil-health-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="${escapeHtml(_TIER_LABELS[tier])} : ${count} films (${pct}%)">
        <span class="accueil-health-fill accueil-health-fill--${escapeHtml(tier)}" style="width: ${pct}%"></span>
      </div>
      <span class="accueil-health-count">${escapeHtml(String(count))}</span>
      <span class="accueil-health-pct">${pct}%</span>
    </div>
  `;
}

function _normalizeTierDist(rawDist) {
  // Le backend peut renvoyer des keys Capitalisees (legacy : "Bronze", "Gold", ...)
  // ou lowercase (v2_tier_distribution.counts). On normalise tout en lowercase.
  const out = {};
  for (const [k, v] of Object.entries(rawDist || {})) {
    out[String(k).toLowerCase()] = Number(v) || 0;
  }
  return out;
}

function _renderHealth(stats) {
  // Priorite a v2_tier_distribution.counts (lowercase garantis, structure v7.6.0).
  // Fallback sur tier_distribution legacy (keys potentiellement Capitalisees).
  let dist = {};
  if (stats && stats.v2_tier_distribution && stats.v2_tier_distribution.counts) {
    dist = _normalizeTierDist(stats.v2_tier_distribution.counts);
  } else if (stats && stats.tier_distribution) {
    dist = _normalizeTierDist(stats.tier_distribution);
  }
  // Total des films effectivement classes (somme des 5 tiers, sans "unknown").
  const sumTiers = _TIER_ORDER.reduce((sum, t) => sum + (Number(dist[t]) || 0), 0);
  const total = sumTiers;
  if (total === 0) {
    return `
      <section class="accueil-section accueil-health accueil-health--empty" aria-labelledby="accueil-health-title">
        <h2 id="accueil-health-title" class="accueil-section-title">Santé bibliothèque</h2>
        <p class="accueil-empty-msg">Lance ton premier scan pour voir la distribution qualité.</p>
      </section>
    `;
  }
  const rows = _TIER_ORDER.map((t) => _renderTierBar(t, Number(dist[t]) || 0, total)).join("");
  return `
    <section class="accueil-section accueil-health" aria-labelledby="accueil-health-title">
      <h2 id="accueil-health-title" class="accueil-section-title">Santé bibliothèque <span class="accueil-health-total">(${escapeHtml(String(total))} films classés)</span></h2>
      <div class="accueil-health-bars">${rows}</div>
      <div class="accueil-actions">
        <button type="button" class="v5-btn v5-btn--ghost" data-accueil-action="view-qualite">→ Audit qualité complet</button>
      </div>
    </section>
  `;
}

const _INSIGHT_ROUTE_BY_TYPE = {
  duplicates_probable: "/bibliotheque?filter=duplicates",
  films_not_identified: "/bibliotheque?filter=not_identified",
  films_low_confidence: "/bibliotheque?filter=low_confidence",
  subs_missing_fr: "/bibliotheque?filter=subs_missing_fr",
  omdb_disagreements: "/bibliotheque?filter=omdb_disagree",
  quality_reject: "/qualite",
  health_low: "/qualite",
  sagas_incomplete: "/bibliotheque?filter=sagas_incomplete",
};

function _routeFromInsight(insight) {
  if (!insight) return "/accueil";
  if (insight.action_url && typeof insight.action_url === "string") {
    // L'URL backend peut etre un hash (#doublons) — on normalise.
    return insight.action_url.replace(/^#/, "/").replace(/^\/?/, "/");
  }
  return _INSIGHT_ROUTE_BY_TYPE[insight.type || insight.code] || "/bibliotheque";
}

function _renderSuggestions(stats) {
  const insights = Array.isArray(stats && stats.insights) ? stats.insights : [];
  if (insights.length === 0) {
    return `
      <section class="accueil-section accueil-suggestions accueil-suggestions--empty" aria-labelledby="accueil-suggestions-title">
        <h2 id="accueil-suggestions-title" class="accueil-section-title">Points à traiter</h2>
        <p class="accueil-empty-msg">✅ Aucun point à traiter. Tout va bien.</p>
      </section>
    `;
  }
  const items = insights.slice(0, 5).map((it) => {
    const sev = String(it.severity || "info");
    const sevClass = sev === "danger" ? "is-danger" : sev === "warning" ? "is-warning" : "is-info";
    const sevDot = sev === "danger" ? "🔴" : sev === "warning" ? "🟡" : "🔵";
    const label = String(it.label || it.title || "Point à traiter");
    const count = it.count != null ? `${Number(it.count)} ` : "";
    const route = _routeFromInsight(it);
    const filterHint = it.filter_hint ? `<span class="accueil-suggestion-hint">${escapeHtml(String(it.filter_hint))}</span>` : "";
    return `
      <li class="accueil-suggestion-row ${sevClass}" data-target-route="${escapeHtml(route)}">
        <span class="accueil-suggestion-dot" aria-hidden="true">${sevDot}</span>
        <span class="accueil-suggestion-text"><strong>${escapeHtml(count + label)}</strong>${filterHint}</span>
        <button type="button" class="v5-btn v5-btn--ghost accueil-suggestion-action" data-accueil-action="open-insight" data-target-route="${escapeHtml(route)}">→</button>
      </li>
    `;
  }).join("");
  return `
    <section class="accueil-section accueil-suggestions" aria-labelledby="accueil-suggestions-title">
      <h2 id="accueil-suggestions-title" class="accueil-section-title">⚠️ ${insights.length} Points à traiter</h2>
      <ul class="accueil-suggestion-list">${items}</ul>
    </section>
  `;
}

function _renderRecentActivity(runs) {
  const list = Array.isArray(runs) ? runs.slice(0, 3) : [];
  if (list.length === 0) {
    return `
      <section class="accueil-section accueil-activity accueil-activity--empty" aria-labelledby="accueil-activity-title">
        <h2 id="accueil-activity-title" class="accueil-section-title">Activité récente</h2>
        <p class="accueil-empty-msg">Aucune activité pour l'instant.</p>
      </section>
    `;
  }
  const rows = list.map((r) => {
    // get_dashboard fournit errors_count + applied_rows mais pas status.
    // On derive le statut : ERROR si errors_count > 0, PARTIAL si applied < total, DONE sinon.
    const errors = Number(r.errors_count || 0);
    const applied = Number(r.applied_rows || 0);
    const total = Number(r.total_rows || 0);
    const derivedStatus = errors > 0 ? "ERROR" : (applied < total && total > 0 ? "PARTIAL" : "DONE");
    const status = String(r.status || derivedStatus).toUpperCase();
    const statusClass = status === "ERROR" ? "is-error" : status === "PARTIAL" ? "is-partial" : "is-done";
    // started_ts est un epoch float (secondes) ; started_at est un fallback ISO si dispo.
    const tsSrc = r.started_ts != null ? new Date(Number(r.started_ts) * 1000) : r.started_at;
    const date = formatRelativeTime(tsSrc);
    const totalLabel = total > 0 ? `${total} films` : "—";
    return `
      <li class="accueil-activity-row clickable-row" tabindex="0" data-run-id="${escapeHtml(r.run_id)}">
        <time class="accueil-activity-date">${escapeHtml(date)}</time>
        <span class="accueil-activity-id">${escapeHtml(r.run_id)}</span>
        <span class="accueil-activity-total">${escapeHtml(totalLabel)}</span>
        <span class="accueil-activity-status ${statusClass}">● ${escapeHtml(status || "—")}</span>
      </li>
    `;
  }).join("");
  return `
    <section class="accueil-section accueil-activity" aria-labelledby="accueil-activity-title">
      <h2 id="accueil-activity-title" class="accueil-section-title">Activité récente</h2>
      <ul class="accueil-activity-list">${rows}</ul>
      <div class="accueil-actions">
        <button type="button" class="v5-btn v5-btn--ghost" data-accueil-action="view-history">→ Voir l'historique complet</button>
      </div>
    </section>
  `;
}

function _extractScanProgress(payload) {
  // Le backend get_dashboard retourne active_run_id si un scan est en cours.
  // Pour cette PR 3.1-C, on se contente d'un check basique. Le polling
  // complet (re-fetch /run/get_status toutes les 2s) viendra Phase 3.1-D.
  if (!payload) return { active: false };
  const activeRunId = payload.active_run_id || (payload.run_info && payload.run_info.status === "running" ? payload.run_info.run_id : null);
  if (!activeRunId) return { active: false };
  const ri = payload.run_info || {};
  return {
    active: true,
    run_id: activeRunId,
    total: ri.total_rows || ri.total || 0,
    current: ri.current_index || 0,
    phase: ri.phase || "running",
    phase_label: ri.phase_label || null,
    eta_min: ri.eta_min != null ? ri.eta_min : null,
  };
}

function _resolveLatestRun(payload) {
  // get_dashboard ne retourne PAS un champ run_info dedie. Le dernier run est
  // identifie par payload.run_id (id du run resolu en mode "latest") et ses
  // donnees se trouvent dans payload.runs_history[]. On cherche d'abord par
  // run_id ; fallback sur runs_history[0].
  const runs = Array.isArray(payload && payload.runs_history) ? payload.runs_history : [];
  if (payload && payload.run_id) {
    const match = runs.find((r) => r && r.run_id === payload.run_id);
    if (match) return match;
  }
  return runs.length > 0 ? runs[0] : null;
}

function _renderAccueil(payload, stats, settings) {
  const latestRun = _resolveLatestRun(payload);
  const recentRuns = Array.isArray(payload && payload.runs_history) ? payload.runs_history : [];
  const insights = Array.isArray(stats && stats.insights) ? stats.insights : [];
  const alertCount = insights.length;
  const alertSeverity = insights.some((i) => i.severity === "danger") ? "danger" : "info";
  const roots = settings && Array.isArray(settings.roots) ? settings.roots : [];
  const scanProgress = _extractScanProgress(payload);
  const heroState = {
    active_run_id: scanProgress.active ? scanProgress.run_id : null,
    active_total: scanProgress.total,
    active_eta_min: scanProgress.eta_min,
    latest_run: latestRun,
    error_critical: payload.error_critical || false,
    alert_count: alertCount,
    alert_severity: alertSeverity,
  };
  return `
    <section class="accueil-view">
      ${_renderEnvironmentBar(roots, settings)}
      ${_renderHero(heroState)}
      ${_renderLastRunCard(latestRun, payload && payload.kpis)}
      ${_renderCtaScan(roots, scanProgress)}
      ${_renderSuggestions(stats || {})}
      ${_renderHealth(stats || {})}
      ${_renderRecentActivity(recentRuns)}
    </section>
  `;
}

/* Phase 3.1-C : alimente l'Inspecteur droit avec 3 sections : Contexte,
 * Rappels operateur, Raccourcis (spec 05 §3 Inspecteur droit sur Accueil).
 */
function _buildInspectorSections(payload, stats, settings) {
  const total = (stats && stats.summary && stats.summary.total_films)
    || (stats && stats.v2_tier_distribution && stats.v2_tier_distribution.total)
    || (stats && stats.total_scored)
    || null;
  const activeRun = payload && payload.active_run_id;
  const latestRun = _resolveLatestRun(payload);
  const lastScanTs = latestRun && latestRun.started_ts != null
    ? new Date(Number(latestRun.started_ts) * 1000)
    : (latestRun && latestRun.started_at) || null;
  const lastScanLabel = lastScanTs ? formatRelativeTime(lastScanTs) : "—";
  const omdbEnabled = settings && (settings.omdb_enabled === true || (typeof settings.omdb_api_key === "string" && settings.omdb_api_key.trim() !== ""));
  const insights = Array.isArray(stats && stats.insights) ? stats.insights : [];
  const reminders = [];
  if (latestRun && String(latestRun.status || "").toUpperCase() === "AWAITING_VALIDATION") {
    reminders.push("Pense à valider la run de ce matin");
  }
  if (!omdbEnabled) {
    reminders.push("OMDb non configuré — pas de validation croisée sur les matchs douteux");
  }
  insights.slice(0, 3).forEach((i) => {
    if (i.label && i.severity === "warning") reminders.push(`${i.count || ""} ${i.label}`.trim());
  });
  return [
    {
      title: "Contexte",
      html: `
        <dl class="accueil-inspector-dl">
          <div><dt>Bibliothèque</dt><dd>${escapeHtml(total != null ? String(total) : "—")}</dd></div>
          <div><dt>Run actif</dt><dd>${escapeHtml(activeRun || "aucun")}</dd></div>
          <div><dt>Dernier scan</dt><dd>${escapeHtml(lastScanLabel)}</dd></div>
        </dl>
      `,
    },
    {
      title: "Rappels opérateur",
      html: reminders.length === 0
        ? `<p class="accueil-empty-msg">Rien à signaler.</p>`
        : `<ul class="accueil-inspector-list">${reminders.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`,
    },
    {
      title: "Raccourcis",
      html: `
        <dl class="accueil-inspector-shortcuts">
          <div><dt><kbd>Ctrl</kbd>+<kbd>S</kbd></dt><dd>Nouveau scan</dd></div>
          <div><dt><kbd>Ctrl</kbd>+<kbd>K</kbd></dt><dd>Recherche / palette</dd></div>
          <div><dt><kbd>Ctrl</kbd>+<kbd>,</kbd></dt><dd>Paramètres</dd></div>
          <div><dt><kbd>?</kbd></dt><dd>Aide</dd></div>
        </dl>
      `,
    },
  ];
}

/* --- Event binding ----------------------------------------------------- */

function _bindEvents(container) {
  // Boutons d'action principaux (start scan / resume / view detail / view history /
  // open-insight / view-qualite / open-scan-options)
  container.querySelectorAll("[data-accueil-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      const action = btn.dataset.accueilAction;
      const runId = btn.dataset.runId;
      const targetRoute = btn.dataset.targetRoute;
      switch (action) {
        case "start-scan":
          navigateTo("/traitement");
          break;
        case "resume-validation":
          if (runId) navigateTo(`/traitement#run-${encodeURIComponent(runId)}`);
          else navigateTo("/traitement");
          break;
        case "view-run-detail":
          if (runId) navigateTo(`/historique#run-${encodeURIComponent(runId)}`);
          else navigateTo("/historique");
          break;
        case "view-history":
          navigateTo("/historique");
          break;
        case "view-qualite":
          navigateTo("/qualite");
          break;
        case "open-insight":
          if (targetRoute) navigateTo(targetRoute);
          break;
        case "open-scan-options":
          // Spec : ouvrira un drawer (Phase 3.3 ou plus tard). En attendant : Traitement.
          navigateTo("/traitement");
          break;
        case "open-traitement":
          navigateTo("/traitement");
          break;
        default:
          break;
      }
      ev.preventDefault();
    });
  });

  // Phase 3.1-C : pastilles integrations cliquables -> Parametres > Integrations.
  container.querySelectorAll("[data-integration]").forEach((pill) => {
    pill.addEventListener("click", (ev) => {
      const key = pill.dataset.integration || "";
      // Section "integrations" dans la sub-sidebar Parametres (Phase 3.1-D).
      // En attendant : fragment pour pre-selection.
      navigateTo(`/parametres#integrations-${encodeURIComponent(key)}`);
      ev.preventDefault();
    });
  });

  // Lignes d'activite cliquables -> historique > detail run
  container.querySelectorAll(".accueil-activity-row").forEach((row) => {
    const open = () => {
      const runId = row.dataset.runId;
      if (runId) navigateTo(`/historique#run-${encodeURIComponent(runId)}`);
    };
    row.addEventListener("click", open);
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
  });

  // Retry button (cas erreur)
  const retryBtn = container.querySelector("[data-accueil-retry]");
  if (retryBtn) {
    retryBtn.addEventListener("click", () => initAccueil(container));
  }
}

/* --- Entrypoint -------------------------------------------------------- */

export async function initAccueil(container) {
  if (!container) return;
  container.innerHTML = _renderSkeleton();
  const signal = typeof getNavSignal === "function" ? getNavSignal() : undefined;

  // Phase 3.1-B : on charge en parallele les 3 sources (dashboard latest +
  // global stats + settings) pour avoir les donnees des 5 sections en un boot.
  let dashRes = null;
  let statsRes = null;
  let settingsRes = null;
  try {
    [dashRes, statsRes, settingsRes] = await Promise.all([
      apiPost("get_dashboard", { run_id: "latest" }, { signal }),
      apiPost("get_global_stats", {}, { signal }).catch(() => null),
      apiPost("settings/get_settings", {}, { signal }).catch(() => null),
    ]);
  } catch (err) {
    if (err && err.name === "AbortError") return;
    container.innerHTML = _renderError(err ? String(err.message || err) : "Erreur réseau");
    _bindEvents(container);
    return;
  }

  if (!dashRes || dashRes.ok === false) {
    const msg = (dashRes && (dashRes.message || dashRes.error)) || "Erreur de chargement du dashboard.";
    container.innerHTML = _renderError(msg);
    _bindEvents(container);
    return;
  }

  const dashboardData = dashRes.data || dashRes;
  const stats = (statsRes && statsRes.ok !== false) ? (statsRes.data || statsRes) : {};
  const settings = (settingsRes && settingsRes.ok !== false) ? (settingsRes.data || settingsRes) : {};

  container.innerHTML = _renderAccueil(dashboardData, stats, settings);
  _bindEvents(container);

  // Phase 3.1-C : alimente l'Inspecteur droit avec contexte + rappels + raccourcis.
  try {
    rightPanel.setSections(_buildInspectorSections(dashboardData, stats, settings));
  } catch (err) {
    // Defensive : l'inspecteur n'est pas critique pour l'Accueil.
    console.warn("[accueil] setSections inspector failed:", err);
  }
}
