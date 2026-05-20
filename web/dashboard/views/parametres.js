/* views/parametres.js — Phase 5 (spec 11-parametres.md) — vue complete.
 *
 * 10 categories portees depuis settings.js, recherche live Ctrl+K, mode expert
 * persiste dans settings.expert_mode, reset modale avec scopes + CONFIRMER +
 * countdown, profils qualite (selecteur + tiers + sliders poids).
 *
 * Architecture :
 * - PARAMETRES_GROUPS : schema declaratif (categorie -> sections -> fields).
 * - _renderField(field, value) : renderer generique par type (toggle, text,
 *   number, range, api-key, multi-path, select, qr-dashboard, action,
 *   profils-qualite, danger-zone).
 * - Save debounce 500ms via settings/save_settings.
 * - Mode expert : toggle persiste en backend via settings.expert_mode.
 * - Recherche : highlight des labels + auto-switch vers la categorie qui
 *   contient le 1er match.
 * - Reset : dangerConfirmModal + champ "CONFIRMER" + countdown si scope=all,
 *   appelle settings/reset_settings(scope) ou settings/reset_database().
 *
 * Endpoints :
 *   settings/get_settings, settings/save_settings  (existants)
 *   settings/reset_settings(scope), settings/reset_database()  (nouveaux)
 *   settings/get_profiles, settings/save_profile, settings/set_active_profile
 *   settings/get_dashboard_qr, settings/get_server_info, settings/get_user_data_size
 *   integrations/test_<service>_connection  (inline test buttons)
 */

import { apiPost, invalidateSettingsCache } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
import { navigateTo } from "../core/router.js";
import { renderOmdbStatusInto } from "../components/omdb-status.js";
import { dangerConfirmModal } from "../components/modal.js";

/* =============================================================
 * 1) SCHEMA DECLARATIF DES 10 CATEGORIES
 * ============================================================= */

