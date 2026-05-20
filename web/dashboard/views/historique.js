/* views/historique.js — Phase 3.4 / Phase 5 (spec 09-historique.md) — Vue Historique complete.
 *
 * Timeline groupée par jour (decision Thomas, spec §1). Source : runs_history
 * fourni par get_dashboard("latest") + detail enrichi par run/get_history_stats.
 *
 * Fonctionnalites :
 *  - Header avec stats agregees (N runs sur 30 jours)
 *  - Banner rétention (auto-suppression > 90j, spec §5)
 *  - Filtres complets : Statut (avec Undone), Periode (avec Custom date picker),
 *    Type (avec Undo), recherche par run_id OU par nom de film
 *  - Toggle Timeline / Tableau (persiste localStorage)
 *  - Timeline groupee par jour avec scroll infini (batch 30 + IntersectionObserver)
 *  - Inspecteur droit cable via right-panel.setSections (4 onglets detailles :
 *    Films / Apply / Doublons / Log) — chaque onglet charge ses donnees via
 *    run/get_history_stats avec cache par run_id
 *  - Page standalone /run/:id (hash route) avec affichage plein écran des 4 onglets
 *  - Actions cablees : "Voir rapport complet" (route /run/:id), "Reprendre" (route
 *    /traitement), "Annuler l'apply" (undo_last_apply), "Supprimer" (run/delete_run)
 *  - Actions dangereuses confirmees via dangerConfirmModal (cf
 *    feedback-cinesort-actions-dangereuses)
 *
 * Route cible : /historique (Phase 2-B PR #261) + /run/:id (standalone).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { navigateTo } from "../core/router.js";
import * as rightPanel from "../components/right-panel.js";
import { dangerConfirmModal } from "../components/modal.js";
import { showToast } from "../components/toast.js";

/* --- Format dates ----------------------------------------------------- */

const _ONE_DAY_MS = 86400000;

function _formatHourMinute(date) {
  if (!date || Number.isNaN(date.getTime())) return "—";
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function _formatDayLabel(date, today) {
  if (!date || Number.isNaN(date.getTime())) return "Date inconnue";
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const diffDays = Math.round((today.getTime() - day.getTime()) / _ONE_DAY_MS);
  if (diffDays === 0) return "Aujourd'hui";
  if (diffDays === 1) return "Hier";
  if (diffDays > 1 && diffDays < 7) return `Il y a ${diffDays} jours`;
  const months = ["jan", "fév", "mar", "avr", "mai", "juin", "juil", "août", "sep", "oct", "nov", "déc"];
  return `${date.getDate()} ${months[date.getMonth()]}`;
}

function _formatDuration(seconds) {
  const s = Number(seconds) || 0;
  if (s <= 0) return "—";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

function _formatDateIsoToFr(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("fr-FR");
  } catch { return iso; }
}

/* --- State management -------------------------------------------------- */

const STORAGE_KEY_VIEW = "cinesort.historique.view"; // "timeline" | "table"
const STORAGE_KEY_PERIOD = "cinesort.historique.period";
const BATCH_SIZE = 30;

let _runs = [];
let _selectedRunId = null;
let _filterStatus = "all";
let _filterPeriod = "30d";
let _filterType = "all";
let _searchQuery = "";
let _viewMode = "timeline";
let _customPeriodFrom = null;   // ISO date string or null
let _customPeriodTo = null;     // ISO date string or null
let _visibleCount = BATCH_SIZE; // scroll infini : nombre de runs affiches
let _retentionDays = 90;
let _scrollObserver = null;
// Cache des appels get_history_stats par run_id (evite refetch a chaque switch onglet).
const _historyStatsCache = new Map();
// Cache des films par run_id (lookup pour recherche par nom).
const _filmsCacheByRun = new Map();

function _readString(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v == null ? fallback : v;
  } catch (_e) {
    return fallback;
  }
}

function _writeString(key, value) {
  try {
    localStorage.setItem(key, String(value));
  } catch (_e) {
    /* noop */
  }
}

/* --- Status derivation (alignee avec accueil.js) ----------------------- */

function _deriveStatus(run) {
  if (run.status) return String(run.status).toUpperCase();
  const errors = Number(run.errors_count || 0);
  const applied = Number(run.applied_rows || 0);
  const total = Number(run.total_rows || 0);
  if (run.undone) return "UNDONE";
  if (errors > 0) return "ERROR";
  if (applied > 0 && applied >= total) return "APPLIED";
  if (applied > 0 && applied < total) return "PARTIAL";
  return "DONE";
}

function _statusClass(status) {
  switch (status) {
    case "ERROR": return "is-error";
    case "PARTIAL": return "is-partial";
    case "APPLIED": return "is-applied";
    case "UNDONE": return "is-undone";
    case "CANCELLED": case "CANCEL": return "is-cancelled";
    case "AWAITING_VALIDATION": return "is-pending";
    default: return "is-done";
  }
}

function _runDate(run) {
  if (run.started_ts != null) return new Date(Number(run.started_ts) * 1000);
  if (run.started_at) return new Date(run.started_at);
  return null;
}

function _runType(run) {
  if (run.is_undo || run.type === "undo") return "undo";
  if (Number(run.applied_rows || 0) > 0) return "apply";
  return "plan";
}

/* --- Filtering -------------------------------------------------------- */

function _periodCutoff() {
  const now = new Date();
  switch (_filterPeriod) {
    case "today": return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    case "7d": return now.getTime() - 7 * _ONE_DAY_MS;
    case "30d": return now.getTime() - 30 * _ONE_DAY_MS;
    case "90d": return now.getTime() - 90 * _ONE_DAY_MS;
    case "all": return 0;
    case "custom": {
      if (!_customPeriodFrom) return 0;
      const fromDate = new Date(_customPeriodFrom);
      return fromDate.getTime();
    }
    default: return now.getTime() - 30 * _ONE_DAY_MS;
  }
}

