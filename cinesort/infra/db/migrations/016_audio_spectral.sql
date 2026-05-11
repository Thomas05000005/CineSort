-- §9 v7.5.0 — Spectral cutoff audio (detection lossy)
-- Ajoute 2 colonnes a perceptual_reports :
--   spectral_cutoff_hz : frequence de coupure detectee (spectral rolloff 85%)
--   lossy_verdict      : verdict contextualise (lossless|lossy_high|lossy_mid|
--                        lossy_low|lossy_ambiguous_sbr|lossless_native_nyquist|
--                        lossless_vintage_master|silent_segment|error|unknown)

PRAGMA foreign_keys = ON;

ALTER TABLE perceptual_reports ADD COLUMN spectral_cutoff_hz REAL;
ALTER TABLE perceptual_reports ADD COLUMN lossy_verdict TEXT;
