/* components/perceptual-modal.js — Modal Analyse Perceptuelle (Phase 3.2, spec 02).
 *
 * Mode B (overlay) : modal centree fullscreen sur fond noir.
 * Mode A (inspecteur elargi) : implementation differee (reportee a la spec
 *   inspecteur-droit). Pour l'instant on rend toujours en overlay.
 *
 * API :
 *   openPerceptualModal({ rowId, runId, rowTitle })
 *   closePerceptualModal()
 *
 * Source des donnees : quality/get_perceptual_details(run_id, row_id).
 * Toutes les metriques sont deja persistees, on lit pure DB. Si missing,
 * on affiche un CTA pour lancer le calcul via get_perceptual_report.
 *
 * 5 etats spec 02 §4 :
 *   4.1 normal      -> details complet
 *   4.2 missing     -> CTA "Lancer l'analyse"
 *   4.3 disabled    -> redirige vers Parametres
 *   4.4 no_ffmpeg   -> redirige vers Parametres > Outils video
 *   4.5 partial     -> rendu normal avec champs "Non calcule" + [Completer]
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { humanize, severityForTier, SCORE_V2_COMPONENTS } from "../core/perceptual-labels.js";

let _overlayEl = null;
let _modalEl = null;
let _state = null;

/* --- Helpers --- */

