-- v13: ajout checksum + taille aux operations apply pour un undo verifie (P1.2).
-- Avant l'undo, on recalcule le sha1_quick du fichier a dst_path et on compare
-- a src_sha1. Si mismatch -> refus (mode atomique) ou quarantaine (best-effort).
-- Empeche de detruire un fichier que l'utilisateur a remplace manuellement
-- entre l'apply et l'undo.

ALTER TABLE apply_operations ADD COLUMN src_sha1 TEXT DEFAULT NULL;
ALTER TABLE apply_operations ADD COLUMN src_size INTEGER DEFAULT NULL;

PRAGMA user_version = 13;
