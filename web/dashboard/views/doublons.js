/* views/doublons.js — Phase 3.3 (spec 01-doublons.md).
 *
 * Vue Doublons refondue : liste des groupes de doublons avec cartes A/B
 * (codec/source/taille/score) + alertes humanisees + actions.
 *
 * Hors scope cette PR (itererations futures) :
 *   - Modal Comparateur 3 onglets (Aperçu / Frames / Audio) → ouvre la
 *     vue legacy lib-duplicates.js en attendant
 *   - Drag rectangulaire de selection bulk
 *   - Endpoint queue_perceptual_analyses + mark_duplicate_winner
 *
 * Route : /doublons (a creer dans app.js).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { labelsForFlags, countBySeverity } from "../core/alert-labels.js";
import { openPerceptualModal } from "../components/perceptual-modal.js";

let _state = null;
let _container = null;

function _initState() {
  return {
    groups: [],
    sizeSavingsTotal: 0,
    decidedCount: 0,
    pendingCount: 0,
    selectedGroupKey: null,
    runId: null,
    loading: true,
    error: null,
    filter: "all", // all | conflict | pending | decided
  };
}

/* --- Formatters --- */

function _fmtSize(bytes) {
  const b = Number(bytes) || 0;
  if (b <= 0) return "—";
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} Mo`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(1)} Go`;
}

function _groupKey(group) {
  return String(group.key || group.title || "") + "::" + String(group.year || "");
}

/* --- Renderers --- */

function _renderSkeleton() {
  return `
    <section class="doublons-view doublons-view--loading" aria-busy="true">
      <div class="doublons-header"><div class="v5-skeleton doublons-title-skel"></div></div>
      <div class="doublons-section v5-skeleton doublons-section-skel"></div>
    </section>
  `;
}

function _renderError(msg) {
  return `
    <section class="doublons-view doublons-view--error" role="alert">
      <h2>La vue Doublons n'a pas pu se charger.</h2>
      <p>${escapeHtml(msg || "Erreur inconnue")}</p>
      <button type="button" class="v5-btn v5-btn--primary" data-doublons-retry>Réessayer</button>
    </section>
  `;
}

function _renderHeader() {
  const n = _state.groups.length;
  const savings = _fmtSize(_state.sizeSavingsTotal);
  return `
    <header class="doublons-header">
      <div class="doublons-header-top">
        <h1 class="doublons-title">Doublons</h1>
        <p class="doublons-summary">
          <strong>${n}</strong> groupe${n > 1 ? "s" : ""} ·
          <strong>${escapeHtml(savings)}</strong> récupérable${savings === "—" ? "" : "s"}
        </p>
      </div>
      <div class="doublons-toolbar" role="toolbar" aria-label="Actions Doublons">
        <button type="button" class="v5-btn v5-btn--secondary" data-doublons-action="refresh">↻ Actualiser</button>
        <select class="v5-input doublons-filter" data-doublons-filter aria-label="Filtrer">
          <option value="all"${_state.filter === "all" ? " selected" : ""}>Tous (${n})</option>
          <option value="conflict"${_state.filter === "conflict" ? " selected" : ""}>Conflits seulement</option>
          <option value="pending"${_state.filter === "pending" ? " selected" : ""}>À décider (${_state.pendingCount})</option>
          <option value="decided"${_state.filter === "decided" ? " selected" : ""}>Décidés (${_state.decidedCount})</option>
        </select>
        <button type="button" class="v5-btn v5-btn--ghost" data-doublons-action="legacy">→ Mode workflow legacy</button>
      </div>
    </header>
  `;
}

function _renderEmpty() {
  return `
    <div class="doublons-empty">
      <p class="doublons-empty-icon" aria-hidden="true">✨</p>
      <h2>Aucun doublon détecté</h2>
      <p>Lance un scan pour analyser ta bibliothèque, ou actualise pour relire l'état actuel.</p>
    </div>
  `;
}

