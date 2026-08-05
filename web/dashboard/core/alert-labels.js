/* core/alert-labels.js — Mapping warning_flags backend -> libelles humains.
 *
 * Utilisable par toutes les vues qui affichent des warning_flags :
 *   - Modal Validation (lib-validation.js)
 *   - Page Film Detail (film-detail.js, spec 06)
 *   - Doublons / Bibliotheque / Historique (spec 01, 07, 09)
 *
 * Severite :
 *   - critical : action requise (probablement faux match, fichier introuvable)
 *   - warning  : a verifier (subtitle manquant, doublon, NFO incoherent)
 *   - info     : signale sans urgence
 *
 * Source des flags : grep ALL warning_flags.append() dans cinesort/{app,domain}.
 */

const FLAG_MAP = {
  // --- Identification / NFO ---
  nfo_title_mismatch: {
    icon: "🏷",
    label: "Titre NFO incohérent",
    description: "Le titre du fichier .nfo ne correspond pas à celui détecté par CineSort.",
    severity: "warning",
    action: { kind: "open_film", label: "Voir détail" },
  },
  nfo_file_mismatch: {
    icon: "🏷",
    label: "Fichier NFO décalé",
    description: "Le .nfo correspond au dossier mais pas au fichier vidéo (ou inversement) — vidéo probablement déplacée sans MAJ du NFO.",
    severity: "warning",
    action: null,
  },
  nfo_year_mismatch: {
    icon: "📅",
    label: "Année NFO incohérente",
    description: "L'année dans le NFO diffère significativement de celle détectée — possible faux match.",
    severity: "critical",
    action: null,
  },
  title_ambiguity_detected: {
    icon: "🏷",
    label: "Titre ambigu",
    description: "Deux films TMDb portent ce titre (ex : Dune 1984 vs 2021). Vérifier le candidat retenu.",
    severity: "warning",
    action: null,
  },
  year_conflict_folder_file: {
    icon: "📅",
    label: "Année dossier ≠ fichier",
    description: "Le dossier et le fichier vidéo annoncent des années différentes.",
    severity: "warning",
    action: null,
  },
  tmdb_year_delta: {
    icon: "📅",
    label: "Année TMDb décalée",
    description: "L'année du candidat TMDb retenu diffère légèrement de l'année du fichier.",
    severity: "info",
    action: null,
  },
  omdb_disagree: {
    icon: "🔍",
    label: "OMDb en désaccord avec TMDb",
    description: "OMDb et TMDb donnent des titres/années différents pour ce film — vérification croisée échouée.",
    severity: "warning",
    action: null,
  },

  // --- Source / Filesystem ---
  root_level_source: {
    icon: "📁",
    // AUDIT 2026-06-13 (R5-I) : ce flag signale UNIQUEMENT un film pose
    // directement a la racine (plan_support_core.py:707), pas un probleme
    // d'identification ni un fichier "renomme a la main" (un BluRay scene a la
    // racine declenchait a tort ce message trompeur). On dit la verite :
    // le film sera range dans un sous-dossier "Titre (Annee)" a l'application.
    label: "Film à la racine",
    description: "Ce film est posé directement à la racine de la bibliothèque (hors sous-dossier dédié). Il sera rangé dans un dossier « Titre (Année) » lors de l'application.",
    severity: "info",
    action: { kind: "ignore", label: "Ignorer" },
  },
  not_a_movie: {
    icon: "🎬",
    label: "Pas un film ?",
    description: "Le fichier ne ressemble pas à un film de cinéma (probablement épisode, bonus, court-métrage).",
    severity: "critical",
    action: null,
  },
  integrity_header_invalid: {
    icon: "🛡",
    label: "Intégrité fichier invalide",
    description: "L'en-tête du fichier vidéo est corrompu ou illisible — re-télécharger ou vérifier.",
    severity: "critical",
    action: { kind: "rescan", label: "Re-scanner" },
  },
  // VN-A.1 : flag explicite pour exposer probe_quality=FAILED/PARTIAL en UI.
  // Backend : analyze_encode_quality + quality_report_support marquent ce flag
  // quand ffprobe/MediaInfo echouent ou ne renvoient qu'un sous-ensemble des
  // metriques. Avant : l'utilisateur voyait juste un score "weird" sans cause.
  integrity_probe_failed: {
    icon: "🛰",
    label: "Analyse technique incomplète",
    description: "La probe ffprobe/MediaInfo a échoué ou n'a renvoyé qu'une partie des métriques — score qualité partiel.",
    severity: "warning",
    action: { kind: "rescan", label: "Re-scanner" },
  },

  // --- Sous-titres ---
  subtitle_missing_fr: {
    icon: "💬",
    label: "Sous-titres FR manquants",
    description: "Aucun sous-titre français détecté pour ce film.",
    severity: "warning",
    action: { kind: "config_subs", label: "Configurer recherche subs" },
  },
  subtitle_missing_en: {
    icon: "💬",
    label: "Sous-titres EN manquants",
    description: "Aucun sous-titre anglais détecté pour ce film.",
    severity: "warning",
    action: { kind: "config_subs", label: "Configurer recherche subs" },
  },
  subtitle_missing: {
    icon: "💬",
    label: "Sous-titres manquants",
    description: "Aucun sous-titre détecté pour les langues configurées.",
    severity: "warning",
    action: { kind: "config_subs", label: "Configurer recherche subs" },
  },
  // ARBITRAGE PRODUIT F12 (2026-08-03) : un « .fr.forced.srt » ne traduit que les
  // passages en langue étrangère. La langue EST détectée (donc pas de
  // subtitle_missing_fr, qui serait de toute façon effacé par les réconciliations
  // backend), mais il n'existe aucune piste FR complète -> flag dédié.
  subtitle_forced_only_fr: {
    icon: "💬",
    label: "Sous-titres FR forcés uniquement",
    description:
      "Seul un sous-titre FR « forcé » a été détecté : il ne traduit que les passages en langue étrangère, pas les dialogues. Aucune piste FR complète.",
    severity: "warning",
    action: { kind: "config_subs", label: "Configurer recherche subs" },
  },
  subtitle_forced_only_en: {
    icon: "💬",
    label: "Sous-titres EN forcés uniquement",
    description:
      "Seul un sous-titre EN « forcé » a été détecté : il ne traduit que les passages en langue étrangère, pas les dialogues. Aucune piste EN complète.",
    severity: "warning",
    action: { kind: "config_subs", label: "Configurer recherche subs" },
  },
  subtitle_orphan: {
    icon: "💬",
    label: "Sous-titre orphelin",
    description: "Un fichier .srt/.sub présent sans match clair avec le fichier vidéo.",
    severity: "info",
    action: null,
  },
  subtitle_duplicate_lang: {
    icon: "💬",
    label: "Sous-titres en double",
    description: "Plusieurs sous-titres pour la même langue détectés.",
    severity: "info",
    action: null,
  },

  // --- Doublons ---
  duplicate_cross_root: {
    icon: "🔁",
    label: "Doublon dans 2 racines",
    description: "Ce film est aussi présent dans un autre dossier racine configuré.",
    severity: "warning",
    action: { kind: "open_duplicates", label: "Voir les doublons" },
  },
  duplicate_same_root: {
    icon: "🔁",
    label: "Doublon dans la même racine",
    description: "Ce film apparaît plusieurs fois dans le même dossier racine — à arbitrer via le comparateur.",
    severity: "warning",
    action: { kind: "open_duplicates", label: "Voir les doublons" },
  },

  // --- TMDb confiance ---
  low_confidence_tmdb: {
    icon: "🎯",
    label: "Match TMDb peu fiable",
    description: "Le match TMDb a une confiance inférieure à 70 % — vérifier le candidat retenu avant Apply.",
    severity: "warning",
    action: { kind: "open_film", label: "Voir détail" },
  },

  // --- Qualité / Probe ---
  low_bitrate: {
    icon: "📉",
    label: "Bitrate faible",
    description: "Le débit vidéo est anormalement bas pour la résolution annoncée — qualité dégradée probable.",
    severity: "info",
    action: null,
  },
  runtime_mismatch: {
    icon: "⏱",
    label: "Durée incohérente",
    description: "La durée du fichier diffère significativement de celle annoncée par TMDb (>30 min). Probablement faux match ou édition non détectée.",
    severity: "critical",
    action: null,
  },
  runtime_mismatch_likely_wrong_film: {
    icon: "⏱",
    label: "Durée — probablement un autre film",
    description: "La durée diffère trop fortement de TMDb pour être une simple édition étendue : il s'agit probablement d'un autre film. Vérifier le match avant Apply.",
    severity: "critical",
    action: { kind: "open_film", label: "Voir détail" },
  },
  // AUDIT 2026-06-14 (R6-I) : flag emis par la detection de doublons quand
  // l'annee est introuvable -> n'etait pas mappe ("Alerte sans description.").
  year_missing: {
    icon: "📅",
    label: "Année introuvable",
    description: "Aucune année exploitable (ni NFO ni nom de dossier). Le regroupement de doublons se base alors sur le titre seul : vérifier l'année avant Apply.",
    severity: "warning",
    action: { kind: "open_film", label: "Voir détail" },
  },
  // #613 : episode TV dont la saison n'a pas ete resolue (nom de type
  // "Episode 12" sans saison). L'apply REFUSE de le ranger : "Saison 00" est le
  // dossier des specials, pas une poubelle pour les saisons inconnues.
  tv_season_unknown: {
    icon: "📺",
    label: "Saison indéterminée",
    description: "La saison de cet épisode n'a pas pu être déterminée. L'application refusera de le ranger (le mettre dans « Saison 00 » le confondrait avec les specials) : renseigner la saison avant Apply.",
    severity: "warning",
    action: { kind: "open_film", label: "Voir détail" },
  },
};

