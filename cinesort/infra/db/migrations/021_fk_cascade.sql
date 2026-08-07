-- @manager: disable_fk
--
-- POURQUOI CE MARQUEUR (ajoute apres mesure, 2026-08-06)
--
-- Ce fichier est execute par DEUX chemins, avec le meme SQL mais pas le meme
-- `PRAGMA foreign_keys` :
--
--   1. MigrationManager.apply, une fois, sur une base restee en v20 ;
--   2. SQLiteStore._bootstrap_schema_latest, a CHAQUE auto-reparation, qui
--      concatene TOUTES les migrations et tourne avec les FK a OFF (fix
--      BUG-001, sans quoi un DROP TABLE runs CASCADE-supprimerait les tables
--      filles).
--
-- La section 1 recopie `errors` SANS filtrer les lignes orphelines — c'est
-- volontaire, et refuse explicitement par la passe adversaire N26 : `errors`
-- est le journal d'erreurs de l'utilisateur, le jeter en silence serait pire
-- que le probleme. Le chemin (2) le permettait deja, les FK y etant a OFF.
-- Le chemin (1), lui, les avait a ON.
--
-- MESURE, base reelle amenee a v20, UNE seule ligne `errors` orpheline :
--
--   essai 1 : IntegrityError: FOREIGN KEY constraint failed -> user_version 20
--   essai 2 : IntegrityError: FOREIGN KEY constraint failed -> user_version 20
--
-- Deterministe, rejoue a chaque ouverture : la base ne s'ouvre plus JAMAIS, et
-- rien dans l'application ne repare la ligne fautive. Une orpheline s'obtient
-- sans rien faire d'exotique — `foreign_keys` vaut OFF par defaut dans SQLite,
-- donc tout ecrivain qui ne pose pas le pragma laisse ses `errors` derriere un
-- run supprime.
--
-- Le marqueur aligne (1) sur (2). Les orphelines survivent au lieu de bloquer.
--
-- CE QUE LE MARQUEUR NE FAIT PAS, contrairement a ce qu'une premiere redaction
-- de ce bloc affirmait (corrige apres mesure en revue adversaire) :
--
--   - il ne rend PAS l'incoherence durablement visible. `PRAGMA foreign_key_check`
--     n'est appele que sous la garde `schema_change_pending` (sqlite_store.py:504),
--     donc UNE seule fois : au boot qui applique la migration. Tous les suivants
--     sont muets, et le resultat part dans un `logger.error` qui n'alimente pas
--     `_integrity_event` — aucune surface produit ne le dit a l'utilisateur.
--     Le choix reste le bon (une base bloquee est pire), mais il se paie en
--     observabilite, et ce cout doit etre ecrit ici plutot que nie.
--   - il ne laisse PAS les sections 2/3/4 sans effet nouveau. Sur la seule classe
--     de bases qu'il debloque, leurs filtres `WHERE EXISTS` suppriment desormais
--     des lignes qui survivaient auparavant par le rollback de la migration
--     entiere. MESURE, meme base v20, 1 orpheline + 1 ligne valide par table :
--       sans marqueur -> user_version 20 ; quality_reports 2, anomalies 2, apply_operations 2
--       avec marqueur -> user_version 31 ; quality_reports 1, anomalies 1, apply_operations 1
--     C'est ce qui a conduit a retirer le filtre de la section 4 (voir sur place).
--
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

-- Pas de filtre orphelines ici, CONTRAIREMENT aux sections 2, 3 et 4 : `errors`
-- est le journal d'erreurs de l'utilisateur, et le jeter en silence est
-- precisement ce que la passe adversaire N26 a refuse (cf.
-- tests/test_infra_db_nuances_audit_20260803.py, ForeignKeyViolationDiagnostic).
-- Les orphelines survivent donc, et `PRAGMA foreign_key_check` les signale au
-- boot suivant. C'est ce que le marqueur `disable_fk` en tete de fichier rend
-- possible sans casser le demarrage — voir son commentaire.
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

-- PAS de filtre orphelines ici — retire apres mesure, meme raison que la
-- section 1. Cette table est le JOURNAL D'UNDO (cf. 005_apply_undo_journal.sql) :
-- chacune de ses lignes est le seul enregistrement d'un DEPLACEMENT DEJA FAIT
-- SUR DISQUE. Ce n'est pas un sous-produit recalculable, c'est le filet de
-- securite de l'utilisateur — la meme categorie que `errors`, en plus grave.
--
-- Le filtre `WHERE EXISTS (SELECT 1 FROM apply_batches ...)` qui vivait ici
-- avait ete ecrit « pour proteger l'integrite FK ». Sous `disable_fk` il ne
-- protege plus rien : contre-epreuve MESUREE, filtre retire et rien d'autre
-- change, la migration aboutit (user_version 31) et l'orpheline est PRESERVEE.
-- Il ne restait donc qu'une suppression silencieuse.
--
-- Les sections 2 (quality_reports) et 3 (anomalies) gardent le leur : ce sont
-- des sorties recalculables par un nouveau scan, pas la trace d'une action
-- irreversible.
INSERT INTO apply_operations_new (
  id, batch_id, op_index, op_type, src_path, dst_path, reversible,
  undo_status, error_message, ts, row_id, src_sha1, src_size
)
SELECT
  id, batch_id, op_index, op_type, src_path, dst_path, reversible,
  undo_status, error_message, ts, row_id, src_sha1, src_size
FROM apply_operations;

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