function _fmtNumber(value, decimals = 2) {
  if (value == null || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(decimals);
}

function _fmtKbps(value) {
  if (value == null || value === 0) return "—";
  return `${Math.round(Number(value))} kbps`;
}

function _fmtKhz(hz) {
  if (hz == null || hz === 0) return "—";
  return `${(Number(hz) / 1000).toFixed(1)} kHz`;
}

function _scoreBar(score, total = 100) {
  const n = Math.max(0, Math.min(total, Number(score) || 0));
  const pct = total > 0 ? Math.round((n / total) * 100) : 0;
  return `<div class="perceptual-bar"><div class="perceptual-bar-fill" style="width:${pct}%"></div></div>`;
}

/* --- Rendering --- */

function _renderHeader(title) {
  return `
    <header class="perceptual-modal-header">
      <h2 class="perceptual-modal-title">
        Analyse perceptuelle
        ${title ? `<span class="perceptual-modal-subtitle">— ${escapeHtml(title)}</span>` : ""}
      </h2>
      <button type="button" class="perceptual-modal-close" data-perceptual-close aria-label="Fermer">✕</button>
    </header>
  `;
}

function _renderFooter(analyzedAt, canRelaunch) {
  return `
    <footer class="perceptual-modal-footer">
      <span class="perceptual-modal-meta">
        ${analyzedAt ? `Dernière analyse : ${escapeHtml(String(analyzedAt))}` : "Non analysé"}
      </span>
      <div class="perceptual-modal-actions">
        ${canRelaunch ? `<button type="button" class="v5-btn v5-btn--secondary" data-perceptual-action="relaunch">↻ Relancer l'analyse</button>` : ""}
        <button type="button" class="v5-btn v5-btn--ghost" data-perceptual-close>Fermer</button>
      </div>
    </footer>
  `;
}

function _renderMissing(title) {
  return `
    ${_renderHeader(title)}
    <div class="perceptual-modal-body perceptual-modal-state perceptual-modal-state--missing">
      <p class="perceptual-state-icon" aria-hidden="true">📊</p>
      <h3>Aucune analyse pour ce film</h3>
      <p>Calcul de :</p>
      <ul>
        <li>Score V2 (composante par composante)</li>
        <li>SSIM self-ref (détection faux upscale)</li>
        <li>Grain analysis (film stock vs artefacts)</li>
        <li>Empreinte Chromaprint (audio)</li>
        <li>Cutoff spectral (détection lossy)</li>
      </ul>
      <p class="perceptual-state-eta">Estimation : ~30 secondes</p>
      <button type="button" class="v5-btn v5-btn--primary" data-perceptual-action="launch">▶ Lancer l'analyse maintenant</button>
    </div>
    ${_renderFooter(null, false)}
  `;
}

function _renderDisabled(title) {
  return `
    ${_renderHeader(title)}
    <div class="perceptual-modal-body perceptual-modal-state perceptual-modal-state--disabled">
      <p class="perceptual-state-icon" aria-hidden="true">ℹ️</p>
      <h3>Analyse perceptuelle désactivée</h3>
      <p>Activez le module dans les Paramètres pour utiliser cette fonctionnalité.</p>
      <button type="button" class="v5-btn v5-btn--primary" data-perceptual-action="open-settings">Aller aux Paramètres</button>
    </div>
    ${_renderFooter(null, false)}
  `;
}

function _renderNoFfmpeg(title) {
  return `
    ${_renderHeader(title)}
    <div class="perceptual-modal-body perceptual-modal-state perceptual-modal-state--no-ffmpeg">
      <p class="perceptual-state-icon" aria-hidden="true">⚠️</p>
      <h3>ffmpeg est introuvable</h3>
      <p>L'analyse perceptuelle nécessite ffmpeg pour :</p>
      <ul>
        <li>Extraction de frames clés</li>
        <li>Calcul d'empreinte Chromaprint</li>
        <li>Analyse spectrale audio</li>
      </ul>
      <button type="button" class="v5-btn v5-btn--primary" data-perceptual-action="open-settings">Installer depuis Paramètres &gt; Outils vidéo</button>
    </div>
    ${_renderFooter(null, false)}
  `;
}

function _renderError(title, msg) {
  return `
    ${_renderHeader(title)}
    <div class="perceptual-modal-body perceptual-modal-state perceptual-modal-state--error" role="alert">
      <p class="perceptual-state-icon" aria-hidden="true">🛑</p>
      <h3>Erreur de chargement</h3>
      <p>${escapeHtml(msg || "Erreur inconnue")}</p>
    </div>
    ${_renderFooter(null, false)}
  `;
}

function _renderScoreSection(d) {
  const score = d.global_score_v2 != null ? Math.round(Number(d.global_score_v2)) : null;
  const tier = String(d.tier_v2 || d.global_tier_v2 || "unknown").toLowerCase();
  const tierLabel = humanize(tier, tier);
  const sev = severityForTier(tier);
  const visualScore = d.visual_score != null ? Number(d.visual_score) : null;
  const audioScore = d.audio_score != null ? Number(d.audio_score) : null;
  const verdict = humanize(d.lossy_verdict) ||
                  (d.cross_verdicts && d.cross_verdicts[0] && d.cross_verdicts[0].label) || "—";

  return `
    <section class="perceptual-section perceptual-section--score" data-section="score">
      <h3 class="perceptual-section-title">📊 Score global &amp; tier</h3>
      <div class="perceptual-score-grid">
        <div class="perceptual-score-circle perceptual-score-circle--${escapeHtml(sev)}">
          <span class="perceptual-score-value">${score != null ? score : "—"}</span>
          <span class="perceptual-score-total">/100</span>
        </div>
        <div class="perceptual-score-bars">
          <div class="perceptual-score-row">
            <span class="perceptual-score-label">Tier</span>
            <strong class="perceptual-score-tier perceptual-tier--${escapeHtml(tier)}">${escapeHtml(tierLabel)}</strong>
          </div>
          ${visualScore != null ? `
          <div class="perceptual-score-row">
            <span class="perceptual-score-label">Vidéo</span>
            ${_scoreBar(visualScore)}
            <span class="perceptual-score-value-sm">${Math.round(visualScore)}/100</span>
          </div>` : ""}
          ${audioScore != null ? `
          <div class="perceptual-score-row">
            <span class="perceptual-score-label">Audio</span>
            ${_scoreBar(audioScore)}
            <span class="perceptual-score-value-sm">${Math.round(audioScore)}/100</span>
          </div>` : ""}
        </div>
      </div>
      <p class="perceptual-verdict">${escapeHtml(verdict)}</p>
    </section>
  `;
}

function _renderVideoSection(d) {
  const ssim = d.ssim_self_ref != null ? _fmtNumber(d.ssim_self_ref, 2) : null;
  const ssimVerdict = ssim != null && Number(ssim) >= 0.85 ? "authentique (>0.85 = vrai natif)" : "potentiel upscale";
  const upscale = humanize(d.upscale_verdict, null);
  const grain = (d.grain_analysis && humanize(d.grain_analysis.verdict_label)) ||
                (d.grain_analysis && d.grain_analysis.verdict_label) || "—";
  const hdrFormat = d.hdr_analysis ? (d.hdr_analysis.hdr_format || (d.hdr_analysis.is_hdr ? "HDR" : "sdr")) : "sdr";
  const hdrLabel = humanize(String(hdrFormat).toLowerCase(), hdrFormat);
  const codec = String(d.codec || "—").toUpperCase();
  const bitDepth = d.bit_depth != null ? `${d.bit_depth}-bit` : "";
  const bitrate = d.bitrate_kbps != null ? _fmtKbps(d.bitrate_kbps) : "—";

  return `
    <section class="perceptual-section" data-section="video">
      <h3 class="perceptual-section-title">🎬 Métriques vidéo</h3>
      <dl class="perceptual-dl">
        ${ssim != null ? `<dt>SSIM self-ref</dt><dd>${escapeHtml(ssim)} → ${escapeHtml(ssimVerdict)}</dd>` : ""}
        ${upscale ? `<dt>Faux 4K détecté</dt><dd>${escapeHtml(upscale)}</dd>` : ""}
        <dt>Grain</dt><dd>${escapeHtml(grain)}</dd>
        <dt>HDR</dt><dd>${escapeHtml(hdrLabel)}</dd>
        <dt>Codec</dt><dd>${escapeHtml(codec)} ${escapeHtml(bitDepth)}</dd>
        <dt>Bitrate</dt><dd>${escapeHtml(bitrate)}</dd>
      </dl>
    </section>
  `;
}

function _renderAudioSection(d) {
  const fp = d.audio_fingerprint || "";
  const cutoff = _fmtKhz(d.spectral_cutoff_hz);
  const lossyVerdict = humanize(d.lossy_verdict, "—");
  const tracks = Array.isArray(d.audio_streams) ? d.audio_streams : [];
  const dynamicRange = d.audio_perceptual && d.audio_perceptual.dynamic_range_db;

  return `
    <section class="perceptual-section" data-section="audio">
      <h3 class="perceptual-section-title">🔊 Métriques audio</h3>
      ${fp ? `
        <div class="perceptual-audio-fp">
          <span class="perceptual-audio-fp-label">Empreinte Chromaprint :</span>
          <code class="perceptual-audio-fp-value" data-perceptual-fp>${escapeHtml(fp.slice(0, 80))}${fp.length > 80 ? "…" : ""}</code>
          <button type="button" class="v5-btn v5-btn--xs v5-btn--ghost" data-perceptual-copy-fp title="Copier l'empreinte complète">📋 Copier</button>
        </div>
      ` : ""}
      <dl class="perceptual-dl">
        <dt>Cutoff spectral</dt><dd>${escapeHtml(cutoff)}</dd>
        <dt>Verdict audio</dt><dd>${escapeHtml(lossyVerdict)}</dd>
        ${tracks.length > 0 ? `
          <dt>Pistes</dt>
          <dd>
            <ul class="perceptual-audio-tracks">
              ${tracks.slice(0, 5).map((t) => `
                <li>${escapeHtml((t.language || "?").toUpperCase())}
                    ${escapeHtml((t.codec || "?").toUpperCase())}
                    ${t.channels ? escapeHtml(String(t.channels)) + " ch" : ""}
                    ${t.bitrate_kbps ? "@ " + _fmtKbps(t.bitrate_kbps) : ""}</li>
              `).join("")}
            </ul>
          </dd>` : ""}
        ${dynamicRange != null ? `
          <dt>Dynamique</dt>
          <dd>${escapeHtml(_fmtNumber(dynamicRange, 1))} dB</dd>` : ""}
      </dl>
    </section>
  `;
}

function _renderBreakdownSection(d) {
  const breakdown = Array.isArray(d.breakdown) ? d.breakdown : null;
  if (!breakdown || breakdown.length === 0) {
    // Reconstruction approximative avec SCORE_V2_COMPONENTS si pas de breakdown DB
    return `
      <section class="perceptual-section" data-section="breakdown">
        <h3 class="perceptual-section-title">📐 Composantes du Score V2</h3>
        <p class="perceptual-empty">Détail composantes indisponible dans cette passe.</p>
        <ul class="perceptual-breakdown-weights">
          ${SCORE_V2_COMPONENTS.map((c) => `
            <li><span class="perceptual-breakdown-name">${escapeHtml(c.label)}</span>
                <span class="perceptual-breakdown-weight">× ${(c.weight * 100).toFixed(0)}%</span></li>
          `).join("")}
        </ul>
      </section>
    `;
  }
  const total = breakdown.reduce((sum, row) => sum + (Number(row.points) || 0), 0);
  return `
    <section class="perceptual-section" data-section="breakdown">
      <h3 class="perceptual-section-title">📐 Breakdown détaillé (Score V2)</h3>
      <table class="perceptual-breakdown-table">
        <thead><tr><th>Composante</th><th>Valeur</th><th>Statut</th><th>Points</th></tr></thead>
        <tbody>
          ${breakdown.map((row) => `
            <tr>
              <td>${escapeHtml(row.component || "?")} <span class="perceptual-weight">× ${row.weight != null ? Number(row.weight).toFixed(2) : "?"}</span></td>
              <td>${escapeHtml(row.value_label || "—")}</td>
              <td><span class="perceptual-status perceptual-status--${escapeHtml(row.status || "info")}">${escapeHtml(row.status || "—")}</span></td>
              <td class="perceptual-breakdown-points">${row.points != null ? Math.round(Number(row.points)) : "—"}</td>
            </tr>
          `).join("")}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="3">Total</td>
            <td class="perceptual-breakdown-points perceptual-breakdown-points--total">${Math.round(total)} / 100</td>
          </tr>
        </tfoot>
      </table>
    </section>
  `;
}

function _renderCrossVerdictsSection(d) {
  const v = Array.isArray(d.cross_verdicts) ? d.cross_verdicts : [];
  if (v.length === 0) return "";
  return `
    <section class="perceptual-section" data-section="cross-verdicts">
      <h3 class="perceptual-section-title">⚠️ Verdicts croisés</h3>
      <ul class="perceptual-verdicts-list">
        ${v.map((c) => `
          <li class="perceptual-verdict-item perceptual-verdict-item--${escapeHtml(c.severity || "info")}">
            <strong>${escapeHtml(c.label || "?")}</strong>
            ${c.suggestion ? `<br><span class="perceptual-verdict-suggestion">${escapeHtml(c.suggestion)}</span>` : ""}
          </li>
        `).join("")}
      </ul>
    </section>
  `;
}

function _renderNormal(title, d) {
  return `
    ${_renderHeader(title)}
    <div class="perceptual-modal-body">
      ${_renderScoreSection(d)}
      ${_renderVideoSection(d)}
      ${_renderAudioSection(d)}
      ${_renderBreakdownSection(d)}
      ${_renderCrossVerdictsSection(d)}
    </div>
    ${_renderFooter(d.analyzed_at, true)}
  `;
}

/* --- Loaders --- */

async function _loadAndRender() {
  if (!_state) return;
  const { runId, rowId, rowTitle } = _state;
  _setModalContent(_renderLoading(rowTitle));
  let res = null;
  try {
    res = await apiPost("quality/get_perceptual_details", { run_id: runId, row_id: rowId });
  } catch (err) {
    _setModalContent(_renderError(rowTitle, err && err.message ? err.message : String(err)));
    return;
  }
  if (!res) {
    _setModalContent(_renderError(rowTitle, "Réponse vide"));
    return;
  }
  if (res.ok === false) {
    const data = res.data || res;
    if (data.missing) {
      _setModalContent(_renderMissing(rowTitle));
      return;
    }
    const msg = String(data.message || data.error || "").toLowerCase();
    if (msg.includes("desactivee") || msg.includes("désactivée")) {
      _setModalContent(_renderDisabled(rowTitle));
      return;
    }
    if (msg.includes("ffmpeg")) {
      _setModalContent(_renderNoFfmpeg(rowTitle));
      return;
    }
    _setModalContent(_renderError(rowTitle, data.message || data.error || "Erreur inconnue"));
    return;
  }
  const data = res.data || res;
  const details = data.details || data;
  _setModalContent(_renderNormal(rowTitle, details || {}));
}

function _renderLoading(title) {
  return `
    ${_renderHeader(title)}
    <div class="perceptual-modal-body perceptual-modal-state perceptual-modal-state--loading">
      <p>Chargement de l'analyse perceptuelle…</p>
    </div>
    ${_renderFooter(null, false)}
  `;
}

async function _launchAnalysis() {
  if (!_state) return;
  const { runId, rowId, rowTitle } = _state;
  _setModalContent(_renderLoading(rowTitle));
  try {
    const res = await apiPost("quality/get_perceptual_report", {
      run_id: runId,
      row_id: rowId,
      options: { force: false },
    });
    if (!res || res.ok === false) {
      _setModalContent(_renderError(rowTitle, (res && (res.message || res.error)) || "Échec de l'analyse"));
      return;
    }
    await _loadAndRender();
  } catch (err) {
    _setModalContent(_renderError(rowTitle, err && err.message ? err.message : String(err)));
  }
}

async function _relaunchAnalysis() {
  if (!_state) return;
  const { runId, rowId, rowTitle } = _state;
  _setModalContent(_renderLoading(rowTitle));
  try {
    const res = await apiPost("quality/get_perceptual_report", {
      run_id: runId,
      row_id: rowId,
      options: { force: true },
    });
    if (!res || res.ok === false) {
      _setModalContent(_renderError(rowTitle, (res && (res.message || res.error)) || "Échec du relancement"));
      return;
    }
    await _loadAndRender();
  } catch (err) {
    _setModalContent(_renderError(rowTitle, err && err.message ? err.message : String(err)));
  }
}

/* --- DOM management --- */

function _ensureOverlay() {
  if (_overlayEl) return;
  _overlayEl = document.createElement("div");
  _overlayEl.className = "perceptual-modal-overlay";
  _overlayEl.setAttribute("role", "dialog");
  _overlayEl.setAttribute("aria-modal", "true");
  _overlayEl.setAttribute("aria-labelledby", "perceptual-modal-title");
  _overlayEl.addEventListener("click", (ev) => {
    if (ev.target === _overlayEl) closePerceptualModal();
  });
  _modalEl = document.createElement("div");
  _modalEl.className = "perceptual-modal";
  _overlayEl.appendChild(_modalEl);
  document.body.appendChild(_overlayEl);
  document.addEventListener("keydown", _onKeydown);
}

function _onKeydown(ev) {
  if (ev.key === "Escape" && _overlayEl) closePerceptualModal();
}

function _bindEvents() {
  if (!_modalEl) return;
  _modalEl.querySelectorAll("[data-perceptual-close]").forEach((btn) => {
    btn.addEventListener("click", closePerceptualModal);
  });
  _modalEl.querySelectorAll("[data-perceptual-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.perceptualAction;
      if (action === "launch") _launchAnalysis();
      else if (action === "relaunch") _relaunchAnalysis();
      else if (action === "open-settings") {
        closePerceptualModal();
        if (typeof window !== "undefined") window.location.hash = "#/parametres";
      }
    });
  });
  const copyFpBtn = _modalEl.querySelector("[data-perceptual-copy-fp]");
  if (copyFpBtn) {
    copyFpBtn.addEventListener("click", async () => {
      const fpEl = _modalEl.querySelector("[data-perceptual-fp]");
      const fp = fpEl ? fpEl.textContent : "";
      if (fp && navigator.clipboard) {
        try {
          await navigator.clipboard.writeText(fp);
          copyFpBtn.textContent = "✓ Copié";
          setTimeout(() => { if (copyFpBtn) copyFpBtn.textContent = "📋 Copier"; }, 1500);
        } catch (_e) { /* noop */ }
      }
    });
  }
}

function _setModalContent(html) {
  if (!_modalEl) return;
  _modalEl.innerHTML = html;
  _bindEvents();
}

/* --- API publique --- */

export async function openPerceptualModal(opts) {
  const { rowId, runId, rowTitle } = opts || {};
  if (!rowId) {
    console.warn("[perceptual-modal] rowId requis");
    return;
  }
  _state = { rowId, runId: runId || null, rowTitle: rowTitle || "" };
  _ensureOverlay();
  document.body.classList.add("modal-open");
  _setModalContent(_renderLoading(rowTitle));
  await _loadAndRender();
}

export function closePerceptualModal() {
  if (_overlayEl) {
    document.removeEventListener("keydown", _onKeydown);
    _overlayEl.remove();
    _overlayEl = null;
    _modalEl = null;
  }
  _state = null;
  document.body.classList.remove("modal-open");
}
