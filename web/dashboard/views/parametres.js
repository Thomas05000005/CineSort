/* views/parametres.js — Phase 3.1-D (spec 11-parametres.md).
 *
 * Nouvelle vue Paramètres avec sub-sidebar 10 categories (selon spec).
 * Pour la PR initiale (3.1-D skeleton), on pose la structure : navigation
 * sub-sidebar, panneau central par categorie, mode expert toggle, recherche.
 * Le CONTENU detaille de chaque categorie viendra en PRs ulterieures :
 * - Phase 3.4 portera la categorie "Profils Qualite" (avec edition seuils/poids)
 * - Les autres categories pointent en attendant vers l'ancienne vue Settings
 *   (/settings, conservee pour retrocompat) ou rendent un schema declaratif
 *   minimal de leurs champs.
 *
 * Layout (spec §1) :
 *   ┌──────────┬───────────────────────────────────┐
 *   │ Sources  │  [contenu de la categorie active] │
 *   │ Analyse  │                                   │
 *   │ ...10    │                                   │
 *   │ [Reset]  │                                   │
 *   └──────────┴───────────────────────────────────┘
 *
 * Mode expert toggle : masque les champs "advanced: true". Persiste dans
 * localStorage cinesort.parametres.expert.
 * Recherche : filtre live des champs visibles (placeholder pour PR future).
 */

import { escapeHtml } from "../core/dom.js";
import { apiPost } from "../core/api.js";
import { navigateTo } from "../core/router.js";

/* --- Categories (spec §2) --------------------------------------------- */

const PARAMETRES_CATEGORIES = [
  { id: "sources", label: "Sources", icon: "📂" },
  { id: "analyse", label: "Analyse", icon: "🔬" },
  { id: "nommage", label: "Nommage", icon: "✏️" },
  { id: "bibliotheque", label: "Bibliothèque", icon: "📚" },
  { id: "integrations", label: "Intégrations", icon: "🔌" },
  { id: "notifications", label: "Notifications", icon: "🔔" },
  { id: "serveur", label: "Serveur distant", icon: "🌐" },
  { id: "apparence", label: "Apparence", icon: "🎨" },
  { id: "profils-qualite", label: "Profils Qualité", icon: "⚡" },
  { id: "avance", label: "Avancé", icon: "⚙️" },
];

const STORAGE_KEY_EXPERT = "cinesort.parametres.expert";
const STORAGE_KEY_LAST_CATEGORY = "cinesort.parametres.last_category";

let _activeCategoryId = "sources";
let _expertMode = false;
let _searchQuery = "";

/* --- localStorage helpers --------------------------------------------- */

function _readBool(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    if (v === null) return fallback;
    return v === "1";
  } catch (_e) {
    return fallback;
  }
}

function _writeBool(key, value) {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch (_e) {
    /* noop */
  }
}

function _readString(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v;
  } catch (_e) {
    return fallback;
  }
}

function _writeString(key, value) {
  try {
    localStorage.setItem(key, String(value));
  } catch (_e) {
    /* noop */
  }
}

/* --- Renderers -------------------------------------------------------- */

function _renderSubSidebar(activeId) {
  const items = PARAMETRES_CATEGORIES.map((cat) => {
    const active = cat.id === activeId;
    return `
      <button type="button" class="parametres-sub-item ${active ? "is-active" : ""}"
              data-category="${escapeHtml(cat.id)}"
              ${active ? 'aria-current="page"' : ''}>
        <span class="parametres-sub-icon" aria-hidden="true">${cat.icon}</span>
        <span class="parametres-sub-label">${escapeHtml(cat.label)}</span>
      </button>
    `;
  }).join("");
  return `
    <aside class="parametres-sub-sidebar" role="navigation" aria-label="Catégories de paramètres">
      <nav class="parametres-sub-nav">${items}</nav>
      <div class="parametres-sub-footer">
        <button type="button" class="v5-btn v5-btn--ghost v5-btn--danger parametres-reset-btn"
                data-parametres-action="reset">↺ Réinitialiser…</button>
      </div>
    </aside>
  `;
}