export const PARAMETRES_GROUPS = [
  {
    id: "sources", label: "Sources", icon: "📂",
    sections: [
      { id: "roots", label: "Dossiers racines", fields: [
        { key: "roots", label: "Chemins racine", type: "multi-path", hint: "Un par ligne (ou séparés par ;)", required: true },
      ]},
      { id: "watch", label: "Surveillance automatique", fields: [
        { key: "watch_enabled", label: "Activer la surveillance (watch folder)", type: "toggle" },
        { key: "watch_interval_minutes", label: "Intervalle de vérification (min)", type: "number", min: 1, max: 60, default: 5, advanced: true },
      ]},
    ],
  },
  {
    id: "analyse", label: "Analyse", icon: "🔬",
    sections: [
      { id: "probe", label: "Probe (ffprobe / mediainfo)", fields: [
        { key: "probe_backend", label: "Backend", type: "select", options: [
          {v:"auto",l:"Auto"},{v:"ffprobe",l:"ffprobe"},{v:"mediainfo",l:"mediainfo"},{v:"none",l:"Aucun"},
        ]},
        { key: "probe_timeout_s", label: "Timeout probe (s)", type: "number", min: 5, max: 300, advanced: true },
      ]},
      { id: "perceptual", label: "Analyse perceptuelle", fields: [
        { key: "perceptual_enabled", label: "Activer l'analyse perceptuelle", type: "toggle" },
        { key: "perceptual_auto_on_scan", label: "Auto-lancer sur scan", type: "toggle" },
        { key: "perceptual_frames_count", label: "Frames analysées", type: "number", min: 5, max: 30, advanced: true },
        { key: "perceptual_timeout_per_film_s", label: "Timeout par film (s)", type: "number", min: 30, max: 600, advanced: true },
        { key: "perceptual_audio_deep", label: "Audio analyse approfondie", type: "toggle", advanced: true },
        { key: "perceptual_lpips_enabled", label: "LPIPS ONNX (modèle deep learning)", type: "toggle", advanced: true },
      ]},
      { id: "subtitles", label: "Sous-titres", fields: [
        { key: "subtitle_detection_enabled", label: "Détection sous-titres", type: "toggle" },
        { key: "subtitle_expected_languages", label: "Langues attendues", type: "text", placeholder: "fr;en", hint: "Séparées par ;" },
      ]},
      { id: "scoring", label: "Scoring qualité", fields: [
        { key: "auto_approve_enabled", label: "Approbation automatique", type: "toggle" },
        { key: "auto_approve_threshold", label: "Seuil confiance (%)", type: "number", min: 70, max: 100 },
        { key: "composite_score_version", label: "Version du score composite", type: "select", options: [
          { v: 1, l: "V1 (stable)" }, { v: 2, l: "V2 (avancé)" },
        ], hint: "V1 par défaut. V2 utilise des poids et règles enrichis. Les scores existants ne seront PAS re-calculés." },
      ]},
    ],
  },
  {
    id: "nommage", label: "Nommage", icon: "✏️",
    sections: [
      { id: "templates", label: "Templates de renommage", fields: [
        { key: "naming_preset", label: "Preset", type: "select", options: [
          {v:"default",l:"Défaut"},{v:"plex",l:"Plex"},{v:"jellyfin",l:"Jellyfin"},{v:"quality",l:"Qualité"},{v:"custom",l:"Custom"},
        ]},
        { key: "naming_movie_template", label: "Template film", type: "text", placeholder: "{title} ({year})" },
        { key: "naming_tv_template", label: "Template série", type: "text", placeholder: "{series} ({year})" },
      ]},
    ],
  },
  {
    id: "bibliotheque", label: "Bibliothèque", icon: "📚",
    sections: [
      { id: "organization", label: "Organisation", fields: [
        { key: "collection_folder_enabled", label: "Regrouper les sagas dans _Collection/", type: "toggle" },
        { key: "enable_tv_detection", label: "Détection séries TV", type: "toggle" },
      ]},
      { id: "cleanup", label: "Nettoyage", fields: [
        { key: "move_empty_folders_enabled", label: "Déplacer les dossiers vides vers _Vide", type: "toggle" },
        { key: "cleanup_residual_folders_enabled", label: "Nettoyer fichiers résiduels (.nfo, images, sous-titres)", type: "toggle" },
      ]},
    ],
  },
  {
    id: "integrations", label: "Intégrations", icon: "🔌",
    sections: [
      { id: "tmdb", label: "TMDb", fields: [
        { key: "tmdb_api_key", label: "Clé API TMDb", type: "api-key", required: true,
          testMethod: "integrations/test_tmdb_key", testParams: { api_key: "$value", state_dir: "" } },
        { key: "tmdb_cache_ttl_days", label: "Durée du cache TMDb (jours)", type: "number", min: 1, max: 365 },
      ]},
      { id: "jellyfin", label: "Jellyfin", fields: [
        { key: "jellyfin_enabled", label: "Activer", type: "toggle" },
        { key: "jellyfin_url", label: "URL Jellyfin", type: "text", placeholder: "http://jellyfin.local:8096" },
        { key: "jellyfin_api_key", label: "Clé API", type: "api-key",
          testMethod: "integrations/test_jellyfin_connection", testParams: { url: "$jellyfin_url", api_key: "$value" } },
        { key: "jellyfin_refresh_on_apply", label: "Refresh auto après apply", type: "toggle" },
        { key: "jellyfin_sync_watched", label: "Sync watched", type: "toggle" },
      ]},
      { id: "plex", label: "Plex", fields: [
        { key: "plex_enabled", label: "Activer", type: "toggle" },
        { key: "plex_url", label: "URL Plex", type: "text" },
        { key: "plex_token", label: "Token Plex", type: "api-key",
          testMethod: "integrations/test_plex_connection", testParams: { url: "$plex_url", token: "$value" } },
        { key: "plex_refresh_on_apply", label: "Refresh après apply", type: "toggle" },
      ]},
      { id: "radarr", label: "Radarr", fields: [
        { key: "radarr_enabled", label: "Activer", type: "toggle" },
        { key: "radarr_url", label: "URL Radarr", type: "text" },
        { key: "radarr_api_key", label: "Clé API", type: "api-key",
          testMethod: "integrations/test_radarr_connection", testParams: { url: "$radarr_url", api_key: "$value" } },
      ]},
      { id: "omdb", label: "OMDb", fields: [
        { key: "omdb_enabled", label: "Activer le cross-check IMDb", type: "toggle",
          hint: "Quand la confiance TMDb est basse, OMDb valide ou conteste le match. -25 confidence + warning si désaccord, +20 si convergence." },
        { key: "omdb_api_key", label: "Clé API OMDb", type: "api-key",
          testMethod: "integrations/test_omdb_connection", testParams: { api_key: "$value" },
          hint: "Gratuit 1000 req/jour sur omdbapi.com/apikey.aspx" },
        { key: "omdb_min_confidence_for_call", label: "Seuil d'appel OMDb (confiance)", type: "number",
          min: 0, max: 100, hint: "Appeler OMDb seulement si la confiance TMDb est < ce seuil (défaut: 90)" },
      ]},
    ],
  },
  {
    id: "notifications", label: "Notifications", icon: "🔔",
    sections: [
      { id: "desktop", label: "Desktop", fields: [
        { key: "notifications_enabled", label: "Activer les notifications", type: "toggle" },
        { key: "notifications_scan_done", label: "Scan terminé", type: "toggle" },
        { key: "notifications_apply_done", label: "Apply terminé", type: "toggle" },
        { key: "notifications_undo_done", label: "Undo terminé", type: "toggle" },
        { key: "notifications_errors", label: "Erreurs critiques", type: "toggle" },
      ]},
      { id: "email", label: "Rapports email (SMTP)", fields: [
        { key: "email_enabled", label: "Activer", type: "toggle" },
        { key: "email_smtp_host", label: "SMTP host", type: "text", advanced: true },
        { key: "email_smtp_port", label: "SMTP port", type: "number", min: 1, max: 65535, advanced: true },
        { key: "email_smtp_user", label: "Utilisateur", type: "text", advanced: true },
        { key: "email_smtp_password", label: "Mot de passe", type: "api-key", advanced: true },
        { key: "email_smtp_tls", label: "STARTTLS", type: "toggle", advanced: true },
        { key: "email_to", label: "Destinataire", type: "text" },
        { key: "email_on_scan", label: "Envoyer après scan", type: "toggle", advanced: true },
        { key: "email_on_apply", label: "Envoyer après apply", type: "toggle", advanced: true },
      ]},
      { id: "plugins", label: "Plugins (hooks externes)", fields: [
        { key: "plugins_enabled", label: "Activer plugins", type: "toggle" },
        { key: "plugins_timeout_s", label: "Timeout (s)", type: "number", min: 5, max: 120, advanced: true },
      ]},
    ],
  },
  {
    id: "serveur", label: "Serveur distant", icon: "🌐",
    sections: [
      { id: "rest", label: "API REST", fields: [
        { key: "rest_api_enabled", label: "Activer l'API REST", type: "toggle" },
        { key: "rest_api_port", label: "Port", type: "number", min: 1024, max: 65535 },
        { key: "rest_api_token", label: "Clé d'accès (Bearer)", type: "api-key-rest" },
        { key: "__restart_api__", label: "", type: "action", action: "restart_api", buttonLabel: "🔄 Redémarrer le service API" },
        { key: "__qr_dashboard__", label: "QR code dashboard", type: "qr-dashboard" },
      ]},
      { id: "https", label: "HTTPS (optionnel)", fields: [
        { key: "rest_api_https_enabled", label: "Activer HTTPS", type: "toggle", advanced: true },
        { key: "rest_api_cert_path", label: "Chemin certificat", type: "text", advanced: true },
        { key: "rest_api_key_path", label: "Chemin clé privée", type: "text", advanced: true },
      ]},
    ],
  },
  {
    id: "apparence", label: "Apparence", icon: "🎨",
    sections: [
      { id: "theme", label: "Thème", fields: [
        { key: "theme", label: "Thème de l'interface", type: "select", options: [
          {v:"studio",l:"Studio"},{v:"cinema",l:"Cinéma"},{v:"luxe",l:"Luxe"},{v:"neon",l:"Neon"},
        ], livePreview: "theme" },
        { key: "animation_level", label: "Niveau d'animation", type: "select", options: [
          {v:"subtle",l:"Subtil"},{v:"moderate",l:"Modéré"},{v:"intense",l:"Intense"},
        ], livePreview: "animation" },
      ]},
      { id: "effects", label: "Effets visuels", fields: [
        { key: "effect_speed", label: "Vitesse animations (%)", type: "range", min: 0, max: 100, default: 50, advanced: true, livePreview: "effect_speed" },
        { key: "glow_intensity", label: "Intensité glow (%)", type: "range", min: 0, max: 100, default: 30, advanced: true, livePreview: "glow_intensity" },
        { key: "light_intensity", label: "Intensité lumière (%)", type: "range", min: 0, max: 100, default: 20, advanced: true, livePreview: "light_intensity" },
      ]},
    ],
  },
  {
    id: "profils-qualite", label: "Profils Qualité", icon: "⚡",
    sections: [
      { id: "profils", label: "Profils Qualité (Score V2)", fields: [
        { key: "__profils_qualite__", label: "", type: "profils-qualite" },
      ]},
    ],
  },
  {
    id: "avance", label: "Avancé", icon: "⚙️",
    sections: [
      { id: "parallelism", label: "Parallélisme", fields: [
        { key: "perceptual_parallelism_mode", label: "Mode parallélisme", type: "select", options: [
          {v:"auto",l:"Auto"},{v:"max",l:"Max"},{v:"safe",l:"Sécurisé"},{v:"serial",l:"Séquentiel"},
        ]},
      ]},
      { id: "logs", label: "Logs", fields: [
        { key: "log_level", label: "Niveau de verbosité", type: "select", options: [
          {v:"DEBUG",l:"DEBUG"},{v:"INFO",l:"INFO"},{v:"WARNING",l:"WARNING"},{v:"ERROR",l:"ERROR"},
        ], advanced: true },
      ]},
      { id: "onboarding", label: "Onboarding", fields: [
        { key: "onboarding_completed", label: "Wizard premier lancement terminé", type: "toggle" },
      ]},
      { id: "updates", label: "Mises à jour", fields: [
        { key: "update_check_enabled", label: "Vérifier automatiquement les mises à jour", type: "toggle" },
        { key: "update_github_repo", label: "Dépôt GitHub (owner/repo)", type: "text", placeholder: "user/cinesort",
          hint: "Vide = check désactivé", advanced: true },
      ]},
      { id: "retention", label: "Rétention historique", fields: [
        { key: "history_retention_days", label: "Conserver l'historique (jours)", type: "number", min: 7, max: 365, default: 90,
          hint: "Au-delà, les runs sont purgés automatiquement.", advanced: true },
      ]},
    ],
  },
];

/* =============================================================
 * 2) ETAT LOCAL
 * ============================================================= */

const STORAGE_KEY_LAST_CATEGORY = "cinesort.parametres.last_category";

const _state = {
  containerRef: null,
  settings: {},
  activeCategory: "sources",
  searchQuery: "",
  saveTimer: null,
  savedAt: null,
  saveError: null,
  // Profils qualite
  profilesList: [],
  activeProfileId: "",
  profileDraft: null,  // { id, label, tiers: {...}, weights: {...} }
};

const _DEFAULT_TIERS = { platinum: 85, gold: 68, silver: 54, bronze: 30 };
const _DEFAULT_WEIGHTS = {
  resolution: 0.25,
  bitrate: 0.20,
  codec: 0.15,
  audio_bitrate: 0.20,
  audio_channels: 0.10,
  subtitles_fr: 0.10,
};
const _WEIGHT_LABELS = {
  resolution: "Résolution",
  bitrate: "Bitrate vidéo",
  codec: "Codec",
  audio_bitrate: "Bitrate audio",
  audio_channels: "Canaux audio",
  subtitles_fr: "Sous-titres FR",
};
/* Bloc OMDb (spec 03-settings-omdb) — état local, alimenté depuis settings backend. */
let _omdbDraft = { enabled: false, api_key: "", min_confidence: 90 };
let _omdbTesting = false;
let _omdbSaving = false;

/* --- localStorage helpers --------------------------------------------- */

/* =============================================================
 * 3) HELPERS
 * ============================================================= */

function _esc(s) { return escapeHtml(String(s ?? "")); }

function _readString(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; }
  catch (_e) { return fallback; }
}

