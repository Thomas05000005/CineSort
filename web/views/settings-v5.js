/* views/settings-v5.js — V5bis-05 (port ES module + REST apiPost)
 *
 * Port de l'IIFE v7.6.0 Vague 6 vers un ES module.
 * Exports : initSettings, unmountSettings, goToCategory, SETTINGS_GROUPS.
 *
 * Architecture preservee :
 *   - Schema declaratif SETTINGS_GROUPS (9 groupes)
 *   - Renderer dynamique par type de champ (toggle, number, text, path, select, api-key, multi-path, update-status)
 *   - Sidebar categories (gauche) + contenu (droite) + search fuzzy top
 *   - Auto-save debounce 500ms apres modification
 *   - Badge "configure" / "non configure" / "partiel" par section
 *   - Preview live pour themes + density
 *   - V3-02 mode expert (toggle + masquage des fields data-advanced)
 *   - V3-03 glossary tooltips (decorateur de label)
 *   - V3-09 Danger Zone (reset_all_user_data)
 *   - V3-12 Section Mises a jour (update_github_repo + check_for_updates)
 */

import { apiPost, escapeHtml } from "./_v5_helpers.js";
import { glossaryTooltip } from "../dashboard/components/glossary-tooltip.js";

/* ===========================================================
 * Schema 9 groupes
 * =========================================================== */

