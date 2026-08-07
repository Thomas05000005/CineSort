/* views/historique.js — Phase 3.4 / Phase 5 (spec 09-historique.md) — Vue Historique complete.
 *
 * Timeline groupée par jour (decision Thomas, spec §1). Source : runs_history
 * fourni par get_dashboard("latest") + detail enrichi par run/get_history_stats.
 *
 * Fonctionnalites :
 *  - Header avec stats agregees (N runs sur 30 jours)
 *  - Banner rétention (auto-suppression, duree lue dans les reglages, spec §5)
 *  - Filtres : Statut, Periode (avec Custom date picker), Type (plan / apply),
 *    recherche par run_id OU par nom de film
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
 *  - Modal "Vue par film" (issue #350) : list_films_with_history pour navigation
 *    cross-runs depuis le header de la vue
 *
 * Route cible : /historique (Phase 2-B PR #261) + /run/:id (standalone).
 *
 * Endpoints consommes (sprint orphelins #350) :
 *   library/list_films_with_history(limit) — overview films cross-runs
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost, cachedGetSettings } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { navigateTo } from "../core/router.js";
import { deriveRunStatus } from "../core/run-status.js";
import * as rightPanel from "../components/right-panel.js";
import { dangerConfirmModal, showModal, closeModal } from "../components/modal.js";
import { showToast } from "../components/toast.js";
import { buildEmptyState } from "../components/empty-state.js";

/* --- Helper EMPTY_STATE uniforme (iter11 4.3.x) ---------------------- */
/* Tous les messages "rien a afficher" de l'historique transitent par ce
 * helper afin d'utiliser le composant v2 .empty-state (styles unifies,
 * a11y aria-label, icone optionnelle) au lieu de <p class=historique-
 * empty-msg> inline. La classe .historique-empty-msg reste preservee
 * via la classe wrapper externe pour back-compat CSS absolue (cf
 * components.css L6371-6372 / web/shared). */
function _emptyInline(message, icon) {
  return `<div class="historique-empty-msg">${buildEmptyState({
    variant: "inline",
    icon: icon || "history",
    title: "",
    message,
  })}</div>`;
}

/* --- Labels FR centralises (iter11 LABELS_APPLY_HISTORIQUE) ---------- */
/* Dict: traduit les op_type/run_type bruts (anglais) en libelles FR
 * uniformes affiches dans la vue Historique. Cf carto iter11 4.5.1-3. */

const _OP_TYPE_LABELS_FR = Object.freeze({
  rename: "renommage",
  move: "déplacement",
  move_file: "déplacement",
  move_dir: "renommage dossier",
  quarantine: "quarantaine",
  delete_mark: "marquage suppression",
  mark_delete: "marquage suppression",
  other: "autre",
});

const _RUN_TYPE_LABELS_FR = Object.freeze({
  apply: "Application",
  undo: "Annulation",
  plan: "Plan",
});

function _opTypeLabelFr(opType) {
  const key = String(opType || "").toLowerCase();
  return _OP_TYPE_LABELS_FR[key] || (key ? key : "autre");
}

function _runTypeLabelFr(runType) {
  const key = String(runType || "").toLowerCase();
  return _RUN_TYPE_LABELS_FR[key] || _RUN_TYPE_LABELS_FR.plan;
}

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
// Revue post-merge 2026-08-03 : cette valeur etait lue dans le payload de
// `run/get_dashboard`, qui n'a JAMAIS emis `history_retention_days` (verifie sur
// les 3 chemins de retour de dashboard_support.get_dashboard). La banniere
// affichait donc « retention 90 jours » en dur pendant que le cron purgait
// reellement a J-<reglage> (app.py lit `settings.history_retention_days`) : un
// utilisateur regle sur 30 croyait ses runs de J-40 encore presents. La valeur
// vient desormais des reglages, seule source qui la porte.
const _RETENTION_DAYS_DEFAULT = 90;
let _retentionDays = _RETENTION_DAYS_DEFAULT;
let _scrollObserver = null;
// Fix audit 2026-05-25 (v1.5.3) Vague F : debounce search ID au niveau module
// pour pouvoir l'annuler dans unmountHistorique() (le let local survivait au
// demontage et declenchait un _rerender sur un container detache).
let _searchDebounceId = null;
// Fix audit 2026-05-25 (v1.5.3) Vague F : flag pour eviter le double attachement
// du listener document.click (initHistorique + initRunDetailPage attachaient
// tous les deux le meme _onActionClick, et un seul removeEventListener restait).
let _documentListenerAttached = false;
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