function _writeString(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (_e) { /* noop */ }
}

function _highlightLabel(label, query) {
  if (!query) return _esc(label);
  const q = String(query).toLowerCase().trim();
  if (!q) return _esc(label);
  const idx = String(label).toLowerCase().indexOf(q);
  if (idx < 0) return _esc(label);
  const before = label.slice(0, idx);
  const match = label.slice(idx, idx + q.length);
  const after = label.slice(idx + q.length);
  return `${_esc(before)}<mark class="parametres-search-highlight">${_esc(match)}</mark>${_esc(after)}`;
}

function _findFieldByKey(key) {
  for (const g of PARAMETRES_GROUPS) {
    for (const s of g.sections || []) {
      const f = (s.fields || []).find((x) => x.key === key);
      if (f) return f;
    }
  }
  return null;
}

function _searchMatches(query, text) {
  if (!query) return true;
  const q = String(query).toLowerCase().trim();
  if (!q) return true;
  return String(text || "").toLowerCase().includes(q);
}

function _groupMatches(query, group) {
  if (!query) return true;
  if (_searchMatches(query, group.label)) return true;
  for (const section of group.sections || []) {
    if (_searchMatches(query, section.label)) return true;
    for (const field of section.fields || []) {
      if (_searchMatches(query, field.label)) return true;
      if (_searchMatches(query, field.hint)) return true;
      if (_searchMatches(query, field.key)) return true;
    }
  }
  return false;
}

function _sectionMatches(query, section) {
  if (!query) return true;
  if (_searchMatches(query, section.label)) return true;
  for (const field of section.fields || []) {
    if (_searchMatches(query, field.label)) return true;
    if (_searchMatches(query, field.hint)) return true;
    if (_searchMatches(query, field.key)) return true;
  }
  return false;
}

function _fieldMatches(query, field) {
  if (!query) return true;
  return _searchMatches(query, field.label) || _searchMatches(query, field.hint) || _searchMatches(query, field.key);
}

/* =============================================================
 * 4) RENDERERS — FIELDS
 * ============================================================= */

function _renderField(field, value, query) {
  const id = `prm_${_esc(field.key)}`;
  const advAttr = field.advanced ? ' data-advanced="true"' : "";
  const reqMark = field.required ? ' <span class="parametres-field-required" aria-hidden="true">*</span>' : "";
  const reqAttr = field.required ? ' aria-required="true"' : "";
  const labelHtml = _highlightLabel(field.label || field.key, query) + reqMark;
  const livePreview = field.livePreview ? ` data-live-preview="${_esc(field.livePreview)}"` : "";
  const common = `id="${id}" data-field-key="${_esc(field.key)}"${reqAttr}${livePreview}`;
  const hintHtml = field.hint ? `<span class="parametres-field-hint">${_esc(field.hint)}</span>` : "";

  switch (field.type) {
    case "toggle":
      return `<label class="parametres-field parametres-field--toggle"${advAttr}>
        <input type="checkbox" class="parametres-checkbox" ${common} ${value ? "checked" : ""}>
        <span class="parametres-field-label">${labelHtml}</span>
        ${hintHtml}
      </label>`;

    case "number":
      return `<div class="parametres-field"${advAttr}>
        <label class="parametres-field-label" for="${id}">${labelHtml}</label>
        <input type="number" class="parametres-input parametres-input--sm" ${common}
               min="${_esc(field.min ?? 0)}" max="${_esc(field.max ?? 999999)}"
               value="${_esc(value != null ? value : (field.default ?? ""))}">
        ${hintHtml}
      </div>`;

    case "text":
      return `<div class="parametres-field"${advAttr}>
        <label class="parametres-field-label" for="${id}">${labelHtml}</label>
        <input type="text" class="parametres-input" ${common}
               placeholder="${_esc(field.placeholder || "")}"
               value="${_esc(value || "")}">
        ${hintHtml}
      </div>`;

    case "select":
      return `<div class="parametres-field"${advAttr}>
        <label class="parametres-field-label" for="${id}">${labelHtml}</label>
        <select class="parametres-select" ${common}>
          ${(field.options || []).map((o) =>
            `<option value="${_esc(o.v)}" ${String(o.v) === String(value) ? "selected" : ""}>${_esc(o.l)}</option>`,
          ).join("")}
        </select>
        ${hintHtml}
      </div>`;

    case "range": {
      const v = (value != null && value !== "") ? value : (field.default ?? 50);
      return `<div class="parametres-field"${advAttr}>
        <label class="parametres-field-label" for="${id}">
          ${labelHtml}
          <span class="parametres-range-value" data-range-value-for="${_esc(field.key)}">${_esc(v)}</span>
        </label>
        <input type="range" class="parametres-input parametres-input--range" ${common}
               min="${_esc(field.min ?? 0)}" max="${_esc(field.max ?? 100)}" value="${_esc(v)}">
        ${hintHtml}
      </div>`;
    }

    case "multi-path": {
      const arr = Array.isArray(value) ? value : (typeof value === "string" ? value.split(/[\n;]+/) : []);
      return `<div class="parametres-field"${advAttr}>
        <label class="parametres-field-label" for="${id}">${labelHtml}</label>
        <textarea class="parametres-textarea" ${common} rows="4">${_esc(arr.join("\n"))}</textarea>
        ${hintHtml}
      </div>`;
    }

    case "api-key": {
      const testBtn = field.testMethod
        ? `<button type="button" class="v5-btn v5-btn--sm" data-test-method="${_esc(field.testMethod)}" data-test-field="${_esc(field.key)}">Tester</button>`
        : "";
      return `<div class="parametres-field"${advAttr}>
        <label class="parametres-field-label" for="${id}">${labelHtml}</label>
        <div class="parametres-api-key-wrap">
          <input type="password" class="parametres-input" ${common} value="${_esc(value || "")}" autocomplete="off">
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-api-key-toggle="${id}" title="Afficher / masquer">👁</button>
          ${testBtn}
          <span class="parametres-test-result" data-test-result-for="${_esc(field.key)}"></span>
        </div>
        ${hintHtml}
      </div>`;
    }

    case "api-key-rest":
      return `<div class="parametres-field"${advAttr}>
        <label class="parametres-field-label" for="${id}">${labelHtml}</label>
        <div class="parametres-api-key-wrap">
          <input type="password" class="parametres-input" ${common} value="${_esc(value || "")}" autocomplete="off">
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-api-key-toggle="${id}" title="Afficher / masquer">👁</button>
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-rest-token-copy title="Copier">📋</button>
          <button type="button" class="v5-btn v5-btn--sm" data-rest-token-regen title="Régénérer">🔄</button>
          <span class="parametres-test-result" data-rest-token-msg></span>
        </div>
        ${hintHtml}
      </div>`;

    case "action":
      return `<div class="parametres-field"${advAttr}>
        <button type="button" class="v5-btn" data-action="${_esc(field.action)}">${_esc(field.buttonLabel || "Action")}</button>
        <span class="parametres-test-result" data-action-result-for="${_esc(field.action)}"></span>
      </div>`;

    case "qr-dashboard":
      return `<div class="parametres-field parametres-field--qr"${advAttr}>
        <label class="parametres-field-label">${labelHtml}</label>
        <div data-qr-dashboard class="parametres-qr-host">
          <span class="parametres-muted">Chargement du QR code…</span>
        </div>
      </div>`;

    case "profils-qualite":
      return _renderProfilsQualite();

    default:
      return `<div class="parametres-field">[type ${_esc(field.type)} non supporté pour « ${_esc(field.label)} »]</div>`;
  }
}

function _isFieldConfigured(field, settings) {
  if (field.key && field.key.startsWith("__")) return false;
  const val = settings[field.key];
  if (val === undefined || val === null || val === "") return false;
  if (field.type === "toggle") return Boolean(val);
  if (field.type === "number") return Number(val) !== 0;
  return true;
}

function _sectionStatus(section, settings) {
  const fields = (section.fields || []).filter((f) => !f.key.startsWith("__"));
  if (fields.length === 0) return "none";
  const configured = fields.filter((f) => _isFieldConfigured(f, settings)).length;
  if (configured === 0) return "none";
  if (configured === fields.length) return "full";
  return "partial";
}