export const SETTINGS_GROUPS = [
  {
    id: "sources", label: "Sources", iconPath: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    sections: [
      { id: "roots", label: "Dossiers racines", fields: [
        { key: "roots", label: "Chemins racine", type: "multi-path", hint: "Séparés par ; ou par ligne", glossaryTerm: "Roots" },
      ]},
      { id: "watch", label: "Surveillance auto (watch folder)", fields: [
        { key: "watch_enabled", label: "Activer la surveillance", type: "toggle" },
        { key: "watch_interval_minutes", label: "Intervalle (min)", type: "number", min: 1, max: 60, default: 5, advanced: true },
      ]},
      { id: "watchlist", label: "Import watchlist", fields: [
        { key: "watchlist_letterboxd_path", label: "CSV Letterboxd", type: "path", placeholder: "chemin vers letterboxd.csv" },
        { key: "watchlist_imdb_path", label: "CSV IMDb", type: "path" },
      ]},
    ],
  },
  {
    id: "analyse", label: "Analyse", iconPath: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    sections: [
      { id: "probe", label: "Probe", fields: [
        { key: "probe_backend", label: "Backend", type: "select", options: [{v:"ffprobe",l:"ffprobe"},{v:"mediainfo",l:"mediainfo"}] },
        { key: "probe_timeout_s", label: "Timeout probe (s)", type: "number", min: 5, max: 300, advanced: true },
      ]},
      { id: "perceptual", label: "Analyse perceptuelle", fields: [
        { key: "perceptual_enabled", label: "Activer l'analyse perceptuelle", type: "toggle", glossaryTerm: "Score perceptuel" },
        { key: "perceptual_auto_on_scan", label: "Auto-lancer sur scan", type: "toggle" },
        { key: "perceptual_frames_count", label: "Frames analysées", type: "number", min: 5, max: 30, advanced: true },
        { key: "perceptual_timeout_per_film_s", label: "Timeout par film (s)", type: "number", min: 30, max: 600, advanced: true },
        { key: "perceptual_audio_deep", label: "Audio analyse approfondie", type: "toggle", advanced: true },
        { key: "perceptual_audio_fingerprint_enabled", label: "Audio fingerprint (§3)", type: "toggle", advanced: true, glossaryTerm: "Chromaprint" },
        { key: "perceptual_audio_spectral_enabled", label: "Spectral cutoff (§9)", type: "toggle", advanced: true },
        { key: "perceptual_audio_mel_enabled", label: "Mel spectrogram (§12)", type: "toggle", advanced: true },
        { key: "perceptual_ssim_self_ref_enabled", label: "SSIM self-ref / fake 4K (§13)", type: "toggle", advanced: true, glossaryTerm: "Faux 4K" },
        { key: "perceptual_hdr10_plus_detection_enabled", label: "HDR10+ detection (§5)", type: "toggle", advanced: true, glossaryTerm: "HDR10+" },
        { key: "perceptual_grain_intelligence_enabled", label: "Grain Intelligence v2 (§15)", type: "toggle", advanced: true },
        { key: "perceptual_lpips_enabled", label: "LPIPS ONNX (§11)", type: "toggle", advanced: true, glossaryTerm: "LPIPS" },
      ]},
      { id: "scoring", label: "Scoring qualité", fields: [
        { key: "auto_approve_enabled", label: "Approbation auto", type: "toggle" },
        { key: "auto_approve_threshold", label: "Seuil confiance (%)", type: "number", min: 70, max: 100 },
      ]},
    ],
  },
  {
    id: "nommage", label: "Nommage", iconPath: '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
    sections: [
      { id: "templates", label: "Templates de renommage", fields: [
        { key: "naming_preset", label: "Preset", type: "select", options: [
          {v:"default",l:"Défaut"},{v:"plex",l:"Plex"},{v:"jellyfin",l:"Jellyfin"},{v:"quality",l:"Qualité"},{v:"custom",l:"Custom"},
        ], livePreview: "naming" },
        { key: "naming_movie_template", label: "Template film", type: "text", placeholder: "{title} ({year})", livePreview: "naming" },
        { key: "naming_tv_template", label: "Template série", type: "text", placeholder: "{series} ({year})", livePreview: "naming" },
      ]},
    ],
  },
  {
    id: "bibliotheque", label: "Bibliothèque", iconPath: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    sections: [
      { id: "organization", label: "Organisation", fields: [
        { key: "collection_folder_enabled", label: "Regrouper les sagas en _Collection/", type: "toggle" },
        { key: "enable_tv_detection", label: "Détection séries TV", type: "toggle" },
      ]},
      { id: "cleanup", label: "Nettoyage", fields: [
        { key: "cleanup_empty_folders", label: "Supprimer dossiers vides", type: "toggle" },
        { key: "cleanup_residuals", label: "Nettoyer fichiers résiduels", type: "toggle" },
      ]},
      { id: "subtitles", label: "Sous-titres", fields: [
        { key: "subtitle_detection_enabled", label: "Détection sous-titres", type: "toggle" },
        { key: "subtitle_expected_languages", label: "Langues attendues", type: "text", placeholder: "fr;en", hint: "Séparées par ;" },
      ]},
    ],
  },
  {
    id: "integrations", label: "Intégrations", iconPath: '<path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/>',
    sections: [
      { id: "tmdb", label: "TMDb", fields: [
        { key: "tmdb_api_key", label: "Clé API TMDb", type: "api-key", glossaryTerm: "TMDb" },
        { key: "tmdb_lang", label: "Langue", type: "text", placeholder: "fr-FR" },
      ]},
      { id: "jellyfin", label: "Jellyfin", fields: [
        { key: "jellyfin_enabled", label: "Activer", type: "toggle" },
        { key: "jellyfin_url", label: "URL", type: "text", placeholder: "http://jellyfin.local:8096" },
        { key: "jellyfin_api_key", label: "Clé API", type: "api-key" },
        { key: "jellyfin_refresh_on_apply", label: "Refresh auto après apply", type: "toggle" },
        { key: "jellyfin_sync_watched", label: "Sync watched", type: "toggle" },
      ]},
      { id: "plex", label: "Plex", fields: [
        { key: "plex_enabled", label: "Activer", type: "toggle" },
        { key: "plex_url", label: "URL", type: "text" },
        { key: "plex_token", label: "Token", type: "api-key" },
        { key: "plex_refresh_on_apply", label: "Refresh après apply", type: "toggle" },
      ]},
      { id: "radarr", label: "Radarr", fields: [
        { key: "radarr_enabled", label: "Activer", type: "toggle" },
        { key: "radarr_url", label: "URL", type: "text" },
        { key: "radarr_api_key", label: "Clé API", type: "api-key" },
      ]},
    ],
  },
  {
    id: "notifications", label: "Notifications", iconPath: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    sections: [
      { id: "desktop", label: "Desktop", fields: [
        { key: "notifications_enabled", label: "Activer", type: "toggle" },
        { key: "notifications_scan_done", label: "Scan termine", type: "toggle" },
        { key: "notifications_apply_done", label: "Apply termine", type: "toggle" },
        { key: "notifications_errors", label: "Erreurs critiques", type: "toggle" },
      ]},
      { id: "email", label: "Rapports email", fields: [
        { key: "email_enabled", label: "Activer", type: "toggle" },
        { key: "email_host", label: "SMTP host", type: "text", advanced: true },
        { key: "email_port", label: "SMTP port", type: "number", min: 1, max: 65535, advanced: true },
        { key: "email_user", label: "Utilisateur", type: "text", advanced: true },
        { key: "email_password", label: "Mot de passe", type: "api-key", advanced: true },
        { key: "email_to", label: "Destinataire", type: "text" },
        { key: "email_on_scan", label: "Après scan", type: "toggle", advanced: true },
        { key: "email_on_apply", label: "Après apply", type: "toggle", advanced: true },
      ]},
      { id: "plugins", label: "Plugins hooks", fields: [
        { key: "plugins_enabled", label: "Activer plugins", type: "toggle" },
        { key: "plugins_timeout_s", label: "Timeout (s)", type: "number", min: 5, max: 120, advanced: true },
      ]},
    ],
  },
  {
    id: "serveur", label: "Serveur distant", iconPath: '<rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
    sections: [
      { id: "rest", label: "API REST", fields: [
        { key: "rest_api_enabled", label: "Activer API REST", type: "toggle" },
        { key: "rest_api_port", label: "Port", type: "number", min: 1024, max: 65535 },
        { key: "rest_api_token", label: "Token Bearer", type: "api-key" },
      ]},
      { id: "https", label: "HTTPS (optionnel)", fields: [
        { key: "rest_api_https_enabled", label: "Activer HTTPS", type: "toggle", advanced: true },
        { key: "rest_api_cert_path", label: "Chemin certificat", type: "path", advanced: true },
        { key: "rest_api_key_path", label: "Chemin clé", type: "path", advanced: true },
      ]},
    ],
  },
  {
    id: "apparence", label: "Apparence", iconPath: '<circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>',
    sections: [
      { id: "theme", label: "Thème", fields: [
        { key: "theme", label: "Thème", type: "select", options: [
          {v:"studio",l:"Studio"},{v:"cinema",l:"Cinéma"},{v:"luxe",l:"Luxe"},{v:"neon",l:"Neon"},
        ], livePreview: "theme" },
        { key: "animation_level", label: "Niveau animation", type: "select", options: [
          {v:"subtle",l:"Subtil"},{v:"moderate",l:"Modéré"},{v:"intense",l:"Intense"},
        ]},
      ]},
      { id: "density", label: "Densité", fields: [
        { key: "ui_density", label: "Densité interface", type: "select", options: [
          {v:"compact",l:"Compact"},{v:"comfortable",l:"Confortable"},{v:"spacious",l:"Spacieux"},
        ], default: "comfortable", livePreview: "density" },
      ]},
    ],
  },
  {
    id: "avance", label: "Avancé", iconPath: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    sections: [
      { id: "logs", label: "Logs", fields: [
        { key: "log_level", label: "Niveau log", type: "select", options: [
          {v:"DEBUG",l:"DEBUG"},{v:"INFO",l:"INFO"},{v:"WARNING",l:"WARNING"},{v:"ERROR",l:"ERROR"},
        ]},
      ]},
      { id: "cache", label: "Cache", fields: [
        { key: "cache_size_limit_mb", label: "Limite cache (MB)", type: "number", min: 10, max: 10000 },
      ]},
      { id: "parallelism", label: "Parallélisme", fields: [
        { key: "perceptual_parallelism_mode", label: "Mode parallélisme", type: "select", options: [
          {v:"auto",l:"Auto"},{v:"sequential",l:"Séquentiel"},{v:"parallel_2",l:"2 workers"},{v:"parallel_4",l:"4 workers"},
        ]},
      ]},
      { id: "onboarding", label: "Onboarding", fields: [
        { key: "onboarding_completed", label: "Wizard premier lancement terminé", type: "toggle" },
      ]},
      // V3-12 — Mises a jour
      { id: "updates", label: "Mises à jour", fields: [
        { key: "update_github_repo", label: "Dépôt GitHub (owner/repo)", type: "text", placeholder: "user/cinesort", hint: "Vide = check désactivé" },
        { key: "__update_status__", label: "État des mises à jour", type: "update-status" },
      ]},
    ],
  },
];