function _periodUpperBound() {
  if (_filterPeriod === "custom" && _customPeriodTo) {
    // include the whole day "to"
    const d = new Date(_customPeriodTo);
    d.setHours(23, 59, 59, 999);
    return d.getTime();
  }
  return Number.POSITIVE_INFINITY;
}

function _matchesSearchQuery(run, q) {
  if (!q) return true;
  const idLower = String(run.run_id || "").toLowerCase();
  if (idLower.includes(q)) return true;
  // Recherche par nom de film : on consulte le cache de films pour ce run.
  const cached = _filmsCacheByRun.get(run.run_id);
  if (Array.isArray(cached)) {
    for (const f of cached) {
      const name = String(f.title || f.name || f.filename || "").toLowerCase();
      if (name.includes(q)) return true;
    }
  }
  return false;
}

function _filterRuns(runs) {
  const cutoffMin = _periodCutoff();
  const cutoffMax = _periodUpperBound();
  const q = _searchQuery.trim().toLowerCase();
  return runs.filter((r) => {
    const d = _runDate(r);
    if (!d) return false;
    const t = d.getTime();
    if (t < cutoffMin || t > cutoffMax) return false;
    if (_filterStatus !== "all") {
      const status = _deriveStatus(r);
      if (status !== _filterStatus.toUpperCase()) return false;
    }
    if (_filterType !== "all") {
      const type = _runType(r);
      if (type !== _filterType) return false;
    }
    if (q && !_matchesSearchQuery(r, q)) return false;
    return true;
  });
}

/* --- Grouping by day -------------------------------------------------- */

function _groupByDay(runs) {
  const today = new Date();
  const todayDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const groups = new Map();
  runs.forEach((r) => {
    const d = _runDate(r);
    if (!d) return;
    const dayKey = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    if (!groups.has(dayKey)) {
      groups.set(dayKey, { label: _formatDayLabel(d, todayDate), runs: [] });
    }
    groups.get(dayKey).runs.push(r);
  });
  // Trier les runs au sein d'un groupe par heure desc.
  for (const g of groups.values()) {
    g.runs.sort((a, b) => (Number(b.started_ts || 0) - Number(a.started_ts || 0)));
  }
  return Array.from(groups.values());
}

/* --- Rendering -------------------------------------------------------- */

function _renderSkeleton() {
  return `
    <section class="historique-view historique-view--loading" aria-busy="true">
      <div class="historique-header"><div class="v5-skeleton historique-title-skel"></div></div>
      <div class="historique-section v5-skeleton historique-section-skel"></div>
    </section>
  `;
}

function _renderError(message) {
  return `
    <section class="historique-view historique-view--error" role="alert">
      <h2 class="historique-error-title">L'historique n'a pas pu se charger.</h2>
      <p>${escapeHtml(message || "Erreur inconnue")}</p>
      <button type="button" class="v5-btn v5-btn--primary" data-historique-retry>Réessayer</button>
    </section>
  `;
}

function _renderRetentionBanner() {
  const days = _retentionDays || 90;
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - days);
  const cutoffStr = cutoffDate.toLocaleDateString("fr-FR");
  return `
    <div class="historique-retention-banner" role="note">
      <span class="historique-retention-banner-icon" aria-hidden="true">ℹ️</span>
      <span>Les runs antérieurs au <strong>${escapeHtml(cutoffStr)}</strong> (rétention ${days} jours) sont supprimés automatiquement.</span>
    </div>
  `;
}

function _renderCustomDatePicker() {
  if (_filterPeriod !== "custom") return "";
  return `
    <div class="historique-custom-period" role="group" aria-label="Période personnalisée">
      <label class="historique-filter">
        <span class="historique-filter-label">Du</span>
        <input type="date" class="v5-input" data-historique-custom-from value="${escapeHtml(_customPeriodFrom || "")}">
      </label>
      <label class="historique-filter">
        <span class="historique-filter-label">Au</span>
        <input type="date" class="v5-input" data-historique-custom-to value="${escapeHtml(_customPeriodTo || "")}">
      </label>
    </div>
  `;
}

function _renderHeader(stats) {
  return `
    <header class="historique-header">
      <h1 class="historique-title">Historique</h1>
      <p class="historique-summary">${escapeHtml(stats.summary)}</p>
      ${_renderRetentionBanner()}
      <div class="historique-filters" role="toolbar" aria-label="Filtres historique">
        <label class="historique-filter">
          <span class="historique-filter-label">Statut</span>
          <select class="v5-input" data-historique-filter="status">
            <option value="all" ${_filterStatus === "all" ? "selected" : ""}>Tous</option>
            <option value="done" ${_filterStatus === "done" ? "selected" : ""}>Done</option>
            <option value="cancelled" ${_filterStatus === "cancelled" ? "selected" : ""}>Cancelled</option>
            <option value="error" ${_filterStatus === "error" ? "selected" : ""}>Error</option>
            <option value="applied" ${_filterStatus === "applied" ? "selected" : ""}>Applied</option>
            <option value="undone" ${_filterStatus === "undone" ? "selected" : ""}>Undone</option>
          </select>
        </label>
        <label class="historique-filter">
          <span class="historique-filter-label">Période</span>
          <select class="v5-input" data-historique-filter="period">
            <option value="today" ${_filterPeriod === "today" ? "selected" : ""}>Aujourd'hui</option>
            <option value="7d" ${_filterPeriod === "7d" ? "selected" : ""}>7 jours</option>
            <option value="30d" ${_filterPeriod === "30d" ? "selected" : ""}>30 jours</option>
            <option value="90d" ${_filterPeriod === "90d" ? "selected" : ""}>90 jours</option>
            <option value="all" ${_filterPeriod === "all" ? "selected" : ""}>Tout</option>
            <option value="custom" ${_filterPeriod === "custom" ? "selected" : ""}>Custom (date picker)</option>
          </select>
        </label>
        <label class="historique-filter">
          <span class="historique-filter-label">Type</span>
          <select class="v5-input" data-historique-filter="type">
            <option value="all" ${_filterType === "all" ? "selected" : ""}>Tous</option>
            <option value="plan" ${_filterType === "plan" ? "selected" : ""}>Plan (scan)</option>
            <option value="apply" ${_filterType === "apply" ? "selected" : ""}>Apply</option>
            <option value="undo" ${_filterType === "undo" ? "selected" : ""}>Undo</option>
          </select>
        </label>
        <div class="historique-search">
          <input type="search" class="v5-input historique-search-input"
                 placeholder="🔍 Rechercher run_id ou nom de film..."
                 value="${escapeHtml(_searchQuery)}"
                 data-historique-search>
        </div>
        <div class="historique-view-toggle" role="group" aria-label="Mode d'affichage">
          <button type="button" class="v5-btn v5-btn--ghost ${_viewMode === "timeline" ? "is-active" : ""}"
                  data-historique-view="timeline" title="Vue chronologique">📅</button>
          <button type="button" class="v5-btn v5-btn--ghost ${_viewMode === "table" ? "is-active" : ""}"
                  data-historique-view="table" title="Vue tableau">≡</button>
        </div>
      </div>
      ${_renderCustomDatePicker()}
    </header>
  `;
}

