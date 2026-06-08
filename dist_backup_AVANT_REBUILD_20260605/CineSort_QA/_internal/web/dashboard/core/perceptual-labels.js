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