const _state = {
  containerRef: null,
  settings: {},
  activeCategory: "sources",
  searchQuery: "",
  saveTimer: null,
  savedAt: null,
};

function _esc(s) {
  return escapeHtml(String(s ?? ""));
}

function _svg(pathContent, size) {
  const s = size || 18;
  return `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${pathContent}</svg>`;
}

/* ===========================================================
 * V3-02 — Mode expert : bascule classe body + masque fields advanced
 * =========================================================== */

function _applyExpertMode(isExpert) {
  document.body.classList.toggle("v5-expert-mode-on", !!isExpert);
  document.body.classList.toggle("v5-expert-mode-off", !isExpert);
  document.querySelectorAll(".v5-settings-field[data-advanced='true']").forEach((el) => {
    el.style.display = isExpert ? "" : "none";
  });
}

/* ===========================================================
 * Search fuzzy sur labels de champs
 * =========================================================== */

function _searchMatch(query, group) {
  if (!query) return true;
  const q = query.toLowerCase().trim();
  if (!q) return true;
  if (group.label.toLowerCase().includes(q)) return true;
  for (const section of group.sections || []) {
    if (section.label.toLowerCase().includes(q)) return true;
    for (const field of section.fields || []) {
      if ((field.label || "").toLowerCase().includes(q)) return true;
      if ((field.hint || "").toLowerCase().includes(q)) return true;
      if ((field.key || "").toLowerCase().includes(q)) return true;
    }
  }
  return false;
}

