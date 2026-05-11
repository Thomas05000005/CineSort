-- v21 (V1-02 polish v7.7.0) : ajout ON DELETE CASCADE sur les FK enfants de runs et apply_batches.
-- Source : audit R5-DB-1, PLAN_RESTE_A_FAIRE.md section 1.2.
--
-- Avant cette migration, les tables `errors`, `quality_reports`, `anomalies` et
-- `apply_operations` pouvaient laisser des rows orphelines lorsqu'on supprimait
-- la row parente (run ou apply_batch). Ce n'etait pas un probleme courant
-- (l'app ne supprime pas de runs en usage normal) mais pour la propre
-- maintenance / RGPD / outils externes c'est un risque de coherence.
--
-- SQLite ne supporte PAS `ALTER TABLE ADD CONSTRAINT FK`. On applique donc le
-- pattern recommande par la doc SQLite "Making Other Kinds Of Table Schema
-- Changes" (Section 7) : recreation atomique de la table.
--
-- Pattern par table :
--   1. DROP TABLE IF EXISTS xxx_new;        -- idempotence si crash precedent
--   2. CREATE TABLE xxx_new (... avec CASCADE ...);
--   3. INSERT INTO xxx_new SELECT * FROM xxx;  -- copie 1:1
--   4. DROP TABLE xxx;
--   5. ALTER TABLE xxx_new RENAME TO xxx;
--   6. CREATE INDEX IF NOT EXISTS ... (les index sont droppes avec la table).
--
-- Le manager de migrations enveloppe tout dans une transaction unique
-- (BEGIN ... COMMIT) avec un SAVEPOINT par statement (cf migration_manager.py).
-- Si une etape echoue, l'ensemble est rollback et le user_version reste a 20.
--
-- Resultat (PRAGMA foreign_key_list apres) :
--   errors.run_id           -> runs.run_id            ON DELETE CASCADE
--   quality_reports.run_id  -> runs.run_id            ON DELETE CASCADE  (FK ajoutee, n'existait pas)
--   anomalies.run_id        -> runs.run_id            ON DELETE CASCADE  (FK ajoutee, n'existait pas)
--   apply_operations.batch_id -> apply_batches.batch_id ON DELETE CASCADE

-- ============================================================================
-- 1. errors  (FK existante NO ACTION -> CASCADE)
-- ============================================================================
DROP TABLE IF EXISTS errors_new;

CREATE TABLE errors_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  ts REAL NOT NULL,
  step TEXT NOT NULL,
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  context_json TEXT,
  FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

INSERT INTO errors_new (id, run_id, ts, step, code, message, context_json)
SELECT id, run_id, ts, step, code, message, context_json FROM errors;

DROP TABLE errors;

ALTER TABLE errors_new RENAME TO errors;

CREATE INDEX IF NOT EXISTS idx_errors_run_id ON errors(run_id);

-- ============================================================================
-- 2. quality_reports  (PAS de FK avant -> ajout FK avec CASCADE)
-- ============================================================================
DROP TABLE IF EXISTS quality_reports_new;

CREATE TABLE quality_reports_new (
  run_id TEXT NOT NULL,
  row_id TEXT NOT NULL,
  score INTEGER NOT NULL,
  tier TEXT NOT NULL,
  reasons_json TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  profile_id TEXT NOT NULL,
  profile_version INTEGER NOT NULL,
  ts REAL NOT NULL,
  PRIMARY KEY(run_id, row_id),
  FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

-- IMPORTANT : on filtre les rows orphelines (run_id sans parent dans `runs`)
-- pour eviter un echec d'integrite FK au commit. En usage normal il n'y en a
-- pas, mais une DB historique pourrait en contenir.
INSERT INTO quality_reports_new (
  run_id, row_id, score, tier, reasons_json, metrics_json,
  profile_id, profile_version, ts
)
SELECT
  qr.run_id, qr.row_id, qr.score, qr.tier, qr.reasons_json, qr.metrics_json,
  qr.profile_id, qr.profile_version, qr.ts
FROM quality_reports qr
WHERE EXISTS (SELECT 1 FROM runs r WHERE r.run_id = qr.run_id);

DROP TABLE quality_reports;

ALTER TABLE quality_reports_new RENAME TO quality_reports;

CREATE INDEX IF NOT EXISTS idx_quality_reports_run ON quality_reports(run_id);
CREATE INDEX IF NOT EXISTS idx_quality_reports_tier ON quality_reports(tier);
CREATE INDEX IF NOT EXISTS idx_quality_reports_score ON quality_reports(score DESC);

-- ============================================================================
-- 3. anomalies  (PAS de FK avant -> ajout FK avec CASCADE)
-- ============================================================================
DROP TABLE IF EXISTS anomalies_new;

CREATE TABLE anomalies_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  row_id TEXT,
  severity TEXT NOT NULL,
  code TEXT NOT NULL,
  message TEXT NOT NULL,
  path TEXT,
  recommended_action TEXT,
  context_json TEXT,
  ts REAL NOT NULL,
  FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

-- Idem : filtrer les anomalies orphelines pour proteger l'integrite FK.
INSERT INTO anomalies_new (
  id, run_id, row_id, severity, code, message, path,
  recommended_action, context_json, ts
)
SELECT
  a.id, a.run_id, a.row_id, a.severity, a.code, a.message, a.path,
  a.recommended_action, a.context_json, a.ts
FROM anomalies a
WHERE EXISTS (SELECT 1 FROM runs r WHERE r.run_id = a.run_id);

DROP TABLE anomalies;

ALTER TABLE anomalies_new RENAME TO anomalies;

CREATE INDEX IF NOT EXISTS idx_anomalies_run_id ON anomalies(run_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_severity ON anomalies(severity);
CREATE INDEX IF NOT EXISTS idx_anomalies_code ON anomalies(code);

-- ============================================================================
-- 4. apply_operations  (FK existante NO ACTION -> CASCADE)
-- ============================================================================
DROP TABLE IF EXISTS apply_operations_new;

CREATE TABLE apply_operations_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL,
  op_index INTEGER NOT NULL,
  op_type TEXT NOT NULL,
  src_path TEXT NOT NULL,
  dst_path TEXT NOT NULL,
  reversible INTEGER NOT NULL CHECK (reversible IN (0, 1)),
  undo_status TEXT NOT NULL DEFAULT 'PENDING',
  error_message TEXT,
  ts REAL NOT NULL,
  row_id TEXT DEFAULT NULL,
  src_sha1 TEXT DEFAULT NULL,
  src_size INTEGER DEFAULT NULL,
  FOREIGN KEY (batch_id) REFERENCES apply_batches(batch_id) ON DELETE CASCADE
);

-- Idem : filtrer les operations orphelines pour proteger l'integrite FK.
INSERT INTO apply_operations_new (
  id, batch_id, op_index, op_type, src_path, dst_path, reversible,
  undo_status, error_message, ts, row_id, src_sha1, src_size
)
SELECT
  ao.id, ao.batch_id, ao.op_index, ao.op_type, ao.src_path, ao.dst_path,
  ao.reversible, ao.undo_status, ao.error_message, ao.ts,
  ao.row_id, ao.src_sha1, ao.src_size
FROM apply_operations ao
WHERE EXISTS (SELECT 1 FROM apply_batches ab WHERE ab.batch_id = ao.batch_id);

DROP TABLE apply_operations;

ALTER TABLE apply_operations_new RENAME TO apply_operations;

CREATE UNIQUE INDEX IF NOT EXISTS idx_apply_ops_batch_opindex
  ON apply_operations(batch_id, op_index);
CREATE INDEX IF NOT EXISTS idx_apply_ops_batch
  ON apply_operations(batch_id, id);
CREATE INDEX IF NOT EXISTS idx_apply_ops_reversible
  ON apply_operations(batch_id, reversible);
CREATE INDEX IF NOT EXISTS idx_apply_ops_row_id
  ON apply_operations(batch_id, row_id);

PRAGMA user_version = 21;
