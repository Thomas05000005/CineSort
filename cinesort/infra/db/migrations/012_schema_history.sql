-- v12: table schema_migrations pour tracer l'historique d'application.
-- Audit AUDIT_20260422 finding DB3 : PRAGMA user_version ne donne qu'un entier ;
-- cette table permet de voir quand chaque migration a ete appliquee et
-- depuis quelle build (utile pour diagnostiquer les upgrades echoues).

CREATE TABLE IF NOT EXISTS schema_migrations (
    version      INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    applied_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    app_version  TEXT    DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_schema_migrations_version ON schema_migrations(version);

PRAGMA user_version = 12;
