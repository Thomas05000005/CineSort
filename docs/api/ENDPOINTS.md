# CineSort REST API — Endpoints

> Auto-genere depuis l'introspection de `CineSortApi` (V3-06, mai 2026).
> Regenerer apres changement d'API : `python scripts/gen_endpoints_doc.py`

## Vue d'ensemble

- **Total endpoints publics** : 1
- **Methode HTTP** : `POST /api/{method_name}` avec body JSON
- **Auth** : `Authorization: Bearer <token>` (token configure dans les Reglages)
- **Format reponse** : `{"ok": true, ...}` ou `{"ok": false, "message": "..."}`
- **Endpoints publics** : `GET /api/health` (sans auth) et `GET /api/spec` (OpenAPI)
- **Body max** : 16 MB ; **Rate limit auth** : 5 echecs / 60s par IP

## Endpoints groupes par categorie

### 9. Notifications & System

#### `POST /api/test_reset`

**Signature** : `test_reset(min_video_bytes: int = 0) -> Dict[str, Any]`

**Description** : Remet l'app dans un etat propre pour les tests E2E. Desactive en production.


## Endpoints exclus du REST

Les methodes suivantes existent sur `CineSortApi` mais sont volontairement filtrees par `_EXCLUDED_METHODS` (`cinesort/infra/rest_server.py`) :

- `log` — Helper interne logging (frontend → backend).
- `log_api_exception` — Helper interne logging, pas un endpoint metier.
- `open_path` — Prend un chemin arbitraire — vector path-traversal en supervision distante.
- `progress` — Helper interne progress reporting (frontend → backend).

## Exemples requete / reponse

Tous les exemples supposent que le serveur ecoute sur `localhost:8642`
et qu'un token Bearer valide est configure cote serveur.

### 1. Lancer un scan

```bash
curl -X POST http://localhost:8642/api/start_plan \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"settings": {"sources": ["D:/Films"], "destination": "D:/Library", "tmdb_key": "***"}}'
```

**Reponse** : `{"ok": true, "run_id": "20260504_120000_001"}`

### 2. Recuperer les settings actuels

```bash
curl -X POST http://localhost:8642/api/get_settings \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Reponse** : `{"ok": true, "data": {"sources": [...], "destination": "...", ...}}`

### 3. Sauvegarder de nouveaux settings

```bash
curl -X POST http://localhost:8642/api/save_settings \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"settings": {"destination": "D:/NewLibrary", "auto_apply_threshold": 90}}'
```

**Reponse** : `{"ok": true}`

### 4. Suivre la progression d'un run

```bash
curl -X POST http://localhost:8642/api/get_status \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id": "20260504_120000_001", "last_log_index": 0}'
```

**Reponse** : `{"ok": true, "status": "running", "progress": 42, "logs": [...]}`

### 5. Recuperer le plan complet d'un run

```bash
curl -X POST http://localhost:8642/api/get_plan \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id": "20260504_120000_001"}'
```

**Reponse** : `{"ok": true, "rows": [...], "stats": {...}}`

### 6. Appliquer les decisions de validation

```bash
curl -X POST http://localhost:8642/api/apply \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id": "20260504_120000_001", "decisions": {"row_id_1": {"approved": true}}, "dry_run": false, "quarantine_unapproved": true}'
```

**Reponse** : `{"ok": true, "applied_count": 42, "errors": []}`

### 7. Annuler la derniere operation apply

```bash
curl -X POST http://localhost:8642/api/undo_last_apply \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Reponse** : `{"ok": true, "undone_count": 42}`

### 8. Tester la cle TMDb

```bash
curl -X POST http://localhost:8642/api/test_tmdb_key \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "abcd1234"}'
```

**Reponse** : `{"ok": true, "valid": true}`

### 9. Tester une connexion Jellyfin

```bash
curl -X POST http://localhost:8642/api/test_jellyfin_connection \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "http://jellyfin.local:8096", "api_key": "***"}'
```

**Reponse** : `{"ok": true, "version": "10.9.6"}`

### 10. Recuperer le dashboard d'un run

```bash
curl -X POST http://localhost:8642/api/get_dashboard \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id": "latest"}'
```

**Reponse** : `{"ok": true, "kpis": {...}, "distribution": [...], "anomalies": [...]}`

---

_Genere par `scripts/gen_endpoints_doc.py` — ne pas editer manuellement._
_Pour regenerer : `.venv313/Scripts/python.exe scripts/gen_endpoints_doc.py`_
