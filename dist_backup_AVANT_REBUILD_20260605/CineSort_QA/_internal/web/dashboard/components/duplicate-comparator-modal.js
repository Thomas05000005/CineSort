/* components/duplicate-comparator-modal.js — Modal Comparateur Doublons (spec 01 §3).
 *
 * Overlay fullscreen 90vw avec 3 onglets :
 *   - Apercu  : tableau critères côte à côte (codec/source/résolution/...)
 *   - Frames  : 3 paires de frames PNG via quality/get_perceptual_compare_frames (lazy)
 *   - Audio   : waveforms PNG + clips MP3 via quality/get_perceptual_compare_audio (lazy)
 *
 * Footer : boutons "✓ Garder A", "✓ Garder B" (… "✓ Garder N" si 3+ fichiers),
 * "→ Skip" cables sur run/mark_duplicate_winner.
 *
 * Cas 3+ fichiers (spec 01 §3 « Cas 3+ fichiers ») :
 *   Si la prop `rows` contient >= 3 éléments, on affiche au-dessus des onglets
 *   un sélecteur de paire `[A vs B] [A vs C] [B vs C] …` (toutes les combinaisons
 *   non ordonnées). Changer de paire reload les onglets frames/audio (cache par
 *   paire). Le footer propose autant de boutons "✓ Garder X" qu'il y a de rows.
 *
 * Mode readOnly (spec 02 §5 — Modal Perceptuelle) : quand on compare 2 films
 * arbitraires (pas un vrai groupe de doublons), on cache le footer de decision
 * et on ne demande pas de groupKey. Seuls Apercu / Frames / Audio sont actifs.
 *
 * API :
 *   openDuplicateComparatorModal({
 *     runId, groupKey,
 *     rowA, rowB,              // legacy 2-fichiers
 *     rows,                    // optionnel : [{row_id, label, file_name?}, …]
 *                              //  — si >= 3, active la bar de paires
 *     title, year, comparison, onDecided
 *   })
 *   openDuplicateComparatorModal({ runId, groupKey, rowA, rowB, title, year,
 *                                  comparison, onDecided, readOnly })
 *   closeDuplicateComparatorModal()
 *
 * Cf docs/internal/design/refonte_2026_05_17/screens/01-doublons.md.
 * Cf docs/internal/design/refonte_2026_05_17/screens/02-modal-perceptuelle.md §5.
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { showToast } from "./toast.js";
// Fix audit 2026-05-24 a11y : focus trap pour eviter que Tab/Shift+Tab sorte
// du modal vers le DOM dessous. trapFocus est exporte par modal.js.
import { trapFocus } from "./modal.js";

let _overlayEl = null;
let _modalEl = null;
let _state = null;
// Audit C17 P1 : AbortController pour cleanup centralise des listeners DOM
// poses sur _modalEl/_overlayEl (idempotent + zero leak au close).
let _eventsController = null;
// Fix audit 2026-05-24 a11y : handler retourne par trapFocus(), conserve pour
// removeEventListener au closeDuplicateComparatorModal.
let _focusTrapHandler = null;
let _focusTrapTarget = null;

/* --- Helpers --- */

