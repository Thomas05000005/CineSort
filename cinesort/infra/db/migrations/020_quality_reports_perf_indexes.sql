-- Migration 020 : indexes de performance sur quality_reports
-- Audit perf 2026-05-01 : SCAN sur GROUP BY tier + ORDER BY score
-- Cible : bibliotheques 50k+ films, 2000 users en attente
--
-- Avant : SCAN + TEMP B-TREE pour `SELECT tier, COUNT(*) FROM quality_reports GROUP BY tier`
--         (0.022 ms a 10k, 2.2 ms a 1M)
-- Avant : SCAN + sort pour `SELECT row_id FROM quality_reports ORDER BY score DESC LIMIT 10`
--         (0.005 ms a 10k, ~5 ms a 1M)

-- Index sur tier pour GROUP BY tier dans dashboard
CREATE INDEX IF NOT EXISTS idx_quality_reports_tier
    ON quality_reports(tier);

-- Index sur score DESC pour ORDER BY score (top wasters)
CREATE INDEX IF NOT EXISTS idx_quality_reports_score
    ON quality_reports(score DESC);

PRAGMA user_version = 20;
