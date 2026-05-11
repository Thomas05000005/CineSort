-- v10: ajout d'un index manquant pour les requetes frequentes (audit L1+L2)
-- - anomalies(code) : filtrage/agregation par code d'anomalie (get_top_anomaly_codes)
-- NB: idx_perceptual_reports_run existe deja (migration 009), pas besoin de le recreer.

CREATE INDEX IF NOT EXISTS idx_anomalies_code ON anomalies(code);

PRAGMA user_version = 10;
