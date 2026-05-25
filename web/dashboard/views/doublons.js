/* views/doublons.js — Vue Doublons (spec 01-doublons.md).
 *
 * Vue principale §1 : liste des groupes avec cartes A/B (codec/source/taille/score)
 * + poster TMDb par groupe + boutons Garder A/B + bulk perceptual.
 *
 * Inspecteur droit §2 : alimente via right-panel.setSections (poster grand
 * format + alertes humanisees + synopsis + candidats TMDb).
 *
 * Modal Comparateur §3 : ouvert via openDuplicateComparatorModal (composant
 * dedie). 3 onglets : Aperçu / Frames / Audio.
 *
 * Workflow decision §4 : appel run/mark_duplicate_winner depuis la carte
 * et depuis le modal. Toast de progression sur les bulk d'analyses
 * perceptuelles (quality/queue_perceptual_analyses + polling job_id).
 *
 * Route : /doublons (deja cablee dans app.js).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { labelsForFlags, countBySeverity } from "../core/alert-labels.js";
import { openPerceptualModal } from "../components/perceptual-modal.js";
import { renderFilmDetail } from "../components/film-detail.js";
import { openDuplicateComparatorModal } from "../components/duplicate-comparator-modal.js";
import { showToast } from "../components/toast.js";
import { setSections as setRightPanelSections } from "../components/right-panel.js";
// Fix audit 2026-05-24 (v1.5.2) : import dangerConfirmModal pour la
// confirmation du bouton "Auto-décider tous" (action irréversible cote UI :
// les décisions sont persistées immédiatement en DB via mark_duplicate_winner).
import { dangerConfirmModal } from "../components/modal.js";
import { navigateTo } from "../core/router.js";

let _state = null;
let _container = null;
let _filmCache = new Map();   // row_id -> {poster_url, overview, candidates}
let _keyboardHandler = null;
const _SELECTED_KEY_STORAGE = "cinesort.doublons.selectedGroupKey";

// Fix audit 2026-05-24 : getNavSignal était importé puis assigné dans une
// variable locale `signal` jamais utilisée (void signal). On centralise un
// getter de signal pour le passer en 3e arg de tous les apiPost.
function _signal() {
  return typeof getNavSignal === "function" ? getNavSignal() : undefined;
}

function _initState() {
  return {
    groups: [],
    sizeSavingsTotal: 0,
    decidedCount: 0,
    pendingCount: 0,
    selectedGroupKey: _readStoredSelection(),
    runId: null,
    loading: true,
    error: null,
    filter: "all", // all | conflict | pending | decided
    bulkInFlight: false,
    // Fix audit 2026-05-24 : avant decisionInFlight était un seul booléen
    // global -> dès qu'on cliquait "Garder A" sur le groupe X, TOUS les
    // boutons "Garder A/B" de tous les autres groupes passaient disabled.
    // Désormais : Set des groupKeys en vol -> seuls les boutons du groupe
    // concerné se désactivent, l'utilisateur peut décider en parallèle.
    decisionInFlightByGroup: new Set(),
  };
}

function _readStoredSelection() {
  try {
    return localStorage.getItem(_SELECTED_KEY_STORAGE) || null;
  } catch (_e) {
    return null;
  }
}

function _writeStoredSelection(key) {
  try {
    if (key) localStorage.setItem(_SELECTED_KEY_STORAGE, key);
    else localStorage.removeItem(_SELECTED_KEY_STORAGE);
  } catch (_e) { /* noop */ }
}

/* --- Formatters --- */

function _fmtSize(bytes) {
  const b = Number(bytes) || 0;
  if (b <= 0) return "—";
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} Mo`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(2)} Go`;
}

function _groupKey(group) {
  for (const key of ["group_key", "id", "signature"]) {
    if (group[key]) return String(group[key]);
  }
  return String(group.key || group.title || "") + "::" + String(group.year || "");
}

function _firstRowId(group) {
  if (group.rows && group.rows[0]) return group.rows[0].row_id;
  return null;
}

function _payload(res) {
  // Tolere {status, data} et payload direct.
  if (!res) return {};
  return res.data && typeof res.data === "object" ? res.data : res;
}

function _rowIdsOfGroup(group) {
  return (group.rows || [])
    .map((r) => r.row_id)
    .filter((rid) => Boolean(rid));
}

/* --- TMDb cache via library/get_film_full --- */

async function _fetchFilmFull(rowId) {
  if (!rowId) return null;
  const cached = _filmCache.get(rowId);
  if (cached) return cached;
  // Pose un placeholder pour eviter de relancer pendant le fetch
  _filmCache.set(rowId, { _loading: true });
  try {
    const res = await apiPost("library/get_film_full", { run_id: _state ? _state.runId : null, row_id: rowId }, { signal: _signal() });
    const data = _payload(res);
    if (data.ok === false) {
      _filmCache.set(rowId, { poster_url: null, overview: null, candidates: [] });
      return _filmCache.get(rowId);
    }
    const entry = {
      poster_url: data.poster_url || null,
      overview: data.overview || null,
      runtime: data.runtime || null,
      director: data.director || null,
      candidates: Array.isArray(data.row && data.row.candidates) ? data.row.candidates : [],
    };
    _filmCache.set(rowId, entry);
    return entry;
  } catch (_err) {
    _filmCache.set(rowId, { poster_url: null, overview: null, candidates: [] });
    return _filmCache.get(rowId);
  }
}

