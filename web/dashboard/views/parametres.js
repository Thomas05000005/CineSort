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
 *   profils-qualite).
 * - Save debounce 500ms via settings/save_settings.
 * - Mode expert : toggle persiste en backend via settings.expert_mode.
 * - Recherche : highlight des labels + auto-switch vers la categorie qui
 *   contient le 1er match.
 * - Reset : modale custom + champ "CONFIRMER" + countdown si scope=all,
 *   appelle settings/reset_settings(scope) ou settings/reset_database().
 *
 * Endpoints :
 *   settings/get_settings, settings/save_settings           (existants)
 *   settings/reset_settings(scope), settings/reset_database (existants)
 *   settings/get_profiles, settings/save_profile, settings/set_active_profile
 *   settings/get_dashboard_qr, settings/get_server_info
 *   settings/restart_api_server
 *   integrations/test_<service>_connection                  (inline test buttons)
 *   quality/recompute_all_scores
 */

import { apiPost, invalidateSettingsCache } from "../core/api.js";
import { escapeHtml } from "../core/dom.js";
// Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplacer window.confirm()
// natifs par dangerConfirmModal (re-scoring bibliotheque + regen token = destructif).
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
      { id: "exclusions", label: "Exclusions", fields: [
        { key: "excluded_patterns", label: "Patterns d'exclusion (glob)", type: "multi-path",
          hint: "Un pattern par ligne (ex : *.tmp, _review/*, **/sample.*)", advanced: true },
        { key: "file_extensions", label: "Extensions vidéo acceptées", type: "text",
          placeholder: ".mkv;.mp4;.avi;.mov;.m4v;.wmv;.flv;.webm;.ts",
          hint: "Séparées par ; (toutes en minuscule, avec le point).", advanced: true },
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
        { key: "probe_backend", label: "Backend probe", type: "select", options: [
          {v:"auto",l:"Auto"},{v:"ffprobe",l:"ffprobe"},{v:"mediainfo",l:"mediainfo"},{v:"none",l:"Aucun"},
        ]},
        { key: "ffprobe_path", label: "Chemin ffprobe", type: "text", placeholder: "(auto-détecté si vide)",
          hint: "Laisser vide pour utiliser ffprobe du PATH système.", advanced: true },
        { key: "mediainfo_path", label: "Chemin mediainfo", type: "text", placeholder: "(auto-détecté si vide)",
          hint: "Laisser vide pour utiliser mediainfo du PATH système.", advanced: true },
        { key: "probe_timeout_s", label: "Timeout probe (s)", type: "number", min: 5, max: 300, advanced: true },
      ]},
      // VAGUE D : Section "Outils externes" — etat/version/path de ffprobe,
      // mediainfo (parametrables), fpcalc et LPIPS (bundled). Reutilise le
      // pattern OmdbStatus : panneau extra dans la section, refresh dedie
      // sans full re-render. Cf runtime/get_probe_tools_status.
      { id: "outils", label: "Outils externes", fields: [
        { key: "__probe_tools__", label: "", type: "probe-tools" },
      ]},
      { id: "perceptual", label: "Analyse perceptuelle", fields: [
        { key: "perceptual_enabled", label: "Activer l'analyse perceptuelle", type: "toggle" },
        { key: "perceptual_auto_on_scan", label: "Auto-lancer sur scan", type: "toggle" },
        { key: "perceptual_workers_count", label: "Workers parallèles (scan)", type: "number", min: 1, max: 16, default: 2,
          hint: "Nombre de films analysés en parallèle. Auto si parallélisme = Auto.", advanced: true },
        { key: "perceptual_frames_count", label: "Frames analysées par film", type: "number", min: 5, max: 30, advanced: true },
        { key: "perceptual_timeout_per_film_s", label: "Timeout par film (s)", type: "number", min: 30, max: 600, advanced: true },
        { key: "perceptual_audio_deep", label: "Audio analyse approfondie", type: "toggle", advanced: true },
        { key: "perceptual_lpips_enabled", label: "LPIPS ONNX (modèle deep learning)", type: "toggle", advanced: true },
      ]},
      { id: "subtitles", label: "Sous-titres", fields: [
        { key: "subtitle_detection_enabled", label: "Détection sous-titres externes", type: "toggle" },
        { key: "subtitle_lang_priority", label: "Priorité des langues", type: "text", placeholder: "fr;en;original",
          hint: "Séparées par ; (la première trouvée est la principale)." },
        { key: "subtitle_expected_languages", label: "Langues attendues", type: "text", placeholder: "fr;en", hint: "Séparées par ;", advanced: true },
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
        { key: "naming_template", label: "Template général", type: "text", placeholder: "{title} ({year})",
          hint: "Variables disponibles : {title} {year} {resolution} {codec} {audio} {source}.", advanced: true },
        { key: "naming_movie_template", label: "Template film", type: "text", placeholder: "{title} ({year})" },
        { key: "naming_tv_template", label: "Template série", type: "text", placeholder: "{series} ({year})" },
      ]},
      { id: "rules", label: "Règles", fields: [
        { key: "windows_safe", label: "Noms sûrs Windows (échappe < > : \" / \\ | ? *)", type: "toggle" },
        { key: "lowercase_extensions", label: "Extensions en minuscule (.mkv vs .MKV)", type: "toggle" },
        { key: "separator", label: "Séparateur entre éléments", type: "select", options: [
          {v:" ",l:"Espace (Inception 2010)"},
          {v:".",l:"Point (Inception.2010)"},
          {v:"_",l:"Underscore (Inception_2010)"},
          {v:"-",l:"Tiret (Inception-2010)"},
        ]},
      ]},
    ],
  },
  {
    id: "bibliotheque", label: "Bibliothèque", icon: "📚",
    sections: [
      { id: "organization", label: "Organisation", fields: [
        { key: "collection_folder_enabled", label: "Regrouper les sagas dans _Collection/", type: "toggle" },
        { key: "collection_folder", label: "Nom du dossier collections", type: "text", placeholder: "_Collection",
          hint: "Nom du sous-dossier où regrouper les films d'une même saga.", advanced: true },
        { key: "enable_tv_detection", label: "Détection séries TV", type: "toggle" },
      ]},
      { id: "cleanup", label: "Nettoyage", fields: [
        { key: "cleanup_orphans", label: "Nettoyer les fichiers orphelins (sous-titres, .nfo, images)", type: "toggle" },
        { key: "cleanup_empty_folders", label: "Supprimer les dossiers vides après apply", type: "toggle" },
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
          testMethod: "integrations/test_tmdb_key", testParams: { api_key: "$value", state_dir: "" },
          hint: "Gratuit sur themoviedb.org/settings/api. Indispensable pour identifier les films." },
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
        { key: "plex_url", label: "URL Plex", type: "text", placeholder: "http://plex.local:32400" },
        { key: "plex_token", label: "Token Plex", type: "api-key",
          testMethod: "integrations/test_plex_connection", testParams: { url: "$plex_url", token: "$value" } },
        { key: "plex_refresh_on_apply", label: "Refresh après apply", type: "toggle" },
      ]},
      { id: "radarr", label: "Radarr", fields: [
        { key: "radarr_enabled", label: "Activer", type: "toggle" },
        { key: "radarr_url", label: "URL Radarr", type: "text", placeholder: "http://radarr.local:7878" },
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
      { id: "desktop", label: "Notifications desktop", fields: [
        { key: "desktop_notifications_enabled", label: "Activer les notifications desktop", type: "toggle" },
        { key: "notifications_enabled", label: "Activer les notifications applicatives", type: "toggle" },
        { key: "notifications_scan_done", label: "Scan terminé", type: "toggle" },
        { key: "notifications_apply_done", label: "Apply terminé", type: "toggle" },
        { key: "notifications_undo_done", label: "Undo terminé", type: "toggle" },
        { key: "notifications_errors", label: "Erreurs critiques", type: "toggle" },
      ]},
      { id: "email", label: "Rapports email (SMTP)", fields: [
        { key: "email_enabled", label: "Activer", type: "toggle" },
        { key: "email_smtp_host", label: "SMTP host", type: "text", placeholder: "smtp.gmail.com", advanced: true },
        { key: "email_smtp_port", label: "SMTP port", type: "number", min: 1, max: 65535, advanced: true },
        { key: "email_smtp_user", label: "Utilisateur", type: "text", advanced: true },
        { key: "email_smtp_password", label: "Mot de passe", type: "api-key", advanced: true },
        { key: "email_smtp_tls", label: "STARTTLS", type: "toggle", advanced: true },
        { key: "email_to", label: "Destinataire", type: "text", placeholder: "vous@example.com" },
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
        { key: "rest_api_enabled", label: "Activer l'API REST", type: "toggle",
          hint: "Active le serveur HTTP pour accéder au dashboard depuis le LAN (téléphone, autre PC)." },
        { key: "rest_api_port", label: "Port", type: "number", min: 1024, max: 65535 },
        { key: "rest_api_token", label: "Clé d'accès (Bearer)", type: "api-key-rest",
          hint: "Token requis pour s'authentifier au dashboard distant. Régénérez si compromis." },
        { key: "__restart_api__", label: "", type: "action", action: "restart_api", buttonLabel: "🔄 Redémarrer le service API" },
        { key: "__qr_dashboard__", label: "QR code dashboard", type: "qr-dashboard" },
      ]},
      { id: "https", label: "HTTPS (optionnel)", fields: [
        { key: "rest_api_https_enabled", label: "Activer HTTPS", type: "toggle", advanced: true },
        { key: "rest_api_cert_path", label: "Chemin certificat", type: "text", placeholder: "C:\\certs\\cert.pem", advanced: true },
        { key: "rest_api_key_path", label: "Chemin clé privée", type: "text", placeholder: "C:\\certs\\key.pem", advanced: true },
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
        { key: "animations_enabled", label: "Activer les animations", type: "toggle",
          hint: "Décocher pour une interface 100% statique (utile sur PC bas de gamme).", advanced: true },
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
      // VO-A UI : Stockage SQLite — tri-etat (auto/local_ssd/nas_smb) + toggle
      // EXCLUSIVE qui doit OBLIGATOIREMENT passer par dangerConfirmModal avec
      // countdown 3s (memoire user actions dangereuses, P0 #233).
      { id: "stockage-sqlite", label: "Stockage SQLite", fields: [
        { key: "__advanced_pragma__", label: "", type: "advanced-pragma" },
      ]},
      { id: "parallelism", label: "Parallélisme", fields: [
        { key: "perceptual_parallelism_mode", label: "Mode parallélisme", type: "select", options: [
          {v:"auto",l:"Auto"},{v:"max",l:"Max"},{v:"safe",l:"Sécurisé"},{v:"serial",l:"Séquentiel"},
        ]},
        { key: "worker_count", label: "Nombre de workers globaux", type: "number", min: 1, max: 32, default: 4,
          hint: "Limite globale pour les opérations parallèles (scan, perceptual, apply).", advanced: true },
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
        { key: "auto_check_updates", label: "Vérification auto au démarrage", type: "toggle", advanced: true },
        { key: "update_github_repo", label: "Dépôt GitHub (owner/repo)", type: "text", placeholder: "user/cinesort",
          hint: "Vide = check désactivé", advanced: true },
        // Fix audit 2026-05-24 (v1.5.2) : Vague E — bouton manuel "Vérifier maintenant"
        // Force un appel reseau immediat via runtime/get_update_info (force_refresh=true),
        // affiche le resultat inline + boutons "Voir / Télécharger" si MAJ dispo.
        { key: "__check_updates_now__", label: "Vérification manuelle", type: "action",
          action: "check_updates_now", buttonLabel: "🔄 Vérifier maintenant",
          hint: "Force un appel à GitHub Releases pour détecter une nouvelle version." },
      ]},
      { id: "retention", label: "Rétention historique", fields: [
        { key: "history_retention_days", label: "Conserver l'historique (jours)", type: "number", min: 7, max: 365, default: 90,
          hint: "Au-delà, les runs sont purgés automatiquement.", advanced: true },
        { key: "retention_days", label: "Rétention scores et analyses (jours)", type: "number", min: 7, max: 730, default: 180,
          hint: "Durée de conservation des analyses perceptuelles et scores qualité.", advanced: true },
      ]},
      // Sprint orphelins #350 : RGPD Art.20 export portable (library/export_full_library).
      { id: "export-rgpd", label: "Export RGPD", fields: [
        { key: "__export_full_library__", label: "Export portable complet (JSON)", type: "action",
          action: "export_full_library", buttonLabel: "💾 Exporter toute la bibliothèque",
          hint: "RGPD Art. 20 : exporte films + décisions + scores + paramètres (anonymisés) dans un fichier JSON v1.0 téléchargé localement." },
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
  // Phase 6 (spec 11) : listener hashchange pour deep-link vers categorie/section.
  // Format supporte : #/parametres#<categorie> ou #/parametres#<categorie>-<section>
  // (ex: #/parametres#integrations-jellyfin ouvre Integrations + scroll jellyfin).
  hashChangeHandler: null,
  pendingScrollSection: null,
  // Phase 6 (spec 11 §OMDb) : dernier resultat du test OMDb pour piloter
  // l'affichage des 6 etats UI explicites (non-configure / config-pending /
  // ok / ko-401 / ko-429 / ko-reseau). Null = aucun test effectue cette session.
  // Forme : { ok, error_code, message, quota_remaining, quota_limit, ts }
  omdbLastTest: null,
  // VAGUE D : dernier snapshot retourne par runtime/get_probe_tools_status
  // ou recheck_probe_tools. Forme : { tools: { ffprobe, mediainfo, fpcalc,
  // lpips }, hybrid_ready, degraded_mode, installer, ... }. Null = pas encore
  // charge cette session (premier render = "Chargement..." puis fetch).
  probeToolsStatus: null,
  // VO-A UI : dernier payload retourne par settings/get_advanced_pragma_settings.
  // Forme : { profile_active, profile_override, available_profiles,
  // storage_detected, locking_mode_exclusive }. Null = pas encore charge.
  advancedPragmaState: null,
  advancedPragmaLoading: false,
  probeToolsLoading: false,
};

/**
 * Parse le fragment du hash courant (ex: "integrations-jellyfin") et retourne
 * { categoryId, sectionId } si la categorie existe. Le sectionId est optionnel.
 * Retourne null si aucun fragment ou categorie inconnue.
 *
 * Le hash format SPA est "#/parametres#integrations-jellyfin" donc fragment
 * = la partie apres le 2eme '#' (= split('#')[2]).
 */
function _parseHashFragment() {
  try {
    const raw = (typeof window !== "undefined" && window.location && window.location.hash) || "";
    if (!raw) return null;
    const parts = raw.split("#"); // ["", "/parametres", "integrations-jellyfin"]
    const fragment = parts.slice(2).join("#");
    if (!fragment) return null;
    // Match longest categoryId prefix (au cas ou un categoryId contiendrait un '-')
    const categories = PARAMETRES_GROUPS.map((g) => g.id);
    // Tri par longueur decroissante pour matcher "nommage" avant "n" hypothetique
    categories.sort((a, b) => b.length - a.length);
    for (const cat of categories) {
      if (fragment === cat) return { categoryId: cat, sectionId: null };
      if (fragment.startsWith(cat + "-")) {
        const sectionId = fragment.slice(cat.length + 1);
        return { categoryId: cat, sectionId: sectionId || null };
      }
    }
    return null;
  } catch (_e) {
    return null;
  }
}

/**
 * Applique le fragment d'URL : change la categorie active si necessaire et
 * memorise la section a faire scroller apres le prochain render.
 * Retourne true si quelque chose a change (categorie ou section).
 */
function _applyHashFragment() {
  const parsed = _parseHashFragment();
  if (!parsed) return false;
  let changed = false;
  if (parsed.categoryId !== _state.activeCategory) {
    _state.activeCategory = parsed.categoryId;
    _writeString(STORAGE_KEY_LAST_CATEGORY, parsed.categoryId);
    changed = true;
  }
  if (parsed.sectionId) {
    _state.pendingScrollSection = parsed.sectionId;
    changed = true;
  }
  return changed;
}

/**
 * Si une section est en attente de scroll (pendingScrollSection), la scroller
 * dans le viewport apres le render. No-op si la section n'existe pas.
 */
function _flushPendingScroll() {
  const sectionId = _state.pendingScrollSection;
  if (!sectionId || !_state.containerRef) return;
  _state.pendingScrollSection = null;
  // setTimeout pour laisser le DOM se peindre apres _refreshAll().
  setTimeout(() => {
    try {
      const target = _state.containerRef?.querySelector(`[data-section-id="${sectionId}"]`);
      if (target && typeof target.scrollIntoView === "function") {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } catch (_e) { /* noop */ }
  }, 80);
}

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
  if (!query || !group) return true;
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
 * 4) RENDERERS — FIELDS
 * ============================================================= */

/**
 * Calcule l'etat OMDb a partir des settings courants + dernier test.
 * 6 etats explicites (Spec 11 §OMDb) :
 *  - "non-configure"  : toggle OFF
 *  - "config-pending" : toggle ON + cle vide
 *  - "ok"             : test 200 (sample_title present)
 *  - "ko-401"         : test 401 / error_code=auth
 *  - "ko-429"         : test 429 / error_code=quota
 *  - "ko-reseau"      : timeout / network / inconnu
 * Sans test effectue (settings + cle presente), on retourne "config-pending"
 * (l'utilisateur doit cliquer "Tester" pour basculer vers ok/ko-*).
 */
function _computeOmdbState(settings, lastTest) {
  const enabled = !!settings.omdb_enabled;
  const key = String(settings.omdb_api_key || "").trim();
  if (!enabled) return "non-configure";
  if (!key) return "config-pending";
  if (!lastTest) return "config-pending";
  if (lastTest.ok) return "ok";
  switch (lastTest.error_code) {
    case "auth":    return "ko-401";
    case "quota":   return "ko-429";
    case "timeout":
    case "network": return "ko-reseau";
    default:        return "ko-reseau";
  }
}

/**
 * Rend le panneau de statut OMDb pour l'un des 6 etats.
 * @param {string} state - "non-configure" | "config-pending" | "ok" | "ko-401" | "ko-429" | "ko-reseau"
 * @param {object} data  - { quota_remaining, quota_limit, message } (optionnel)
 * @returns {string} HTML du panneau
 */
function _renderOmdbStatus(state, data) {
  const d = data || {};
  const used = (typeof d.quota_remaining === "number" && typeof d.quota_limit === "number")
    ? Math.max(0, d.quota_limit - d.quota_remaining)
    : null;
  const limit = (typeof d.quota_limit === "number") ? d.quota_limit : 1000;

  let cls = "parametres-omdb-status";
  let title = "";
  let detail = "";

  switch (state) {
    case "non-configure":
      cls += " parametres-omdb-status--off";
      title = "OMDb desactive.";
      detail = "Activer pour valider les matches TMDb douteux.";
      break;
    case "config-pending":
      cls += " parametres-omdb-status--pending";
      title = "Cle OMDb requise.";
      detail = "Renseignez votre cle OMDb (gratuit 1000/jour sur omdbapi.com).";
      break;
    case "ok":
      cls += " parametres-omdb-status--ok";
      title = (used !== null)
        ? `✓ Connecte (quota ${used}/${limit} utilise aujourd'hui)`
        : "✓ Connecte";
      detail = "Cross-check IMDb actif sur les matches a faible confiance.";
      break;
    case "ko-401":
      cls += " parametres-omdb-status--ko-auth";
      title = "❌ Cle invalide (401).";
      detail = "Verifiez votre cle sur omdbapi.com.";
      break;
    case "ko-429":
      cls += " parametres-omdb-status--ko-quota";
      title = "⚠ Quota depasse (429).";
      detail = "Reessayez demain.";
      break;
    case "ko-reseau":
    default:
      cls += " parametres-omdb-status--ko-net";
      title = "⚠ Reseau inaccessible.";
      detail = "Reessayez plus tard.";
      break;
  }

  return `<div class="${cls}" data-omdb-status data-omdb-state="${_esc(state)}" role="status" aria-live="polite">
    <span class="parametres-omdb-status-title">${_esc(title)}</span>
    <span class="parametres-omdb-status-detail">${_esc(detail)}</span>
  </div>`;
}

/**
 * Swap le panneau de statut OMDb in-place (pas de full re-render).
 * Appele apres un test reussi/echoue ou un changement de toggle/cle.
 */
function _refreshOmdbStatusPanel(container) {
  const host = container && container.querySelector('[data-section-id="omdb"] [data-omdb-status]');
  if (!host) return;
  const state = _computeOmdbState(_state.settings, _state.omdbLastTest);
  const html = _renderOmdbStatus(state, _state.omdbLastTest);
  // Remplacer le node entier (preserve la structure parent)
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  const next = tmp.firstElementChild;
  if (next) host.replaceWith(next);
}

/* =============================================================
 * 4-bis) RENDERERS — OUTILS EXTERNES (VAGUE D)
 * Pattern adapte de _renderOmdbStatus : table 4 lignes (ffprobe,
 * mediainfo, fpcalc, lpips) + boutons globaux (Recheck, Installer
 * auto, MAJ). Refresh in-place via _refreshProbeToolsPanel.
 * Endpoints :
 *   runtime/get_probe_tools_status  -> chargement initial (cache 90s)
 *   runtime/recheck_probe_tools     -> force recheck (boutton Tester)
 *   runtime/auto_install_probe_tools -> HTTP download winget-free
 *   runtime/update_probe_tools       -> winget upgrade
 * ============================================================= */

function _formatBundledSize(bytes) {
  const n = Number(bytes) || 0;
  if (n <= 0) return "";
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} Mo`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} Ko`;
  return `${n} o`;
}

/**
 * Rend une ligne du tableau outils. `info` = entree status.tools[key].
 * `kind` : "managed" (ffprobe/mediainfo : actions Tester+Reinstaller)
 *        | "bundled-exe" (fpcalc : Tester uniquement)
 *        | "bundled-asset" (LPIPS : pas d'action, juste affichage).
 */
function _renderProbeToolRow(toolKey, displayLabel, info, kind) {
  const i = info || {};
  // "found" est le flag VAGUE D ; on retombe sur "available" pour ffprobe/mediainfo.
  const found = (typeof i.found === "boolean") ? i.found : !!i.available;
  const compatible = (typeof i.compatible === "boolean") ? i.compatible : found;
  let statusHtml = "";
  if (!found) {
    statusHtml = `<span class="parametres-tool-status parametres-tool-status--ko">✗ Manquant</span>`;
  } else if (!compatible) {
    statusHtml = `<span class="parametres-tool-status parametres-tool-status--warn">⚠ Trop ancien</span>`;
  } else {
    statusHtml = `<span class="parametres-tool-status parametres-tool-status--ok">✓ Installé</span>`;
  }
  const version = i.version ? _esc(i.version) : (kind === "bundled-asset" ? "—" : "?");
  // Pour LPIPS : afficher taille au lieu de version.
  const versionCell = (kind === "bundled-asset" && found)
    ? _esc(_formatBundledSize(i.size_bytes) || "—")
    : version;
  const path = String(i.path || "").trim();
  const pathHtml = path
    ? `<code class="parametres-tool-path" title="${_esc(path)}">${_esc(path)}</code>`
    : `<span class="parametres-muted">—</span>`;
  let actionsHtml = "";
  if (kind === "managed") {
    actionsHtml = `
      <button type="button" class="v5-btn v5-btn--sm" data-probe-tool-action="test" data-probe-tool="${_esc(toolKey)}">Tester</button>
      <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-probe-tool-action="reinstall" data-probe-tool="${_esc(toolKey)}">Réinstaller</button>
    `;
  } else if (kind === "bundled-exe") {
    actionsHtml = `<span class="parametres-muted">(bundled)</span>`;
  } else {
    actionsHtml = `<span class="parametres-muted">(bundled)</span>`;
  }
  return `<tr class="parametres-tools-row" data-probe-tool-row="${_esc(toolKey)}">
    <td class="parametres-tools-cell parametres-tools-cell--label">${_esc(displayLabel)}</td>
    <td class="parametres-tools-cell parametres-tools-cell--status">${statusHtml}</td>
    <td class="parametres-tools-cell parametres-tools-cell--version">${versionCell}</td>
    <td class="parametres-tools-cell parametres-tools-cell--path">${pathHtml}</td>
    <td class="parametres-tools-cell parametres-tools-cell--actions">${actionsHtml}</td>
  </tr>`;
}

/**
 * VO-A UI : rend la section "Stockage SQLite" (tri-etat profil + toggle EXCLUSIVE).
 *
 * `state` = payload retourne par settings/get_advanced_pragma_settings :
 *   { profile_active, profile_override, available_profiles, storage_detected,
 *     locking_mode_exclusive }
 *
 * IMPORTANT : la bascule "Verrouillage EXCLUSIVE" est DANGEREUSE (empeche
 * toute lecture concurrente). Le handler attache (_attachAdvancedPragmaHandlers)
 * intercepte le change et ouvre dangerConfirmModal avec countdown 3s avant
 * de propager la modification au backend (memoire user actions dangereuses).
 */
function _renderAdvancedPragmaSection(state) {
  if (_state.advancedPragmaLoading) {
    return `<div class="parametres-muted">Chargement des paramètres de stockage…</div>`;
  }
  if (!state || typeof state !== "object") {
    return `<div class="parametres-muted">Statut non disponible. <button type="button" class="v5-btn v5-btn--sm" data-advanced-pragma-reload>Recharger</button></div>`;
  }

  const profiles = Array.isArray(state.available_profiles) ? state.available_profiles : [];
  const override = String(state.profile_override || "auto");
  const active = String(state.profile_active || "auto");
  const detected = String(state.storage_detected || "local_ssd");
  const exclusive = !!state.locking_mode_exclusive;

  const detectedLabel = detected === "nas_smb"
    ? "NAS / SMB"
    : "SSD local";

  const profileOptions = profiles.length > 0
    ? profiles.map((p) =>
        `<option value="${escapeHtml(String(p.v))}" ${String(p.v) === override ? "selected" : ""}>${escapeHtml(String(p.l))}</option>`,
      ).join("")
    : `<option value="auto" selected>Auto (détection)</option>
       <option value="local_ssd">SSD local (perf max)</option>
       <option value="nas_smb">NAS / SMB (sécurisé)</option>`;

  const activeBadge = active === "nas_smb"
    ? `<span class="parametres-tools-mode parametres-tools-mode--warn">Actif : NAS / SMB</span>`
    : `<span class="parametres-tools-mode parametres-tools-mode--ok">Actif : SSD local</span>`;

  const exclusiveBadge = exclusive
    ? `<span class="parametres-tools-mode parametres-tools-mode--warn">⚠ Verrouillage EXCLUSIVE activé</span>`
    : "";

  return `<div class="parametres-advanced-pragma">
    <p class="parametres-section-intro">
      Profil SQLite adapté au stockage de la base. <strong>Auto</strong> détecte
      automatiquement (stockage détecté : <em>${escapeHtml(detectedLabel)}</em>).
    </p>
    <div class="parametres-field">
      <label class="parametres-field-label" for="parametres-storage-profile">Profil de stockage</label>
      <select id="parametres-storage-profile" class="parametres-select" data-advanced-pragma-profile>
        ${profileOptions}
      </select>
      <span class="parametres-field-hint">${activeBadge}</span>
    </div>
    <label class="parametres-field parametres-field--toggle">
      <input type="checkbox" class="parametres-checkbox"
             data-advanced-pragma-exclusive
             ${exclusive ? "checked" : ""}
             aria-describedby="parametres-exclusive-hint">
      <span class="parametres-field-label">Verrouillage EXCLUSIVE (lectures exclusives)</span>
      <span id="parametres-exclusive-hint" class="parametres-field-hint">
        Mode dangereux : aucun autre processus ne peut lire la base en parallèle.
        Une confirmation supplémentaire est requise. ${exclusiveBadge}
      </span>
    </label>
    <p class="parametres-advanced-pragma-message parametres-muted" data-advanced-pragma-message></p>
  </div>`;
}

/**
 * Rend la table complete des outils externes. `status` = payload retourne
 * par runtime/get_probe_tools_status. Si null/loading, on affiche un placeholder.
 */
function _renderProbeToolsTable(status) {
  if (_state.probeToolsLoading) {
    return `<div class="parametres-tools-loading parametres-muted">Vérification des outils externes…</div>`;
  }
  if (!status || typeof status !== "object") {
    return `<div class="parametres-tools-loading parametres-muted">Statut non disponible. Cliquez sur « Tester » pour vérifier.</div>`;
  }
  const tools = (status.tools && typeof status.tools === "object") ? status.tools : {};
  const rows = [
    _renderProbeToolRow("ffprobe", "ffprobe", tools.ffprobe, "managed"),
    _renderProbeToolRow("mediainfo", "MediaInfo", tools.mediainfo, "managed"),
    _renderProbeToolRow("fpcalc", "fpcalc (Chromaprint)", tools.fpcalc, "bundled-exe"),
    _renderProbeToolRow("lpips", "LPIPS (modèle ONNX)", tools.lpips, "bundled-asset"),
  ].join("");
  const mode = String(status.degraded_mode || "");
  const modeBadge = mode === "hybrid"
    ? `<span class="parametres-tools-mode parametres-tools-mode--ok">Mode hybride (ffprobe + MediaInfo)</span>`
    : mode === "partial"
      ? `<span class="parametres-tools-mode parametres-tools-mode--warn">Mode dégradé (un seul outil disponible)</span>`
      : mode === "disabled"
        ? `<span class="parametres-tools-mode parametres-tools-mode--muted">Probe désactivée</span>`
        : `<span class="parametres-tools-mode parametres-tools-mode--ko">Aucun outil probe disponible</span>`;
  return `<div class="parametres-tools-panel">
    ${modeBadge}
    <table class="parametres-tools-table" data-probe-tools-table>
      <thead>
        <tr>
          <th>Outil</th><th>Statut</th><th>Version</th><th>Chemin</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="parametres-tools-actions">
      <button type="button" class="v5-btn v5-btn--sm" data-probe-tools-action="recheck">↻ Recheck (force)</button>
      <button type="button" class="v5-btn v5-btn--sm v5-btn--primary" data-probe-tools-action="auto_install">⬇ Installer auto (ffprobe + MediaInfo)</button>
      <button type="button" class="v5-btn v5-btn--sm" data-probe-tools-action="update">⇧ Mettre à jour (winget)</button>
    </div>
    <p class="parametres-tools-message" data-probe-tools-message></p>
  </div>`;
}

/**
 * Swap in-place le panneau outils (sans full re-render de la categorie).
 * Reutilise le pattern _refreshOmdbStatusPanel.
 */
function _refreshProbeToolsPanel(container) {
  const host = container && container.querySelector('[data-section-id="outils"] .parametres-section-body');
  if (!host) return;
  // On cible le wrapper qui contient soit le placeholder loading, soit la table.
  const fieldWrapper = host.querySelector(".parametres-field--probe-tools");
  if (!fieldWrapper) return;
  const html = `<div class="parametres-field parametres-field--probe-tools">${_renderProbeToolsTable(_state.probeToolsStatus)}</div>`;
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  const next = tmp.firstElementChild;
  if (next) {
    fieldWrapper.replaceWith(next);
    _bindProbeToolsActions(container);
  }
}

function _setProbeToolsMessage(container, msg, level) {
  const el = container && container.querySelector("[data-probe-tools-message]");
  if (!el) return;
  el.textContent = msg || "";
  el.className = "parametres-tools-message";
  if (level === "error") el.classList.add("parametres-tools-message--error");
  else if (level === "ok") el.classList.add("parametres-tools-message--ok");
  else if (level === "info") el.classList.add("parametres-tools-message--info");
}

/**
 * Charge le statut initial (cache 90s cote backend, donc tres rapide).
 * Appele apres le premier render de la categorie "analyse".
 */
async function _loadProbeToolsStatus(container, { force } = { force: false }) {
  _state.probeToolsLoading = true;
  _refreshProbeToolsPanel(container);
  try {
    const method = force ? "runtime/recheck_probe_tools" : "runtime/get_probe_tools_status";
    const res = await apiPost(method, {});
    const data = res && res.data ? res.data : res;
    if (data && data.ok) {
      _state.probeToolsStatus = data;
    } else {
      _state.probeToolsStatus = null;
      _setProbeToolsMessage(container, `Erreur : ${data?.message || "statut indisponible"}`, "error");
    }
  } catch (err) {
    _state.probeToolsStatus = null;
    _setProbeToolsMessage(container, `Erreur réseau : ${err?.message || err}`, "error");
  } finally {
    _state.probeToolsLoading = false;
    _refreshProbeToolsPanel(container);
  }
}

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

    case "action": {
      // Sprint orphelins #350 : si la field declare label/hint, on les rend pour
      // contextualiser l'action (utile pour export_full_library). Si seulement
      // buttonLabel est present (cas restart_api existant), comportement
      // historique inchange.
      const hasContext = !!(field.label || field.hint);
      const labelBlock = field.label
        ? `<label class="parametres-field-label">${labelHtml}</label>`
        : "";
      const hintBlock = hasContext && field.hint
        ? `<span class="parametres-field-hint">${_esc(field.hint)}</span>`
        : "";
      return `<div class="parametres-field"${advAttr}>
        ${labelBlock}
        <button type="button" class="v5-btn" data-action="${_esc(field.action)}">${_esc(field.buttonLabel || "Action")}</button>
        <span class="parametres-test-result" data-action-result-for="${_esc(field.action)}"></span>
        ${hintBlock}
      </div>`;
    }

    case "qr-dashboard":
      return `<div class="parametres-field parametres-field--qr"${advAttr}>
        <label class="parametres-field-label">${labelHtml}</label>
        <div data-qr-dashboard class="parametres-qr-host">
          <span class="parametres-muted">Chargement du QR code…</span>
        </div>
      </div>`;

    case "profils-qualite":
      return _renderProfilsQualite();

    case "probe-tools":
      // VAGUE D : tableau des outils externes (ffprobe, mediainfo, fpcalc, LPIPS).
      // Le contenu reel est rendu apres apiPost("runtime/get_probe_tools_status").
      return `<div class="parametres-field parametres-field--probe-tools">${_renderProbeToolsTable(_state.probeToolsStatus)}</div>`;

    case "advanced-pragma":
      // VO-A UI : section "Stockage SQLite" tri-etat + toggle EXCLUSIVE.
      // Le contenu reel est rendu apres settings/get_advanced_pragma_settings.
      return `<div class="parametres-field parametres-field--advanced-pragma" data-advanced-pragma-host>${_renderAdvancedPragmaSection(_state.advancedPragmaState)}</div>`;

    default:
      return `<div class="parametres-field">[type ${_esc(field.type)} non supporté pour « ${_esc(field.label)} »]</div>`;
  }
}

/* =============================================================
 * 5) RENDERERS — PROFILS QUALITE (categorie 2.9)
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

function _renderCategoryPanel(categoryId) {
  const group = PARAMETRES_GROUPS.find((c) => c.id === categoryId) || PARAMETRES_GROUPS[0];
  const visibleSections = (group.sections || []).filter((s) => _sectionMatches(_state.searchQuery, s));

  if (visibleSections.length === 0) {
    return `<section class="parametres-panel" aria-labelledby="parametres-panel-title">
      <h2 id="parametres-panel-title" class="parametres-panel-title">
        <span class="parametres-panel-icon" aria-hidden="true">${group.icon}</span>
        ${_esc(group.label)}
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
    // Phase 6 (spec 11 §OMDb) : panneau de statut 6 etats au-dessus des champs OMDb
    const extraTop = (section.id === "omdb")
      ? _renderOmdbStatus(_computeOmdbState(_state.settings, _state.omdbLastTest), _state.omdbLastTest)
      : "";
    return `<section class="parametres-section" data-section-id="${_esc(section.id)}">
      <header class="parametres-section-header">
        <h3 class="parametres-section-title">${_highlightLabel(section.label, _state.searchQuery)}</h3>
        ${badge}
      </header>
      <div class="parametres-section-body">${extraTop}${fields}</div>
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
 * 7) PROFILS QUALITE — LOAD / SAVE / RECOMPUTE
 * ============================================================= */

async function _loadProfiles() {
  try {
    const res = await apiPost("settings/get_profiles", {});
    if (res && res.data && (res.data.ok || Array.isArray(res.data.profiles))) {
      _state.profilesList = res.data.profiles || [];
      _state.activeProfileId = res.data.active_profile_id || "";
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
      }
    }
  } catch (_e) {
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
  // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace window.confirm()
  // natif par dangerConfirmModal (ecrasement des scores de toute la biblio = destructif).
  // Memoire utilisateur exige modale custom + confirm supplementaire.
  dangerConfirmModal({
    title: "Re-calculer les scores avec ce profil ?",
    consequence: "Cette opération va re-scorer l'ensemble des films de votre bibliothèque (~5-10 min). Les scores existants seront écrasés.",
    countdownSeconds: 3,
    confirmLabel: "Lancer le re-calcul",
    cancelLabel: "Annuler",
    onConfirm: async () => {
      _showProfilMessage("Re-calcul en cours… (voir vue Qualité)", "info");
      try {
        const res = await apiPost("quality/recompute_all_scores", {});
        if (res && res.data && res.data.ok) {
          _showProfilMessage(`✓ Re-calcul lancé : job_id = ${res.data.job_id || "?"}.`, "ok");
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
  } catch (_e) { /* noop */ }
  if (!url) {
    try {
      const si = await apiPost("settings/get_server_info");
      if (si?.data?.ok) url = si.data.dashboard_url || "";
    } catch (_e) { /* noop */ }
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
      } catch (_e) { /* noop */ }
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
 * 11) RESET MODAL (12 scopes + CONFIRMER + countdown)
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
      try { prev.focus(); } catch (_e) { /* noop */ }
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
          ? "⚠ TRES DANGEREUX : cela supprime TOUS les films, runs, scores et analyses de la base. Action TOTALEMENT irréversible côté DB (backup auto cependant)."
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
        await _loadSettings();
        await _loadProfiles();
        _refreshAll();
        const backupPath = res.data.backup_path || "";
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
  setTimeout(() => { try { input.focus(); } catch (_e) { /* noop */ } }, 50);
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
      // Phase 6 (spec 11 §OMDb) : si la cle ou le toggle change, on invalide
      // le dernier resultat et on refresh le panneau de statut.
      if (key === "omdb_enabled" || key === "omdb_api_key") {
        _state.omdbLastTest = null;
        _refreshOmdbStatusPanel(container);
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

  // Test buttons (TMDb, Jellyfin, Plex, Radarr, OMDb)
  container.querySelectorAll("[data-test-method]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const method = btn.dataset.testMethod;
      const fieldKey = btn.dataset.testField;
      const field = _findFieldByKey(fieldKey);
      const isOmdb = (fieldKey === "omdb_api_key");
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
        const payload = res?.data || {};
        const ok = !!payload.ok;
        // Phase 6 (spec 11 §OMDb) : pour OMDb on stocke le statut riche
        // (error_code 401/429/network/timeout + quota_remaining/limit) et
        // on rafraichit le panneau d'etat plutot que la pastille inline.
        if (isOmdb) {
          _state.omdbLastTest = {
            ok,
            error_code: payload.error_code || (ok ? null : "network"),
            message: payload.message || payload.error || "",
            quota_remaining: payload.quota_remaining ?? null,
            quota_limit: payload.quota_limit ?? null,
            quota_reset_at: payload.quota_reset_at ?? null,
            ts: Date.now(),
          };
          _refreshOmdbStatusPanel(container);
          if (resultEl) { resultEl.textContent = ""; resultEl.className = "parametres-test-result"; }
        } else if (resultEl) {
          resultEl.textContent = ok ? "✓ Connexion réussie" : `✗ Échec : ${payload.message || payload.error || "inconnu"}`;
          resultEl.className = `parametres-test-result parametres-test-result--${ok ? "ok" : "error"}`;
        }
      } catch (err) {
        if (isOmdb) {
          _state.omdbLastTest = {
            ok: false,
            error_code: "network",
            message: String(err?.message || err || "Erreur reseau"),
            quota_remaining: null,
            quota_limit: null,
            quota_reset_at: null,
            ts: Date.now(),
          };
          _refreshOmdbStatusPanel(container);
          if (resultEl) { resultEl.textContent = ""; resultEl.className = "parametres-test-result"; }
        } else if (resultEl) {
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
      } catch (_e) { if (msgEl) msgEl.textContent = "Échec copie"; }
    });
  }
  if (regenBtn && tokenInput) {
    regenBtn.addEventListener("click", () => {
      // Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplace window.confirm()
      // natif par dangerConfirmModal (regen token = invalide tous les clients distants).
      dangerConfirmModal({
        title: "Régénérer le token API ?",
        consequence: "Les clients distants (mobile, navigateur autre poste) devront utiliser la nouvelle clé. Les connexions en cours seront perdues.",
        confirmLabel: "Régénérer",
        cancelLabel: "Annuler",
        onConfirm: () => {
          const bytes = new Uint8Array(24);
          crypto.getRandomValues(bytes);
          const b64 = btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
          tokenInput.value = b64;
          tokenInput.type = "text";
          _state.settings.rest_api_token = b64;
          if (msgEl) { msgEl.textContent = "✓ Nouveau token"; msgEl.className = "parametres-test-result parametres-test-result--ok"; }
          _scheduleSave();
        },
      });
    });
  }

  // Sprint orphelins #350 : Export RGPD complet de la bibliotheque.
  // Cf cinesort.ui.api.export_support.export_full_library + docs/EXPORT_FORMAT.md.
  container.querySelectorAll('[data-action="export_full_library"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const resultEl = container.querySelector('[data-action-result-for="export_full_library"]');
      btn.disabled = true;
      if (resultEl) { resultEl.textContent = "Export en cours…"; resultEl.className = "parametres-test-result parametres-test-result--info"; }
      try {
        const res = await apiPost("library/export_full_library", {});
        const data = res && res.data ? res.data : res;
        if (!data || data.ok === false) {
          throw new Error((data && (data.message || data.error)) || "Echec export.");
        }
        // Le backend renvoie le payload JSON complet sous "export" (ou data directement).
        // On serialise et declenche le download cote browser pour rester local.
        const payload = data.export || data.payload || data;
        const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
        a.href = url;
        a.download = `cinesort-export-${ts}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 2000);
        if (resultEl) {
          const sz = blob.size > 1024 * 1024 ? `${(blob.size / 1024 / 1024).toFixed(1)} Mo` : `${(blob.size / 1024).toFixed(0)} Ko`;
          resultEl.textContent = `✓ Téléchargé (${sz})`;
          resultEl.className = "parametres-test-result parametres-test-result--ok";
        }
      } catch (err) {
        if (resultEl) { resultEl.textContent = `✗ Erreur : ${err?.message || err}`; resultEl.className = "parametres-test-result parametres-test-result--error"; }
      } finally {
        btn.disabled = false;
      }
    });
  });

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

  // Fix audit 2026-05-24 (v1.5.2) : Vague E — bouton manuel "Vérifier maintenant"
  // Force un check via runtime/get_update_info {force_refresh: true} (le backend
  // delegue a check_for_updates). En cas de MAJ disponible, on affiche le numero
  // de version et deux boutons "Voir sur GitHub" + "Telecharger" qui ouvrent
  // l'URL en externe via runtime/open_external_url (WebView2 sans handler bloque
  // target="_blank" et window.open silencieusement).
  container.querySelectorAll('[data-action="check_updates_now"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const resultEl = container.querySelector('[data-action-result-for="check_updates_now"]');
      btn.disabled = true;
      if (resultEl) {
        resultEl.innerHTML = "";
        resultEl.textContent = "Vérification…";
        resultEl.className = "parametres-test-result parametres-test-result--info";
      }
      try {
        const res = await apiPost("runtime/get_update_info", { force_refresh: true });
        // Fix audit 2026-05-25 (v1.5.3) Vague F : payload imbrique dans res.data
        const _payload = (res && res.data) || res || {};
        const ok = !!(_payload.ok !== false);
        const data = _payload;
        if (!ok) {
          if (resultEl) {
            // Fix audit 2026-05-25 (v1.5.3) Vague F : payload imbrique dans res.data
            resultEl.textContent = `✗ ${_payload?.message || res?.error || "Echec du check"}`;
            resultEl.className = "parametres-test-result parametres-test-result--error";
          }
          return;
        }
        if (data.update_available && data.latest_version) {
          // Nouvelle version disponible : afficher version + boutons Voir / Télécharger.
          if (resultEl) {
            const versionTxt = _esc(String(data.latest_version));
            const releaseUrl = data.release_url ? String(data.release_url) : "";
            const downloadUrl = data.download_url ? String(data.download_url) : releaseUrl;
            const viewBtn = releaseUrl
              ? `<button type="button" class="v5-btn v5-btn--sm" data-update-open-url="${_esc(releaseUrl)}">Voir sur GitHub</button>`
              : "";
            const dlBtn = downloadUrl
              ? `<button type="button" class="v5-btn v5-btn--sm v5-btn--primary" data-update-open-url="${_esc(downloadUrl)}">Télécharger</button>`
              : "";
            resultEl.innerHTML = `<span class="parametres-update-banner">⬆ Nouvelle version disponible : v${versionTxt}</span> ${viewBtn} ${dlBtn}`;
            resultEl.className = "parametres-test-result parametres-test-result--ok";
            // Bind click sur les boutons "Voir" / "Télécharger" -> ouvre URL externe via runtime.
            resultEl.querySelectorAll("[data-update-open-url]").forEach((b) => {
              b.addEventListener("click", async () => {
                const u = b.getAttribute("data-update-open-url") || "";
                if (!u) return;
                try { await apiPost("runtime/open_external_url", { url: u }); } catch { /* silencieux */ }
              });
            });
          }
        } else {
          if (resultEl) {
            resultEl.textContent = `✓ À jour (v${_esc(String(data.current_version || ""))})`;
            resultEl.className = "parametres-test-result parametres-test-result--ok";
          }
        }
      } catch (err) {
        if (resultEl) {
          resultEl.textContent = `✗ Erreur : ${err?.message || err}`;
          resultEl.className = "parametres-test-result parametres-test-result--error";
        }
      } finally {
        btn.disabled = false;
      }
    });
  });

  // Profils Qualité
  _bindProfilsQualite(container);

  // VAGUE D : Outils externes (ffprobe/mediainfo/fpcalc/LPIPS)
  _bindProbeToolsActions(container);
  // Auto-load au premier rendu de la section "outils" (categorie analyse).
  if (container.querySelector('[data-section-id="outils"]') && _state.probeToolsStatus === null && !_state.probeToolsLoading) {
    _loadProbeToolsStatus(container, { force: false });
  }

  // VO-A UI : Stockage SQLite (tri-etat profil + toggle EXCLUSIVE)
  _bindAdvancedPragmaActions(container);
  // Auto-load au premier rendu si la section "stockage-sqlite" est presente
  if (container.querySelector("[data-advanced-pragma-host]") && _state.advancedPragmaState === null && !_state.advancedPragmaLoading) {
    _loadAdvancedPragmaState(container);
  }

  // QR dashboard auto-load
  if (container.querySelector("[data-qr-dashboard]")) {
    _loadQrDashboard(container);
  }
}

/**
 * VO-A UI : refresh le panneau "Stockage SQLite" sans full re-render.
 * Re-attache les handlers (idempotent via data-bound).
 */
function _refreshAdvancedPragmaPanel(container) {
  const host = container.querySelector("[data-advanced-pragma-host]");
  if (!host) return;
  host.innerHTML = _renderAdvancedPragmaSection(_state.advancedPragmaState);
  _bindAdvancedPragmaActions(container);
}

/**
 * VO-A UI : charge l'etat initial via settings/get_advanced_pragma_settings.
 */
async function _loadAdvancedPragmaState(container) {
  _state.advancedPragmaLoading = true;
  _refreshAdvancedPragmaPanel(container);
  try {
    const res = await apiPost("settings/get_advanced_pragma_settings", {});
    const data = res && res.data ? res.data : res;
    if (data && data.ok) {
      _state.advancedPragmaState = data;
    } else {
      _state.advancedPragmaState = null;
    }
  } catch (err) {
    _state.advancedPragmaState = null;
  } finally {
    _state.advancedPragmaLoading = false;
    _refreshAdvancedPragmaPanel(container);
  }
}

/**
 * VO-A UI : applique le profil + locking_mode via settings/set_advanced_pragma_settings.
 * Met a jour _state.advancedPragmaState avec la reponse et refresh.
 */
async function _applyAdvancedPragma(container, profileName, lockingExclusive, msgEl) {
  if (msgEl) msgEl.textContent = "Application en cours…";
  try {
    const res = await apiPost("settings/set_advanced_pragma_settings", {
      profile_name: String(profileName || "auto"),
      locking_mode_exclusive: !!lockingExclusive,
    });
    const data = res && res.data ? res.data : res;
    if (data && data.ok) {
      _state.advancedPragmaState = {
        ...(_state.advancedPragmaState || {}),
        profile_active: data.profile_active,
        profile_override: data.profile_override,
        storage_detected: data.storage_detected || _state.advancedPragmaState?.storage_detected,
        locking_mode_exclusive: !!data.locking_mode_exclusive,
        available_profiles: _state.advancedPragmaState?.available_profiles || [],
      };
      _refreshAdvancedPragmaPanel(container);
      const newMsg = container.querySelector("[data-advanced-pragma-message]");
      if (newMsg) newMsg.textContent = "✓ Paramètres de stockage enregistrés.";
      return true;
    }
    if (msgEl) msgEl.textContent = `Erreur : ${data?.message || "échec de l'enregistrement"}`;
    return false;
  } catch (err) {
    if (msgEl) msgEl.textContent = `Erreur réseau : ${err?.message || err}`;
    return false;
  }
}

/**
 * VO-A UI : bind des handlers select profil + toggle EXCLUSIVE.
 *
 * Le toggle EXCLUSIVE est DANGEREUX (memoire user actions dangereuses) :
 *   - JAMAIS window.confirm/prompt/alert
 *   - dangerConfirmModal avec countdown 3s OBLIGATOIRE
 *   - Cancel = checkbox revient a son etat initial (pas de changement)
 */
function _bindAdvancedPragmaActions(container) {
  // Bouton "Recharger" si state null
  const reloadBtn = container.querySelector("[data-advanced-pragma-reload]");
  if (reloadBtn && reloadBtn.dataset.bound !== "1") {
    reloadBtn.dataset.bound = "1";
    reloadBtn.addEventListener("click", () => _loadAdvancedPragmaState(container));
  }

  // Select profil — applique direct (pas dangereux)
  const profileSelect = container.querySelector("[data-advanced-pragma-profile]");
  if (profileSelect && profileSelect.dataset.bound !== "1") {
    profileSelect.dataset.bound = "1";
    profileSelect.addEventListener("change", async () => {
      const msg = container.querySelector("[data-advanced-pragma-message]");
      const currentExclusive = !!(_state.advancedPragmaState && _state.advancedPragmaState.locking_mode_exclusive);
      await _applyAdvancedPragma(container, profileSelect.value, currentExclusive, msg);
    });
  }

  // Toggle EXCLUSIVE — DANGEREUX : dangerConfirmModal + countdown 3s
  const exclusiveToggle = container.querySelector("[data-advanced-pragma-exclusive]");
  if (exclusiveToggle && exclusiveToggle.dataset.bound !== "1") {
    exclusiveToggle.dataset.bound = "1";
    exclusiveToggle.addEventListener("change", () => {
      const target = !!exclusiveToggle.checked;
      const previous = !target; // on connait l'ancien etat
      const msg = container.querySelector("[data-advanced-pragma-message]");
      const currentProfile = _state.advancedPragmaState?.profile_override || "auto";

      if (!target) {
        // Desactivation : pas de confirmation (revenir a un mode safe)
        _applyAdvancedPragma(container, currentProfile, false, msg);
        return;
      }

      // Activation EXCLUSIVE : modale obligatoire avec countdown 3s
      // Memoire feedback_cinesort_actions_dangereuses : JAMAIS window.confirm.
      dangerConfirmModal({
        title: "Verrouillage exclusif de la base de données",
        consequence: "Mode EXCLUSIVE : aucun autre processus (UI distant, CLI, plugin) ne pourra lire la base de données en parallèle. À utiliser uniquement si vous êtes seul·e à utiliser CineSort sur cette machine.",
        items: [
          "Aucun autre processus ne peut lire la DB en parallèle",
          "Les clients REST distants seront refusés tant que ce mode est actif",
          "Désactivable à tout moment depuis ce même écran",
        ],
        countdownSeconds: 3,
        confirmLabel: "Activer EXCLUSIVE",
        cancelLabel: "Annuler",
        onConfirm: async () => {
          await _applyAdvancedPragma(container, currentProfile, true, msg);
        },
      });

      // Reset visuel immediat : si l'utilisateur annule, l'etat de la checkbox
      // doit refleter l'ancien etat. _applyAdvancedPragma fera un refresh
      // complet en cas de succes ; en cas d'annulation, on remet manuellement.
      // On revert tout de suite puis on laisse onConfirm faire le refresh si
      // confirme (le refresh re-rend la section avec la bonne valeur).
      setTimeout(() => {
        const stillActive = !!(_state.advancedPragmaState && _state.advancedPragmaState.locking_mode_exclusive);
        if (!stillActive && exclusiveToggle.isConnected) {
          exclusiveToggle.checked = previous;
        }
      }, 100);
    });
  }
}

/**
 * Bind des boutons globaux + par ligne du tableau outils externes.
 * Idempotent (peut etre appele plusieurs fois apres un refresh).
 */
function _bindProbeToolsActions(container) {
  // Boutons globaux (recheck / auto_install / update)
  container.querySelectorAll("[data-probe-tools-action]").forEach((btn) => {
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", async () => {
      const action = btn.dataset.probeToolsAction;
      const all = container.querySelectorAll("[data-probe-tools-action], [data-probe-tool-action]");
      all.forEach((b) => { b.disabled = true; });
      try {
        if (action === "recheck") {
          _setProbeToolsMessage(container, "Recheck en cours…", "info");
          await _loadProbeToolsStatus(container, { force: true });
          _setProbeToolsMessage(container, "✓ Statut rafraîchi.", "ok");
        } else if (action === "auto_install") {
          _setProbeToolsMessage(container, "Installation auto en cours… (téléchargement HTTP, ~30-60s)", "info");
          const res = await apiPost("runtime/auto_install_probe_tools", {});
          const data = res && res.data ? res.data : res;
          if (data && data.ok) {
            _setProbeToolsMessage(container, "✓ Installation terminée.", "ok");
          } else {
            const errs = Array.isArray(data?.errors) ? data.errors.join(" ; ") : "";
            _setProbeToolsMessage(container, `Erreur : ${data?.message || "installation impossible"}${errs ? ` (${errs})` : ""}`, "error");
          }
          if (data && data.status) {
            _state.probeToolsStatus = { ok: true, ...data.status };
            _refreshProbeToolsPanel(container);
          } else {
            await _loadProbeToolsStatus(container, { force: true });
          }
        } else if (action === "update") {
          _setProbeToolsMessage(container, "Mise à jour winget en cours…", "info");
          const res = await apiPost("runtime/update_probe_tools", {});
          const data = res && res.data ? res.data : res;
          if (data && data.ok) {
            _setProbeToolsMessage(container, "✓ Mise à jour réussie.", "ok");
          } else {
            _setProbeToolsMessage(container, `Erreur : ${data?.message || "MAJ impossible"}`, "error");
          }
          if (data && data.status) {
            _state.probeToolsStatus = { ok: true, ...data.status };
            _refreshProbeToolsPanel(container);
          }
        }
      } catch (err) {
        _setProbeToolsMessage(container, `Erreur réseau : ${err?.message || err}`, "error");
      } finally {
        const all2 = container.querySelectorAll("[data-probe-tools-action], [data-probe-tool-action]");
        all2.forEach((b) => { b.disabled = false; });
      }
    });
  });

  // Boutons par ligne (test / reinstall ; seulement pour ffprobe/mediainfo)
  container.querySelectorAll("[data-probe-tool-action]").forEach((btn) => {
    if (btn.dataset.bound === "1") return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", async () => {
      const tool = btn.dataset.probeTool;
      const action = btn.dataset.probeToolAction;
      if (!tool) return;
      const all = container.querySelectorAll("[data-probe-tools-action], [data-probe-tool-action]");
      all.forEach((b) => { b.disabled = true; });
      try {
        if (action === "test") {
          _setProbeToolsMessage(container, `Test ${tool}…`, "info");
          await _loadProbeToolsStatus(container, { force: true });
        } else if (action === "reinstall") {
          _setProbeToolsMessage(container, `Réinstallation de ${tool} (winget)…`, "info");
          const res = await apiPost("runtime/install_probe_tools", { options: { tools: [tool], scope: "user" } });
          const data = res && res.data ? res.data : res;
          if (data && data.ok) {
            _setProbeToolsMessage(container, `✓ ${tool} réinstallé.`, "ok");
          } else {
            _setProbeToolsMessage(container, `Erreur : ${data?.message || "réinstallation impossible"}`, "error");
          }
          if (data && data.status) {
            _state.probeToolsStatus = { ok: true, ...data.status };
            _refreshProbeToolsPanel(container);
          } else {
            await _loadProbeToolsStatus(container, { force: true });
          }
        }
      } catch (err) {
        _setProbeToolsMessage(container, `Erreur réseau : ${err?.message || err}`, "error");
      } finally {
        const all2 = container.querySelectorAll("[data-probe-tools-action], [data-probe-tool-action]");
        all2.forEach((b) => { b.disabled = false; });
      }
    });
  });
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

  // Phase 6 (spec 11) : si l'URL contient un fragment "#/parametres#<categorie>"
  // ou "#/parametres#<categorie>-<section>", il prend le pas sur lastCat.
  _applyHashFragment();

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
  _flushPendingScroll();

  // Listener hashchange : si on est deja sur /parametres et que l'utilisateur
  // clique un lien #/parametres#integrations-jellyfin depuis un autre endroit
  // (banniere demo, page jellyfin/plex/radarr...), on switch de categorie sans
  // re-monter la vue.
  if (typeof window !== "undefined") {
    _state.hashChangeHandler = () => {
      const hash = window.location.hash || "";
      if (!hash.startsWith("#/parametres")) return;
      const changed = _applyHashFragment();
      if (changed) {
        _refreshAll();
        _flushPendingScroll();
      }
    };
    window.addEventListener("hashchange", _state.hashChangeHandler);
  }
}

export function unmountParametres() {
  if (_state.saveTimer) { clearTimeout(_state.saveTimer); _state.saveTimer = null; }
  _uninstallCtrlK();
  if (_state.hashChangeHandler && typeof window !== "undefined") {
    window.removeEventListener("hashchange", _state.hashChangeHandler);
    _state.hashChangeHandler = null;
  }
  _state.pendingScrollSection = null;
  _state.containerRef = null;
  _state.searchQuery = "";
  _state.savedAt = null;
  _state.saveError = null;
}