function _sectionMatchesQuery(query, section) {
  if (!query) return true;
  const q = query.toLowerCase().trim();
  if (!q) return true;
  if (section.label.toLowerCase().includes(q)) return true;
  for (const field of section.fields || []) {
    if ((field.label || "").toLowerCase().includes(q)) return true;
    if ((field.hint || "").toLowerCase().includes(q)) return true;
    if ((field.key || "").toLowerCase().includes(q)) return true;
  }
  return false;
}

/* ===========================================================
 * Configure status (badge per section)
 * =========================================================== */

function _isFieldConfigured(field, settings) {
  const val = settings[field.key];
  if (val === undefined || val === null || val === "") return false;
  if (field.type === "toggle") return Boolean(val);
  if (field.type === "number") return Number(val) !== 0;
  return true;
}

function _sectionStatus(section, settings) {
  if (!section.fields || section.fields.length === 0) return "none";
  const configured = section.fields.filter((f) => _isFieldConfigured(f, settings)).length;
  const total = section.fields.length;
  if (configured === 0) return "none";
  if (configured === total) return "full";
  return "partial";
}

function _sectionStatusBadge(status) {
  if (status === "full") return '<span class="v5-settings-badge v5-settings-badge--full">configuré</span>';
  if (status === "partial") return '<span class="v5-settings-badge v5-settings-badge--partial">partiel</span>';
  return "";
}

/* ===========================================================
 * Field renderers
 * =========================================================== */

function _renderField(field, value) {
  const id = `v5s_${_esc(field.key)}`;
  const common = `id="${id}" data-field-key="${_esc(field.key)}" ${field.livePreview ? `data-live-preview="${_esc(field.livePreview)}"` : ""}`;
  // V3-02 : propager data-advanced sur le wrapper du field si flag advanced.
  const advAttr = field.advanced ? ' data-advanced="true"' : "";
  // V3-03 : si glossaryTerm defini, decorer le label avec un tooltip glossaire.
  const labelHtml = field.glossaryTerm
    ? glossaryTooltip(field.glossaryTerm, field.label)
    : _esc(field.label);

  switch (field.type) {
    case "toggle":
      return `
        <label class="v5-settings-field v5-settings-field--toggle"${advAttr}>
          <span class="v5-settings-field-label">${labelHtml}</span>
          <input type="checkbox" class="v5-checkbox" ${common} ${value ? "checked" : ""}>
          ${field.hint ? `<span class="v5-settings-field-hint">${_esc(field.hint)}</span>` : ""}
        </label>
      `;

    case "number":
      return `
        <div class="v5-settings-field"${advAttr}>
          <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
          <input type="number" class="v5-input v5-input--sm" ${common}
                 min="${_esc(field.min || 0)}" max="${_esc(field.max || 999999)}"
                 value="${_esc(value || field.default || "")}">
          ${field.hint ? `<span class="v5-settings-field-hint">${_esc(field.hint)}</span>` : ""}
        </div>
      `;

    case "text":
    case "path":
      return `
        <div class="v5-settings-field"${advAttr}>
          <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
          <input type="text" class="v5-input" ${common}
                 placeholder="${_esc(field.placeholder || "")}"
                 value="${_esc(value || "")}">
          ${field.hint ? `<span class="v5-settings-field-hint">${_esc(field.hint)}</span>` : ""}
        </div>
      `;

    case "api-key":
      return `
        <div class="v5-settings-field"${advAttr}>
          <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
          <div class="v5-settings-api-key-wrap">
            <input type="password" class="v5-input" ${common}
                   value="${_esc(value || "")}" autocomplete="off">
            <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost"
                    data-api-key-toggle="${id}" aria-label="Afficher / masquer">
              ${_svg('<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>', 14)}
            </button>
          </div>
        </div>
      `;

    case "select":
      return `
        <div class="v5-settings-field"${advAttr}>
          <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
          <select class="v5-select" ${common}>
            ${(field.options || []).map((o) =>
              `<option value="${_esc(o.v)}" ${o.v === value ? "selected" : ""}>${_esc(o.l)}</option>`
            ).join("")}
          </select>
        </div>
      `;

    case "multi-path": {
      const arr = Array.isArray(value) ? value : (typeof value === "string" ? value.split(";") : []);
      return `
        <div class="v5-settings-field"${advAttr}>
          <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
          <textarea class="v5-textarea" ${common} rows="4">${_esc(arr.join("\n"))}</textarea>
          ${field.hint ? `<span class="v5-settings-field-hint">${_esc(field.hint)}</span>` : ""}
        </div>
      `;
    }

    case "update-status": {
      // V3-12 — bloc autonome (status + bouton + toggle auto-check).
      // Les IDs ci-dessous sont attendus par le badge dashboard et les tests.
      const auto = _state.settings.auto_check_updates;
      const checked = (auto === undefined ? !!_state.settings.update_check_enabled : !!auto) ? "checked" : "";
      return `
        <section class="updates-section v5-settings-update">
          <h2 class="v5-settings-update-title">Mises à jour</h2>
          <div id="updateStatusContent" class="v5-settings-update-status">
            <p class="text-muted v5u-text-muted">Chargement...</p>
          </div>
          <button type="button" class="btn v5-btn v5-btn--sm" id="btnCheckUpdates">Vérifier maintenant</button>
          <label class="switch-label v5-settings-update-toggle">
            <input type="checkbox" id="ckAutoCheckUpdates" ${checked} />
            <span>Vérifier automatiquement au démarrage</span>
          </label>
        </section>
      `;
    }

    default:
      return `<div class="v5-settings-field">${_esc(field.label)} (type ${_esc(field.type)} non supporte)</div>`;
  }
}

