-- Migration 022 : drop des indexes redondants avec les PRIMARY KEYs
--
-- Cf issue #77 (audit-2026-05-12:c5d7) : 5 indexes etaient definis sur
-- des colonnes deja couvertes par leur PRIMARY KEY composite ou simple.
-- SQLite cree automatiquement un index implicite sur chaque PK, donc
-- l'index nomme en double consomme 2x l'espace disque + double les writes
-- a chaque INSERT/UPDATE sans benefice de lecture.
--
-- Tables concernees (~20% disk + 15% write speedup attendu sur grosses
-- tables comme quality_reports/perceptual_reports > 1M rows):
--
-- 1. probe_cache : index (path,size,mtime,tool) == PK identique
-- 2. incremental_file_hashes : PK simple sur 'path' suffit pour lookup
--    par path (le multi-col (path,size,mtime_ns) etait pour eviter SCAN
--    apres filtre PK, mais PK simple match directement la row puis filtre
--    en memoire — cout negligeable car 1 row matchee)
-- 3. schema_migrations : index version == PRIMARY KEY version
-- 4. quality_reports : index run_id == prefix-leftmost de PK (run_id, row_id)
-- 5. perceptual_reports : idem
--
-- NB : pas de BEGIN/COMMIT explicite ici — migration_manager.apply()
-- enveloppe deja chaque migration dans une transaction (sinon nested
-- transaction error). Pattern identique aux migrations 015-021.

DROP INDEX IF EXISTS idx_probe_cache_lookup;
DROP INDEX IF EXISTS idx_incremental_file_hashes_lookup;
DROP INDEX IF EXISTS idx_schema_migrations_version;
DROP INDEX IF EXISTS idx_quality_reports_run;
DROP INDEX IF EXISTS idx_perceptual_reports_run;
