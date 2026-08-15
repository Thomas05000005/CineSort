---
name: verify
description: Lancer et piloter CineSort isolé (state + bibliothèque bac à sable) pour vérifier un changement en conditions réelles via l'API REST, sans toucher la vraie base ni la vraie bibliothèque.
---

# Vérifier CineSort en conditions réelles (isolé)

## Lancement isolé (ne touche PAS l'état réel de l'utilisateur)

Le state dir est résolu via `%LOCALAPPDATA%/CineSort` → surcharger `LOCALAPPDATA`
isole tout (DB, settings, runs) :

```bash
SB=<dossier bac à sable>   # contiendra state/ et lib/
mkdir -p "$SB/state" "$SB/lib"
# 1. PRÉ-REQUIS : en mode --api le serveur REFUSE de démarrer sans token.
#    Écrire $SB/state/CineSort/settings.json AVANT le lancement :
#    { "root": "<SB>/lib", "state_dir": "<SB>/state/CineSort",
#      "rest_api_token": "verify-token", "rest_api_enabled": true,
#      "tmdb_enabled": false, "probe_backend": "none",
#      "collection_folder_enabled": true, "auto_approve_threshold": 85, ... }
#    (modèle complet : tests/e2e/create_test_data.py::get_settings_dict)
# 2. Lancer sur un port éphémère (JAMAIS 8642 = port de l'instance réelle) :
LOCALAPPDATA="$(cygpath -w "$SB/state")" python app.py --api --port 18642 &
```

## Bibliothèque factice

Fichiers **sparse ≥ 52 Mo** (`truncate -s 52M`) avec extensions vidéo — passent le
seuil de taille min du scan. Un dossier multi-vidéos ⇒ `collection` + `extra`
(bonus). `probe_backend: none` ⇒ pas besoin de vrais MKV (les flags
`integrity_header_invalid` sur fichiers factices sont NORMAUX).

## Contrats d'API (pièges vécus)

- Auth : `Authorization: Bearer <token>` — le **loopback 127.0.0.1 est exempté
  par design** (issues #72/#73, gardes CSRF) : pas un bug.
- `run/start_plan` : `{"settings": {<echo complet de get_settings> +
  "library_path": "<lib>"}}` — `library_path` est requis par pydantic.
- `run/get_status {"run_id":"latest"}` renvoie `run_id: null` une fois le run
  fini → **mémoriser le run_id retourné par start_plan**, ne pas le re-résoudre.
- `run/check_duplicates` : `{"run_id", "decisions": {}}` — decisions requis.
- `run/apply` : `{"run_id", "decisions": {}, "dry_run": false,
  "quarantine_unapproved": false}` — dernier argument REQUIS.
- `run/undo_last_apply` : `dry_run=True` PAR DÉFAUT (prévisualisation) →
  passer `{"dry_run": false}` pour l'undo réel.
- `library/mark_for_deletion_bulk` : `{"run_id", "row_ids": [...]}` →
  réponse `{ok, count, failed[]}`.
- Sortie console Windows : les accents mal affichés (`Am�lie`) = encodage du
  terminal, PAS l'app (les payloads JSON sont corrects).

## Flux qui valent le coup d'être exercés

scan→plan (kinds/flags/row_id `^[SCT]|[0-9a-f]{16}$`), recherche accents
(`library/get_library_filtered {"filters":{"search":...}}`), compteurs
(`run/get_sidebar_counters` → `{data:{validation,application,quality,duplicates}}`),
doublons ×2 (les warning_flags du plan doivent rester STABLES), exports
(`run/export_run_report {"fmt":"json"|"csv"}` — le CSV doit commencer par
BOM + `run_id;`), et le cycle destructif complet sur le bac à sable :
marquer un `extra` → apply réel → SEUL le bonus va dans
`_review/_user_marked_for_deletion/` → undo réel → tout revient.

## Nettoyage

`taskkill //PID $(netstat -ano | grep ":<port>.*LISTENING" | awk '{print $5}') //F`
