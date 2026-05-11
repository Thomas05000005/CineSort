-- §3 v7.5.0 — Fingerprint audio Chromaprint
-- Ajoute la colonne audio_fingerprint (base64 du tableau d'entiers 32-bit)
-- a la table perceptual_reports pour detection "meme source" en deep compare.

PRAGMA foreign_keys = ON;

ALTER TABLE perceptual_reports ADD COLUMN audio_fingerprint TEXT;

-- Index commente : a activer quand la bibliotheque depasse ~10k films et
-- qu'une detection de doublons cross-run devient necessaire.
-- CREATE INDEX IF NOT EXISTS idx_perceptual_reports_audio_fingerprint
--   ON perceptual_reports(audio_fingerprint)
--   WHERE audio_fingerprint IS NOT NULL;