/* --- Status derivation ------------------------------------------------
 *
 * Revue post-merge 2026-08-03 — le court-circuit `if (run.status) return ...`
 * rendait MORTES toutes les lignes suivantes : `run/get_dashboard` emet toujours
 * un `status` NON VIDE (`str(run_row.get("status") or "PENDING")`,
 * dashboard_support.py). Consequences mesurees a l'ecran :
 *   - un run FAILED tombait dans le `default` de _statusClass et s'affichait en
 *     GRIS, comme un run sain ; le filtre « Error » ne le trouvait pas ;
 *   - les filtres « Applied » et « Partiel » ne matchaient jamais rien, alors
 *     que le payload porte bien applied_rows / total_rows ;
 *   - AWAITING_VALIDATION mappait vers `is-pending`, classe qui n'existe dans
 *     AUCUN CSS du depot -> statut affiche sans couleur.
 *
 * La regle vit desormais dans `core/run-status.js`, IMPORTEE ICI ET DANS
 * accueil.js : les deux ecrans decrivent le meme objet et ne peuvent plus se
 * contredire (la premiere version de ce correctif ne touchait qu'historique.js
 * et faisait lire ERROR ici, DONE sur l'accueil, pour le meme run).
 *
 * `run.undone` / `run.is_undo` / `run.type` ne sont emis par AUCUN payload :
 * l'undo n'insere pas de ligne dans la table `runs`. Les options de filtre
 * correspondantes sont retirees plus bas plutot que laissees inertes.
 */
function _deriveStatus(run) {
  return deriveRunStatus(run);
}

function _statusClass(status) {
  switch (status) {
    case "ERROR": return "is-error";
    case "PARTIAL": return "is-partial";
    case "APPLIED": return "is-applied";
    case "UNDONE": return "is-undone";
    case "CANCELLED": case "CANCEL": return "is-cancelled";
    // « En validation » demande une action de l'utilisateur : on reutilise la
    // teinte warning existante (.historique-run-status.is-partial). L'ancienne
    // valeur `is-pending` n'etait declaree dans aucun CSS -> statut incolore.
    case "AWAITING_VALIDATION": return "is-partial";
    default: return "is-done";
  }
}

function _runDate(run) {
  if (run.started_ts != null) return new Date(Number(run.started_ts) * 1000);
  if (run.started_at) return new Date(run.started_at);
  return null;
}

/* Revue post-merge 2026-08-03 : `run.is_undo` et `run.type` n'existent dans
 * aucun payload de `run/get_dashboard` — et ne peuvent pas exister, `undo_last_apply`
 * n'inserant aucune ligne dans la table `runs`. Le type « undo » etait donc
 * inatteignable ; il a ete retire du filtre Type et du resume d'en-tete. */
