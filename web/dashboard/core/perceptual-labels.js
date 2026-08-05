/* core/perceptual-labels.js — Mapping codes verdicts perceptuels -> labels humains.
 *
 * Spec 02 §2 : centralise les libelles pour Modal Perceptuelle, Score V2,
 * et tout endroit qui affiche les verdicts (Bibliotheque, Doublons, etc.).
 *
 * Source des codes : cinesort/domain/perceptual/* (analyse audio + video).
 */

export const VERDICT_LABELS = {
  // lossy_verdict (compression audio)
  lossless: "Sans perte (FLAC, ALAC, PCM)",
  lossy_high: "Compressé qualité haute (>256 kbps AAC/MP3)",
  lossy_medium: "Compressé qualité moyenne (~192 kbps)",
  lossy_low: "Compressé basse qualité (<160 kbps)",
  lossy_very_low: "Compressé très basse qualité (<96 kbps)",

  // upscale_verdict (SSIM self-ref)
  native_4k: "Vrai 4K natif",
  native_1080p: "Vrai 1080p natif",
  native_720p: "Vrai 720p natif",
  native_sd: "SD natif",
  upscaled_720p: "Faux 720p (upscalé)",
  upscaled_1080p: "Faux 1080p (upscalé depuis 720p)",
  upscaled_4k: "Faux 4K (upscalé depuis 1080p)",
  unknown_upscale: "Origine indéterminée",

  // tier_v2
  platinum: "Platinum (référence)",
  gold: "Gold (excellent)",
  silver: "Silver (bon)",
  bronze: "Bronze (acceptable)",
  reject: "Reject (à remplacer)",
  degrade: "Dégradé",
  unknown: "Non analysé",

  // grain_label / grain_nature
  clean: "Très propre (denoised)",
  subtle: "Subtil, naturel",
  moderate: "Modéré, naturel (film stock)",
  heavy: "Lourd (grain marqué)",
  noisy: "Bruité (artefacts encodage)",

  // hdr_format
  sdr: "SDR (aucune métadonnée HDR)",
  hdr10: "HDR10",
  hdr10_plus: "HDR10+",
  dolby_vision: "Dolby Vision",
  hlg: "HLG (HDR broadcast)",
};

/**
 * Renvoie le label humain d'un code (ex: "lossy_low" -> "Compressé basse qualité").
 * Si inconnu, retourne le code brut.
 */
export function humanize(code, fallback) {
  if (code == null) return fallback != null ? fallback : "—";
  const key = String(code).toLowerCase();
  return VERDICT_LABELS[key] || (fallback != null ? fallback : code);
}

/* --- Analyse mel (#381) -----------------------------------------------------
 *
 * Table SEPAREE de VERDICT_LABELS, et non une poignee de cles ajoutees dedans :
 * `mel_verdict` et `grain_label` partagent le code "clean" avec deux sens
 * differents. Dans VERDICT_LABELS, "clean" vaut deja « Très propre (denoised) »,
 * qui parle du GRAIN VIDEO ; passer un verdict mel par `humanize()` afficherait
 * donc « denoised » a propos d'une piste AUDIO — exactement l'etiquette fausse
 * que ce lot corrige ailleurs. Les deux tables restent disjointes.
 *
 * Codes emis par cinesort/domain/perceptual/mel_analysis.py (compute_mel_score
 * + les deux gardes d'analyze_mel) et par audio_perceptual.py ("disabled").
 */
export const MEL_VERDICT_LABELS = {
  clean: "Aucune signature de compression",
  soft_clipped: "Soft clipping (harmoniques de saturation)",
  mp3_encoded: "Signature MP3 (coupure vers 16 kHz)",
  aac_low_bitrate: "AAC bas débit (trous spectraux)",
  degraded: "Dégradé (aucun motif dominant)",
  insufficient_data: "Non mesuré (signal trop court)",
  disabled: "Analyse mel désactivée",
  unknown: "Non mesuré",
};

/**
 * Verdicts mel qui attestent d'une mesure ABOUTIE.
 *
 * Les autres ("insufficient_data", "disabled", "unknown") laissent les quatre
 * sous-detections a leur valeur par defaut — 0.0 / false — qui ne sont pas des
 * mesures. Les afficher telles quelles annoncerait « 0,0 % de frames clippees »
 * et « aplatissement 0,000 » pour une analyse qui n'a jamais tourne : un
 * resultat faux, pas une absence de resultat.
 */
export const MEL_MEASURED_VERDICTS = [
  "clean",
  "soft_clipped",
  "mp3_encoded",
  "aac_low_bitrate",
  "degraded",
];

/** Label humain d'un `mel_verdict`. Ne retombe JAMAIS sur VERDICT_LABELS. */
export function humanizeMelVerdict(code) {
  const key = String(code == null ? "" : code).toLowerCase();
  return MEL_VERDICT_LABELS[key] || MEL_VERDICT_LABELS.unknown;
}

/** True si `code` designe une mesure mel qui a abouti. */
export function isMelMeasured(code) {
  return MEL_MEASURED_VERDICTS.includes(String(code == null ? "" : code).toLowerCase());
}

/**
 * Classification rapide d'une severite a partir du tier_v2.
 */
export function severityForTier(tier) {
  const t = String(tier || "").toLowerCase();
  if (t === "platinum" || t === "gold") return "good";
  if (t === "silver" || t === "bronze") return "warning";
  if (t === "reject" || t === "degrade") return "critical";
  return "info";
}

/**
 * Composantes du Score V2 (poids fixes documentes dans spec 02 §1).
 * Used pour le breakdown affiche dans la modal.
 */
export const SCORE_V2_COMPONENTS = [
  { id: "resolution", label: "Résolution", weight: 0.25 },
  { id: "bitrate", label: "Bitrate vidéo", weight: 0.20 },
  { id: "codec", label: "Codec", weight: 0.15 },
  { id: "audio_bitrate", label: "Bitrate audio", weight: 0.20 },
  { id: "audio_channels", label: "Canaux audio", weight: 0.10 },
  { id: "subtitle_fr", label: "Sous-titres FR", weight: 0.10 },
];