async function _hydrateGroupsWithPosters() {
  // Charge en parallele les film_full des premiers rows de chaque groupe
  if (!_state || !_state.groups) return;
  const tasks = [];
  for (const g of _state.groups) {
    const rid = _firstRowId(g);
    if (rid && !_filmCache.has(rid)) {
      tasks.push(_fetchFilmFull(rid));
    }
  }
  if (tasks.length === 0) return;
  await Promise.allSettled(tasks);
  // Re-render pour afficher les posters
  _render();
  _renderRightPanel();
}

/* --- Filtering --- */

function _visibleGroups() {
  const all = Array.isArray(_state.groups) ? _state.groups : [];
  switch (_state.filter) {
    case "pending":
      return all.filter((g) => !g.winner_decided);
    case "decided":
      return all.filter((g) => g.winner_decided);
    case "conflict":
      return all.filter((g) => g.plan_conflict);
    default:
      return all;
  }
}

function _findGroupByKey(key) {
  if (!key) return null;
  return (_state.groups || []).find((g) => _groupKey(g) === key) || null;
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
  const pendingForBulk = _visibleGroups().filter((g) => !g.winner_decided).length;
  const bulkBtnDisabled = (_state.bulkInFlight || pendingForBulk === 0) ? "disabled" : "";
  // Fix audit 2026-05-24 (v1.5.2) : compter les groupes avec un winner score
  // déterministe ("a" ou "b" et pas "tie/unknown") pour activer le bouton
  // Auto-décider. Si aucun groupe n'a de winner clair -> bouton désactivé.
  const autoDecidable = _state.groups.filter((g) => {
    if (g.winner_decided) return false;
    const w = String((g.comparison && g.comparison.winner) || "").toLowerCase();
    return w === "a" || w === "b";
  }).length;
  const autoBtnDisabled = (_state.bulkInFlight || autoDecidable === 0) ? "disabled" : "";
  return `
    <header class="doublons-header">
      <div class="doublons-header-top">
        <h1 class="doublons-title">Doublons</h1>
        <p class="doublons-summary">
          <strong>${n}</strong> groupe${n > 1 ? "s" : ""} ·
          <strong>${escapeHtml(savings)}</strong> récupérable${savings === "—" ? "" : "s"} ·
          <strong>${_state.decidedCount}</strong> décidé${_state.decidedCount > 1 ? "s" : ""} ·
          <strong>${_state.pendingCount}</strong> en attente
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
        <button type="button" class="v5-btn v5-btn--primary" data-doublons-action="bulk-perceptual" ${bulkBtnDisabled}>
          ▾ Analyser perceptuel sur ${pendingForBulk} groupe${pendingForBulk > 1 ? "s" : ""}
        </button>
        <button type="button" class="v5-btn v5-btn--secondary" data-doublons-action="auto-decide-all" ${autoBtnDisabled}
                title="Choisit automatiquement le winner par score qualité pour tous les groupes non décidés">
          🤖 Auto-décider tous (${autoDecidable})
        </button>
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

  // Alertes agregees
  const allFlags = [];
  for (const row of (group.rows || [])) {
    if (Array.isArray(row.warning_flags)) allFlags.push(...row.warning_flags);
  }
  const alerts = labelsForFlags(allFlags);
  const alertCounts = countBySeverity(allFlags);

  const recommendation = comparison.recommendation || "—";
  const groupKey = _groupKey(group);
  const isSelected = _state.selectedGroupKey === groupKey;

  // Poster TMDb du premier row (cache hydrate apres premier load)
  const firstRid = _firstRowId(group);
  const filmInfo = firstRid ? _filmCache.get(firstRid) : null;
  const posterUrl = filmInfo && !filmInfo._loading ? filmInfo.poster_url : null;

  // Decision badge
  const decided = Boolean(group.winner_decided);
  const winnerSide = String(group.winner_side || group.winner || "").toLowerCase();
  const winnerLabel = winnerSide === "a" ? "A" : winnerSide === "b" ? "B" : "?";
  const savings = _fmtSize(group.size_savings || (comparison && comparison.size_savings) || 0);

  // Ids row pour les boutons Garder A/B (sur la carte)
  const rowAId = group.rows && group.rows[0] ? group.rows[0].row_id : null;
  const rowBId = group.rows && group.rows[1] ? group.rows[1].row_id : null;
  // Fix audit 2026-05-24 : disable uniquement les boutons du groupe en vol.
  const inflight = _state.decisionInFlightByGroup.has(groupKey) ? "disabled" : "";

  return `
    <article class="doublons-card${isSelected ? " is-selected" : ""}${decided ? " is-decided" : ""}"
             data-doublons-group="${escapeHtml(groupKey)}" tabindex="0">
      <header class="doublons-card-header">
        <div class="doublons-card-poster" aria-hidden="true">
          ${posterUrl
            ? `<img src="${escapeHtml(posterUrl)}" alt="" loading="lazy" />`
            : `<div class="doublons-card-poster-placeholder">🎬</div>`}
        </div>
        <div class="doublons-card-title-block">
          <h3 class="doublons-card-title">${escapeHtml(title)} <span class="doublons-card-year">${escapeHtml(year)}</span></h3>
          <div class="doublons-card-meta">
            <span>${totalFiles} fichier${totalFiles > 1 ? "s" : ""}</span>
            <span>·</span>
            <span>${escapeHtml(_fmtSize(totalSize))}</span>
            ${alertCounts.total > 0 ? `<span class="doublons-card-alerts">⚠ ${alertCounts.total} alerte${alertCounts.total > 1 ? "s" : ""}</span>` : ""}
          </div>
          ${decided ? `
            <p class="duplicate-decision-badge duplicate-decision-badge--decided">
              ✓ Décidé : Garder ${escapeHtml(winnerLabel)}${savings !== "—" ? ` · ${escapeHtml(savings)} récupérables` : ""}
            </p>` : ""}
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
          ${rowAId ? `
          <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm"
                  data-doublons-card-action="keep" data-side="a"
                  data-row-id="${escapeHtml(rowAId)}"
                  data-group-key="${escapeHtml(groupKey)}" ${inflight}>
            ✓ Garder A
          </button>` : ""}
          ${rowBId ? `
          <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm"
                  data-doublons-card-action="keep" data-side="b"
                  data-row-id="${escapeHtml(rowBId)}"
                  data-group-key="${escapeHtml(groupKey)}" ${inflight}>
            ✓ Garder B
          </button>` : ""}
          <button type="button" class="v5-btn v5-btn--primary v5-btn--sm"
                  data-doublons-card-action="compare" data-group-key="${escapeHtml(groupKey)}">
            Comparer en détail
          </button>
          ${(group.rows && group.rows[0] && group.rows[0].row_id) ? `
          <button type="button" class="v5-btn v5-btn--secondary v5-btn--sm" data-doublons-card-action="perceptual" data-row-id="${escapeHtml(group.rows[0].row_id)}" data-row-title="${escapeHtml(title)}">
            ▶ Analyser perceptuel
          </button>
          <button type="button" class="v5-btn v5-btn--ghost v5-btn--sm" data-doublons-card-action="detail" data-row-id="${escapeHtml(group.rows[0].row_id)}">
            Voir fiche détaillée
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
  const list = _visibleGroups();
  if (list.length === 0) {
    return _renderEmpty();
  }
  return `
    <div class="doublons-list">
      ${list.map(_renderGroupCard).join("")}
    </div>
    ${_renderApplyCta()}
  `;
}

// Fix audit 2026-05-24 (v1.5.2) : CTA "Passer à Apply" en bas. Quand tous les
// groupes sont décidés -> bouton primary visible. Sinon : afficher un compteur
// de progression "X / Y décidés" pour guider l'utilisateur. Sans ce CTA, après
// avoir cliqué "Garder A/B" sur tous les groupes, l'utilisateur restait coincé
// sur la vue Doublons sans savoir comment passer à l'étape Apply.
function _renderApplyCta() {
  const total = _state.groups.length;
  if (total === 0) return "";
  const decided = _state.decidedCount;
  if (decided >= total) {
    return `
      <div class="doublons-apply-cta doublons-apply-cta--ready">
        <p class="doublons-apply-cta-msg">
          ✓ Tous les groupes sont décidés (${decided}/${total}).
        </p>
        <button type="button" class="v5-btn v5-btn--primary v5-btn--lg" data-doublons-action="go-apply">
          → Passer à Apply
        </button>
      </div>
    `;
  }
  return `
    <div class="doublons-apply-cta doublons-apply-cta--progress">
      <p class="doublons-apply-cta-msg">
        ${decided} / ${total} groupe${total > 1 ? "s" : ""} décidé${decided > 1 ? "s" : ""}.
        Décide les ${total - decided} restant${(total - decided) > 1 ? "s" : ""} pour passer à Apply.
      </p>
      <button type="button" class="v5-btn v5-btn--ghost v5-btn--lg" disabled
              title="Tous les groupes doivent être décidés avant Apply">
        → Passer à Apply (${decided}/${total})
      </button>
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

/* --- Right Panel (Inspecteur §2) --- */

function _renderRightPanel() {
  if (typeof setRightPanelSections !== "function") return;
  const total = _state.groups.length;
  const sectionContext = {
    title: "Contexte",
    html: `
      <p class="doublons-inspector-stat">
        <strong>${total}</strong> groupe${total > 1 ? "s" : ""} au total
      </p>
      <p class="doublons-inspector-stat">
        <strong>${escapeHtml(_fmtSize(_state.sizeSavingsTotal))}</strong> récupérables
      </p>
      <p class="doublons-inspector-stat">
        <strong>${_state.decidedCount}</strong> décidé${_state.decidedCount > 1 ? "s" : ""} ·
        <strong>${_state.pendingCount}</strong> en attente
      </p>
    `,
  };

  const sections = [sectionContext];

  const group = _findGroupByKey(_state.selectedGroupKey);
  if (group) {
    const title = group.title || "Sans titre";
    const year = group.year ? ` (${group.year})` : "";
    const firstRid = _firstRowId(group);
    const filmInfo = firstRid ? _filmCache.get(firstRid) : null;
    const posterUrl = filmInfo && !filmInfo._loading ? filmInfo.poster_url : null;
    const overview = filmInfo && !filmInfo._loading ? filmInfo.overview : null;
    const candidates = filmInfo && !filmInfo._loading ? (filmInfo.candidates || []) : [];
    const runtime = filmInfo && !filmInfo._loading ? filmInfo.runtime : null;

    const allFlags = [];
    for (const r of (group.rows || [])) {
      if (Array.isArray(r.warning_flags)) allFlags.push(...r.warning_flags);
    }
    const alerts = labelsForFlags(allFlags);

    // Fix audit 2026-05-24 : disable uniquement si décision en vol pour CE groupe.
    const inflight = _state.decisionInFlightByGroup.has(_groupKey(group)) ? "disabled" : "";

    sections.push({
      title: "📌 Groupe sélectionné",
      html: `
        ${posterUrl
          ? `<div class="doublons-inspector-poster"><img src="${escapeHtml(posterUrl)}" alt="" loading="lazy" /></div>`
          : `<div class="doublons-inspector-poster doublons-inspector-poster--empty">🎬</div>`}
        <h4 class="doublons-inspector-title">${escapeHtml(title)}${escapeHtml(year)}</h4>
        ${runtime ? `<p class="doublons-inspector-meta">${escapeHtml(String(runtime))} min</p>` : ""}
        ${alerts.length > 0 ? `
          <p class="doublons-inspector-alerts-title">⚠ ${alerts.length} alerte${alerts.length > 1 ? "s" : ""}</p>
          <ul class="doublons-inspector-alerts">
            ${alerts.map((a) => `
              <li class="doublons-card-alert doublons-card-alert--${escapeHtml(a.severity)}">
                <span class="doublons-card-alert-icon">${escapeHtml(a.icon)}</span>
                ${escapeHtml(a.label)}
              </li>
            `).join("")}
          </ul>` : ""}
        ${overview ? `
          <p class="doublons-inspector-section-title">🎬 Synopsis</p>
          <p class="doublons-inspector-overview">${escapeHtml(overview)}</p>` : ""}
        ${candidates && candidates.length > 0 ? `
          <p class="doublons-inspector-section-title">🏷 Candidats TMDb</p>
          <ul class="doublons-inspector-candidates">
            ${candidates.slice(0, 3).map((c) => {
              const conf = c.confidence != null ? Math.round(Number(c.confidence) * 100) : null;
              return `<li>
                <strong>${escapeHtml(c.title || "?")}</strong>${c.year ? ` (${escapeHtml(String(c.year))})` : ""}
                ${conf != null ? `<br><span class="doublons-inspector-confidence">Confiance ${conf}%</span>` : ""}
              </li>`;
            }).join("")}
          </ul>` : ""}
      `,
    });

    sections.push({
      title: "Actions",
      html: `
        <div class="doublons-inspector-actions">
          <button type="button" class="v5-btn v5-btn--primary"
                  data-doublons-inspector-action="compare"
                  data-group-key="${escapeHtml(_groupKey(group))}">
            ▶ Comparer en détail
          </button>
          <button type="button" class="v5-btn v5-btn--secondary"
                  data-doublons-inspector-action="perceptual"
                  data-row-id="${firstRid ? escapeHtml(firstRid) : ""}"
                  data-row-title="${escapeHtml(title)}" ${firstRid ? "" : "disabled"}>
            ▾ Analyser perceptuel
          </button>
          <button type="button" class="v5-btn v5-btn--ghost"
                  data-doublons-inspector-action="skip" ${inflight}>
            → Skip ce groupe
          </button>
        </div>
      `,
    });
  } else if (total === 0) {
    sections.push({
      title: "Aucun groupe sélectionné",
      html: `<p class="doublons-inspector-empty">Aucun doublon dans la liste.</p>`,
    });
  } else {
    sections.push({
      title: "Aucun groupe sélectionné",
      html: `<p class="doublons-inspector-empty">Clique sur un groupe pour voir son détail.</p>`,
    });
  }

  setRightPanelSections(sections);
  _bindRightPanelEvents();
}

function _bindRightPanelEvents() {
  // Les sections du right-panel sont rendues dans un container externe geré par
  // right-panel.js. On binde via delegation sur document.
  document.querySelectorAll("[data-doublons-inspector-action]").forEach((btn) => {
    // Eviter de re-bind
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      const action = btn.dataset.doublonsInspectorAction;
      const groupKey = btn.dataset.groupKey;
      if (action === "compare" && groupKey) {
        _openComparator(_findGroupByKey(groupKey));
      } else if (action === "perceptual") {
        const rowId = btn.dataset.rowId;
        const rowTitle = btn.dataset.rowTitle;
        if (rowId) openPerceptualModal({ rowId, runId: _state.runId, rowTitle });
      } else if (action === "skip") {
        _navigateNext();
      }
    });
  });
}