function _readField(field, fieldEl) {
  if (!fieldEl) return undefined;
  switch (field.type) {
    case "toggle": return !!fieldEl.checked;
    case "number": return Number(fieldEl.value) || 0;
    case "multi-path":
      return fieldEl.value.split(/[\n;]+/).map((s) => s.trim()).filter(Boolean);
    case "api-key":
    case "text":
    case "path":
    case "select":
    default:
      return fieldEl.value;
  }
}

/* ===========================================================
 * V3-12 — Update status helpers
 * =========================================================== */

async function _loadUpdateStatus() {
  const el = document.getElementById("updateStatusContent");
  if (!el) return;
  const res = await apiPost("get_update_info");
  if (!res.ok) {
    el.innerHTML = `<p class="v5u-text-muted">Statut indisponible.</p>`;
    return;
  }
  const info = res.data || {};
  const current = info.current_version || "?";
  const latest = info.latest_version;
  if (info.update_available && latest) {
    el.innerHTML = `
      <div class="update-card update-card--available">
        <p>🎉 <strong>Nouvelle version disponible</strong> : ${_esc(latest)}</p>
        <p>Tu utilises la v${_esc(current)}.</p>
        <a class="btn v5-btn v5-btn--primary" href="${_esc(info.release_url || "")}" target="_blank" rel="noopener">
          Télécharger sur GitHub
        </a>
        <p class="v5u-text-muted v5-settings-update-notes">${_esc(info.release_notes_short || "")}</p>
      </div>
    `;
  } else if (latest) {
    el.innerHTML = `<p>✅ Tu es à jour (v${_esc(current)}).</p>`;
  } else {
    el.innerHTML = `<p class="v5u-text-muted">Pas d'info disponible. Clique sur "Vérifier maintenant".</p>`;
  }
}

function _bindUpdateStatusEvents(container) {
  const btn = container.querySelector("#btnCheckUpdates");
  if (btn && !btn.__v5Bound) {
    btn.__v5Bound = true;
    btn.addEventListener("click", async (e) => {
      const target = e.currentTarget;
      target.disabled = true;
      const old = target.textContent;
      target.textContent = "Vérification...";
      await apiPost("check_for_updates");
      await _loadUpdateStatus();
      target.disabled = false;
      target.textContent = old;
    });
  }
  const toggle = container.querySelector("#ckAutoCheckUpdates");
  if (toggle && !toggle.__v5Bound) {
    toggle.__v5Bound = true;
    toggle.addEventListener("change", (e) => {
      _state.settings.auto_check_updates = !!e.target.checked;
      _state.settings.update_check_enabled = !!e.target.checked;
      _scheduleSave();
    });
  }
  if (container.querySelector("#updateStatusContent")) {
    _loadUpdateStatus();
  }
}

/* ===========================================================
 * Sidebar categories
 * =========================================================== */

