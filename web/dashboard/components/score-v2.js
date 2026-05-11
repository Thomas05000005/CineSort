/* dashboard/components/score-v2.js — §16b v7.5.0
 * Version ES module du composant score V2 (parite desktop).
 */

import { escapeHtml } from "../core/dom.js";

const TIER_FR = {
  platinum: "Platinum", gold: "Or", silver: "Argent",
  bronze: "Bronze", reject: "Refuse",
};

const CATEGORY_FR = {
  video: "Video", audio: "Audio", coherence: "Coherence",
};

const SUB_TOOLTIPS = {
  perceptual_visual: "Synthese block/blur/banding/profondeur effective sur un echantillon de frames.",
  resolution: "Resolution effective + cross-check fake 4K (FFT 2D + SSIM self-ref).",
  hdr_validation: "Presence HDR10/HDR10+/Dolby Vision et integrite des metadonnees MaxCLL/MaxFALL.",
  lpips_distance: "Distance perceptuelle apprise entre 2 fichiers (mode comparaison uniquement).",
  perceptual_audio: "EBU R128 (LRA, integrated), clipping, bruit de fond. Synthese audio.",
  spectral_cutoff: "Frequence de coupure spectrale. Lossless > 19 kHz, AAC 128 ~16 kHz, MP3 ~15 kHz.",
  drc_category: "Compression dynamique : cinema (large), standard (moyenne), broadcast (agressive).",
  chromaprint: "Empreinte audio Chromaprint (identification robuste face aux re-encodes).",
  reserve: "Reserve pour futurs criteres (NR-VMAF, timbre, etc.).",
  runtime_match: "Duree reelle du fichier vs TMDb. Ecart = version alternative probable.",
  nfo_consistency: "Alignement du NFO (titre/annee/TMDb ID) avec le fichier.",
};

function _tierOf(v) {
  const t = String(v || "").toLowerCase();
  return ["platinum", "gold", "silver", "bronze", "reject"].includes(t) ? t : "unknown";
}

function _fmtPct(v) {
  return Math.round(Math.max(0, Math.min(100, Number(v) || 0))).toString();
}

export function scoreCircleHtml({ score, tier, small }) {
  const s = Math.max(0, Math.min(100, Number(score) || 0));
  const t = _tierOf(tier || "unknown");
  const size = small ? 80 : 120;
  const radius = small ? 32 : 50;
  const cx = size / 2, cy = size / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - s / 100);
  const tierLabel = TIER_FR[t] || "";
  return `
    <div class="score-circle ${small ? "small" : ""} tier-${t}" data-tier="${escapeHtml(t)}" data-score="${Math.round(s)}">
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">
        <circle class="bg" cx="${cx}" cy="${cy}" r="${radius}"></circle>
        <circle class="fg stroke-${t}" cx="${cx}" cy="${cy}" r="${radius}"
          stroke-dasharray="${circumference.toFixed(2)}"
          stroke-dashoffset="${offset.toFixed(2)}"></circle>
      </svg>
      <div class="content">
        <div class="value">${_fmtPct(s)}</div>
        <div class="tier">${escapeHtml(tierLabel)}</div>
      </div>
    </div>
  `;
}

export function scoreGaugeHtml(cat) {
  const t = _tierOf(cat.tier);
  const v = Math.max(0, Math.min(100, Number(cat.value) || 0));
  const label = CATEGORY_FR[cat.name] || cat.name;
  return `
    <div class="score-gauge-row" data-category="${escapeHtml(cat.name)}">
      <div class="score-gauge-label">${escapeHtml(label)}</div>
      <div class="score-gauge-track">
        <div class="score-gauge-fill bg-${t}" style="--gauge-target: ${v.toFixed(1)}%"></div>
      </div>
      <div class="score-gauge-value tier-${t}">${v.toFixed(0)}</div>
    </div>
  `;
}

