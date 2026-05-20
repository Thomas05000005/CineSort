-- Migration 023 (V8-01 spec 08 Traitement) : etend la contrainte CHECK sur runs.status
-- pour supporter PAUSED, SAVED, AWAITING_VALIDATION + ajoute colonne paused_at.
--
-- Cf docs/internal/design/refonte_2026_05_17/screens/08-traitement.md §5
-- 4 nouveaux endpoints Run Control : pause_run, resume_run, save_for_later,
-- list_pending_runs. Ces endpoints ont besoin d'etats supplementaires :
--   - PAUSED               : run en pause, reprenable via resume_run
--   - SAVED                : run sauvegarde pour plus tard (pause + flag user)
--   - AWAITING_VALIDATION  : run en attente d'action utilisateur (validation manuelle)
--
-- SQLite ne supporte pas ALTER TABLE pour modifier une contrainte CHECK,
-- on applique le pattern recommande "Section 7" : recreation de la table.
--
-- Le manager de migrations enveloppe le tout dans une transaction unique
-- + SAVEPOINT par statement. En cas d'echec, rollback complet, user_version
-- reste a 22.
--
-- NB : depuis la migration 021, les FK enfants (errors, quality_reports,
-- anomalies) ont ON DELETE CASCADE sur `runs(run_id)`. Le simple DROP TABLE
-- runs supprimerait donc les rows enfants en cascade. On demande au manager
-- de migrations de desactiver les FK le temps de la migration via le marker :
--
--   @manager: disable_fk
--
-- (Cf migration_manager.py — PRAGMA foreign_keys ne fonctionne PAS dans une
-- transaction, le manager pose le PRAGMA avant BEGIN et le restaure apres.)

DROP TABLE IF EXISTS runs_new;

CREATE TABLE runs_new (
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN (
    'PENDING', 'RUNNING', 'DONE', 'FAILED', 'CANCELLED',
    'PAUSED', 'SAVED', 'AWAITING_VALIDATION'
  )),
  created_ts REAL NOT NULL,
  started_ts REAL,
  ended_ts REAL,
  root TEXT NOT NULL,
  state_dir TEXT NOT NULL,
  config_json TEXT NOT NULL,
  stats_json TEXT,
  idx INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0,
  current_folder TEXT NOT NULL DEFAULT '',
  cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
  error_message TEXT,
  paused_at REAL
);

INSERT INTO runs_new (
  run_id, status, created_ts, started_ts, ended_ts, root, state_dir,
  config_json, stats_json, idx, total, current_folder, cancel_requested,
  error_message, paused_at
)
SELECT
  run_id, status, created_ts, started_ts, ended_ts, root, state_dir,
  config_json, stats_json, idx, total, current_folder, cancel_requested,
  error_message, NULL
FROM runs;

DROP TABLE runs;

ALTER TABLE runs_new RENAME TO runs;

CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);

PRAGMA user_version = 23;