function _renderSidebar(container) {
  const items = SETTINGS_GROUPS.map((g) => {
    const visible = _searchMatch(_state.searchQuery, g);
    if (!visible) return "";
    const isActive = g.id === _state.activeCategory;
    // Status : si au moins une section de ce groupe a au moins un champ configure
    let totalFields = 0, configuredFields = 0;
    g.sections.forEach((s) => {
      s.fields.forEach((f) => {
        totalFields += 1;
        if (_isFieldConfigured(f, _state.settings)) configuredFields += 1;
      });
    });
    const status = configuredFields === 0 ? "none"
                 : configuredFields === totalFields ? "full" : "partial";
    const dot = status !== "none"
      ? `<span class="v5-settings-cat-dot v5-settings-cat-dot--${_esc(status)}" title="${configuredFields}/${totalFields} configures"></span>`
      : "";
    return `
      <button type="button" class="v5-settings-cat ${isActive ? "is-active" : ""}"
              data-settings-cat="${_esc(g.id)}"
              role="tab" aria-selected="${isActive ? "true" : "false"}">
        <span class="v5-settings-cat-icon">${_svg(g.iconPath, 18)}</span>
        <span class="v5-settings-cat-label">${_esc(g.label)}</span>
        ${dot}
      </button>
    `;
  }).join("");

  container.innerHTML = `
    <div class="v5-settings-sidebar">
      <div class="v5-settings-search-wrap">
        <input type="text" class="v5-input v5-input--sm" data-v5-settings-search
               placeholder="Rechercher..." value="${_esc(_state.searchQuery)}">
      </div>
      <nav class="v5-settings-cats" role="tablist" aria-label="Catégories paramètres">
        ${items || `<div class="v5u-text-muted v5u-p-3">Aucune correspondance</div>`}
      </nav>
    </div>
  `;

  container.querySelectorAll("[data-settings-cat]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _state.activeCategory = btn.dataset.settingsCat;
      _renderActiveCategory();
      _renderSidebarActiveState();
    });
  });

  const searchInput = container.querySelector("[data-v5-settings-search]");
  if (searchInput) {
    let debounce = null;
    searchInput.addEventListener("input", () => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(() => {
        _state.searchQuery = searchInput.value;
        _refreshAll();
      }, 150);
    });
  }
}

