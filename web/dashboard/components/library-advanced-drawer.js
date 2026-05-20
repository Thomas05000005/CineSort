/* components/library-advanced-drawer.js — Drawer "Filtres avances" Bibliotheque
 *
 * Phase 5 spec 07 §2 "+ Bouton Avance" — 10 filtres detailles :
 *  1. Annee (slider min/max 1900-2025)
 *  2. Duree (slider min/max 0-300 min)
 *  3. Taille fichier (slider min/max 0-100 Go)
 *  4. Resolution (multi-select : 480p / 720p / 1080p / 4K / autre)
 *  5. Codec (multi-select : H264 / H265 / AV1 / autre)
 *  6. Source (multi-select : BluRay / WEB / DVD / autre)
 *  7. Audio language (multi-select : fr / en / multi)
 *  8. Subtitle language (multi-select : fr / en / aucun)
 *  9. Confidence (slider 0-100%)
 * 10. Date d'ajout (range picker : added_after / added_before)
 *
 * AND entre filtres. Le drawer renvoie un objet `filters` extensible passable
 * directement a `library/get_library_filtered({filters, ...})`.
 *
 * Usage :
 *   import { openLibraryAdvancedDrawer } from "../components/library-advanced-drawer.js";
 *   openLibraryAdvancedDrawer({ initial: state.advancedFilters, onApply: (f) => {...}, onReset: () => {...} });
 */

import { escapeHtml } from "../core/dom.js";

const DRAWER_ID = "libraryAdvancedDrawer";

const RESOLUTION_OPTIONS = ["480p", "720p", "1080p", "4k", "other"];
const CODEC_OPTIONS = ["h264", "h265", "av1", "other"];
const SOURCE_OPTIONS = ["bluray", "web", "dvd", "other"];
const AUDIO_LANG_OPTIONS = [
  { value: "fr", label: "Francais (fr)" },
  { value: "en", label: "Anglais (en)" },
  { value: "multi", label: "Multi-langues" },
];
const SUB_LANG_OPTIONS = [
  { value: "fr", label: "Francais (fr)" },
  { value: "en", label: "Anglais (en)" },
  { value: "none", label: "Aucun" },
];

const DEFAULTS = {
  year_min: 1900,
  year_max: 2025,
  duration_min: 0,
  duration_max: 300,
  size_min_gb: 0,
  size_max_gb: 100,
  resolution: [],
  codec: [],
  source: [],
  audio_languages: [],
  subtitle_languages: [],
  confidence_min: 0,
  confidence_max: 100,
  added_after: "",
  added_before: "",
};

function _toGb(bytes) {
  if (!bytes) return 0;
  return +(bytes / (1024 * 1024 * 1024)).toFixed(1);
}

function _gbToBytes(gb) {
  const n = Number(gb || 0);
  return Math.round(n * 1024 * 1024 * 1024);
}

function _isoToTs(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t / 1000 : null;
}

function _renderMultiSelect(name, options, current) {
  const sel = new Set((current || []).map((v) => String(v).toLowerCase()));
  return options
    .map((opt) => {
      const value = typeof opt === "string" ? opt : opt.value;
      const label = typeof opt === "string" ? opt.toUpperCase() : opt.label;
      const checked = sel.has(String(value).toLowerCase());
      return `
        <label class="bibliotheque-drawer-checkbox">
          <input type="checkbox" name="${escapeHtml(name)}" value="${escapeHtml(value)}"${checked ? " checked" : ""}>
          <span>${escapeHtml(label)}</span>
        </label>
      `;
    })
    .join("");
}

function _renderRange(name, minVal, maxVal, absMin, absMax, step, suffix) {
  return `
    <div class="bibliotheque-drawer-range">
      <input type="number" class="v5-input bibliotheque-drawer-range-input"
             name="${escapeHtml(name)}_min"
             min="${absMin}" max="${absMax}" step="${step}"
             value="${minVal}" aria-label="${escapeHtml(name)} min">
      <span class="bibliotheque-drawer-range-sep">—</span>
      <input type="number" class="v5-input bibliotheque-drawer-range-input"
             name="${escapeHtml(name)}_max"
             min="${absMin}" max="${absMax}" step="${step}"
             value="${maxVal}" aria-label="${escapeHtml(name)} max">
      ${suffix ? `<span class="bibliotheque-drawer-range-suffix">${escapeHtml(suffix)}</span>` : ""}
    </div>
  `;
}

function _renderDateRange(initial) {
  const after = initial.added_after || "";
  const before = initial.added_before || "";
  return `
    <div class="bibliotheque-drawer-range bibliotheque-drawer-date-range">
      <input type="date" class="v5-input" name="added_after" value="${escapeHtml(after)}" aria-label="Date d'ajout apres">
      <span class="bibliotheque-drawer-range-sep">—</span>
      <input type="date" class="v5-input" name="added_before" value="${escapeHtml(before)}" aria-label="Date d'ajout avant">
    </div>
  `;
}