function _renderHeader() {
  return `
    <header class="parametres-header">
      <h1 class="parametres-title">Paramètres</h1>
      <div class="parametres-controls">
        <label class="parametres-expert-toggle">
          <input type="checkbox" data-parametres-expert ${_expertMode ? "checked" : ""}>
          <span>Mode expert</span>
        </label>
        <div class="parametres-search">
          <input type="search" class="v5-input parametres-search-input"
                 placeholder="🔍 Rechercher (Ctrl+K)..."
                 value="${escapeHtml(_searchQuery)}"
                 data-parametres-search>
        </div>
      </div>
    </header>
  `;
}

const _CATEGORY_PLACEHOLDERS = {
  sources: `
    <p class="parametres-section-intro">Dossiers racines à scanner + patterns d'exclusion.</p>
    <p class="parametres-placeholder">L'édition fine est temporairement disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>. La nouvelle version (édition avec confirmation pour les actions dangereuses) arrive en Phase 3.4.</p>
  `,
  analyse: `
    <p class="parametres-section-intro">ffprobe + mediainfo + analyse perceptuelle + détection sous-titres.</p>
    <p class="parametres-placeholder">L'édition fine est temporairement disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.</p>
  `,
  nommage: `
    <p class="parametres-section-intro">Templates de renommage + options Windows-safe / séparateurs.</p>
    <p class="parametres-placeholder">L'édition fine est temporairement disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.</p>
  `,
  bibliotheque: `
    <p class="parametres-section-intro">Organisation (collection folder, détection TV) + nettoyage (dossiers vides, résidus).</p>
    <p class="parametres-placeholder">L'édition fine est temporairement disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.</p>
  `,
  integrations: `
    <p class="parametres-section-intro">5 services : TMDb · Jellyfin · Plex · Radarr · <strong>OMDb</strong> (visible maintenant, cf spec 03).</p>
    <p class="parametres-placeholder">L'édition fine est temporairement disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.</p>
  `,
  notifications: `
    <p class="parametres-section-intro">Toggles desktop par événement + SMTP email + hooks plugins.</p>
    <p class="parametres-placeholder">L'édition fine est temporairement disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.</p>
  `,
  serveur: `
    <p class="parametres-section-intro">API REST + QR code dashboard + HTTPS (mode expert).</p>
    <p class="parametres-placeholder">L'édition fine est temporairement disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.</p>
  `,
  apparence: `
    <p class="parametres-section-intro">Thème Studio / Cinéma / Luxe / Neon + effets visuels (mode expert).</p>
    <p class="parametres-placeholder">L'édition fine est temporairement disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.</p>
  `,
  "profils-qualite": `
    <p class="parametres-section-intro">Édition des seuils de tier (Platinum/Gold/Silver/Bronze/Reject) et des poids des composantes du Score V2.</p>
    <p class="parametres-placeholder">À implémenter en Phase 3.4 (spec 11 §2.9). Pour l'instant, les seuils par défaut s'appliquent.</p>
  `,
  avance: `
    <p class="parametres-section-intro">Parallélisme + onboarding + MAJ + rétention historique + log level.</p>
    <p class="parametres-placeholder">L'édition fine est temporairement disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.</p>
  `,
};

function _renderCategoryPanel(categoryId) {
  const cat = PARAMETRES_CATEGORIES.find((c) => c.id === categoryId) || PARAMETRES_CATEGORIES[0];
  const placeholder = _CATEGORY_PLACEHOLDERS[cat.id] || "<p>Catégorie inconnue.</p>";
  return `
    <section class="parametres-panel" aria-labelledby="parametres-panel-title">
      <h2 id="parametres-panel-title" class="parametres-panel-title">
        <span class="parametres-panel-icon" aria-hidden="true">${cat.icon}</span>
        ${escapeHtml(cat.label)}
      </h2>
      <div class="parametres-panel-body">
        ${placeholder}
      </div>
    </section>
  `;
}