function _renderSidebarActiveState() {
  const root = _state.containerRef;
  if (!root) return;
  root.querySelectorAll("[data-settings-cat]").forEach((btn) => {
    const active = btn.dataset.settingsCat === _state.activeCategory;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
}

/* ===========================================================
 * Content (category active)
 * =========================================================== */

function _renderContent(container) {
  const group = SETTINGS_GROUPS.find((g) => g.id === _state.activeCategory);
  if (!group) {
    container.innerHTML = `<div class="v5-settings-empty">Groupe introuvable.</div>`;
    return;
  }

  const sections = group.sections.filter((s) => _sectionMatchesQuery(_state.searchQuery, s));

  // V3-09 : Danger Zone uniquement dans "avance" (et seulement si pas de recherche active
  // qui exclut les sections du groupe).
  const showDangerZone = group.id === "avance" && _sectionMatchesQuery(_state.searchQuery, {
    label: "Zone de danger reinitialiser",
    fields: [{ label: "reset reinitialiser danger" }],
  });

  container.innerHTML = `
    <div class="v5-settings-content">
      <header class="v5-settings-header">
        <h2 class="v5-settings-header-title">${_svg(group.iconPath, 22)} ${_esc(group.label)}</h2>
        <div class="v5-settings-saved-state" data-v5-saved-state></div>
        <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-v5-settings-reload>
          Recharger
        </button>
      </header>

      ${sections.length === 0 && !showDangerZone
        ? `<div class="v5-settings-empty">Aucune section ne correspond a votre recherche.</div>`
        : sections.map((section) => _renderSection(group, section)).join("") + (showDangerZone ? _renderDangerZone() : "")}
    </div>
  `;

  _bindContentEvents(container);
  if (showDangerZone) _bindDangerZoneEvents(container);
  _updateSavedStateLabel();
}

/* ===========================================================
 * V3-09 — Danger Zone (Reset all user data)
 * =========================================================== */

function _renderDangerZone() {
  return `
    <section class="danger-zone" data-v5-danger-zone>
      <h2>${_svg('<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>', 20)} Zone de danger</h2>
      <div class="danger-card">
        <h3>Reinitialiser toutes mes donnees</h3>
        <p>Supprime ta base de donnees, tes parametres, l'historique des runs, les caches TMDb et les analyses perceptuelles.</p>
        <p><strong>Preserve</strong> : tes fichiers video (jamais touches), les logs (utiles pour debug).</p>
        <p class="text-muted">Un backup ZIP automatique est cree avant la suppression dans le dossier parent.</p>
        <p id="userDataSizeInfo" class="text-muted">Donnees actuelles : ...</p>
        <button type="button" class="v5-btn btn--danger" data-v5-open-reset-dialog>Reinitialiser...</button>
      </div>
    </section>
  `;
}

function _bindDangerZoneEvents(container) {
  const sizeEl = container.querySelector("#userDataSizeInfo");
  if (sizeEl) {
    apiPost("get_user_data_size").then((res) => {
      const data = (res && res.data) || {};
      sizeEl.textContent = `Donnees actuelles : ${data.items || 0} fichiers (${data.size_mb || 0} MB)`;
    }).catch(() => {
      sizeEl.textContent = "Donnees actuelles : indisponibles";
    });
  }

  const btn = container.querySelector("[data-v5-open-reset-dialog]");
  if (btn) btn.addEventListener("click", _openResetDialog);
}

async function _openResetDialog() {
  const sizeRes = await apiPost("get_user_data_size");
  const sizeData = (sizeRes && sizeRes.data) || {};
  const sizeMb = sizeData.size_mb || 0;
  const items = sizeData.items || 0;

  const confirm1 = window.prompt(
    `Tu vas supprimer ${items} fichiers (${sizeMb} MB) de donnees utilisateur.\n\n` +
    `Tape exactement "RESET" pour confirmer (ou Annuler pour abandonner) :`
  );
  if (confirm1 !== "RESET") {
    if (confirm1 !== null) window.alert("Mauvaise confirmation. Reset annule.");
    return;
  }

  if (!window.confirm("DERNIERE CHANCE : continuer le reset ?\n(un backup sera cree avant la suppression)")) return;

  const res = await apiPost("reset_all_user_data", { confirmation: "RESET" });
  if (res.ok) {
    const backupPath = (res.data && res.data.backup_path) || "";
    window.alert(`Reset termine.\n\nBackup cree : ${backupPath}\n\nL'application va se rafraichir.`);
    window.location.reload();
  } else {
    window.alert("Erreur : " + (res.error || "inconnue"));
  }
}

function _renderSection(group, section) {
  const status = _sectionStatus(section, _state.settings);
  const fields = (section.fields || []).map((f) => _renderField(f, _state.settings[f.key])).join("");
  return `
    <section class="v5-settings-section" data-section-id="${_esc(section.id)}">
      <header class="v5-settings-section-header">
        <h3 class="v5-settings-section-title">${_esc(section.label)}</h3>
        ${_sectionStatusBadge(status)}
        <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-reset-section="${_esc(section.id)}" title="Réinitialiser cette section">
          Réinit.
        </button>
      </header>
      <div class="v5-settings-section-body">
        ${fields}
      </div>
    </section>
  `;
}

function _bindContentEvents(container) {
  // Field changes
  container.querySelectorAll("[data-field-key]").forEach((fieldEl) => {
    const key = fieldEl.dataset.fieldKey;
    const field = _findFieldByKey(key);
    const livePreview = fieldEl.dataset.livePreview;

    const handler = () => {
      const v = _readField(field, fieldEl);
      _state.settings[key] = v;

      // Live preview
      if (livePreview === "theme") {
        document.documentElement.setAttribute("data-theme", String(v));
      } else if (livePreview === "density") {
        document.documentElement.setAttribute("data-density", String(v));
      }
      _scheduleSave();
    };

    if (field?.type === "toggle" || field?.type === "select") {
      fieldEl.addEventListener("change", handler);
    } else {
      fieldEl.addEventListener("input", handler);
    }
  });

  // Api-key toggles
  container.querySelectorAll("[data-api-key-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.apiKeyToggle;
      const input = container.querySelector("#" + id);
      if (input) input.type = input.type === "password" ? "text" : "password";
    });
  });

  // Reload
  const reloadBtn = container.querySelector("[data-v5-settings-reload]");
  if (reloadBtn) {
    reloadBtn.addEventListener("click", async () => {
      await _loadSettings();
      _refreshAll();
    });
  }

  // Reset per section
  container.querySelectorAll("[data-reset-section]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const sectionId = btn.dataset.resetSection;
      const group = SETTINGS_GROUPS.find((g) => g.id === _state.activeCategory);
      const section = group?.sections.find((s) => s.id === sectionId);
      if (!section) return;
      if (!window.confirm(`Réinitialiser la section "${section.label}" ?`)) return;
      (section.fields || []).forEach((f) => {
        if (f.default !== undefined) _state.settings[f.key] = f.default;
        else if (f.type === "toggle") _state.settings[f.key] = false;
        else if (f.type === "number") _state.settings[f.key] = 0;
        else _state.settings[f.key] = "";
      });
      _scheduleSave();
      _refreshAll();
    });
  });

  // V3-12 — Update status section bindings (silencieux si non rendue)
  _bindUpdateStatusEvents(container);
}