function _fmtSize(bytes) {
  const b = Number(bytes) || 0;
  if (b <= 0) return "—";
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} Mo`;
  return `${(b / (1024 * 1024 * 1024)).toFixed(2)} Go`;
}

function _fmtPercent(num) {
  if (num == null || !Number.isFinite(Number(num))) return "—";
  return `${(Number(num) * 100).toFixed(0)}%`;
}

function _payload(res) {
  // L'API REST renvoie {ok, ...} directement ; apiPost peut wrapper en {status, data}.
  // On tolere les deux : si res.data existe, c'est le payload, sinon res est deja le payload.
  if (!res) return {};
  return res.data && typeof res.data === "object" ? res.data : res;
}

/* --- Multi-rows (3+) helpers --- */

function _letter(i) {
  // 0 -> A, 1 -> B, ... 25 -> Z. Au-dela : AA, AB... (cas pratique <= 6).
  if (i < 26) return String.fromCharCode(65 + i);
  return `${String.fromCharCode(65 + Math.floor(i / 26) - 1)}${String.fromCharCode(65 + (i % 26))}`;
}

function _buildPairs(rowsCount) {
  // Toutes les combinaisons non ordonnees (i < j) pour rowsCount rows.
  const pairs = [];
  for (let i = 0; i < rowsCount; i += 1) {
    for (let j = i + 1; j < rowsCount; j += 1) {
      pairs.push({ idxA: i, idxB: j, key: `${i}_${j}` });
    }
  }
  return pairs;
}

function _currentPair() {
  if (!_state || !_state.pairs || _state.pairs.length === 0) return null;
  const k = _state.activePairKey;
  return _state.pairs.find((p) => p.key === k) || _state.pairs[0];
}

function _currentRowIds() {
  // Resout (rowAId, rowBId) selon la paire active dans le state multi-rows.
  if (!_state) return { rowA: null, rowB: null };
  const pair = _currentPair();
  if (pair && _state.rows && _state.rows.length >= 2) {
    return {
      rowA: _state.rows[pair.idxA].row_id,
      rowB: _state.rows[pair.idxB].row_id,
    };
  }
  return { rowA: _state.rowA, rowB: _state.rowB };
}

/* --- Header / Footer --- */

function _renderHeader() {
  const { title, year, rows } = _state;
  const subtitle = rows && rows.length >= 3 ? `${rows.length} fichiers` : "";
  return `
    <header class="duplicate-modal-header">
      <h2 class="duplicate-modal-title" id="duplicate-modal-title">
        Comparer : ${escapeHtml(title || "Sans titre")}${year ? ` (${escapeHtml(String(year))})` : ""}${subtitle ? ` — ${escapeHtml(subtitle)}` : ""}
      </h2>
      <button type="button" class="duplicate-modal-close" data-duplicate-close aria-label="Fermer">✕</button>
    </header>
  `;
}

function _renderPairsBar() {
  // Spec 01 §3 « Cas 3+ fichiers » : sélecteur paire-à-paire.
  if (!_state || !_state.rows || _state.rows.length < 3) return "";
  const pairs = _state.pairs || [];
  const active = _state.activePairKey;
  return `
    <nav class="duplicate-modal-pairs" role="tablist" aria-label="Sélection paire à comparer">
      ${pairs.map((p) => {
        const lbl = `${_letter(p.idxA)} vs ${_letter(p.idxB)}`;
        const isActive = p.key === active;
        return `
          <button type="button" role="tab"
                  class="duplicate-modal-pair${isActive ? " is-active" : ""}"
                  aria-selected="${isActive ? "true" : "false"}"
                  data-duplicate-pair="${escapeHtml(p.key)}">
            ${escapeHtml(lbl)}
          </button>
        `;
      }).join("")}
    </nav>
  `;
}

function _renderTabs() {
  const tabs = [
    { id: "apercu", label: "Aperçu" },
    { id: "frames", label: "Frames" },
    { id: "audio",  label: "Audio" },
  ];
  return `
    <nav class="duplicate-modal-tabs" role="tablist" aria-label="Onglets comparateur">
      ${tabs.map((t) => `
        <button type="button" role="tab"
                class="duplicate-modal-tab${_state.activeTab === t.id ? " is-active" : ""}"
                aria-selected="${_state.activeTab === t.id ? "true" : "false"}"
                data-duplicate-tab="${t.id}">
          ${escapeHtml(t.label)}
        </button>
      `).join("")}
    </nav>
  `;
}

function _renderFooter() {
  const { rows, rowA, rowB, decisionInFlight, readOnly } = _state;
  // Spec 02 §5 : en mode readOnly (comparaison ad-hoc depuis Modal Perceptuelle),
  // pas de boutons de decision — juste un footer informatif avec Fermer.
  if (readOnly) {
    return `
      <footer class="duplicate-modal-footer duplicate-modal-footer--readonly">
        <p class="duplicate-modal-footer-note">
          Comparaison perceptuelle (lecture seule). Pour décider d'un doublon,
          ouvrez la vue Doublons.
        </p>
        <div class="duplicate-modal-footer-actions">
          <button type="button" class="v5-btn v5-btn--ghost" data-duplicate-close>
            Fermer
          </button>
        </div>
      </footer>
    `;
  }
  const disabled = decisionInFlight ? "disabled" : "";

  let buttons = "";
  if (rows && rows.length >= 3) {
    // Spec 01 §3 « Cas 3+ fichiers » : un bouton "Garder X" par row.
    buttons = rows.map((r, i) => `
      <button type="button" class="v5-btn v5-btn--primary" data-duplicate-decide="${i}"
              data-row-id="${escapeHtml(String(r.row_id || ""))}" ${disabled}>
        ✓ Garder ${_letter(i)}
      </button>
    `).join("");
  } else {
    const rowA = _state.rowA;
    const rowB = _state.rowB;
    buttons = `
      <button type="button" class="v5-btn v5-btn--primary" data-duplicate-decide="a"
              data-row-id="${escapeHtml(String(rowA || ""))}" ${disabled}>
        ✓ Garder A
      </button>
      <button type="button" class="v5-btn v5-btn--primary" data-duplicate-decide="b"
              data-row-id="${escapeHtml(String(rowB || ""))}" ${disabled}>
        ✓ Garder B
      </button>
    `;
  }

  return `
    <footer class="duplicate-modal-footer">
      <div class="duplicate-modal-footer-actions">
        ${buttons}
        <button type="button" class="v5-btn v5-btn--ghost" data-duplicate-decide="skip" ${disabled}>
          → Skip ce groupe
        </button>
      </div>
      <p class="duplicate-modal-footer-note">
        La suppression effective se fait à l'étape Apply (sécurité torrents : les fichiers
        non-winner sont déplacés vers <code>_review/_duplicates_user_decided/</code>).
      </p>
    </footer>
  `;
}

/* --- Onglet Apercu --- */

function _criteriaList(comparison) {
  const list = Array.isArray(comparison && comparison.criteria) ? comparison.criteria : [];
  return list.map((c) => ({
    name: c.name || "?",
    label: c.label || c.name || "?",
    a: c.value_a != null ? String(c.value_a) : "—",
    b: c.value_b != null ? String(c.value_b) : "—",
    winner: String(c.winner || "").toLowerCase(),
  }));
}

function _renderApercu() {
  const { comparison } = _state;
  const c = comparison || {};
  const winner = String(c.winner || "").toLowerCase();
  const scoreA = Math.round(Number(c.total_score_a) || 0);
  const scoreB = Math.round(Number(c.total_score_b) || 0);
  const sizeA = _fmtSize(c.file_a_size);
  const sizeB = _fmtSize(c.file_b_size);
  const fileA = c.file_a_name || "Fichier A";
  const fileB = c.file_b_name || "Fichier B";
  const reco = c.recommendation || "";
  const savings = _fmtSize(c.size_savings);
  const criteria = _criteriaList(comparison);

  return `
    <div class="duplicate-modal-tab-content" data-tab="apercu">
      <div class="duplicate-apercu-headers">
        <div class="duplicate-apercu-side${winner === "a" ? " is-winner" : ""}">
          <h3 class="duplicate-apercu-side-title">
            Fichier A
            ${winner === "a" ? `<span class="duplicate-decision-badge duplicate-decision-badge--reco">🏆 Recommandé</span>` : ""}
          </h3>
          <p class="duplicate-apercu-side-filename"><code>${escapeHtml(fileA)}</code></p>
          <p class="duplicate-apercu-side-meta">Score ${scoreA}/100 · ${escapeHtml(sizeA)}</p>
        </div>
        <div class="duplicate-apercu-side${winner === "b" ? " is-winner" : ""}">
          <h3 class="duplicate-apercu-side-title">
            Fichier B
            ${winner === "b" ? `<span class="duplicate-decision-badge duplicate-decision-badge--reco">🏆 Recommandé</span>` : ""}
          </h3>
          <p class="duplicate-apercu-side-filename"><code>${escapeHtml(fileB)}</code></p>
          <p class="duplicate-apercu-side-meta">Score ${scoreB}/100 · ${escapeHtml(sizeB)}</p>
        </div>
      </div>
      ${reco ? `<p class="duplicate-apercu-reco">💡 ${escapeHtml(reco)}${c.size_savings ? ` — Économie disque : ${escapeHtml(savings)}` : ""}</p>` : ""}
      ${criteria.length > 0 ? `
        <table class="duplicate-apercu-table">
          <thead>
            <tr><th>Critère</th><th>A</th><th>B</th><th>Gagnant</th></tr>
          </thead>
          <tbody>
            ${criteria.map((row) => `
              <tr>
                <td>${escapeHtml(row.label)}</td>
                <td class="${row.winner === "a" ? "is-winner" : ""}">${escapeHtml(row.a)}</td>
                <td class="${row.winner === "b" ? "is-winner" : ""}">${escapeHtml(row.b)}</td>
                <td>${row.winner === "a" ? "A" : row.winner === "b" ? "B" : "="}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      ` : `<p class="duplicate-modal-empty">Aucun critère détaillé disponible pour cette paire.</p>`}
    </div>
  `;
}

