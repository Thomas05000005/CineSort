-- §16 v7.5.0 — Score composite v2 (GlobalScoreResult)
-- Ajoute 3 colonnes a perceptual_reports :
--   global_score_v2       : score composite 0-100 (null si non calcule)
--   global_tier_v2        : platinum|gold|silver|bronze|reject (null si non calcule)
--   global_score_v2_json  : GlobalScoreResult serialise (category_scores, sub_scores, warnings, adjustments)

PRAGMA foreign_keys = ON;

ALTER TABLE perceptual_reports ADD COLUMN global_score_v2 REAL;
ALTER TABLE perceptual_reports ADD COLUMN global_tier_v2 TEXT;
ALTER TABLE perceptual_reports ADD COLUMN global_score_v2_json TEXT;