/* --- Comparator open --- */

function _openComparator(group) {
  if (!group) return;
  const rowAId = group.rows && group.rows[0] ? group.rows[0].row_id : null;
  const rowBId = group.rows && group.rows[1] ? group.rows[1].row_id : null;
  if (!rowAId || !rowBId) {
    showToast({ type: "warn", text: "Comparaison nécessite au moins 2 rows valides." });
    return;
  }
  openDuplicateComparatorModal({
    runId: _state.runId,
    groupKey: _groupKey(group),
    rowA: rowAId,
    rowB: rowBId,
    title: group.title,
    year: group.year,
    comparison: group.comparison || {},
    onDecided: (decision) => {
      _handleDecision(decision.groupKey, decision.winnerSide, decision.winnerRowId, decision.payload);
    },
  });
}

/* --- Decision (mark_duplicate_winner) --- */

async function _decideFromCard(groupKey, side, winnerRowId) {
  // Fix audit 2026-05-24 : check + add + delete par groupKey (per-group lock).
  if (!_state || _state.decisionInFlightByGroup.has(groupKey)) return;
  _state.decisionInFlightByGroup.add(groupKey);
  _render();
  try {
    const res = await apiPost("run/mark_duplicate_winner", {
      run_id: _state.runId,
      group_key: groupKey,
      winner_row_id: winnerRowId,
      notes: null,
    }, { signal: _signal() });
    // Fix audit 2026-05-24 : si _state a été vidé pendant le fetch (unmount),
    // ne pas continuer (NPE sur _state.decisionInFlightByGroup.delete).
    if (!_state) return;
    const data = _payload(res);
    if (data.ok === false) {
      showToast({ type: "error", text: data.message || data.error || "Échec décision" });
      _state.decisionInFlightByGroup.delete(groupKey);
      _render();
      return;
    }
    // Fix audit 2026-05-24 : avant on mettait juste à jour le groupe local,
    // mais size_savings_total et decidedCount peuvent diverger côté backend
    // (recalcul tier, recouvrement) -> total affiché en header devenait stale.
    // Round-trip _loadGroups() pour resynchroniser depuis la source de vérité.
    _state.decisionInFlightByGroup.delete(groupKey);
    _handleDecision(groupKey, side, winnerRowId, data);
    await _loadGroups();
  } catch (err) {
    if (!_state) return;
    showToast({ type: "error", text: err && err.message ? err.message : String(err) });
    _state.decisionInFlightByGroup.delete(groupKey);
    _render();
  }
}

