/* views/accueil.js — Phase 3.1 (spec 05-accueil.md) — Accueil refondu.
 *
 * Vue de synthese editoriale. PR 3.1-A : Hero + Dernier run + Activite.
 * PR 3.1-B (ce fichier) : ajoute CTA Scan + Sante biblio + Suggestions.
 *
 * Sections actuellement couvertes :
 * - Section 2 : Hero ("Bonjour Thomas") + resume dynamique + carte Dernier run
 * - Section 3 : CTA "Lancer un nouveau scan" (sur les roots configures)
 * - Section 4 : Points a traiter (suggestions issues de get_global_stats.insights)
 * - Section 5 : Sante bibliotheque (bargraph 5 tiers)
 * - Section 6 : Activite recente (3 derniers runs)
 *
 * Restent en PR 3.1-C : Section 1 (Environment bar) + Inspecteur droit
 * + etats dynamiques avances (premier lancement, run actif polling, etc).
 *
 * Source backend : get_dashboard("latest") + get_global_stats() (existants).
 * Route cible : /accueil (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { navigateTo } from "../core/router.js";

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

function _renderLastRunCard(latestRun) {
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
  const date = formatRelativeTime(latestRun.started_at);
  const total = latestRun.total_rows != null ? Number(latestRun.total_rows) : null;
  const avgScore = latestRun.avg_score_v2;
  const avgConfidence = latestRun.avg_confidence_pct;
  const scoreTxt = avgScore != null ? `${Math.round(avgScore)}/100` : "— (pas calculé)";
  const confTxt = avgConfidence != null ? `${Math.round(avgConfidence)}%` : "—";
  const totalTxt = total != null ? `${total} films analysés` : "— films";
  const showResume = String(latestRun.status || "").toUpperCase() === "AWAITING_VALIDATION";
  return `
    <section class="accueil-section accueil-last-run" aria-labelledby="accueil-last-run-title">
      <h2 id="accueil-last-run-title" class="accueil-section-title">Dernier run</h2>
      <div class="accueil-last-run-meta">
        <span class="accueil-last-run-id">${escapeHtml(latestRun.run_id)}</span>
        <span class="accueil-last-run-sep">·</span>
        <time class="accueil-last-run-date" datetime="${escapeHtml(String(latestRun.started_at || ""))}">${escapeHtml(date)}</time>
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

function _renderCtaScan(roots) {
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

function _renderHealth(stats) {
  const dist = stats && stats.tier_distribution ? stats.tier_distribution : {};
  const total = Number(stats && stats.total_scored) || _TIER_ORDER.reduce((sum, t) => sum + (Number(dist[t]) || 0), 0);
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
    const status = String(r.status || "").toUpperCase();
    const statusClass = status === "ERROR" ? "is-error" : status === "PARTIAL" ? "is-partial" : "is-done";
    const date = formatRelativeTime(r.started_at);
    const total = r.total_rows != null ? `${Number(r.total_rows)} films` : "—";
    return `
      <li class="accueil-activity-row clickable-row" tabindex="0" data-run-id="${escapeHtml(r.run_id)}">
        <time class="accueil-activity-date">${escapeHtml(date)}</time>
        <span class="accueil-activity-id">${escapeHtml(r.run_id)}</span>
        <span class="accueil-activity-total">${escapeHtml(total)}</span>
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

function _renderAccueil(payload, stats, settings) {
  const latestRun = payload.run_info || payload.latest_run || null;
  const recentRuns = Array.isArray(payload.runs_history) ? payload.runs_history : [];
  const insights = Array.isArray(stats && stats.insights) ? stats.insights : [];
  const alertCount = insights.length;
  const alertSeverity = insights.some((i) => i.severity === "danger") ? "danger" : "info";
  const roots = settings && Array.isArray(settings.roots) ? settings.roots : [];
  const heroState = {
    active_run_id: payload.active_run_id || null,
    latest_run: latestRun,
    error_critical: payload.error_critical || false,
    alert_count: alertCount,
    alert_severity: alertSeverity,
  };
  return `
    <section class="accueil-view">
      ${_renderHero(heroState)}
      ${_renderLastRunCard(latestRun)}
      ${_renderCtaScan(roots)}
      ${_renderSuggestions(stats || {})}
      ${_renderHealth(stats || {})}
      ${_renderRecentActivity(recentRuns)}
    </section>
  `;
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
          // Spec 3.1-C : ouvrira un drawer. En attendant : naviguer vers Traitement.
          navigateTo("/traitement");
          break;
        default:
          break;
      }
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
}
