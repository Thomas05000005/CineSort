/* views/qualite.js — Phase 3.4 (spec 10-qualite.md) — Vue Qualité audit transverse.
 *
 * 6 sections (spec §1) :
 *  1. Distribution qualité (bargraph 5 tiers)
 *  2. À remplacer en priorité (top 8 mini-posters Reject)
 *  3. Sagas incomplètes
 *  4. Subs FR manquants (count + lien)
 *  5. Décennies (histogramme horizontal)
 *  6. Évolution 30j (graphique line + KPIs delta)
 *
 * + Filtres globaux (décennie / genre / source / audio / période) — placeholder
 * + Action "Re-calculer scores" — placeholder (action longue, modale conf)
 *
 * Pour la PR initiale, sections 1 / 4 / 6 sont câblées sur les endpoints existants
 * (get_global_stats). Les 4 autres (Reject top, sagas, décennies, évolution KPIs)
 * sont des placeholders qui pointent vers les endpoints backend à créer :
 *   - quality/get_films_by_tier
 *   - library/get_incomplete_sagas
 *   - library/get_films_by_decade
 *   - quality/get_history(period)
 *
 * Route cible : /qualite (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { navigateTo } from "../core/router.js";
import * as rightPanel from "../components/right-panel.js";

/* --- Tier order + labels --------------------------------------------- */

const _TIER_ORDER = ["platinum", "gold", "silver", "bronze", "reject"];
const _TIER_LABELS = {
  platinum: "Platinum",
  gold: "Gold",
  silver: "Silver",
  bronze: "Bronze",
  reject: "Reject",
};

function _normalizeTierDist(rawDist) {
  const out = {};
  for (const [k, v] of Object.entries(rawDist || {})) {
    out[String(k).toLowerCase()] = Number(v) || 0;
  }
  return out;
}

function _resolveTierDist(stats) {
  // Priorite v2 si non vide, sinon legacy tier_distribution.
  if (stats && stats.v2_tier_distribution && stats.v2_tier_distribution.counts) {
    const v2 = _normalizeTierDist(stats.v2_tier_distribution.counts);
    const v2sum = _TIER_ORDER.reduce((s, t) => s + (v2[t] || 0), 0);
    if (v2sum > 0) return v2;
  }
  if (stats && stats.tier_distribution) return _normalizeTierDist(stats.tier_distribution);
  return {};
}

/* --- Renderers ------------------------------------------------------- */

function _renderSkeleton() {
  return `
    <section class="qualite-view qualite-view--loading" aria-busy="true">
      <div class="qualite-header"><div class="v5-skeleton qualite-title-skel"></div></div>
      <div class="qualite-section v5-skeleton qualite-section-skel"></div>
      <div class="qualite-section v5-skeleton qualite-section-skel"></div>
    </section>
  `;
}

function _renderError(message) {
  return `
    <section class="qualite-view qualite-view--error" role="alert">
      <h2 class="qualite-error-title">La vue Qualité n'a pas pu se charger.</h2>
      <p>${escapeHtml(message || "Erreur inconnue")}</p>
      <button type="button" class="v5-btn v5-btn--primary" data-qualite-retry>Réessayer</button>
    </section>
  `;
}

function _renderHeader(stats) {
  const total = (stats && stats.summary && stats.summary.total_films) || 0;
  const avgScore = (stats && stats.summary && stats.summary.avg_score) || 0;
  const dist = _resolveTierDist(stats);
  const totalScored = _TIER_ORDER.reduce((s, t) => s + (dist[t] || 0), 0);
  const healthPct = totalScored > 0 ? Math.round(((dist.platinum + dist.gold + dist.silver) / totalScored) * 100) : 0;
  return `
    <header class="qualite-header">
      <h1 class="qualite-title">Qualité — Audit de la bibliothèque</h1>
      <p class="qualite-summary">
        <strong>${total}</strong> films classés ·
        Score moyen <strong>${avgScore}/100</strong> ·
        Santé globale <strong>${healthPct}%</strong>
      </p>
      <div class="qualite-controls" role="toolbar" aria-label="Actions Qualité">
        <button type="button" class="v5-btn v5-btn--secondary" data-qualite-action="filters">▾ Filtres globaux</button>
        <button type="button" class="v5-btn v5-btn--ghost" data-qualite-action="recompute">↻ Re-calculer les scores</button>
      </div>
    </header>
  `;
}