function _renderGroupCard(group) {
  const comparison = group.comparison || {};
  const winner = String(comparison.winner || "").toLowerCase();
  const totalFiles = (group.rows && group.rows.length) || (group.files && group.files.length) || 2;
  const totalSize = (Number(comparison.file_a_size) || 0) + (Number(comparison.file_b_size) || 0);
  const title = group.title || "Sans titre";
  const year = group.year ? `(${group.year})` : "";
  const fileA = comparison.file_a_name || "Fichier A";
  const fileB = comparison.file_b_name || "Fichier B";
  const qualityA = comparison.quality_a || {};
  const qualityB = comparison.quality_b || {};
  const scoreA = Math.round(Number(comparison.total_score_a) || 0);
  const scoreB = Math.round(Number(comparison.total_score_b) || 0);

  // Alertes agregees sur tous les rows du groupe
  const allFlags = [];
  for (const row of (group.rows || [])) {
    if (Array.isArray(row.warning_flags)) allFlags.push(...row.warning_flags);
  }
  const alerts = labelsForFlags(allFlags);
  const alertCounts = countBySeverity(allFlags);

  const recommendation = comparison.recommendation || "—";
  const isSelected = _state.selectedGroupKey === _groupKey(group);

  return `
    <article class="doublons-card${isSelected ? " is-selected" : ""}" data-doublons-group="${escapeHtml(_groupKey(group))}">
      <header class="doublons-card-header">
        <h3 class="doublons-card-title">${escapeHtml(title)} <span class="doublons-card-year">${escapeHtml(year)}</span></h3>
        <div class="doublons-card-meta">
          <span>${totalFiles} fichier${totalFiles > 1 ? "s" : ""}</span>
          <span>·</span>
          <span>${escapeHtml(_fmtSize(totalSize))}</span>
          ${alertCounts.total > 0 ? `<span class="doublons-card-alerts">⚠ ${alertCounts.total} alerte${alertCounts.total > 1 ? "s" : ""}</span>` : ""}
        </div>
      </header>
      <div class="doublons-card-versions">
        <div class="doublons-version${winner === "a" ? " is-winner" : ""}">
          <div class="doublons-version-label">A ${winner === "a" ? `<span class="doublons-version-badge">✓ Recommandé</span>` : ""}</div>
          <div class="doublons-version-name">${escapeHtml(fileA)}</div>
          <dl class="doublons-version-dl">
            <dt>Score</dt><dd>${scoreA}/100</dd>
            <dt>Taille</dt><dd>${escapeHtml(_fmtSize(comparison.file_a_size))}</dd>
            ${qualityA.codec ? `<dt>Codec</dt><dd>${escapeHtml(String(qualityA.codec).toUpperCase())}</dd>` : ""}
            ${qualityA.resolution ? `<dt>Résolution</dt><dd>${escapeHtml(qualityA.resolution)}</dd>` : ""}
            ${qualityA.audio_codec ? `<dt>Audio</dt><dd>${escapeHtml(qualityA.audio_codec)}</dd>` : ""}
          </dl>
        </div>
        <div class="doublons-version${winner === "b" ? " is-winner" : ""}">
          <div class="doublons-version-label">B ${winner === "b" ? `<span class="doublons-version-badge">✓ Recommandé</span>` : ""}</div>
          <div class="doublons-version-name">${escapeHtml(fileB)}</div>
          <dl class="doublons-version-dl">
            <dt>Score</dt><dd>${scoreB}/100</dd>
            <dt>Taille</dt><dd>${escapeHtml(_fmtSize(comparison.file_b_size))}</dd>
            ${qualityB.codec ? `<dt>Codec</dt><dd>${escapeHtml(String(qualityB.codec).toUpperCase())}</dd>` : ""}
            ${qualityB.resolution ? `<dt>Résolution</dt><dd>${escapeHtml(qualityB.resolution)}</dd>` : ""}
            ${qualityB.audio_codec ? `<dt>Audio</dt><dd>${escapeHtml(qualityB.audio_codec)}</dd>` : ""}
          </dl>
        </div>
      </div>
      ${alerts.length > 0 ? `
        <ul class="doublons-card-alert-list">
          ${alerts.slice(0, 3).map((a) => `
            <li class="doublons-card-alert doublons-card-alert--${escapeHtml(a.severity)}">
              <span class="doublons-card-alert-icon">${escapeHtml(a.icon)}</span>
              ${escapeHtml(a.label)}
            </li>
          `).join("")}
        </ul>` : ""}
      <footer class="doublons-card-footer">
        <div class="doublons-card-reco">${escapeHtml(recommendation)}</div>
        <div class="doublons-card-actions">
          <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-doublons-card-action="compare" data-group-key="${escapeHtml(_groupKey(group))}">
            Comparer en détail
          </button>
          ${(group.rows && group.rows[0] && group.rows[0].row_id) ? `
          <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-doublons-card-action="perceptual" data-row-id="${escapeHtml(group.rows[0].row_id)}" data-row-title="${escapeHtml(title)}">
            ▶ Analyser perceptuel
          </button>` : ""}
        </div>
      </footer>
    </article>
  `;
}