function _renderRunRow(run, selected) {
  const d = _runDate(run);
  const time = _formatHourMinute(d);
  const status = _deriveStatus(run);
  const statusClass = _statusClass(status);
  const total = Number(run.total_rows || 0);
  const type = _runType(run);
  const typeLabel = type === "apply" ? "Apply" : (type === "undo" ? "Undo" : "Plan");
  return `
    <li class="historique-run ${selected ? "is-selected" : ""}" tabindex="0" data-run-id="${escapeHtml(run.run_id)}">
      <span class="historique-run-time">${escapeHtml(time)}</span>
      <span class="historique-run-id">${escapeHtml(run.run_id)}</span>
      <span class="historique-run-type">${escapeHtml(typeLabel)}</span>
      <span class="historique-run-total">${total > 0 ? `${total} films` : "—"}</span>
      <span class="historique-run-status ${statusClass}">● ${escapeHtml(status)}</span>
    </li>
  `;
}

function _renderTimeline(runs, selectedId) {
  const groups = _groupByDay(runs);
  if (groups.length === 0) {
    return `
      <section class="historique-section historique-empty">
        <p class="historique-empty-msg">Aucun run ne correspond aux filtres actuels.</p>
      </section>
    `;
  }
  return groups.map((g) => `
    <section class="historique-section historique-day">
      <h3 class="historique-day-label">📅 ${escapeHtml(g.label)}</h3>
      <ul class="historique-runs-list">
        ${g.runs.map((r) => _renderRunRow(r, r.run_id === selectedId)).join("")}
      </ul>
    </section>
  `).join("");
}

function _renderTable(runs, selectedId) {
  if (runs.length === 0) {
    return `
      <section class="historique-section historique-empty">
        <p class="historique-empty-msg">Aucun run ne correspond aux filtres actuels.</p>
      </section>
    `;
  }
  const rows = runs.map((r) => {
    const d = _runDate(r);
    const status = _deriveStatus(r);
    const total = Number(r.total_rows || 0);
    const type = _runType(r);
    const typeLabel = type === "apply" ? "Apply" : (type === "undo" ? "Undo" : "Plan");
    return `
      <tr class="${r.run_id === selectedId ? "is-selected" : ""}" tabindex="0" data-run-id="${escapeHtml(r.run_id)}">
        <td>${escapeHtml(d ? d.toLocaleString("fr-FR") : "—")}</td>
        <td class="historique-table-id">${escapeHtml(r.run_id)}</td>
        <td>${escapeHtml(typeLabel)}</td>
        <td>${total > 0 ? total : "—"}</td>
        <td><span class="historique-run-status ${_statusClass(status)}">${escapeHtml(status)}</span></td>
        <td>${escapeHtml(_formatDuration(r.duration_s))}</td>
      </tr>
    `;
  }).join("");
  return `
    <section class="historique-section historique-table">
      <table class="v5-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Run ID</th>
            <th>Type</th>
            <th>Films</th>
            <th>Statut</th>
            <th>Durée</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </section>
  `;
}

function _renderLoadingMore(remaining) {
  if (remaining <= 0) return "";
  return `
    <div class="historique-loading-more" data-historique-sentinel>
      <span class="historique-loading-more-icon" aria-hidden="true">⏳</span>
      <span>Chargement... (${remaining} runs restants)</span>
    </div>
  `;
}

function _computeHistoriqueStats(runs) {
  const totalRuns = runs.length;
  const applies = runs.filter((r) => Number(r.applied_rows || 0) > 0).length;
  const undones = runs.filter((r) => _deriveStatus(r) === "UNDONE" || _runType(r) === "undo").length;
  const periodLabel = (() => {
    switch (_filterPeriod) {
      case "today": return "aujourd'hui";
      case "7d": return "les 7 derniers jours";
      case "30d": return "les 30 derniers jours";
      case "90d": return "les 90 derniers jours";
      case "all": return "toute la période";
      case "custom": {
        const from = _customPeriodFrom ? _formatDateIsoToFr(_customPeriodFrom) : "—";
        const to = _customPeriodTo ? _formatDateIsoToFr(_customPeriodTo) : "aujourd'hui";
        return `du ${from} au ${to}`;
      }
      default: return "les 30 derniers jours";
    }
  })();
  return {
    summary: `${totalRuns} runs · ${applies} apply · ${undones} undo · sur ${periodLabel}`,
  };
}

function _renderHistorique() {
  const filtered = _filterRuns(_runs);
  const stats = _computeHistoriqueStats(filtered);
  const visible = filtered.slice(0, _visibleCount);
  const remaining = Math.max(0, filtered.length - visible.length);
  return `
    <section class="historique-view">
      ${_renderHeader(stats)}
      ${_viewMode === "table" ? _renderTable(visible, _selectedRunId) : _renderTimeline(visible, _selectedRunId)}
      ${_renderLoadingMore(remaining)}
    </section>
  `;
}