/* Section 1 — Distribution qualité */
function _renderDistributionSection(stats) {
  const dist = _resolveTierDist(stats);
  const total = _TIER_ORDER.reduce((s, t) => s + (dist[t] || 0), 0);
  if (total === 0) {
    return `
      <section class="qualite-section qualite-distribution qualite-empty">
        <h2 class="qualite-section-title">📊 Distribution Qualité</h2>
        <p class="qualite-empty-msg">Aucun film classé. Lance un scan pour calculer les tiers.</p>
      </section>
    `;
  }
  const rows = _TIER_ORDER.map((t) => {
    const count = dist[t] || 0;
    const pct = total > 0 ? Math.round((count / total) * 100) : 0;
    return `
      <div class="qualite-tier-row" data-qualite-tier="${escapeHtml(t)}">
        <span class="qualite-tier-label">${escapeHtml(_TIER_LABELS[t])}</span>
        <div class="qualite-tier-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
          <span class="qualite-tier-fill qualite-tier-fill--${escapeHtml(t)}" style="width:${pct}%"></span>
        </div>
        <span class="qualite-tier-count">${count}</span>
        <span class="qualite-tier-pct">${pct}%</span>
      </div>
    `;
  }).join("");
  return `
    <section class="qualite-section qualite-distribution" aria-labelledby="qualite-distribution-title">
      <h2 id="qualite-distribution-title" class="qualite-section-title">📊 Distribution Qualité <span class="qualite-section-meta">${total} films</span></h2>
      <div class="qualite-tier-bars">${rows}</div>
    </section>
  `;
}

/* Section 2 — À remplacer en priorité (top 8 Reject) */
function _renderRejectSection(stats) {
  const dist = _resolveTierDist(stats);
  const count = dist.reject || 0;
  return `
    <section class="qualite-section qualite-reject" aria-labelledby="qualite-reject-title">
      <h2 id="qualite-reject-title" class="qualite-section-title">🔴 À remplacer en priorité <span class="qualite-section-meta">${count} films Reject</span></h2>
      <p class="qualite-placeholder">
        Liste des 8 films au pire score V2 à venir (endpoint backend <code>quality/get_films_by_tier("reject", limit=8)</code> à créer).
        En attendant : <a href="#/bibliotheque?filter=tier_reject" class="link-primary">voir tous les Reject dans la Bibliothèque</a>.
      </p>
    </section>
  `;
}

/* Section 3 — Sagas incomplètes */
function _renderSagasSection() {
  return `
    <section class="qualite-section qualite-sagas" aria-labelledby="qualite-sagas-title">
      <h2 id="qualite-sagas-title" class="qualite-section-title">⚠️ Sagas incomplètes</h2>
      <p class="qualite-placeholder">
        Endpoint backend <code>library/get_incomplete_sagas()</code> à créer.
        L'Accueil affiche déjà un compteur agrégé ("X sagas avec films manquants").
      </p>
    </section>
  `;
}