function _findFieldByKey(key) {
  for (const g of SETTINGS_GROUPS) {
    for (const s of g.sections || []) {
      const f = (s.fields || []).find((x) => x.key === key);
      if (f) return f;
    }
  }
  return null;
}

/* ===========================================================
 * Save / Load
 * =========================================================== */

function _scheduleSave() {
  if (_state.saveTimer) clearTimeout(_state.saveTimer);
  _state.saveTimer = setTimeout(async () => {
    const res = await apiPost("save_settings", { settings: _state.settings });
    if (res.ok) {
      _state.savedAt = new Date();
      _updateSavedStateLabel();
    } else {
      console.error("[settings-v5] save error:", res.error);
    }
  }, 500);
}

function _updateSavedStateLabel() {
  const root = _state.containerRef;
  if (!root) return;
  const el = root.querySelector("[data-v5-saved-state]");
  if (!el) return;
  if (_state.savedAt) {
    const diff = Math.round((Date.now() - _state.savedAt.getTime()) / 1000);
    el.innerHTML = `<span class="v5u-text-muted">Sauvegarde ${diff < 5 ? "a l'instant" : "il y a " + diff + "s"}</span>`;
  } else {
    el.innerHTML = "";
  }
}

async function _loadSettings() {
  const res = await apiPost("get_settings");
  if (res.ok && res.data && typeof res.data === "object") {
    _state.settings = res.data;
  }
}

/* ===========================================================
 * Refresh / Mount
 * =========================================================== */

function _refreshAll() {
  const root = _state.containerRef;
  if (!root) return;
  const sidebarHost = root.querySelector("[data-v5-settings-sidebar]");
  const contentHost = root.querySelector("[data-v5-settings-content]");
  if (sidebarHost) _renderSidebar(sidebarHost);
  if (contentHost) _renderContent(contentHost);
  // V3-02 : re-appliquer l'etat expert sur les fields fraichement rendus.
  _applyExpertMode(!!_state.settings.expert_mode);
}

function _renderActiveCategory() {
  const root = _state.containerRef;
  if (!root) return;
  const contentHost = root.querySelector("[data-v5-settings-content]");
  if (contentHost) _renderContent(contentHost);
  // V3-02 : re-appliquer l'etat expert sur les fields fraichement rendus.
  _applyExpertMode(!!_state.settings.expert_mode);
}

export async function initSettings(container, opts = {}) {
  if (!container) return;
  _state.containerRef = container;
  _state.activeCategory = opts.category || "sources";
  await _loadSettings();
  // V3-02 : toggle Mode expert place AU-DESSUS du shell (visible peu importe la categorie).
  const expertChecked = _state.settings.expert_mode ? "checked" : "";
  container.innerHTML = `
    <div class="v5-settings-expert-toggle" data-v5-expert-toggle>
      <label class="v5-toggle-label">
        <input type="checkbox" id="v5CkExpertMode" ${expertChecked} />
        <span><strong>Mode expert</strong> — afficher tous les paramètres avancés</span>
      </label>
      <p class="v5-text-muted">Désactivé par défaut. Active pour tweaker timeouts, ports, retries, HTTPS, etc.</p>
    </div>
    <div class="v5-settings-shell">
      <aside data-v5-settings-sidebar></aside>
      <section data-v5-settings-content class="v5-settings-main"></section>
    </div>
  `;
  _refreshAll();
  // V3-02 : appliquer l'etat persiste apres render initial (les fields sont presents).
  _applyExpertMode(!!_state.settings.expert_mode);
  // V3-02 : listener change sur le toggle (persiste via auto-save 500ms existant).
  const expertToggle = container.querySelector("#v5CkExpertMode");
  if (expertToggle) {
    expertToggle.addEventListener("change", (e) => {
      const checked = !!e.target.checked;
      _state.settings.expert_mode = checked;
      _applyExpertMode(checked);
      _scheduleSave();
    });
  }
}

export function goToCategory(catId) {
  if (!SETTINGS_GROUPS.find((g) => g.id === catId)) return;
  _state.activeCategory = catId;
  _renderActiveCategory();
  _renderSidebarActiveState();
}

export function unmountSettings() {
  if (_state.saveTimer) clearTimeout(_state.saveTimer);
  if (_state.containerRef) _state.containerRef.innerHTML = "";
  _state.containerRef = null;
}