/* --- Inspector content (spec §3) -------------------------------------- */

let _inspectorTab = "films"; // films | apply | doublons | log

const _INSPECTOR_TABS = [
  { id: "films", label: "Films", icon: "🎬" },
  { id: "apply", label: "Apply", icon: "✓" },
  { id: "doublons", label: "Doublons", icon: "🔁" },
  { id: "log", label: "Log", icon: "📜" },
];

function _buildInspectorSections(selectedRun) {
  if (!selectedRun) {
    return [
      {
        title: "Inspecteur",
        html: `<p class="historique-empty-msg">Sélectionnez un run dans la liste pour voir son détail.</p>`,
      },
    ];
  }
  const d = _runDate(selectedRun);
  const dateLabel = d ? d.toLocaleString("fr-FR") : "—";
  const status = _deriveStatus(selectedRun);
  const total = Number(selectedRun.total_rows || 0);
  const applied = Number(selectedRun.applied_rows || 0);
  const dur = _formatDuration(selectedRun.duration_s);
  const isApply = applied > 0;
  return [
    {
      title: `Run ${selectedRun.run_id}`,
      html: `
        <dl class="historique-inspector-dl">
          <div><dt>Date</dt><dd>${escapeHtml(dateLabel)}</dd></div>
          <div><dt>Durée</dt><dd>${escapeHtml(dur)}</dd></div>
          <div><dt>Statut</dt><dd>${escapeHtml(status)}</dd></div>
          <div><dt>Films analysés</dt><dd>${total > 0 ? total : "—"}</dd></div>
          <div><dt>Apply effectué</dt><dd>${isApply ? "Oui" : "Non"}</dd></div>
        </dl>
      `,
    },
    _buildInspectorTabSection(selectedRun),
    {
      title: "Actions",
      html: `
        <div class="historique-inspector-actions">
          <button type="button" class="v5-btn v5-btn--secondary" data-historique-action="view-report" data-run-id="${escapeHtml(selectedRun.run_id)}">📄 Voir rapport complet</button>
          <button type="button" class="v5-btn v5-btn--ghost" data-historique-action="resume" data-run-id="${escapeHtml(selectedRun.run_id)}">↻ Reprendre ce run</button>
          ${isApply ? `<button type="button" class="v5-btn v5-btn--ghost v5-btn--danger" data-historique-action="undo-apply" data-run-id="${escapeHtml(selectedRun.run_id)}">↺ Annuler l'apply</button>` : ""}
          <button type="button" class="v5-btn v5-btn--ghost v5-btn--danger" data-historique-action="delete-run" data-run-id="${escapeHtml(selectedRun.run_id)}">🗑 Supprimer ce run</button>
        </div>
      `,
    },
  ];
}

function _renderInspectorTabs() {
  return `
    <div class="historique-inspector-tabs" role="tablist" aria-label="Détail du run">
      ${_INSPECTOR_TABS.map((t) => `
        <button type="button"
                class="historique-inspector-tab${_inspectorTab === t.id ? " is-active" : ""}"
                data-historique-inspector-tab="${t.id}"
                role="tab"
                aria-selected="${_inspectorTab === t.id}">
          ${t.icon} ${t.label}
        </button>
      `).join("")}
    </div>
  `;
}

/* --- Inspector detailed tabs (Phase 5) ------------------------------ */

function _filmStatusLabel(film) {
  // Map vers Approuvé/Rejeté/Doublon/Suppression
  const tier = String(film.tier || "").toLowerCase();
  if (tier === "reject") return { label: "Rejeté", cls: "is-rejected" };
  const dec = String(film.decision || film.status || "").toLowerCase();
  if (dec.includes("duplicate") || dec === "duplicate" || film.is_duplicate) return { label: "Doublon", cls: "is-duplicate" };
  if (dec.includes("delete") || dec === "delete_marked") return { label: "Suppression", cls: "is-deleted" };
  if (dec.includes("reject")) return { label: "Rejeté", cls: "is-rejected" };
  return { label: "Approuvé", cls: "is-approved" };
}

function _renderFilmsList(runStats, runId) {
  const films = Array.isArray(runStats.films) ? runStats.films : [];
  if (films.length === 0) {
    const total = Number(runStats.total_rows || 0);
    if (total > 0) {
      return `
        <p class="historique-tab-stat"><strong>${total}</strong> film${total > 1 ? "s" : ""} analysé${total > 1 ? "s" : ""} (détail non disponible pour ce run)</p>
        <a href="#/bibliotheque?run_id=${encodeURIComponent(runId)}" class="v5-btn v5-btn--secondary v5-btn--sm">→ Voir dans Bibliothèque</a>
      `;
    }
    return `<p class="historique-empty-msg">Aucun film associé à ce run.</p>`;
  }
  const items = films.map((f) => {
    const st = _filmStatusLabel(f);
    const title = String(f.title || f.name || f.filename || `Film ${f.film_id || ""}`);
    const score = (f.score != null) ? Number(f.score).toFixed(1) : "—";
    const filmId = f.film_id != null ? `#/film/${encodeURIComponent(f.film_id)}` : null;
    return `
      <li class="historique-film-row">
        <span class="historique-film-title">${escapeHtml(title)}</span>
        <span class="historique-film-status ${st.cls}">${escapeHtml(st.label)}</span>
        <span class="historique-film-score">${escapeHtml(score)}</span>
        ${filmId ? `<a href="${escapeHtml(filmId)}" class="historique-film-link">→</a>` : `<span class="historique-film-link-dim">—</span>`}
      </li>
    `;
  }).join("");
  return `
    <p class="historique-tab-stat"><strong>${films.length}</strong> film${films.length > 1 ? "s" : ""} traité${films.length > 1 ? "s" : ""}</p>
    <ul class="historique-films-list">${items}</ul>
    <a href="#/bibliotheque?run_id=${encodeURIComponent(runId)}" class="v5-btn v5-btn--secondary v5-btn--sm">→ Voir dans Bibliothèque</a>
  `;
}