function _buildHtml(initial) {
  const state = { ...DEFAULTS, ...(initial || {}) };
  return `
    <aside class="bibliotheque-drawer-advanced" role="dialog" aria-modal="true" aria-labelledby="${DRAWER_ID}Title">
      <header class="bibliotheque-drawer-header">
        <h2 id="${DRAWER_ID}Title" class="bibliotheque-drawer-title">Filtres avances</h2>
        <button type="button" class="v5-btn v5-btn--ghost bibliotheque-drawer-close" aria-label="Fermer">x</button>
      </header>
      <div class="bibliotheque-drawer-body">

        <section class="bibliotheque-drawer-section">
          <h3>Annee</h3>
          ${_renderRange("year", state.year_min, state.year_max, 1900, 2025, 1, "")}
        </section>

        <section class="bibliotheque-drawer-section">
          <h3>Duree (minutes)</h3>
          ${_renderRange("duration", state.duration_min, state.duration_max, 0, 600, 5, "min")}
        </section>

        <section class="bibliotheque-drawer-section">
          <h3>Taille fichier (Go)</h3>
          ${_renderRange("size_gb", state.size_min_gb, state.size_max_gb, 0, 200, 0.5, "Go")}
        </section>

        <section class="bibliotheque-drawer-section">
          <h3>Resolution</h3>
          <div class="bibliotheque-drawer-multi">${_renderMultiSelect("resolution", RESOLUTION_OPTIONS, state.resolution)}</div>
        </section>

        <section class="bibliotheque-drawer-section">
          <h3>Codec video</h3>
          <div class="bibliotheque-drawer-multi">${_renderMultiSelect("codec", CODEC_OPTIONS, state.codec)}</div>
        </section>

        <section class="bibliotheque-drawer-section">
          <h3>Source</h3>
          <div class="bibliotheque-drawer-multi">${_renderMultiSelect("source", SOURCE_OPTIONS, state.source)}</div>
        </section>

        <section class="bibliotheque-drawer-section">
          <h3>Audio</h3>
          <div class="bibliotheque-drawer-multi">${_renderMultiSelect("audio_languages", AUDIO_LANG_OPTIONS, state.audio_languages)}</div>
        </section>

        <section class="bibliotheque-drawer-section">
          <h3>Sous-titres</h3>
          <div class="bibliotheque-drawer-multi">${_renderMultiSelect("subtitle_languages", SUB_LANG_OPTIONS, state.subtitle_languages)}</div>
        </section>

        <section class="bibliotheque-drawer-section">
          <h3>Confiance (%)</h3>
          ${_renderRange("confidence", state.confidence_min, state.confidence_max, 0, 100, 5, "%")}
        </section>

        <section class="bibliotheque-drawer-section">
          <h3>Date d'ajout</h3>
          ${_renderDateRange(state)}
        </section>

      </div>
      <footer class="bibliotheque-drawer-footer">
        <button type="button" class="v5-btn v5-btn--ghost" data-drawer-action="reset">Reinitialiser</button>
        <button type="button" class="v5-btn v5-btn--primary" data-drawer-action="apply">Appliquer</button>
      </footer>
    </aside>
    <div class="bibliotheque-drawer-backdrop" data-drawer-backdrop></div>
  `;
}

function _collectValues(rootEl) {
  const out = { ...DEFAULTS };

  const numInputs = rootEl.querySelectorAll("input[type=number]");
  numInputs.forEach((inp) => {
    const name = inp.name;
    const v = Number(inp.value);
    if (Number.isFinite(v)) out[name] = v;
  });

  const dateAfter = rootEl.querySelector('input[name="added_after"]');
  const dateBefore = rootEl.querySelector('input[name="added_before"]');
  if (dateAfter) out.added_after = dateAfter.value || "";
  if (dateBefore) out.added_before = dateBefore.value || "";

  // Multi-selects
  ["resolution", "codec", "source", "audio_languages", "subtitle_languages"].forEach((name) => {
    const boxes = rootEl.querySelectorAll(`input[type=checkbox][name="${name}"]:checked`);
    out[name] = Array.from(boxes).map((b) => b.value);
  });

  return out;
}

/**
 * Transforme le state du drawer en filtres compatibles avec l'endpoint
 * library/get_library_filtered (cf cinesort/ui/api/library_support.py _row_matches).
 */