export function scoreAccordionHtml(categoryScores) {
  if (!Array.isArray(categoryScores) || !categoryScores.length) return "";
  let html = '<div class="score-accordion">';
  for (const cat of categoryScores) {
    const t = _tierOf(cat.tier);
    const catLabel = CATEGORY_FR[cat.name] || cat.name;
    const catValue = Math.round(Number(cat.value) || 0);
    html += `<div class="score-accordion-section" data-section="${escapeHtml(cat.name)}">`;
    html += `<div class="score-accordion-header" role="button" tabindex="0" aria-expanded="false">`;
    html += `<span><span class="chevron">&#9656;</span> ${escapeHtml(catLabel)}</span>`;
    html += `<span class="tier-${t}">${catValue}/100</span>`;
    html += `</div>`;
    html += `<div class="score-accordion-body"><div class="score-sub-list">`;
    for (const sub of cat.sub_scores || []) {
      const subTier = _tierOf(sub.tier || "unknown");
      const conf = Number(sub.confidence) || 0;
      const lowConf = conf > 0 && conf < 0.6;
      const tipText = sub.detail_fr || SUB_TOOLTIPS[sub.name] || "";
      html += `<div class="score-sub-row ${lowConf ? "low-confidence" : ""}" title="${escapeHtml(tipText)}">`;
      html += `<div><div class="score-sub-label">${escapeHtml(sub.label_fr || sub.name)}</div>`;
      if (sub.detail_fr) html += `<span class="score-sub-detail">${escapeHtml(sub.detail_fr)}</span>`;
      html += `</div>`;
      if (sub.tier) html += `<span class="score-sub-tier-badge tier-${subTier}">${escapeHtml(TIER_FR[subTier] || sub.tier)}</span>`;
      else html += "<span></span>";
      html += `<span class="score-sub-value tier-${subTier}">${Math.round(Number(sub.value) || 0)}</span>`;
      html += `</div>`;
    }
    html += `</div></div></div>`;
  }
  html += "</div>";
  return html;
}

export function scoreWarningsHtml(warnings) {
  if (!Array.isArray(warnings) || !warnings.length) return "";
  let html = '<div class="score-warnings">';
  for (const w of warnings) html += `<div class="score-warning">${escapeHtml(w)}</div>`;
  html += "</div>";
  return html;
}

export function renderScoreV2Container(gsv2, { compact = false } = {}) {
  if (!gsv2 || typeof gsv2 !== "object") return "";
  const score = Number(gsv2.global_score) || 0;
  const tier = _tierOf(gsv2.global_tier || "unknown");
  const cats = Array.isArray(gsv2.category_scores) ? gsv2.category_scores : [];
  const warns = Array.isArray(gsv2.warnings) ? gsv2.warnings : [];

  let html = `<div class="score-v2-container ${compact ? "compact" : ""}">`;
  html += scoreCircleHtml({ score, tier, small: compact });
  if (cats.length) {
    html += '<div class="score-gauges">';
    for (const c of cats) html += scoreGaugeHtml(c);
    html += "</div>";
  }
  html += `</div>`;
  html += scoreAccordionHtml(cats);
  html += scoreWarningsHtml(warns);
  return html;
}

export function renderScoreV2CompareHtml(gsvA, gsvB) {
  if (!gsvA && !gsvB) return "";
  const sA = Number(gsvA?.global_score) || 0;
  const sB = Number(gsvB?.global_score) || 0;
  const delta = sA - sB;
  let deltaLabel;
  if (Math.abs(delta) < 3) deltaLabel = `Scores quasi-identiques (delta ${delta.toFixed(1)} pt).`;
  else if (delta > 0) deltaLabel = `Version A superieure de ${delta.toFixed(1)} points.`;
  else deltaLabel = `Version B superieure de ${Math.abs(delta).toFixed(1)} points.`;

  let html = `<div class="score-v2-compare">`;
  html += `<div class="score-v2-compare-side"><div class="score-v2-compare-label">Version A</div>`;
  html += gsvA ? scoreCircleHtml({ score: sA, tier: gsvA.global_tier }) : '<div class="text-muted">Non analyse</div>';
  html += `</div>`;
  html += `<div class="score-v2-compare-side"><div class="score-v2-compare-label">Version B</div>`;
  html += gsvB ? scoreCircleHtml({ score: sB, tier: gsvB.global_tier }) : '<div class="text-muted">Non analyse</div>';
  html += `</div>`;
  html += `<div class="score-v2-compare-delta">${escapeHtml(deltaLabel)}</div>`;
  html += "</div>";
  return html;
}

export function bindScoreV2Events(root) {
  if (!root) return;
  const headers = root.querySelectorAll(".score-accordion-header");
  headers.forEach((h) => {
    const toggle = () => {
      const section = h.parentElement;
      if (!section) return;
      const expanded = section.classList.toggle("expanded");
      h.setAttribute("aria-expanded", expanded ? "true" : "false");
    };
    h.addEventListener("click", toggle);
    h.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggle();
      }
    });
  });
}
