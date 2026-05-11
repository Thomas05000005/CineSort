/* components/score-v2.js — §16b v7.5.0
 * Composants UI pour le score composite V2 :
 *   - ScoreCircle : cercle SVG anime avec valeur + tier
 *   - ScoreGauge  : jauge horizontale par categorie
 *   - ScoreAccordion : detail sous-scores cliquable
 * Expose window.ScoreV2 et window.renderScoreV2Container pour usage desktop + dashboard.
 */
(function () {
  "use strict";

  const TIER_LABELS = {
    platinum: "Platinum",
    gold: "Gold",
    silver: "Silver",
    bronze: "Bronze",
    reject: "Reject",
    unknown: "Indetermine",
  };

  // 14 tooltips FR educatifs par sous-score (cf plan §16)
  const SUB_TOOLTIPS = {
    perceptual_visual: "Synthèse block/blur/banding/profondeur effective sur un échantillon de frames.",
    resolution: "Résolution effective + cross-check fake 4K (FFT 2D + SSIM self-ref).",
    hdr_validation: "Présence HDR10/HDR10+/Dolby Vision et intégrité des métadonnées MaxCLL/MaxFALL.",
    lpips_distance: "Distance perceptuelle apprise entre 2 fichiers (mode comparaison uniquement).",
    perceptual_audio: "EBU R128 (LRA, integrated), clipping, bruit de fond. Synthèse audio.",
    spectral_cutoff: "Fréquence de coupure spectrale. Lossless > 19 kHz, AAC 128 ~16 kHz, MP3 ~15 kHz.",
    drc_category: "Compression dynamique : cinéma (large), standard (moyenne), broadcast (agressive).",
    chromaprint: "Empreinte audio Chromaprint (identification robuste face aux ré-encodes).",
    reserve: "Réservé pour futurs critères (NR-VMAF, timbre, etc.).",
    runtime_match: "Durée réelle du fichier vs TMDb. Écart = version alternative probable.",
    nfo_consistency: "Alignement du NFO (titre/année/TMDb ID) avec le fichier.",
  };

  const TIER_FR = {
    platinum: "Platinum",
    gold: "Or",
    silver: "Argent",
    bronze: "Bronze",
    reject: "Refusé",
  };

  const CATEGORY_FR = {
    video: "Video",
    audio: "Audio",
    coherence: "Coherence",
  };

  function _esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function _tierOf(v) {
    const t = String(v || "").toLowerCase();
    return ["platinum", "gold", "silver", "bronze", "reject"].includes(t) ? t : "unknown";
  }

  function _fmtPct(v) {
    const n = Math.max(0, Math.min(100, Number(v) || 0));
    return Math.round(n).toString();
  }

  /**
   * Cercle SVG anime.
   * @param {{ score:number, tier?:string, small?:boolean, label?:string }} opts
   */
  function scoreCircleHtml(opts) {
    const score = Math.max(0, Math.min(100, Number(opts.score) || 0));
    const tier = _tierOf(opts.tier || "unknown");
    const small = !!opts.small;
    const size = small ? 80 : 120;
    const radius = small ? 32 : 50;
    const cx = size / 2;
    const cy = size / 2;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference * (1 - score / 100);
    const tierLabel = TIER_FR[tier] || TIER_LABELS[tier] || "";
    return `
      <div class="score-circle ${small ? "small" : ""} tier-${tier}" data-tier="${_esc(tier)}" data-score="${Math.round(score)}">
        <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" aria-hidden="true">
          <circle class="bg" cx="${cx}" cy="${cy}" r="${radius}"></circle>
          <circle class="fg stroke-${tier}" cx="${cx}" cy="${cy}" r="${radius}"
            stroke-dasharray="${circumference.toFixed(2)}"
            stroke-dashoffset="${offset.toFixed(2)}"></circle>
        </svg>
        <div class="content">
          <div class="value">${_fmtPct(score)}</div>
          <div class="tier">${_esc(tierLabel)}</div>
        </div>
      </div>
    `;
  }

  /**
   * Jauge horizontale pour une categorie.
   * @param {{ name:string, value:number, tier:string, weight?:number }} cat
   */
  function scoreGaugeHtml(cat) {
    const tier = _tierOf(cat.tier);
    const value = Math.max(0, Math.min(100, Number(cat.value) || 0));
    const label = CATEGORY_FR[cat.name] || cat.name;
    return `
      <div class="score-gauge-row" data-category="${_esc(cat.name)}">
        <div class="score-gauge-label">${_esc(label)}</div>
        <div class="score-gauge-track">
          <div class="score-gauge-fill bg-${tier}" style="--gauge-target: ${value.toFixed(1)}%"></div>
        </div>
        <div class="score-gauge-value tier-${tier}">${value.toFixed(0)}</div>
      </div>
    `;
  }

  /**
   * Accordeon detaillant les sous-scores par categorie.
   * @param {Array} categoryScores
   */
  function scoreAccordionHtml(categoryScores) {
    if (!Array.isArray(categoryScores) || !categoryScores.length) return "";
    let html = '<div class="score-accordion">';
    for (const cat of categoryScores) {
      const tier = _tierOf(cat.tier);
      const catLabel = CATEGORY_FR[cat.name] || cat.name;
      const catValue = Math.round(Number(cat.value) || 0);
      html += `<div class="score-accordion-section" data-section="${_esc(cat.name)}">`;
      html += `<div class="score-accordion-header" role="button" tabindex="0" aria-expanded="false">`;
      html += `<span><span class="chevron">&#9656;</span> ${_esc(catLabel)}</span>`;
      html += `<span class="tier-${tier}">${catValue}/100</span>`;
      html += `</div>`;
      html += `<div class="score-accordion-body"><div class="score-sub-list">`;
      for (const sub of cat.sub_scores || []) {
        const subTier = _tierOf(sub.tier || "unknown");
        const conf = Number(sub.confidence) || 0;
        const lowConf = conf > 0 && conf < 0.6;
        const tipText = sub.detail_fr || SUB_TOOLTIPS[sub.name] || "";
        html += `<div class="score-sub-row ${lowConf ? "low-confidence" : ""}" title="${_esc(tipText)}">`;
        html += `<div>`;
        html += `<div class="score-sub-label">${_esc(sub.label_fr || sub.name)}</div>`;
        if (sub.detail_fr) html += `<span class="score-sub-detail">${_esc(sub.detail_fr)}</span>`;
        html += `</div>`;
        if (sub.tier) html += `<span class="score-sub-tier-badge tier-${subTier}">${_esc(TIER_FR[subTier] || sub.tier)}</span>`;
        else html += `<span></span>`;
        html += `<span class="score-sub-value tier-${subTier}">${Math.round(Number(sub.value) || 0)}</span>`;
        html += `</div>`;
      }
      html += `</div></div></div>`;
    }
    html += "</div>";
    return html;
  }

  /**
   * Warnings encarts jaunes.
   * @param {string[]} warnings
   */
  function scoreWarningsHtml(warnings) {
    if (!Array.isArray(warnings) || !warnings.length) return "";
    let html = '<div class="score-warnings">';
    for (const w of warnings) {
      html += `<div class="score-warning">${_esc(w)}</div>`;
    }
    html += "</div>";
    return html;
  }

  /**
   * Rendu complet d'un score V2 : cercle + jauges + accordeon + warnings.
   * @param {object} gsv2 - GlobalScoreResult.to_dict()
   * @param {{ compact?: boolean }} opts
   */
  function renderScoreV2Container(gsv2, opts) {
    if (!gsv2 || typeof gsv2 !== "object") return "";
    opts = opts || {};
    const compact = !!opts.compact;
    const score = Number(gsv2.global_score) || 0;
    const tier = _tierOf(gsv2.global_tier || "unknown");
    const cats = Array.isArray(gsv2.category_scores) ? gsv2.category_scores : [];
    const warns = Array.isArray(gsv2.warnings) ? gsv2.warnings : [];

    let html = `<div class="score-v2-container ${compact ? "compact" : ""}">`;
    html += scoreCircleHtml({ score, tier, small: compact });
    if (cats.length) {
      html += '<div class="score-gauges">';
      for (const c of cats) html += scoreGaugeHtml(c);
      html += '</div>';
    }
    html += `</div>`;
    html += scoreAccordionHtml(cats);
    html += scoreWarningsHtml(warns);
    return html;
  }

  /**
   * Vue compare cote-a-cote (A vs B).
   * @param {object} gsvA
   * @param {object} gsvB
   */
  function renderScoreV2CompareHtml(gsvA, gsvB) {
    if (!gsvA && !gsvB) return "";
    const sA = Number(gsvA?.global_score) || 0;
    const sB = Number(gsvB?.global_score) || 0;
    const delta = sA - sB;
    let deltaLabel;
    if (Math.abs(delta) < 3) deltaLabel = "Scores quasi-identiques (delta " + delta.toFixed(1) + " pt).";
    else if (delta > 0) deltaLabel = `Version A superieure de ${delta.toFixed(1)} points.`;
    else deltaLabel = `Version B superieure de ${Math.abs(delta).toFixed(1)} points.`;

    let html = `<div class="score-v2-compare">`;
    html += `<div class="score-v2-compare-side">`;
    html += `<div class="score-v2-compare-label">Version A</div>`;
    html += gsvA ? scoreCircleHtml({ score: sA, tier: gsvA.global_tier }) : '<div class="text-muted">Non analyse</div>';
    html += `</div>`;
    html += `<div class="score-v2-compare-side">`;
    html += `<div class="score-v2-compare-label">Version B</div>`;
    html += gsvB ? scoreCircleHtml({ score: sB, tier: gsvB.global_tier }) : '<div class="text-muted">Non analyse</div>';
    html += `</div>`;
    html += `<div class="score-v2-compare-delta">${_esc(deltaLabel)}</div>`;
    html += `</div>`;
    return html;
  }

  /**
   * Active les clics sur les headers d'accordeon dans un conteneur.
   * A appeler apres avoir injecte le HTML dans le DOM.
   */
  function bindAccordionEvents(root) {
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

  // Export global
  window.ScoreV2 = {
    scoreCircleHtml,
    scoreGaugeHtml,
    scoreAccordionHtml,
    scoreWarningsHtml,
    renderScoreV2Container,
    renderScoreV2CompareHtml,
    bindAccordionEvents,
    TIER_LABELS,
    TIER_FR,
    CATEGORY_FR,
    SUB_TOOLTIPS,
  };
  window.renderScoreV2Container = renderScoreV2Container;
  window.renderScoreV2CompareHtml = renderScoreV2CompareHtml;
  window.bindScoreV2Events = bindAccordionEvents;
})();