function _runType(run) {
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

// Fix bug audit : la recherche par nom de film ne fonctionnait QUE sur les runs
// deja consultes (cache rempli par _ensureHistoryStats au clic). Resultat : faux
// negatif silencieux. Solution : prefetch les films pour tous les runs non encore
// cachees lors d'une recherche, puis re-render pour appliquer le filtre.
let _prefetchInflight = false;
async function _prefetchFilmsForSearch(container) {
  if (_prefetchInflight) return;
  if (!_searchQuery || !_searchQuery.trim()) return;
  const missing = _runs.filter((r) => r && r.run_id && !_filmsCacheByRun.has(r.run_id));
  if (missing.length === 0) return;
  _prefetchInflight = true;
  try {
    // Sequentiel pour ne pas saturer le rate-limiter backend (5/60s).
    for (const r of missing) {
      if (!_searchQuery || !_searchQuery.trim()) break; // user a vide la recherche
      try {
        await _ensureHistoryStats(r.run_id);
      } catch (_e) { /* noop par run */ }
    }
  } finally {
    _prefetchInflight = false;
    // Re-render uniquement si le container existe encore.
    if (container && container.isConnected) {
      try { _rerender(container); } catch (_e) { /* noop */ }
    }
  }
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

/** Lit `history_retention_days` dans les reglages (cache memoire partage).
 *  Retourne le defaut backend (90) si le reglage est absent ou invalide. */
async function _fetchRetentionDays() {
  try {
    const res = await cachedGetSettings();
    if (!res || !res.data || typeof res.data !== "object" || res.data.ok === false) {
      return _RETENTION_DAYS_DEFAULT;
    }
    const settings = res.data.data || res.data || {};
    const days = Number(settings.history_retention_days);
    return Number.isFinite(days) && days > 0 ? days : _RETENTION_DAYS_DEFAULT;
  } catch {
    return _RETENTION_DAYS_DEFAULT;
  }
}

function _renderRetentionBanner() {
  const days = _retentionDays || _RETENTION_DAYS_DEFAULT;
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - days);
  const cutoffStr = cutoffDate.toLocaleDateString("fr-FR");
  // Fix audit 2026-05-24 : ajout CTA "Modifier" -> ancre #retention dans
  // Parametres pour permettre a l'utilisateur de changer la duree de retention
  // sans avoir a chercher dans les onglets.
  return `
    <div class="historique-retention-banner" role="note">
      <span class="historique-retention-banner-icon" aria-hidden="true">ℹ️</span>
      <span>Les runs antérieurs au <strong>${escapeHtml(cutoffStr)}</strong> (rétention ${days} jours) sont supprimés automatiquement.</span>
      <a href="#/parametres#retention" class="historique-retention-banner-cta">Modifier</a>
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

/* Revue post-merge 2026-08-03 : les options « Undone » (filtre Statut) et
 * « Undo » (filtre Type) ont ete retirees. Un undo n'insere aucune ligne dans la
 * table runs et le payload de run/get_dashboard ne porte ni undone, ni is_undo,
 * ni type : les deux filtres etaient morts par construction et repondaient
 * toujours « Aucun run ne correspond aux filtres actuels ». */
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
            <!-- Fix audit 2026-05-24 : ajout des statuts manquants (partial / awaiting_validation) -->
            <option value="partial" ${_filterStatus === "partial" ? "selected" : ""}>Partiel</option>
            <option value="awaiting_validation" ${_filterStatus === "awaiting_validation" ? "selected" : ""}>En validation</option>
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
          <button type="button" class="v5-btn v5-btn--ghost"
                  data-historique-films-history-open
                  title="Vue par film : historique cross-runs">🎬</button>
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
  const typeLabel = _runTypeLabelFr(type);
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
        ${_emptyInline("Aucun run ne correspond aux filtres actuels.", "history")}
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
        ${_emptyInline("Aucun run ne correspond aux filtres actuels.", "history")}
      </section>
    `;
  }
  const rows = runs.map((r) => {
    const d = _runDate(r);
    const status = _deriveStatus(r);
    const total = Number(r.total_rows || 0);
    const type = _runType(r);
    const typeLabel = _runTypeLabelFr(type);
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
  const errors = runs.filter((r) => _deriveStatus(r) === "ERROR").length;
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
  // Revue post-merge 2026-08-03 : le compteur « N undo » etait fige a 0 par
  // construction (aucun run d'undo n'existe en base). Remplace par le nombre de
  // runs en erreur, qui lui est reellement derivable du payload.
  return {
    summary: `${totalRuns} runs · ${applies} apply · ${errors} en erreur · sur ${periodLabel}`,
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
        html: _emptyInline("Sélectionnez un run dans la liste pour voir son détail.", "inbox"),
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
          ${isApply && status !== "UNDONE" ? `<button type="button" class="v5-btn v5-btn--ghost v5-btn--danger" data-historique-action="undo-apply" data-run-id="${escapeHtml(selectedRun.run_id)}">↺ Annuler l'apply</button>` : (isApply && status === "UNDONE" ? `<span class="historique-inspector-disabled">↺ Déjà annulé</span>` : "")}
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
  // Map vers Approuvé/Rejeté/Reporté/Doublon/Suppression.
  const dec = String(film.decision || film.status || "").toLowerCase();
  // H8 (2026-07-15) : la DÉCISION utilisateur explicite (tri-état
  // accepted/approved/rejected/deferred exposé par history_support.py depuis
  // validation.json) PRIME sur le tier qualité. Avant, `tier === "reject"` était
  // testé AVANT de lire `film.decision` : un film au tier `reject` mais
  // explicitement ACCEPTÉ affichait encore « Rejeté ». On ne retombe sur le tier
  // (ni sur la détection doublon/suppression) QUE si `decision` est vide.
  if (dec === "accepted" || dec === "approved") return { label: "Approuvé", cls: "is-approved" };
  if (dec === "rejected") return { label: "Rejeté", cls: "is-rejected" };
  if (dec === "deferred") return { label: "Reporté", cls: "is-deferred" };
  const tier = String(film.tier || "").toLowerCase();
  if (tier === "reject") return { label: "Rejeté", cls: "is-rejected" };
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
    return _emptyInline("Aucun film associé à ce run.", "film");
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

// Fix audit 2026-05-25 (v1.5.3) Vague F : separer dossier/fichier pour ne
// pas suggerer un renommage du fichier video. apply_core ne renomme JAMAIS
// les fichiers video, seul le dossier parent est renomme/deplace.
function _opLabel(op) {
  const t = String(op.op_type || "").toLowerCase();
  const src = String(op.src_path || "");
  const dst = String(op.dst_path || "");
  const srcShort = src.split(/[\\/]/).pop() || src;
  const dstShort = dst.split(/[\\/]/).pop() || dst;
  if (t === "rename" || t === "move_dir") {
    // Renommage de dossier : le fichier video conserve son nom.
    return { icon: "→", text: `Dossier renommé : ${srcShort} → ${dstShort} (fichier conservé)` };
  }
  if (t === "move" || t === "move_file") {
    // Deplacement de fichier : nom conserve si srcShort == dstShort, sinon
    // c'est un renommage TV (episodes).
    if (srcShort === dstShort) {
      return { icon: "→", text: `Vidéo déplacée : ${srcShort} (nom conservé)` };
    }
    return { icon: "→", text: `Vidéo renommée (TV) : ${srcShort} → ${dstShort}` };
  }
  if (t === "quarantine") return { icon: "⚠", text: `Quarantaine bucket _review/ — ${srcShort}` };
  if (t === "delete_mark" || t === "mark_delete") return { icon: "🗑", text: `Marqué suppression — ${srcShort}` };
  // Fallback FR : libelle traduit au lieu d'op_type brut anglais (iter11).
  const labelFr = _opTypeLabelFr(op.op_type) || "Opération";
  const labelCap = labelFr.charAt(0).toUpperCase() + labelFr.slice(1);
  return { icon: "•", text: `${labelCap} : ${srcShort}${dst ? " → " + dstShort : ""}` };
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
      ${applied > 0 ? _emptyInline("Détail des opérations non disponible pour ce run.", "history") : _emptyInline("Aucun apply effectué.", "history")}
    `;
  }
  // Compter par type
  const counts = ops.reduce((acc, o) => {
    const t = String(o.op_type || "other").toLowerCase();
    acc[t] = (acc[t] || 0) + 1;
    return acc;
  }, {});
  const countersHtml = Object.entries(counts).map(([t, n]) => `<span class="historique-apply-counter">${escapeHtml(_opTypeLabelFr(t))}: <strong>${n}</strong></span>`).join("");
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
      ${dupGroups > 0 ? `${_emptyInline("Détail des groupes non disponible pour ce run.", "history")}<a href="#/doublons" class="v5-btn v5-btn--secondary v5-btn--sm">→ Ouvrir la vue Doublons</a>` : _emptyInline("Aucun doublon dans ce run.", "history")}
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

/** Ultra-audit 2026-08-03 (N29) — chemin du journal sur disque.
 *  `run_dir` vient de runs_history (dashboard_support.py) ; on n'y ajoute le
 *  nom de fichier qu'avec le separateur deja present dans le chemin. */
function _uiLogPath(runDir) {
  const dir = String(runDir || "").trim();
  if (!dir) return "";
  const sep = dir.includes("\\") ? "\\" : "/";
  return `${dir.replace(/[\\/]+$/, "")}${sep}ui_log.txt`;
}

function _renderLogViewer(runStats, runId, runDir) {
  const lines = Array.isArray(runStats.log_lines) ? runStats.log_lines : [];
  if (lines.length === 0) {
    // Ultra-audit 2026-08-03 (N29) : le journal live n'existe qu'en memoire du
    // process (api._runs, alimente au demarrage du run) ; get_status repond
    // `logs: []` pour tout run d'une session anterieure et get_history_stats
    // n'a jamais porte `log_lines`. « Aucun log disponible » etait donc exact
    // mais laissait croire que le journal n'existait plus, et le bouton
    // « Recharger » ne pouvait rien y changer. Le fichier, lui, est bien sur
    // disque : on dit pourquoi c'est vide et ou aller le lire.
    const logPath = _uiLogPath(runDir);
    const message = logPath
      ? `Aucun log en mémoire pour ce run. Le journal live n'est conservé que par la session qui a lancé le run : il est vide après un redémarrage de CineSort. Le journal complet reste sur disque : ${logPath}`
      : "Aucun log en mémoire pour ce run. Le journal live n'est conservé que par la session qui a lancé le run : il est vide après un redémarrage de CineSort. Le journal complet reste sur disque, dans le dossier du run (ui_log.txt).";
    return `
      <div class="historique-log-viewer-actions">
        <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-historique-action="reload-log" data-run-id="${escapeHtml(runId)}">↻ Recharger</button>
      </div>
      ${_emptyInline(message, "history")}
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
    // N29 : `run` vient de runs_history et porte `run_dir` — runStats (payload
    // get_history_stats) ne l'a pas.
    default:        return _renderLogViewer(runStats, runId, run.run_dir);
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
    // Fix audit 2026-05-24 : apiPost retourne {status, data}. res.ok = undefined
    // -> la condition ancienne `res.ok !== false` etait TOUJOURS vraie meme
    // si le backend retournait {ok: false, message: "..."}. Lire res.data.ok.
    const _payload = (res && res.data) || res || {};
    if (res && _payload.ok !== false) {
      // Le payload est `{ok, run: {...}}` ou `{ok, ...}` selon impl.
      const data = _payload.run || _payload || {};
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
    // Fix audit 2026-05-25 (v1.5.3) Vague F : guard isConnected pour eviter
    // _rerender sur un container detache du DOM (apres unmount). On disconnecte
    // l'observer immediatement pour libérer la reference.
    if (!container || !container.isConnected) {
      if (_scrollObserver) { try { _scrollObserver.disconnect(); } catch { /* noop */ } _scrollObserver = null; }
      return;
    }
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
  // Fix bug audit : validation si _customPeriodTo < _customPeriodFrom. Auto-swap
  // pour eviter une liste vide silencieuse + toast informatif a l'utilisateur.
  const _swapDatesIfInverted = () => {
    if (_customPeriodFrom && _customPeriodTo && _customPeriodTo < _customPeriodFrom) {
      const oldFrom = _customPeriodFrom;
      _customPeriodFrom = _customPeriodTo;
      _customPeriodTo = oldFrom;
      try {
        showToast({ type: "info", text: "Date de fin avant date de début — dates inversées automatiquement." });
      } catch (_e) { /* noop si toast indisponible */ }
    }
  };
  const fromInput = container.querySelector("[data-historique-custom-from]");
  if (fromInput) {
    fromInput.addEventListener("change", (ev) => {
      _customPeriodFrom = String(ev.target.value || "") || null;
      _swapDatesIfInverted();
      _visibleCount = BATCH_SIZE;
      _rerender(container);
    });
  }
  const toInput = container.querySelector("[data-historique-custom-to]");
  if (toInput) {
    toInput.addEventListener("change", (ev) => {
      _customPeriodTo = String(ev.target.value || "") || null;
      _swapDatesIfInverted();
      _visibleCount = BATCH_SIZE;
      _rerender(container);
    });
  }
  // Recherche
  const searchInput = container.querySelector("[data-historique-search]");
  if (searchInput) {
    // Fix audit 2026-05-25 (v1.5.3) Vague F : _searchDebounceId au niveau module
    // (cf declaration en tete) pour pouvoir annuler le setTimeout dans
    // unmountHistorique() — sinon le _rerender s'execute sur un container detache.
    searchInput.addEventListener("input", (ev) => {
      const value = String(ev.target.value || "");
      if (_searchDebounceId) clearTimeout(_searchDebounceId);
      _searchDebounceId = setTimeout(() => {
        _searchDebounceId = null;
        _searchQuery = value;
        _visibleCount = BATCH_SIZE;
        _rerender(container);
        // Restore focus dans la search box.
        const next = container.querySelector("[data-historique-search]");
        if (next) { next.focus(); next.setSelectionRange(value.length, value.length); }
        // Fix bug audit : prefetch films pour tous les runs non caches pour
        // que la recherche par nom de film fonctionne meme sur runs non consultes.
        if (value && value.trim()) _prefetchFilmsForSearch(container);
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
  // Actions (depuis l'inspector ou ailleurs : delegation globale).
  // Fix audit 2026-05-25 (v1.5.3) Vague F : flag _documentListenerAttached pour
  // eviter le double attachement (le rerender + initRunDetailPage attachaient
  // tous deux le meme handler, et un seul removeEventListener n'en detachait
  // qu'une seule reference).
  if (!_documentListenerAttached) {
    document.addEventListener("click", _onActionClick);
    _documentListenerAttached = true;
  }
  // Retry
  const retryBtn = container.querySelector("[data-historique-retry]");
  if (retryBtn) retryBtn.addEventListener("click", () => initHistorique(container));
  // Issue #350 : ouverture de la modale "Vue par film" (list_films_with_history).
  container.querySelectorAll("[data-historique-films-history-open]").forEach((btn) => {
    btn.addEventListener("click", () => _openFilmsHistoryModal());
  });
}

/* --- Sprint orphelins #350 : modale "Vue par film" ---
 *
 * Liste les films du dernier run avec un resume cross-runs (nombre de runs ou
 * apparait le film, dernier statut, derniere modif). Click sur un film -> page
 * /film/:id (deja existante).
 *
 * Pas un onglet additionnel dans l'inspecteur car list_films_with_history n'est
 * pas scope-run mais cross-runs : c'est une vue alternative globale, mieux
 * placee dans une modale invoquable depuis le header.
 */

const FILMS_HISTORY_MODAL_ID = "historiqueFilmsHistoryModal";

async function _openFilmsHistoryModal() {
  // Construire la modale skeleton puis fetch async.
  showModal({
    title: "🎬 Films avec historique (cross-runs)",
    body: `
      <div class="historique-films-history" data-historique-films-history-body>
        <p class="historique-films-history-loading">Chargement…</p>
      </div>
    `,
    actions: [
      { label: "Fermer", cls: "", onClick: () => {} },
    ],
  });

  try {
    const res = await apiPost("library/list_films_with_history", { limit: 100 });
    const data = res && res.data ? res.data : res;
    if (!data || data.ok === false) {
      throw new Error((data && (data.message || data.error)) || "Echec chargement.");
    }
    const films = Array.isArray(data.films) ? data.films : [];
    _renderFilmsHistoryModalBody(films);
  } catch (err) {
    const body = document.querySelector("[data-historique-films-history-body]");
    if (body) {
      body.innerHTML = `<p class="historique-films-history-error">Erreur : ${escapeHtml(String(err && err.message ? err.message : err))}</p>`;
    }
  }
}

function _renderFilmsHistoryModalBody(films) {
  const body = document.querySelector("[data-historique-films-history-body]");
  if (!body) return;
  if (!films.length) {
    body.innerHTML = `<p class="historique-films-history-empty">Aucun film avec historique disponible.</p>`;
    return;
  }
  // Shape backend (cinesort.domain.film_history.list_films_overview) :
  //   { film_id, title, year, edition, score, tier, row_id }
  const itemsHtml = films.map((f) => {
    const filmId = String(f.film_id || f.row_id || "");
    const title = String(f.title || f.proposed_title || "Sans titre");
    const year = f.year ? ` (${f.year})` : "";
    const edition = f.edition ? ` · ${f.edition}` : "";
    const score = (f.score != null && f.score !== 0) ? `${Math.round(Number(f.score))}/100` : "—";
    const tier = String(f.tier || "").toLowerCase();
    const tierBadge = tier
      ? `<span class="historique-films-history-tier historique-films-history-tier--${escapeHtml(tier)}">${escapeHtml(tier)}</span>`
      : "—";
    const linkHref = filmId ? `#/film/${encodeURIComponent(filmId)}` : null;
    const titleCell = linkHref
      ? `<a href="${escapeHtml(linkHref)}" class="historique-films-history-link">${escapeHtml(title + year + edition)}</a>`
      : escapeHtml(title + year + edition);
    return `
      <tr class="historique-films-history-row">
        <td class="historique-films-history-title">${titleCell}</td>
        <td class="historique-films-history-score">${escapeHtml(score)}</td>
        <td class="historique-films-history-tier-cell">${tierBadge}</td>
      </tr>
    `;
  }).join("");
  body.innerHTML = `
    <p class="historique-films-history-summary">
      ${films.length} film${films.length > 1 ? "s" : ""} du dernier run. Cliquez sur un titre pour voir la timeline complète cross-runs.
    </p>
    <div class="historique-films-history-tablewrap">
      <table class="historique-films-history-table">
        <thead>
          <tr>
            <th>Titre</th>
            <th>Score</th>
            <th>Tier</th>
          </tr>
        </thead>
        <tbody>${itemsHtml}</tbody>
      </table>
    </div>
  `;
  // Cliquer sur un lien doit fermer la modale puis naviguer (sinon le modal
  // reste ouvert au-dessus de la page film).
  body.querySelectorAll("[href^='#/film/']").forEach((a) => {
    a.addEventListener("click", () => {
      try { closeModal(); } catch (_e) { /* noop */ }
      // Le navigate hash-change naturel se charge du reste.
    });
  });
}

/* Politique COMPENSATE (arbitrage Thomas, 2026-08-06).
 *
 * L'undo est atomique par defaut : si UN SEUL fichier a ete modifie depuis
 * l'apply, il refuse TOUT et ne restaure rien. Mesure : 1 fichier touche a la
 * main sur 5 -> 0 sur 5 restaures.
 *
 * Le backend sait pourtant faire autrement — `atomic=false` restaure les
 * fichiers intacts et ignore les autres (cf. `_execute_undo_ops`). Ce mode
 * n'etait atteignable qu'en REST BRUT : ce site forcait `atomic: true`, et
 * `traitement.js` l'omet (le defaut vaut True). L'utilisateur n'avait donc
 * AUCUN moyen, depuis l'application, de recuperer ses quatre films intacts.
 *
 * On propose desormais le repli, derriere la modale destructive : liste des
 * fichiers concernes, consequence explicite, et delai derive du nombre
 * (regle projet n3, cf. `gradedCountdownSeconds`).
 */
function _proposerUndoPartiel(runId, preverify) {
  const details = Array.isArray(preverify && preverify.mismatch_details)
    ? preverify.mismatch_details
    : [];
  const restaurables = Number((preverify && preverify.safe_count) || 0);
  const modifies = Number((preverify && preverify.hash_mismatch_count) || details.length || 0);

  // Rien a proposer : le repli ne restaurerait aucun fichier. Le dire est plus
  // honnete que d'ouvrir une modale destructive dont la seule issue est
  // « 0 restaure » — cela userait la confirmation quand elle doit porter.
  if (restaurables <= 0) {
    showToast({
      type: "error",
      text: `Annulation impossible : les ${modifies} fichier(s) ont été modifiés depuis l'apply, aucun n'est restaurable.`,
    });
    return;
  }

  dangerConfirmModal({
    title: `Restaurer ${restaurables} film(s) sur ${restaurables + modifies} ?`,
    // `items` liste les fichiers MODIFIES : c'est ce que l'utilisateur doit
    // savoir, puisque ce sont les seuls qui ne bougeront pas.
    items: details.map((d) => String((d && d.dst_path) || "").split(/[\\/]/).pop()).filter(Boolean),
    // Le delai se calibre sur ce qui est REELLEMENT DEPLACE, donc sur
    // `restaurables` — pas sur `modifies`, que la premiere version passait ici.
    // Se tromper de nombre revenait a graduer la confirmation sur les fichiers
    // qu'on ne touche PAS.
    itemCount: restaurables,
    // `countdownSeconds` EXPLICITE, et pas seulement `itemCount` : la derivation
    // automatique par la modale vit dans une AUTRE branche (regle n3 unifiee).
    // Tant qu'elle n'est pas fusionnee, `dangerConfirmModal` ignore `itemCount`
    // et retombe sur 0 seconde — une restauration de 200 films serait alors
    // confirmable au premier clic. Une PR ne doit pas dependre d'une autre pour
    // etre correcte.
    //
    // La formule REPLIQUE `gradedCountdownSeconds` a l'identique, et ce n'est pas
    // cosmetique : une valeur explicite l'emporte sur la derivation. Un simple
    // `restaurables > 50 ? 3 : 0` aurait donc rendu 0 s la ou la regle partagee
    // rend 1 s (entre 31 et 50 elements) — et cet ecart aurait SURVECU a la
    // fusion, en reintroduisant la convention par appelant que l'autre branche
    // supprime justement.
    //
    // A RETIRER une fois les deux branches sur `main` : `itemCount` suffira, et
    // la regle ne vivra plus qu'a un seul endroit.
    countdownSeconds: (() => {
      const n = Number(restaurables) || 0;
      if (n <= 30) return 0;
      if (n > 50) return 3;
      return Math.max(0, Math.min(3, Math.round(((n - 30) / (100 - 30)) * 3)));
    })(),
    consequence:
      `${modifies} fichier(s) ont été modifiés depuis l'apply et seront LAISSÉS EN PLACE. `
      + `Les ${restaurables} autres seront remis à leur emplacement d'origine. `
      + "Cette opération déplace des fichiers sur le disque.",
    confirmLabel: `Restaurer les ${restaurables} intacts`,
    cancelLabel: "Ne rien faire",
    onConfirm: () => _doUndoApply(runId, { atomic: false }),
  });
}

// Garde de re-entrance de l'undo.
//
// La modale initiale passe `closeBeforeConfirm: true` : sans cela, la modale de
// repli s'ouvrait ALORS QUE la premiere etait encore active — `dangerConfirmModal`
// n'appelle `close()` qu'apres resolution de `onConfirm`. La fermeture differee
// de la premiere restaurait alors le focus sur son declencheur, situe DERRIERE la
// seconde modale, qui perdait le focus qu'elle venait de prendre.
//
// Fermer tot a une contrepartie, que la documentation de `dangerConfirmModal`
// enonce : le declencheur redevient cliquable pendant l'appel reseau. Sans cette
// garde, un double-clic lancerait deux annulations concurrentes sur le meme run.
// L'appel de repli (`atomic: false`) n'est PAS bloque : il part apres le retour
// du premier, donc apres la remise a zero du drapeau.
let _undoEnVol = false;

async function _doUndoApply(runId, options) {
  if (_undoEnVol) return;
  _undoEnVol = true;
  const atomic = !(options && options.atomic === false);
  try {
    const res = await apiPost("run/undo_last_apply", { run_id: runId, dry_run: false, atomic });
    // Fix audit 2026-05-24 : res.ok = undefined (apiPost retourne {status, data}).
    const _payload = (res && res.data) || res || {};

    // Refus atomique : le backend n'a RIEN touche et dit pourquoi. C'est le seul
    // moment ou proposer le repli a du sens — apres, le disque a deja bouge.
    if (atomic && _payload.status === "ABORTED_HASH_MISMATCH") {
      _proposerUndoPartiel(runId, _payload.preverify);
      return;
    }

    // Un undo qui n'a restaure AUCUN fichier n'est pas un succes : le backend le
    // dit desormais (`UNDONE_NONE`) et laisse le batch annulable.
    if (_payload.status === "UNDONE_NONE") {
      showToast({ type: "warn", text: _payload.message || "Aucun film n'a été restauré." });
      await _refreshRuns();
      return;
    }

    if (res && _payload.ok !== false) {
      const _c = _payload.counts || {};
      const _done = Number(_c.done || 0);
      const _skipped = Number(_c.skipped || 0);
      // « Apply annule. Fichiers restaures. » se lisait comme un succes COMPLET,
      // y compris quand un film sur cinq avait ete laisse en place.
      showToast({
        type: "success",
        text: _skipped > 0
          ? `Apply annulé : ${_done} film(s) restauré(s), ${_skipped} laissé(s) en place.`
          : `Apply annulé. ${_done} fichier(s) restauré(s).`,
      });
      // Ultra-audit 2026-08-03 (N01) : app.js ecoute `cinesort:undo` pour
      // recharger les compteurs de sidebar (#92 quick win #2). L'evenement
      // n'etait plus emis par personne depuis la migration ESM.
      try { window.dispatchEvent(new CustomEvent("cinesort:undo")); }
      catch (e) { console.warn("[historique] dispatch cinesort:undo", e); }
      // Refresh dashboard + cache + UI.
      _historyStatsCache.delete(runId);
      await _refreshRuns();
    } else {
      const msg = _payload.message || _payload.error || "Échec de l'annulation.";
      showToast({ type: "error", text: msg });
    }
  } catch (err) {
    showToast({ type: "error", text: `Erreur : ${err && err.message || err}` });
  } finally {
    _undoEnVol = false;
  }
}

async function _doDeleteRun(runId) {
  try {
    const res = await apiPost("run/delete_run", { run_id: runId });
    // Fix audit 2026-05-24 : voir _doUndoApply pour le pattern res.data.ok.
    const _payload = (res && res.data) || res || {};
    if (res && _payload.ok !== false) {
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
      const msg = _payload.message || _payload.error || "Échec de la suppression.";
      showToast({ type: "error", text: msg });
    }
  } catch (err) {
    showToast({ type: "error", text: `Erreur : ${err && err.message || err}` });
  }
}

async function _refreshRuns() {
  try {
    // Le reglage de retention ne vient PAS de get_dashboard (il ne l'emet pas) :
    // cachedGetSettings sert un cache memoire, donc aucun aller-retour reseau
    // supplementaire dans le cas courant.
    const [res, retentionDays] = await Promise.all([
      apiPost("run/get_dashboard", { run_id: "latest" }),
      _fetchRetentionDays(),
    ]);
    // Fix audit 2026-05-24 : voir _doUndoApply.
    const data = (res && res.data) || res || {};
    if (res && data.ok !== false) {
      _runs = Array.isArray(data.runs_history) ? data.runs_history : [];
      _retentionDays = retentionDays;
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
      // Fix audit 2026-06-07 UX medium : cancelLabel par defaut "Annuler" vs
      // confirmLabel "Annuler l'apply" cree une ambiguite cognitive (deux
      // boutons "Annuler" aux sens opposes). Pattern traitement.js "Garder
      // le run" => "Garder l'apply".
      dangerConfirmModal({
        title: `Annuler l'apply du run ${runId} ?`,
        items: [`Run ${runId}`],
        consequence:
          "Cela va restaurer les fichiers à leur emplacement initial. " +
          "Réversible tant qu'un nouvel apply n'a pas eu lieu.",
        countdownSeconds: 3,
        confirmLabel: "✗ Annuler l'apply",
        cancelLabel: "Garder l'apply",
        // Cette confirmation peut en ouvrir une SECONDE (le repli partiel, quand
        // le backend refuse l'undo atomique). Par defaut `dangerConfirmModal`
        // ne se ferme qu'apres resolution de `onConfirm` : la modale de repli
        // s'ouvrirait donc par-dessus celle-ci, et la fermeture differee de
        // celle-ci renverrait ensuite le focus sur le bouton situe DERRIERE.
        // On ferme donc AVANT ; la re-entrance est gardee par `_undoEnVol`.
        closeBeforeConfirm: true,
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
  // Attach action click delegation (idempotent grace au flag module-level).
  // Fix audit 2026-05-25 (v1.5.3) Vague F : cf _bindEvents — le flag empeche
  // le double attachement avec initHistorique().
  if (!_documentListenerAttached) {
    document.addEventListener("click", _onActionClick);
    _documentListenerAttached = true;
  }
}

export function unmountRunDetailPage() {
  // Fix audit 2026-05-25 (v1.5.3) Vague F : flag pour ne detacher qu'une fois.
  if (_documentListenerAttached) {
    document.removeEventListener("click", _onActionClick);
    _documentListenerAttached = false;
  }
  // M19 (audit ultra 2026-07-13) : idem unmountHistorique — purge des caches par
  // run_id (voir la note detaillee la-bas). La page standalone /run/:id partage
  // _historyStatsCache / _filmsCacheByRun avec la timeline ; sans reset ici, un
  // aller-retour /run/:id -> /historique servait un detail perime. Refetch au
  // remontage via _ensureHistoryStats.
  _historyStatsCache.clear();
  _filmsCacheByRun.clear();
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
  let retentionDays = _RETENTION_DAYS_DEFAULT;
  try {
    // En parallele du dashboard : le reglage de retention n'est PAS dans ce
    // payload (cf _fetchRetentionDays), et un echec de sa lecture ne doit pas
    // faire passer la vue en ecran d'erreur -> _fetchRetentionDays ne rejette
    // jamais, elle retombe sur le defaut.
    [res, retentionDays] = await Promise.all([
      apiPost("run/get_dashboard", { run_id: "latest" }, { signal }),
      _fetchRetentionDays(),
    ]);
  } catch (err) {
    if (err && err.name === "AbortError") return;
    container.innerHTML = _renderError(err ? String(err.message || err) : "Erreur réseau");
    _bindEvents(container);
    return;
  }
  // Fix audit 2026-05-24 : voir pattern res.data.ok dans _doUndoApply.
  const _initPayload = (res && res.data) || res || {};
  if (!res || _initPayload.ok === false) {
    container.innerHTML = _renderError(_initPayload.message || _initPayload.error || "Erreur de chargement.");
    _bindEvents(container);
    return;
  }

  const data = res.data || res;
  _runs = Array.isArray(data.runs_history) ? data.runs_history : [];
  _retentionDays = retentionDays;
  _selectedRunId = _runs.length > 0 ? _runs[0].run_id : null;

  _rerender(container);
  // Charge le detail du run selectionne par defaut.
  if (_selectedRunId) _fetchAndUpdate(_selectedRunId);
}

export function unmountHistorique() {
  // Fix audit 2026-05-25 (v1.5.3) Vague F : flag _documentListenerAttached pour
  // ne detacher qu'une fois (vs double attachement avec initRunDetailPage).
  if (_documentListenerAttached) {
    document.removeEventListener("click", _onActionClick);
    _documentListenerAttached = false;
  }
  _detachScrollObserver();
  // Fix audit 2026-05-25 (v1.5.3) Vague F : annuler le debounce search en cours,
  // sinon le setTimeout survivait au demontage et declenchait _rerender sur un
  // container detache du DOM.
  if (_searchDebounceId) {
    clearTimeout(_searchDebounceId);
    _searchDebounceId = null;
  }
  // M19 (audit ultra 2026-07-13) : purge des caches par run_id au demontage.
  // _historyStatsCache / _filmsCacheByRun sont module-level et n'etaient invalides
  // que par delete_run / undo / bouton Recharger. Sans reset au unmount, un
  // remontage ulterieur (autre run selectionne, apply survenu entre-temps)
  // reaffichait des stats / films PERIMES d'un run different. Sur-invalider est
  // sans danger : tout remontage refetch via _ensureHistoryStats.
  _historyStatsCache.clear();
  _filmsCacheByRun.clear();
  _runs = [];
  _selectedRunId = null;
}
