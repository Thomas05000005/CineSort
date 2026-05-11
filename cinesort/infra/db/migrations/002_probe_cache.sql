PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS probe_cache (
  path TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  tool TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  normalized_json TEXT NOT NULL,
  ts REAL NOT NULL,
  PRIMARY KEY (path, size, mtime, tool)
);

CREATE INDEX IF NOT EXISTS idx_probe_cache_lookup
ON probe_cache(path, size, mtime, tool);

