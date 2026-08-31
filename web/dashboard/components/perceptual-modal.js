/* components/perceptual-modal.js — Modal Analyse Perceptuelle (Phase 5, spec 02).
 *
 * Mode B (overlay) : modal centree fullscreen sur fond noir (Accueil / Parametres / Aide).
 * Mode A (inspecteur elargi) : injecte le contenu dans right-panel.setSections() et
 *   force la largeur a 600px (Bibliotheque / Doublons / Qualite / Historique).
 *
 * API :
 *   openPerceptualModal({ rowId, runId, rowTitle, mode? })
 *     mode = "A" (inspecteur) | "B" (overlay) | auto (defaut, choisi selon hash route)
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
 *
 * Sections specifiques :
 *   §1 Frames lazy           -> bouton "Voir les frames", appel ondemand
 *   §5 Dropdown Comparer     -> liste films du run, route vers comparateur doublons
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { humanize, humanizeMelVerdict, isMelMeasured, severityForTier, SCORE_V2_COMPONENTS } from "../core/perceptual-labels.js";
import { setSections as rpSetSections, setExpandedWidth as rpSetExpandedWidth, isExpandedWidth as rpIsExpandedWidth } from "./right-panel.js";
import { openDuplicateComparatorModal } from "./duplicate-comparator-modal.js";
// Fix audit 2026-05-24 a11y : reutilisation du trapFocus exporte par modal.js
// (auparavant : aucun trap -> Tab pouvait sortir du modal vers le DOM dessous).
import { trapFocus } from "./modal.js";

// Spec 02 §0 : vues qui affichent l'analyse perceptuelle dans l'inspecteur droit.
// Le reste utilise l'overlay modal.
const _VIEWS_INSPECTOR = ["/bibliotheque", "/library", "/doublons", "/qualite", "/historique", "/qij", "/traitement", "/processing"];

let _overlayEl = null;
let _modalEl = null;
let _state = null;
// Fix audit 2026-05-24 a11y : handler retourne par trapFocus(), conserve pour
// removeEventListener au close (zero leak + focus trap propre).
let _focusTrapHandler = null;
let _focusTrapTarget = null;

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
  return `<div class="perceptual-bar"><div class="perceptual-bar-fill" style="--progress:${pct / 100}"></div></div>`;
}

/** Spec 02 §0 : decide le mode A/B selon la route active.
 * Si opts.mode est explicite ("A"/"B"), on respecte. Sinon on lit window.location.hash.
 */
