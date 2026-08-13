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
import { formatBytes } from "../core/format.js";
// Fix audit 2026-05-30 (v1.5.8) UI/UX critical+high : A11Y-03 remplacer window.confirm()
// natifs par dangerConfirmModal (re-scoring bibliotheque + regen token = destructif).
import { dangerConfirmModal, showModal, trapFocus } from "../components/modal.js";
// Vague D2 : le simulateur que l'avertissement ci-dessous reclame depuis toujours.
import { ouvrirSimulateurQualite } from "../components/simulateur-qualite.js";
// Vague D3 : les regles custom modifient score et tier, et etaient increables.
import { ouvrirReglesQualite } from "../components/regles-qualite.js";
// Vague D4 : le rapport de calibration que l'interface promet depuis toujours.
import { ouvrirCalibrationQualite } from "../components/calibration-qualite.js";

/* =============================================================
 * 1) SCHEMA DECLARATIF DES 10 CATEGORIES
 * ============================================================= */

export const PARAMETRES_GROUPS = [
  {
    id: "sources", label: "Sources", icon: "📂",
    sections: [
      { id: "roots", label: "Dossiers racines", fields: [
        // Fix audit 2026-06-07 UX medium : label "Chemins racine" est jargonneux.
        // L'utilisateur cherche "Dossier de films" ou "Bibliotheque". Hint plus
        // explicite pour expliquer ce qui est attendu.
        { key: "roots", label: "Dossiers de films à analyser", type: "multi-path",
          hint: "Un dossier par ligne (ou séparés par ;). Ex : D:\\Films, E:\\Cinéma. Au moins un dossier est requis pour scanner.",
          required: true },
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
        // AUDIT 2026-06-11 (R4-P1) : clé CANONIQUE perceptual_workers (= celle du GET
        // et du moteur). L'ancien alias perceptual_workers_count n'était jamais
        // renvoyé par le GET, et le POST de l'objet settings entier écrasait la
        // saisie avec l'écho canonique périmé -> réglage ignoré + champ figé au défaut.
        { key: "perceptual_workers", label: "Workers parallèles (scan)", type: "number", min: 0, max: 16, default: 0,
          hint: "0 = auto. Nombre de films analysés en parallèle.", advanced: true },
        { key: "perceptual_frames_count", label: "Frames analysées par film", type: "number", min: 5, max: 30, advanced: true },
        { key: "perceptual_timeout_per_film_s", label: "Timeout par film (s)", type: "number", min: 30, max: 600, advanced: true },
        { key: "perceptual_audio_deep", label: "Audio analyse approfondie", type: "toggle", advanced: true },
        { key: "perceptual_lpips_enabled", label: "LPIPS ONNX (modèle deep learning)", type: "toggle", advanced: true },
      ]},
      { id: "subtitles", label: "Sous-titres", fields: [
        { key: "subtitle_detection_enabled", label: "Détection sous-titres externes", type: "toggle" },
        // R8-065-lang (F5) : champ "subtitle_lang_priority" RETIRÉ — fantôme write-only jamais
        // lu (la clé consommée par le pipeline sous-titres est subtitle_expected_languages).
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
        // R8-071 (F5) : champ "naming_template" (général) RETIRÉ — fantôme jamais lu par
        // le pipeline de nommage (canoniques = naming_movie_template / naming_tv_template).
        { key: "naming_movie_template", label: "Template film", type: "text", placeholder: "{title} ({year})" },
        { key: "naming_tv_template", label: "Template série", type: "text", placeholder: "{series} ({year})" },
      ]},
      { id: "rules", label: "Règles", fields: [
        // R8-101 (filet F5) : toggle "windows_safe" RETIRÉ — fantôme. La fonction
        // windows_safe() est appliquée INCONDITIONNELLEMENT (apply_core/duplicate_support,
        // aucun gate settings) -> l'échappement Windows est toujours actif (sécurité), le
        // toggle laissait croire qu'on pouvait le désactiver.
        // Toggle "lowercase_extensions" (.mkv vs .MKV) RETIRÉ : son seul effet était de
        // RENOMMER le fichier vidéo cible, ce qu'interdit la règle inviolable n°1 (le nom
        // du fichier doit rester synchrone avec le torrent, sinon le seeding casse).
        // Aucun nom de DOSSIER n'en dépendait. Ne pas le réintroduire.
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
        // AUDIT 2026-06-11 (R4-P9) : clé CANONIQUE collection_folder_name (= celle
        // du GET et du backend). L'alias collection_folder n'était jamais renvoyé
        // par le GET -> le champ retombait sur le placeholder au rechargement
        // alors que la vraie valeur était persistée (même pattern que R4-P1).
        { key: "collection_folder_name", label: "Nom du dossier collections", type: "text", placeholder: "_Collection",
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
        // Fix audit 2026-06-07 UX medium : hint d'URL aligne sur TMDb/OMDb.
        { key: "jellyfin_url", label: "URL Jellyfin", type: "text", placeholder: "http://jellyfin.local:8096",
          hint: "URL complète incluant http:// ou https:// et le port (ex : http://192.168.1.10:8096). À trouver dans Tableau de bord > Réseau de Jellyfin." },
        // Fix audit 2026-06-08 UX medium : hint manquant pour trouver la cle API.
        { key: "jellyfin_api_key", label: "Clé API", type: "api-key",
          testMethod: "integrations/test_jellyfin_connection", testParams: { url: "$jellyfin_url", api_key: "$value" },
          hint: "À créer dans Jellyfin > Tableau de bord > Clés API > +. Nommez-la « CineSort » pour la retrouver facilement." },
        { key: "jellyfin_refresh_on_apply", label: "Refresh auto après apply", type: "toggle" },
        { key: "jellyfin_sync_watched", label: "Sync watched", type: "toggle" },
      ]},
      { id: "plex", label: "Plex", fields: [
        { key: "plex_enabled", label: "Activer", type: "toggle" },
        // Fix audit 2026-06-07 UX medium : hint d'URL.
        { key: "plex_url", label: "URL Plex", type: "text", placeholder: "http://plex.local:32400",
          hint: "URL complète incluant http:// ou https:// et le port (ex : http://192.168.1.10:32400). Port Plex par défaut : 32400." },
        // Fix audit 2026-06-08 UX medium : hint manquant pour trouver le token Plex.
        { key: "plex_token", label: "Token Plex", type: "api-key",
          testMethod: "integrations/test_plex_connection", testParams: { url: "$plex_url", token: "$value" },
          hint: "À récupérer dans Plex Web > Compte > Avancées : valeur du paramètre X-Plex-Token (visible dans l'URL d'un média via « Obtenir les informations »)." },
        { key: "plex_refresh_on_apply", label: "Refresh après apply", type: "toggle" },
      ]},
      { id: "radarr", label: "Radarr", fields: [
        { key: "radarr_enabled", label: "Activer", type: "toggle" },
        // Fix audit 2026-06-07 UX medium : hint d'URL.
        { key: "radarr_url", label: "URL Radarr", type: "text", placeholder: "http://radarr.local:7878",
          hint: "URL complète incluant http:// ou https:// et le port (ex : http://192.168.1.10:7878). Port Radarr par défaut : 7878." },
        // Fix audit 2026-06-08 UX medium : hint manquant pour trouver la cle API.
        { key: "radarr_api_key", label: "Clé API", type: "api-key",
          testMethod: "integrations/test_radarr_connection", testParams: { url: "$radarr_url", api_key: "$value" },
          hint: "À récupérer dans Radarr > Paramètres > Général > Sécurité > API Key." },
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
      // [FR-only 2026-07-10 / PHASE5_ARBITRAGES §1] Sélecteur de langue RETIRÉ :
      // les 9 vues principales sont en français en dur (zéro appel t()), donc
      // proposer « English » était une promesse trompeuse (seuls la sidebar, la
      // top-bar et les messages backend basculaient). Le backend garde la
      // machinerie `locale` (en.json + /api/settings/set_locale) pour un usage
      // avancé via settings.json ; l'UI assume le français.
      { id: "theme", label: "Thème", fields: [
        { key: "theme", label: "Thème de l'interface", type: "select", options: [
          {v:"studio",l:"Studio"},{v:"cinema",l:"Cinéma"},{v:"luxe",l:"Luxe"},{v:"neon",l:"Neon"},
        ], livePreview: "theme" },
        { key: "animation_level", label: "Niveau d'animation", type: "select", options: [
          {v:"subtle",l:"Subtil"},{v:"moderate",l:"Modéré"},{v:"intense",l:"Intense"},
        ], livePreview: "animation" },
        // R8-067 (F5) : toggle "animations_enabled" RETIRÉ — fantôme cosmétique jamais
        // consommé (aucun JS ne lit s.animations_enabled). L'intensité d'animation est
        // pilotée par animation_level (sélecteur au-dessus : subtil/modéré/intense).
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
      // VO-B-CONFIG : Scan parallele — tri-etat auto/manuel + N workers [1..64].
      // En mode auto : delegue a VO-A detect_storage (SSD=8 workers, SMB=4, autre=1).
      // En mode manuel : l'utilisateur force une valeur entre 1 et 64.
      // Backward compat (memoire user) : manuel=1 = comportement strictement sequentiel.
      { id: "scan", label: "Scan", fields: [
        { key: "__scan_max_workers__", label: "", type: "scan-max-workers" },
      ]},
      { id: "parallelism", label: "Parallélisme", fields: [
        { key: "perceptual_parallelism_mode", label: "Mode parallélisme", type: "select", options: [
          {v:"auto",l:"Auto"},{v:"max",l:"Max"},{v:"safe",l:"Sécurisé"},{v:"serial",l:"Séquentiel"},
        ]},
        // R8-068 (F5) : toggle "worker_count" RETIRÉ — inerte, aucune opération ne le lit
        // (le parallélisme réel est piloté par le mode au-dessus + perceptual_workers_count).
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
        // "retention_days" RETIRE (2026-08-03) : le champ promettait une purge des
        // "analyses perceptuelles et scores qualité" qui n'existe nulle part cote
        // backend (aucun lecteur du reglage). Il ne restait que le seul reglage
        // reellement branche, sur le cron de purge des runs.
        { key: "history_retention_days", label: "Conserver l'historique (jours)", type: "number", min: 7, max: 365, default: 90,
          hint: "Au-delà, les runs sont purgés automatiquement.", advanced: true },
      ]},
      // VQ-2 QUARANTAINE-TTL : TTL filesystem du bucket _review + viewer + bouton vider.
      // Cron 24h cote backend purge _review/_conflicts, _conflicts_sidecars,
      // _duplicates_identical, _leftovers et rows top-level > TTL jours.
      // `quarantaine_ttl_days = 0` desactive le cron. Bouton "Vider maintenant"
      // protege par dangerConfirmModal (countdown 3s si > 50 fichiers).
      { id: "quarantaine", label: "Quarantaine", fields: [
        { key: "quarantaine_ttl_days", label: "TTL fichiers en quarantaine (jours)", type: "number", min: 0, max: 365, default: 30,
          hint: "Bucket _review (conflits, doublons, leftovers, rows non approuvées). 0 = désactivé." },
        { key: "__quarantine_viewer__", label: "Contenu du bucket _review", type: "action",
          action: "quarantine_viewer", buttonLabel: "👁️ Voir le bucket",
          hint: "Inventaire des fichiers actuellement en quarantaine (lecture seule)." },
        { key: "__quarantine_purge_all__", label: "Vider le bucket maintenant", type: "action",
          action: "quarantine_purge_all", buttonLabel: "🗑️ Vider maintenant",
          hint: "Supprime TOUS les fichiers de _review/ sauf les décisions de doublons. Action irréversible — confirmation requise." },
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
  // F04 (revue post-merge 2026-07-18) : promesse du POST save_settings en vol.
  // Permet a _loadSettings d'attendre la fin d'un flush declenche par
  // unmountParametres avant de relire l'etat serveur (sinon on relit un etat
  // pre-save et on ecrase l'edition de l'utilisateur au remontage).
  saveInFlight: null,
  savedAt: null,
  saveError: null,
  // F04 (revue adversaire R1) : `saveError` est de l'etat de VUE (remis a null
  // par unmountParametres), or le flush part justement AU demontage : un refus
  // backend (ok:false, 401, 5xx apres les 3 retries de core/api.js) arrivait
  // donc quand la vue etait deja partie et ne laissait AUCUNE trace. Ce champ-ci
  // survit au demontage et est re-affiche au prochain montage de la vue.
  lastFlushError: null,
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
  // VO-B-CONFIG : dernier payload retourne par settings/get_scan_max_workers.
  // Forme : { mode, value, effective, storage_detected, auto_suggestion, min, max }.
  // Null = pas encore charge cette session (premier render = "Chargement..." puis fetch).
  scanMaxWorkersState: null,
  scanMaxWorkersLoading: false,
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

// Audit ultra 2026-07-13 (M5) : recalibre sur la grille backend CANONIQUE
// v1.5.7 (cinesort/domain/quality_score.default_quality_profile()["tiers"] ==
// cinesort/domain/tiers_helpers.DEFAULT_TIER_THRESHOLDS = 70/66/55/40). L'ancienne
// grille 85/68/54/30 (pre-v1.5.5) etait ECRITE en base au save de profil et
// divergeait des seuils reellement appliques par le scoring.
const _DEFAULT_TIERS = { platinum: 70, gold: 66, silver: 55, bronze: 40 };
// LES POIDS QUE LE SCORING LIT REELLEMENT, dans SA forme (points de
// pourcentage, somme 100). Mesure : `quality_score.py:1403-1407` n'additionne
// que `video`, `audio` et `extras` — et `default_quality_profile()["weights"]`
// vaut {video: 60, audio: 30, extras: 10}.
//
// L'ANCIENNE CONSTANTE DECRIVAIT UN AUTRE MODELE, que rien ne lisait :
// {resolution: .25, bitrate: .20, codec: .15, audio_bitrate: .20,
//  audio_channels: .10, subtitles_fr: .10}. L'editeur rendait un curseur par
// cle de CETTE liste, et la sauvegarde renvoyait ces six cles. Mesure de bout
// en bout, sur un profil regle a video 70 / audio 20 / extras 10 :
//
//     l'utilisateur bouge ses curseurs et sauvegarde  ->  ok: True
//     poids APRES : video 60 / audio 30 / extras 10   <- LE DEFAUT
//                   + les six cles mortes, portees sans etre lues
//
// Autrement dit : bouger les curseurs REMETTAIT les vrais poids aux valeurs
// d'usine, et les curseurs eux-memes ne faisaient rien. Le commentaire de
// `_DEFAULT_TIERS` ci-dessus documente la meme derive sur les seuils
// (grille 85/68/54/30 ecrite en base et divergente du scoring) : c'est la meme
// cause — une constante JS qui fait autorite a la place du backend.
const _DEFAULT_WEIGHTS = { video: 60, audio: 30, extras: 10 };

//: Somme attendue des poids, dans la forme canonique du backend.
const _SOMME_POIDS = 100;
const _TOLERANCE_POIDS = 5;

// VP-B (Vague P) : hierarchie qualite multi-axes (TRaSH/Radarr 2026).
// OPT-IN strict (toggle default OFF). Default sync avec
// cinesort.domain.tiers_helpers.default_hierarchy_config() :
// - enabled=false (memo fix #4 ROADMAP : aucune redistribution sur 853 films).
// - order = 5 dimensions canoniques (drag-and-drop user). Backend filtre
//   les inconnues automatiquement.
const _DEFAULT_HIERARCHY_DIMENSIONS = [
  "resolution",
  "video_codec",
  "hdr",
  "audio",
  "release_group",
];
const _HIERARCHY_DIMENSION_LABELS = {
  resolution: "Résolution",
  video_codec: "Codec vidéo",
  hdr: "HDR (DV / HDR10+)",
  audio: "Audio",
  release_group: "Release group",
};
const _DEFAULT_TIER_HIERARCHY = {
  enabled: false,
  order: _DEFAULT_HIERARCHY_DIMENSIONS.slice(),
};
const _WEIGHT_LABELS = {
  video: "Vidéo (résolution, bitrate, codec, HDR)",
  audio: "Audio (codec, canaux, bitrate)",
  extras: "Extras (sous-titres, langues, bonus)",
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
  // AUDIT 2026-06-11 (R4-P13) : 0 est une valeur CONFIGUREE pour un champ
  // number dont le min est 0 (ex: perceptual_workers=0 = auto) - l'ancien
  // `!== 0` degradait le badge de section a "partial" pour une valeur legitime.
  if (field.type === "number") return field.min === 0 ? Number.isFinite(Number(val)) : Number(val) !== 0;
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
 *   runtime/recheck_probe_tools     -> force recheck (bouton « Vérifier »)
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
 * `kind` : "managed" (ffprobe/mediainfo : actions Vérifier + Réinstaller)
 *        | "bundled-exe" (fpcalc : bundled, pas d'action utilisateur)
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
      <button type="button" class="v5-btn v5-btn--sm" data-probe-tool-action="test" data-probe-tool="${_esc(toolKey)}" title="Re-vérifier si ${_esc(displayLabel)} est installé sur le système">Vérifier</button>
      <button type="button" class="v5-btn v5-btn--sm v5-btn--ghost" data-probe-tool-action="reinstall" data-probe-tool="${_esc(toolKey)}" title="Réinstaller via winget (Microsoft Store)">Réinstaller</button>
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
 * VO-B-CONFIG : rend la section "Scan" (tri-etat workers auto/manuel).
 *
 * `state` = payload retourne par settings/get_scan_max_workers :
 *   { mode, value, effective, storage_detected, auto_suggestion, min, max }
 *
 * En mode "auto", l'input number "value" est masque (le backend choisit
 * en fonction de VO-A detect_storage). En mode "manual", il est visible
 * et editable entre [min..max] (1..64). Le champ est applique au blur OU
 * a l'Enter pour eviter les writes intermediaires.
 */
function _renderScanMaxWorkersSection(state) {
  if (_state.scanMaxWorkersLoading) {
    return `<div class="parametres-muted">Chargement de la configuration scan…</div>`;
  }
  if (!state || typeof state !== "object") {
    return `<div class="parametres-muted">Statut non disponible. <button type="button" class="v5-btn v5-btn--sm" data-scan-workers-reload>Recharger</button></div>`;
  }

  const mode = String(state.mode || "auto");
  const value = Number(state.value || 1);
  const effective = Number(state.effective || 1);
  const detected = String(state.storage_detected || "local_ssd");
  const autoSuggestion = Number(state.auto_suggestion || 1);
  const minVal = Number(state.min || 1);
  const maxVal = Number(state.max || 64);

  const detectedLabel = detected === "nas_smb"
    ? "NAS / SMB"
    : "SSD local";

  const isManual = mode === "manual";
  const numberHidden = isManual ? "" : ' style="display:none"';

  const activeBadge = `<span class="parametres-tools-mode parametres-tools-mode--ok">Workers actifs : ${escapeHtml(String(effective))}</span>`;

  return `<div class="parametres-scan-max-workers">
    <p class="parametres-section-intro">
      Nombre de workers pour la phase 1 du scan (parallelisation iter_videos).
      <strong>Auto</strong> s'adapte au stockage détecté
      (<em>${escapeHtml(detectedLabel)}</em> &rArr; ${escapeHtml(String(autoSuggestion))} workers).
      Manuel = vous forcez une valeur entre ${escapeHtml(String(minVal))} et ${escapeHtml(String(maxVal))}.
    </p>
    <div class="parametres-field">
      <label class="parametres-field-label" for="parametres-scan-workers-mode">Mode</label>
      <select id="parametres-scan-workers-mode" class="parametres-select" data-scan-workers-mode>
        <option value="auto" ${mode === "auto" ? "selected" : ""}>Auto (synergie storage)</option>
        <option value="manual" ${mode === "manual" ? "selected" : ""}>Manuel (forcer N)</option>
      </select>
      <span class="parametres-field-hint">${activeBadge}</span>
    </div>
    <div class="parametres-field" data-scan-workers-value-wrapper${numberHidden}>
      <label class="parametres-field-label" for="parametres-scan-workers-value">
        Workers (${escapeHtml(String(minVal))}-${escapeHtml(String(maxVal))})
      </label>
      <input type="number" id="parametres-scan-workers-value" class="parametres-input"
             min="${escapeHtml(String(minVal))}" max="${escapeHtml(String(maxVal))}" step="1"
             value="${escapeHtml(String(value))}" data-scan-workers-value>
      <span class="parametres-field-hint">
        Backward compat : valeur 1 = comportement strictement séquentiel (aucune parallélisation).
      </span>
    </div>
    <p class="parametres-scan-max-workers-message parametres-muted" data-scan-workers-message></p>
  </div>`;
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
    return `<div class="parametres-tools-loading parametres-muted">
      Statut des outils externes non disponible.
      <button type="button" class="v5-btn v5-btn--sm v5-btn--primary" data-probe-tools-action="recheck" style="margin-left:8px">↻ Détecter maintenant</button>
    </div>`;
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
      <button type="button" class="v5-btn v5-btn--sm" data-probe-tools-action="recheck" title="Re-détecter les outils installés sur le système (ignore le cache)">↻ Vérifier (forcer la détection)</button>
      <button type="button" class="v5-btn v5-btn--sm v5-btn--primary" data-probe-tools-action="auto_install" title="Télécharger et installer ffprobe + MediaInfo (~110 Mo, empreinte SHA256 vérifiée avant installation)">⬇ Installer automatiquement (ffprobe + MediaInfo)</button>
      <button type="button" class="v5-btn v5-btn--sm" data-probe-tools-action="update" title="Mettre à jour via winget (nécessite Windows Package Manager)">⇧ Mettre à jour (winget)</button>
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
      // Fix audit 2026-06-08 UX medium : label "Tester" trop ambigu (declenche un
      // appel reseau reel). Pour OMDb, on precise que ca consomme du quota.
      const isOmdbTest = field.key === "omdb_api_key";
      const testLabel = isOmdbTest ? "Tester (consomme 1 appel quota)" : "Tester la connexion";
      const testTitle = isOmdbTest
        ? "Effectue un appel reel a OMDb pour valider la cle. Consomme 1 requete de votre quota quotidien."
        : "Effectue un appel reseau reel au service pour valider la cle/URL.";
      const testBtn = field.testMethod
        ? `<button type="button" class="v5-btn v5-btn--sm" data-test-method="${_esc(field.testMethod)}" data-test-field="${_esc(field.key)}" title="${_esc(testTitle)}">${_esc(testLabel)}</button>`
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

    case "scan-max-workers":
      // VO-B-CONFIG : tri-etat auto/manuel + input number 1..64.
      // Le contenu reel est rendu apres settings/get_scan_max_workers.
      return `<div class="parametres-field parametres-field--scan-max-workers" data-scan-workers-host>${_renderScanMaxWorkersSection(_state.scanMaxWorkersState)}</div>`;

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
  // VP-B : hierarchie qualite (default OFF, opt-in user).
  const hierarchy = draft.tier_hierarchy || { ..._DEFAULT_TIER_HIERARCHY };
  const hierarchyEnabled = !!hierarchy.enabled;
  const hierarchyOrder = (Array.isArray(hierarchy.order) && hierarchy.order.length > 0)
    ? hierarchy.order.filter((d) => _DEFAULT_HIERARCHY_DIMENSIONS.includes(d))
    : _DEFAULT_HIERARCHY_DIMENSIONS.slice();

  const totalWeight = Object.values(weights).reduce((s, v) => s + (Number(v) || 0), 0);
  const totalDisplay = String(Math.round(totalWeight));
  const inRange = Math.abs(totalWeight - _SOMME_POIDS) <= _TOLERANCE_POIDS;
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

  // LES CLES VIENNENT DU PROFIL, pas d'une liste ecrite ici. Une liste figee
  // dans le front finit toujours par decrire un autre modele que le scoring :
  // c'est precisement ce qui rendait cet editeur inoperant.
  const clesDePoids = Object.keys(weights).length ? Object.keys(weights) : Object.keys(_DEFAULT_WEIGHTS);
  const weightRows = clesDePoids.map((key) => {
    const v = Number(weights[key] ?? _DEFAULT_WEIGHTS[key] ?? 0);
    return `<div class="parametres-weight-row">
      <label for="weight-${key}">${_esc(_WEIGHT_LABELS[key] || key)}</label>
      <input type="range" id="weight-${key}" min="0" max="100" step="1" value="${Math.round(v)}"
             data-weight-input="${key}" class="parametres-input parametres-input--range">
      <span class="parametres-weight-value" data-weight-value="${key}">${Math.round(v)} %</span>
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
      Ces trois poids sont ceux que le calcul du score applique réellement.
    </p>
    <p class="parametres-section-intro">
      La somme des poids doit faire ~100 (tolérance ± 5).
    </p>
    <div class="parametres-weight-rows">
      ${weightRows}
      <div class="parametres-weight-total ${totalCls}" data-weight-total>
        Total = ${totalDisplay} ${totalIcon}
      </div>
    </div>

    <h4 class="parametres-subheading">Hiérarchie qualité (TRaSH 2026)</h4>
    <p class="parametres-section-intro">
      Mode avancé "Quality Trumps All" inspiré de TRaSH-Guides / Radarr.
      Certaines dimensions techniques (résolution, codec, HDR, audio, release group)
      imposent un plancher de tier (ex&nbsp;: un 2160p vérifié ne pourra pas être
      Bronze). <strong>Activer ce mode peut redistribuer 30-40&nbsp;% de votre
      bibliothèque actuelle — utilisez la simulation avant d'activer.</strong>
      Par défaut désactivé pour préserver vos scores existants.
    </p>
    <p class="parametres-section-intro">
      <button type="button" class="v5-btn v5-btn--secondary" data-parametres-ouvrir-simulateur>
        🧪 Simuler un profil
      </button>
      <button type="button" class="v5-btn v5-btn--secondary" data-parametres-ouvrir-regles>
        ⚙ Règles personnalisées
      </button>
      <button type="button" class="v5-btn v5-btn--secondary" data-parametres-ouvrir-calibration>
        🎚 Réglages fins
      </button>
      <span class="parametres-hint">Comparez avant / après, ou affinez le score avec vos propres règles.</span>
    </p>
    <div class="parametres-hierarchy-section" data-parametres-hierarchy-host>
      <label class="parametres-hierarchy-toggle">
        <input type="checkbox" data-parametres-hierarchy-enabled
               ${hierarchyEnabled ? "checked" : ""}
               aria-label="Activer la hiérarchie qualité multi-axes (TRaSH 2026)">
        <span>Activer la hiérarchie qualité multi-axes</span>
      </label>
      <div class="parametres-hierarchy-order" data-parametres-hierarchy-order
           aria-label="Ordre des dimensions (la première a la priorité la plus haute)">
        <p class="parametres-hierarchy-order-intro">
          Ordre de priorité (haut = plus prioritaire). Réorganisez avec
          ↑ / ↓ pour ajuster les plafonds et planchers.
        </p>
        <ol class="parametres-hierarchy-list">
          ${hierarchyOrder.map((dim, idx) => `
            <li class="parametres-hierarchy-row" data-hierarchy-dim="${_esc(dim)}">
              <span class="parametres-hierarchy-rank">${idx + 1}.</span>
              <span class="parametres-hierarchy-label">${_esc(_HIERARCHY_DIMENSION_LABELS[dim] || dim)}</span>
              <span class="parametres-hierarchy-controls">
                <button type="button" class="v5-btn v5-btn--ghost v5-btn--xs"
                        data-hierarchy-move="up" data-hierarchy-dim-target="${_esc(dim)}"
                        ${idx === 0 ? "disabled" : ""}
                        aria-label="Monter ${_esc(dim)}">↑</button>
                <button type="button" class="v5-btn v5-btn--ghost v5-btn--xs"
                        data-hierarchy-move="down" data-hierarchy-dim-target="${_esc(dim)}"
                        ${idx === hierarchyOrder.length - 1 ? "disabled" : ""}
                        aria-label="Descendre ${_esc(dim)}">↓</button>
              </span>
            </li>`).join("")}
        </ol>
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

    <!-- VP-F (Vague P batch 6) : import/export Recyclarr YAML + breakdown 5 axes + upgrade_until_score -->
    <h4 class="parametres-subheading">Profils qualité (compatibilité Recyclarr / TRaSH 2026)</h4>
    <p class="parametres-section-intro">
      Importez ou exportez votre profil au format Recyclarr v6+ YAML, compatible avec
      les <em>Custom Format Groups</em> TRaSH-Guides. Le format embarque l'intégralité
      du profil CineSort dans la clé <code>cinesort_profile</code> pour un round-trip
      sans perte.
    </p>

    <div class="parametres-profils-recyclarr" data-vpf-recyclarr-host>
      <div class="parametres-profils-recyclarr-actions">
        <button type="button" class="v5-btn" data-vpf-action="export-yaml"
                aria-label="Exporter le profil actif au format Recyclarr YAML">
          📤 Exporter YAML (Recyclarr)
        </button>
        <button type="button" class="v5-btn" data-vpf-action="import-yaml"
                aria-label="Importer un profil depuis YAML Recyclarr">
          📥 Importer YAML (Recyclarr)
        </button>
        <button type="button" class="v5-btn v5-btn--ghost" data-vpf-action="show-presets"
                aria-label="Voir les presets embarqués TRaSH 2026">
          📚 Presets TRaSH 2026
        </button>
      </div>
      <textarea class="parametres-input parametres-profils-yaml" data-vpf-yaml-textarea
                rows="8" placeholder="Collez ici votre YAML Recyclarr puis cliquez sur Importer YAML, ou cliquez sur Exporter YAML pour obtenir le profil actif."
                aria-label="Zone YAML Recyclarr"></textarea>
      <p class="parametres-profils-message" data-vpf-recyclarr-message></p>
    </div>

    <h4 class="parametres-subheading">Score d'arrêt des upgrades</h4>
    <p class="parametres-section-intro">
      Au-dessus de ce score, l'UI n'affichera plus de recommandation
      d'upgrade pour ces films (réduit le bruit décisionnel). Par défaut
      <strong>10000</strong> (jamais arrêter).
    </p>
    <div class="parametres-profils-upgrade-until" data-vpf-upgrade-host>
      <label for="parametres-upgrade-until-score">Score seuil d'arrêt&nbsp;:</label>
      <input type="number" id="parametres-upgrade-until-score"
             class="parametres-input"
             min="0" max="100000" step="100" value="10000"
             data-vpf-upgrade-input
             aria-label="upgrade_until_score">
      <button type="button" class="v5-btn v5-btn--primary" data-vpf-action="save-upgrade-until">
        ✓ Enregistrer
      </button>
      <p class="parametres-profils-message" data-vpf-upgrade-message></p>
    </div>

    <h4 class="parametres-subheading">Détail du scoring (5 axes)</h4>
    <p class="parametres-section-intro">
      Décomposition du scoring par axe technique. Le poids affiché est la
      contribution maximale théorique du profil actif sur chaque axe.
    </p>
    <div class="parametres-profils-breakdown" data-vpf-breakdown-host>
      <p class="parametres-section-intro" data-vpf-breakdown-loading>
        Chargement…
      </p>
    </div>
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

/**
 * Actions d'une section d'integration — vague B2.
 *
 * CE QUE CES BOUTONS RENDENT ATTEIGNABLE. Six methodes de facade existaient,
 * testees cote backend, et n'etaient appelees par AUCUN code du dashboard.
 * `docs/TROUBLESHOOTING.md` donne pourtant le rapport de coherence Jellyfin
 * comme *la* solution utilisateur a un probleme documente — une reponse que
 * personne ne pouvait suivre.
 *
 * DECLARATIF, ET NON CABLE EN DUR : la page entiere est batie sur un schema,
 * et une exception codee a la main pour six boutons aurait diverge au premier
 * champ ajoute. Chaque entree porte sa route, son libelle, et la facon de
 * rendre sa reponse.
 *
 * `request_radarr_upgrade` n'est PAS ici : elle exige un `radarr_movie_id`,
 * donc elle appartient a la fiche d'un film, pas a un reglage global. La
 * cabler ici aurait demande d'inventer un champ de saisie d'identifiant
 * Radarr — une interface que personne n'a demandee, pour une methode qui a
 * deja son domicile naturel ailleurs.
 */
const ACTIONS_DE_SECTION = {
  jellyfin: [
    {
      route: "integrations/get_jellyfin_sync_report",
      label: "Rapport de cohérence",
      titre: "Compare la bibliothèque Jellyfin au dernier scan et liste les écarts",
      rendu: "rapport",
    },
    {
      route: "integrations/refresh_jellyfin_library_now",
      label: "Rafraîchir maintenant",
      titre: "Demande à Jellyfin de re-scanner sa bibliothèque immédiatement",
      rendu: "message",
    },
  ],
  plex: [
    {
      route: "integrations/get_plex_sync_report",
      label: "Rapport de cohérence",
      titre: "Compare la bibliothèque Plex au dernier scan et liste les écarts",
      rendu: "rapport",
    },
    {
      route: "integrations/refresh_plex_library_now",
      label: "Rafraîchir maintenant",
      titre: "Demande à Plex de re-scanner sa bibliothèque immédiatement",
      rendu: "message",
    },
  ],
  email: [
    {
      route: "integrations/test_email_report",
      label: "Envoyer un email de test",
      titre: "Envoie un rapport d'exemple pour valider la configuration SMTP",
      rendu: "message",
    },
  ],
  // --- Vague B3 : runtime et reglages ---------------------------------------
  logs: [
    {
      route: "runtime/get_log_paths",
      label: "Où sont les journaux ?",
      titre: "Affiche les chemins des fichiers de log sur ce poste",
      rendu: "chemins",
    },
  ],
  outils: [
    {
      route: "runtime/purge_probe_cache",
      label: "Vider le cache de sonde",
      titre: "Oublie les mesures techniques déjà faites : elles seront refaites au prochain scan",
      rendu: "message",
      // DESTRUCTIVE : la regle du depot exige une confirmation qui NOMME la
      // consequence. Le cache de sonde n'est pas de la donnee utilisateur, mais
      // le vider fait repayer chaque mesure technique au prochain scan — sur une
      // grande bibliotheque, c'est long, et l'utilisateur doit le savoir avant.
      confirmation: {
        titre: "Vider le cache de sonde ?",
        corps:
          "Les mesures techniques déjà faites (codec, résolution, HDR, pistes audio) seront oubliées. " +
          "Elles seront refaites au prochain scan, ce qui peut être long sur une grande bibliothèque. " +
          "Aucun film et aucun réglage n'est supprimé.",
        libelle: "Vider le cache",
        // LE DELAI DE 3 s EST ECARTE ICI, ET C'EST UNE DECISION, PAS UN OUBLI.
        // La regle n3 gradue le delai sur le NOMBRE d'elements detruits ; or
        // `purge_probe_cache()` ne prend aucun parametre et ne rend son compte
        // (`entries_deleted`) qu'APRES coup — le nombre est inconnaissable
        // avant l'appel (mesure sur la facade runtime).
        //
        // Et il ne s'agit pas d'une destruction : le cache se REGENERE au
        // prochain scan. Ce que l'utilisateur perd, c'est du temps, pas de la
        // donnee — la consequence le dit, et c'est le bon instrument. Un delai
        // graduable sur un compte invente serait pire que pas de delai.
        delaiSecondes: 0,
        motifSansDelai: "cache regenerable ; le nombre d'entrees n'est pas connu avant l'appel",
      },
    },
  ],
  templates: [
    {
      route: "settings/get_naming_presets",
      label: "Modèles proposés",
      titre: "Liste les modèles de nommage fournis avec l'application",
      rendu: "presets",
    },
  ],
  "stockage-sqlite": [
    {
      route: "settings/get_user_data_size",
      label: "Taille des données",
      titre: "Mesure la place occupée par la base et les données de runs",
      rendu: "taille",
    },
    {
      route: "settings/reset_all_user_data",
      label: "Tout réinitialiser…",
      titre: "Supprime la base, les réglages et l'historique — après une sauvegarde ZIP complète",
      rendu: "reset",
      // LA PLUS DESTRUCTIVE DES ACTIONS DE L'APPLICATION, et la seule des dix
      // methodes de la vague B3 restee non cablable : le backend exige que
      // l'utilisateur TAPE « RESET » (reset_support.py:266), et la modale de
      // danger n'avait aucune affordance de saisie. Elle en a une desormais.
      confirmation: {
        titre: "Réinitialiser toutes les données ?",
        elements: [
          "la base SQLite : scans, scores, doublons, décisions",
          "settings.json : tous vos réglages",
          "l'historique des runs et le cache TMDb",
          "les rapports de similarité perceptuelle",
        ],
        corps:
          "Une sauvegarde ZIP complète est créée AVANT toute suppression, à côté du dossier " +
          "de données. Vos journaux (logs/) sont conservés. Aucun fichier de votre " +
          "bibliothèque de films n'est touché : seules les données de l'application le sont.",
        libelle: "Tout réinitialiser",
        delaiSecondes: 3,
        // Le mot est transmis TEL QUE TAPE ; c'est le backend qui le verifie.
        motAConfirmer: "RESET",
        parametre: "confirmation",
      },
      // Cette action REECRIT l'etat sous l'application : tout ce qui en derive
      // doit repartir du disque, sinon la premiere autosave la defait.
      rechargeTout: true,
    },
  ],
};

function _renderSectionActions(section) {
  const actions = ACTIONS_DE_SECTION[section.id];
  if (!actions || !actions.length) return "";
  const boutons = actions
    .map(
      (a) => `<button type="button" class="v5-btn v5-btn--sm v5-btn--ghost"
        data-section-action="${_esc(a.route)}"
        title="${_esc(a.titre)}">${_esc(a.label)}</button>`
    )
    .join("");
  return `<div class="parametres-section-actions">${boutons}
    <div class="parametres-section-actions-out" data-section-actions-out="${_esc(section.id)}"></div>
  </div>`;
}

/** Retrouve la definition d'une action a partir de sa route. */
function _trouverAction(route) {
  for (const actions of Object.values(ACTIONS_DE_SECTION)) {
    const trouvee = actions.find((a) => a.route === route);
    if (trouvee) return trouvee;
  }
  return null;
}

/**
 * Met en forme la reponse d'une action de section.
 *
 * DEUX RENDUS, PARCE QU'IL Y A DEUX NATURES DE REPONSE. Un rafraichissement ou
 * un email de test rend un accuse ; un rapport de coherence rend des CHIFFRES
 * que l'utilisateur doit pouvoir lire. Les afficher tous les deux comme un
 * simple « OK » perdrait precisement l'information pour laquelle le rapport
 * existe.
 *
 * Les compteurs sont lus SANS invention : seules les cles reellement presentes
 * dans la reponse sont affichees. Une cle absente n'est pas rendue « 0 », ce qui
 * ferait passer une absence de mesure pour une mesure nulle.
 */
//: Cles d'enveloppe d'une reponse d'API : elles ne portent jamais de donnee
//: metier, et un rendu generique qui les prendrait pour telle mentirait.
const _CLES_ENVELOPPE = new Set(["ok", "error", "message", "user_message", "category", "level"]);

function _rendreReponseAction(action, data) {
  if (action.rendu === "rapport") {
    const compteurs = [
      ["manquants", "absents de la médiathèque"],
      ["missing", "absents de la médiathèque"],
      ["extra", "présents en trop"],
      ["orphans", "orphelins"],
      ["matched", "concordants"],
      ["total", "films comparés"],
    ]
      .filter(([cle]) => data[cle] !== undefined && data[cle] !== null)
      .map(([cle, libelle]) => `${String(data[cle])} ${libelle}`);
    if (compteurs.length) return compteurs.join(" · ");
  }
  if (action.rendu === "chemins") {
    // Les cles d'ENVELOPPE sont exclues : sans cela, une reponse sans chemin
    // mais avec un `message` rendait « message : ... » comme s'il s'agissait
    // d'un chemin, au lieu de retomber sur le message. Mesure : le sous-test
    // `chemins` du repli echouait exactement la-dessus.
    const chemins = Object.entries(data)
      .filter(([cle, v]) => !_CLES_ENVELOPPE.has(cle) && typeof v === "string" && v)
      .map(([cle, v]) => `${cle} : ${v}`);
    if (chemins.length) return chemins.join(" | ");
  }
  if (action.rendu === "presets") {
    const liste = Array.isArray(data.presets) ? data.presets : [];
    // Un preset peut etre une chaine ou un objet {name, template} : on ne
    // suppose pas la forme, on rend ce qui est lisible.
    const noms = liste.map((p) => (typeof p === "string" ? p : p && (p.name || p.label || p.template))).filter(Boolean);
    if (noms.length) return `${noms.length} modèle(s) : ${noms.join(" · ")}`;
  }
  if (action.rendu === "reset") {
    // `reset_all_user_data` rend `{backup_path, removed, failed, message}`.
    //
    // UN RESET PARTIEL EST LE CAS NORMAL, PAS L'EXCEPTION. Le wipe s'execute
    // pendant que l'application TOURNE : ses threads de fond tiennent des
    // fichiers ouverts, et sous Windows un seul suffit a faire echouer la
    // suppression de son dossier parent (docstring de `_vider_state_dir_sauf_logs`).
    // Le backend le sait et rend `failed` + un message « Reinitialisation
    // PARTIELLE … ferme puis relance l'application ».
    //
    // Une premiere version ne lisait que `removed` et `backup_path` et
    // retournait AVANT le repli sur `data.message` : la base et settings.json
    // pouvaient SURVIVRE pendant que l'ecran annoncait « 1 element(s)
    // supprime(s) » en vert. Un echec devenu succes silencieux, sur la plus
    // destructive des actions.
    const parts = [];
    if (Array.isArray(data.removed) && data.removed.length) {
      parts.push(`${data.removed.length} élément(s) supprimé(s)`);
    }
    const echecs = Array.isArray(data.failed) ? data.failed : [];
    if (echecs.length) {
      parts.push(`${echecs.length} N'ONT PAS PU L'ÊTRE (${echecs.slice(0, 3).join(", ")})`);
    }
    if (data.backup_path) parts.push(`sauvegarde : ${data.backup_path}`);
    // Le message du backend porte la CONSIGNE (« fermez puis relancez ») : il
    // vient en dernier, mais il vient.
    const consigne = String(data.user_message || data.message || "");
    if (consigne) parts.push(consigne);
    if (parts.length) return parts.join(" · ");
  }
  if (action.rendu === "taille") {
    // `get_user_data_size` rend `{size_mb, items}` -- des MEGAOCTETS et un
    // COMPTE, pas des octets. Une premiere version passait toute valeur
    // numerique a `formatBytes` : les megaoctets sortaient mille fois trop
    // petits, et le nombre d'elements etait affiche comme un poids.
    const parts = [];
    if (typeof data.size_mb === "number") parts.push(`${data.size_mb} Mo`);
    if (typeof data.items === "number") parts.push(`${data.items} élément(s)`);
    if (parts.length) return parts.join(" · ");
  }
  return String(data.user_message || data.message || "Terminé.");
}

/**
 * Apres une action qui a REECRIT l'etat sous l'application, tout ce qui en
 * derive doit repartir du disque.
 *
 * SANS CELA, LE RESET S'ANNULE TOUT SEUL. `_state.settings` garde en memoire
 * l'objet d'AVANT, et `_saveSettingsNow` POSTe `{settings: _state.settings}` en
 * ENTIER : la premiere modification d'un champ — ou le simple `_flushPendingSave`
 * d'une sortie de vue — recree `settings.json` avec exactement les reglages que
 * l'utilisateur venait de demander a supprimer. Les autres vues, elles,
 * continueraient de servir le cache partage.
 *
 * Le reset FRERE de ce fichier (`settings/reset_settings`) fait deja ces appels.
 * L'action strictement plus destructive etait la seule a ne pas les faire.
 */
async function _rechargerApresReset() {
  // Une ecriture en vol reposerait l'ancien contenu : on la neutralise AVANT
  // de relire, et on attend qu'elle soit retombee.
  if (_state.saveTimer) {
    clearTimeout(_state.saveTimer);
    _state.saveTimer = null;
  }
  if (_state.saveInFlight) {
    try {
      await _state.saveInFlight;
    } catch {
      /* une sauvegarde d'avant-reset qui echoue est sans consequence ici */
    }
    _state.saveInFlight = null;
  }
  invalidateSettingsCache();
  await _loadSettings();
  await _loadProfiles();
  _refreshAll();
}

/** Appelle la route et rend sa reponse dans la zone de sortie de la section. */
async function _executerActionDeSection(action, route, btn, ecrire, params = {}) {
  ecrire("En cours…", "info");
  btn.disabled = true;
  let aboutie = false;
  let derniereClasse = "ok";
  let dernierTexte = "";
  try {
    const res = await apiPost(route, params);
    const data = (res && res.data) || res || {};
    if (data.ok === false) {
      // Le message du backend passe AVANT tout libelle generique : c'est lui qui
      // dit pourquoi (URL absente, jeton invalide, serveur injoignable).
      //
      // `error` EST UNE CLE REELLE, PAS UNE PRECAUTION. `reset_support` renvoie
      // ses echecs sous `key="error"` (lignes 272, 278 et 326) — contrat
      // historique documente dans `_responses.py`. Sans elle, un disque plein
      // pendant le ZIP de sauvegarde s'affichait « L'action a échoué. » et rien
      // d'autre : l'utilisateur ignorait que la SAUVEGARDE n'avait pas ete faite.
      ecrire(String(data.user_message || data.message || data.error || "L'action a échoué."), "error");
      return;
    }
    // UN SUCCES PARTIEL N'EST PAS UN SUCCES. Regle generale, pas propre au
    // reset : toute reponse qui porte un `failed` non vide decrit un travail
    // inacheve, et l'ecrire en vert serait mentir sur son resultat.
    const inacheve = Array.isArray(data.failed) && data.failed.length > 0;
    derniereClasse = inacheve ? "avertissement" : "ok";
    dernierTexte = _rendreReponseAction(action, data);
    ecrire(dernierTexte, derniereClasse);
    aboutie = true;
  } catch {
    ecrire("L'action a échoué : le serveur n'a pas répondu.", "error");
  } finally {
    btn.disabled = false;
  }

  // LE RECHARGEMENT VIENT APRES, ET DEHORS. Le laisser dans le `try` faisait
  // rapporter son echec comme celui de l'ACTION — « le serveur n'a pas répondu »
  // sur un wipe qui venait pourtant d'aboutir. Deux evenements distincts
  // meritent deux phrases distinctes.
  if (aboutie && action.rechargeTout) {
    try {
      await _rechargerApresReset();
      // LE RECHARGEMENT A REMPLACE LE DOM. On RECRIT le resultat, sinon il
      // disparaitrait avec le noeud qui le portait — chemin de sauvegarde
      // compris, c'est-a-dire le seul moyen de revenir en arriere. `ecrire`
      // retrouve le noeud NEUF de lui-meme.
      if (dernierTexte) ecrire(dernierTexte, derniereClasse);
    } catch {
      ecrire(
        "L'action a abouti, mais les réglages n'ont pas pu être relus : rouvrez l'écran avant de rien modifier.",
        "avertissement"
      );
    }
  }
}

function _lancerActionDeSection(container, btn) {
  const route = btn.dataset.sectionAction || "";
  const action = _trouverAction(route);
  if (!action) return;
  const sectionEl = btn.closest("[data-section-id]");
  const sortie = sectionEl && sectionEl.querySelector("[data-section-actions-out]");
  const idSection = sectionEl && sectionEl.dataset ? sectionEl.dataset.sectionId : "";

  // LE NOEUD DE SORTIE EST RETROUVE A CHAQUE ECRITURE, PAS CAPTURE UNE FOIS.
  //
  // `_refreshAll()` fait `root.innerHTML = _renderParametres()` : il DETRUIT le
  // noeud. Une action qui recharge les reglages apres coup — « Tout
  // reinitialiser » le fait — ecrivait donc son resultat dans un noeud detache,
  // et l'utilisateur ne voyait RIEN. Sur la plus destructive des actions, cela
  // emportait le CHEMIN DE SAUVEGARDE, c'est-a-dire le seul moyen de revenir en
  // arriere.
  const noeudDeSortie = () => {
    const racine = _state.containerRef;
    if (racine && idSection) {
      const frais = racine.querySelector(`[data-section-actions-out="${idSection}"]`);
      if (frais) return frais;
    }
    return sortie;
  };

  // `textContent` et non `innerHTML` : la reponse du backend n'est PAS de la
  // mise en forme, et l'echapper serait a la fois inutile et visible
  // (`&amp;` a l'ecran). Le rendu ci-dessus ne produit donc aucune balise.
  const ecrire = (texte, classe) => {
    const cible = noeudDeSortie();
    if (!cible) return;
    cible.textContent = texte;
    cible.className = `parametres-section-actions-out parametres-section-actions-out--${classe}`;
  };
  // Une action destructive DOIT nommer sa consequence avant de partir. La regle
  // du depot l'exige, et c'est le seul endroit ou l'utilisateur peut encore dire
  // non — apres, l'effet est fait.
  //
  // LE CONTRAT DE `dangerConfirmModal` EST PAR RAPPEL, PAS PAR PROMESSE. Mesure
  // sur le source : la fonction n'est pas `async` et ne porte AUCUN `return`
  // avec valeur. Une premiere version de ce code faisait
  // `const accepte = await dangerConfirmModal({...}); if (!accepte) return;` :
  // `accepte` valait donc toujours `undefined`, et l'action ne partait JAMAIS.
  // Elle passait aussi `body:`, option que la modale ne destructure pas — la
  // consequence etait silencieusement jetee, en violation de la regle n3.
  // Les 12 autres sites d'appel du depot utilisent tous `consequence` +
  // `onConfirm` ; celui-ci etait le seul a s'en ecarter.
  if (action.confirmation) {
    const conf = action.confirmation;
    dangerConfirmModal({
      title: conf.titre,
      items: conf.elements || [],
      consequence: conf.corps,
      confirmLabel: conf.libelle,
      // Le delai vient de la TABLE, jamais d'un defaut implicite : sans cette
      // ligne, `dangerConfirmModal` le graduerait sur `items.length` — et
      // l'absence de delai passerait pour un choix alors que ce serait un
      // silence. Cf. `motifSansDelai` a cote de chaque confirmation, et le garde
      // `tests/test_actions_integration_parametres.py`.
      countdownSeconds: conf.delaiSecondes,
      requireTyped: conf.motAConfirmer || "",
      // LA SAISIE PART TELLE QUELLE. Envoyer `conf.motAConfirmer` a la place
      // rendrait le garde du backend decoratif : il verifierait une constante
      // que ce fichier lui aurait fournie, quoi que l'utilisateur ait tape.
      onConfirm: (saisie) =>
        _executerActionDeSection(
          action,
          route,
          btn,
          ecrire,
          conf.parametre ? { [conf.parametre]: saisie } : {}
        ),
    });
    return;
  }
  return _executerActionDeSection(action, route, btn, ecrire);
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
      <div class="parametres-section-body">${extraTop}${fields}${_renderSectionActions(section)}</div>
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

/**
 * Restaure le brouillon de profil aux valeurs par defaut — CELLES DU BACKEND.
 *
 * POURQUOI ON LES DEMANDE PLUTOT QUE DE LES RECOPIER. La version precedente
 * repartait de `_DEFAULT_TIERS` et `_DEFAULT_WEIGHTS`, deux constantes ecrites
 * ici. Le commentaire de `_DEFAULT_TIERS` garde la trace de ce que ca a coute :
 * la grille 85/68/54/30 avait ete ECRITE EN BASE au save de profil, alors que
 * le scoring en appliquait une autre. Une valeur par defaut recopiee dans le
 * front est une verite en double, et une verite en double finit par diverger.
 *
 * `quality/reset_quality_profile` avec `dry_run` rend le profil canonique sans
 * rien ecrire — seuils ET poids. C'est la seule source qui ne peut pas mentir.
 *
 * Si l'appel echoue, on le DIT et on ne touche a rien : restaurer des valeurs
 * inventees serait exactement le defaut qu'on corrige.
 */
async function _reinitialiserLeBrouillonDeProfil() {
  let canonique = null;
  try {
    const res = await apiPost("quality/reset_quality_profile", { dry_run: true });
    const data = (res && res.data) || res || {};
    if (data.ok !== false && data.profile && typeof data.profile === "object") canonique = data.profile;
  } catch {
    canonique = null;
  }
  if (!canonique) {
    _showProfilMessage(
      "Les valeurs par défaut n'ont pas pu être lues ; rien n'a été modifié. Réessayez.",
      "error"
    );
    return;
  }
  _state.profileDraft = {
    id: "",
    label: "",
    tiers: { ...(canonique.tiers || {}) },
    weights: { ...(canonique.weights || {}) },
    tier_hierarchy: _mergeTierHierarchy(canonique.tier_hierarchy),
  };
  _showProfilMessage(
    "Seuils, poids et hiérarchie restaurés aux valeurs par défaut. Cliquez sur Sauvegarder pour créer un profil.",
    "info"
  );
  _rerenderActiveCategory();
}

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
          // VP-B : tier_hierarchy charge depuis profil backend (default OFF).
          tier_hierarchy: _mergeTierHierarchy(active.tier_hierarchy),
        };
      } else {
        _state.profileDraft = {
          id: "", label: "",
          tiers: { ..._DEFAULT_TIERS },
          weights: { ..._DEFAULT_WEIGHTS },
          tier_hierarchy: { ..._DEFAULT_TIER_HIERARCHY, order: _DEFAULT_HIERARCHY_DIMENSIONS.slice() },
        };
      }
    }
  } catch (_e) {
    _state.profilesList = [];
    _state.profileDraft = {
      id: "", label: "",
      tiers: { ..._DEFAULT_TIERS },
      weights: { ..._DEFAULT_WEIGHTS },
      tier_hierarchy: { ..._DEFAULT_TIER_HIERARCHY, order: _DEFAULT_HIERARCHY_DIMENSIONS.slice() },
    };
  }
}

// VP-B : merge tier_hierarchy backend vers shape canonique UI (default OFF
// si profil legacy sans cle). Filtre les dimensions inconnues (backend deja
// resilient mais on prefere belt-and-suspenders cote UI).
function _mergeTierHierarchy(raw) {
  const out = { ..._DEFAULT_TIER_HIERARCHY, order: _DEFAULT_HIERARCHY_DIMENSIONS.slice() };
  if (!raw || typeof raw !== "object") return out;
  if (typeof raw.enabled === "boolean") out.enabled = raw.enabled;
  if (Array.isArray(raw.order)) {
    const filtered = raw.order.filter((d) => _DEFAULT_HIERARCHY_DIMENSIONS.includes(d));
    if (filtered.length > 0) out.order = filtered;
  }
  return out;
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
          tier_hierarchy: _mergeTierHierarchy(active.tier_hierarchy),
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
  // Validation somme poids. La forme canonique du backend est en POINTS DE
  // POURCENTAGE (somme 100) : `default_quality_profile()["weights"]` vaut
  // {video: 60, audio: 30, extras: 10}. L'ancienne validation exigeait ~1.00 et
  // aurait donc refuse tout profil reel.
  const total = Object.values(draft.weights).reduce((s, v) => s + (Number(v) || 0), 0);
  if (Math.abs(total - _SOMME_POIDS) > _TOLERANCE_POIDS) {
    _showProfilMessage(`Erreur : somme des poids = ${Math.round(total)}, doit être ~${_SOMME_POIDS} (± ${_TOLERANCE_POIDS}).`, "error");
    return;
  }
  // Fix audit 2026-06-07 UX medium : window.prompt natif est interdit (memoire
  // user actions_dangereuses + casse l'UX WebView2). Remplacement par une
  // modale custom avec validation cote UI (regex + longueur).
  await _promptNewProfileName(async (name) => {
    const profile = {
      id: String(name).trim(),
      label: String(name).trim(),
      description: "Profil personnalisé",
      version: 1,
      tiers: draft.tiers,
      weights: draft.weights,
      // VP-B : transmet la config hierarchie (OFF par defaut). Backend
      // normalise via validate_quality_profile -> normalize_hierarchy_config.
      tier_hierarchy: draft.tier_hierarchy || { ..._DEFAULT_TIER_HIERARCHY },
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
  });
}

/* Revue post-merge 2026-08-03 — deux defauts cumules sur la saisie du nom :
 *
 * (1) MESSAGE D'ERREUR INVISIBLE. components/modal.js appelle `onClick()` PUIS
 *     `closeModal()` sans condition, et closeModal fait `overlay.remove()` de
 *     maniere synchrone : le texte etait donc ecrit dans un noeud DEJA DETACHE
 *     et n'atteignait jamais l'ecran. La modale rouverte repartait en plus de la
 *     valeur par defaut, effacant la saisie. Symptome vecu : le champ redevient
 *     « MonProfil_v1 », rien n'explique pourquoi, l'utilisateur reboucle.
 *     Correctif : on transmet la saisie ET le motif du refus a la modale
 *     rouverte, au lieu d'ecrire dans un noeud mort.
 *
 * (2) REGEX ASCII DANS UNE UI FRANCAISE. `[A-Za-z0-9 _-]` refusait tout accent :
 *     « Qualité max », « Ciné 4K » etaient rejetes — le cas courant, pas un cas
 *     tordu. On accepte desormais lettres et chiffres Unicode, espace,
 *     apostrophe, tiret et underscore. `/`, `\`, `.`, `:` et les caracteres de
 *     controle restent exclus (le nom sert d'`id` de profil ; il n'est jamais
 *     transforme en chemin cote backend — il est stocke dans
 *     settings.custom_quality_profiles — mais on garde la liste courte).
 *
 *     `\p{M}` (marques combinantes) est inclus en plus de `\p{L}` : un « é »
 *     colle depuis un texte en forme NFD est la sequence « e » + U+0301, que
 *     `\p{L}` seul refuse. Mesure faite avec la regex reelle : « Qualité max »
 *     passe en NFC et echouait en NFD. Une marque combinante ne peut etre ni un
 *     separateur de chemin ni un caractere de controle.
 */
const _PROFILE_NAME_RE = /^[\p{L}\p{M}\p{N} '’_-]{3,40}$/u;
const _PROFILE_NAME_HELP =
  "3 à 40 caractères. Lettres (accents acceptés), chiffres, espaces, apostrophes, tirets, underscores.";
const _PROFILE_NAME_DEFAULT = "MonProfil_v1";

/**
 * Modale custom pour demander un nom de profil. Remplace window.prompt() natif
 * (incompatible WebView2, viole la memoire user "JAMAIS window.prompt/confirm/alert").
 *
 * @param {Function} onSubmit - appele avec le nom valide.
 * @param {{initialValue?: string, errorMessage?: string}} [opts] - etat reinjecte
 *        quand la modale se rouvre apres un refus de validation.
 */
function _promptNewProfileName(onSubmit, opts) {
  return new Promise((resolve) => {
    const initialValue = opts && opts.initialValue != null ? String(opts.initialValue) : _PROFILE_NAME_DEFAULT;
    const errorMessage = opts && opts.errorMessage ? String(opts.errorMessage) : "";
    const bodyHtml = `
      <p>Saisissez un nom pour le nouveau profil qualité.</p>
      <label class="parametres-profile-name-label" for="parametres-profile-name-input">Nom du profil</label>
      <input id="parametres-profile-name-input" type="text" class="v5-input" value="${escapeHtml(initialValue)}"
             autocomplete="off" spellcheck="false" data-parametres-profile-name-input
             style="width:100%;margin-top:4px;">
      <p class="text-muted font-sm mt-2" data-parametres-profile-name-error
         ${errorMessage ? 'role="alert"' : ""}
         style="min-height:1.2em;${errorMessage ? "color:#DC2626;font-weight:600;" : ""}">
        ${escapeHtml(errorMessage || _PROFILE_NAME_HELP)}
      </p>
    `;
    showModal({
      title: "Nouveau profil qualité",
      body: bodyHtml,
      actions: [
        { label: "Annuler", cls: "", onClick: () => { resolve(); } },
        { label: "Créer", cls: "btn-primary", onClick: () => {
          const overlay = document.getElementById("dashModal");
          const input = overlay?.querySelector("[data-parametres-profile-name-input]");
          const value = input?.value?.trim() || "";
          if (!_PROFILE_NAME_RE.test(value)) {
            // modal.js va fermer la modale quoi qu'il arrive : inutile d'ecrire
            // dans l'overlay courant (il sera detache). On rouvre en portant le
            // motif du refus ET la saisie de l'utilisateur.
            setTimeout(() => {
              _promptNewProfileName(onSubmit, {
                initialValue: value,
                errorMessage: `Nom invalide. ${_PROFILE_NAME_HELP}`,
              }).then(resolve);
            }, 0);
            return;
          }
          // OK : execute la callback puis resolve
          Promise.resolve(onSubmit(value)).finally(() => resolve());
        } },
      ],
    });
  });
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

/**
 * Transforme le SVG renvoye par le backend en URL `data:` affichable par <img>.
 *
 * Cf issue #555. Le SVG etait interpole tel quel dans `host.innerHTML`, alors
 * que l'URL voisine passait deja par `_esc()` — asymetrie dans le meme
 * template. Le rendu en <img> supprime la classe entiere du probleme plutot
 * que de la filtrer :
 *
 *  - un SVG charge en contexte IMAGE ne peut ni executer de script (<script>,
 *    on*, javascript:) ni charger de ressource externe : c'est la specification
 *    SVG, pas une liste noire de balises qu'il faudrait maintenir ;
 *  - `encodeURIComponent` percent-encode `<`, `>`, `"`, `'` et `&`, donc la
 *    chaine ne peut pas non plus sortir de l'attribut `src` pour injecter du
 *    HTML dans la page.
 *
 * Le CSP du dashboard autorise deja `img-src 'self' data:`.
 * Retourne "" si l'entree est vide, pour que l'appelant n'affiche rien.
 */
function _qrSvgToDataUri(svg) {
  const raw = String(svg == null ? "" : svg).trim();
  if (!raw) return "";
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(raw)}`;
}

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
  const qrDataUri = _qrSvgToDataUri(qrSvg);
  host.innerHTML = `
    ${qrDataUri ? `<div class="parametres-qr-svg"><img src="${qrDataUri}" alt="QR code d'accès au dashboard" decoding="async"></div>` : ""}
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

// F04 (revue adversaire R1) : borne d'attente du flush au montage de la vue
// (cf. _loadSettings). Un save local repond en < 100 ms ; au-dela, mieux vaut
// afficher les parametres que geler l'ecran sur son skeleton.
const FLUSH_WAIT_MAX_MS = 1500;

// F04 (revue post-merge 2026-07-18) : corps du save extrait du setTimeout pour
// pouvoir etre declenche AUSSI hors debounce (flush au demontage de la vue).
// Aucun `opts.signal` volontairement : le flush doit survivre a
// `abortCurrentNav()` que le router appelle juste apres `_currentCleanup()`.
async function _saveSettingsNow() {
  // Seul `savedAt` est garde par `_state.containerRef` : c'est lui qui produisait
  // le badge fantome « ✓ Sauvegarde a HH:MM » au remontage de la vue.
  // F04 (revue adversaire R1) : l'ECHEC, lui, doit etre pose INCONDITIONNELLEMENT
  // (etat module, pas du DOM) et memorise dans `lastFlushError` qui survit au
  // demontage — sinon un flush refuse par le backend perdait l'edition en
  // silence, exactement comme avant le correctif.
  try {
    const res = await apiPost("settings/save_settings", { settings: _state.settings });
    if (res && res.data && (res.data.ok || res.data === true || !res.data.message)) {
      _state.lastFlushError = null;
      if (_state.containerRef) {
        _state.savedAt = new Date();
        _state.saveError = null;
      }
      invalidateSettingsCache();
      _updateSavedIndicator();
    } else {
      const msg = res?.data?.message || "Erreur inconnue";
      _state.saveError = msg;
      _state.lastFlushError = msg;
      _updateSavedIndicator();
    }
  } catch (err) {
    const msg = err?.message || "Erreur réseau";
    _state.saveError = msg;
    _state.lastFlushError = msg;
    _updateSavedIndicator();
  }
}

// F04 (revue adversaire R1) : re-affiche au montage l'echec d'un flush survenu
// pendant que la vue etait demontee. Sans ce rappel, l'utilisateur retrouvait
// son ANCIEN reglage (ecrase par _loadSettings) sans aucun message.
function _surfacePendingFlushError() {
  if (!_state.lastFlushError) return;
  _state.savedAt = null;
  _state.saveError = `Dernière modification NON enregistrée (${_state.lastFlushError}) — vérifiez la valeur et ressaisissez-la.`;
  _updateSavedIndicator();
}

function _scheduleSave() {
  if (_state.saveTimer) clearTimeout(_state.saveTimer);
  _state.saveTimer = setTimeout(() => {
    _state.saveTimer = null;
    _state.saveInFlight = _saveSettingsNow();
  }, 500);
}

// F04 : envoie immediatement le save en attente (debounce non echu). Appele par
// unmountParametres — sans lui, quitter la vue < 500 ms apres une frappe perdait
// silencieusement l'edition (clearTimeout nu, aucun beforeunload dans le dashboard).
function _flushPendingSave() {
  if (!_state.saveTimer) return;
  clearTimeout(_state.saveTimer);
  _state.saveTimer = null;
  _state.saveInFlight = _saveSettingsNow();
}

function _updateSavedIndicator() {
  const el = _state.containerRef?.querySelector("[data-parametres-saved-indicator]");
  if (!el) return;
  if (_state.saveError) {
    el.innerHTML = `<span class="parametres-saved-indicator--error">⚠ ${_esc(_state.saveError)}</span>`;
    return;
  }
  if (_state.savedAt) {
    // Fix audit 2026-06-07 UX high : badge persistant avec horodatage HH:MM:SS
    // au lieu d'un toast 2500ms qui disparait. L'utilisateur a tout moment voit
    // la derniere heure de sauvegarde, meme s'il scrolle ou regarde ailleurs.
    let timeLabel = "";
    try {
      timeLabel = _state.savedAt.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch (_e) { timeLabel = ""; }
    el.innerHTML = `<span class="parametres-saved-indicator--ok">✓ Sauvegardé${timeLabel ? ` à ${_esc(timeLabel)}` : ""}</span>`;
  } else {
    el.innerHTML = "";
  }
}

async function _loadSettings() {
  // F04 : si un flush de sauvegarde est encore en vol (quitte puis revenu sur
  // la vue en moins d'un aller-retour reseau), on l'attend avant de relire le
  // serveur — sinon on recharge un etat pre-save et l'edition est perdue.
  //
  // F04 (revue adversaire R1) : attente BORNEE. Cet await est sur le chemin de
  // MONTAGE de la vue (initParametres, bloc aria-busy) et l'apiPost du flush
  // part sans `timeoutMs`, avec jusqu'a 3 retries + backoff (core/api.js) : sans
  // borne, l'ecran Parametres restait fige sur son skeleton tant que le POST
  // n'avait pas repondu. Au-dela de la borne on relit le serveur sans attendre ;
  // un echec tardif reste signale par `lastFlushError`.
  const pendingSave = _state.saveInFlight;
  if (pendingSave) {
    let waitTimer = null;
    const bound = new Promise((resolve) => { waitTimer = setTimeout(resolve, FLUSH_WAIT_MAX_MS); });
    try {
      await Promise.race([Promise.resolve(pendingSave).catch(() => {}), bound]);
    } finally {
      if (waitTimer) clearTimeout(waitTimer);
    }
    if (_state.saveInFlight === pendingSave) _state.saveInFlight = null;
  }
  const res = await apiPost("settings/get_settings", {});
  // BUG USER #1 : si get_settings echoue (401, 429, 5xx...), `res.data` est
  // un objet d'erreur `{ok: false, message: "..."}`. L'ancien code l'assignait
  // silencieusement a `_state.settings`, ce qui faisait croire que le
  // chargement avait reussi. Au premier toggle (Mode expert), `_scheduleSave`
  // partait POSTer cet objet d'erreur + retombait sur le meme 401 -> badge
  // rouge "Authentification refusee par le backend." dans l'indicateur de
  // sauvegarde, alors que la vraie cause est l'echec initial. On detecte
  // explicitement l'erreur et on throw pour que `initParametres` affiche le
  // banner d'erreur avec bouton "Reessayer" (parcours UX clair).
  if (!res || !res.data || typeof res.data !== "object" || res.data.ok === false) {
    const msg = res?.data?.message || `Erreur ${res?.status || "inconnue"}.`;
    throw new Error(msg);
  }
  _state.settings = res.data.data || res.data || {};
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
        <!-- DUPLICATION DELIBEREE de l'option requireTyped de modal.js, et il
             faut le dire ici sinon quelqu'un corrigera l'une des deux.
             Cette modale porte un SELECTEUR DE PORTEE (reglages / base / tout)
             que dangerConfirmModal ne sait pas rendre : la consolider
             demanderait de lui ajouter un formulaire arbitraire, donc d'en
             faire autre chose qu'une confirmation. Les deux implementations
             partagent la propriete qui compte : les deux verrous, mot tape et
             decompte, sont INDEPENDANTS. -->
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

  // R8-078 (F6-a) : piège de focus Tab/Shift+Tab — même helper partagé que les modales
  // standard (modal.js). Le handler est posé sur l'overlay -> nettoyé automatiquement par
  // overlay.remove() dans close(). AVANT : aucun trap -> le focus s'échappait vers le fond.
  trapFocus(overlay);

  const input = overlay.querySelector("[data-parametres-reset-input]");
  const confirmBtn = overlay.querySelector("[data-parametres-reset-confirm]");
  const cancelBtn = overlay.querySelector("[data-parametres-reset-cancel]");
  const countdownEl = overlay.querySelector("[data-parametres-reset-countdown]");
  // R8-078 (F6-a) : focus initial dans la modale (comme les modales standard) -> le trap
  // démarre avec le focus à l'intérieur.
  if (input) { try { input.focus(); } catch (_e) { /* noop */ } }
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
      // `dry_run: false` EXPLICITE. Le defaut des deux routes est passe a True :
      // elles sont exposees en POST et n'ont aucun argument obligatoire, donc un
      // appel au corps vide effacait la base ou reinitialisait tous les reglages.
      // Ici l'utilisateur a saisi CONFIRMER puis attendu le compte a rebours :
      // l'intention est etablie, on la dit au serveur.
      if (scope === "__database__") {
        res = await apiPost("settings/reset_database", { dry_run: false });
      } else {
        res = await apiPost("settings/reset_settings", { scope, dry_run: false });
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
        // `error` EST LA CLE DE CETTE ROUTE, ET C'EST LA SEULE QU'ELLE EMET.
        // `reset_support` renvoie tous ses refus sous `key="error"` — dont
        // « Un traitement est en cours (<run>) : arretez-le avant de … », qui
        // est la seule chose utile a dire a cet instant. Sans cette lecture,
        // l'ecran affichait « Reset impossible » et rien d'autre : l'utilisateur
        // ne pouvait pas savoir qu'il lui suffisait d'arreter son scan.
        //
        // Le meme defaut a ete corrige dans `_executerActionDeSection` ; ce
        // site-ci, voisin, avait ete oublie — les deux lisent desormais la meme
        // famille de cles.
        const raison = res?.data?.user_message || res?.data?.message || res?.data?.error || "Reset impossible";
        if (ind) ind.innerHTML = `<span class="parametres-saved-indicator--error">⚠ ${_esc(raison)}</span>`;
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
      // Fix audit 2026-06-08 UX medium : si le champ a un testMethod, effacer le
      // resultat affiche apres modification (sinon "✓ Connexion réussie" reste
      // affiche pour une valeur differente non encore testee).
      if (field.testMethod) {
        const resEl = container.querySelector(`[data-test-result-for="${key}"]`);
        if (resEl) { resEl.textContent = ""; resEl.className = "parametres-test-result"; }
      }
      _scheduleSave();
    };
    if (field.type === "toggle" || field.type === "select") fieldEl.addEventListener("change", handler);
    else fieldEl.addEventListener("input", handler);
  });

  // API-key show/hide
  // LOTC-B3 : le GET settings renvoie le masque SEC-H3 ('••••••••') pour
  // rest_api_token — basculer input.type revelait (et 📋 copiait) le MASQUE,
  // 401 garanti cote appareil distant. On resout le vrai Bearer via
  // settings/reveal_rest_token (R7-10, refuse hors localhost) avant d'afficher.
  let _realRestToken = null;
  const _isMaskedToken = (v) => /^[•*]+$/.test(String(v || "").trim());
  const _restMsg = (text, isError) => {
    const el = container.querySelector("[data-rest-token-msg]");
    if (!el) return;
    el.textContent = text;
    el.className = "parametres-test-result" + (text ? (isError ? " parametres-test-result--error" : " parametres-test-result--ok") : "");
  };
  const _getRealRestToken = async () => {
    if (_realRestToken != null) return _realRestToken;
    try {
      const res = await apiPost("settings/reveal_rest_token");
      const d = (res && res.data) || res || {};
      if (d.ok && d.rest_api_token) {
        _realRestToken = String(d.rest_api_token);
        return _realRestToken;
      }
    } catch (_e) { /* refuse (distant) ou reseau : message cote appelant */ }
    return null;
  };
  container.querySelectorAll("[data-api-key-toggle]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.apiKeyToggle;
      const input = container.querySelector("#" + id);
      if (!input) return;
      const reveal = input.type === "password";
      if (input.dataset.fieldKey === "rest_api_token") {
        if (reveal && _isMaskedToken(input.value)) {
          const real = await _getRealRestToken();
          if (!real) { _restMsg("Clé révélable en local uniquement.", true); return; }
          input.value = real;
          _restMsg("", false);
        } else if (!reveal && _realRestToken != null && input.value === _realRestToken) {
          // Re-masquage : restaurer le masque du GET pour ne pas laisser le
          // vrai token dans le DOM (sans toucher _state.settings ni l'autosave ;
          // une saisie manuelle de l'utilisateur est preservee telle quelle).
          input.value = String(_state.settings.rest_api_token || "");
        }
      }
      input.type = reveal ? "text" : "password";
    });
  });

  // Actions d'integration (vague B2) : rapports de coherence, rafraichissements,
  // email de test. Une seule delegation pour les cinq, la route etant portee par
  // le bouton — c'est la meme discipline declarative que le reste de la page.
  container.querySelectorAll("[data-section-action]").forEach((btn) => {
    btn.addEventListener("click", () => _lancerActionDeSection(container, btn));
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
          // Fix audit 2026-06-08 UX medium : afficher infos de diagnostic riches
          // retournees par le backend (server_name, version, movies_count,
          // libraries) au lieu d'un simple "Connexion reussie".
          if (ok) {
            const parts = [];
            if (payload.server_name) parts.push(String(payload.server_name));
            if (payload.version) parts.push(`v${payload.version}`);
            const counts = [];
            if (typeof payload.movies_count === "number") counts.push(`${payload.movies_count} films`);
            else if (Array.isArray(payload.libraries) && payload.libraries.length) counts.push(`${payload.libraries.length} bibliothèques`);
            const head = parts.length ? ` — ${parts.join(" ")}` : "";
            const tail = counts.length ? ` (${counts.join(", ")} détectés)` : "";
            resultEl.textContent = `✓ Connexion réussie${head}${tail}`;
          } else {
            resultEl.textContent = `✗ Échec : ${payload.message || payload.error || "inconnu"}`;
          }
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
        // LOTC-B3 : le champ peut contenir le masque SEC-H3 -> copier la vraie
        // valeur revelee, jamais les puces.
        let value = tokenInput.value;
        if (_isMaskedToken(value)) {
          const real = await _getRealRestToken();
          if (!real) { _restMsg("Clé copiable en local uniquement.", true); return; }
          value = real;
        }
        await navigator.clipboard.writeText(value);
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
          _realRestToken = b64; // LOTC-B3 : l'ancien token revele est perime

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

  // VQ-2 QUARANTAINE-TTL : viewer du bucket _review (route /quarantine_viewer).
  // Inventaire lecture seule des fichiers en quarantaine, trie par mtime DESC.
  container.querySelectorAll('[data-action="quarantine_viewer"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const resultEl = container.querySelector('[data-action-result-for="quarantine_viewer"]');
      btn.disabled = true;
      if (resultEl) { resultEl.textContent = "Chargement…"; resultEl.className = "parametres-test-result parametres-test-result--info"; }
      try {
        const res = await apiPost("run/list_quarantine_bucket", { limit: 500 });
        const data = res && res.data ? res.data : res;
        if (!data || data.ok === false) {
          throw new Error((data && (data.message || data.error)) || "Echec inventaire.");
        }
        const total = Number(data.files_count || 0);
        const sizeBytes = Number(data.total_size_bytes || 0);
        const sizeMo = sizeBytes > 0 ? (sizeBytes / 1024 / 1024).toFixed(1) : "0";
        if (!data.exists) {
          if (resultEl) {
            resultEl.textContent = "Bucket _review absent (rien à afficher).";
            resultEl.className = "parametres-test-result parametres-test-result--info";
          }
          return;
        }
        const subdirCounts = Object.entries(data.by_subdir || {})
          .map(([k, v]) => `${escapeHtml(k)} : ${v?.count || 0}`)
          .join(" · ");
        const sample = (data.files || []).slice(0, 20).map((f) => {
          const age = Number(f.age_days || 0).toFixed(1);
          const sub = escapeHtml(String(f.subdir || ""));
          const rel = escapeHtml(String(f.rel || f.path || ""));
          return `<li><code>${rel}</code> <span class="parametres-muted">(${sub}, ${age}j)</span></li>`;
        }).join("");
        if (resultEl) {
          resultEl.innerHTML = `
            <div><strong>${total}</strong> fichier(s) en quarantaine · <strong>${sizeMo} Mo</strong></div>
            <div class="parametres-muted">${subdirCounts || "(vide)"}</div>
            ${sample ? `<ul class="parametres-quarantine-sample">${sample}</ul>` : ""}
            ${total > 20 ? `<div class="parametres-muted">(${total - 20} fichier(s) supplémentaire(s) non listé(s))</div>` : ""}
          `;
          resultEl.className = "parametres-test-result parametres-test-result--ok";
        }
      } catch (err) {
        if (resultEl) { resultEl.textContent = `✗ Erreur : ${err?.message || err}`; resultEl.className = "parametres-test-result parametres-test-result--error"; }
      } finally {
        btn.disabled = false;
      }
    });
  });

  // VQ-2 QUARANTAINE-TTL : bouton "Vider maintenant" — DANGEREUX.
  // Memoire actions dangereuses utilisateur : dangerConfirmModal OBLIGATOIRE
  // avec liste elements + consequence + countdown 3s si > 50 fichiers.
  container.querySelectorAll('[data-action="quarantine_purge_all"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const resultEl = container.querySelector('[data-action-result-for="quarantine_purge_all"]');
      btn.disabled = true;
      try {
        // 1) On interroge le bucket pour avoir un decompte fiable (declenche
        // le countdown 3s si > 50 fichiers, exigence memoire utilisateur).
        // FIX #2/#6/#10 : la modale doit refleter ce que "Vider maintenant"
        // supprime REELLEMENT (purge_review_bucket_all scope <root>/_review sauf
        // _duplicates_user_decided), pas l'agregat viewer files_count qui inclut
        // aussi les buckets runs et les decisions preservees -> l'utilisateur
        // confirmait N et obtenait deleted << N. On utilise donc le perimetre
        // purgeable (purge_scope_*) et un echantillon filtre au meme perimetre.
        let total = 0;
        let sample = [];
        let sizeMo = "0";
        try {
          const listRes = await apiPost("run/list_quarantine_bucket", { limit: 50 });
          const listData = listRes && listRes.data ? listRes.data : listRes;
          if (listData && listData.ok !== false) {
            total = Number(listData.purge_scope_files_count || 0);
            // R2 : echantillon backend aligne sur le perimetre purgeable
            // (purge_scope_sample) — l'ancien filtre sur `files` (top-50 toutes
            // buckets) pouvait etre vide alors que total > 0. Fallback conserve.
            sample = Array.isArray(listData.purge_scope_sample) && listData.purge_scope_sample.length
              ? listData.purge_scope_sample.slice(0, 10)
              : (listData.files || [])
                  .filter((f) => !f.source_root && f.subdir !== "_duplicates_user_decided")
                  .slice(0, 10)
                  .map((f) => f.rel || f.path);
            const sizeBytes = Number(listData.purge_scope_size_bytes || 0);
            sizeMo = sizeBytes > 0 ? (sizeBytes / 1024 / 1024).toFixed(1) : "0";
          }
        } catch (_listErr) {
          // best-effort, on continue meme si l'inventaire echoue
        }

        if (total === 0) {
          if (resultEl) {
            resultEl.textContent = "Bucket déjà vide.";
            resultEl.className = "parametres-test-result parametres-test-result--info";
          }
          btn.disabled = false;
          return;
        }

        const sampleHtml = sample.length
          ? `<ul class="parametres-quarantine-sample">${sample.map((s) => `<li><code>${escapeHtml(String(s))}</code></li>`).join("")}</ul>`
          : "";
        dangerConfirmModal({
          title: `Vider le bucket _review (${total} fichier(s)) ?`,
          consequence: `Cette action va supprimer définitivement <strong>${total}</strong> fichier(s) en quarantaine (~${sizeMo} Mo). Les décisions de doublons (_duplicates_user_decided) sont préservées. ${sampleHtml}`,
          // Regle n3 : delai derive du nombre de fichiers reellement purgeables
          // par la modale (`gradedCountdownSeconds`). La ternaire
          // `total > 50 ? 3 : 0` qui vivait ici rendait 0 s entre 42 et 50
          // fichiers, la ou la regle partagee rend 1 s.
          itemCount: total,
          // MOT A TAPER : la perte est IRRECUPERABLE PAR L'APPLICATION
          // (`_purge_dir_recursive` supprime definitivement — ni corbeille, ni
          // sauvegarde) et la portee n'est PAS une selection de l'utilisateur :
          // c'est « tous les fichiers en quarantaine ». Les deux conditions du
          // critere sont remplies ; cf. la docstring de `dangerConfirmModal`.
          requireTyped: "VIDER",
          confirmLabel: "Vider maintenant",
          cancelLabel: "Annuler",
          onConfirm: async () => {
            if (resultEl) { resultEl.textContent = "Suppression en cours…"; resultEl.className = "parametres-test-result parametres-test-result--info"; }
            try {
              const res = await apiPost("run/purge_quarantine_bucket_all", { dry_run: false });
              const data = res && res.data ? res.data : res;
              if (!data || data.ok === false) {
                throw new Error((data && (data.message || data.error)) || "Echec suppression.");
              }
              const deleted = Number(data.deleted || 0);
              const freedMo = Number(data.bytes_freed || 0) / 1024 / 1024;
              if (resultEl) {
                resultEl.textContent = `✓ ${deleted} fichier(s) supprimé(s) (${freedMo.toFixed(1)} Mo libérés).`;
                resultEl.className = "parametres-test-result parametres-test-result--ok";
              }
            } catch (err) {
              if (resultEl) { resultEl.textContent = `✗ Erreur : ${err?.message || err}`; resultEl.className = "parametres-test-result parametres-test-result--error"; }
            } finally {
              btn.disabled = false;
            }
          },
          onCancel: () => { btn.disabled = false; },
        });
      } catch (err) {
        if (resultEl) { resultEl.textContent = `✗ Erreur : ${err?.message || err}`; resultEl.className = "parametres-test-result parametres-test-result--error"; }
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

  // VO-B-CONFIG : Scan parallele (tri-etat workers auto/manuel)
  _bindScanMaxWorkersActions(container);
  if (container.querySelector("[data-scan-workers-host]") && _state.scanMaxWorkersState === null && !_state.scanMaxWorkersLoading) {
    _loadScanMaxWorkersState(container);
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

/* =============================================================
 * VO-B-CONFIG : Scan parallele (tri-etat workers auto/manuel)
 * ============================================================= */

/**
 * Refresh le panneau "Scan" sans full re-render. Re-attache les handlers
 * (idempotent via data-bound).
 */
function _refreshScanMaxWorkersPanel(container) {
  const host = container.querySelector("[data-scan-workers-host]");
  if (!host) return;
  host.innerHTML = _renderScanMaxWorkersSection(_state.scanMaxWorkersState);
  _bindScanMaxWorkersActions(container);
}

/**
 * Charge l'etat initial via settings/get_scan_max_workers.
 */
async function _loadScanMaxWorkersState(container) {
  _state.scanMaxWorkersLoading = true;
  _refreshScanMaxWorkersPanel(container);
  try {
    const res = await apiPost("settings/get_scan_max_workers", {});
    const data = res && res.data ? res.data : res;
    if (data && data.ok) {
      _state.scanMaxWorkersState = data;
    } else {
      _state.scanMaxWorkersState = null;
    }
  } catch (err) {
    _state.scanMaxWorkersState = null;
  } finally {
    _state.scanMaxWorkersLoading = false;
    _refreshScanMaxWorkersPanel(container);
  }
}

/**
 * Applique la combinaison (mode, value) via settings/set_scan_max_workers.
 */
async function _applyScanMaxWorkers(container, mode, value, msgEl) {
  if (msgEl) msgEl.textContent = "Application en cours…";
  try {
    const payload = { mode: String(mode || "auto") };
    if (mode === "manual") {
      payload.value = Number(value);
    }
    const res = await apiPost("settings/set_scan_max_workers", payload);
    const data = res && res.data ? res.data : res;
    if (data && data.ok) {
      _state.scanMaxWorkersState = {
        ...(_state.scanMaxWorkersState || {}),
        mode: data.mode,
        value: data.value,
        effective: data.effective,
        storage_detected: data.storage_detected,
        auto_suggestion: data.auto_suggestion,
        min: data.min,
        max: data.max,
      };
      _refreshScanMaxWorkersPanel(container);
      const newMsg = container.querySelector("[data-scan-workers-message]");
      if (newMsg) newMsg.textContent = "✓ Configuration scan enregistrée.";
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
 * Bind des handlers select mode + input value.
 *
 * Memoire user "Pas de window.confirm/alert/prompt" : aucune dialog native.
 * Le toggle mode applique immediatement (changement non-destructif).
 * L'input value applique au blur OU sur Enter (evite N writes intermediaires
 * pendant la frappe).
 */
function _bindScanMaxWorkersActions(container) {
  // Bouton "Recharger" si state null
  const reloadBtn = container.querySelector("[data-scan-workers-reload]");
  if (reloadBtn && reloadBtn.dataset.bound !== "1") {
    reloadBtn.dataset.bound = "1";
    reloadBtn.addEventListener("click", () => _loadScanMaxWorkersState(container));
  }

  // Select mode — change applique direct
  const modeSelect = container.querySelector("[data-scan-workers-mode]");
  if (modeSelect && modeSelect.dataset.bound !== "1") {
    modeSelect.dataset.bound = "1";
    modeSelect.addEventListener("change", async () => {
      const msg = container.querySelector("[data-scan-workers-message]");
      const newMode = String(modeSelect.value || "auto");
      const currentValue = Number(_state.scanMaxWorkersState?.value || 1);
      // Show / hide l'input number selon le mode (UX)
      const wrapper = container.querySelector("[data-scan-workers-value-wrapper]");
      if (wrapper) {
        wrapper.style.display = newMode === "manual" ? "" : "none";
      }
      await _applyScanMaxWorkers(container, newMode, currentValue, msg);
    });
  }

  // Input value (mode manuel uniquement) — applique au blur ou Enter
  const valueInput = container.querySelector("[data-scan-workers-value]");
  if (valueInput && valueInput.dataset.bound !== "1") {
    valueInput.dataset.bound = "1";
    const applyFromInput = async () => {
      const msg = container.querySelector("[data-scan-workers-message]");
      const raw = valueInput.value;
      const n = Number(raw);
      const minVal = Number(_state.scanMaxWorkersState?.min || 1);
      const maxVal = Number(_state.scanMaxWorkersState?.max || 64);
      if (!Number.isFinite(n) || n < minVal || n > maxVal) {
        if (msg) msg.textContent = `Valeur invalide : doit être un entier entre ${minVal} et ${maxVal}.`;
        return;
      }
      const currentMode = String(_state.scanMaxWorkersState?.mode || "manual");
      // Si l'utilisateur edite la valeur sans avoir bascule en manuel, on bascule pour eux
      const targetMode = currentMode === "manual" ? "manual" : "manual";
      await _applyScanMaxWorkers(container, targetMode, Math.floor(n), msg);
    };
    valueInput.addEventListener("blur", applyFromInput);
    valueInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        applyFromInput();
      }
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
          // Confirmation : DL HTTPS ~110 Mo + écriture dans %LOCALAPPDATA% — action sensible.
          const ok = (typeof window !== "undefined" && typeof window.confirm === "function")
            ? window.confirm(
                "Installer automatiquement ffprobe et MediaInfo ?\n\n"
                + "• Téléchargement HTTPS : environ 110 Mo\n"
                + "• Durée estimée : 1 à 3 minutes\n"
                + "• Empreinte SHA256 vérifiée avant installation : en cas d'écart, rien n'est installé\n"
                + "• Destination : dossier utilisateur (pas besoin d'admin)\n\n"
                + "Confirmer l'installation ?",
              )
            : true;
          if (!ok) {
            _setProbeToolsMessage(container, "Installation annulée.", "info");
            return;
          }
          _setProbeToolsMessage(container, "Installation en cours… (téléchargement HTTP, environ 30-60 s)", "info");
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
          const ok = (typeof window !== "undefined" && typeof window.confirm === "function")
            ? window.confirm(
                "Mettre à jour ffprobe et MediaInfo via winget ?\n\n"
                + "• Utilise Windows Package Manager (doit être installé)\n"
                + "• Met à jour vers les dernières versions disponibles\n\n"
                + "Confirmer la mise à jour ?",
              )
            : true;
          if (!ok) {
            _setProbeToolsMessage(container, "Mise à jour annulée.", "info");
            return;
          }
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
          _setProbeToolsMessage(container, `Vérification de ${tool} en cours…`, "info");
          await _loadProbeToolsStatus(container, { force: true });
          _setProbeToolsMessage(container, `✓ ${tool} vérifié.`, "ok");
        } else if (action === "reinstall") {
          const okR = (typeof window !== "undefined" && typeof window.confirm === "function")
            ? window.confirm(
                `Réinstaller ${tool} via winget ?\n\n`
                + "• Utilise Windows Package Manager\n"
                + "• Remplace la version existante\n\n"
                + "Confirmer la réinstallation ?",
              )
            : true;
          if (!okR) {
            _setProbeToolsMessage(container, "Réinstallation annulée.", "info");
            return;
          }
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
      const v = Math.max(0, Math.min(100, parseInt(ev.target.value, 10) || 0));
      _state.profileDraft.weights[key] = v;
      // MAJ affichage
      const valEl = container.querySelector(`[data-weight-value="${key}"]`);
      if (valEl) valEl.textContent = `${v} %`;
      // MAJ total
      const total = Object.values(_state.profileDraft.weights).reduce((s, x) => s + (Number(x) || 0), 0);
      const totalEl = container.querySelector("[data-weight-total]");
      if (totalEl) {
        const inRange = Math.abs(total - _SOMME_POIDS) <= _TOLERANCE_POIDS;
        totalEl.textContent = `Total = ${Math.round(total)} ${inRange ? "✓" : "⚠"}`;
        totalEl.className = `parametres-weight-total ${inRange ? "parametres-weight-total--ok" : "parametres-weight-total--warning"}`;
      }
    });
  });

  // VP-B (Vague P) : toggle hierarchie qualite (default OFF).
  const hierarchyToggle = container.querySelector("[data-parametres-hierarchy-enabled]");
  if (hierarchyToggle) {
    hierarchyToggle.addEventListener("change", (ev) => {
      if (!_state.profileDraft) {
        _state.profileDraft = {
          id: "", label: "",
          tiers: { ..._DEFAULT_TIERS },
          weights: { ..._DEFAULT_WEIGHTS },
          tier_hierarchy: { ..._DEFAULT_TIER_HIERARCHY, order: _DEFAULT_HIERARCHY_DIMENSIONS.slice() },
        };
      }
      if (!_state.profileDraft.tier_hierarchy) {
        _state.profileDraft.tier_hierarchy = { ..._DEFAULT_TIER_HIERARCHY, order: _DEFAULT_HIERARCHY_DIMENSIONS.slice() };
      }
      _state.profileDraft.tier_hierarchy.enabled = !!ev.target.checked;
    });
  }

  // VP-B : reorder dimensions (haut/bas).
  container.querySelectorAll("[data-hierarchy-move]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const dim = btn.dataset.hierarchyDimTarget;
      const direction = btn.dataset.hierarchyMove;
      if (!dim || !direction) return;
      if (!_state.profileDraft) {
        _state.profileDraft = {
          id: "", label: "",
          tiers: { ..._DEFAULT_TIERS },
          weights: { ..._DEFAULT_WEIGHTS },
          tier_hierarchy: { ..._DEFAULT_TIER_HIERARCHY, order: _DEFAULT_HIERARCHY_DIMENSIONS.slice() },
        };
      }
      const hier = _state.profileDraft.tier_hierarchy
        || (_state.profileDraft.tier_hierarchy = { ..._DEFAULT_TIER_HIERARCHY, order: _DEFAULT_HIERARCHY_DIMENSIONS.slice() });
      const order = Array.isArray(hier.order) && hier.order.length > 0
        ? hier.order.slice()
        : _DEFAULT_HIERARCHY_DIMENSIONS.slice();
      const idx = order.indexOf(dim);
      if (idx === -1) return;
      const swapIdx = direction === "up" ? idx - 1 : idx + 1;
      if (swapIdx < 0 || swapIdx >= order.length) return;
      [order[idx], order[swapIdx]] = [order[swapIdx], order[idx]];
      hier.order = order;
      _rerenderActiveCategory();
    });
  });

  // Le simulateur : une LECTURE, donc aucune confirmation.
  container.querySelectorAll("[data-parametres-ouvrir-simulateur]").forEach((btn) => {
    btn.addEventListener("click", () => ouvrirSimulateurQualite());
  });

  // Les reglages fins : options, calibration et partage. Une LECTURE aussi —
  // l'ecran montre le diff d'un import AVANT d'ecrire quoi que ce soit.
  container.querySelectorAll("[data-parametres-ouvrir-calibration]").forEach((btn) => {
    btn.addEventListener("click", () => ouvrirCalibrationQualite());
  });

  container.querySelectorAll("[data-parametres-ouvrir-regles]").forEach((btn) => {
    // Le builder lit ses regles LUI-MEME, a la source qu'il ecrit. Lui passer
    // `_state.profileDraft.custom_rules` revenait a passer `undefined` : ce
    // brouillon est construit en cinq endroits avec exactement
    // {id, label, tiers, weights, tier_hierarchy}, et un `grep custom_rules` sur
    // ce fichier ne rendait QUE ce site de lecture. L'ecran s'ouvrait donc
    // toujours vide, puis « Enregistrer » DETRUISAIT les regles preexistantes
    // avec un toast de succes.
    btn.addEventListener("click", () => ouvrirReglesQualite());
  });

  // Boutons d'action
  container.querySelectorAll("[data-parametres-profils-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.parametresProfilsAction;
      if (action === "save") _saveProfileAsNew();
      else if (action === "recompute") _recomputeScores();
      else if (action === "reset") _reinitialiserLeBrouillonDeProfil();
    });
  });

  // VP-F (Vague P batch 6) : import/export Recyclarr YAML + breakdown + upgrade_until_score.
  _bindVPFRecyclarrActions(container);
  _bindVPFUpgradeUntilScore(container);
  // Charge le breakdown (lazy ; pas bloquant pour le rendu).
  _loadVPFBreakdown(container);
  // Charge la valeur initiale de upgrade_until_score.
  _loadVPFUpgradeUntilScore(container);
}

/* =============================================================
 * 12bis) VP-F (Vague P batch 6) — Recyclarr import/export + breakdown
 * ============================================================= */

function _showVPFMessage(selector, msg, level) {
  const el = _state.containerRef?.querySelector(selector);
  if (!el) return;
  el.textContent = msg || "";
  el.className = `parametres-profils-message ${level ? `parametres-profils-message--${level}` : ""}`;
}

function _bindVPFRecyclarrActions(container) {
  container.querySelectorAll("[data-vpf-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.vpfAction;
      try {
        if (action === "export-yaml") {
          await _vpfExportRecyclarrYaml();
        } else if (action === "import-yaml") {
          await _vpfImportRecyclarrYaml();
        } else if (action === "show-presets") {
          await _vpfShowEmbeddedPresets();
        }
      } catch (e) {
        _showVPFMessage("[data-vpf-recyclarr-message]", `Erreur : ${e?.message || e}`, "error");
      }
    });
  });
}

async function _vpfExportRecyclarrYaml() {
  const textarea = _state.containerRef?.querySelector("[data-vpf-yaml-textarea]");
  if (!textarea) return;
  _showVPFMessage("[data-vpf-recyclarr-message]", "Export en cours…", "info");
  const res = await apiPost("quality/export_recyclarr_yaml", {});
  if (res && res.data && res.data.ok) {
    textarea.value = res.data.yaml || "";
    _showVPFMessage(
      "[data-vpf-recyclarr-message]",
      `✓ Profil exporté (${res.data.profile_id || "actif"}). Copiez le YAML ci-dessus.`,
      "ok"
    );
  } else {
    _showVPFMessage(
      "[data-vpf-recyclarr-message]",
      `Erreur : ${res?.data?.message || "export impossible"}`,
      "error"
    );
  }
}

async function _vpfImportRecyclarrYaml() {
  const textarea = _state.containerRef?.querySelector("[data-vpf-yaml-textarea]");
  if (!textarea) return;
  const yaml = String(textarea.value || "").trim();
  if (!yaml) {
    _showVPFMessage("[data-vpf-recyclarr-message]", "Collez d'abord du YAML dans la zone.", "warning");
    return;
  }
  _showVPFMessage("[data-vpf-recyclarr-message]", "Import en cours…", "info");
  const res = await apiPost("quality/import_recyclarr_yaml", { yaml_text: yaml, activate: false });
  if (res && res.data && res.data.ok) {
    const lossy = res.data.lossy ? " (reconstruction approximative)" : " (lossless)";
    _showVPFMessage(
      "[data-vpf-recyclarr-message]",
      `✓ Profil "${res.data.profile_id}" importé${lossy}.`,
      "ok"
    );
    // Rafraichit la liste des profils pour faire apparaitre le nouveau custom.
    await _loadProfiles();
    _rerenderActiveCategory();
  } else {
    const errs = Array.isArray(res?.data?.errors) ? ` (${res.data.errors.join(" ; ")})` : "";
    _showVPFMessage(
      "[data-vpf-recyclarr-message]",
      `Erreur : ${res?.data?.message || "import refusé"}${errs}`,
      "error"
    );
  }
}

async function _vpfShowEmbeddedPresets() {
  _showVPFMessage("[data-vpf-recyclarr-message]", "Chargement des presets embarqués…", "info");
  const res = await apiPost("quality/get_embedded_presets", {});
  if (res && res.data && res.data.ok) {
    const presets = res.data.presets || [];
    if (presets.length === 0) {
      _showVPFMessage(
        "[data-vpf-recyclarr-message]",
        "Aucun preset embarqué disponible.",
        "warning"
      );
      return;
    }
    const labels = presets
      .map((p) => `${p.label} (${p.preset_id}) — ${p.enabled_by_default ? "ON" : "OFF par défaut"}`)
      .join("\n");
    _showVPFMessage(
      "[data-vpf-recyclarr-message]",
      `${presets.length} preset(s) embarqué(s) : ${labels}. Tous DÉSACTIVÉS par défaut (AC-3).`,
      "info"
    );
  } else {
    _showVPFMessage(
      "[data-vpf-recyclarr-message]",
      `Erreur : ${res?.data?.message || "chargement impossible"}`,
      "error"
    );
  }
}

function _bindVPFUpgradeUntilScore(container) {
  const saveBtn = container.querySelector('[data-vpf-action="save-upgrade-until"]');
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const input = container.querySelector("[data-vpf-upgrade-input]");
      if (!input) return;
      const score = parseInt(input.value, 10);
      if (Number.isNaN(score) || score < 0 || score > 100000) {
        _showVPFMessage(
          "[data-vpf-upgrade-message]",
          "Valeur invalide (0..100000 attendu).",
          "error"
        );
        return;
      }
      _showVPFMessage("[data-vpf-upgrade-message]", "Enregistrement…", "info");
      try {
        const res = await apiPost("quality/set_upgrade_until_score", { score });
        if (res && res.data && res.data.ok) {
          _showVPFMessage(
            "[data-vpf-upgrade-message]",
            `✓ Score d'arrêt mis à jour : ${res.data.upgrade_until_score}.`,
            "ok"
          );
        } else {
          _showVPFMessage(
            "[data-vpf-upgrade-message]",
            `Erreur : ${res?.data?.message || "sauvegarde refusée"}`,
            "error"
          );
        }
      } catch (e) {
        _showVPFMessage("[data-vpf-upgrade-message]", `Erreur : ${e?.message || e}`, "error");
      }
    });
  }
}