function _opLabel(op) {
  const t = String(op.op_type || "").toLowerCase();
  const src = String(op.src_path || "");
  const dst = String(op.dst_path || "");
  const srcShort = src.split(/[\\/]/).pop() || src;
  const dstShort = dst.split(/[\\/]/).pop() || dst;
  if (t === "rename") return { icon: "→", text: `Renommé ${srcShort} → ${dstShort}` };
  if (t === "move") return { icon: "→", text: `Déplacé ${srcShort} → ${dst}` };
  if (t === "quarantine") return { icon: "⚠", text: `Quarantaine bucket _review/ — ${srcShort}` };
  if (t === "delete_mark" || t === "mark_delete") return { icon: "🗑", text: `Marqué suppression — ${srcShort}` };
  return { icon: "•", text: `${op.op_type || "Op"} : ${srcShort}${dst ? " → " + dstShort : ""}` };
}

function _renderApplyOps(runStats) {
  const ops = Array.isArray(runStats.apply_operations) ? runStats.apply_operations : [];
  const applied = Number(runStats.applied_rows || 0);
  const total = Number(runStats.total_rows || 0);
  const errors = Number(runStats.errors_count || 0);
  if (ops.length === 0) {
    return `
      <p class="historique-tab-stat"><strong>${applied}</strong> film${applied > 1 ? "s" : ""} appliqué${applied > 1 ? "s" : ""}</p>
      <p class="historique-tab-stat"><strong>${Math.max(0, total - applied)}</strong> non appliqué${total - applied > 1 ? "s" : ""}</p>
      <p class="historique-tab-stat"><strong>${errors}</strong> erreur${errors > 1 ? "s" : ""}</p>
      ${applied > 0 ? `<p class="historique-empty-msg">Détail des opérations non disponible pour ce run.</p>` : `<p class="historique-empty-msg">Aucun apply effectué.</p>`}
    `;
  }
  // Compter par type
  const counts = ops.reduce((acc, o) => {
    const t = String(o.op_type || "other").toLowerCase();
    acc[t] = (acc[t] || 0) + 1;
    return acc;
  }, {});
  const countersHtml = Object.entries(counts).map(([t, n]) => `<span class="historique-apply-counter">${escapeHtml(t)}: <strong>${n}</strong></span>`).join("");
  const opsHtml = ops.map((o) => {
    const lbl = _opLabel(o);
    return `<li class="historique-apply-op"><span class="historique-apply-op-icon">${escapeHtml(lbl.icon)}</span><span class="historique-apply-op-text">${escapeHtml(lbl.text)}</span></li>`;
  }).join("");
  return `
    <p class="historique-tab-stat"><strong>${ops.length}</strong> opération${ops.length > 1 ? "s" : ""} appliquée${ops.length > 1 ? "s" : ""}</p>
    <div class="historique-apply-counters">${countersHtml}</div>
    <ul class="historique-apply-ops">${opsHtml}</ul>
  `;
}

function _renderDoublonsList(runStats) {
  const decided = Array.isArray(runStats.duplicates_decided) ? runStats.duplicates_decided : [];
  const skipped = Array.isArray(runStats.duplicates_skipped) ? runStats.duplicates_skipped : [];
  const dupGroups = Number(runStats.duplicates_groups || 0);
  if (decided.length === 0 && skipped.length === 0) {
    return `
      <p class="historique-tab-stat"><strong>${dupGroups}</strong> groupe${dupGroups > 1 ? "s" : ""} de doublons</p>
      ${dupGroups > 0 ? `<p class="historique-empty-msg">Détail des groupes non disponible pour ce run.</p><a href="#/doublons" class="v5-btn v5-btn--secondary v5-btn--sm">→ Ouvrir la vue Doublons</a>` : `<p class="historique-empty-msg">Aucun doublon dans ce run.</p>`}
    `;
  }
  const decidedHtml = decided.map((g) => {
    const title = String(g.title || g.canonical_title || "(Sans titre)");
    const year = g.year ? ` (${g.year})` : "";
    const winner = String(g.winner_label || g.winner || "—");
    const savings = (g.size_savings != null) ? `· ${(Number(g.size_savings) / (1024 * 1024 * 1024)).toFixed(1)} Go récupérés` : "";
    return `<li class="historique-doublon-row historique-doublon-row--decided">${escapeHtml(title + year)} — Garder ${escapeHtml(winner)} ${escapeHtml(savings)}</li>`;
  }).join("");
  const skippedHtml = skipped.map((g) => {
    const title = String(g.title || g.canonical_title || "(Sans titre)");
    const year = g.year ? ` (${g.year})` : "";
    return `<li class="historique-doublon-row historique-doublon-row--skipped">${escapeHtml(title + year)} — Non décidé (skip)</li>`;
  }).join("");
  return `
    <p class="historique-tab-stat"><strong>${decided.length}</strong> décidé${decided.length > 1 ? "s" : ""} · <strong>${skipped.length}</strong> ignoré${skipped.length > 1 ? "s" : ""}</p>
    ${decided.length > 0 ? `<h4 class="historique-doublons-h4">Décidés</h4><ul class="historique-doublons-list">${decidedHtml}</ul>` : ""}
    ${skipped.length > 0 ? `<h4 class="historique-doublons-h4">Ignorés</h4><ul class="historique-doublons-list">${skippedHtml}</ul>` : ""}
  `;
}