/* =============================================================
 * 5) RENDERERS — PROFILS QUALITE (catégorie 2.9)
 * ============================================================= */

function _renderProfilsQualite() {
  const profiles = _state.profilesList || [];
  const activeId = _state.activeProfileId || "";
  const draft = _state.profileDraft || { tiers: { ..._DEFAULT_TIERS }, weights: { ..._DEFAULT_WEIGHTS } };
  const tiers = draft.tiers || { ..._DEFAULT_TIERS };
  const weights = draft.weights || { ..._DEFAULT_WEIGHTS };

  const totalWeight = Object.values(weights).reduce((s, v) => s + (Number(v) || 0), 0);
  const totalDisplay = totalWeight.toFixed(2);
  const inRange = totalWeight >= 0.95 && totalWeight <= 1.05;
  const totalCls = inRange ? "parametres-weight-total--ok" : "parametres-weight-total--warning";
  const totalIcon = inRange ? "✓" : "⚠";

  const profileOptions = profiles.map((p) => {
    const sel = String(p.id) === String(activeId) ? "selected" : "";
    const custom = p.is_custom ? " (custom)" : "";
    return `<option value="${_esc(p.id)}" ${sel}>${_esc(p.label || p.name || p.id)}${custom}</option>`;
  }).join("");

  const tierRows = ["platinum", "gold", "silver", "bronze"].map((name) => {
    const labels = { platinum: "⬤ Platinum", gold: "⬤ Gold", silver: "⬤ Silver", bronze: "⬤ Bronze" };
    return `<div class="parametres-tier-row">
      <label for="tier-${name}">
        <span class="parametres-tier-badge parametres-tier-badge--${name}">${labels[name]}</span>
        score ≥
      </label>
      <input type="number" id="tier-${name}" min="0" max="100"
             value="${_esc(tiers[name] ?? _DEFAULT_TIERS[name])}"
             data-tier-input="${name}">
    </div>`;
  }).join("");

  const weightRows = Object.keys(_DEFAULT_WEIGHTS).map((key) => {
    const v = Number(weights[key] ?? _DEFAULT_WEIGHTS[key]);
    const pct = Math.round(v * 100);
    return `<div class="parametres-weight-row">
      <label for="weight-${key}">${_esc(_WEIGHT_LABELS[key] || key)}</label>
      <input type="range" id="weight-${key}" min="0" max="100" step="1" value="${pct}"
             data-weight-input="${key}" class="parametres-input parametres-input--range">
      <span class="parametres-weight-value" data-weight-value="${key}">×${v.toFixed(2)}</span>
    </div>`;
  }).join("");
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

  return `<div class="parametres-field parametres-profils-qualite">
    <div class="parametres-profils-selector">
      <label for="parametres-profile-active">Profil actif</label>
      <select id="parametres-profile-active" data-parametres-profile-select class="parametres-select">
        ${profileOptions || '<option value="">(aucun profil chargé)</option>'}
      </select>
    </div>

    <h4 class="parametres-subheading">Seuils de tier</h4>
    <p class="parametres-section-intro">
      Un film est classé selon son score global (0-100). L'ordre logique est
      <strong>Platinum &gt; Gold &gt; Silver &gt; Bronze &gt; Reject</strong>
      (en-dessous du seuil Bronze = Reject).
    </p>
    <form class="parametres-profils-form" data-parametres-profils-form>
      ${tierRows}
    </form>

    <h4 class="parametres-subheading">Poids des composantes</h4>
    <p class="parametres-section-intro">
      La somme des poids doit faire ~1.00 (tolérance ± 5 %).
    </p>
    <div class="parametres-weight-rows">
      ${weightRows}
      <div class="parametres-weight-total ${totalCls}" data-weight-total>
        Total = ${totalDisplay} ${totalIcon}
      </div>
    </div>

    <div class="parametres-profils-actions">
      <button type="button" class="v5-btn v5-btn--primary" data-parametres-profils-action="save">
        💾 Sauvegarder comme nouveau profil
      </button>
      <button type="button" class="v5-btn" data-parametres-profils-action="recompute">
        ↻ Re-calculer scores avec ce profil
      </button>
      <button type="button" class="v5-btn v5-btn--ghost" data-parametres-profils-action="reset">
        ↺ Restaurer les défauts
      </button>
    </div>
    <p class="parametres-profils-message" data-parametres-profils-message></p>
  </div>`;
}

/* =============================================================
 * 6) RENDERERS — LAYOUT
 * ============================================================= */

function _renderHeader() {
  const expertChecked = _state.settings.expert_mode ? "checked" : "";
  return `<header class="parametres-header">
    <h1 class="parametres-title">Paramètres</h1>
    <div class="parametres-controls">
      <label class="parametres-expert-toggle">
        <input type="checkbox" data-parametres-expert ${expertChecked}>
        <span>Mode expert</span>
      </label>
      <div class="parametres-search">
        <input type="search" class="parametres-input parametres-search-input"
               placeholder="🔍 Rechercher (Ctrl+K)…"
               value="${_esc(_state.searchQuery)}"
               data-parametres-search aria-label="Rechercher un paramètre">
      </div>
      <div class="parametres-saved-indicator" data-parametres-saved-indicator></div>
    </div>
  </header>`;
}

function _renderSubSidebar() {
  const items = PARAMETRES_GROUPS.map((g) => {
    const visible = _groupMatches(_state.searchQuery, g);
    if (!visible) return "";
    const active = g.id === _state.activeCategory;
    let total = 0, configured = 0;
    g.sections.forEach((s) => s.fields.forEach((f) => {
      if (f.key.startsWith("__")) return;
      total += 1;
      if (_isFieldConfigured(f, _state.settings)) configured += 1;
    }));
    const status = configured === 0 ? "none" : configured === total ? "full" : "partial";
    const dot = status !== "none"
      ? `<span class="parametres-sub-dot parametres-sub-dot--${status}" title="${configured}/${total} configurés"></span>`
      : "";
    return `<button type="button" class="parametres-sub-item ${active ? "is-active" : ""}"
            data-category="${_esc(g.id)}"
            ${active ? 'aria-current="page"' : ''}>
      <span class="parametres-sub-icon" aria-hidden="true">${g.icon}</span>
      <span class="parametres-sub-label">${_highlightLabel(g.label, _state.searchQuery)}</span>
      ${dot}
    </button>`;
  }).join("");

  return `<aside class="parametres-sub-sidebar" role="navigation" aria-label="Catégories de paramètres">
    <nav class="parametres-sub-nav">${items || '<div class="parametres-muted">Aucune catégorie ne correspond à la recherche.</div>'}</nav>
    <div class="parametres-sub-footer">
      <button type="button" class="v5-btn v5-btn--ghost v5-btn--danger parametres-reset-btn"
              data-parametres-action="reset">↺ Réinitialiser…</button>
    </div>
  </aside>`;
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
  const group = PARAMETRES_GROUPS.find((c) => c.id === categoryId) || PARAMETRES_GROUPS[0];
  const visibleSections = (group.sections || []).filter((s) => _sectionMatches(_state.searchQuery, s));

  if (visibleSections.length === 0) {
    return `<section class="parametres-panel">
      <h2 class="parametres-panel-title">
        <span class="parametres-panel-icon" aria-hidden="true">${group.icon}</span>
        ${_esc(group.label)}
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
      <div class="parametres-empty">Aucun paramètre ne correspond à votre recherche dans cette catégorie.</div>
    </section>`;
  }

  const sectionsHtml = visibleSections.map((section) => {
    const status = _sectionStatus(section, _state.settings);
    const badge = status === "full"
      ? '<span class="parametres-section-badge parametres-section-badge--full">Configuré</span>'
      : status === "partial"
        ? '<span class="parametres-section-badge parametres-section-badge--partial">Partiel</span>'
        : "";
    const fields = (section.fields || [])
      .filter((f) => _fieldMatches(_state.searchQuery, f))
      .map((f) => _renderField(f, _state.settings[f.key], _state.searchQuery))
      .join("");
    return `<section class="parametres-section" data-section-id="${_esc(section.id)}">
      <header class="parametres-section-header">
        <h3 class="parametres-section-title">${_highlightLabel(section.label, _state.searchQuery)}</h3>
        ${badge}
      </header>
      <div class="parametres-section-body">${fields}</div>
    </section>`;
  }).join("");

  return `<section class="parametres-panel" aria-labelledby="parametres-panel-title">
    <h2 id="parametres-panel-title" class="parametres-panel-title">
      <span class="parametres-panel-icon" aria-hidden="true">${group.icon}</span>
      ${_esc(group.label)}
    </h2>
    <div class="parametres-panel-body">${sectionsHtml}</div>
  </section>`;
}

