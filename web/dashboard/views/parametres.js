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
import { renderOmdbStatusInto } from "../components/omdb-status.js";

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

/* Bloc OMDb (spec 03-settings-omdb) — état local, alimenté depuis settings backend. */
let _omdbDraft = { enabled: false, api_key: "", min_confidence: 90 };
let _omdbTesting = false;
let _omdbSaving = false;

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
  integrations: "__SPECIAL_INTEGRATIONS__",
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
  "profils-qualite": "__SPECIAL_PROFILS_QUALITE__",
  avance: `
    <p class="parametres-section-intro">Parallélisme + onboarding + MAJ + rétention historique + log level.</p>
    <p class="parametres-placeholder">L'édition fine est temporairement disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.</p>
  `,
};

/* --- Panneau spécifique Profils Qualité (Phase 3.1-D, spec 11 §2.9) ----- */

let _profilDraft = null;  // { platinum, gold, silver, bronze }
let _profilSaving = false;
let _profilMessage = null;

const _DEFAULT_TIERS = { platinum: 85, gold: 68, silver: 54, bronze: 30 };

function _renderProfilsQualitePanel() {
  const t = _profilDraft || _DEFAULT_TIERS;
  return `
    <p class="parametres-section-intro">
      Seuils des tiers Score V2 : un film est classé selon son score global (0-100).
      L'ordre logique est <strong>Platinum &gt; Gold &gt; Silver &gt; Bronze &gt; Reject</strong>
      (en-dessous du seuil Bronze = Reject).
    </p>
    <form class="parametres-profils-form" data-parametres-profils-form>
      <div class="parametres-tier-row">
        <label for="tier-platinum">
          <span class="parametres-tier-badge parametres-tier-badge--platinum">⬤ Platinum</span>
          score ≥
        </label>
        <input type="number" id="tier-platinum" name="platinum" min="0" max="100" value="${t.platinum}" data-tier-input="platinum">
      </div>
      <div class="parametres-tier-row">
        <label for="tier-gold">
          <span class="parametres-tier-badge parametres-tier-badge--gold">⬤ Gold</span>
          score ≥
        </label>
        <input type="number" id="tier-gold" name="gold" min="0" max="100" value="${t.gold}" data-tier-input="gold">
      </div>
      <div class="parametres-tier-row">
        <label for="tier-silver">
          <span class="parametres-tier-badge parametres-tier-badge--silver">⬤ Silver</span>
          score ≥
        </label>
        <input type="number" id="tier-silver" name="silver" min="0" max="100" value="${t.silver}" data-tier-input="silver">
      </div>
      <div class="parametres-tier-row">
        <label for="tier-bronze">
          <span class="parametres-tier-badge parametres-tier-badge--bronze">⬤ Bronze</span>
          score ≥
        </label>
        <input type="number" id="tier-bronze" name="bronze" min="0" max="100" value="${t.bronze}" data-tier-input="bronze">
      </div>
      ${_profilMessage ? `<p class="parametres-profils-message">${escapeHtml(_profilMessage)}</p>` : ""}
      <div class="parametres-profils-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-parametres-profils-action="save" ${_profilSaving ? "disabled" : ""}>
          ${_profilSaving ? "Sauvegarde…" : "💾 Sauvegarder"}
        </button>
        <button type="button" class="v5-btn v5-btn--ghost" data-parametres-profils-action="reset">↺ Restaurer les défauts</button>
      </div>
    </form>
    <p class="parametres-placeholder">
      L'édition fine des poids (vidéo/audio/extras) et des bonus codec/HDR/audio
      reste disponible dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.
      Cette édition Phase 3.1-D ne couvre que les <strong>seuils de tier</strong>.
    </p>
  `;
}

