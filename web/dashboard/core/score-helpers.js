/* dashboard/core/score-helpers.js — VO-C-FRONTEND (Vague O)
 *
 * Helpers waterfall reutilisables par les inspecteurs qui exposent le
 * `quality_score` (score-v2, lib-validation, lib-verification).
 *
 * Spec ROADMAP_VAGUE_O.md item VO-1-SCORE-BREAKDOWN-WATERFALL :
 *   - renderScoreWaterfallHtml(explanation) : bars empilees additives.
 *   - renderCustomFormatsImpact(applied_rule_ids, profileRulesById) :
 *     parite Radarr "CF X +50pts", lookup via profileRulesById[id].
 *   - renderBaselineGauge(baseline) : "X pts du tier Y".
 *   - renderSuggestionsList(suggestions) : actionnable FR.
 *
 * Invariants :
 *   - Tier colors via `var(--tier-*)` (memoire feedback_cinesort_v76_ui).
 *   - Prefix CSS `.score-waterfall-*` EXCLUSIF (memoire feedback_js_release_checks :
 *     pas de classe CSS partagee entre composants DOM differents).
 *   - Le waterfall concerne le quality_score UNIQUEMENT, pas PerceptualScore V2
 *     (memoire feedback_cinesort_design).
 */

import { escapeHtml } from "./dom.js";

const TIER_FR = {
  platinum: "Platinum",
  gold: "Or",
  silver: "Argent",
  bronze: "Bronze",
  reject: "Refuse",
};

const CATEGORY_LABELS_FR = {
  video: "Vidéo",
  audio: "Audio",
  extras: "Extras",
  coherence: "Cohérence",
  custom_rules: "Règles personnalisées",
};

function _tierOf(v) {
  const t = String(v || "").toLowerCase();
  return ["platinum", "gold", "silver", "bronze", "reject"].includes(t) ? t : "unknown";
}

function _fmtSignedNumber(v) {
  const n = Number(v) || 0;
  if (n === 0) return "0";
  const rounded = Math.round(n * 10) / 10;
  return rounded > 0 ? `+${rounded}` : `${rounded}`;
}

function _fmtNumber(v) {
  const n = Number(v) || 0;
  return String(Math.round(n));
}

function _categoryLabel(name) {
  return CATEGORY_LABELS_FR[name] || String(name || "");
}

/* ============================================================
 * renderScoreWaterfallHtml(explanation)
 *
 * Affiche un waterfall additif : baseline -> categories -> total.
 * Chaque categorie est une barre proportionnelle a sa contribution
 * (signed). Les contributions positives sont en vert tier-gold,
 * negatives en rouge tier-reject (utilisation des var(--tier-*)).
 *
 * Backend payload (depuis dashboard_support.compose_score_explanation) :
 *   {
 *     categories: [{name, label, contribution, baseline?, ...}],
 *     baseline: {score, tier, ...},
 *     suggestions: [...],
 *     applied_rule_ids: [...],
 *     narrative: "...",
 *     top_positive: [...],
 *     top_negative: [...]
 *   }
 * ============================================================ */