function _handleDecision(groupKey, side, winnerRowId, payload) {
  // Met a jour le groupe en local pour feedback immédiat (le _loadGroups()
  // qui suit dans _decideFromCard resync le total fiable).
  const group = _findGroupByKey(groupKey);
  if (group) {
    group.winner_decided = true;
    group.winner_side = side;
    group.winner_row_id = winnerRowId;
    if (payload && payload.losers) group.losers = payload.losers;
  }
  // Compteurs
  _state.decidedCount = _state.groups.filter((g) => g.winner_decided).length;
  _state.pendingCount = _state.groups.length - _state.decidedCount;
  // Fix audit 2026-05-24 : decisionInFlight global supprimé au profit du Set.
  _state.decisionInFlightByGroup.delete(groupKey);
  const sideLabel = side === "a" ? "A" : "B";
  showToast({ type: "success", text: `✓ Décidé : Garder ${sideLabel}` });
  _render();
  _renderRightPanel();
}

/* --- Auto-décider tous (par score qualité) --- */

// Fix audit 2026-05-24 (v1.5.2) : auto-décide tous les groupes non décidés en
// utilisant comparison.winner ("a" ou "b") calculé par le backend (winner score
// qualité). Pas d'endpoint bulk -> boucle séquentielle d'appels
// mark_duplicate_winner avec mutex per-group + progress toast tous les 5
// groupes. dangerConfirmModal car action irréversible côté UI (rollback
// nécessite de re-cliquer sur chaque carte).
async function _autoDecideAll() {
  if (!_state || _state.bulkInFlight) return;
  const candidates = _state.groups.filter((g) => {
    if (g.winner_decided) return false;
    const w = String((g.comparison && g.comparison.winner) || "").toLowerCase();
    return w === "a" || w === "b";
  });
  if (candidates.length === 0) {
    showToast({ type: "info", text: "Aucun groupe à auto-décider (winners ambigus)." });
    return;
  }

  dangerConfirmModal({
    title: `Auto-décider ${candidates.length} groupe${candidates.length > 1 ? "s" : ""} ?`,
    items: [
      `${candidates.length} décision${candidates.length > 1 ? "s" : ""} seront posée${candidates.length > 1 ? "s" : ""} d'un coup`,
      `Critère : winner du score qualité (codec + résolution + bitrate)`,
      `Les "losers" iront en _review/_duplicates_user_decided/ à l'apply`,
    ],
    consequence:
      "Les décisions sont persistées immédiatement en base. Pour annuler, il faudra rouvrir chaque groupe et changer le winner manuellement.",
    confirmLabel: `🤖 Auto-décider ${candidates.length}`,
    cancelLabel: "Annuler",
    countdownSeconds: candidates.length > 50 ? 3 : 0,
    onConfirm: async () => {
      if (!_state) return;
      _state.bulkInFlight = true;
      _render();
      showToast({
        type: "info",
        text: `⏳ Auto-décision en cours sur ${candidates.length} groupe${candidates.length > 1 ? "s" : ""}…`,
      });

      let ok = 0;
      let ko = 0;
      for (let i = 0; i < candidates.length; i++) {
        if (!_state) return; // unmount pendant la boucle
        const g = candidates[i];
        const groupKey = _groupKey(g);
        const side = String(g.comparison.winner).toLowerCase();
        const winnerIdx = side === "a" ? 0 : 1;
        const winnerRow = (g.rows || [])[winnerIdx];
        const winnerRowId = winnerRow ? winnerRow.row_id : null;
        if (!winnerRowId) { ko += 1; continue; }
        try {
          const res = await apiPost("run/mark_duplicate_winner", {
            run_id: _state.runId,
            group_key: groupKey,
            winner_row_id: winnerRowId,
            notes: "auto-decide:score_v2",
          }, { signal: _signal() });
          if (!_state) return;
          const data = _payload(res);
          if (data.ok === false) { ko += 1; }
          else {
            ok += 1;
            g.winner_decided = true;
            g.winner_side = side;
            g.winner_row_id = winnerRowId;
            if (data.losers) g.losers = data.losers;
          }
        } catch (_e) {
          if (!_state) return;
          ko += 1;
        }
        // Progress feedback tous les 5 groupes
        if ((i + 1) % 5 === 0 && _state) {
          _state.decidedCount = _state.groups.filter((x) => x.winner_decided).length;
          _state.pendingCount = _state.groups.length - _state.decidedCount;
          _render();
        }
      }

      if (!_state) return;
      _state.bulkInFlight = false;
      // Resync depuis le backend pour les totaux (size_savings, decidedCount).
      await _loadGroups();
      if (!_state) return;
      if (ko === 0) {
        showToast({ type: "success", text: `✓ ${ok} groupe${ok > 1 ? "s" : ""} auto-décidé${ok > 1 ? "s" : ""}.` });
      } else {
        showToast({
          type: "warn",
          text: `${ok} décidé${ok > 1 ? "s" : ""}, ${ko} échec${ko > 1 ? "s" : ""}. Vérifie les groupes restants.`,
          duration: 6000,
        });
      }
    },
  });
}

