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
    label: "Source non identifiée",
    description: "Le dossier source n'est pas dans un format scene standard — fichier probablement renommé à la main.",
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
  const entry = FLAG_MAP[c] || DEFAULT;
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
