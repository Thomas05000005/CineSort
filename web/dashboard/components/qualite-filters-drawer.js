/* components/qualite-filters-drawer.js — Phase 5 (spec 10-qualite.md §3)
 *
 * Drawer global de filtres pour la vue Qualité.
 *
 * Filtres exposés (spec §3, moins Genre — cf. note R4-P7 plus bas) :
 *   - Décennie  (multi-select 1930s → 2020s)
 *   - Source    (BluRay / WEB-DL / DVD / Autre)
 *   - Audio language (FR / EN / multi)
 *   - Période (Aujourd'hui / 7j / 30j / 90j / Tout) — utilisé par section Évolution
 *
 * API publique :
 *   openQualiteFiltersDrawer({ initial, onApply, onReset }) — ouvre le drawer
 *   closeQualiteFiltersDrawer()                              — ferme
 *
 * Le drawer slide depuis la droite, est replieable via Esc / clic backdrop,
 * et appelle onApply(filters) à la confirmation.
 */

import { escapeHtml } from "../core/dom.js";
import { trapFocus } from "./modal.js"; // R8-078b (filet F6-a) : piège de focus partagé

const DRAWER_ID = "qualiteFiltersDrawer";

const DECADES = ["1930", "1940", "1950", "1960", "1970", "1980", "1990", "2000", "2010", "2020"];
// AUDIT 2026-06-11 (R4-P7) : la section "Genres TMDb" (19 checkboxes) est
// RETIRÉE du drawer — les rows bibliothèque n'embarquent pas les genres TMDb,
// donc le backend (_row_matches) ne peut pas filtrer dessus : cocher un genre
// affichait un badge actif et un toast "Filtres appliqués" sans AUCUN effet
// sur les données (contrôle mort, mensonger pour l'utilisateur). La clé
// `genres: []` reste dans l'état/payload pour compat. À réintroduire le jour
// où les rows porteront les genres (enrichissement TMDb au scan).
const SOURCES = ["BluRay", "WEB-DL", "WEB-Rip", "DVD", "HDTV", "Autre"];
const AUDIO_LANGS = ["FR", "EN", "Multi", "Autre"];
const PERIODS = [
  { value: "1", label: "Aujourd'hui" },
  { value: "7", label: "7 jours" },
  { value: "30", label: "30 jours" },
  { value: "90", label: "90 jours" },
  { value: "0", label: "Tout" },
];

const EMPTY_FILTERS = {
  decades: [],
  genres: [],
  sources: [],
  audio_languages: [],
  period_days: 30,
};

function _cloneFilters(src) {
  return {
    decades: Array.isArray(src && src.decades) ? [...src.decades] : [],
    genres: Array.isArray(src && src.genres) ? [...src.genres] : [],
    sources: Array.isArray(src && src.sources) ? [...src.sources] : [],
    audio_languages: Array.isArray(src && src.audio_languages) ? [...src.audio_languages] : [],
    period_days: src && src.period_days != null ? Number(src.period_days) : 30,
  };
}

function _renderCheckList(group, options, current) {
  return options.map((opt) => {
    const value = typeof opt === "string" ? opt : opt.value;
    const label = typeof opt === "string" ? `${opt}s`.replace("ss", "s") : opt.label;
    const checked = (current || []).includes(value) ? "checked" : "";
    return `
      <label class="qualite-drawer-check">
        <input type="checkbox" data-qualite-filter-group="${escapeHtml(group)}" value="${escapeHtml(value)}" ${checked} />
        <span>${escapeHtml(typeof opt === "string" ? (group === "decades" ? opt + "s" : opt) : opt.label)}</span>
      </label>
    `;
  }).join("");
}

function _renderRadioList(group, options, currentValue) {
  return options.map((opt) => {
    const value = typeof opt === "string" ? opt : opt.value;
    const label = typeof opt === "string" ? opt : opt.label;
    const checked = String(currentValue) === String(value) ? "checked" : "";
    return `
      <label class="qualite-drawer-check qualite-drawer-check--radio">
        <input type="radio" data-qualite-filter-group="${escapeHtml(group)}" name="${escapeHtml(group)}" value="${escapeHtml(value)}" ${checked} />
        <span>${escapeHtml(label)}</span>
      </label>
    `;
  }).join("");
}