/* --- Onglet Frames (lazy) --- */

function _renderFramesPlaceholder() {
  return `
    <div class="duplicate-modal-tab-content" data-tab="frames">
      <p class="duplicate-modal-loading">⏳ Extraction des frames en cours…</p>
    </div>
  `;
}

function _renderFramesError(msg) {
  return `
    <div class="duplicate-modal-tab-content" data-tab="frames">
      <p class="duplicate-modal-error" role="alert">${escapeHtml(msg || "Erreur frames")}</p>
      <button type="button" class="v5-btn v5-btn--secondary" data-duplicate-retry-frames>↻ Réessayer</button>
    </div>
  `;
}

function _renderFramesPayload(payload) {
  const frames = Array.isArray(payload.frames) ? payload.frames : [];
  if (frames.length === 0) {
    return `
      <div class="duplicate-modal-tab-content" data-tab="frames">
        <p class="duplicate-modal-empty">Aucune frame extraite.</p>
      </div>
    `;
  }
  return `
    <div class="duplicate-modal-tab-content" data-tab="frames">
      <p class="duplicate-modal-hint">${frames.length} paire${frames.length > 1 ? "s" : ""} de frames extraites. Les frames sont en luminance (Y plane).</p>
      <div class="duplicate-frames-grid">
        ${frames.map((f, i) => `
          <div class="duplicate-frames-row">
            <div class="duplicate-frames-col">
              <span class="duplicate-frames-label">A — ts ${escapeHtml(String(f.timestamp || i))}s</span>
              ${f.frame_a_b64 ? `<img alt="Frame A ${i}" src="data:image/png;base64,${escapeHtml(f.frame_a_b64)}" />` : `<div class="duplicate-frames-placeholder">N/A</div>`}
            </div>
            <div class="duplicate-frames-col">
              <span class="duplicate-frames-label">B — ts ${escapeHtml(String(f.timestamp || i))}s</span>
              ${f.frame_b_b64 ? `<img alt="Frame B ${i}" src="data:image/png;base64,${escapeHtml(f.frame_b_b64)}" />` : `<div class="duplicate-frames-placeholder">N/A</div>`}
            </div>
            <div class="duplicate-frames-diff">
              Δ moyen ${f.mean_diff != null ? Number(f.mean_diff).toFixed(1) : "—"} / 255
            </div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

async function _loadFramesTab() {
  if (!_state) return;
  const pair = _currentPair();
  const pairKey = pair ? pair.key : "default";
  // Cache par paire (cas 3+ fichiers).
  if (!_state.framesLoadedByPair) _state.framesLoadedByPair = {};
  if (_state.framesLoadedByPair[pairKey]) return;
  _state.framesLoadedByPair[pairKey] = true;
  const tabContent = _modalEl && _modalEl.querySelector('[data-tab="frames"]');
  if (!tabContent) return;
  const { rowA, rowB } = _currentRowIds();
  try {
    const res = await apiPost("quality/get_perceptual_compare_frames", {
      run_id: _state.runId,
      row_id_a: rowA,
      row_id_b: rowB,
      options: { max_frames: 3 },
    });
    const data = _payload(res);
    if (data.ok === false) {
      _state.framesLoadedByPair[pairKey] = false;
      const msg = data.message || data.error || "Échec extraction frames";
      _replaceTabContent("frames", _renderFramesError(msg));
      return;
    }
    _replaceTabContent("frames", _renderFramesPayload(data));
  } catch (err) {
    _state.framesLoadedByPair[pairKey] = false;
    _replaceTabContent("frames", _renderFramesError(err && err.message ? err.message : String(err)));
  }
}

/* --- Onglet Audio (lazy) --- */

function _renderAudioPlaceholder() {
  return `
    <div class="duplicate-modal-tab-content" data-tab="audio">
      <p class="duplicate-modal-loading">⏳ Extraction audio en cours (ffmpeg)…</p>
    </div>
  `;
}

function _renderAudioError(msg) {
  return `
    <div class="duplicate-modal-tab-content" data-tab="audio">
      <p class="duplicate-modal-error" role="alert">${escapeHtml(msg || "Erreur audio")}</p>
      <button type="button" class="v5-btn v5-btn--secondary" data-duplicate-retry-audio>↻ Réessayer</button>
    </div>
  `;
}

function _renderAudioPayload(payload) {
  const mime = payload.audio_mime || "audio/mpeg";
  const ts = payload.timestamp_s != null ? Number(payload.timestamp_s).toFixed(0) : "—";
  const dur = payload.duration_s != null ? Number(payload.duration_s) : 10;
  const wa = payload.waveform_a_b64;
  const wb = payload.waveform_b_b64;
  const aa = payload.audio_a_b64;
  const ab = payload.audio_b_b64;
  return `
    <div class="duplicate-modal-tab-content" data-tab="audio">
      <p class="duplicate-modal-hint">Extrait de ${escapeHtml(String(dur))}s au timestamp ${escapeHtml(String(ts))}s.</p>
      <div class="duplicate-audio-grid">
        <div class="duplicate-audio-player">
          <h4>A</h4>
          ${wa ? `<img class="duplicate-audio-waveform" alt="Waveform A" src="data:image/png;base64,${escapeHtml(wa)}" />` : `<div class="duplicate-audio-waveform duplicate-audio-waveform--empty">Waveform A indisponible</div>`}
          ${aa ? `<audio controls preload="none" src="data:${escapeHtml(mime)};base64,${escapeHtml(aa)}"></audio>` : `<p class="duplicate-modal-empty">Audio A indisponible</p>`}
        </div>
        <div class="duplicate-audio-player">
          <h4>B</h4>
          ${wb ? `<img class="duplicate-audio-waveform" alt="Waveform B" src="data:image/png;base64,${escapeHtml(wb)}" />` : `<div class="duplicate-audio-waveform duplicate-audio-waveform--empty">Waveform B indisponible</div>`}
          ${ab ? `<audio controls preload="none" src="data:${escapeHtml(mime)};base64,${escapeHtml(ab)}"></audio>` : `<p class="duplicate-modal-empty">Audio B indisponible</p>`}
        </div>
      </div>
    </div>
  `;
}

async function _loadAudioTab() {
  if (!_state) return;
  const pair = _currentPair();
  const pairKey = pair ? pair.key : "default";
  if (!_state.audioLoadedByPair) _state.audioLoadedByPair = {};
  if (_state.audioLoadedByPair[pairKey]) return;
  _state.audioLoadedByPair[pairKey] = true;
  const tabContent = _modalEl && _modalEl.querySelector('[data-tab="audio"]');
  if (!tabContent) return;
  const { rowA, rowB } = _currentRowIds();
  try {
    const res = await apiPost("quality/get_perceptual_compare_audio", {
      run_id: _state.runId,
      row_id_a: rowA,
      row_id_b: rowB,
      options: { duration_s: 10 },
    });
    const data = _payload(res);
    if (data.ok === false) {
      _state.audioLoadedByPair[pairKey] = false;
      _replaceTabContent("audio", _renderAudioError(data.message || data.error || "Échec extraction audio"));
      return;
    }
    _replaceTabContent("audio", _renderAudioPayload(data));
  } catch (err) {
    _state.audioLoadedByPair[pairKey] = false;
    _replaceTabContent("audio", _renderAudioError(err && err.message ? err.message : String(err)));
  }
}

/* --- Tabs management --- */

function _renderTabContent() {
  switch (_state.activeTab) {
    case "frames":
      return _renderFramesPlaceholder();
    case "audio":
      return _renderAudioPlaceholder();
    default:
      return _renderApercu();
  }
}

function _replaceTabContent(tab, html) {
  if (!_modalEl) return;
  const wrapper = _modalEl.querySelector("[data-duplicate-tabbody]");
  if (!wrapper) return;
  wrapper.innerHTML = html;
  _bindTabContentEvents();
}

function _switchTab(tabId) {
  if (!_state) return;
  if (_state.activeTab === tabId) return;
  _state.activeTab = tabId;
  // Re-render tab nav
  const tabsNav = _modalEl.querySelector(".duplicate-modal-tabs");
  if (tabsNav) {
    tabsNav.outerHTML = _renderTabs();
    _bindTabNavEvents();
  }
  // Re-render tab body
  _replaceTabContent(tabId, _renderTabContent());
  if (tabId === "frames") void _loadFramesTab();
  else if (tabId === "audio") void _loadAudioTab();
}

function _switchPair(pairKey) {
  if (!_state) return;
  if (_state.activePairKey === pairKey) return;
  _state.activePairKey = pairKey;
  // Re-render pairs bar
  const bar = _modalEl.querySelector(".duplicate-modal-pairs");
  if (bar) {
    bar.outerHTML = _renderPairsBar();
    _bindPairsBarEvents();
  }
  // Re-render le body de l'onglet actif
  _replaceTabContent(_state.activeTab, _renderTabContent());
  if (_state.activeTab === "frames") void _loadFramesTab();
  else if (_state.activeTab === "audio") void _loadAudioTab();
}

/* --- Decision (mark_duplicate_winner) --- */

async function _decideWinner(side) {
  if (!_state || _state.decisionInFlight) return;
  if (side === "skip") {
    closeDuplicateComparatorModal();
    return;
  }

  // Mode multi-rows : `side` est un index numerique 0..N
  let winnerRow = null;
  let sideLabel = "?";
  let winnerIndex = null;
  if (_state.rows && _state.rows.length >= 3) {
    const idx = Number(side);
    if (Number.isFinite(idx) && idx >= 0 && idx < _state.rows.length) {
      winnerRow = _state.rows[idx].row_id;
      sideLabel = _letter(idx);
      winnerIndex = idx;
    }
  } else if (side === "a" || side === "b") {
    winnerRow = side === "a" ? _state.rowA : _state.rowB;
    sideLabel = side === "a" ? "A" : "B";
  }

  if (!winnerRow) {
    showToast({ type: "error", text: "Row ID winner manquant" });
    return;
  }
  _state.decisionInFlight = true;
  _refreshFooter();
  try {
    const res = await apiPost("run/mark_duplicate_winner", {
      run_id: _state.runId,
      group_key: _state.groupKey,
      winner_row_id: winnerRow,
      notes: null,
    });
    const data = _payload(res);
    if (data.ok === false) {
      showToast({ type: "error", text: data.message || data.error || "Échec décision" });
      _state.decisionInFlight = false;
      _refreshFooter();
      return;
    }
    const savings = data.size_savings || (_state.comparison && _state.comparison.size_savings) || 0;
    let toastText = `✓ Décidé : Garder ${sideLabel}`;
    if (savings > 0) {
      toastText += ` · ${_fmtSize(savings)} récupérables`;
    }
    showToast({ type: "success", text: toastText });
    // Callback pour que la vue parente actualise la carte sans recharger
    if (typeof _state.onDecided === "function") {
      try {
        _state.onDecided({
          groupKey: _state.groupKey,
          // legacy : winnerSide = "a"|"b". En 3+ : on expose aussi winnerIndex.
          winnerSide: side === "a" || side === "b" ? side : "a",
          winnerIndex,
          winnerRowId: winnerRow,
          payload: data,
        });
      } catch (cbErr) {
        console.warn("[duplicate-comparator-modal] onDecided callback error:", cbErr);
      }
    }
    closeDuplicateComparatorModal();
  } catch (err) {
    showToast({ type: "error", text: err && err.message ? err.message : String(err) });
    _state.decisionInFlight = false;
    _refreshFooter();
  }
}

function _refreshFooter() {
  if (!_modalEl) return;
  const footer = _modalEl.querySelector(".duplicate-modal-footer");
  if (!footer) return;
  footer.outerHTML = _renderFooter();
  _bindFooterEvents();
}

/* --- DOM management --- */

function _ensureOverlay() {
  if (_overlayEl) return;
  // Audit C17 P1 : controller frais pour ce nouveau mount du modal.
  if (_eventsController) {
    try { _eventsController.abort(); } catch (_e) { /* noop */ }
  }
  _eventsController = new AbortController();
  const opts = { signal: _eventsController.signal };

  _overlayEl = document.createElement("div");
  _overlayEl.className = "duplicate-modal-overlay";
  _overlayEl.setAttribute("role", "dialog");
  _overlayEl.setAttribute("aria-modal", "true");
  _overlayEl.setAttribute("aria-labelledby", "duplicate-modal-title");
  _overlayEl.addEventListener("click", (ev) => {
    if (ev.target === _overlayEl) closeDuplicateComparatorModal();
  }, opts);
  _modalEl = document.createElement("div");
  _modalEl.className = "duplicate-modal";
  _overlayEl.appendChild(_modalEl);
  document.body.appendChild(_overlayEl);
  document.addEventListener("keydown", _onKeydown, opts);
  // Fix audit 2026-05-24 a11y : capture Tab/Shift+Tab dans l'overlay.
  _focusTrapTarget = _overlayEl;
  _focusTrapHandler = trapFocus(_overlayEl);
}

function _onKeydown(ev) {
  if (ev.key === "Escape" && _overlayEl) {
    closeDuplicateComparatorModal();
  }
}

// Audit C17 P1 : tous les listeners poses ici utilisent _eventsController.signal,
// abort() au closeDuplicateComparatorModal -> zero leak meme si _renderModal()
// est rappele plusieurs fois (switch pair / decide -> re-render).

function _bindTabNavEvents() {
  if (!_modalEl) return;
  const opts = _eventsController ? { signal: _eventsController.signal } : undefined;
  _modalEl.querySelectorAll("[data-duplicate-tab]").forEach((btn) => {
    btn.addEventListener("click", () => _switchTab(btn.dataset.duplicateTab), opts);
  });
}

function _bindPairsBarEvents() {
  if (!_modalEl) return;
  const opts = _eventsController ? { signal: _eventsController.signal } : undefined;
  _modalEl.querySelectorAll("[data-duplicate-pair]").forEach((btn) => {
    btn.addEventListener("click", () => _switchPair(btn.dataset.duplicatePair), opts);
  });
}

function _bindTabContentEvents() {
  if (!_modalEl) return;
  const opts = _eventsController ? { signal: _eventsController.signal } : undefined;
  const retryFrames = _modalEl.querySelector("[data-duplicate-retry-frames]");
  if (retryFrames) {
    retryFrames.addEventListener("click", () => {
      const pair = _currentPair();
      const pairKey = pair ? pair.key : "default";
      if (_state.framesLoadedByPair) _state.framesLoadedByPair[pairKey] = false;
      _replaceTabContent("frames", _renderFramesPlaceholder());
      void _loadFramesTab();
    }, opts);
  }
  const retryAudio = _modalEl.querySelector("[data-duplicate-retry-audio]");
  if (retryAudio) {
    retryAudio.addEventListener("click", () => {
      const pair = _currentPair();
      const pairKey = pair ? pair.key : "default";
      if (_state.audioLoadedByPair) _state.audioLoadedByPair[pairKey] = false;
      _replaceTabContent("audio", _renderAudioPlaceholder());
      void _loadAudioTab();
    }, opts);
  }
}

function _bindFooterEvents() {
  if (!_modalEl) return;
  const opts = _eventsController ? { signal: _eventsController.signal } : undefined;
  _modalEl.querySelectorAll("[data-duplicate-decide]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const side = btn.dataset.duplicateDecide;
      void _decideWinner(side);
    }, opts);
  });
}