/* --- Navigation vers étape Apply --- */

// Fix audit 2026-05-24 (v1.5.2) : navigation directe vers la step Apply du
// workflow Traitement. Utilise navigateTo pour rester dans le router SPA et
// déclencher l'init du workflow Traitement sur la bonne étape.
function _goToApply() {
  // navigateTo préfixe avec "#" -> on passe sans le "#" initial.
  // Le fragment "#step-apply" est lu par traitement.js _readStep().
  navigateTo("/traitement#step-apply");
}

/* --- Bulk perceptual --- */

async function _bulkPerceptual() {
  if (!_state || _state.bulkInFlight) return;
  const targets = _visibleGroups().filter((g) => !g.winner_decided);
  if (targets.length === 0) {
    showToast({ type: "info", text: "Aucun groupe à analyser." });
    return;
  }
  const pairs = [];
  for (const g of targets) {
    const ids = _rowIdsOfGroup(g);
    if (ids.length >= 2) {
      pairs.push({ run_id: _state.runId, row_a: ids[0], row_b: ids[1] });
    }
  }
  if (pairs.length === 0) {
    showToast({ type: "warn", text: "Aucune paire valide à analyser." });
    return;
  }
  _state.bulkInFlight = true;
  _render();
  showToast({ type: "info", text: `⏳ Lancement de ${pairs.length} analyse${pairs.length > 1 ? "s" : ""} perceptuelle${pairs.length > 1 ? "s" : ""}…` });

  try {
    const res = await apiPost("quality/queue_perceptual_analyses", { pairs, options: {} }, { signal: _signal() });
    const data = _payload(res);
    if (data.ok === false) {
      showToast({ type: "error", text: data.message || data.error || "Échec queue analyses" });
      _state.bulkInFlight = false;
      _render();
      return;
    }
    const jobId = data.job_id;
    if (!jobId) {
      showToast({ type: "warn", text: "Job ID manquant." });
      _state.bulkInFlight = false;
      _render();
      return;
    }
    // Polling job status (max 30 essais, 2s entre chaque = 1 min)
    await _pollJobUntilDone(jobId, 30, 2000);
  } catch (err) {
    showToast({ type: "error", text: err && err.message ? err.message : String(err) });
  } finally {
    _state.bulkInFlight = false;
    _render();
  }
}