function _renderLogViewer(runStats, runId) {
  const lines = Array.isArray(runStats.log_lines) ? runStats.log_lines : [];
  if (lines.length === 0) {
    return `
      <div class="historique-log-viewer-actions">
        <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-historique-action="reload-log" data-run-id="${escapeHtml(runId)}">↻ Recharger</button>
      </div>
      <p class="historique-empty-msg">Aucun log disponible pour ce run.</p>
    `;
  }
  const content = lines.map((l) => escapeHtml(String(l))).join("\n");
  return `
    <div class="historique-log-viewer-actions">
      <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-historique-action="reload-log" data-run-id="${escapeHtml(runId)}">↻ Recharger</button>
      <span class="historique-log-count">${lines.length} ligne${lines.length > 1 ? "s" : ""}</span>
    </div>
    <pre class="historique-log-viewer">${content}</pre>
  `;
}

function _renderInspectorTabContent(run) {
  const runId = run.run_id;
  const cached = _historyStatsCache.get(runId);
  if (!cached) {
    return `<p class="historique-tab-loading" data-historique-tab-loading="${escapeHtml(runId)}">Chargement du détail…</p>`;
  }
  if (cached.error) {
    return `<p class="historique-empty-msg">Erreur de chargement : ${escapeHtml(cached.error)}</p>`;
  }
  const runStats = cached.run || cached;
  switch (_inspectorTab) {
    case "films":   return _renderFilmsList(runStats, runId);
    case "apply":   return _renderApplyOps(runStats);
    case "doublons": return _renderDoublonsList(runStats);
    case "log":
    default:        return _renderLogViewer(runStats, runId);
  }
}

function _buildInspectorTabSection(selectedRun) {
  return {
    title: "Détail",
    html: `
      ${_renderInspectorTabs()}
      <div class="historique-inspector-tab-content" data-historique-inspector-content>
        ${_renderInspectorTabContent(selectedRun)}
      </div>
    `,
  };
}

function _updateInspector() {
  if (typeof rightPanel.setSections !== "function") return;
  const sel = _selectedRunId ? _runs.find((r) => r.run_id === _selectedRunId) : null;
  try {
    rightPanel.setSections(_buildInspectorSections(sel));
  } catch (err) {
    console.warn("[historique] setSections inspector failed:", err);
  }
}

/* --- Detail fetch ----------------------------------------------------- */

async function _ensureHistoryStats(runId, { force = false } = {}) {
  if (!runId) return null;
  if (!force && _historyStatsCache.has(runId)) return _historyStatsCache.get(runId);
  try {
    // Endpoint backend PR #298 (run/get_history_stats). Si non encore mergé,
    // on retourne un fallback minimal a partir du run courant pour ne pas casser.
    const res = await apiPost("run/get_history_stats", { run_id: runId });
    if (res && res.ok !== false) {
      // Le payload est `{ok, run: {...}}` ou `{ok, ...}` selon impl.
      const data = res.run ? res.run : (res.data && res.data.run ? res.data.run : (res.data || {}));
      // Pour les logs : si pas dans payload, fallback via get_status.
      if (!Array.isArray(data.log_lines)) {
        try {
          const statusRes = await apiPost("run/get_status", { run_id: runId, last_log_index: 0 });
          const logs = (statusRes && statusRes.data && Array.isArray(statusRes.data.logs))
            ? statusRes.data.logs
            : (Array.isArray(statusRes?.logs) ? statusRes.logs : []);
          data.log_lines = logs;
        } catch { data.log_lines = []; }
      }
      // Indexe films par run pour la recherche.
      if (Array.isArray(data.films)) _filmsCacheByRun.set(runId, data.films);
      _historyStatsCache.set(runId, { ok: true, run: data });
      return _historyStatsCache.get(runId);
    }
    // Fallback : on essaie au moins get_status pour avoir des logs et un état basique.
    let logs = [];
    try {
      const statusRes = await apiPost("run/get_status", { run_id: runId, last_log_index: 0 });
      logs = (statusRes && statusRes.data && Array.isArray(statusRes.data.logs))
        ? statusRes.data.logs
        : (Array.isArray(statusRes?.logs) ? statusRes.logs : []);
    } catch { /* ignore */ }
    const base = _runs.find((r) => r.run_id === runId) || {};
    _historyStatsCache.set(runId, {
      ok: true,
      run: {
        run_id: runId,
        total_rows: base.total_rows || 0,
        applied_rows: base.applied_rows || 0,
        errors_count: base.errors_count || 0,
        duplicates_groups: base.duplicates_groups || 0,
        films: [],
        apply_operations: [],
        duplicates_decided: [],
        duplicates_skipped: [],
        log_lines: logs,
      },
    });
    return _historyStatsCache.get(runId);
  } catch (err) {
    _historyStatsCache.set(runId, { error: String(err && err.message || err) });
    return _historyStatsCache.get(runId);
  }
}

async function _fetchAndUpdate(runId) {
  await _ensureHistoryStats(runId);
  // Si l'utilisateur a entre-temps change de run, on n'overwrite pas.
  if (_selectedRunId === runId) {
    _updateInspector();
    // Re-render standalone si on est sur cette route.
    _refreshStandaloneIfActive();
  }
}

/* --- Events ----------------------------------------------------------- */

function _selectRun(container, runId) {
  _selectedRunId = runId;
  if (container) {
    container.querySelectorAll("[data-run-id]").forEach((el) => {
      el.classList.toggle("is-selected", el.dataset.runId === runId);
    });
  }
  _updateInspector();
  // Async fetch detail.
  _fetchAndUpdate(runId);
}

function _rerender(container) {
  _detachScrollObserver();
  container.innerHTML = _renderHistorique();
  _bindEvents(container);
  _updateInspector();
  _attachScrollObserver(container);
}

function _attachScrollObserver(container) {
  if (!container) return;
  const sentinel = container.querySelector("[data-historique-sentinel]");
  if (!sentinel) return;
  if (typeof IntersectionObserver === "undefined") return;
  _scrollObserver = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        _visibleCount += BATCH_SIZE;
        _rerender(container);
        break;
      }
    }
  }, { rootMargin: "200px" });
  _scrollObserver.observe(sentinel);
}