function _renderParametres() {
  return `<section class="parametres-view">
    ${_renderHeader()}
    <div class="parametres-grid">
      <div data-parametres-sidebar-host>${_renderSubSidebar()}</div>
      <main class="parametres-main" id="parametres-main-content">
        ${_renderCategoryPanel(_state.activeCategory)}
      </main>
    </div>
  </section>`;
}

function _renderError(message) {
  return `<section class="parametres-view parametres-view--error" role="alert">
    <h2>Les paramètres n'ont pas pu se charger.</h2>
    <p>${_esc(message || "Erreur inconnue")}</p>
    <button type="button" class="v5-btn v5-btn--primary" data-parametres-retry>Réessayer</button>
  </section>`;
}

/* =============================================================
 * 7) PROFILS QUALITE — LOAD / SAVE
 * ============================================================= */

async function _loadProfiles() {
  try {
    const res = await apiPost("settings/get_profiles", {});
    if (res && res.data && (res.data.ok || Array.isArray(res.data.profiles))) {
      _state.profilesList = res.data.profiles || [];
      _state.activeProfileId = res.data.active_profile_id || "";
      // Initialise le draft a partir du profil actif (sinon defauts)
      const active = _state.profilesList.find((p) => String(p.id) === String(_state.activeProfileId));
      if (active) {
        _state.profileDraft = {
          id: active.id,
          label: active.label,
          tiers: { ..._DEFAULT_TIERS, ...(active.tiers || {}) },
          weights: { ..._DEFAULT_WEIGHTS, ...(active.weights || {}) },
        };
      } else {
        _state.profileDraft = { id: "", label: "", tiers: { ..._DEFAULT_TIERS }, weights: { ..._DEFAULT_WEIGHTS } };
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

  // Reset action — P0 #233 : utilise dangerConfirmModal (sans redirection legacy).
  // L'endpoint settings/reset_all_user_data exige confirmation: "RESET" cote serveur,
  // donc on ne l'appelle PAS automatiquement depuis cette modale ; on redirige vers
  // /settings pour la double saisie textuelle. Mais on demande deja une confirmation
  // explicite ici avec compteur anti-clic-reflexe.
  const resetBtn = container.querySelector("[data-parametres-action='reset']");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      dangerConfirmModal({
        title: "Réinitialiser tous les paramètres utilisateur ?",
        items: ["Préférences globales", "Profils qualité", "Historique runs", "Cache TMDb"],
        consequence:
          "Cette action est irréversible (un backup .json est cependant créé automatiquement). " +
          "Vous serez redirigé vers la page Settings pour confirmer en tapant « RESET ».",
        countdownSeconds: 3,
        confirmLabel: "↺ Continuer vers Settings",
        onConfirm: () => {
          navigateTo("/settings");
        },
      });
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
    // Fallback silencieux : draft par defaut
    _state.profilesList = [];
    _state.profileDraft = { id: "", label: "", tiers: { ..._DEFAULT_TIERS }, weights: { ..._DEFAULT_WEIGHTS } };
  }
}

async function _setActiveProfile(profileId) {
  if (!profileId) return;
  try {
    const res = await apiPost("settings/set_active_profile", { profile_id: profileId });
    if (res && res.data && res.data.ok) {
      _state.activeProfileId = profileId;
      const active = _state.profilesList.find((p) => String(p.id) === String(profileId));
      if (active) {
        _state.profileDraft = {
          id: active.id, label: active.label,
          tiers: { ..._DEFAULT_TIERS, ...(active.tiers || {}) },
          weights: { ..._DEFAULT_WEIGHTS, ...(active.weights || {}) },
        };
      }
      _showProfilMessage("✓ Profil activé.", "ok");
      _rerenderActiveCategory();
    } else {
      _showProfilMessage(`Erreur : ${res?.data?.message || "activation impossible"}`, "error");
    }
  } catch (err) {
    _showProfilMessage(`Erreur : ${err?.message || err}`, "error");
  }
}

async function _saveProfileAsNew() {
  const draft = _state.profileDraft;
  if (!draft) return;
  // Validation tiers strictement décroissants
  const t = draft.tiers;
  if (!(t.platinum > t.gold && t.gold > t.silver && t.silver > t.bronze)) {
    _showProfilMessage("Erreur : les seuils doivent être strictement décroissants (Platinum > Gold > Silver > Bronze).", "error");
    return;
  }
  // Validation somme poids (±5%)
  const total = Object.values(draft.weights).reduce((s, v) => s + (Number(v) || 0), 0);
  if (total < 0.95 || total > 1.05) {
    _showProfilMessage(`Erreur : somme des poids = ${total.toFixed(2)}, doit être ~1.00 (± 5 %).`, "error");
    return;
  }
  const name = window.prompt("Nom du nouveau profil :", "MonProfil_v1");
  if (!name) return;
  const profile = {
    id: String(name).trim(),
    label: String(name).trim(),
    description: "Profil personnalisé",
    version: 1,
    tiers: draft.tiers,
    weights: draft.weights,
  };
  try {
    const res = await apiPost("settings/save_profile", { profile });
    if (res && res.data && res.data.ok) {
      _showProfilMessage(`✓ Profil "${name}" sauvegardé.`, "ok");
      await _loadProfiles();
      _rerenderActiveCategory();
    } else {
      const errs = res?.data?.errors ? ` (${res.data.errors.join(" ; ")})` : "";
      _showProfilMessage(`Erreur : ${res?.data?.message || "sauvegarde refusée"}${errs}`, "error");
    }
  } catch (err) {
    _showProfilMessage(`Erreur : ${err?.message || err}`, "error");
  }
}

async function _recomputeScores() {
  dangerConfirmModal({
    title: "Re-calculer les scores avec ce profil ?",
    items: ["Tous les films classés"],
    consequence: "Cette opération va re-scorer l'ensemble des films de votre bibliothèque (~5-10 min). Les scores existants seront écrasés.",
    countdownSeconds: 0,
    confirmLabel: "↻ Lancer le re-calcul",
    onConfirm: async () => {
      _showProfilMessage("Re-calcul en cours… (voir vue Qualité)", "info");
      try {
        const res = await apiPost("quality/recompute_all_scores", {});
        if (res && res.data && res.data.ok) {
          _showProfilMessage(`✓ Re-calcul terminé : ${res.data.updated_count || 0} films re-scorés.`, "ok");
        } else {
          _showProfilMessage(`Erreur : ${res?.data?.message || "re-calcul impossible"}`, "error");
        }
      } catch (err) {
        _showProfilMessage(`Erreur : ${err?.message || err}`, "error");
      }
    },
  });
}

function _showProfilMessage(msg, level) {
  const el = _state.containerRef?.querySelector("[data-parametres-profils-message]");
  if (!el) return;
  el.textContent = msg;
  el.className = "parametres-profils-message";
  if (level === "error") el.classList.add("parametres-profils-message--error");
  else if (level === "ok") el.classList.add("parametres-profils-message--ok");
}

/* =============================================================
 * 8) QR DASHBOARD
 * ============================================================= */

async function _loadQrDashboard(container) {
  const host = container.querySelector("[data-qr-dashboard]");
  if (!host) return;
  const token = String(_state.settings.rest_api_token || "");
  if (!_state.settings.rest_api_enabled) {
    host.innerHTML = `<span class="parametres-muted">API REST désactivée — activez-la pour générer un QR code.</span>`;
    return;
  }
  if (!token) {
    host.innerHTML = `<span class="parametres-warning">Aucune clé d'accès configurée.</span>`;
    return;
  }
  let qrSvg = "", url = "";
  try {
    const r = await apiPost("settings/get_dashboard_qr");
    if (r?.data?.ok) { qrSvg = r.data.svg || ""; url = r.data.url || ""; }
  } catch { /* noop */ }
  if (!url) {
    try {
      const si = await apiPost("settings/get_server_info");
      if (si?.data?.ok) url = si.data.dashboard_url || "";
    } catch { /* noop */ }
  }
  host.innerHTML = `
    ${qrSvg ? `<div class="parametres-qr-svg">${qrSvg}</div>` : ""}
    <div class="parametres-qr-info">
      <div class="parametres-muted parametres-qr-label">URL d'accès LAN</div>
      <code class="parametres-qr-url">${_esc(url || "(serveur arrêté)")}</code>
      <button type="button" class="v5-btn v5-btn--sm" data-qr-copy-url="${_esc(url)}">Copier l'URL</button>
      <p class="parametres-muted parametres-qr-hint">Scannez le QR depuis votre téléphone pour accéder au dashboard sur votre réseau local.</p>
    </div>
  `;
  const copyBtn = host.querySelector("[data-qr-copy-url]");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(copyBtn.dataset.qrCopyUrl);
        const original = copyBtn.textContent;
        copyBtn.textContent = "✓ Copié";
        setTimeout(() => { copyBtn.textContent = original; }, 1800);
      } catch { /* noop */ }
    });
  }
}