function _buildHtml(state) {
  return `
    <div class="qualite-drawer-backdrop" data-qualite-drawer-backdrop></div>
    <aside class="qualite-drawer" role="dialog" aria-modal="true" aria-labelledby="qualite-drawer-title" tabindex="-1">
      <header class="qualite-drawer-header">
        <h2 id="qualite-drawer-title" class="qualite-drawer-title">Filtres Qualité</h2>
        <button type="button" class="qualite-drawer-close" data-qualite-drawer-close aria-label="Fermer le drawer">×</button>
      </header>
      <div class="qualite-drawer-body">
        <fieldset class="qualite-drawer-group">
          <legend>Décennies</legend>
          <div class="qualite-drawer-checks">${_renderCheckList("decades", DECADES, state.decades)}</div>
        </fieldset>
        <fieldset class="qualite-drawer-group">
          <legend>Source</legend>
          <div class="qualite-drawer-checks">${_renderCheckList("sources", SOURCES, state.sources)}</div>
        </fieldset>
        <fieldset class="qualite-drawer-group">
          <legend>Audio</legend>
          <div class="qualite-drawer-checks">${_renderCheckList("audio_languages", AUDIO_LANGS, state.audio_languages)}</div>
        </fieldset>
        <fieldset class="qualite-drawer-group">
          <legend>Période d'évolution</legend>
          <div class="qualite-drawer-checks">${_renderRadioList("period_days", PERIODS, state.period_days)}</div>
        </fieldset>
      </div>
      <footer class="qualite-drawer-footer">
        <button type="button" class="v5-btn v5-btn--ghost" data-qualite-drawer-reset>Réinitialiser</button>
        <button type="button" class="v5-btn v5-btn--primary" data-qualite-drawer-apply>Appliquer</button>
      </footer>
    </aside>
  `;
}

/**
 * Ouvre le drawer de filtres globaux.
 * @param {object} opts
 * @param {object} [opts.initial] - filtres actuels (decades, genres, sources, audio_languages, period_days)
 * @param {Function} [opts.onApply] - callback(filters) à l'appui sur Appliquer
 * @param {Function} [opts.onReset] - callback() à l'appui sur Réinitialiser
 */
export function openQualiteFiltersDrawer(opts) {
  closeQualiteFiltersDrawer();

  const { initial = {}, onApply = () => {}, onReset = null } = opts || {};
  const state = _cloneFilters({ ...EMPTY_FILTERS, ...initial });

  const container = document.createElement("div");
  container.id = DRAWER_ID;
  container.className = "qualite-drawer-overlay";
  container.innerHTML = _buildHtml(state);
  document.body.appendChild(container);
  trapFocus(container); // R8-078b : Tab/Shift+Tab piégés dans le drawer filtres qualité (aria-modal)

  const previouslyFocused = document.activeElement;
  container._previouslyFocused = previouslyFocused;

  const aside = container.querySelector(".qualite-drawer");
  if (aside) {
    try { aside.focus(); } catch (_e) { /* noop */ }
  }

  // Esc / backdrop / close button
  const close = () => closeQualiteFiltersDrawer();
  container._escHandler = (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
  };
  document.addEventListener("keydown", container._escHandler);

  container.querySelector("[data-qualite-drawer-backdrop]")?.addEventListener("click", close);
  container.querySelector("[data-qualite-drawer-close]")?.addEventListener("click", close);

  // Sync checkbox / radio changes back to state
  container.querySelectorAll("[data-qualite-filter-group]").forEach((input) => {
    input.addEventListener("change", () => {
      const group = input.dataset.qualiteFilterGroup;
      if (group === "period_days") {
        state.period_days = Number(input.value) || 0;
        return;
      }
      const arr = state[group];
      if (!Array.isArray(arr)) return;
      if (input.checked) {
        if (!arr.includes(input.value)) arr.push(input.value);
      } else {
        const idx = arr.indexOf(input.value);
        if (idx >= 0) arr.splice(idx, 1);
      }
    });
  });

  // Reset
  container.querySelector("[data-qualite-drawer-reset]")?.addEventListener("click", () => {
    Object.assign(state, _cloneFilters(EMPTY_FILTERS));
    // Decoche tous
    container.querySelectorAll("input[type=checkbox][data-qualite-filter-group]").forEach((cb) => { cb.checked = false; });
    container.querySelectorAll("input[type=radio][data-qualite-filter-group]").forEach((rb) => {
      rb.checked = String(rb.value) === String(EMPTY_FILTERS.period_days);
    });
    if (typeof onReset === "function") {
      try { onReset(); } catch (err) { console.warn("[qualite-drawer] onReset:", err); }
    }
  });

  // Apply
  container.querySelector("[data-qualite-drawer-apply]")?.addEventListener("click", () => {
    const applied = _cloneFilters(state);
    try {
      onApply(applied);
    } catch (err) {
      console.warn("[qualite-drawer] onApply error:", err);
    }
    close();
  });
}

export function closeQualiteFiltersDrawer() {
  const existing = document.getElementById(DRAWER_ID);
  if (!existing) return;
  if (existing._escHandler) {
    document.removeEventListener("keydown", existing._escHandler);
  }
  const prev = existing._previouslyFocused;
  existing.remove();
  if (prev && typeof prev.focus === "function") {
    try { prev.focus(); } catch (_e) { /* noop */ }
  }
}

/** Exporté pour les tests : filtres "vides" / defaults. */
export function emptyFilters() {
  return _cloneFilters(EMPTY_FILTERS);
}