function _resolveMode(opts) {
  if (opts && (opts.mode === "A" || opts.mode === "B")) return opts.mode;
  if (typeof window === "undefined" || !window.location) return "B";
  const hash = String(window.location.hash || "").replace(/^#/, "");
  const base = hash.split("#")[0].split("?")[0];
  return _VIEWS_INSPECTOR.includes(base) ? "A" : "B";
}

/** Detection de l'etat "partial" : au moins un champ cle null/manquant
 * (spec 02 §4.5). On considere : audio_fingerprint, ssim_self_ref, spectral_cutoff_hz.
 */
function _isPartial(d) {
  if (!d) return false;
  const missingFp = d.audio_fingerprint == null || d.audio_fingerprint === "";
  const missingSsim = d.ssim_self_ref == null;
  const missingCutoff = d.spectral_cutoff_hz == null || d.spectral_cutoff_hz === 0;
  return missingFp || missingSsim || missingCutoff;
}

/** Rend une cellule "valeur" avec fallback "Non calcule" + [Completer] si null. */
function _renderPartialCell(value, displayValue) {
  if (value == null || value === "" || value === 0) {
    return `<span class="perceptual-partial-row">Non calculé dans cette passe <button type="button" class="v5-btn v5-btn--xs v5-btn--ghost" data-perceptual-action="complete" title="Relancer pour completer">↻ Compléter</button></span>`;
  }
  return displayValue != null ? displayValue : escapeHtml(String(value));
}

/* --- Rendering --- */

function _renderCompareDropdown() {
  return `
    <details class="perceptual-compare-dropdown" data-perceptual-compare>
      <summary>▾ Comparer avec un autre film du run</summary>
      <div class="perceptual-compare-panel">
        <input type="search" class="perceptual-compare-filter" placeholder="🔍 Filtrer..." data-perceptual-compare-filter autocomplete="off" />
        <ul class="perceptual-compare-list" data-perceptual-compare-list>
          <li class="perceptual-compare-loading">Chargement des films du run...</li>
        </ul>
      </div>
    </details>
  `;
}

function _renderHeader(title) {
  return `
    <header class="perceptual-modal-header">
      <div class="perceptual-modal-title-row">
        <h2 class="perceptual-modal-title">
          Analyse perceptuelle
          ${title ? `<span class="perceptual-modal-subtitle">— ${escapeHtml(title)}</span>` : ""}
        </h2>
        <div class="perceptual-modal-header-actions">
          ${_state && _state.mode === "A" ? `<button type="button" class="perceptual-modal-toggle-width v5-btn v5-btn--xs v5-btn--ghost" data-perceptual-action="toggle-width" title="Basculer largeur normale/elargie" aria-label="Basculer largeur">${rpIsExpandedWidth() ? "◀" : "▶"}</button>` : ""}
          <button type="button" class="perceptual-modal-close" data-perceptual-close aria-label="Fermer">✕</button>
        </div>
      </div>
      ${_renderCompareDropdown()}
    </header>
  `;
}

/* Revue post-merge 2026-08-03 : le pied de modale lisait `d.analyzed_at`, cle
 * que le backend n'emet PAS. `quality/get_perceptual_details` renvoie
 * l'horodatage sous `ts` (epoch secondes, colonne perceptual_reports.ts) et
 * `_flatten_perceptual_for_modal` ne le renomme pas. Resultat : une analyse
 * complete et persistee s'affichait avec « Non analysé » en pied de modale,
 * juste sous son propre score — contradiction directe a l'ecran. On lit donc
 * `analyzed_at` (si un jour le backend l'ajoute) PUIS `ts` en repli.
 */
function _analyzedAtLabel(d) {
  if (!d || typeof d !== "object") return null;
  if (d.analyzed_at) return String(d.analyzed_at);
  const ts = Number(d.ts);
  if (!Number.isFinite(ts) || ts <= 0) return null;
  const date = new Date(ts * 1000);
  if (Number.isNaN(date.getTime())) return null;
  try { return date.toLocaleString("fr-FR"); }
  catch { return date.toISOString(); }
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
  // VN-B.2 : single source of truth display_tier (echelle V2 lowercase
  // reconciliee backend). Fallback tier_v2 / global_tier_v2 pour les payloads
  // pre-VN-B.2.
  const tier = String(d.display_tier || d.tier_v2 || d.global_tier_v2 || "unknown").toLowerCase();
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

/** Spec 02 §1 : ligne "Bitrate vs resolution" calcul JS (Mbps/megapixel).
 * < 3 -> faible ; 3-6 -> moyen ; > 6 -> bon.
 */
function _renderBitrateVsResolution(d) {
  const bitrateKbps = Number(d.bitrate_kbps || 0);
  const width = Number(d.width || (d.video_streams && d.video_streams[0] && d.video_streams[0].width) || 0);
  const height = Number(d.height || (d.video_streams && d.video_streams[0] && d.video_streams[0].height) || 0);
  if (!bitrateKbps || !width || !height) return null;
  const bitrateMbps = bitrateKbps / 1000;
  const megapixels = (width * height) / 1000000;
  if (megapixels <= 0) return null;
  const ratio = bitrateMbps / megapixels;
  // Resolution label
  let resLabel = `${width}x${height}`;
  if (height >= 2000) resLabel = "4K";
  else if (height >= 1000) resLabel = "1080p";
  else if (height >= 700) resLabel = "720p";
  else if (height >= 460) resLabel = "480p";
  let verdict;
  if (ratio < 3) verdict = `faible : ~6+ attendu pour ${resLabel}`;
  else if (ratio < 6) verdict = `moyen pour ${resLabel}`;
  else verdict = `bon pour ${resLabel}`;
  return `${bitrateMbps.toFixed(1)} Mbps pour ${resLabel} (${verdict}, ratio ${ratio.toFixed(1)} Mb/s/MP)`;
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
  const bitrateVsRes = _renderBitrateVsResolution(d);

  // Spec 02 §4.5 : champs vides en mode partial
  const ssimCell = d.ssim_self_ref != null
    ? `${escapeHtml(ssim)} → ${escapeHtml(ssimVerdict)}`
    : _renderPartialCell(null, null);

  return `
    <section class="perceptual-section" data-section="video">
      <h3 class="perceptual-section-title">🎬 Métriques vidéo</h3>
      <dl class="perceptual-dl">
        <dt>SSIM self-ref</dt><dd>${ssimCell}</dd>
        ${upscale ? `<dt>Faux 4K détecté</dt><dd>${escapeHtml(upscale)}</dd>` : ""}
        <dt>Grain</dt><dd>${escapeHtml(grain)}</dd>
        <dt>HDR</dt><dd>${escapeHtml(hdrLabel)}</dd>
        <dt>Codec</dt><dd>${escapeHtml(codec)} ${escapeHtml(bitDepth)} ${bitrate !== "—" ? "@ " + escapeHtml(bitrate) : ""}</dd>
        <dt>Bitrate</dt><dd>${escapeHtml(bitrate)}</dd>
        ${bitrateVsRes ? `<dt>Bitrate vs résolution</dt><dd>${escapeHtml(bitrateVsRes)}</dd>` : ""}
      </dl>
    </section>
  `;
}

/* #381 — les quatre sous-detections mel etaient calculees, scorees (15 % du
 * sous-score audio, AUDIO_WEIGHT_MEL) et persistees... puis jamais montrees :
 * `grep -rn "spectral_flatness" web/` rendait 0 resultat. Le backend les sert
 * pourtant deja au top-level : `_flatten_perceptual_for_modal` remonte
 * `metrics.audio_perceptual` (perceptual_support.py), dont `to_dict()` porte le
 * bloc `mel` (domain/perceptual/models.py).
 *
 * Le verdict s'affiche toujours ; les GRANDEURS ne s'affichent que si la mesure
 * a abouti (cf. MEL_MEASURED_VERDICTS) — sinon on montrerait les valeurs par
 * defaut du dataclass (0.0 / false) comme si elles avaient ete mesurees.
 */
function _renderMelRows(d) {
  const audio = d && typeof d.audio_perceptual === "object" && d.audio_perceptual !== null ? d.audio_perceptual : null;
  const mel = audio && typeof audio.mel === "object" && audio.mel !== null ? audio.mel : null;
  if (!mel) return "";  // rapport anterieur a §12 v7.5.0 : rien a dire.
  const verdict = mel.verdict;
  const rows = [`<dt>Analyse spectrale (mel)</dt><dd>${escapeHtml(humanizeMelVerdict(verdict))}</dd>`];
  if (!isMelMeasured(verdict)) return rows.join("\n");
  if (mel.score != null) {
    rows.push(`<dt>Score mel</dt><dd>${Math.round(Number(mel.score) || 0)}/100</dd>`);
  }
  rows.push(`<dt>Soft clipping</dt><dd>${escapeHtml(_fmtNumber(mel.soft_clipping_pct, 1))} % des frames</dd>`);
  rows.push(`<dt>Shelf MP3 16 kHz</dt><dd>${mel.mp3_shelf_detected ? "détecté" : "absent"}</dd>`);
  rows.push(`<dt>Trous AAC</dt><dd>${escapeHtml(_fmtNumber(Number(mel.aac_holes_ratio) * 100, 1))} % des bandes</dd>`);
  rows.push(`<dt>Aplatissement spectral</dt><dd>${escapeHtml(_fmtNumber(mel.spectral_flatness, 3))}</dd>`);
  return rows.join("\n");
}

function _renderAudioSection(d) {
  const fp = d.audio_fingerprint || "";
  // Spec 02 fix : on stocke la valeur complete pour copie
  if (_state) _state.fullFingerprint = fp;
  const cutoff = _fmtKhz(d.spectral_cutoff_hz);
  const lossyVerdict = humanize(d.lossy_verdict, "—");
  const tracks = Array.isArray(d.audio_streams) ? d.audio_streams : [];
  const dynamicRange = d.audio_perceptual && d.audio_perceptual.dynamic_range_db;

  // Spec 02 §4.5 : champs vides
  const fpBlock = fp ? `
    <div class="perceptual-audio-fp">
      <span class="perceptual-audio-fp-label">Empreinte Chromaprint :</span>
      <code class="perceptual-audio-fp-value" data-perceptual-fp>${escapeHtml(fp.slice(0, 80))}${fp.length > 80 ? "…" : ""}</code>
      <button type="button" class="v5-btn v5-btn--xs v5-btn--ghost" data-perceptual-copy-fp title="Copier l'empreinte complète">📋 Copier</button>
    </div>
  ` : `
    <div class="perceptual-audio-fp perceptual-audio-fp--missing">
      <span class="perceptual-audio-fp-label">Empreinte Chromaprint :</span>
      ${_renderPartialCell(null, null)}
    </div>
  `;

  const cutoffCell = (d.spectral_cutoff_hz != null && d.spectral_cutoff_hz !== 0)
    ? escapeHtml(cutoff)
    : _renderPartialCell(null, null);

  return `
    <section class="perceptual-section" data-section="audio">
      <h3 class="perceptual-section-title">🔊 Métriques audio</h3>
      ${fpBlock}
      <dl class="perceptual-dl">
        <dt>Cutoff spectral</dt><dd>${cutoffCell}</dd>
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
        ${_renderMelRows(d)}
      </dl>
    </section>
  `;
}

function _renderBreakdownSection(d) {
  const breakdown = Array.isArray(d.breakdown) ? d.breakdown : null;
  if (!breakdown || breakdown.length === 0) {
    return `
      <section class="perceptual-section" data-section="breakdown">
        <h3 class="perceptual-section-title">📐 Composantes du Score V2 <button type="button" class="v5-btn v5-btn--xs v5-btn--ghost" data-perceptual-action="toggle-breakdown" title="Replier/deployer">▼ Replier</button></h3>
        <div data-perceptual-breakdown-body>
          <p class="perceptual-empty">Détail composantes indisponible dans cette passe.</p>
          <ul class="perceptual-breakdown-weights">
            ${SCORE_V2_COMPONENTS.map((c) => `
              <li><span class="perceptual-breakdown-name">${escapeHtml(c.label)}</span>
                  <span class="perceptual-breakdown-weight">× ${(c.weight * 100).toFixed(0)}%</span></li>
            `).join("")}
          </ul>
        </div>
      </section>
    `;
  }
  const total = breakdown.reduce((sum, row) => sum + (Number(row.points) || 0), 0);
  return `
    <section class="perceptual-section" data-section="breakdown">
      <h3 class="perceptual-section-title">📐 Breakdown détaillé (Score V2) <button type="button" class="v5-btn v5-btn--xs v5-btn--ghost" data-perceptual-action="toggle-breakdown" title="Replier/deployer">▼ Replier</button></h3>
      <div data-perceptual-breakdown-body>
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
      </div>
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

/** Spec 02 §1 : section Frames lazy. Bouton declenche fetch + rendu PNG. */
function _renderFramesSection() {
  return `
    <section class="perceptual-section" data-section="frames">
      <h3 class="perceptual-section-title">🔬 Frames analysées</h3>
      <div data-perceptual-frames-container>
        <p class="perceptual-empty">Extraction ~10-30s (sera affichee a la demande).</p>
        <button type="button" class="v5-btn v5-btn--secondary" data-perceptual-action="load-frames">▶ Voir les frames</button>
      </div>
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
      ${_renderFramesSection()}
    </div>
    ${_renderFooter(_analyzedAtLabel(d), true)}
  `;
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
  // apiPost peut retourner {status, data} ou directement les donnees selon le wrapper.
  const payload = res.data != null ? res.data : res;
  if (payload.ok === false) {
    // Spec 02 §7 : detection via codes structures (category, missing_tool)
    if (payload.missing === true) {
      _setModalContent(_renderMissing(rowTitle));
      return;
    }
    if (payload.missing_tool === "ffmpeg" || payload.missing_tool === "ffprobe") {
      _setModalContent(_renderNoFfmpeg(rowTitle));
      return;
    }
    if (payload.category === "state") {
      // feature desactivee dans les reglages
      _setModalContent(_renderDisabled(rowTitle));
      return;
    }
    // Fallback string-match pour endpoints non encore migres
    const msg = String(payload.message || payload.error || "").toLowerCase();
    if (msg.includes("desactivee") || msg.includes("désactivée") || msg.includes("disabled")) {
      _setModalContent(_renderDisabled(rowTitle));
      return;
    }
    if (msg.includes("ffmpeg") || msg.includes("ffprobe")) {
      _setModalContent(_renderNoFfmpeg(rowTitle));
      return;
    }
    _setModalContent(_renderError(rowTitle, payload.message || payload.error || "Erreur inconnue"));
    return;
  }
  const details = payload.details || payload;
  _setModalContent(_renderNormal(rowTitle, details || {}));
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
    const payload = res && res.data != null ? res.data : res;
    if (!payload || payload.ok === false) {
      _setModalContent(_renderError(rowTitle, (payload && (payload.message || payload.error)) || "Échec de l'analyse"));
      return;
    }
    await _loadAndRender();
  } catch (err) {
    _setModalContent(_renderError(rowTitle, err && err.message ? err.message : String(err)));
  }
}

async function _relaunchAnalysis(opts) {
  if (!_state) return;
  const { runId, rowId, rowTitle } = _state;
  _setModalContent(_renderLoading(rowTitle));
  const options = { force: true };
  // Spec 02 §4.5 : flag only_missing pour completer les champs absents
  if (opts && opts.onlyMissing) options.only_missing = true;
  try {
    const res = await apiPost("quality/get_perceptual_report", {
      run_id: runId,
      row_id: rowId,
      options,
    });
    const payload = res && res.data != null ? res.data : res;
    if (!payload || payload.ok === false) {
      _setModalContent(_renderError(rowTitle, (payload && (payload.message || payload.error)) || "Échec du relancement"));
      return;
    }
    await _loadAndRender();
  } catch (err) {
    _setModalContent(_renderError(rowTitle, err && err.message ? err.message : String(err)));
  }
}

/** Spec 02 §1 : appel get_perceptual_compare_frames pour les self-frames. */
async function _loadFrames() {
  if (!_state) return;
  const { runId, rowId } = _state;
  const container = _modalEl && _modalEl.querySelector("[data-perceptual-frames-container]");
  if (!container) return;
  container.innerHTML = `<p class="perceptual-empty">Extraction en cours… (~10-30s)</p>`;
  try {
    // self-comparison : row_id_a = row_id_b = rowId pour avoir les frames du film
    const res = await apiPost("quality/get_perceptual_compare_frames", {
      run_id: runId,
      row_id_a: rowId,
      row_id_b: rowId,
      options: { max_frames: 3 },
    });
    const payload = res && res.data != null ? res.data : res;
    if (!payload || payload.ok === false) {
      container.innerHTML = `<p class="perceptual-empty">Erreur : ${escapeHtml((payload && (payload.message || payload.error)) || "indisponible")}</p>`;
      return;
    }
    const frames = Array.isArray(payload.frames) ? payload.frames : [];
    if (frames.length === 0) {
      container.innerHTML = `<p class="perceptual-empty">Aucune frame disponible.</p>`;
      return;
    }
    container.innerHTML = `
      <div class="perceptual-frames-grid">
        ${frames.map((f) => `
          <figure class="perceptual-frame-item">
            <img src="data:image/png;base64,${escapeHtml(f.frame_a_b64 || f.frame_b_b64 || "")}" alt="Frame à t=${escapeHtml(String(f.timestamp || "?"))}s" loading="lazy" />
            <figcaption>t = ${escapeHtml(String(f.timestamp != null ? Number(f.timestamp).toFixed(1) : "?"))}s</figcaption>
          </figure>
        `).join("")}
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<p class="perceptual-empty">Erreur : ${escapeHtml(err && err.message ? err.message : String(err))}</p>`;
  }
}

/* --- Compare dropdown (spec 02 §5) --- */

let _filterDebounceTimer = null;

async function _loadCompareList() {
  if (!_state) return;
  if (_state.compareLoaded) {
    // Spec 02 §5 polish : la liste est deja en cache (pre-fetch au open) —
    // on re-rend juste les items dans le DOM (pas de fetch en double).
    _renderCompareListItems(_state.compareRows || []);
    return;
  }
  if (_state.compareInFlight) return;
  _state.compareInFlight = true;
  const { runId, rowId } = _state;
  const listEl = _modalEl && _modalEl.querySelector("[data-perceptual-compare-list]");
  // LOT 5-B : la garde `if (!_state)` ci-dessus est AVANT l'await, or cette
  // liste est pre-chargee a l'ouverture (`void _loadCompareList()`) et
  // `closePerceptualModal()` pose `_state = null` — Echap juste apres l'ouverture
  // est donc le cas nominal. On memorise la session et on re-verifie APRES
  // l'await avant toute ecriture (sinon TypeError, y compris dans le `catch`).
  const sessionRef = _state;
  const memeSession = () => _state === sessionRef;
  try {
    const res = await apiPost("library/get_library_filtered", {
      run_id: runId,
      page_size: 500,
      page: 1,
    });
    if (!memeSession()) return;
    const payload = res && res.data != null ? res.data : res;
    if (!payload || payload.ok === false) {
      _state.compareInFlight = false;
      if (listEl) {
        listEl.innerHTML = `<li class="perceptual-compare-loading">Erreur : ${escapeHtml((payload && (payload.message || payload.error)) || "indisponible")}</li>`;
      }
      return;
    }
    // Le contrat peut etre {rows: [...]} ou {items: [...]}
    const rows = payload.rows || payload.items || payload.films || [];
    _state.compareRows = rows.filter((r) => String(r.row_id || r.id) !== String(rowId));
    _state.compareLoaded = true;
    _state.compareInFlight = false;
    _renderCompareListItems(_state.compareRows);
  } catch (err) {
    if (!memeSession()) return;
    _state.compareInFlight = false;
    if (listEl) {
      listEl.innerHTML = `<li class="perceptual-compare-loading">Erreur : ${escapeHtml(err && err.message ? err.message : String(err))}</li>`;
    }
  }
}

function _renderCompareListItems(rows) {
  const listEl = _modalEl && _modalEl.querySelector("[data-perceptual-compare-list]");
  if (!listEl) return;
  if (!rows || rows.length === 0) {
    listEl.innerHTML = `<li class="perceptual-compare-loading">Aucun film trouvé.</li>`;
    return;
  }
  // Cap a 100 entries pour perf
  const items = rows.slice(0, 100);
  listEl.innerHTML = items.map((r) => {
    const id = String(r.row_id || r.id || "");
    const title = String(r.title || r.final_name || r.original_name || r.basename || id);
    const year = r.year ? `(${r.year})` : "";
    const score = r.global_score_v2 != null ? `Score ${Math.round(Number(r.global_score_v2))}` : "";
    return `<li><button type="button" class="perceptual-compare-item" data-perceptual-compare-pick="${escapeHtml(id)}" data-row-title="${escapeHtml(title)}">${escapeHtml(title)} ${escapeHtml(year)} <span class="perceptual-compare-score">${escapeHtml(score)}</span></button></li>`;
  }).join("");
}

function _filterCompareList(query) {
  if (!_state || !_state.compareRows) return;
  const q = String(query || "").trim().toLowerCase();
  if (!q) {
    _renderCompareListItems(_state.compareRows);
    return;
  }
  const filtered = _state.compareRows.filter((r) => {
    const title = String(r.title || r.final_name || r.original_name || r.basename || "").toLowerCase();
    return title.includes(q);
  });
  _renderCompareListItems(filtered);
}

function _onPickCompare(otherRowId, otherTitle) {
  if (!_state) return;
  // Spec 02 §5 : ouverture de la VRAIE Modal Comparateur Doublons (3 onglets
  // Apercu/Frames/Audio), en mode readOnly puisque les 2 films ne forment pas
  // forcement un groupe de doublons enregistre. Pas de decision Garder A/B
  // ici : pour ca, l'utilisateur passe par la vue Doublons.
  const runId = _state.runId;
  const rowId = _state.rowId;
  const rowTitle = _state.rowTitle;
  // On ferme d'abord la Modal Perceptuelle pour eviter d'empiler 2 overlays
  // (cleaner UX : la modal comparateur prend le relais).
  closePerceptualModal();
  try {
    openDuplicateComparatorModal({
      runId,
      // groupKey synthetique : permet d'identifier la paire dans les logs,
      // mais readOnly=true desactive l'appel a mark_duplicate_winner.
      groupKey: `perceptual::${rowId}::${otherRowId}`,
      rowA: rowId,
      rowB: otherRowId,
      title: rowTitle || otherTitle || "",
      year: "",
      // Pas de comparison.criteria : l'onglet Apercu affichera juste les en-tetes A/B
      // et un message "Aucun critère détaillé disponible pour cette paire."
      comparison: null,
      readOnly: true,
    });
  } catch (e) {
    console.warn("[perceptual-modal] openDuplicateComparatorModal a echoue", e);
    // Fallback ultime : navigation vers /doublons (preserve l'ancien comportement
    // si jamais le module comparateur est casse).
    if (typeof window !== "undefined" && window.location) {
      window.location.hash = `#/doublons?compareA=${encodeURIComponent(rowId)}&compareB=${encodeURIComponent(otherRowId)}`;
    }
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
  // Fix audit 2026-05-24 a11y : capture le Tab/Shift+Tab dans l'overlay.
  _focusTrapTarget = _overlayEl;
  _focusTrapHandler = trapFocus(_overlayEl);
}

function _onKeydown(ev) {
  if (ev.key === "Escape" && (_overlayEl || (_state && _state.mode === "A"))) closePerceptualModal();
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
      else if (action === "complete") _relaunchAnalysis({ onlyMissing: true });
      else if (action === "load-frames") _loadFrames();
      else if (action === "toggle-breakdown") {
        const body = _modalEl.querySelector("[data-perceptual-breakdown-body]");
        if (body) {
          const hidden = body.style.display === "none";
          body.style.display = hidden ? "" : "none";
          btn.textContent = hidden ? "▼ Replier" : "▶ Déployer";
        }
      } else if (action === "toggle-width") {
        if (_state && _state.mode === "A") {
          const wasExpanded = rpIsExpandedWidth();
          rpSetExpandedWidth(!wasExpanded);
          btn.textContent = !wasExpanded ? "◀" : "▶";
        }
      } else if (action === "open-settings") {
        closePerceptualModal();
        if (typeof window !== "undefined") window.location.hash = "#/parametres";
      }
    });
  });
  const copyFpBtn = _modalEl.querySelector("[data-perceptual-copy-fp]");
  if (copyFpBtn) {
    copyFpBtn.addEventListener("click", async () => {
      // Spec 02 fix : copie la valeur complete, pas la version tronquee
      const fp = (_state && _state.fullFingerprint) || "";
      if (fp && navigator.clipboard) {
        try {
          await navigator.clipboard.writeText(fp);
          copyFpBtn.textContent = "✓ Copié";
          setTimeout(() => { if (copyFpBtn) copyFpBtn.textContent = "📋 Copier"; }, 1500);
        } catch (_e) { /* noop */ }
      }
    });
  }
  // Spec 02 §5 : dropdown Comparer
  const compareDetails = _modalEl.querySelector("[data-perceptual-compare]");
  if (compareDetails) {
    compareDetails.addEventListener("toggle", () => {
      if (compareDetails.open) _loadCompareList();
    });
  }
  // Si la liste est deja chargee (pre-fetch a l'ouverture, spec 02 §5 polish),
  // on la re-rend immediatement apres rebind pour eviter de re-afficher
  // "Chargement..." apres un _setModalContent.
  if (_state && _state.compareLoaded && Array.isArray(_state.compareRows) && _state.compareRows.length > 0) {
    _renderCompareListItems(_state.compareRows);
  }
  const filterInput = _modalEl.querySelector("[data-perceptual-compare-filter]");
  if (filterInput) {
    filterInput.addEventListener("input", (ev) => {
      if (_filterDebounceTimer) clearTimeout(_filterDebounceTimer);
      const val = ev.target.value;
      _filterDebounceTimer = setTimeout(() => _filterCompareList(val), 250);
    });
  }
  // Delegation pour le pick dans la liste (rendue dynamiquement)
  const listEl = _modalEl.querySelector("[data-perceptual-compare-list]");
  if (listEl) {
    listEl.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-perceptual-compare-pick]");
      if (!btn) return;
      const otherId = btn.dataset.perceptualComparePick;
      const otherTitle = btn.dataset.rowTitle;
      _onPickCompare(otherId, otherTitle);
    });
  }
}

