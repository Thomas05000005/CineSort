/* views/settings.js — V7-fusion Phase 2 SETTINGS
 *
 * Base : architecture v5 schema declaratif (web/views/settings-v5.js).
 * Ajouts : 5 fixes mismatches noms champs (sinon save_settings ecrase silencieusement)
 *          + features v4 portees (boutons test connexion, QR dashboard, restart API,
 *            regen/copy token, sliders apparence preview live, notifications_undo_done).
 *
 * Champs orphelins backend supprimes (tmdb_lang, ui_density, log_level,
 * cache_size_limit_mb, watchlist_*) — ils n'existent pas cote serveur, donc
 * les laisser dans le schema confondrait l'utilisateur.
 *
 * Endpoints utilises : save_settings, get_settings, get_user_data_size,
 *   reset_all_user_data, get_update_info, check_for_updates,
 *   test_tmdb_key, test_jellyfin_connection, test_plex_connection,
 *   test_radarr_connection, restart_api_server, get_dashboard_qr,
 *   get_server_info.
 */

import { apiPost } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
import { glossaryTooltip } from "../components/glossary-tooltip.js";
import { t, onLocaleChange } from "../core/i18n.js";

/**
 * V6-02 helper : resout un label sur un objet { labelKey?, label?, l? } via i18n.
 * Fallback sur label/l si labelKey absent (compat tests existants).
 */
function _i18nLabel(obj, fallback) {
  if (!obj) return fallback || "";
  if (obj.labelKey) {
    const tr = t(obj.labelKey);
    // si la cle n'est pas trouvee, t() renvoie la cle elle-meme. Dans ce cas
    // on prefere le fallback explicite.
    if (tr && tr !== obj.labelKey) return tr;
  }
  return obj.label || obj.l || fallback || "";
}

/* ===========================================================
 * Schema 9 groupes (avec corrections v4 backend)
 * =========================================================== */