async function _pollJobUntilDone(jobId, maxAttempts, delayMs) {
  for (let i = 0; i < maxAttempts; i++) {
    // Fix audit 2026-05-24 : si l'utilisateur navigue hors de la vue Doublons
    // pendant un bulk perceptual, unmountDoublons met _state à null. Avant
    // ce guard, la boucle continuait, faisait des apiPost zombies et tentait
    // de showToast/render sur un container détruit -> NPE silencieux + fuite
    // 1 fetch/2s pendant 1 min.
    if (!_state) return;
    try {
      const res = await apiPost("quality/get_perceptual_job_status", { job_id: jobId }, { signal: _signal() });
      if (!_state) return;
      const data = _payload(res);
      if (data.ok === false) {
        showToast({ type: "error", text: data.message || data.error || "Polling job échoué" });
        return;
      }
      const status = String(data.status || "").toLowerCase();
      const done = Number(data.done || 0);
      const total = Number(data.total || 0);
      if (status === "done" || status === "complete" || status === "completed" || status === "finished") {
        showToast({ type: "success", text: `✓ ${done}/${total} analyses terminées` });
        return;
      }
      if (status === "error" || status === "failed") {
        showToast({ type: "error", text: "Analyses échouées." });
        return;
      }
      // En cours
      if (i > 0 && i % 5 === 0) {
        showToast({ type: "info", text: `⏳ ${done}/${total} analyses…` });
      }
    } catch (err) {
      if (!_state) return;
      showToast({ type: "error", text: err && err.message ? err.message : String(err) });
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    // Fix audit 2026-05-24 : re-check après le sleep (même iteration suivante).
    if (!_state) return;
  }
  if (!_state) return;
  showToast({ type: "warn", text: "Polling timeout — vérifie l'état dans Logs." });
}

/* --- Navigation clavier --- */

function _navigateNext() {
  const list = _visibleGroups();
  if (list.length === 0) return;
  const cur = _state.selectedGroupKey;
  const idx = list.findIndex((g) => _groupKey(g) === cur);
  const next = list[Math.min(list.length - 1, Math.max(0, idx + 1))];
  if (next) _selectGroup(_groupKey(next));
}

function _navigatePrev() {
  const list = _visibleGroups();
  if (list.length === 0) return;
  const cur = _state.selectedGroupKey;
  const idx = list.findIndex((g) => _groupKey(g) === cur);
  const prev = list[Math.max(0, idx - 1)];
  if (prev) _selectGroup(_groupKey(prev));
}

function _selectGroup(key) {
  _state.selectedGroupKey = key;
  _writeStoredSelection(key);
  _render();
  _renderRightPanel();
}

function _onKeydown(ev) {
  if (!_state) return;
  // Ignorer si l'utilisateur tape dans un input/select/textarea ou dans un modal
  const tgt = ev.target;
  if (tgt && tgt.matches && tgt.matches("input, select, textarea, [contenteditable]")) return;
  if (document.body.classList.contains("modal-open")) return;
  if (ev.key === "ArrowDown") {
    ev.preventDefault();
    _navigateNext();
  } else if (ev.key === "ArrowUp") {
    ev.preventDefault();
    _navigatePrev();
  }
}

/* --- Data --- */

async function _loadGroups() {
  _state.loading = true;
  _state.error = null;
  _render();
  _renderRightPanel();

  let runId = _state.runId;
  if (!runId) {
    try {
      // Fix audit 2026-05-24 : `run_id_or` n'existe pas dans la facade (cf traitement.js).
      const dash = await apiPost("run/get_dashboard", { run_id: "latest" }, { signal: _signal() });
      const data = _payload(dash);
      runId = data && data.run_id;
      _state.runId = runId;
    } catch (_e) { /* on continuera meme sans runId */ }
  }

  if (!runId) {
    _state.error = "Aucun run actif. Lance un scan d'abord.";
    _state.loading = false;
    _render();
    _renderRightPanel();
    return;
  }

  try {
    const res = await apiPost("run/check_duplicates", { run_id: runId, decisions: {} }, { signal: _signal() });
    const data = _payload(res);
    if (data.ok === false) {
      _state.error = data.message || data.error || "Erreur de chargement.";
      _state.loading = false;
      _render();
      _renderRightPanel();
      return;
    }
    _state.groups = Array.isArray(data.groups) ? data.groups : [];
    // Utilise size_savings_total enrichi backend si dispo, sinon agrège
    if (typeof data.size_savings_total === "number") {
      _state.sizeSavingsTotal = data.size_savings_total;
    } else {
      _state.sizeSavingsTotal = _state.groups.reduce((sum, g) => {
        return sum + (Number(g.comparison && g.comparison.size_savings) || 0);
      }, 0);
    }
    _state.decidedCount = _state.groups.filter((g) => g.winner_decided).length;
    _state.pendingCount = _state.groups.length - _state.decidedCount;
    _state.loading = false;
    // Selection : restaurer si encore valide, sinon premier groupe non décidé
    if (_state.selectedGroupKey && !_findGroupByKey(_state.selectedGroupKey)) {
      _state.selectedGroupKey = null;
    }
    if (!_state.selectedGroupKey && _state.groups.length > 0) {
      const firstUndec = _state.groups.find((g) => !g.winner_decided) || _state.groups[0];
      _state.selectedGroupKey = _groupKey(firstUndec);
      _writeStoredSelection(_state.selectedGroupKey);
    }
    _render();
    _renderRightPanel();
    // Hydrater posters en background
    void _hydrateGroupsWithPosters();
  } catch (err) {
    _state.error = err && err.message ? err.message : String(err);
    _state.loading = false;
    _render();
    _renderRightPanel();
  }
}

/* --- Events --- */

function _bindEvents() {
  if (!_container) return;
  const retryBtn = _container.querySelector("[data-doublons-retry]");
  if (retryBtn) retryBtn.addEventListener("click", () => {
    // Fix audit 2026-05-24 : avant on appelait initDoublons sans unmount,
    // donc l'ancien _keyboardHandler restait attaché (double handler), le
    // _state précédent leakait et le right-panel gardait les sections de
    // l'instance morte. Unmount avant re-init = reset propre.
    const target = _container;
    unmountDoublons();
    initDoublons(target);
  });

  _container.querySelectorAll("[data-doublons-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.doublonsAction;
      if (action === "refresh") _loadGroups();
      else if (action === "bulk-perceptual") void _bulkPerceptual();
      // Fix audit 2026-05-24 (v1.5.2) : nouveaux handlers auto-décide + go-apply.
      else if (action === "auto-decide-all") void _autoDecideAll();
      else if (action === "go-apply") _goToApply();
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
      _selectGroup(card.dataset.doublonsGroup);
    });
  });

  _container.querySelectorAll("[data-doublons-card-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const action = btn.dataset.doublonsCardAction;
      const groupKey = btn.dataset.groupKey;
      if (action === "compare") {
        _openComparator(_findGroupByKey(groupKey));
      } else if (action === "perceptual") {
        const rowId = btn.dataset.rowId;
        const rowTitle = btn.dataset.rowTitle;
        if (rowId) openPerceptualModal({ rowId, runId: _state.runId, rowTitle });
      } else if (action === "detail") {
        // Spec 06 : depuis Modal Comparateur / vue Doublons -> mode C overlay.
        const rowId = btn.dataset.rowId;
        if (rowId) renderFilmDetail({ mode: "C", rowId, runId: _state.runId });
      } else if (action === "keep") {
        const side = btn.dataset.side;
        const rowId = btn.dataset.rowId;
        if (groupKey && rowId && (side === "a" || side === "b")) {
          void _decideFromCard(groupKey, side, rowId);
        }
      }
    });
  });
}

/* --- Entrypoint --- */

export async function initDoublons(container) {
  if (!container) return;
  _container = container;
  _state = _initState();
  _filmCache = new Map();
  container.innerHTML = _renderSkeleton();
  // Fix audit 2026-05-24 : avant on récupérait getNavSignal() puis on faisait
  // `void signal` -> import inutile, abort jamais relié. Le helper _signal()
  // au scope module est passé à chaque apiPost ci-dessus pour vraiment
  // annuler les requêtes en cas de nav.
  // Keyboard nav
  if (_keyboardHandler) {
    document.removeEventListener("keydown", _keyboardHandler);
  }
  _keyboardHandler = _onKeydown;
  document.addEventListener("keydown", _keyboardHandler);
  await _loadGroups();
}

export function unmountDoublons() {
  _container = null;
  _state = null;
  if (_keyboardHandler) {
    document.removeEventListener("keydown", _keyboardHandler);
    _keyboardHandler = null;
  }
  if (typeof setRightPanelSections === "function") {
    setRightPanelSections([]);
  }
}
