/* views/accueil.js — Phase 3.1 (spec 05-accueil.md) — Accueil refondu.
 *
 * Vue de synthese editoriale : Hero + Card Dernier run + Activite recente.
 * Pour la PR initiale (3.1-A), on couvre les sections 2 et 6 de la spec :
 * - Section 2 : Hero ("Bonjour Thomas") + resume dynamique selon etat + carte Dernier run
 * - Section 6 : Activite recente (3 derniers runs)
 *
 * Les sections 1 (Environment bar), 3 (CTA Scan), 4 (Points a traiter),
 * 5 (Sante bibliotheque) et l'inspecteur droit sont implementes dans les
 * PRs suivantes (3.1-B, 3.1-C).
 *
 * Source backend : api.get_dashboard("latest") (existant).
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

function _renderAccueil(payload) {
  const latestRun = payload.run_info || payload.latest_run || null;
  const recentRuns = Array.isArray(payload.runs_history) ? payload.runs_history : [];
  const heroState = {
    active_run_id: payload.active_run_id || null,
    latest_run: latestRun,
    error_critical: payload.error_critical || false,
    alert_count: payload.alert_count || 0,
    alert_severity: payload.alert_severity || "info",
  };
  return `
    <section class="accueil-view">
      ${_renderHero(heroState)}
      ${_renderLastRunCard(latestRun)}
      ${_renderRecentActivity(recentRuns)}
    </section>
  `;
}

/* --- Event binding ----------------------------------------------------- */

function _bindEvents(container) {
  // Boutons d'action principaux (start scan / resume / view detail / view history)
  container.querySelectorAll("[data-accueil-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      const action = btn.dataset.accueilAction;
      const runId = btn.dataset.runId;
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

  let res = null;
  try {
    res = await apiPost("get_dashboard", { run_id: "latest" }, { signal });
  } catch (err) {
    if (err && err.name === "AbortError") return;
    container.innerHTML = _renderError(err ? String(err.message || err) : "Erreur réseau");
    _bindEvents(container);
    return;
  }

  if (!res || res.ok === false) {
    const msg = (res && (res.message || res.error)) || "Erreur de chargement du dashboard.";
    container.innerHTML = _renderError(msg);
    _bindEvents(container);
    return;
  }

  // Le backend renvoie { ok, mode, run_id, ..., runs_history: [...], + cached_payload }
  // On normalise pour ne dépendre que de quelques champs.
  const data = res.data || res;
  container.innerHTML = _renderAccueil(data);
  _bindEvents(container);
}