/* Section 4 — Subs FR manquants */
function _renderSubsSection(stats) {
  const insights = Array.isArray(stats && stats.insights) ? stats.insights : [];
  const subsInsight = insights.find((i) => String(i.type || i.code || "").includes("subs_missing"));
  const count = subsInsight && subsInsight.count != null ? Number(subsInsight.count) : null;
  // Fallback sur librarian (suggestion id="subs_missing").
  const lsugs = stats && stats.librarian && stats.librarian.suggestions;
  const subsLs = Array.isArray(lsugs) ? lsugs.find((s) => String(s.id || "").includes("subs_missing")) : null;
  const finalCount = count != null ? count : (subsLs && subsLs.count != null ? Number(subsLs.count) : null);
  return `
    <section class="qualite-section qualite-subs" aria-labelledby="qualite-subs-title">
      <h2 id="qualite-subs-title" class="qualite-section-title">💬 Subs FR manquants <span class="qualite-section-meta">${finalCount != null ? finalCount + " films" : "—"}</span></h2>
      <div class="qualite-subs-banner">
        <p>${finalCount != null && finalCount > 0
          ? `<strong>${finalCount} films</strong> n'ont pas de sous-titres FR détectés.`
          : "Tous les films ont des sous-titres FR détectés."}</p>
        <div class="qualite-actions">
          <button type="button" class="v5-btn v5-btn--secondary" data-qualite-action="configure-subs">⚙ Configurer recherche subs</button>
          <a href="#/bibliotheque?filter=subs_missing_fr" class="v5-btn v5-btn--ghost">→ Voir la liste</a>
        </div>
      </div>
    </section>
  `;
}

/* Section 5 — Décennies (placeholder) */
function _renderDecadesSection() {
  return `
    <section class="qualite-section qualite-decades" aria-labelledby="qualite-decades-title">
      <h2 id="qualite-decades-title" class="qualite-section-title">📅 Décennies</h2>
      <p class="qualite-placeholder">
        Histogramme horizontal du nombre de films par décennie (1930s → 2020s) à venir.
        Endpoint backend <code>library/get_films_by_decade()</code> à créer.
      </p>
    </section>
  `;
}

/* Section 6 — Évolution 30j */
function _renderEvolutionSection(stats) {
  const trend = Array.isArray(stats && stats.trend_30days) ? stats.trend_30days : [];
  const validPoints = trend.filter((p) => p && p.avg_score != null);
  const first = validPoints[0];
  const last = validPoints[validPoints.length - 1];
  let deltaTxt = "—";
  let deltaIcon = "→";
  if (first && last) {
    const delta = Math.round((Number(last.avg_score) - Number(first.avg_score)) * 10) / 10;
    deltaTxt = `${delta >= 0 ? "+" : ""}${delta}`;
    deltaIcon = delta > 0 ? "📈" : delta < 0 ? "📉" : "→";
  }
  return `
    <section class="qualite-section qualite-evolution" aria-labelledby="qualite-evolution-title">
      <h2 id="qualite-evolution-title" class="qualite-section-title">📈 Évolution (30 derniers jours)</h2>
      <dl class="qualite-evolution-kpis">
        <div><dt>Δ Score moyen</dt><dd>${escapeHtml(deltaTxt)} ${deltaIcon}</dd></div>
        <div><dt>Points de mesure</dt><dd>${validPoints.length}</dd></div>
      </dl>
      <p class="qualite-placeholder">
        Le graphique line/area complet et les KPIs delta films/reject sont à venir
        (endpoint <code>quality/get_history(period)</code> à créer).
      </p>
    </section>
  `;
}

function _renderQualite(stats) {
  return `
    <section class="qualite-view">
      ${_renderHeader(stats)}
      ${_renderDistributionSection(stats)}
      ${_renderRejectSection(stats)}
      ${_renderSagasSection()}
      ${_renderSubsSection(stats)}
      ${_renderDecadesSection()}
      ${_renderEvolutionSection(stats)}
    </section>
  `;
}

/* --- Inspector content (spec §5) -------------------------------------- */

function _buildInspectorSections(stats) {
  const dist = _resolveTierDist(stats);
  const total = _TIER_ORDER.reduce((s, t) => s + (dist[t] || 0), 0);
  return [
    {
      title: "Vue d'ensemble",
      html: `
        <dl class="qualite-inspector-dl">
          <div><dt>Films classés</dt><dd>${total}</dd></div>
          <div><dt>Score moyen</dt><dd>${(stats && stats.summary && stats.summary.avg_score) || "—"}/100</dd></div>
          <div><dt>Tier dominant</dt><dd>${_TIER_LABELS[_dominantTier(dist)] || "—"}</dd></div>
        </dl>
      `,
    },
    {
      title: "Détail par section",
      html: `
        <p class="qualite-empty-msg">Clique sur une barre Distribution ou une décennie pour voir le détail du tier ou de l'époque sélectionnés.</p>
      `,
    },
    {
      title: "Action longue",
      html: `
        <button type="button" class="v5-btn v5-btn--ghost" data-qualite-action="recompute" style="width:100%">↻ Re-calculer tous les scores</button>
        <p class="qualite-empty-msg" style="margin-top:var(--sp-2);">Utile après modification du profil qualité (Paramètres > Profils Qualité). Durée : 5-10 minutes.</p>
      `,
    },
  ];
}

function _dominantTier(dist) {
  let max = -1;
  let dom = null;
  for (const t of _TIER_ORDER) {
    const v = dist[t] || 0;
    if (v > max) { max = v; dom = t; }
  }
  return dom;
}

function _updateInspector(stats) {
  if (typeof rightPanel.setSections !== "function") return;
  try {
    rightPanel.setSections(_buildInspectorSections(stats));
  } catch (err) {
    console.warn("[qualite] setSections inspector failed:", err);
  }
}

/* --- Events ----------------------------------------------------------- */

function _bindEvents(container) {
  container.querySelectorAll("[data-qualite-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      const action = btn.dataset.qualiteAction;
      switch (action) {
        case "filters":
          // PR future : drawer de filtres globaux.
          alert("Filtres globaux (décennie / genre / source / audio / période) : à implémenter en PR future.");
          break;
        case "recompute":
          // Action dangereuse (longue) : modale de confirmation à créer.
          alert("Re-calcul des scores (5-10 min) : modale de confirmation + JobRunner à implémenter en PR future.");
          break;
        case "configure-subs":
          navigateTo("/parametres#analyse-subs");
          break;
        default:
          break;
      }
    });
  });
  // Clic sur tier bar -> navigation vers Bibliothèque filtrée
  container.querySelectorAll("[data-qualite-tier]").forEach((row) => {
    row.addEventListener("click", () => {
      const tier = row.dataset.qualiteTier;
      navigateTo(`/bibliotheque?filter=tier_${encodeURIComponent(tier)}`);
    });
    row.style.cursor = "pointer";
  });

  const retryBtn = container.querySelector("[data-qualite-retry]");
  if (retryBtn) retryBtn.addEventListener("click", () => initQualite(container));
}

/* --- Entrypoint ------------------------------------------------------- */

export async function initQualite(container) {
  if (!container) return;
  container.innerHTML = _renderSkeleton();
  const signal = typeof getNavSignal === "function" ? getNavSignal() : undefined;

  let res = null;
  try {
    res = await apiPost("get_global_stats", {}, { signal });
  } catch (err) {
    if (err && err.name === "AbortError") return;
    container.innerHTML = _renderError(err ? String(err.message || err) : "Erreur réseau");
    _bindEvents(container);
    return;
  }
  if (!res || res.ok === false) {
    container.innerHTML = _renderError((res && (res.message || res.error)) || "Erreur de chargement.");
    _bindEvents(container);
    return;
  }

  const stats = res.data || res;
  container.innerHTML = _renderQualite(stats);
  _bindEvents(container);
  _updateInspector(stats);
}

export function unmountQualite() {
  /* Pas d'etat global a reinitialiser. */
}