function _renderParametres() {
  return `
    <section class="parametres-view">
      ${_renderHeader()}
      <div class="parametres-grid">
        ${_renderSubSidebar(_activeCategoryId)}
        <main class="parametres-main" id="parametres-main-content">
          ${_renderCategoryPanel(_activeCategoryId)}
        </main>
      </div>
    </section>
  `;
}

function _renderError(message) {
  return `
    <section class="parametres-view parametres-view--error" role="alert">
      <h2>Les paramètres n'ont pas pu se charger.</h2>
      <p>${escapeHtml(message || "Erreur inconnue")}</p>
      <button type="button" class="v5-btn v5-btn--primary" data-parametres-retry>Réessayer</button>
    </section>
  `;
}

/* --- Events ----------------------------------------------------------- */

function _switchCategory(container, newCategoryId) {
  if (!PARAMETRES_CATEGORIES.some((c) => c.id === newCategoryId)) return;
  _activeCategoryId = newCategoryId;
  _writeString(STORAGE_KEY_LAST_CATEGORY, newCategoryId);
  // Active la nouvelle entree
  container.querySelectorAll("[data-category]").forEach((btn) => {
    const isActive = btn.dataset.category === newCategoryId;
    btn.classList.toggle("is-active", isActive);
    if (isActive) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
  // Re-render le panneau de droite
  const main = container.querySelector("#parametres-main-content");
  if (main) main.innerHTML = _renderCategoryPanel(newCategoryId);
}

function _bindEvents(container) {
  // Categories sidebar
  container.querySelectorAll("[data-category]").forEach((btn) => {
    btn.addEventListener("click", () => _switchCategory(container, btn.dataset.category));
  });

  // Mode expert toggle
  const expertInput = container.querySelector("[data-parametres-expert]");
  if (expertInput) {
    expertInput.addEventListener("change", (ev) => {
      _expertMode = !!ev.target.checked;
      _writeBool(STORAGE_KEY_EXPERT, _expertMode);
      container.classList.toggle("is-expert", _expertMode);
    });
  }

  // Search input
  const searchInput = container.querySelector("[data-parametres-search]");
  if (searchInput) {
    searchInput.addEventListener("input", (ev) => {
      _searchQuery = String(ev.target.value || "");
      // PR future : filtrer les champs visibles. Pour cette PR skeleton, on
      // se contente de stocker la query dans l'etat local.
    });
  }

  // Reset action (placeholder, redirige vers l'ancienne vue qui gere la modale)
  const resetBtn = container.querySelector("[data-parametres-action='reset']");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      // PR future : implementera une vraie modale danger avec liste + countdown.
      navigateTo("/settings");
    });
  }

  // Retry button (cas erreur)
  const retryBtn = container.querySelector("[data-parametres-retry]");
  if (retryBtn) {
    retryBtn.addEventListener("click", () => initParametres(container));
  }
}

/* --- Entrypoint -------------------------------------------------------- */

export async function initParametres(container) {
  if (!container) return;
  // Restore last category + expert mode preferences
  const lastCat = _readString(STORAGE_KEY_LAST_CATEGORY, "sources");
  if (PARAMETRES_CATEGORIES.some((c) => c.id === lastCat)) _activeCategoryId = lastCat;
  _expertMode = _readBool(STORAGE_KEY_EXPERT, false);

  // Pour la PR skeleton, on ne fetch rien : pas de backend cable encore.
  // En PR future on chargera apiPost("settings/get_settings") + ses derivés.
  void apiPost; // garde l'import pour usage futur (suppression de l'avertissement linter).

  container.innerHTML = _renderParametres();
  container.classList.toggle("is-expert", _expertMode);
  _bindEvents(container);
}

export function unmountParametres() {
  // Reset etat local pour eviter les fuites entre nav.
  _activeCategoryId = "sources";
  _searchQuery = "";
}