export const SETTINGS_GROUPS = [
  {
    id: "sources", label: "Sources", labelKey: "settings.groups.sources", iconPath: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    sections: [
      { id: "roots", label: "Dossiers racines", labelKey: "settings.sections.roots", fields: [
        // V2-D (a11y, WCAG 3.3.2) : champ obligatoire (sans roots, scan impossible).
        { key: "roots", label: "Chemins racine", type: "multi-path", hint: "Séparés par ; ou par ligne", glossaryTerm: "Roots", required: true },
      ]},
      { id: "watch", label: "Surveillance auto (watch folder)", labelKey: "settings.sections.watch", fields: [
        { key: "watch_enabled", label: "Activer la surveillance", type: "toggle" },
        { key: "watch_interval_minutes", label: "Intervalle (min)", type: "number", min: 1, max: 60, default: 5, advanced: true },
      ]},
    ],
  },
  {
    id: "analyse", label: "Analyse", labelKey: "settings.groups.analyse", iconPath: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    sections: [
      { id: "probe", label: "Probe", labelKey: "settings.sections.probe", fields: [
        { key: "probe_backend", label: "Backend", type: "select", options: [
          {v:"auto",l:"Auto"},{v:"ffprobe",l:"ffprobe"},{v:"mediainfo",l:"mediainfo"},{v:"none",l:"Aucun"},
        ]},
        { key: "probe_timeout_s", label: "Timeout probe (s)", type: "number", min: 5, max: 300, advanced: true },
      ]},
      { id: "perceptual", label: "Analyse perceptuelle", labelKey: "settings.sections.perceptual", fields: [
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
      { id: "scoring", label: "Scoring qualité", labelKey: "settings.sections.scoring", fields: [
        { key: "auto_approve_enabled", label: "Approbation auto", type: "toggle" },
        { key: "auto_approve_threshold", label: "Seuil confiance (%)", type: "number", min: 70, max: 100 },
        // V4-05 (Polish Total v7.7.0, R4-PERC-7 / H16) : toggle Composite Score V1/V2.
        // V1 reste defaut. Switch V2 = opt-in. Pas de re-scoring auto :
        // les anciens scores restent V1 jusqu'a un nouveau scan/analyse perceptuelle.
        { key: "composite_score_version", label: "Score composite", type: "select", options: [
          { v: 1, l: "Composite Score V1 (stable)" },
          { v: 2, l: "Composite Score V2 (avancé)" },
        ], hint: "V1 par défaut. V2 utilise des poids et règles d'ajustement enrichis. Les scores existants ne seront PAS re-calculés automatiquement." },
      ]},
    ],
  },
  {
    id: "nommage", label: "Nommage", labelKey: "settings.groups.nommage", iconPath: '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
    sections: [
      { id: "templates", label: "Templates de renommage", labelKey: "settings.sections.templates", fields: [
        { key: "naming_preset", label: "Preset", type: "select", options: [
          {v:"default",l:"Défaut"},{v:"plex",l:"Plex"},{v:"jellyfin",l:"Jellyfin"},{v:"quality",l:"Qualité"},{v:"custom",l:"Custom"},
        ]},
        { key: "naming_movie_template", label: "Template film", type: "text", placeholder: "{title} ({year})" },
        { key: "naming_tv_template", label: "Template série", type: "text", placeholder: "{series} ({year})" },
      ]},
    ],
  },
  {
    id: "bibliotheque", label: "Bibliothèque", labelKey: "settings.groups.bibliotheque", iconPath: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    sections: [
      { id: "organization", label: "Organisation", labelKey: "settings.sections.organization", fields: [
        { key: "collection_folder_enabled", label: "Regrouper les sagas en _Collection/", type: "toggle" },
        { key: "enable_tv_detection", label: "Détection séries TV", type: "toggle" },
      ]},
      { id: "cleanup", label: "Nettoyage", labelKey: "settings.sections.cleanup", fields: [
        // V7-fix R1 : nom backend correct (etait "cleanup_empty_folders" en v5 = mismatch).
        { key: "move_empty_folders_enabled", label: "Déplacer dossiers vides vers _Vide", type: "toggle" },
        // V7-fix : nom backend correct (etait "cleanup_residuals" en v5 = mismatch).
        { key: "cleanup_residual_folders_enabled", label: "Nettoyer fichiers résiduels", type: "toggle" },
      ]},
      { id: "subtitles", label: "Sous-titres", labelKey: "settings.sections.subtitles", fields: [
        { key: "subtitle_detection_enabled", label: "Détection sous-titres", type: "toggle" },
        { key: "subtitle_expected_languages", label: "Langues attendues", type: "text", placeholder: "fr;en", hint: "Séparées par ;" },
      ]},
    ],
  },
  {
    id: "integrations", label: "Intégrations", labelKey: "settings.groups.integrations", iconPath: '<path d="M9 11H1l6 6 6-6h-3V3h-1z"/><path d="M22 12.5V7l-6-6H6a2 2 0 0 0-2 2v6"/>',
    sections: [
      { id: "tmdb", label: "TMDb", labelKey: "settings.sections.tmdb", fields: [
        // V7-port : bouton test inline via testMethod.
        // V2-D (a11y) : requis pour utiliser TMDb (matching/posters/collections).
        { key: "tmdb_api_key", label: "Clé API TMDb", type: "api-key", glossaryTerm: "TMDb",
          testMethod: "integrations/test_tmdb_key", testParams: { api_key: "$value", state_dir: "" }, required: true },
        // V5-03 polish v7.7.0 (R5-STRESS-4) : TTL configurable du cache local.
        { key: "tmdb_cache_ttl_days", label: "Durée du cache TMDb (jours)", type: "number",
          min: 1, max: 365, hint: "Au-delà, les fiches sont rafraîchies. Purge automatique au démarrage." },
      ]},
      { id: "jellyfin", label: "Jellyfin", labelKey: "settings.sections.jellyfin", fields: [
        { key: "jellyfin_enabled", label: "Activer", type: "toggle" },
        { key: "jellyfin_url", label: "URL", type: "text", placeholder: "http://jellyfin.local:8096" },
        { key: "jellyfin_api_key", label: "Clé API", type: "api-key",
          testMethod: "integrations/test_jellyfin_connection", testParams: { url: "$jellyfin_url", api_key: "$value" } },
        { key: "jellyfin_refresh_on_apply", label: "Refresh auto après apply", type: "toggle" },
        { key: "jellyfin_sync_watched", label: "Sync watched", type: "toggle" },
      ]},
      { id: "plex", label: "Plex", labelKey: "settings.sections.plex", fields: [
        { key: "plex_enabled", label: "Activer", type: "toggle" },
        { key: "plex_url", label: "URL", type: "text" },
        { key: "plex_token", label: "Token", type: "api-key",
          testMethod: "integrations/test_plex_connection", testParams: { url: "$plex_url", token: "$value" } },
        { key: "plex_refresh_on_apply", label: "Refresh après apply", type: "toggle" },
      ]},
      { id: "radarr", label: "Radarr", labelKey: "settings.sections.radarr", fields: [
        { key: "radarr_enabled", label: "Activer", type: "toggle" },
        { key: "radarr_url", label: "URL", type: "text" },
        { key: "radarr_api_key", label: "Clé API", type: "api-key",
          testMethod: "integrations/test_radarr_connection", testParams: { url: "$radarr_url", api_key: "$value" } },
      ]},
      // Phase 6.2 : OMDb (cross-check IMDb pour identification)
      { id: "omdb", label: "OMDb", labelKey: "settings.sections.omdb", fields: [
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
    id: "notifications", label: "Notifications", labelKey: "settings.groups.notifications", iconPath: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    sections: [
      { id: "desktop", label: "Desktop", labelKey: "settings.sections.desktop", fields: [
        { key: "notifications_enabled", label: "Activer", type: "toggle" },
        { key: "notifications_scan_done", label: "Scan terminé", type: "toggle" },
        { key: "notifications_apply_done", label: "Apply terminé", type: "toggle" },
        // V7-fix R6 : champ present en v4, oublie dans le schema v5.
        { key: "notifications_undo_done", label: "Undo terminé", type: "toggle" },
        { key: "notifications_errors", label: "Erreurs critiques", type: "toggle" },
      ]},
      { id: "email", label: "Rapports email", labelKey: "settings.sections.email", fields: [
        { key: "email_enabled", label: "Activer", type: "toggle" },
        // V7-fix R3-R5 : noms backend (etait email_host/port/user en v5 = mismatch).
        { key: "email_smtp_host", label: "SMTP host", type: "text", advanced: true },
        { key: "email_smtp_port", label: "SMTP port", type: "number", min: 1, max: 65535, advanced: true },
        { key: "email_smtp_user", label: "Utilisateur", type: "text", advanced: true },
        // V7-fix R2 : nom backend (etait email_password en v5 = mismatch DPAPI critique).
        { key: "email_smtp_password", label: "Mot de passe", type: "api-key", advanced: true,
          testMethod: "test_email_report" },
        { key: "email_smtp_tls", label: "STARTTLS", type: "toggle", advanced: true },
        { key: "email_to", label: "Destinataire", type: "text" },
        { key: "email_on_scan", label: "Après scan", type: "toggle", advanced: true },
        { key: "email_on_apply", label: "Après apply", type: "toggle", advanced: true },
      ]},
      { id: "plugins", label: "Plugins hooks", labelKey: "settings.sections.plugins", fields: [
        { key: "plugins_enabled", label: "Activer plugins", type: "toggle" },
        { key: "plugins_timeout_s", label: "Timeout (s)", type: "number", min: 5, max: 120, advanced: true },
      ]},
    ],
  },
  {
    id: "serveur", label: "Serveur distant", labelKey: "settings.groups.serveur", iconPath: '<rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/>',
    sections: [
      { id: "rest", label: "API REST", labelKey: "settings.sections.rest", fields: [
        { key: "rest_api_enabled", label: "Activer API REST", type: "toggle" },
        { key: "rest_api_port", label: "Port", type: "number", min: 1024, max: 65535 },
        // V7-port : bouton regen + copy + show pour le token (replace api-key standard).
        { key: "rest_api_token", label: "Clé d'accès (Bearer)", type: "api-key-rest" },
        // V7-port : bouton restart serveur.
        { key: "__restart_api__", label: "", type: "action", action: "restart_api", buttonLabel: "🔄 Redémarrer le service API" },
        // V7-port : bloc QR + URL dashboard.
        { key: "__qr_dashboard__", label: "", type: "qr-dashboard" },
      ]},
      { id: "https", label: "HTTPS (optionnel)", labelKey: "settings.sections.https", fields: [
        { key: "rest_api_https_enabled", label: "Activer HTTPS", type: "toggle", advanced: true },
        { key: "rest_api_cert_path", label: "Chemin certificat", type: "path", advanced: true },
        { key: "rest_api_key_path", label: "Chemin clé", type: "path", advanced: true },
      ]},
    ],
  },
  {
    id: "apparence", label: "Apparence", labelKey: "settings.groups.apparence", iconPath: '<circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>',
    sections: [
      { id: "theme", label: "Thème", labelKey: "settings.sections.theme", fields: [
        { key: "theme", label: "Thème", type: "select", options: [
          {v:"studio",l:"Studio"},{v:"cinema",l:"Cinéma"},{v:"luxe",l:"Luxe"},{v:"neon",l:"Neon"},
        ], livePreview: "theme" },
        { key: "animation_level", label: "Niveau animation", type: "select", options: [
          {v:"subtle",l:"Subtil"},{v:"moderate",l:"Modéré"},{v:"intense",l:"Intense"},
        ], livePreview: "animation" },
      ]},
      // V7-port : sliders apparence avec preview live (CSS custom properties).
      { id: "effects", label: "Effets visuels", labelKey: "settings.sections.effects", fields: [
        { key: "effect_speed", label: "Vitesse animations (%)", type: "range", min: 0, max: 100, default: 50, livePreview: "effect_speed" },
        { key: "glow_intensity", label: "Intensité glow (%)", type: "range", min: 0, max: 100, default: 30, livePreview: "glow_intensity" },
        { key: "light_intensity", label: "Intensité lumière (%)", type: "range", min: 0, max: 100, default: 20, livePreview: "light_intensity" },
        // V7-fix : zone preview visible qui consomme les 4 variables en temps reel.
        // Sans ca l'utilisateur ne voit aucun effet car les variables ne sont consommees
        // que par quelques composants peu visibles (boutons primary glow, scanPulse...).
        { key: "__effects_preview__", label: "", type: "effects-preview" },
      ]},
    ],
  },
  {
    id: "avance", label: "Avancé", labelKey: "settings.groups.avance", iconPath: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    sections: [
      { id: "parallelism", label: "Parallélisme", labelKey: "settings.sections.parallelism", fields: [
        { key: "perceptual_parallelism_mode", label: "Mode parallélisme", type: "select", options: [
          {v:"auto",l:"Auto"},{v:"max",l:"Max"},{v:"safe",l:"Sécurisé"},{v:"serial",l:"Séquentiel"},
        ]},
      ]},
      { id: "onboarding", label: "Onboarding", labelKey: "settings.sections.onboarding", fields: [
        { key: "onboarding_completed", label: "Wizard premier lancement terminé", type: "toggle" },
      ]},
      { id: "updates", label: "Mises à jour", labelKey: "settings.sections.updates", fields: [
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

function _esc(s) { return escapeHtml(String(s ?? "")); }
function _svg(p, s) { const sz = s || 18; return `<svg viewBox="0 0 24 24" width="${sz}" height="${sz}" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`; }

/* === Mode expert === */
function _applyExpertMode(isExpert) {
  document.body.classList.toggle("v5-expert-mode-on", !!isExpert);
  document.body.classList.toggle("v5-expert-mode-off", !isExpert);
  document.querySelectorAll(".v5-settings-field[data-advanced='true']").forEach((el) => {
    el.style.display = isExpert ? "" : "none";
  });
}

/* === Search fuzzy === */
function _searchMatch(query, group) {
  if (!query) return true;
  const q = query.toLowerCase().trim();
  if (!q) return true;
  if (_i18nLabel(group, "").toLowerCase().includes(q)) return true;
  for (const section of group.sections || []) {
    if (_i18nLabel(section, "").toLowerCase().includes(q)) return true;
    for (const field of section.fields || []) {
      if (_i18nLabel(field, "").toLowerCase().includes(q)) return true;
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
  if (_i18nLabel(section, "").toLowerCase().includes(q)) return true;
  for (const field of section.fields || []) {
    if (_i18nLabel(field, "").toLowerCase().includes(q)) return true;
    if ((field.hint || "").toLowerCase().includes(q)) return true;
    if ((field.key || "").toLowerCase().includes(q)) return true;
  }
  return false;
}

/* === Configure status === */
function _isFieldConfigured(field, settings) {
  if (field.key && field.key.startsWith("__")) return false; // pseudo-fields (qr, restart, update-status)
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

function _sectionStatusBadge(status) {
  if (status === "full") return `<span class="v5-settings-badge v5-settings-badge--full">${escapeHtml(t("settings.badge_full"))}</span>`;
  if (status === "partial") return `<span class="v5-settings-badge v5-settings-badge--partial">${escapeHtml(t("settings.badge_partial"))}</span>`;
  return "";
}

/* ===========================================================
 * Field renderers
 * =========================================================== */

function _renderField(field, value) {
  const id = `v5s_${_esc(field.key)}`;
  // V2-D (a11y, WCAG 3.3.2 Labels or Instructions) : aria-required + asterisque visuel.
  const reqAttr = field.required ? ' aria-required="true" required' : "";
  const reqMark = field.required
    ? ' <span class="v5-settings-required" aria-hidden="true" style="color:var(--danger,#EF4444);font-weight:bold">*</span>'
    : "";
  const common = `id="${id}" data-field-key="${_esc(field.key)}"${reqAttr} ${field.livePreview ? `data-live-preview="${_esc(field.livePreview)}"` : ""}`;
  const advAttr = field.advanced ? ' data-advanced="true"' : "";
  // V6-02 : label resolu via i18n (fallback `field.label`).
  const fieldLabel = _i18nLabel(field, field.label || field.key);
  const baseLabel = field.glossaryTerm ? glossaryTooltip(field.glossaryTerm, fieldLabel) : _esc(fieldLabel);
  const labelHtml = baseLabel + reqMark;

  switch (field.type) {
    case "toggle":
      return `<label class="v5-settings-field v5-settings-field--toggle"${advAttr}>
        <span class="v5-settings-field-label">${labelHtml}</span>
        <input type="checkbox" class="v5-checkbox" ${common} ${value ? "checked" : ""}>
        ${field.hint ? `<span class="v5-settings-field-hint">${_esc(field.hint)}</span>` : ""}
      </label>`;

    case "number":
      return `<div class="v5-settings-field"${advAttr}>
        <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
        <input type="number" class="v5-input v5-input--sm" ${common}
               min="${_esc(field.min || 0)}" max="${_esc(field.max || 999999)}"
               value="${_esc(value != null ? value : (field.default || ""))}">
        ${field.hint ? `<span class="v5-settings-field-hint">${_esc(field.hint)}</span>` : ""}
      </div>`;

    case "text":
    case "path":
      return `<div class="v5-settings-field"${advAttr}>
        <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
        <input type="text" class="v5-input" ${common}
               placeholder="${_esc(field.placeholder || "")}"
               value="${_esc(value || "")}">
        ${field.hint ? `<span class="v5-settings-field-hint">${_esc(field.hint)}</span>` : ""}
      </div>`;

    case "api-key": {
      const testBtn = field.testMethod
        ? `<button type="button" class="v5-btn v5-btn--sm" data-test-method="${_esc(field.testMethod)}" data-test-field="${_esc(field.key)}">${_esc(t("common.test"))}</button>`
        : "";
      return `<div class="v5-settings-field"${advAttr}>
        <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
        <div class="v5-settings-api-key-wrap" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <input type="password" class="v5-input" ${common} value="${_esc(value || "")}" autocomplete="off" style="flex:1;min-width:200px">
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-api-key-toggle="${id}" title="${_esc(t("common.show_hide"))}">👁</button>
          ${testBtn}
          <span class="v5-test-result" data-test-result-for="${_esc(field.key)}" style="font-size:var(--fs-xs);color:var(--text-muted)"></span>
        </div>
      </div>`;
    }

    case "api-key-rest": {
      // V7-port : token REST avec show/copy/regen.
      return `<div class="v5-settings-field"${advAttr}>
        <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
        <div class="v5-settings-api-key-wrap" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <input type="password" class="v5-input" ${common} value="${_esc(value || "")}" autocomplete="off" style="flex:1;min-width:200px">
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-api-key-toggle="${id}" title="${_esc(t("common.show_hide"))}">👁</button>
          <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-rest-token-copy title="${_esc(t("settings.rest_token_copy_title"))}">📋</button>
          <button type="button" class="v5-btn v5-btn--sm" data-rest-token-regen title="${_esc(t("settings.rest_token_regen_title"))}">🔄</button>
          <span class="v5-rest-token-msg" data-rest-token-msg style="font-size:var(--fs-xs);color:var(--text-muted)"></span>
        </div>
      </div>`;
    }

    case "select":
      return `<div class="v5-settings-field"${advAttr}>
        <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
        <select class="v5-select" ${common}>
          ${(field.options || []).map((o) =>
            `<option value="${_esc(o.v)}" ${o.v === value ? "selected" : ""}>${_esc(o.l)}</option>`
          ).join("")}
        </select>
      </div>`;

    case "range": {
      // V7-port : slider avec preview live des CSS custom properties.
      const v = (value != null && value !== "") ? value : (field.default || 50);
      return `<div class="v5-settings-field"${advAttr}>
        <label class="v5-settings-field-label" for="${id}">${labelHtml}<span class="v5-range-value" style="float:right;color:var(--text-muted)" data-range-value-for="${_esc(field.key)}">${_esc(v)}</span></label>
        <input type="range" class="v5-input" ${common}
               min="${_esc(field.min || 0)}" max="${_esc(field.max || 100)}" value="${_esc(v)}"
               style="width:100%">
      </div>`;
    }

    case "multi-path": {
      const arr = Array.isArray(value) ? value : (typeof value === "string" ? value.split(";") : []);
      return `<div class="v5-settings-field"${advAttr}>
        <label class="v5-settings-field-label" for="${id}">${labelHtml}</label>
        <textarea class="v5-textarea" ${common} rows="4">${_esc(arr.join("\n"))}</textarea>
        ${field.hint ? `<span class="v5-settings-field-hint">${_esc(field.hint)}</span>` : ""}
        ${field.required ? `<span class="v5-settings-field-hint" style="color:var(--danger,#EF4444)">${_esc(t("settings.fields.field_required_hint"))}</span>` : ""}
      </div>`;
    }

    case "action":
      // V7-port : bouton standalone (restart, etc.).
      return `<div class="v5-settings-field"${advAttr}>
        <button type="button" class="v5-btn" data-action="${_esc(field.action)}">${_esc(field.buttonLabel || "Action")}</button>
        <span class="v5-action-result" data-action-result-for="${_esc(field.action)}" style="font-size:var(--fs-xs);color:var(--text-muted);margin-left:var(--sp-3)"></span>
      </div>`;

    case "effects-preview":
      // V7-fix : zone preview visible des 4 variables apparence (slider live).
      // Le CSS inline ci-dessous consomme TOUTES les variables pour que l'utilisateur
      // voie l'effet meme si les variables sont peu utilisees ailleurs sur la page.
      return `<div class="v5-settings-field">
        <label class="v5-settings-field-label">${_esc(t("settings.preview_effects.title"))}</label>
        <div class="apparence-preview" style="
          display:flex;gap:var(--sp-3);align-items:center;flex-wrap:wrap;
          background:var(--bg-raised);
          padding:var(--sp-4);border-radius:var(--radius-md);
          border:1px solid var(--border-1);
          opacity:calc(0.55 + var(--light-intensity, 0.2) * 1.5);
          transition:opacity calc(0.4s / var(--animation-speed, 1)) ease;
        ">
          <button type="button" style="
            background:var(--accent);color:#fff;border:0;
            padding:10px 18px;border-radius:var(--radius-md);font-weight:600;cursor:pointer;
            box-shadow:0 0 calc(20px * var(--glow-intensity, 0.3)) var(--accent),
                       0 4px 12px rgba(0,0,0,calc(0.3 + var(--effect-opacity, 0.06) * 4));
            transition:all calc(0.3s / var(--animation-speed, 1)) ease;
          ">${_esc(t("settings.preview_effects.btn_glow"))}</button>
          <div style="
            background:var(--surface-2);
            padding:12px 18px;border-radius:var(--radius-md);
            border:1px solid var(--accent);
            box-shadow:0 0 calc(15px * var(--glow-intensity, 0.3)) var(--accent),
                       inset 0 0 calc(8px * var(--glow-intensity, 0.3)) rgba(255,255,255,calc(var(--effect-opacity, 0.06) * 8));
            color:var(--text-primary);font-weight:500;
            transition:box-shadow calc(0.3s / var(--animation-speed, 1)) ease;
          ">${_esc(t("settings.preview_effects.card_glow"))}</div>
          <div style="
            width:60px;height:60px;border-radius:50%;
            background:radial-gradient(circle,var(--accent) 0%,transparent 70%);
            opacity:calc(0.4 + var(--glow-intensity, 0.3) * 1.5);
            animation:apparencePreviewPulse calc(2s / var(--animation-speed, 1)) ease-in-out infinite;
          "></div>
          <span style="color:var(--text-muted);font-size:var(--fs-xs);flex:1;min-width:200px">
            ${_esc(t("settings.preview_effects.hint"))}
          </span>
        </div>
        <style>
          @keyframes apparencePreviewPulse {
            0%, 100% { transform:scale(0.85); }
            50%      { transform:scale(1.1); }
          }
        </style>
      </div>`;

    case "qr-dashboard":
      // V7-port : bloc QR + URL + token (chargement au mount).
      return `<div class="v5-settings-field"${advAttr}>
        <label class="v5-settings-field-label">${_esc(t("settings.qr.section_title"))}</label>
        <div data-qr-dashboard style="display:flex;gap:var(--sp-4);align-items:flex-start;flex-wrap:wrap;background:var(--surface-1);padding:var(--sp-3);border-radius:var(--radius-md);border:1px solid var(--border-1)">
          <span class="v5-text-muted">${_esc(t("settings.qr.loading"))}</span>
        </div>
      </div>`;

    case "update-status": {
      const auto = _state.settings.auto_check_updates;
      const checked = (auto === undefined ? !!_state.settings.update_check_enabled : !!auto) ? "checked" : "";
      return `<section class="updates-section v5-settings-update">
        <h2 class="v5-settings-update-title">${_esc(t("settings.updates.title"))}</h2>
        <div id="updateStatusContent" class="v5-settings-update-status">
          <p class="text-muted v5u-text-muted">${_esc(t("settings.updates.loading"))}</p>
        </div>
        <button type="button" class="btn v5-btn v5-btn--sm" id="btnCheckUpdates">${_esc(t("settings.updates.check_now"))}</button>
        <label class="switch-label v5-settings-update-toggle">
          <input type="checkbox" id="ckAutoCheckUpdates" ${checked} />
          <span>${_esc(t("settings.updates.auto_check"))}</span>
        </label>
      </section>`;
    }

    default:
      return `<div class="v5-settings-field">${_esc(t("settings.fields.type_unsupported", { label: _i18nLabel(field, field.label || field.key), type: field.type }))}</div>`;
  }
}

function _readField(field, fieldEl) {
  if (!fieldEl) return undefined;
  switch (field.type) {
    case "toggle": return !!fieldEl.checked;
    case "number": case "range": return Number(fieldEl.value) || 0;
    case "multi-path": return fieldEl.value.split(/[\n;]+/).map((s) => s.trim()).filter(Boolean);
    default: return fieldEl.value;
  }
}

/* === Update status === */

async function _loadUpdateStatus() {
  const el = document.getElementById("updateStatusContent");
  if (!el) return;
  const res = await apiPost("get_update_info");
  if (!res || !res.data) { el.innerHTML = `<p class="v5u-text-muted">${_esc(t("settings.updates.status_unavailable"))}</p>`; return; }
  const info = res.data || {};
  const current = info.current_version || "?";
  const latest = info.latest_version;
  if (info.update_available && latest) {
    el.innerHTML = `<div class="update-card update-card--available">
      <p>${_esc(t("settings.updates.available_title"))} : ${_esc(latest)}</p>
      <p>${_esc(t("settings.updates.available_current", { current }))}</p>
      <a class="btn v5-btn v5-btn--primary" href="${_esc(info.release_url || "")}" target="_blank" rel="noopener">${_esc(t("settings.updates.download_github"))}</a>
      <p class="v5u-text-muted v5-settings-update-notes">${_esc(info.release_notes_short || "")}</p>
    </div>`;
  } else if (latest) {
    el.innerHTML = `<p>${_esc(t("settings.updates.up_to_date", { current }))}</p>`;
  } else {
    el.innerHTML = `<p class="v5u-text-muted">${_esc(t("settings.updates.no_info"))}</p>`;
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
      target.textContent = t("settings.updates.checking");
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
  if (container.querySelector("#updateStatusContent")) _loadUpdateStatus();
}

/* === V7-port : QR Dashboard ============================== */

async function _loadQrDashboard(container) {
  const host = container.querySelector("[data-qr-dashboard]");
  if (!host) return;
  const token = String(_state.settings.rest_api_token || "");
  if (!_state.settings.rest_api_enabled) {
    host.innerHTML = `<span class="v5u-text-muted">${_esc(t("settings.qr.rest_disabled"))}</span>`;
    return;
  }
  if (!token) {
    host.innerHTML = `<span style="color:var(--warning)">${_esc(t("settings.qr.no_token"))}</span>`;
    return;
  }
  let qrSvg = "", url = "";
  try {
    const r = await apiPost("get_dashboard_qr");
    if (r?.data?.ok) { qrSvg = r.data.svg || ""; url = r.data.url || ""; }
  } catch { /* noop */ }
  if (!url) {
    try {
      const si = await apiPost("get_server_info");
      if (si?.data?.ok) url = si.data.dashboard_url || "";
    } catch { /* noop */ }
  }
  host.innerHTML = `
    ${qrSvg ? `<div style="min-width:140px">${qrSvg}</div>` : ""}
    <div style="flex:1;min-width:240px">
      <div class="v5u-text-muted" style="font-size:0.85em;margin-bottom:4px">${_esc(t("settings.qr.url_label"))}</div>
      <code style="display:block;word-break:break-all;font-family:monospace;padding:6px 10px;background:var(--bg-raised);border-radius:var(--radius-sm);border:1px solid var(--border-1);margin-bottom:6px">${_esc(url || t("settings.qr.url_placeholder"))}</code>
      <button type="button" class="v5-btn v5-btn--sm" data-qr-copy-url="${_esc(url)}">${_esc(t("settings.qr.copy_url"))}</button>
      <p class="v5u-text-muted" style="font-size:0.85em;margin-top:var(--sp-2)">${_esc(t("settings.qr.scan_hint"))}</p>
    </div>`;
  // Hook copy
  const copyBtn = host.querySelector("[data-qr-copy-url]");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const restoreLabel = t("settings.qr.copy_url");
      try { await navigator.clipboard.writeText(copyBtn.dataset.qrCopyUrl); copyBtn.textContent = t("common.copied"); setTimeout(() => copyBtn.textContent = restoreLabel, 1800); } catch { /* noop */ }
    });
  }
}

/* === Sidebar === */

function _renderSidebar(container) {
  const items = SETTINGS_GROUPS.map((g) => {
    const visible = _searchMatch(_state.searchQuery, g);
    if (!visible) return "";
    const isActive = g.id === _state.activeCategory;
    let totalFields = 0, configuredFields = 0;
    g.sections.forEach((s) => {
      s.fields.forEach((f) => {
        if (f.key.startsWith("__")) return;
        totalFields += 1;
        if (_isFieldConfigured(f, _state.settings)) configuredFields += 1;
      });
    });
    const status = configuredFields === 0 ? "none" : configuredFields === totalFields ? "full" : "partial";
    const dot = status !== "none"
      ? `<span class="v5-settings-cat-dot v5-settings-cat-dot--${_esc(status)}" title="${_esc(t("settings.configured_count_title", { configured: configuredFields, total: totalFields }))}"></span>` : "";
    return `<button type="button" class="v5-settings-cat ${isActive ? "is-active" : ""}"
            data-settings-cat="${_esc(g.id)}" role="tab" aria-selected="${isActive ? "true" : "false"}">
      <span class="v5-settings-cat-icon">${_svg(g.iconPath, 18)}</span>
      <span class="v5-settings-cat-label">${_esc(_i18nLabel(g, g.label))}</span>
      ${dot}
    </button>`;
  }).join("");

  container.innerHTML = `<div class="v5-settings-sidebar">
    <div class="v5-settings-search-wrap">
      <input type="text" class="v5-input v5-input--sm" data-v5-settings-search placeholder="${_esc(t("settings.sidebar_search_placeholder"))}" value="${_esc(_state.searchQuery)}">
    </div>
    <nav class="v5-settings-cats" role="tablist" aria-label="${_esc(t("settings.sidebar_aria"))}">
      ${items || `<div class="v5u-text-muted v5u-p-3">${_esc(t("settings.sidebar_no_match"))}</div>`}
    </nav>
  </div>`;

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
      debounce = setTimeout(() => { _state.searchQuery = searchInput.value; _refreshAll(); }, 150);
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

/* === Content === */

function _renderContent(container) {
  const group = SETTINGS_GROUPS.find((g) => g.id === _state.activeCategory);
  if (!group) { container.innerHTML = `<div class="v5-settings-empty">${_esc(t("settings.group_not_found"))}</div>`; return; }
  const sections = group.sections.filter((s) => _sectionMatchesQuery(_state.searchQuery, s));
  const showDangerZone = group.id === "avance" && _sectionMatchesQuery(_state.searchQuery, {
    label: "zone danger reset reinitialiser", fields: [{ label: "reset reinitialiser danger" }],
  });

  container.innerHTML = `<div class="v5-settings-content">
    <header class="v5-settings-header">
      <h2 class="v5-settings-header-title">${_svg(group.iconPath, 22)} ${_esc(_i18nLabel(group, group.label))}</h2>
      <div class="v5-settings-saved-state" data-v5-saved-state></div>
      <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-v5-settings-reload>${_esc(t("common.reload"))}</button>
    </header>
    ${sections.length === 0 && !showDangerZone
      ? `<div class="v5-settings-empty">${_esc(t("settings.no_section_match"))}</div>`
      : sections.map((section) => _renderSection(group, section)).join("") + (showDangerZone ? _renderDangerZone() : "")}
  </div>`;

  _bindContentEvents(container);
  if (showDangerZone) _bindDangerZoneEvents(container);
  // V7-port : si la section contient un QR dashboard, le charger.
  if (container.querySelector("[data-qr-dashboard]")) _loadQrDashboard(container);
  _updateSavedStateLabel();
}

function _renderDangerZone() {
  return `<section class="danger-zone" data-v5-danger-zone>
    <h2>${_svg('<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>', 20)} ${_esc(t("danger_zone.title"))}</h2>
    <div class="danger-card">
      <h3>${_esc(t("danger_zone.reset_title"))}</h3>
      <p>${_esc(t("danger_zone.reset_desc"))}</p>
      <p>${t("danger_zone.reset_preserve")}</p>
      <p class="text-muted">${_esc(t("danger_zone.reset_backup"))}</p>
      <p id="userDataSizeInfo" class="text-muted">${_esc(t("danger_zone.current_data"))}</p>
      <button type="button" class="v5-btn btn--danger" data-v5-open-reset-dialog>${_esc(t("danger_zone.reset_button"))}</button>
    </div>
  </section>`;
}

function _bindDangerZoneEvents(container) {
  const sizeEl = container.querySelector("#userDataSizeInfo");
  if (sizeEl) {
    apiPost("settings/get_user_data_size").then((res) => {
      const data = (res && res.data) || {};
      sizeEl.textContent = t("danger_zone.current_data_known", { items: data.items || 0, size: data.size_mb || 0 });
    }).catch(() => { sizeEl.textContent = t("danger_zone.current_data_unavailable"); });
  }
  const btn = container.querySelector("[data-v5-open-reset-dialog]");
  if (btn) btn.addEventListener("click", _openResetDialog);
}

async function _openResetDialog() {
  const sizeRes = await apiPost("settings/get_user_data_size");
  const sizeData = (sizeRes && sizeRes.data) || {};
  const sizeMb = sizeData.size_mb || 0;
  const items = sizeData.items || 0;
  const c1 = window.prompt(t("danger_zone.prompt_confirm", { items, size: sizeMb }));
  if (c1 !== "RESET") { if (c1 !== null) window.alert(t("danger_zone.wrong_confirm")); return; }
  if (!window.confirm(t("danger_zone.last_chance"))) return;
  const res = await apiPost("settings/reset_all_user_data", { confirmation: "RESET" });
  if (res && res.data && res.data.ok) {
    const backupPath = (res.data.backup_path) || "";
    window.alert(t("danger_zone.reset_done", { path: backupPath }));
    window.location.reload();
  } else {
    window.alert(t("danger_zone.reset_error", { msg: res?.data?.message || t("common.error_unknown") }));
  }
}

function _renderSection(group, section) {
  const status = _sectionStatus(section, _state.settings);
  const fields = (section.fields || []).map((f) => _renderField(f, _state.settings[f.key])).join("");
  return `<section class="v5-settings-section" data-section-id="${_esc(section.id)}">
    <header class="v5-settings-section-header">
      <h3 class="v5-settings-section-title">${_esc(_i18nLabel(section, section.label))}</h3>
      ${_sectionStatusBadge(status)}
      <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-reset-section="${_esc(section.id)}" title="${_esc(t("settings.reset_section_title"))}">${_esc(t("common.reset"))}</button>
    </header>
    <div class="v5-settings-section-body">${fields}</div>
  </section>`;
}

/* === Bind events === */

function _bindContentEvents(container) {
  // Field changes
  container.querySelectorAll("[data-field-key]").forEach((fieldEl) => {
    const key = fieldEl.dataset.fieldKey;
    if (key.startsWith("__")) return;
    const field = _findFieldByKey(key);
    const livePreview = fieldEl.dataset.livePreview;

    const handler = () => {
      const v = _readField(field, fieldEl);
      _state.settings[key] = v;
      // Live preview (theme/animation/effects)
      _applyLivePreview(livePreview, v);
      // Range : MAJ label affiché
      if (field?.type === "range") {
        const label = container.querySelector(`[data-range-value-for="${key}"]`);
        if (label) label.textContent = String(v);
      }
      _scheduleSave();
    };

    if (field?.type === "toggle" || field?.type === "select") fieldEl.addEventListener("change", handler);
    else fieldEl.addEventListener("input", handler);
  });

  // Api-key show/hide
  container.querySelectorAll("[data-api-key-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.apiKeyToggle;
      const input = container.querySelector("#" + id);
      if (input) input.type = input.type === "password" ? "text" : "password";
    });
  });

  // V7-port : bouton Tester (boutons inline dans api-key)
  container.querySelectorAll("[data-test-method]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const method = btn.dataset.testMethod;
      const fieldKey = btn.dataset.testField;
      const field = _findFieldByKey(fieldKey);
      const resultEl = container.querySelector(`[data-test-result-for="${fieldKey}"]`);
      if (resultEl) { resultEl.textContent = t("common.testing"); resultEl.style.color = "var(--text-muted)"; }
      btn.disabled = true;
      try {
        // Resolution des params : $value → valeur courante du field, $autre_key → autre setting
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
        const msg = ok
          ? t("settings.rest_test_ok", { server: res.data?.server_name ? "— " + res.data.server_name : "" })
          : t("settings.rest_test_fail", { msg: res?.data?.message || res?.data?.error || t("common.failed") });
        if (resultEl) { resultEl.textContent = msg; resultEl.style.color = ok ? "var(--success)" : "var(--danger)"; }
      } catch (e) {
        if (resultEl) { resultEl.textContent = t("common.error_network"); resultEl.style.color = "var(--danger)"; }
      } finally {
        btn.disabled = false;
      }
    });
  });

  // V7-port : token REST (copy + regen)
  const tokenInput = container.querySelector('[data-field-key="rest_api_token"]');
  const msgEl = container.querySelector("[data-rest-token-msg]");
  const copyBtn = container.querySelector("[data-rest-token-copy]");
  const regenBtn = container.querySelector("[data-rest-token-regen]");
  if (copyBtn && tokenInput) {
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(tokenInput.value);
        if (msgEl) { msgEl.textContent = t("common.copied"); msgEl.style.color = "var(--success)"; setTimeout(() => msgEl.textContent = "", 2000); }
      } catch { if (msgEl) msgEl.textContent = t("common.copy_failed"); }
    });
  }
  if (regenBtn && tokenInput) {
    regenBtn.addEventListener("click", () => {
      if (!window.confirm(t("settings.rest_token_regen_confirm"))) return;
      const bytes = new Uint8Array(24);
      crypto.getRandomValues(bytes);
      const b64 = btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
      tokenInput.value = b64;
      tokenInput.type = "text";
      _state.settings.rest_api_token = b64;
      if (msgEl) { msgEl.textContent = t("settings.rest_token_regen_success"); msgEl.style.color = "var(--success)"; }
      _scheduleSave();
    });
  }

  // V7-port : bouton restart API
  container.querySelectorAll('[data-action="restart_api"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const resultEl = container.querySelector('[data-action-result-for="restart_api"]');
      btn.disabled = true;
      if (resultEl) { resultEl.textContent = t("settings.restart_in_progress"); resultEl.style.color = "var(--text-muted)"; }
      try {
        const res = await apiPost("settings/restart_api_server");
        const ok = !!(res?.data?.ok);
        if (resultEl) {
          resultEl.textContent = ok
            ? t("settings.restart_success")
            : t("settings.restart_fail", { msg: res?.data?.message || t("common.failed") });
          resultEl.style.color = ok ? "var(--success)" : "var(--danger)";
        }
        if (ok) { setTimeout(() => _loadQrDashboard(container), 1000); }
      } catch { if (resultEl) { resultEl.textContent = t("common.error_network"); resultEl.style.color = "var(--danger)"; } }
      finally { btn.disabled = false; }
    });
  });

  // Reload
  const reloadBtn = container.querySelector("[data-v5-settings-reload]");
  if (reloadBtn) {
    reloadBtn.addEventListener("click", async () => { await _loadSettings(); _refreshAll(); });
  }

  // Reset per section
  container.querySelectorAll("[data-reset-section]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const sectionId = btn.dataset.resetSection;
      const group = SETTINGS_GROUPS.find((g) => g.id === _state.activeCategory);
      const section = group?.sections.find((s) => s.id === sectionId);
      if (!section) return;
      if (!window.confirm(t("settings.reset_section_confirm", { label: _i18nLabel(section, section.label) }))) return;
      (section.fields || []).forEach((f) => {
        if (f.key.startsWith("__")) return;
        if (f.default !== undefined) _state.settings[f.key] = f.default;
        else if (f.type === "toggle") _state.settings[f.key] = false;
        else if (f.type === "number" || f.type === "range") _state.settings[f.key] = 0;
        else _state.settings[f.key] = "";
      });
      _scheduleSave();
      _refreshAll();
    });
  });

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