function _bindEvents() {
  if (!_modalEl) return;
  const opts = _eventsController ? { signal: _eventsController.signal } : undefined;
  _modalEl.querySelectorAll("[data-duplicate-close]").forEach((btn) => {
    btn.addEventListener("click", closeDuplicateComparatorModal, opts);
  });
  _bindTabNavEvents();
  _bindPairsBarEvents();
  _bindTabContentEvents();
  _bindFooterEvents();
}

function _renderModal() {
  if (!_modalEl) return;
  _modalEl.innerHTML = `
    ${_renderHeader()}
    ${_renderPairsBar()}
    ${_renderTabs()}
    <div class="duplicate-modal-body" data-duplicate-tabbody>
      ${_renderTabContent()}
    </div>
    ${_renderFooter()}
  `;
  _bindEvents();
}

/* --- API publique --- */

export function openDuplicateComparatorModal(opts) {
  const o = opts || {};
  const readOnly = o.readOnly === true;
  // En mode normal (vue Doublons), groupKey est obligatoire car requis par
  // mark_duplicate_winner. En mode readOnly (Modal Perceptuelle §5), on
  // tolere son absence puisqu'on ne propose pas de decision.
  if (!o.runId || !o.rowA || !o.rowB || (!readOnly && !o.groupKey)) {
    console.warn("[duplicate-comparator-modal] runId/rowA/rowB requis (groupKey requis hors readOnly)");
    return;
  }

  // Normalisation rows / rowA / rowB.
  // - Si `rows` (array) fournie et >= 2, on l'utilise comme source de verite.
  // - Sinon on fallback sur rowA/rowB legacy.
  let rows = null;
  if (Array.isArray(o.rows) && o.rows.length >= 2) {
    rows = o.rows.map((r, i) => ({
      row_id: String(r.row_id || r.rowId || ""),
      label: r.label || _letter(i),
      file_name: r.file_name || r.fileName || "",
    })).filter((r) => r.row_id);
  }

  const rowA = o.rowA || (rows && rows[0] ? rows[0].row_id : null);
  const rowB = o.rowB || (rows && rows[1] ? rows[1].row_id : null);

  if (!rowA || !rowB) {
    console.warn("[duplicate-comparator-modal] rowA/rowB requis (ou rows[0/1])");
    return;
  }

  const pairs = rows && rows.length >= 3 ? _buildPairs(rows.length) : [];
  const activePairKey = pairs.length > 0 ? pairs[0].key : null;

  _state = {
    runId: String(o.runId),
    groupKey: o.groupKey != null ? String(o.groupKey) : "",
    rowA: String(rowA),
    rowB: String(rowB),
    rows: rows && rows.length >= 2 ? rows : null,
    pairs,
    activePairKey,
    title: o.title || "",
    year: o.year || "",
    comparison: o.comparison || null,
    onDecided: typeof o.onDecided === "function" ? o.onDecided : null,
    readOnly,
    activeTab: "apercu",
    framesLoadedByPair: {},
    audioLoadedByPair: {},
    decisionInFlight: false,
  };
  _ensureOverlay();
  document.body.classList.add("modal-open");
  _renderModal();
}

export function closeDuplicateComparatorModal() {
  // Audit C17 P1 : abort() libere tous les listeners en une fois (overlay click,
  // document keydown Escape, tab-nav, pair-bar, footer decide, tab-content retries).
  if (_eventsController) {
    try { _eventsController.abort(); } catch (_e) { /* noop */ }
    _eventsController = null;
  }
  // Fix audit 2026-05-24 a11y : libere le focus trap installe par _ensureOverlay
  // (handler retourne par trapFocus n'est pas couvert par _eventsController).
  if (_focusTrapHandler && _focusTrapTarget) {
    try { _focusTrapTarget.removeEventListener("keydown", _focusTrapHandler); } catch (_e) { /* noop */ }
  }
  _focusTrapHandler = null;
  _focusTrapTarget = null;
  if (_overlayEl) {
    // removeEventListener garde pour compat ascendante au cas ou abort() ne
    // serait pas supporte (browsers < 2022). Idempotent.
    document.removeEventListener("keydown", _onKeydown);
    _overlayEl.remove();
    _overlayEl = null;
    _modalEl = null;
  }
  _state = null;
  document.body.classList.remove("modal-open");
}
