/* views/bibliotheque.js — Phase 3.2 (spec 07-bibliotheque.md) — squelette.
 *
 * Spec cible : grille de posters TMDb + scroll infini + bulk actions + chips
 * de filtres + checkbox multi-selection + toolbar contextuelle. Effort
 * estime spec : 7 jours.
 *
 * Pour la PR initiale (squelette), on pose la structure et on redirige vers
 * la vue legacy Bibliotheque (workflow 5 etapes) en attendant le portage
 * complet. Le portage des composants (grille de posters, scroll infini,
 * bulk actions) viendra en PRs incrementales : 3.2-A (grille readonly),
 * 3.2-B (chips + filtres), 3.2-C (bulk actions + modales danger).
 *
 * Route cible : /bibliotheque (Phase 2-B PR #261).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { getNavSignal } from "../core/nav-abort.js";
import { navigateTo } from "../core/router.js";

/* --- HTML --- */

function _renderSkeleton() {
  return `
    <section class="bibliotheque-view bibliotheque-view--loading" aria-busy="true">
      <div class="bibliotheque-header"><div class="v5-skeleton bibliotheque-title-skel"></div></div>
      <div class="bibliotheque-section v5-skeleton bibliotheque-section-skel"></div>
    </section>
  `;
}

function _renderError(message) {
  return `
    <section class="bibliotheque-view bibliotheque-view--error" role="alert">
      <h2>La Bibliothèque n'a pas pu se charger.</h2>
      <p>${escapeHtml(message || "Erreur inconnue")}</p>
      <button type="button" class="v5-btn v5-btn--primary" data-bibliotheque-retry>Réessayer</button>
    </section>
  `;
}

function _renderBibliotheque(stats) {
  const total = (stats && stats.summary && stats.summary.total_films) || 0;
  const avgScore = (stats && stats.summary && stats.summary.avg_score) || 0;
  return `
    <section class="bibliotheque-view">
      <header class="bibliotheque-header">
        <h1 class="bibliotheque-title">Bibliothèque</h1>
        <p class="bibliotheque-summary">
          <strong>${total}</strong> films analysés ·
          Score moyen <strong>${avgScore}/100</strong>
        </p>
        <div class="bibliotheque-toolbar" role="toolbar" aria-label="Actions Bibliothèque">
          <input type="search" class="v5-input bibliotheque-search" placeholder="🔍 Rechercher un film..." data-bibliotheque-search>
          <button type="button" class="v5-btn v5-btn--secondary" data-bibliotheque-action="filters">▾ Filtres</button>
          <div class="bibliotheque-view-toggle">
            <button type="button" class="v5-btn v5-btn--ghost is-active" title="Grille de posters">▦</button>
            <button type="button" class="v5-btn v5-btn--ghost" title="Tableau dense">≡</button>
          </div>
        </div>
      </header>
      <section class="bibliotheque-section bibliotheque-coming-soon">
        <h2 class="bibliotheque-section-title">🚧 Refonte en cours</h2>
        <p class="bibliotheque-placeholder">
          La nouvelle Bibliothèque (grille de posters TMDb + scroll infini + bulk actions
          + 6 chips de filtres + modale Détail Film + Modal Perceptuelle dual-mode)
          est en cours d'implémentation. Effort estimé : <strong>~17 jours</strong> dont
          7 j Bibliothèque + 6 j Détail Film + 3.6 j Perceptuelle dual-mode + 6.9 j Doublons.
        </p>
        <p class="bibliotheque-placeholder">
          En attendant, l'ancienne vue workflow reste accessible :
          <a href="#/library" class="v5-btn v5-btn--primary">→ Ouvrir l'ancienne Bibliothèque (workflow 5 étapes)</a>
        </p>
        <p class="bibliotheque-placeholder">
          Pour ouvrir le détail d'un film par son ID :
          <a href="#/film/123" class="link-primary">/film/&lt;id&gt;</a> (la modale Détail Film tri-mode arrive en Phase 3.2 ultérieure).
        </p>
      </section>
    </section>
  `;
}

function _bindEvents(container) {
  const retryBtn = container.querySelector("[data-bibliotheque-retry]");
  if (retryBtn) retryBtn.addEventListener("click", () => initBibliotheque(container));

  container.querySelectorAll("[data-bibliotheque-action]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      const action = btn.dataset.bibliothequeAction;
      if (action === "filters") {
        alert("Drawer Filtres (6 chips) à implémenter en Phase 3.2-B.");
      }
    });
  });
}

/* --- Entrypoint --- */

export async function initBibliotheque(container) {
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
  container.innerHTML = _renderBibliotheque(stats);
  _bindEvents(container);
  void navigateTo;
}

export function unmountBibliotheque() {
  /* noop pour cette PR squelette */
}