function _setModalContent(html) {
  if (!_modalEl) return;
  if (_state && _state.mode === "A") {
    // Mode A : injection dans le right-panel via setSections
    rpSetSections([{ title: "", html }]);
    // Le _modalEl est un placeholder pour eviter de casser les query selectors
    _modalEl.innerHTML = html;
  } else {
    _modalEl.innerHTML = html;
  }
  _bindEvents();
}

/* --- API publique --- */

export async function openPerceptualModal(opts) {
  const { rowId, runId, rowTitle } = opts || {};
  if (!rowId) {
    console.warn("[perceptual-modal] rowId requis");
    return;
  }
  const mode = _resolveMode(opts);
  _state = {
    rowId,
    runId: runId || null,
    rowTitle: rowTitle || "",
    mode,
    fullFingerprint: "",
    compareLoaded: false,
    compareInFlight: false,
    compareRows: [],
  };

  if (mode === "A") {
    // Mode A : injecter dans le right-panel, ne PAS creer d'overlay
    rpSetExpandedWidth(true);
    // Reuse _modalEl comme conteneur de queries DOM (rattache au right-panel body)
    const rpBody = document.querySelector("[data-v5-right-panel-body]");
    if (rpBody) {
      _modalEl = rpBody;
    } else {
      // Fallback en cas d'absence d'inspecteur : on retombe sur overlay
      _ensureOverlay();
    }
    document.addEventListener("keydown", _onKeydown);
  } else {
    // Mode B : overlay classique
    _ensureOverlay();
    document.body.classList.add("modal-open");
  }
  _setModalContent(_renderLoading(rowTitle));
  await _loadAndRender();
  // Spec 02 §5 polish : pre-charger la liste "Comparer avec un autre film"
  // en arriere-plan pour eviter le "Chargement..." au moment du clic sur
  // le dropdown. On ignore les erreurs (la liste re-tentera au toggle).
  void _loadCompareList();
}

export function closePerceptualModal() {
  // Fix audit 2026-05-24 a11y : libere le focus trap installe par _ensureOverlay
  // (removeEventListener du handler retourne par trapFocus()).
  if (_focusTrapHandler && _focusTrapTarget) {
    try { _focusTrapTarget.removeEventListener("keydown", _focusTrapHandler); } catch (_e) { /* noop */ }
  }
  _focusTrapHandler = null;
  _focusTrapTarget = null;
  if (_overlayEl) {
    document.removeEventListener("keydown", _onKeydown);
    _overlayEl.remove();
    _overlayEl = null;
    _modalEl = null;
  } else if (_state && _state.mode === "A") {
    document.removeEventListener("keydown", _onKeydown);
    // Mode A : reset le right-panel + largeur normale
    try {
      rpSetSections([]);
      rpSetExpandedWidth(false);
    } catch (_e) { /* noop */ }
    _modalEl = null;
  }
  _state = null;
  document.body.classList.remove("modal-open");
  if (_filterDebounceTimer) {
    clearTimeout(_filterDebounceTimer);
    _filterDebounceTimer = null;
  }
}