export function renderScoreWaterfallHtml(explanation) {
  if (!explanation || typeof explanation !== "object") return "";
  const categories = Array.isArray(explanation.categories) ? explanation.categories : [];
  if (!categories.length) return "";

  // Calcul amplitude max pour normaliser les barres.
  const contributions = categories.map((c) => Math.abs(Number(c.contribution) || 0));
  const maxAmp = Math.max(1, ...contributions);

  let html = '<div class="score-waterfall" data-testid="score-waterfall">';
  html += '<div class="score-waterfall-title">Décomposition du score</div>';
  html += '<div class="score-waterfall-bars">';

  for (const cat of categories) {
    const name = String(cat.name || "");
    const label = String(cat.label || _categoryLabel(name));
    const contrib = Number(cat.contribution) || 0;
    const ampPct = (Math.abs(contrib) / maxAmp) * 100;
    const sign = contrib >= 0 ? "positive" : "negative";
    const signClass = contrib >= 0 ? "score-waterfall-bar--positive" : "score-waterfall-bar--negative";
    const rulesCount = Number(cat.rules_count) || 0;
    const isCustomRules = name === "custom_rules";

    html += `<div class="score-waterfall-row" data-category="${escapeHtml(name)}" data-sign="${sign}">`;
    html += `<div class="score-waterfall-label">${escapeHtml(label)}`;
    if (isCustomRules && rulesCount > 0) {
      html += ` <span class="score-waterfall-rules-badge">${rulesCount}</span>`;
    }
    html += `</div>`;
    html += `<div class="score-waterfall-track">`;
    html += `<div class="score-waterfall-bar ${signClass}" style="--waterfall-target:${ampPct.toFixed(1)}%"></div>`;
    html += `</div>`;
    html += `<div class="score-waterfall-value">${escapeHtml(_fmtSignedNumber(contrib))}</div>`;
    html += `</div>`;
  }
  html += "</div>";
  html += "</div>";
  return html;
}

/* ============================================================
 * renderCustomFormatsImpact(applied_rule_ids, profileRulesById)
 *
 * Affiche les regles custom_formats appliquees, parite Radarr.
 * Lookup nom lisible via profileRulesById (transmis par
 * get_active_profile).
 *
 * Si applied_rule_ids vide : retourne "" (rien a afficher).
 * Si profileRulesById absent : affiche l'id brut en fallback.
 * ============================================================ */
export function renderCustomFormatsImpact(applied_rule_ids, profileRulesById) {
  if (!Array.isArray(applied_rule_ids) || !applied_rule_ids.length) return "";

  const lookup = (profileRulesById && typeof profileRulesById === "object") ? profileRulesById : {};

  let html = '<div class="score-waterfall-custom-formats" data-testid="score-waterfall-custom-formats">';
  html += '<div class="score-waterfall-custom-formats-title">Règles personnalisées appliquées</div>';
  html += '<ul class="score-waterfall-custom-formats-list">';
  for (const ruleId of applied_rule_ids) {
    const id = String(ruleId || "");
    if (!id) continue;
    const rule = lookup[id] || {};
    const name = String(rule.name || rule.label || id);
    const score = Number(rule.score || rule.score_delta || 0);
    const scoreLabel = score !== 0 ? _fmtSignedNumber(score) : "";
    html += `<li class="score-waterfall-custom-formats-item" data-rule-id="${escapeHtml(id)}">`;
    html += `<span class="score-waterfall-custom-formats-name">${escapeHtml(name)}</span>`;
    if (scoreLabel) {
      const cls = score >= 0 ? "score-waterfall-custom-formats-score--positive" : "score-waterfall-custom-formats-score--negative";
      html += `<span class="score-waterfall-custom-formats-score ${cls}">${escapeHtml(scoreLabel)} pts</span>`;
    }
    html += `</li>`;
  }
  html += "</ul>";
  html += "</div>";
  return html;
}

/* ============================================================
 * renderBaselineGauge(baseline)
 *
 * Affiche "X pts du tier Y" si baseline.points_to_next defini.
 * baseline payload (depuis explain_score.build_rich_explanation) :
 *   {score, tier, next_tier, points_to_next, ...}
 * ============================================================ */
