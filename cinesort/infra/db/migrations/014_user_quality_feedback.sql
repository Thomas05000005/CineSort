-- v14 : table user_quality_feedback pour la calibration perceptuelle (P4.1).
-- L'utilisateur peut donner son tier attendu pour un film, et le système
-- agrège ces écarts pour détecter les biais du scoring et proposer des
-- ajustements de pondération.

CREATE TABLE IF NOT EXISTS user_quality_feedback (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT    NOT NULL,
    row_id           TEXT    NOT NULL,
    computed_score   INTEGER NOT NULL,
    computed_tier    TEXT    NOT NULL,
    user_tier        TEXT    NOT NULL,
    tier_delta       INTEGER NOT NULL,          -- écart ordinal : user_tier - computed_tier (ex: +1 si user dit Gold pour Silver calculé)
    category_focus   TEXT    DEFAULT NULL,      -- video|audio|extras si l'utilisateur précise où est le biais
    comment          TEXT    DEFAULT NULL,
    created_ts       REAL    NOT NULL,
    app_version      TEXT    DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_uqf_run ON user_quality_feedback(run_id);
CREATE INDEX IF NOT EXISTS idx_uqf_row ON user_quality_feedback(row_id);
CREATE INDEX IF NOT EXISTS idx_uqf_tier_delta ON user_quality_feedback(tier_delta);

PRAGMA user_version = 14;