function _detachScrollObserver() {
  if (_scrollObserver) {
    try { _scrollObserver.disconnect(); } catch { /* noop */ }
    _scrollObserver = null;
  }
}

function _bindEvents(container) {
  // Filtres
  container.querySelectorAll("[data-historique-filter]").forEach((sel) => {
    sel.addEventListener("change", (ev) => {
      const filter = sel.dataset.historiqueFilter;
      const val = ev.target.value;
      if (filter === "status") _filterStatus = val;
      else if (filter === "period") { _filterPeriod = val; _writeString(STORAGE_KEY_PERIOD, val); }
      else if (filter === "type") _filterType = val;
      _visibleCount = BATCH_SIZE;
      _rerender(container);
    });
  });
  // Custom date pickers
  const fromInput = container.querySelector("[data-historique-custom-from]");
  if (fromInput) {
    fromInput.addEventListener("change", (ev) => {
      _customPeriodFrom = String(ev.target.value || "") || null;
      _visibleCount = BATCH_SIZE;
      _rerender(container);
    });
  }
  const toInput = container.querySelector("[data-historique-custom-to]");
  if (toInput) {
    toInput.addEventListener("change", (ev) => {
      _customPeriodTo = String(ev.target.value || "") || null;
      _visibleCount = BATCH_SIZE;
      _rerender(container);
    });
  }
  // Recherche
  const searchInput = container.querySelector("[data-historique-search]");
  if (searchInput) {
    let debounce;
    searchInput.addEventListener("input", (ev) => {
      const value = String(ev.target.value || "");
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        _searchQuery = value;
        _visibleCount = BATCH_SIZE;
        _rerender(container);
        // Restore focus dans la search box.
        const next = container.querySelector("[data-historique-search]");
        if (next) { next.focus(); next.setSelectionRange(value.length, value.length); }
      }, 200);
    });
  }
  // Toggle vue
  container.querySelectorAll("[data-historique-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _viewMode = btn.dataset.historiqueView;
      _writeString(STORAGE_KEY_VIEW, _viewMode);
      _rerender(container);
    });
  });
  // Selection run (timeline + table)
  container.querySelectorAll("[data-run-id]").forEach((el) => {
    const select = () => _selectRun(container, el.dataset.runId);
    el.addEventListener("click", select);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); }
    });
  });
  // Actions (depuis l'inspector ou ailleurs : delegation globale)
  document.addEventListener("click", _onActionClick);
  // Retry
  const retryBtn = container.querySelector("[data-historique-retry]");
  if (retryBtn) retryBtn.addEventListener("click", () => initHistorique(container));
}

async function _doUndoApply(runId) {
  try {
    const res = await apiPost("run/undo_last_apply", { run_id: runId, dry_run: false, atomic: true });
    if (res && res.ok !== false) {
      showToast({ type: "success", text: "Apply annulé. Fichiers restaurés." });
      // Refresh dashboard + cache + UI.
      _historyStatsCache.delete(runId);
      await _refreshRuns();
    } else {
      const msg = (res && (res.message || res.error)) || "Échec de l'annulation.";
      showToast({ type: "error", text: msg });
    }
  } catch (err) {
    showToast({ type: "error", text: `Erreur : ${err && err.message || err}` });
  }
}

async function _doDeleteRun(runId) {
  try {
    const res = await apiPost("run/delete_run", { run_id: runId });
    if (res && res.ok !== false) {
      showToast({ type: "success", text: `Run ${runId} supprimé.` });
      // Splice du tableau local sans refetch reseau.
      _runs = _runs.filter((r) => r.run_id !== runId);
      _historyStatsCache.delete(runId);
      _filmsCacheByRun.delete(runId);
      if (_selectedRunId === runId) {
        _selectedRunId = _runs.length > 0 ? _runs[0].run_id : null;
      }
      const container = document.querySelector(".historique-view");
      const root = container ? container.parentNode : document.querySelector("#view-qij") || document.querySelector("#view-historique");
      if (root) _rerender(root);
    } else {
      const msg = (res && (res.message || res.error)) || "Échec de la suppression.";
      showToast({ type: "error", text: msg });
    }
  } catch (err) {
    showToast({ type: "error", text: `Erreur : ${err && err.message || err}` });
  }
}

async function _refreshRuns() {
  try {
    const res = await apiPost("run/get_dashboard", { run_id: "latest" });
    if (res && res.ok !== false) {
      const data = res.data || res;
      _runs = Array.isArray(data.runs_history) ? data.runs_history : [];
      _retentionDays = Number(data.history_retention_days || _retentionDays || 90);
      const container = document.querySelector(".historique-view");
      const root = container ? container.parentNode : null;
      if (root) _rerender(root);
    }
  } catch { /* silencieux */ }
}

function _onActionClick(ev) {
  // Tab clicks dans l'inspector
  const tabBtn = ev.target.closest && ev.target.closest("[data-historique-inspector-tab]");
  if (tabBtn) {
    _inspectorTab = tabBtn.dataset.historiqueInspectorTab;
    _updateInspector();
    // Si la standalone page existe, refresh aussi.
    _refreshStandaloneIfActive();
    return;
  }
  const target = ev.target.closest && ev.target.closest("[data-historique-action]");
  if (!target) return;
  const action = target.dataset.historiqueAction;
  const runId = target.dataset.runId;
  switch (action) {
    case "view-report":
      // Phase 5 : navigation vers la page standalone /run/:id.
      if (runId) navigateTo(`/run/${encodeURIComponent(runId)}`);
      break;
    case "resume":
      if (runId) navigateTo(`/traitement#run-${encodeURIComponent(runId)}`);
      break;
    case "undo-apply":
      // Action dangereuse — dangerConfirmModal (P0 #233, cf feedback-cinesort-actions-dangereuses).
      dangerConfirmModal({
        title: `Annuler l'apply du run ${runId} ?`,
        items: [`Run ${runId}`],
        consequence:
          "Cela va restaurer les fichiers à leur emplacement initial. " +
          "Réversible tant qu'un nouvel apply n'a pas eu lieu.",
        countdownSeconds: 3,
        confirmLabel: "✗ Annuler l'apply",
        onConfirm: () => _doUndoApply(runId),
      });
      break;
    case "delete-run":
      // Action dangereuse — dangerConfirmModal + retention 90j auto (spec 09 §5).
      dangerConfirmModal({
        title: `Supprimer le run ${runId} de l'historique ?`,
        items: [`Run ${runId}`],
        consequence:
          "Le run + son plan + son log seront supprimés définitivement. " +
          "Aucune modification sur les fichiers vidéo du disque. Action NON réversible.",
        countdownSeconds: 3,
        confirmLabel: "✗ Supprimer le run",
        onConfirm: () => _doDeleteRun(runId),
      });
      break;
    case "reload-log":
      if (runId) {
        _historyStatsCache.delete(runId);
        _fetchAndUpdate(runId);
      }
      break;
    default:
      break;
  }
}

