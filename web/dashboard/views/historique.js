/* views/historique.js — Phase 3.4 (spec 09-historique.md) — Vue Historique refondue.
 *
 * Timeline groupée par jour (decision Thomas, spec §1). Source : runs_history
 * fourni par get_dashboard("latest").
 *
 * Pour la PR initiale (squelette) :
 *  - Header avec stats agregees (N runs sur 30 jours)
 *  - Filtres : Statut, Periode, Type, recherche (filtrage cote frontend pour v1)
 *  - Toggle Timeline / Tableau (persiste localStorage)
 *  - Timeline groupee par jour : Aujourd'hui / Hier / "5 mai" / etc.
 *  - Inspecteur droit cable via right-panel.setSections (5 onglets : Resume /
 *    Films / Apply / Doublons / Log) - PR initiale rend Resume uniquement,
 *    les autres en placeholder
 *  - Actions : "Voir rapport complet" + "Reprendre" + "Annuler l'apply" + "Supprimer"
 *    (3 dernieres en placeholder car endpoints backend a creer en PR future)
 *
 * Actions dangereuses (suppr run, annuler apply) demanderont modale de
 * confirmation (cf feedback-cinesort-actions-dangereuses). Pour cette PR
 * squelette, on stub avec navigateTo placeholder.
 *
 * Route cible : /historique (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { navigateTo } from "../core/router.js";
import * as rightPanel from "../components/right-panel.js";

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

/* --- State management -------------------------------------------------- */

const STORAGE_KEY_VIEW = "cinesort.historique.view"; // "timeline" | "table"
const STORAGE_KEY_PERIOD = "cinesort.historique.period";

let _runs = [];
let _selectedRunId = null;
let _filterStatus = "all";
let _filterPeriod = "30d";
let _filterType = "all";
let _searchQuery = "";
let _viewMode = "timeline";

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

/* --- Filtering -------------------------------------------------------- */

