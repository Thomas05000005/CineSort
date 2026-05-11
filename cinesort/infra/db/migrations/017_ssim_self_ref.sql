-- §13 v7.5.0 — SSIM self-referential (detection fake 4K)
-- Ajoute 2 colonnes a perceptual_reports :
--   ssim_self_ref    : score luminance 0.0-1.0 (-1 si non applicable/erreur)
--   upscale_verdict  : native|ambiguous|upscale_fake|not_applicable_*|disabled|error

PRAGMA foreign_keys = ON;

ALTER TABLE perceptual_reports ADD COLUMN ssim_self_ref REAL;
ALTER TABLE perceptual_reports ADD COLUMN upscale_verdict TEXT;
