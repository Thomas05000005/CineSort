/* components/duplicate-comparator-modal.js — Modal Comparateur Doublons (spec 01 §3).
 *
 * Overlay fullscreen 90vw avec 3 onglets :
 *   - Apercu  : tableau critères côte à côte (codec/source/résolution/...)
 *   - Frames  : 3 paires de frames PNG via quality/get_perceptual_compare_frames (lazy)
 *   - Audio   : waveforms PNG + clips MP3 via quality/get_perceptual_compare_audio (lazy)
 *
 * Footer : boutons "✓ Garder A", "✓ Garder B", "→ Skip" cables sur
 * run/mark_duplicate_winner.
 *
 * API :
 *   openDuplicateComparatorModal({ runId, groupKey, rowA, rowB, title, year,
 *                                  comparison, onDecided })
 *   closeDuplicateComparatorModal()
 *
 * Cf docs/internal/design/refonte_2026_05_17/screens/01-doublons.md.
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { showToast } from "./toast.js";

let _overlayEl = null;
let _modalEl = null;
let _state = null;

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

/* --- Header / Footer --- */

function _renderHeader() {
  const { title, year } = _state;
  return `
    <header class="duplicate-modal-header">
      <h2 class="duplicate-modal-title" id="duplicate-modal-title">
        Comparer : ${escapeHtml(title || "Sans titre")}${year ? ` (${escapeHtml(String(year))})` : ""}
      </h2>
      <button type="button" class="duplicate-modal-close" data-duplicate-close aria-label="Fermer">✕</button>
    </header>
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
  const { rowA, rowB, decisionInFlight } = _state;
  const disabled = decisionInFlight ? "disabled" : "";
  return `
    <footer class="duplicate-modal-footer">
      <div class="duplicate-modal-footer-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-duplicate-decide="a"
                data-row-id="${escapeHtml(String(rowA || ""))}" ${disabled}>
          ✓ Garder A
        </button>
        <button type="button" class="v5-btn v5-btn--primary" data-duplicate-decide="b"
                data-row-id="${escapeHtml(String(rowB || ""))}" ${disabled}>
          ✓ Garder B
        </button>
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
  if (_state.framesLoaded) return; // cache
  _state.framesLoaded = true;
  const tabContent = _modalEl && _modalEl.querySelector('[data-tab="frames"]');
  if (!tabContent) return;
  try {
    const res = await apiPost("quality/get_perceptual_compare_frames", {
      run_id: _state.runId,
      row_id_a: _state.rowA,
      row_id_b: _state.rowB,
      options: { max_frames: 3 },
    });
    const data = _payload(res);
    if (data.ok === false) {
      _state.framesLoaded = false;
      const msg = data.message || data.error || "Échec extraction frames";
      _replaceTabContent("frames", _renderFramesError(msg));
      return;
    }
    _replaceTabContent("frames", _renderFramesPayload(data));
  } catch (err) {
    _state.framesLoaded = false;
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
  if (_state.audioLoaded) return;
  _state.audioLoaded = true;
  const tabContent = _modalEl && _modalEl.querySelector('[data-tab="audio"]');
  if (!tabContent) return;
  try {
    const res = await apiPost("quality/get_perceptual_compare_audio", {
      run_id: _state.runId,
      row_id_a: _state.rowA,
      row_id_b: _state.rowB,
      options: { duration_s: 10 },
    });
    const data = _payload(res);
    if (data.ok === false) {
      _state.audioLoaded = false;
      _replaceTabContent("audio", _renderAudioError(data.message || data.error || "Échec extraction audio"));
      return;
    }
    _replaceTabContent("audio", _renderAudioPayload(data));
  } catch (err) {
    _state.audioLoaded = false;
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

/* --- Decision (mark_duplicate_winner) --- */

async function _decideWinner(side) {
  if (!_state || _state.decisionInFlight) return;
  if (side === "skip") {
    closeDuplicateComparatorModal();
    return;
  }
  const winnerRow = side === "a" ? _state.rowA : _state.rowB;
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
    const sideLabel = side === "a" ? "A" : "B";
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
          winnerSide: side,
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
  _overlayEl = document.createElement("div");
  _overlayEl.className = "duplicate-modal-overlay";
  _overlayEl.setAttribute("role", "dialog");
  _overlayEl.setAttribute("aria-modal", "true");
  _overlayEl.setAttribute("aria-labelledby", "duplicate-modal-title");
  _overlayEl.addEventListener("click", (ev) => {
    if (ev.target === _overlayEl) closeDuplicateComparatorModal();
  });
  _modalEl = document.createElement("div");
  _modalEl.className = "duplicate-modal";
  _overlayEl.appendChild(_modalEl);
  document.body.appendChild(_overlayEl);
  document.addEventListener("keydown", _onKeydown);
}

function _onKeydown(ev) {
  if (ev.key === "Escape" && _overlayEl) {
    closeDuplicateComparatorModal();
  }
}

function _bindTabNavEvents() {
  if (!_modalEl) return;
  _modalEl.querySelectorAll("[data-duplicate-tab]").forEach((btn) => {
    btn.addEventListener("click", () => _switchTab(btn.dataset.duplicateTab));
  });
}

function _bindTabContentEvents() {
  if (!_modalEl) return;
  const retryFrames = _modalEl.querySelector("[data-duplicate-retry-frames]");
  if (retryFrames) {
    retryFrames.addEventListener("click", () => {
      _state.framesLoaded = false;
      _replaceTabContent("frames", _renderFramesPlaceholder());
      void _loadFramesTab();
    });
  }
  const retryAudio = _modalEl.querySelector("[data-duplicate-retry-audio]");
  if (retryAudio) {
    retryAudio.addEventListener("click", () => {
      _state.audioLoaded = false;
      _replaceTabContent("audio", _renderAudioPlaceholder());
      void _loadAudioTab();
    });
  }
}

function _bindFooterEvents() {
  if (!_modalEl) return;
  _modalEl.querySelectorAll("[data-duplicate-decide]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const side = btn.dataset.duplicateDecide;
      void _decideWinner(side);
    });
  });
}

function _bindEvents() {
  if (!_modalEl) return;
  _modalEl.querySelectorAll("[data-duplicate-close]").forEach((btn) => {
    btn.addEventListener("click", closeDuplicateComparatorModal);
  });
  _bindTabNavEvents();
  _bindTabContentEvents();
  _bindFooterEvents();
}

function _renderModal() {
  if (!_modalEl) return;
  _modalEl.innerHTML = `
    ${_renderHeader()}
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
  if (!o.runId || !o.groupKey || !o.rowA || !o.rowB) {
    console.warn("[duplicate-comparator-modal] runId/groupKey/rowA/rowB requis");
    return;
  }
  _state = {
    runId: String(o.runId),
    groupKey: String(o.groupKey),
    rowA: String(o.rowA),
    rowB: String(o.rowB),
    title: o.title || "",
    year: o.year || "",
    comparison: o.comparison || null,
    onDecided: typeof o.onDecided === "function" ? o.onDecided : null,
    activeTab: "apercu",
    framesLoaded: false,
    audioLoaded: false,
    decisionInFlight: false,
  };
  _ensureOverlay();
  document.body.classList.add("modal-open");
  _renderModal();
}

export function closeDuplicateComparatorModal() {
  if (_overlayEl) {
    document.removeEventListener("keydown", _onKeydown);
    _overlayEl.remove();
    _overlayEl = null;
    _modalEl = null;
  }
  _state = null;
  document.body.classList.remove("modal-open");
}