function _filterRuns(runs) {
  const now = new Date();
  const periodCutoffMs = (() => {
    switch (_filterPeriod) {
      case "today": return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
      case "7d": return now.getTime() - 7 * _ONE_DAY_MS;
      case "30d": return now.getTime() - 30 * _ONE_DAY_MS;
      case "90d": return now.getTime() - 90 * _ONE_DAY_MS;
      case "all": return 0;
      default: return now.getTime() - 30 * _ONE_DAY_MS;
    }
  })();
  const q = _searchQuery.trim().toLowerCase();
  return runs.filter((r) => {
    const d = _runDate(r);
    if (!d || d.getTime() < periodCutoffMs) return false;
    if (_filterStatus !== "all") {
      const status = _deriveStatus(r);
      if (status !== _filterStatus.toUpperCase()) return false;
    }
    if (_filterType !== "all") {
      // Type "apply" = run avec applied_rows > 0. Type "plan" = pas d'apply.
      // Type "undo" reservé pour PR future (Phase 3.3 traitement).
      const hasApply = Number(r.applied_rows || 0) > 0;
      if (_filterType === "apply" && !hasApply) return false;
      if (_filterType === "plan" && hasApply) return false;
    }
    if (q) {
      const idLower = String(r.run_id || "").toLowerCase();
      if (!idLower.includes(q)) return false;
    }
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

function _renderHeader(stats) {
  return `
    <header class="historique-header">
      <h1 class="historique-title">Historique</h1>
      <p class="historique-summary">${escapeHtml(stats.summary)}</p>
      <div class="historique-filters" role="toolbar" aria-label="Filtres historique">
        <label class="historique-filter">
          <span class="historique-filter-label">Statut</span>
          <select class="v5-input" data-historique-filter="status">
            <option value="all" ${_filterStatus === "all" ? "selected" : ""}>Tous</option>
            <option value="done" ${_filterStatus === "done" ? "selected" : ""}>Done</option>
            <option value="cancelled" ${_filterStatus === "cancelled" ? "selected" : ""}>Cancelled</option>
            <option value="error" ${_filterStatus === "error" ? "selected" : ""}>Error</option>
            <option value="applied" ${_filterStatus === "applied" ? "selected" : ""}>Applied</option>
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
          </select>
        </label>
        <label class="historique-filter">
          <span class="historique-filter-label">Type</span>
          <select class="v5-input" data-historique-filter="type">
            <option value="all" ${_filterType === "all" ? "selected" : ""}>Tous</option>
            <option value="plan" ${_filterType === "plan" ? "selected" : ""}>Plan (scan)</option>
            <option value="apply" ${_filterType === "apply" ? "selected" : ""}>Apply</option>
          </select>
        </label>
        <div class="historique-search">
          <input type="search" class="v5-input historique-search-input"
                 placeholder="🔍 Rechercher run_id..."
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
    </header>
  `;
}

function _renderRunRow(run, selected) {
  const d = _runDate(run);
  const time = _formatHourMinute(d);
  const status = _deriveStatus(run);
  const statusClass = _statusClass(status);
  const total = Number(run.total_rows || 0);
  const isApply = Number(run.applied_rows || 0) > 0;
  const typeLabel = isApply ? "Apply" : "Plan";
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
    const isApply = Number(r.applied_rows || 0) > 0;
    return `
      <tr class="${r.run_id === selectedId ? "is-selected" : ""}" tabindex="0" data-run-id="${escapeHtml(r.run_id)}">
        <td>${escapeHtml(d ? d.toLocaleString("fr-FR") : "—")}</td>
        <td class="historique-table-id">${escapeHtml(r.run_id)}</td>
        <td>${escapeHtml(isApply ? "Apply" : "Plan")}</td>
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

function _computeHistoriqueStats(runs) {
  const totalRuns = runs.length;
  const applies = runs.filter((r) => Number(r.applied_rows || 0) > 0).length;
  const errors = runs.filter((r) => Number(r.errors_count || 0) > 0).length;
  const periodLabel = (() => {
    switch (_filterPeriod) {
      case "today": return "aujourd'hui";
      case "7d": return "les 7 derniers jours";
      case "30d": return "les 30 derniers jours";
      case "90d": return "les 90 derniers jours";
      case "all": return "toute la période";
      default: return "les 30 derniers jours";
    }
  })();
  return {
    summary: `${totalRuns} runs · ${applies} apply · ${errors} erreurs · sur ${periodLabel}`,
  };
}

function _renderHistorique() {
  const filtered = _filterRuns(_runs);
  const stats = _computeHistoriqueStats(filtered);
  return `
    <section class="historique-view">
      ${_renderHeader(stats)}
      ${_viewMode === "table" ? _renderTable(filtered, _selectedRunId) : _renderTimeline(filtered, _selectedRunId)}
    </section>
  `;
}

/* --- Inspector content (spec §3) -------------------------------------- */

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

let _inspectorTab = "films"; // films | apply | doublons | log

const _INSPECTOR_TABS = [
  { id: "films", label: "Films", icon: "🎬" },
  { id: "apply", label: "Apply", icon: "✓" },
  { id: "doublons", label: "Doublons", icon: "🔁" },
  { id: "log", label: "Log", icon: "📜" },
];

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

function _renderInspectorTabContent(run) {
  const runId = run.run_id;
  const total = Number(run.total_rows || 0);
  const applied = Number(run.applied_rows || 0);
  const errors = Number(run.errors_count || 0);
  const conflicts = Number(run.conflicts_count || 0);
  const dupGroups = Number(run.duplicates_groups || 0);
  switch (_inspectorTab) {
    case "films":
      return `
        <p class="historique-tab-stat"><strong>${total}</strong> film${total > 1 ? "s" : ""} analysé${total > 1 ? "s" : ""}</p>
        <p class="historique-tab-stat"><strong>${conflicts}</strong> conflit${conflicts > 1 ? "s" : ""} à vérifier</p>
        <a href="#/bibliotheque?run_id=${encodeURIComponent(runId)}" class="v5-btn v5-btn--secondary v5-btn--sm">→ Voir dans Bibliothèque</a>
      `;
    case "apply":
      return `
        <p class="historique-tab-stat"><strong>${applied}</strong> film${applied > 1 ? "s" : ""} appliqué${applied > 1 ? "s" : ""}</p>
        <p class="historique-tab-stat"><strong>${Math.max(0, total - applied)}</strong> non appliqué${total - applied > 1 ? "s" : ""}</p>
        <p class="historique-tab-stat"><strong>${errors}</strong> erreur${errors > 1 ? "s" : ""}</p>
        ${applied > 0 ? `<a href="#/traitement#step-apply" class="v5-btn v5-btn--secondary v5-btn--sm">→ Voir l'étape Apply</a>` : ""}
      `;
    case "doublons":
      return `
        <p class="historique-tab-stat"><strong>${dupGroups}</strong> groupe${dupGroups > 1 ? "s" : ""} de doublons</p>
        ${dupGroups > 0 ? `<a href="#/doublons" class="v5-btn v5-btn--secondary v5-btn--sm">→ Ouvrir la vue Doublons</a>` : `<p class="historique-empty-msg">Aucun doublon dans ce run.</p>`}
      `;
    case "log":
    default:
      return `
        <p class="historique-tab-stat"><strong>${errors}</strong> erreur${errors > 1 ? "s" : ""} loguée${errors > 1 ? "s" : ""}</p>
        <p class="historique-empty-msg">Le log complet est dans les fichiers <code>logs/</code> du run. Ouvre l'Aide &gt; Logs pour les voir.</p>
        <a href="#/aide" class="v5-btn v5-btn--secondary v5-btn--sm">→ Ouvrir Aide &gt; Logs</a>
      `;
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

/* --- Events ----------------------------------------------------------- */

function _selectRun(container, runId) {
  _selectedRunId = runId;
  container.querySelectorAll("[data-run-id]").forEach((el) => {
    el.classList.toggle("is-selected", el.dataset.runId === runId);
  });
  _updateInspector();
}

function _rerender(container) {
  container.innerHTML = _renderHistorique();
  _bindEvents(container);
  _updateInspector();
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
      _rerender(container);
    });
  });
  // Recherche
  const searchInput = container.querySelector("[data-historique-search]");
  if (searchInput) {
    let debounce;
    searchInput.addEventListener("input", (ev) => {
      const value = String(ev.target.value || "");
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        _searchQuery = value;
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

function _onActionClick(ev) {
  // Tab clicks dans l'inspector
  const tabBtn = ev.target.closest && ev.target.closest("[data-historique-inspector-tab]");
  if (tabBtn) {
    _inspectorTab = tabBtn.dataset.historiqueInspectorTab;
    _updateInspector();
    return;
  }
  const target = ev.target.closest && ev.target.closest("[data-historique-action]");
  if (!target) return;
  const action = target.dataset.historiqueAction;
  const runId = target.dataset.runId;
  switch (action) {
    case "view-report":
      // PR future : page standalone #run/<id>. Pour l'instant : detail dans l'inspecteur seul.
      break;
    case "resume":
      if (runId) navigateTo(`/traitement#run-${encodeURIComponent(runId)}`);
      break;
    case "undo-apply":
      // Action dangereuse — modale de confirmation (cf feedback-cinesort-actions-dangereuses).
      if (window.confirm(`Annuler l'apply du run ${runId} ?\n\nCela va restaurer les fichiers à leur emplacement initial.\nRéversible tant qu'un nouvel apply n'a pas eu lieu.\n\n[Endpoint backend à brancher en PR future]`)) {
        // TODO: appeler apply/undo_apply(run_id)
        alert(`Action enregistrée. Endpoint backend non encore branché.`);
      }
      break;
    case "delete-run":
      // Action dangereuse — modale + retention 90j auto (spec 09 §5).
      if (window.confirm(`Supprimer le run ${runId} de l'historique ?\n\nLes fichiers vidéo ne seront pas touchés.\nSeul le log de ce run sera retiré.\n\nLes runs > 90 jours sont supprimés automatiquement.\n\n[Endpoint backend à brancher en PR future]`)) {
        // TODO: appeler runs/delete_run(run_id)
        alert(`Action enregistrée. Endpoint backend non encore branché.`);
      }
      break;
    default:
      break;
  }
}

/* --- Entrypoint ------------------------------------------------------- */

export async function initHistorique(container) {
  if (!container) return;
  // Restore persisted state
  _viewMode = _readString(STORAGE_KEY_VIEW, "timeline");
  _filterPeriod = _readString(STORAGE_KEY_PERIOD, "30d");
  if (!["timeline", "table"].includes(_viewMode)) _viewMode = "timeline";

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
    container.innerHTML = _renderError((res && (res.message || res.error)) || "Erreur de chargement.");
    _bindEvents(container);
    return;
  }

  const data = res.data || res;
  _runs = Array.isArray(data.runs_history) ? data.runs_history : [];
  _selectedRunId = _runs.length > 0 ? _runs[0].run_id : null;

  _rerender(container);
}

export function unmountHistorique() {
  document.removeEventListener("click", _onActionClick);
  _runs = [];
  _selectedRunId = null;
}