function _renderIntegrationsPanel() {
  const enabled = !!_omdbDraft.enabled;
  const apiKey = String(_omdbDraft.api_key || "");
  const threshold = Number(_omdbDraft.min_confidence ?? 90);
  return `
    <p class="parametres-section-intro">
      5 services : TMDb · Jellyfin · Plex · Radarr · <strong>OMDb</strong>.
      Édition fine TMDb/Jellyfin/Plex/Radarr dans <a href="#/settings" class="link-primary">l'ancienne vue Paramètres</a>.
    </p>

    <section class="parametres-integration-card" aria-labelledby="parametres-omdb-title">
      <h3 id="parametres-omdb-title" class="parametres-integration-title">
        OMDb <span class="parametres-integration-subtitle">(cross-check IMDb)</span>
      </h3>

      <div class="parametres-omdb-row">
        <label class="parametres-omdb-toggle">
          <input type="checkbox" data-omdb-field="enabled" ${enabled ? "checked" : ""}>
          <span>Activer le cross-check IMDb</span>
        </label>
        <p class="parametres-omdb-hint">
          Quand la confiance TMDb est basse, OMDb valide ou conteste le match.
          Convergence : +20 confidence. Désaccord : −25 + warning sur la ligne.
        </p>
      </div>

      <div class="parametres-omdb-row">
        <label for="parametres-omdb-key">Clé API OMDb</label>
        <div class="parametres-omdb-key-wrap">
          <input type="password" id="parametres-omdb-key" class="v5-input"
                 data-omdb-field="api_key"
                 autocomplete="off"
                 placeholder="Collez votre clé OMDb..."
                 value="${escapeHtml(apiKey)}">
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-omdb-toggle-show title="Afficher / masquer">👁</button>
          <button type="button" class="v5-btn v5-btn--sm" data-omdb-test ${_omdbTesting ? "disabled" : ""}>
            ${_omdbTesting ? "Test…" : "Tester"}
          </button>
        </div>
        <p class="parametres-omdb-hint">
          Gratuit 1000 req/jour sur
          <a href="https://www.omdbapi.com/apikey.aspx" target="_blank" rel="noopener noreferrer">omdbapi.com/apikey.aspx</a>.
        </p>
        <div class="parametres-omdb-status-slot" data-omdb-status></div>
      </div>

      <div class="parametres-omdb-row">
        <label for="parametres-omdb-threshold">Seuil d'appel OMDb (confiance %)</label>
        <input type="number" id="parametres-omdb-threshold" class="v5-input parametres-omdb-threshold"
               min="0" max="100" value="${threshold}"
               data-omdb-field="min_confidence">
        <p class="parametres-omdb-hint">
          Appeler OMDb seulement si la confiance TMDb est &lt; ce seuil
          (défaut : 90 ; plus bas = moins d'appels mais moins de cross-check).
        </p>
      </div>

      <div class="parametres-omdb-actions">
        <button type="button" class="v5-btn v5-btn--primary" data-omdb-save ${_omdbSaving ? "disabled" : ""}>
          ${_omdbSaving ? "Sauvegarde…" : "💾 Sauvegarder"}
        </button>
      </div>
    </section>
  `;
}