/* === Live preview (theme + apparence sliders) === */

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
  // Sliders apparence (effect_speed, glow_intensity, light_intensity)
  const root = document.documentElement;
  const map = (v, lo, hi) => lo + ((Number(v) || 0) / 100) * (hi - lo);
  if (kind === "effect_speed")    root.style.setProperty("--animation-speed", map(value, 0.3, 3));
  if (kind === "glow_intensity")  root.style.setProperty("--glow-intensity", map(value, 0, 0.5));
  if (kind === "light_intensity") {
    root.style.setProperty("--light-intensity", map(value, 0, 0.3));
    root.style.setProperty("--effect-opacity", map(value, 0, 0.08));
  }
}

/* === Save / Load === */

function _scheduleSave() {
  if (_state.saveTimer) clearTimeout(_state.saveTimer);
  _state.saveTimer = setTimeout(async () => {
    try {
      const res = await apiPost("settings/save_settings", { settings: _state.settings });
      if (res && res.data && (res.data.ok || res.data === true || !res.data.message)) {
        _state.savedAt = new Date();
        _updateSavedStateLabel();
      } else {
        // H5 fix : afficher l'erreur dans la barre top-right au lieu de console silent
        const errMsg = res?.data?.message || res?.error || "Erreur inconnue";
        console.error("[settings] save error:", errMsg);
        _updateSavedStateError(errMsg);
      }
    } catch (e) {
      // H5 fix : erreur reseau
      console.error("[settings] save exception:", e);
      _updateSavedStateError(t("settings.save_error_network"));
    }
  }, 500);
}