// AUDIT 2026-06-14 (R6-I) : map de langues pour les flags subtitle_missing_<lang>
// dynamiques (de/es/it/...) non listes explicitement ci-dessus.
const _LANG_NAMES = {
  fr: "français", en: "anglais", de: "allemand", es: "espagnol",
  it: "italien", pt: "portugais", nl: "néerlandais", ja: "japonais",
  ko: "coréen", zh: "chinois", ru: "russe", ar: "arabe",
};

const DEFAULT = {
  icon: "⚠",
  label: null, // sera remplace par le code brut
  description: "Alerte sans description.",
  severity: "info",
  action: null,
};

/**
 * Renvoie { code, icon, label, description, severity, action } pour un flag.
 * Si le flag n'est pas connu, retourne le code brut comme label.
 */
export function labelForFlag(code) {
  const c = String(code || "").trim();
  if (!c) return null;
  let entry = FLAG_MAP[c];
  // AUDIT 2026-06-14 (R6-I) : flags subtitle_missing_<lang> dynamiques.
  if (!entry && c.startsWith("subtitle_missing_")) {
    const lang = c.slice("subtitle_missing_".length);
    const langName = _LANG_NAMES[lang] || lang.toUpperCase();
    entry = {
      icon: "💬",
      label: `Sous-titres ${lang.toUpperCase()} manquants`,
      description: `Aucun sous-titre ${langName} détecté pour ce film.`,
      severity: "warning",
      action: { kind: "config_subs", label: "Configurer recherche subs" },
    };
  }
  // F12 (2026-08-03) : flags subtitle_forced_only_<lang> dynamiques (de/es/it/...).
  if (!entry && c.startsWith("subtitle_forced_only_")) {
    const lang = c.slice("subtitle_forced_only_".length);
    const langName = _LANG_NAMES[lang] || lang.toUpperCase();
    entry = {
      icon: "💬",
      label: `Sous-titres ${lang.toUpperCase()} forcés uniquement`,
      description: `Seul un sous-titre ${langName} « forcé » a été détecté : il ne traduit que les passages en langue étrangère, pas les dialogues. Aucune piste ${lang.toUpperCase()} complète.`,
      severity: "warning",
      action: { kind: "config_subs", label: "Configurer recherche subs" },
    };
  }
  // AUDIT 2026-06-14 (R6-I) : flag inconnu -> on affiche le code en clair plutot
  // que le generique "Alerte sans description." (sans valeur pour l'utilisateur).
  if (!entry) {
    entry = {
      ...DEFAULT,
      description: `Alerte « ${c} » (non documentée). Signalez-la si elle est fréquente.`,
    };
  }
  return {
    code: c,
    icon: entry.icon,
    label: entry.label || c,
    description: entry.description,
    severity: entry.severity,
    action: entry.action,
  };
}

/**
 * Map une liste de flags vers leurs entrees. Filtre les vides.
 */
export function labelsForFlags(flags) {
  if (!Array.isArray(flags)) return [];
  return flags
    .map(labelForFlag)
    .filter((x) => x !== null);
}

/**
 * Compte par severite : { critical, warning, info, total }.
 */
export function countBySeverity(flags) {
  const out = { critical: 0, warning: 0, info: 0, total: 0 };
  for (const l of labelsForFlags(flags)) {
    out[l.severity] = (out[l.severity] || 0) + 1;
    out.total += 1;
  }
  return out;
}

/** Severite globale : critical > warning > info > none */
export function worstSeverity(flags) {
  const c = countBySeverity(flags);
  if (c.critical > 0) return "critical";
  if (c.warning > 0) return "warning";
  if (c.info > 0) return "info";
  return null;
}