/* =============================================================
 * 9) SAVE / LOAD
 * ============================================================= */

function _readFieldValue(field, fieldEl) {
  if (!fieldEl) return undefined;
  switch (field.type) {
    case "toggle": return !!fieldEl.checked;
    case "number": case "range": return Number(fieldEl.value) || 0;
    case "multi-path":
      return fieldEl.value.split(/[\n;]+/).map((s) => s.trim()).filter(Boolean);
    default: return fieldEl.value;
  }
}

function _scheduleSave() {
  if (_state.saveTimer) clearTimeout(_state.saveTimer);
  _state.saveTimer = setTimeout(async () => {
    try {
      const res = await apiPost("settings/save_settings", { settings: _state.settings });
      if (res && res.data && (res.data.ok || res.data === true || !res.data.message)) {
        _state.savedAt = new Date();
        _state.saveError = null;
        invalidateSettingsCache();
        _updateSavedIndicator();
      } else {
        _state.saveError = res?.data?.message || "Erreur inconnue";
        _updateSavedIndicator();
      }
    } catch (err) {
      _state.saveError = err?.message || "Erreur réseau";
      _updateSavedIndicator();
    }
  }, 500);
}

function _updateSavedIndicator() {
  const el = _state.containerRef?.querySelector("[data-parametres-saved-indicator]");
  if (!el) return;
  if (_state.saveError) {
    el.innerHTML = `<span class="parametres-saved-indicator--error">⚠ ${_esc(_state.saveError)}</span>`;
    return;
  }
  if (_state.savedAt) {
    el.innerHTML = `<span class="parametres-saved-indicator--ok">✓ Sauvegardé</span>`;
    setTimeout(() => {
      if (el.querySelector(".parametres-saved-indicator--ok")) el.innerHTML = "";
    }, 2500);
  } else {
    el.innerHTML = "";
  }
}

async function _loadSettings() {
  const res = await apiPost("settings/get_settings", {});
  if (res && res.data && typeof res.data === "object") {
    _state.settings = res.data.data || res.data || {};
  }
}

/* =============================================================
 * 10) LIVE PREVIEW (theme + sliders apparence)
 * ============================================================= */

function _applyLivePreview(kind, value) {
  if (!kind) return;
  if (kind === "theme") {
    document.documentElement.setAttribute("data-theme", String(value));
    document.body.setAttribute("data-theme", String(value));
    return;
  }
  if (kind === "animation") {
    document.body.dataset.animation = String(value);
    return;
  }
  const root = document.documentElement;
  const map = (v, lo, hi) => lo + ((Number(v) || 0) / 100) * (hi - lo);
  if (kind === "effect_speed")    root.style.setProperty("--animation-speed", String(map(value, 0.3, 3)));
  if (kind === "glow_intensity")  root.style.setProperty("--glow-intensity", String(map(value, 0, 0.5)));
  if (kind === "light_intensity") {
    root.style.setProperty("--light-intensity", String(map(value, 0, 0.3)));
    root.style.setProperty("--effect-opacity", String(map(value, 0, 0.08)));
  }
}

/* =============================================================
 * 11) RESET MODAL (10 scopes + CONFIRMER + countdown)
 * ============================================================= */

const _RESET_SCOPES = [
  { id: "all", label: "Tout réinitialiser (toutes catégories)" },
  { id: "sources", label: "Sources seulement" },
  { id: "analyse", label: "Analyse seulement" },
  { id: "nommage", label: "Nommage seulement" },
  { id: "bibliotheque", label: "Bibliothèque seulement" },
  { id: "integrations", label: "Intégrations seulement" },
  { id: "notifications", label: "Notifications seulement" },
  { id: "serveur", label: "Serveur distant seulement" },
  { id: "apparence", label: "Apparence seulement" },
  { id: "profils-qualite", label: "Profils Qualité seulement" },
  { id: "avance", label: "Avancé seulement" },
  { id: "__database__", label: "⚠ Base de données complète (films, runs, scores)" },
];