function _updateSavedStateError(msg) {
  const root = _state.containerRef;
  if (!root) return;
  const el = root.querySelector("[data-v5-saved-state]");
  if (!el) return;
  el.innerHTML = `<span style="color:var(--danger)">${escapeHtml(t("settings.save_error", { msg: String(msg).slice(0, 80) }))}</span>`;
}

function _updateSavedStateLabel() {
  const root = _state.containerRef;
  if (!root) return;
  const el = root.querySelector("[data-v5-saved-state]");
  if (!el) return;
  if (_state.savedAt) {
    const diff = Math.round((Date.now() - _state.savedAt.getTime()) / 1000);
    const when = diff < 5 ? t("settings.save_now") : t("settings.save_ago", { seconds: diff });
    el.innerHTML = `<span class="v5u-text-muted" style="color:var(--success)">${escapeHtml(t("settings.save_success", { when }))}</span>`;
  } else {
    el.innerHTML = "";
  }
}

async function _loadSettings() {
  const res = await apiPost("settings/get_settings");
  if (res && res.data && typeof res.data === "object") _state.settings = res.data;
}

/* === Refresh / Mount === */

function _refreshAll() {
  const root = _state.containerRef;
  if (!root) return;
  const sidebarHost = root.querySelector("[data-v5-settings-sidebar]");
  const contentHost = root.querySelector("[data-v5-settings-content]");
  if (sidebarHost) _renderSidebar(sidebarHost);
  if (contentHost) _renderContent(contentHost);
  _applyExpertMode(!!_state.settings.expert_mode);
}