function _renderCategoryPanel(categoryId) {
  const cat = PARAMETRES_CATEGORIES.find((c) => c.id === categoryId) || PARAMETRES_CATEGORIES[0];
  const raw = _CATEGORY_PLACEHOLDERS[cat.id] || "<p>Catégorie inconnue.</p>";
  let body;
  if (raw === "__SPECIAL_PROFILS_QUALITE__") body = _renderProfilsQualitePanel();
  else if (raw === "__SPECIAL_INTEGRATIONS__") body = _renderIntegrationsPanel();
  else body = raw;
  return `
    <section class="parametres-panel" aria-labelledby="parametres-panel-title">
      <h2 id="parametres-panel-title" class="parametres-panel-title">
        <span class="parametres-panel-icon" aria-hidden="true">${cat.icon}</span>
        ${escapeHtml(cat.label)}
      </h2>
      <div class="parametres-panel-body">
        ${body}
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

  // Profils Qualité — inputs + actions
  container.querySelectorAll("[data-tier-input]").forEach((input) => {
    input.addEventListener("input", (ev) => {
      const key = ev.target.dataset.tierInput;
      if (!_profilDraft) _profilDraft = { ..._DEFAULT_TIERS };
      _profilDraft[key] = Math.max(0, Math.min(100, parseInt(ev.target.value, 10) || 0));
    });
  });

  container.querySelectorAll("[data-parametres-profils-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.parametresProfilsAction;
      if (action === "save") {
        _saveProfilsQualite(container);
      } else if (action === "reset") {
        _profilDraft = { ..._DEFAULT_TIERS };
        _profilMessage = "Seuils restaurés aux valeurs par défaut. Cliquez sur Sauvegarder pour appliquer.";
        _rerenderPanel(container);
      }
    });
  });

  // --- Intégrations / OMDb (spec 03-settings-omdb) ----------------------
  _bindOmdbEvents(container);

  // Affichage initial du status OMDb (état 1 ou 2) après chaque (re)render
  _refreshOmdbInitialStatus(container);
}

function _bindOmdbEvents(container) {
  // Changements de champs (debounce save côté serveur via bouton explicit)
  container.querySelectorAll("[data-omdb-field]").forEach((input) => {
    const evt = input.type === "checkbox" ? "change" : "input";
    input.addEventListener(evt, (ev) => {
      const key = input.dataset.omdbField;
      if (key === "enabled") _omdbDraft.enabled = !!ev.target.checked;
      else if (key === "api_key") _omdbDraft.api_key = String(ev.target.value || "");
      else if (key === "min_confidence") {
        const v = parseInt(ev.target.value, 10);
        _omdbDraft.min_confidence = Number.isFinite(v) ? Math.max(0, Math.min(100, v)) : 90;
      }
      // Si la clé change → l'utilisateur doit retester
      if (key === "api_key") {
        _refreshOmdbInitialStatus(container);
      }
    });
  });

  // Show/hide clé
  const showBtn = container.querySelector("[data-omdb-toggle-show]");
  const keyInput = container.querySelector('input[data-omdb-field="api_key"]');
  if (showBtn && keyInput) {
    showBtn.addEventListener("click", () => {
      keyInput.type = keyInput.type === "password" ? "text" : "password";
    });
  }

  // Bouton Tester
  const testBtn = container.querySelector("[data-omdb-test]");
  if (testBtn) {
    testBtn.addEventListener("click", () => _testOmdbConnection(container));
  }

  // Bouton Sauvegarder
  const saveBtn = container.querySelector("[data-omdb-save]");
  if (saveBtn) {
    saveBtn.addEventListener("click", () => _saveOmdbSettings(container));
  }
}

function _refreshOmdbInitialStatus(container) {
  const slot = container.querySelector("[data-omdb-status]");
  if (!slot) return;
  const key = String(_omdbDraft.api_key || "").trim();
  if (!key) {
    renderOmdbStatusInto(slot, { ok: false, error_code: "empty_key" });
  } else {
    slot.innerHTML = `<span class="omdb-status omdb-status--info" role="status">
        <span class="omdb-status__label">Cliquez sur Tester pour vérifier la clé</span>
      </span>`;
  }
}

async function _testOmdbConnection(container) {
  if (_omdbTesting) return;
  const slot = container.querySelector("[data-omdb-status]");
  if (!slot) return;
  _omdbTesting = true;
  // Mise à jour bouton + état "test en cours"
  const btn = container.querySelector("[data-omdb-test]");
  if (btn) { btn.disabled = true; btn.textContent = "Test…"; }
  slot.innerHTML = `<span class="omdb-status omdb-status--info" role="status">
      <span class="omdb-status__label">Test en cours…</span>
    </span>`;
  try {
    const res = await apiPost("integrations/test_omdb_connection", {
      api_key: _omdbDraft.api_key,
    });
    const data = (res && res.data) || {};
    renderOmdbStatusInto(slot, data);
  } catch (_e) {
    renderOmdbStatusInto(slot, { ok: false, error_code: "network" });
  } finally {
    _omdbTesting = false;
    if (btn) { btn.disabled = false; btn.textContent = "Tester"; }
  }
}

async function _saveOmdbSettings(container) {
  if (_omdbSaving) return;
  _omdbSaving = true;
  const btn = container.querySelector("[data-omdb-save]");
  if (btn) { btn.disabled = true; btn.textContent = "Sauvegarde…"; }
  try {
    const cur = await apiPost("settings/get_settings", {});
    if (!cur || cur.ok === false) throw new Error("Lecture paramètres impossible");
    const settings = cur.data || cur;
    settings.omdb_enabled = !!_omdbDraft.enabled;
    settings.omdb_api_key = String(_omdbDraft.api_key || "");
    settings.omdb_min_confidence_for_call = Number(_omdbDraft.min_confidence) || 90;
    const res = await apiPost("settings/save_settings", { settings });
    if (!res || res.ok === false) {
      throw new Error((res && (res.message || res.error)) || "Sauvegarde refusée");
    }
  } catch (err) {
    // Affiche l'erreur dans le slot status
    const slot = container.querySelector("[data-omdb-status]");
    if (slot) {
      renderOmdbStatusInto(slot, {
        ok: false,
        error_code: "network",
        message: err && err.message ? err.message : "Sauvegarde impossible",
      });
    }
  } finally {
    _omdbSaving = false;
    if (btn) { btn.disabled = false; btn.textContent = "💾 Sauvegarder"; }
  }
}

function _rerenderPanel(container) {
  const main = container.querySelector("#parametres-main-content");
  if (main) main.innerHTML = _renderCategoryPanel(_activeCategoryId);
  _bindEvents(container);
}

async function _saveProfilsQualite(container) {
  if (_profilSaving) return;
  const t = _profilDraft || _DEFAULT_TIERS;
  // Validation ordre logique (Platinum > Gold > Silver > Bronze)
  if (!(t.platinum > t.gold && t.gold > t.silver && t.silver > t.bronze)) {
    _profilMessage = "Erreur : les seuils doivent être strictement décroissants (Platinum > Gold > Silver > Bronze).";
    _rerenderPanel(container);
    return;
  }
  _profilSaving = true;
  _profilMessage = "Sauvegarde en cours…";
  _rerenderPanel(container);
  try {
    const cur = await apiPost("settings/get_settings", {});
    if (!cur || cur.ok === false) throw new Error("Lecture des paramètres impossible");
    const settings = cur.data || cur;
    const profile = (settings.quality_profile && typeof settings.quality_profile === "object")
      ? { ...settings.quality_profile }
      : {};
    profile.tiers = { ...t };
    settings.quality_profile = profile;
    const res = await apiPost("settings/save_settings", { settings });
    if (!res || res.ok === false) throw new Error((res && (res.message || res.error)) || "Sauvegarde refusée");
    _profilMessage = "✓ Seuils sauvegardés. Effet immédiat sur les futurs scans.";
  } catch (err) {
    _profilMessage = `Erreur : ${err && err.message ? err.message : String(err)}`;
  } finally {
    _profilSaving = false;
    _rerenderPanel(container);
  }
}

/* --- Entrypoint -------------------------------------------------------- */

export async function initParametres(container) {
  if (!container) return;
  // Restore last category + expert mode preferences
  const lastCat = _readString(STORAGE_KEY_LAST_CATEGORY, "sources");
  if (PARAMETRES_CATEGORIES.some((c) => c.id === lastCat)) _activeCategoryId = lastCat;
  _expertMode = _readBool(STORAGE_KEY_EXPERT, false);

  container.innerHTML = _renderParametres();
  container.classList.toggle("is-expert", _expertMode);
  _bindEvents(container);

  // Charge les seuils tier + bloc OMDb depuis settings backend
  try {
    const cur = await apiPost("settings/get_settings", {});
    if (cur && cur.ok !== false) {
      const settings = cur.data || cur;
      const profile = settings.quality_profile && typeof settings.quality_profile === "object" ? settings.quality_profile : null;
      const tiers = profile && profile.tiers && typeof profile.tiers === "object" ? profile.tiers : null;
      if (tiers) {
        _profilDraft = {
          platinum: Number(tiers.platinum) || _DEFAULT_TIERS.platinum,
          gold: Number(tiers.gold) || _DEFAULT_TIERS.gold,
          silver: Number(tiers.silver) || _DEFAULT_TIERS.silver,
          bronze: Number(tiers.bronze) || _DEFAULT_TIERS.bronze,
        };
      }
      // OMDb (spec 03-settings-omdb)
      _omdbDraft = {
        enabled: !!settings.omdb_enabled,
        api_key: String(settings.omdb_api_key || ""),
        min_confidence: Number(settings.omdb_min_confidence_for_call ?? 90),
      };
      // Si on est sur la catégorie active, refresh affichage
      if (_activeCategoryId === "profils-qualite" || _activeCategoryId === "integrations") {
        _rerenderPanel(container);
      }
    }
  } catch (_e) {
    /* silencieux : fallback sur les defaults */
  }
}

export function unmountParametres() {
  // Reset etat local pour eviter les fuites entre nav.
  _activeCategoryId = "sources";
  _searchQuery = "";
}