function _openResetModal() {
  const existing = document.getElementById("parametresResetModal");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id = "parametresResetModal";
  overlay.className = "parametres-reset-modal-overlay";
  overlay.setAttribute("role", "alertdialog");
  overlay.setAttribute("aria-modal", "true");

  const scopesHtml = _RESET_SCOPES.map((s, i) => `
    <label class="parametres-reset-scope">
      <input type="radio" name="parametres-reset-scope" value="${_esc(s.id)}" ${i === 0 ? "checked" : ""}>
      <span>${_esc(s.label)}</span>
    </label>
  `).join("");

  overlay.innerHTML = `
    <div class="parametres-reset-modal card" role="document">
      <h3 class="parametres-reset-modal-title">Réinitialiser les paramètres ?</h3>
      <p class="parametres-reset-modal-intro">
        Choisissez la portée de la réinitialisation. Cette opération restaurera les valeurs par défaut.
      </p>
      <div class="parametres-reset-modal-scopes" data-parametres-reset-scopes>
        ${scopesHtml}
      </div>
      <div class="parametres-reset-modal-confirm">
        <label for="parametres-reset-confirm-input">
          Tapez <strong>CONFIRMER</strong> pour valider :
        </label>
        <input type="text" id="parametres-reset-confirm-input" class="parametres-input" data-parametres-reset-input autocomplete="off">
      </div>
      <p class="parametres-reset-modal-warning" data-parametres-reset-warning>
        Cette action est irréversible (un backup automatique est créé).
      </p>
      <div class="parametres-reset-modal-actions">
        <button type="button" class="v5-btn" data-parametres-reset-cancel>Annuler</button>
        <button type="button" class="v5-btn v5-btn--danger" data-parametres-reset-confirm disabled>
          ↺ Confirmer <span data-parametres-reset-countdown></span>
        </button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);
  overlay._previouslyFocused = document.activeElement;

  const input = overlay.querySelector("[data-parametres-reset-input]");
  const confirmBtn = overlay.querySelector("[data-parametres-reset-confirm]");
  const cancelBtn = overlay.querySelector("[data-parametres-reset-cancel]");
  const countdownEl = overlay.querySelector("[data-parametres-reset-countdown]");
  const warningEl = overlay.querySelector("[data-parametres-reset-warning]");

  let countdownTimer = null;
  let countdownRemaining = 0;
  let textOk = false;

  const updateConfirmState = () => {
    const enabled = textOk && countdownRemaining <= 0;
    confirmBtn.disabled = !enabled;
  };

  const startCountdown = (seconds) => {
    if (countdownTimer) clearInterval(countdownTimer);
    countdownRemaining = seconds;
    if (seconds > 0) {
      countdownEl.textContent = `(${seconds}s)`;
      countdownTimer = setInterval(() => {
        countdownRemaining -= 1;
        if (countdownRemaining <= 0) {
          clearInterval(countdownTimer);
          countdownTimer = null;
          countdownEl.textContent = "";
          updateConfirmState();
        } else {
          countdownEl.textContent = `(${countdownRemaining}s)`;
        }
      }, 1000);
    } else {
      countdownEl.textContent = "";
    }
    updateConfirmState();
  };

  const close = () => {
    if (countdownTimer) clearInterval(countdownTimer);
    if (overlay._escHandler) document.removeEventListener("keydown", overlay._escHandler);
    const prev = overlay._previouslyFocused;
    overlay.remove();
    if (prev && typeof prev.focus === "function") {
      try { prev.focus(); } catch (e) { /* noop */ }
    }
  };

  const getSelectedScope = () => {
    const checked = overlay.querySelector("input[name='parametres-reset-scope']:checked");
    return checked ? checked.value : "all";
  };

  // Démarre avec scope "all" -> countdown 3s
  startCountdown(3);

  // Changement de scope -> recalcule countdown + warning
  overlay.querySelectorAll("input[name='parametres-reset-scope']").forEach((radio) => {
    radio.addEventListener("change", () => {
      const scope = getSelectedScope();
      if (scope === "all" || scope === "__database__") {
        startCountdown(3);
        warningEl.textContent = scope === "__database__"
          ? "⚠ TRÈS DANGEREUX : cela supprime TOUS les films, runs, scores et analyses de la base. Action TOTALEMENT irréversible côté DB (backup auto cependant)."
          : "Cette action réinitialise TOUS les paramètres aux valeurs par défaut.";
      } else {
        startCountdown(0);
        warningEl.textContent = "Cette action est irréversible (un backup automatique des settings est créé).";
      }
    });
  });

  // Validation texte CONFIRMER
  input.addEventListener("input", () => {
    textOk = input.value.trim() === "CONFIRMER";
    updateConfirmState();
  });

  // Esc + backdrop
  overlay._escHandler = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", overlay._escHandler);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

  // Cancel
  cancelBtn.addEventListener("click", close);

  // Confirm
  confirmBtn.addEventListener("click", async () => {
    if (confirmBtn.disabled) return;
    confirmBtn.disabled = true;
    const scope = getSelectedScope();
    try {
      let res;
      if (scope === "__database__") {
        res = await apiPost("settings/reset_database", {});
      } else {
        res = await apiPost("settings/reset_settings", { scope });
      }
      close();
      if (res && res.data && res.data.ok) {
        _state.savedAt = new Date();
        _state.saveError = null;
        invalidateSettingsCache();
        // Recharge les settings
        await _loadSettings();
        await _loadProfiles();
        _refreshAll();
        const backupPath = res.data.backup_path || "";
        _state.containerRef?.querySelector("[data-parametres-saved-indicator]")?.setAttribute("data-flash", "ok");
        const msg = scope === "__database__"
          ? `Base de données réinitialisée. Backup créé : ${backupPath}`
          : `Paramètres réinitialisés (${scope === "all" ? "tout" : scope}).`;
        const ind = _state.containerRef?.querySelector("[data-parametres-saved-indicator]");
        if (ind) ind.innerHTML = `<span class="parametres-saved-indicator--ok">✓ ${_esc(msg)}</span>`;
      } else {
        const ind = _state.containerRef?.querySelector("[data-parametres-saved-indicator]");
        if (ind) ind.innerHTML = `<span class="parametres-saved-indicator--error">⚠ ${_esc(res?.data?.message || "Reset impossible")}</span>`;
      }
    } catch (err) {
      close();
      const ind = _state.containerRef?.querySelector("[data-parametres-saved-indicator]");
      if (ind) ind.innerHTML = `<span class="parametres-saved-indicator--error">⚠ ${_esc(err?.message || err)}</span>`;
    }
  });

  // Focus initial sur le champ texte
  setTimeout(() => { try { input.focus(); } catch (e) { /* noop */ } }, 50);
}

/* =============================================================
 * 12) EVENTS
 * ============================================================= */

function _onCategoryClick(catId) {
  if (!PARAMETRES_GROUPS.some((c) => c.id === catId)) return;
  _state.activeCategory = catId;
  _writeString(STORAGE_KEY_LAST_CATEGORY, catId);
  _rerenderActiveCategory();
  _rerenderSidebar();
}

function _bindHeader(container) {
  // Mode expert
  const expertInput = container.querySelector("[data-parametres-expert]");
  if (expertInput) {
    expertInput.addEventListener("change", (ev) => {
      const v = !!ev.target.checked;
      _state.settings.expert_mode = v;
      container.classList.toggle("is-expert", v);
      _scheduleSave();
    });
  }

  // Search
  const searchInput = container.querySelector("[data-parametres-search]");
  if (searchInput) {
    let timer = null;
    searchInput.addEventListener("input", (ev) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        _state.searchQuery = String(ev.target.value || "").trim();
        // Auto-switch vers la première catégorie qui matche, si la catégorie active n'en contient pas
        if (_state.searchQuery) {
          const currentMatches = _groupMatches(_state.searchQuery, PARAMETRES_GROUPS.find((g) => g.id === _state.activeCategory));
          if (!currentMatches) {
            const firstMatch = PARAMETRES_GROUPS.find((g) => _groupMatches(_state.searchQuery, g));
            if (firstMatch) _state.activeCategory = firstMatch.id;
          }
        }
        _refreshAll();
        // Ré-focus le champ recherche (sinon perdu après re-render)
        const newSearch = _state.containerRef?.querySelector("[data-parametres-search]");
        if (newSearch) {
          newSearch.focus();
          newSearch.setSelectionRange(newSearch.value.length, newSearch.value.length);
        }
      }, 150);
    });
  }

  // Retry
  const retryBtn = container.querySelector("[data-parametres-retry]");
  if (retryBtn) retryBtn.addEventListener("click", () => initParametres(container));
}

function _bindSidebar(container) {
  container.querySelectorAll("[data-category]").forEach((btn) => {
    btn.addEventListener("click", () => _onCategoryClick(btn.dataset.category));
  });
  const resetBtn = container.querySelector("[data-parametres-action='reset']");
  if (resetBtn) resetBtn.addEventListener("click", _openResetModal);
}

function _bindFields(container) {
  // Field changes (input/change)
  container.querySelectorAll("[data-field-key]").forEach((fieldEl) => {
    const key = fieldEl.dataset.fieldKey;
    if (key.startsWith("__")) return;
    const field = _findFieldByKey(key);
    if (!field) return;
    const handler = () => {
      const v = _readFieldValue(field, fieldEl);
      _state.settings[key] = v;
      _applyLivePreview(field.livePreview, v);
      if (field.type === "range") {
        const label = container.querySelector(`[data-range-value-for="${key}"]`);
        if (label) label.textContent = String(v);
      }
      _scheduleSave();
    };
    if (field.type === "toggle" || field.type === "select") fieldEl.addEventListener("change", handler);
    else fieldEl.addEventListener("input", handler);
  });

  // API-key show/hide
  container.querySelectorAll("[data-api-key-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.apiKeyToggle;
      const input = container.querySelector("#" + id);
      if (input) input.type = input.type === "password" ? "text" : "password";
    });
  });

  // Test buttons
  container.querySelectorAll("[data-test-method]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const method = btn.dataset.testMethod;
      const fieldKey = btn.dataset.testField;
      const field = _findFieldByKey(fieldKey);
      const resultEl = container.querySelector(`[data-test-result-for="${fieldKey}"]`);
      if (resultEl) { resultEl.textContent = "Test…"; resultEl.className = "parametres-test-result parametres-test-result--info"; }
      btn.disabled = true;
      try {
        const params = {};
        const tp = field?.testParams || {};
        for (const [k, v] of Object.entries(tp)) {
          if (typeof v === "string" && v.startsWith("$")) {
            const ref = v.slice(1);
            params[k] = (ref === "value") ? _state.settings[fieldKey] : _state.settings[ref];
          } else params[k] = v;
        }
        const res = await apiPost(method, params);
        const ok = !!(res?.data?.ok);
        if (resultEl) {
          resultEl.textContent = ok ? "✓ Connexion réussie" : `✗ Échec : ${res?.data?.message || res?.data?.error || "inconnu"}`;
          resultEl.className = `parametres-test-result parametres-test-result--${ok ? "ok" : "error"}`;
        }
      } catch (err) {
        if (resultEl) {
          resultEl.textContent = `✗ Erreur réseau : ${err?.message || err}`;
          resultEl.className = "parametres-test-result parametres-test-result--error";
        }
      } finally {
        btn.disabled = false;
      }
    });
  });

  // REST token regen + copy
  const tokenInput = container.querySelector('[data-field-key="rest_api_token"]');
  const msgEl = container.querySelector("[data-rest-token-msg]");
  const copyBtn = container.querySelector("[data-rest-token-copy]");
  const regenBtn = container.querySelector("[data-rest-token-regen]");
  if (copyBtn && tokenInput) {
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(tokenInput.value);
        if (msgEl) { msgEl.textContent = "✓ Copié"; msgEl.className = "parametres-test-result parametres-test-result--ok"; setTimeout(() => { msgEl.textContent = ""; }, 1800); }
      } catch { if (msgEl) msgEl.textContent = "Échec copie"; }
    });
  }
  if (regenBtn && tokenInput) {
    regenBtn.addEventListener("click", () => {
      if (!window.confirm("Régénérer le token ? Les clients distants devront utiliser la nouvelle clé.")) return;
      const bytes = new Uint8Array(24);
      crypto.getRandomValues(bytes);
      const b64 = btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
      tokenInput.value = b64;
      tokenInput.type = "text";
      _state.settings.rest_api_token = b64;
      if (msgEl) { msgEl.textContent = "✓ Nouveau token"; msgEl.className = "parametres-test-result parametres-test-result--ok"; }
      _scheduleSave();
    });
  }

  // Action buttons (restart API)
  container.querySelectorAll('[data-action="restart_api"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const resultEl = container.querySelector('[data-action-result-for="restart_api"]');
      btn.disabled = true;
      if (resultEl) { resultEl.textContent = "Redémarrage…"; resultEl.className = "parametres-test-result parametres-test-result--info"; }
      try {
        const res = await apiPost("settings/restart_api_server", {});
        const ok = !!(res?.data?.ok);
        if (resultEl) {
          resultEl.textContent = ok ? "✓ Service redémarré" : `✗ Échec : ${res?.data?.message || "inconnu"}`;
          resultEl.className = `parametres-test-result parametres-test-result--${ok ? "ok" : "error"}`;
        }
        if (ok) setTimeout(() => _loadQrDashboard(container), 1000);
      } catch (err) {
        if (resultEl) { resultEl.textContent = `✗ Erreur : ${err?.message || err}`; resultEl.className = "parametres-test-result parametres-test-result--error"; }
      } finally {
        btn.disabled = false;
      }
    });
  });

  // Profils Qualité
  _bindProfilsQualite(container);

  // QR dashboard auto-load
  if (container.querySelector("[data-qr-dashboard]")) {
    _loadQrDashboard(container);
  }
}

function _bindProfilsQualite(container) {
  // Selector du profil actif
  const selector = container.querySelector("[data-parametres-profile-select]");
  if (selector) {
    selector.addEventListener("change", (ev) => _setActiveProfile(ev.target.value));
  }

  // Inputs des tiers
  container.querySelectorAll("[data-tier-input]").forEach((input) => {
    input.addEventListener("input", (ev) => {
      const key = ev.target.dataset.tierInput;
      if (!_state.profileDraft) _state.profileDraft = { tiers: { ..._DEFAULT_TIERS }, weights: { ..._DEFAULT_WEIGHTS } };
      _state.profileDraft.tiers[key] = Math.max(0, Math.min(100, parseInt(ev.target.value, 10) || 0));
    });
  });

  // Sliders des poids
  container.querySelectorAll("[data-weight-input]").forEach((input) => {
    input.addEventListener("input", (ev) => {
      const key = ev.target.dataset.weightInput;
      if (!_state.profileDraft) _state.profileDraft = { tiers: { ..._DEFAULT_TIERS }, weights: { ..._DEFAULT_WEIGHTS } };
      const pct = Math.max(0, Math.min(100, parseInt(ev.target.value, 10) || 0));
      const v = pct / 100;
      _state.profileDraft.weights[key] = v;
      // MAJ affichage
      const valEl = container.querySelector(`[data-weight-value="${key}"]`);
      if (valEl) valEl.textContent = `×${v.toFixed(2)}`;
      // MAJ total
      const total = Object.values(_state.profileDraft.weights).reduce((s, x) => s + (Number(x) || 0), 0);
      const totalEl = container.querySelector("[data-weight-total]");
      if (totalEl) {
        const inRange = total >= 0.95 && total <= 1.05;
        totalEl.textContent = `Total = ${total.toFixed(2)} ${inRange ? "✓" : "⚠"}`;
        totalEl.className = `parametres-weight-total ${inRange ? "parametres-weight-total--ok" : "parametres-weight-total--warning"}`;
      }
    });
  });

  // Boutons d'action
  container.querySelectorAll("[data-parametres-profils-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.parametresProfilsAction;
      if (action === "save") _saveProfileAsNew();
      else if (action === "recompute") _recomputeScores();
      else if (action === "reset") {
        _state.profileDraft = { id: "", label: "", tiers: { ..._DEFAULT_TIERS }, weights: { ..._DEFAULT_WEIGHTS } };
        _showProfilMessage("Seuils et poids restaurés aux valeurs par défaut. Cliquez sur Sauvegarder pour créer un profil.", "info");
        _rerenderActiveCategory();
      }
    });
  });
}

/* =============================================================
 * 13) RE-RENDER & REFRESH
 * ============================================================= */

function _rerenderSidebar() {
  const host = _state.containerRef?.querySelector("[data-parametres-sidebar-host]");
  if (!host) return;
  host.innerHTML = _renderSubSidebar();
  _bindSidebar(_state.containerRef);
}

function _rerenderActiveCategory() {
  const main = _state.containerRef?.querySelector("#parametres-main-content");
  if (!main) return;
  main.innerHTML = _renderCategoryPanel(_state.activeCategory);
  _bindFields(_state.containerRef);
}

function _refreshAll() {
  const root = _state.containerRef;
  if (!root) return;
  root.innerHTML = _renderParametres();
  root.classList.toggle("is-expert", !!_state.settings.expert_mode);
  _bindHeader(root);
  _bindSidebar(root);
  _bindFields(root);
  // Live previews initiaux
  _applyLivePreview("theme", _state.settings.theme);
  _applyLivePreview("animation", _state.settings.animation_level);
  _applyLivePreview("effect_speed", _state.settings.effect_speed);
  _applyLivePreview("glow_intensity", _state.settings.glow_intensity);
  _applyLivePreview("light_intensity", _state.settings.light_intensity);
}

/* =============================================================
 * 14) RACCOURCI Ctrl+K (global handler)
 * ============================================================= */

let _ctrlKHandler = null;

function _installCtrlK() {
  if (_ctrlKHandler) return;
  _ctrlKHandler = (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
      const input = _state.containerRef?.querySelector("[data-parametres-search]");
      if (input) {
        e.preventDefault();
        input.focus();
        input.select();
      }
    }
  };
  document.addEventListener("keydown", _ctrlKHandler);
}

function _uninstallCtrlK() {
  if (_ctrlKHandler) {
    document.removeEventListener("keydown", _ctrlKHandler);
    _ctrlKHandler = null;
  }
}

/* =============================================================
 * 15) ENTRY POINTS
 * ============================================================= */

export async function initParametres(container) {
  if (!container) return;
  _state.containerRef = container;
  const lastCat = _readString(STORAGE_KEY_LAST_CATEGORY, "sources");
  if (PARAMETRES_GROUPS.some((c) => c.id === lastCat)) _state.activeCategory = lastCat;

  container.setAttribute("aria-busy", "true");
  container.innerHTML = `<section class="parametres-view parametres-view--loading"><p class="parametres-muted">Chargement des paramètres…</p></section>`;

  try {
    await _loadSettings();
    await _loadProfiles();
  } catch (err) {
    container.innerHTML = _renderError(err?.message || String(err));
    const retry = container.querySelector("[data-parametres-retry]");
    if (retry) retry.addEventListener("click", () => initParametres(container));
    container.setAttribute("aria-busy", "false");
    return;
  } finally {
    container.setAttribute("aria-busy", "false");
  }

  _refreshAll();
  _installCtrlK();
}

export function unmountParametres() {
  if (_state.saveTimer) { clearTimeout(_state.saveTimer); _state.saveTimer = null; }
  _uninstallCtrlK();
  _state.containerRef = null;
  _state.searchQuery = "";
  _state.savedAt = null;
  _state.saveError = null;
}