export function renderBaselineGauge(baseline) {
  if (!baseline || typeof baseline !== "object") return "";
  const tier = _tierOf(baseline.tier || "unknown");
  const tierLabel = TIER_FR[tier] || baseline.tier || "";
  const nextTier = baseline.next_tier ? _tierOf(baseline.next_tier) : "";
  const nextTierLabel = nextTier ? (TIER_FR[nextTier] || baseline.next_tier) : "";
  const pointsToNext = Number(baseline.points_to_next) || 0;
  const score = _fmtNumber(baseline.score);

  let html = '<div class="score-waterfall-baseline" data-testid="score-waterfall-baseline">';
  html += `<span class="score-waterfall-baseline-score tier-${tier}">${escapeHtml(score)} pts</span>`;
  if (tierLabel) {
    html += ` <span class="score-waterfall-baseline-tier">(tier ${escapeHtml(tierLabel)})</span>`;
  }
  if (pointsToNext > 0 && nextTierLabel) {
    html += ` — <span class="score-waterfall-baseline-next">${_fmtNumber(pointsToNext)} pts du tier ${escapeHtml(nextTierLabel)}</span>`;
  }
  html += "</div>";
  return html;
}

/* ============================================================
 * renderSuggestionsList(suggestions)
 *
 * Liste actionnable FR des suggestions retournees par
 * build_rich_explanation. Chaque suggestion peut etre un string
 * brut ou un objet {message, gain?, category?}.
 * ============================================================ */
export function renderSuggestionsList(suggestions) {
  if (!Array.isArray(suggestions) || !suggestions.length) return "";

  let html = '<div class="score-waterfall-suggestions" data-testid="score-waterfall-suggestions">';
  html += '<div class="score-waterfall-suggestions-title">Suggestions d\'amélioration</div>';
  html += '<ul class="score-waterfall-suggestions-list">';
  for (const sugg of suggestions) {
    let message = "";
    let gain = 0;
    if (typeof sugg === "string") {
      message = sugg;
    } else if (sugg && typeof sugg === "object") {
      message = String(sugg.message || sugg.text || sugg.label || "");
      gain = Number(sugg.gain || sugg.points || sugg.delta || 0);
    }
    if (!message) continue;
    html += `<li class="score-waterfall-suggestions-item">`;
    html += `<span class="score-waterfall-suggestions-message">${escapeHtml(message)}</span>`;
    if (gain > 0) {
      html += ` <span class="score-waterfall-suggestions-gain">+${_fmtNumber(gain)} pts</span>`;
    }
    html += `</li>`;
  }
  html += "</ul>";
  html += "</div>";
  return html;
}

/* ============================================================
 * renderQualityWaterfallSection(scoreExplanationFull, opts)
 *
 * Wrapper qui assemble baseline + waterfall + custom formats +
 * suggestions en une seule section "Quality breakdown" reutilisable
 * dans tous les inspecteurs cibles. Renvoie "" si pas d'explanation.
 *
 * opts.profileRulesById : optionnel, pour lookup nom regles custom.
 * ============================================================ */
export function renderQualityWaterfallSection(scoreExplanationFull, opts = {}) {
  if (!scoreExplanationFull || typeof scoreExplanationFull !== "object") return "";

  const baseline = scoreExplanationFull.baseline || null;
  const categories = Array.isArray(scoreExplanationFull.categories) ? scoreExplanationFull.categories : [];
  const suggestions = Array.isArray(scoreExplanationFull.suggestions) ? scoreExplanationFull.suggestions : [];
  const appliedRuleIds = Array.isArray(scoreExplanationFull.applied_rule_ids) ? scoreExplanationFull.applied_rule_ids : [];
  const narrative = String(scoreExplanationFull.narrative || "");

  if (!categories.length && !baseline && !suggestions.length && !appliedRuleIds.length && !narrative) return "";

  let html = '<div class="score-waterfall-section" data-testid="score-waterfall-section">';
  html += '<div class="score-waterfall-section-header">Quality breakdown</div>';
  if (narrative) {
    html += `<div class="score-waterfall-narrative">${escapeHtml(narrative)}</div>`;
  }
  html += renderBaselineGauge(baseline);
  html += renderScoreWaterfallHtml({ categories });
  html += renderCustomFormatsImpact(appliedRuleIds, opts.profileRulesById);
  html += renderSuggestionsList(suggestions);
  html += "</div>";
  return html;
}