function _renderBody() {
  if (_state.loading) {
    return `<div class="doublons-section doublons-loading">Chargement des doublons…</div>`;
  }
  if (_state.error) {
    return `<div class="doublons-section doublons-error">${escapeHtml(_state.error)}</div>`;
  }
  if (_state.groups.length === 0) {
    return _renderEmpty();
  }
  return `
    <div class="doublons-list">
      ${_state.groups.map(_renderGroupCard).join("")}
    </div>
  `;
}

function _render() {
  if (!_container) return;
  _container.innerHTML = `
    <section class="doublons-view">
      ${_renderHeader()}
      ${_renderBody()}
    </section>
  `;
  _bindEvents();
}

/* --- Data --- */

async function _loadGroups() {
  _state.loading = true;
  _state.error = null;
  _render();

  // Resolve current run_id
  let runId = _state.runId;
  if (!runId) {
    try {
      const dash = await apiPost("get_dashboard", { run_id_or: "latest" });
      const data = dash && (dash.data || dash);
      runId = data && data.run_id;
      _state.runId = runId;
    } catch (_e) { /* on continuera meme sans runId */ }
  }

  if (!runId) {
    _state.error = "Aucun run actif. Lance un scan d'abord.";
    _state.loading = false;
    _render();
    return;
  }

  try {
    const res = await apiPost("check_duplicates", { run_id: runId, decisions: {} });
    if (!res || res.ok === false) {
      _state.error = (res && (res.message || res.error)) || "Erreur de chargement.";
      _state.loading = false;
      _render();
      return;
    }
    const data = res.data || res;
    _state.groups = Array.isArray(data.groups) ? data.groups : [];
    _state.sizeSavingsTotal = _state.groups.reduce((sum, g) => {
      return sum + (Number(g.comparison && g.comparison.size_savings) || 0);
    }, 0);
    _state.decidedCount = _state.groups.filter((g) => g.winner_decided).length;
    _state.pendingCount = _state.groups.length - _state.decidedCount;
    _state.loading = false;
    if (!_state.selectedGroupKey && _state.groups.length > 0) {
      _state.selectedGroupKey = _groupKey(_state.groups[0]);
    }
    _render();
  } catch (err) {
    _state.error = err && err.message ? err.message : String(err);
    _state.loading = false;
    _render();
  }
}

/* --- Events --- */

function _bindEvents() {
  if (!_container) return;
  const retryBtn = _container.querySelector("[data-doublons-retry]");
  if (retryBtn) retryBtn.addEventListener("click", () => initDoublons(_container));

  _container.querySelectorAll("[data-doublons-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.doublonsAction;
      if (action === "refresh") _loadGroups();
      else if (action === "legacy") window.location.hash = "#/library";
    });
  });

  const filter = _container.querySelector("[data-doublons-filter]");
  if (filter) {
    filter.addEventListener("change", () => {
      _state.filter = filter.value;
      _render();
    });
  }

  _container.querySelectorAll("[data-doublons-group]").forEach((card) => {
    card.addEventListener("click", (ev) => {
      // Eviter de re-selectionner sur clic d'un bouton enfant
      if (ev.target.closest("[data-doublons-card-action]")) return;
      _state.selectedGroupKey = card.dataset.doublonsGroup;
      _render();
    });
  });

  _container.querySelectorAll("[data-doublons-card-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const action = btn.dataset.doublonsCardAction;
      if (action === "compare") {
        // Fallback : ouvre la vue legacy lib-duplicates.js pour l'instant.
        window.location.hash = "#/library";
      } else if (action === "perceptual") {
        const rowId = btn.dataset.rowId;
        const rowTitle = btn.dataset.rowTitle;
        if (rowId) openPerceptualModal({ rowId, runId: _state.runId, rowTitle });
      }
    });
  });
}

/* --- Entrypoint --- */

export async function initDoublons(container) {
  if (!container) return;
  _container = container;
  _state = _initState();
  container.innerHTML = _renderSkeleton();
  const signal = typeof getNavSignal === "function" ? getNavSignal() : undefined;
  void signal;
  await _loadGroups();
}

export function unmountDoublons() {
  _container = null;
  _state = null;
}