/* --- Standalone page /run/:id (Phase 5) ------------------------------ */

let _standaloneRunId = null;
let _standaloneContainer = null;

function _renderStandalone(runId) {
  const cached = _historyStatsCache.get(runId);
  const run = (cached && cached.run) || { run_id: runId };
  const d = run.started_ts ? new Date(Number(run.started_ts) * 1000) : null;
  const dateLabel = d ? d.toLocaleString("fr-FR") : "—";
  const status = _deriveStatus(run);
  const total = Number(run.total_rows || 0);
  const applied = Number(run.applied_rows || 0);
  const dur = _formatDuration(run.duration_s);
  return `
    <section class="historique-run-detail-page">
      <header class="historique-run-detail-header">
        <button type="button" class="v5-btn v5-btn--ghost" data-historique-back>← Retour à l'historique</button>
        <h1 class="historique-run-detail-title">Run ${escapeHtml(runId)}</h1>
        <div class="historique-run-detail-meta">
          <span><strong>Date</strong> : ${escapeHtml(dateLabel)}</span>
          <span><strong>Durée</strong> : ${escapeHtml(dur)}</span>
          <span><strong>Statut</strong> : <span class="historique-run-status ${_statusClass(status)}">${escapeHtml(status)}</span></span>
          <span><strong>Films</strong> : ${total}</span>
          <span><strong>Appliqués</strong> : ${applied}</span>
        </div>
      </header>
      <div class="historique-run-detail-tabs" role="tablist" aria-label="Détail du run (page complète)">
        ${_INSPECTOR_TABS.map((t) => `
          <button type="button" class="historique-inspector-tab${_inspectorTab === t.id ? " is-active" : ""}" data-historique-inspector-tab="${t.id}" role="tab" aria-selected="${_inspectorTab === t.id}">${t.icon} ${t.label}</button>
        `).join("")}
      </div>
      <div class="historique-run-detail-content" data-historique-standalone-content>
        ${_renderInspectorTabContent({ run_id: runId })}
      </div>
    </section>
  `;
}

function _refreshStandaloneIfActive() {
  if (!_standaloneRunId || !_standaloneContainer) return;
  // Si le DOM standalone n'existe plus (navigation), on no-op.
  if (!document.body.contains(_standaloneContainer)) return;
  _standaloneContainer.innerHTML = _renderStandalone(_standaloneRunId);
  _bindStandaloneEvents();
}

function _bindStandaloneEvents() {
  if (!_standaloneContainer) return;
  const back = _standaloneContainer.querySelector("[data-historique-back]");
  if (back) back.addEventListener("click", () => navigateTo("/historique"));
  // Tab clicks (delegues via _onActionClick deja attache au document).
}

export async function initRunDetailPage(container, opts) {
  if (!container) return;
  const params = (opts && opts.params) || {};
  const runId = params.id;
  _standaloneRunId = runId;
  _standaloneContainer = container;
  container.innerHTML = _renderStandalone(runId);
  _bindStandaloneEvents();
  // Charge le detail si pas en cache.
  await _ensureHistoryStats(runId);
  _refreshStandaloneIfActive();
  // Attach action click delegation (idempotent grace au listener au boot).
  document.addEventListener("click", _onActionClick);
}

export function unmountRunDetailPage() {
  document.removeEventListener("click", _onActionClick);
  _standaloneRunId = null;
  _standaloneContainer = null;
}

/* --- Entrypoint ------------------------------------------------------- */

export async function initHistorique(container) {
  if (!container) return;
  // Restore persisted state
  _viewMode = _readString(STORAGE_KEY_VIEW, "timeline");
  _filterPeriod = _readString(STORAGE_KEY_PERIOD, "30d");
  if (!["timeline", "table"].includes(_viewMode)) _viewMode = "timeline";
  _visibleCount = BATCH_SIZE;

  container.innerHTML = _renderSkeleton();
  const signal = typeof getNavSignal === "function" ? getNavSignal() : undefined;

  let res = null;
  try {
    res = await apiPost("run/get_dashboard", { run_id: "latest" }, { signal });
  } catch (err) {
    if (err && err.name === "AbortError") return;
    container.innerHTML = _renderError(err ? String(err.message || err) : "Erreur réseau");
    _bindEvents(container);
    return;
  }
  if (!res || res.ok === false) {
    container.innerHTML = _renderError((res && (res.message || res.error)) || "Erreur de chargement.");
    _bindEvents(container);
    return;
  }

  const data = res.data || res;
  _runs = Array.isArray(data.runs_history) ? data.runs_history : [];
  _retentionDays = Number(data.history_retention_days || 90);
  _selectedRunId = _runs.length > 0 ? _runs[0].run_id : null;

  _rerender(container);
  // Charge le detail du run selectionne par defaut.
  if (_selectedRunId) _fetchAndUpdate(_selectedRunId);
}

export function unmountHistorique() {
  document.removeEventListener("click", _onActionClick);
  _detachScrollObserver();
  _runs = [];
  _selectedRunId = null;
}