export function buildBackendFilters(drawerState) {
  const s = { ...DEFAULTS, ...(drawerState || {}) };
  const filters = {};
  if (s.year_min && s.year_min > 1900) filters.year_min = s.year_min;
  if (s.year_max && s.year_max < 2025) filters.year_max = s.year_max;
  if (s.duration_min && s.duration_min > 0) filters.duration_min = s.duration_min;
  if (s.duration_max && s.duration_max < 600) filters.duration_max = s.duration_max;
  if (s.size_min_gb && s.size_min_gb > 0) filters.size_min = _gbToBytes(s.size_min_gb);
  if (s.size_max_gb && s.size_max_gb < 200) filters.size_max = _gbToBytes(s.size_max_gb);
  if (Array.isArray(s.resolution) && s.resolution.length > 0) filters.resolution = s.resolution;
  if (Array.isArray(s.codec) && s.codec.length > 0) filters.codec = s.codec;
  if (Array.isArray(s.source) && s.source.length > 0) filters.source = s.source;
  if (Array.isArray(s.audio_languages) && s.audio_languages.length > 0)
    filters.audio_languages = s.audio_languages;
  if (Array.isArray(s.subtitle_languages) && s.subtitle_languages.length > 0)
    filters.subtitle_languages = s.subtitle_languages;
  if (typeof s.confidence_min === "number" && s.confidence_min > 0)
    filters.confidence_min = s.confidence_min;
  if (typeof s.confidence_max === "number" && s.confidence_max < 100)
    filters.confidence_max = s.confidence_max;
  const af = _isoToTs(s.added_after);
  const ab = _isoToTs(s.added_before);
  if (af != null) filters.added_after = af;
  if (ab != null) filters.added_before = ab;
  return filters;
}

/**
 * Ouvre le drawer Avance.
 *
 * @param {object} opts
 * @param {object} [opts.initial] - state initial (year_min, duration_min, etc.)
 * @param {(state: object, filters: object) => void} opts.onApply - appele a "Appliquer"
 * @param {() => void} [opts.onReset] - appele a "Reinitialiser"
 * @returns {() => void} fonction de fermeture programmatique
 */
export function openLibraryAdvancedDrawer(opts) {
  closeLibraryAdvancedDrawer();
  const { initial = {}, onApply, onReset } = opts || {};

  const host = document.createElement("div");
  host.id = DRAWER_ID;
  host.className = "bibliotheque-drawer-host";
  host.innerHTML = _buildHtml(initial);
  document.body.appendChild(host);
  // Trigger transition next frame
  requestAnimationFrame(() => host.classList.add("is-open"));

  const drawerEl = host.querySelector(".bibliotheque-drawer-advanced");
  const backdrop = host.querySelector("[data-drawer-backdrop]");

  const close = () => {
    host.classList.remove("is-open");
    setTimeout(() => host.remove(), 200);
    document.removeEventListener("keydown", _onKey);
  };

  const _onKey = (ev) => {
    if (ev.key === "Escape") {
      ev.preventDefault();
      close();
    }
  };
  document.addEventListener("keydown", _onKey);

  if (backdrop) backdrop.addEventListener("click", close);
  const closeBtn = host.querySelector(".bibliotheque-drawer-close");
  if (closeBtn) closeBtn.addEventListener("click", close);

  const applyBtn = host.querySelector('[data-drawer-action="apply"]');
  if (applyBtn) {
    applyBtn.addEventListener("click", () => {
      const state = _collectValues(drawerEl);
      const filters = buildBackendFilters(state);
      try { if (typeof onApply === "function") onApply(state, filters); } finally {
        close();
      }
    });
  }

  const resetBtn = host.querySelector('[data-drawer-action="reset"]');
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      // Re-render avec defaults
      host.innerHTML = _buildHtml(DEFAULTS);
      _rebindAfterReset();
      try { if (typeof onReset === "function") onReset(); } catch (_e) { /* noop */ }
    });
  }

  // Apres reset (re-render), il faut re-attacher les handlers internes
  function _rebindAfterReset() {
    const newClose = host.querySelector(".bibliotheque-drawer-close");
    if (newClose) newClose.addEventListener("click", close);
    const newBackdrop = host.querySelector("[data-drawer-backdrop]");
    if (newBackdrop) newBackdrop.addEventListener("click", close);
    const newApply = host.querySelector('[data-drawer-action="apply"]');
    if (newApply) {
      newApply.addEventListener("click", () => {
        const newDrawer = host.querySelector(".bibliotheque-drawer-advanced");
        const state = _collectValues(newDrawer);
        const filters = buildBackendFilters(state);
        try { if (typeof onApply === "function") onApply(state, filters); } finally {
          close();
        }
      });
    }
    const newReset = host.querySelector('[data-drawer-action="reset"]');
    if (newReset) {
      newReset.addEventListener("click", () => {
        host.innerHTML = _buildHtml(DEFAULTS);
        _rebindAfterReset();
        try { if (typeof onReset === "function") onReset(); } catch (_e) { /* noop */ }
      });
    }
  }

  // Focus initial sur "Appliquer" (focus utile clavier)
  if (applyBtn) {
    try { applyBtn.focus(); } catch (_e) { /* noop */ }
  }

  return close;
}

export function closeLibraryAdvancedDrawer() {
  const existing = document.getElementById(DRAWER_ID);
  if (existing) existing.remove();
}

export const ADVANCED_DRAWER_DEFAULTS = DEFAULTS;