async function _loadVPFUpgradeUntilScore(container) {
  try {
    const res = await apiPost("quality/get_upgrade_until_score", {});
    if (res && res.data && res.data.ok) {
      const input = container.querySelector("[data-vpf-upgrade-input]");
      if (input && typeof res.data.upgrade_until_score === "number") {
        input.value = String(res.data.upgrade_until_score);
      }
    }
  } catch (_e) {
    // Silencieux : le default 10000 est deja dans le HTML.
  }
}

async function _loadVPFBreakdown(container) {
  const host = container.querySelector("[data-vpf-breakdown-host]");
  if (!host) return;
  try {
    const res = await apiPost("quality/get_breakdown_5_axes", {});
    if (res && res.data && res.data.ok) {
      const axes = res.data.axes || [];
      const totalWeight = axes.reduce((s, a) => s + (Number(a.weight) || 0), 0);
      const rows = axes
        .map((a) => {
          const w = Number(a.weight) || 0;
          const pct = totalWeight > 0 ? Math.round((w / totalWeight) * 100) : 0;
          return `<div class="parametres-breakdown-row" data-axis="${escapeHtml(a.id)}">
            <span class="parametres-breakdown-label">${escapeHtml(a.label || a.id)}</span>
            <span class="parametres-breakdown-bar" aria-hidden="true">
              <span class="parametres-breakdown-bar-fill" style="width: ${pct}%"></span>
            </span>
            <span class="parametres-breakdown-value">${w} pts (${pct}%)</span>
          </div>`;
        })
        .join("");
      host.innerHTML = `<div class="parametres-breakdown-grid">${rows}</div>
        <p class="parametres-section-intro">
          Total théorique max : <strong>${totalWeight} pts</strong>. Score d'arrêt
          des upgrades configuré : <strong>${res.data.upgrade_until_score || 10000}</strong>.
        </p>`;
    } else {
      host.innerHTML = `<p class="parametres-section-intro parametres-profils-message--warning">
        Breakdown indisponible : ${escapeHtml(res?.data?.message || "réponse vide")}.
      </p>`;
    }
  } catch (e) {
    host.innerHTML = `<p class="parametres-section-intro parametres-profils-message--error">
      Erreur : ${escapeHtml(e?.message || String(e))}.
    </p>`;
  }
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

/* Ctrl+S — la table de raccourcis de core/keyboard.js (ligne 44) annonce
 * « Enregistrer » a l'utilisateur, et le handler global fait bien un
 * preventDefault() puis emet `cinesort:save-request`. Mais AUCUNE vue n'ecoutait
 * cet evenement : le raccourci bloquait le « Enregistrer » natif du navigateur
 * et ne faisait rien — une promesse affichee mais jamais tenue.
 *
 * Les Parametres sont le seul ecran ou « Enregistrer » a un sens : on y branche
 * le flush du debounce, exactement ce que fait deja la sortie de vue. Ailleurs
 * l'evenement reste sans effet (comportement inchange). */
let _saveRequestHandler = null;

function _installSaveRequest() {
  if (_saveRequestHandler || typeof window === "undefined") return;
  _saveRequestHandler = () => {
    // Pas de save en vol et rien en attente -> ne rien faire (pas de POST inutile).
    if (!_state.saveTimer) return;
    _flushPendingSave();
  };
  window.addEventListener("cinesort:save-request", _saveRequestHandler);
}

function _uninstallSaveRequest() {
  if (_saveRequestHandler && typeof window !== "undefined") {
    window.removeEventListener("cinesort:save-request", _saveRequestHandler);
  }
  _saveRequestHandler = null;
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
  // F04 (revue adversaire R1) : APRES _refreshAll (qui (re)cree l'indicateur
  // dans le DOM), on re-affiche l'echec d'un flush parti au demontage.
  _surfacePendingFlushError();
  _installCtrlK();
  _installSaveRequest();
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
  // F04 : NE PAS annuler le debounce sans l'envoyer. Quitter la vue < 500 ms
  // apres une frappe partait sinon sans jamais POSTer settings/save_settings,
  // et _loadSettings ecrasait l'edition au retour (perte silencieuse).
  _flushPendingSave();
  _uninstallCtrlK();
  _uninstallSaveRequest();
  if (_state.hashChangeHandler && typeof window !== "undefined") {
    window.removeEventListener("hashchange", _state.hashChangeHandler);
    _state.hashChangeHandler = null;
  }
  _state.pendingScrollSection = null;
  _state.containerRef = null;
  _state.searchQuery = "";
  _state.savedAt = null;
  // savedAt/saveError sont de l'etat de VUE : ils repartent a zero.
  // F04 (revue adversaire R1) : `lastFlushError` N'EST PAS remis a zero ici —
  // c'est lui qui porte l'echec du flush declenche par ce demontage meme, et il
  // doit survivre pour etre affiche au prochain montage.
  _state.saveError = null;
}