function _renderActiveCategory() {
  const root = _state.containerRef;
  if (!root) return;
  const contentHost = root.querySelector("[data-v5-settings-content]");
  if (contentHost) _renderContent(contentHost);
  _applyExpertMode(!!_state.settings.expert_mode);
}

// V6-02 : observer i18n unique pour re-render quand la locale change.
let _localeUnsubscribe = null;

export async function initSettings(container, opts = {}) {
  if (!container) return;
  _state.containerRef = container;
  _state.activeCategory = opts.category || "sources";
  // V6-02 : abonnement re-render au changement de locale.
  if (_localeUnsubscribe) { try { _localeUnsubscribe(); } catch { /* noop */ } }
  _localeUnsubscribe = onLocaleChange(() => {
    if (_state.containerRef && _state.containerRef.isConnected) _refreshAll();
  });
  // V2-D (a11y) : annonce "chargement en cours" sur le conteneur ARIA-live.
  container.setAttribute("aria-busy", "true");
  try {
    await _loadSettings();
  } finally {
    container.setAttribute("aria-busy", "false");
  }
  const expertChecked = _state.settings.expert_mode ? "checked" : "";
  container.innerHTML = `
    <div class="v5-settings-expert-toggle" data-v5-expert-toggle>
      <label class="v5-toggle-label">
        <input type="checkbox" id="v5CkExpertMode" ${expertChecked} />
        <span>${t("settings.expert_mode.label_html")}</span>
      </label>
      <p class="v5-text-muted" style="font-size:var(--fs-xs);color:var(--text-muted)">${_esc(t("settings.expert_mode.hint"))}</p>
    </div>
    <div class="v5-settings-shell" style="display:flex;gap:var(--sp-4);align-items:flex-start">
      <aside data-v5-settings-sidebar style="flex:0 0 240px;position:sticky;top:0"></aside>
      <section data-v5-settings-content class="v5-settings-main" style="flex:1;min-width:0"></section>
    </div>
  `;
  _refreshAll();
  _applyExpertMode(!!_state.settings.expert_mode);
  // Initial apply pour les sliders apparence (preview live au premier rendu).
  _applyLivePreview("effect_speed", _state.settings.effect_speed);
  _applyLivePreview("glow_intensity", _state.settings.glow_intensity);
  _applyLivePreview("light_intensity", _state.settings.light_intensity);
  // Toggle Mode expert
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
  // V6-02 : cleanup observer i18n.
  if (_localeUnsubscribe) { try { _localeUnsubscribe(); } catch { /* noop */ } _localeUnsubscribe = null; }
}
