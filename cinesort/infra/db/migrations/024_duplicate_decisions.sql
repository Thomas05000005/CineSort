-- Migration 024 : table duplicate_decisions (phase 4 doublons / spec 01-doublons.md).
--
-- Stocke la decision utilisateur "garder ce winner" par groupe de doublons.
-- A l'apply, les non-winners du groupe seront deplaces vers
-- <root>/_review/_duplicates_user_decided/ (cf section 4 du spec).
--
-- Le groupe est identifie par une `group_key` libre (typiquement la cle TMDB
-- normalisee renvoyee par check_duplicates : title|year ou tmdb_id). Le winner
-- est designe par son row_id.
--
-- (run_id, group_key) est PK : on upsert sur conflict pour permettre a
-- l'utilisateur de changer d'avis sur un groupe.
--
-- NB : pas de FK vers runs car un run peut etre purge sans qu'on veuille
-- bloquer la decision si l'utilisateur restaure / replanifie. Le run_id reste
-- un simple discriminant logique.

CREATE TABLE IF NOT EXISTS duplicate_decisions (
    run_id          TEXT NOT NULL,
    group_key       TEXT NOT NULL,
    winner_row_id   TEXT NOT NULL,
    loser_row_ids   TEXT NOT NULL,    -- JSON array des row_ids non retenus
    decided_ts      REAL NOT NULL,
    notes           TEXT,
    PRIMARY KEY (run_id, group_key)
);

CREATE INDEX IF NOT EXISTS idx_duplicate_decisions_run
    ON duplicate_decisions(run_id);

PRAGMA user_version = 24;
