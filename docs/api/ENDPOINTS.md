# CineSort REST API — Endpoints

> Auto-genere depuis l'introspection de `CineSortApi` (V3-06, mai 2026).
> Regenerer apres changement d'API : `python scripts/gen_endpoints_doc.py`

## Vue d'ensemble

- **Total endpoints publics** : 32
- **Methode HTTP** : `POST /api/{method_name}` avec body JSON
- **Auth** : `Authorization: Bearer <token>` (token configure dans les Reglages)
- **Format reponse** : `{"ok": true, ...}` ou `{"ok": false, "message": "..."}`
- **Endpoints publics** : `GET /api/health` (sans auth) et `GET /api/spec` (OpenAPI)
- **Body max** : 16 MB ; **Rate limit auth** : 5 echecs / 60s par IP

## Endpoints groupes par categorie

### 1. Configuration & Settings

#### `POST /api/get_server_info`

**Signature** : `get_server_info() -> Dict[str, Any]`

**Description** : Retourne les infos du serveur REST (IP, port, URL dashboard).

#### `POST /api/get_log_paths`

**Signature** : `get_log_paths() -> Dict[str, Any]`

**Description** : V3-13 — Retourne les chemins des logs (pour affichage UI + copie).


### 2. Scan & Plan

#### `POST /api/load_validation`

**Signature** : `load_validation(run_id: str) -> Dict[str, Any]`

**Description** : Recharge les decisions (approve/reject) persistees pour ce run.

#### `POST /api/save_validation`

**Signature** : `save_validation(run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]`

**Description** : Persiste les decisions de validation dans validation.json (atomique).

#### `POST /api/validate_dropped_path`

**Signature** : `validate_dropped_path(path: str = '') -> Dict[str, Any]`

**Description** : Valide qu'un chemin droppe est un dossier existant.

#### `POST /api/get_sidebar_counters`

**Signature** : `get_sidebar_counters() -> Dict[str, Any]`

**Description** : V3-04 — Compteurs sidebar pour badges UI (validation/application/quality).


### 3. Apply & Undo

#### `POST /api/apply`

**Signature** : `apply(run_id: str, decisions: Dict[str, Dict[str, Any]], dry_run: bool, quarantine_unapproved: bool) -> Dict[str, Any]`

**Description** : _(pas de docstring)_

#### `POST /api/export_apply_audit`

**Signature** : `export_apply_audit(run_id: str, batch_id: Optional[str] = None, as_format: str = 'json') -> Dict[str, Any]`

**Description** : P2.3 : journal d'audit JSONL d'un apply (complémentaire à apply_operations).

#### `POST /api/undo_last_apply`

**Signature** : `undo_last_apply(run_id: str, dry_run: bool = True, atomic: bool = True) -> Dict[str, Any]`

**Description** : Annule le dernier batch apply reel (undo v1). `dry_run=True` ne touche rien.

#### `POST /api/get_cleanup_residual_preview`

**Signature** : `get_cleanup_residual_preview(run_id: str) -> Dict[str, Any]`

**Description** : Preview du nettoyage de fin de run : dossiers vides + residuels identifies.


### 6. Probe tools

#### `POST /api/get_probe_tools_status`

**Signature** : `get_probe_tools_status() -> Dict[str, Any]`

**Description** : Retourne le statut de detection de ffprobe + MediaInfo (version, chemin, dispo).

#### `POST /api/auto_install_probe_tools`

**Signature** : `auto_install_probe_tools() -> Dict[str, Any]`

**Description** : Telecharge et installe ffprobe + MediaInfo depuis les sources officielles.


### 7. Integrations (TMDb / Jellyfin / Plex / Radarr)

#### `POST /api/import_watchlist`

**Signature** : `import_watchlist(csv_content: str, source: str) -> Dict[str, Any]`

**Description** : Importe une watchlist CSV et compare avec la bibliotheque locale.

#### `POST /api/test_email_report`

**Signature** : `test_email_report() -> Dict[str, Any]`

**Description** : Envoie un email test avec des donnees mock.


### 8. Library, Films & UI

#### `POST /api/get_dashboard`

**Signature** : `get_dashboard(run_id: str = 'latest') -> Dict[str, Any]`

**Description** : Dashboard d'un run (KPIs, distribution scores, anomalies, timeline).

#### `POST /api/get_dashboard_qr`

**Signature** : `get_dashboard_qr() -> Dict[str, Any]`

**Description** : Retourne un QR code SVG inline pour l'URL du dashboard distant.

#### `POST /api/get_global_stats`

**Signature** : `get_global_stats(limit_runs: int = 20) -> Dict[str, Any]`

**Description** : Global dashboard: multi-run statistics for the library.

#### `POST /api/export_run_nfo`

**Signature** : `export_run_nfo(run_id: str, overwrite: bool = False, dry_run: bool = True) -> Dict[str, Any]`

**Description** : Génère des fichiers .nfo (Kodi/Jellyfin) pour chaque film du run.

#### `POST /api/check_duplicates`

**Signature** : `check_duplicates(run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]`

**Description** : Detecte les collisions de destination entre rows approuvees avant apply.


### 9. Notifications & System

#### `POST /api/get_notifications`

**Signature** : `get_notifications(unread_only: bool = False, limit: int = 100, category: Optional[str] = None) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : liste les notifications en memoire (LIFO).

#### `POST /api/get_notifications_unread_count`

**Signature** : `get_notifications_unread_count() -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : compteur pour le badge top bar.

#### `POST /api/mark_notification_read`

**Signature** : `mark_notification_read(notification_id: str) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : marque une notification comme lue.

#### `POST /api/mark_all_notifications_read`

**Signature** : `mark_all_notifications_read() -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : marque toutes les notifications comme lues.

#### `POST /api/dismiss_notification`

**Signature** : `dismiss_notification(notification_id: str) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : supprime une notification du centre.

#### `POST /api/clear_notifications`

**Signature** : `clear_notifications() -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : vide completement le centre de notifications.

#### `POST /api/check_for_updates`

**Signature** : `check_for_updates() -> Dict[str, Any]`

**Description** : V3-12 — Force un check MAJ immediat (bouton "Verifier maintenant").

#### `POST /api/get_update_info`

**Signature** : `get_update_info() -> Dict[str, Any]`

**Description** : V3-12 — Retourne le dernier resultat connu (cache).

#### `POST /api/open_logs_folder`

**Signature** : `open_logs_folder() -> Dict[str, Any]`

**Description** : V3-13 — Ouvre le dossier des logs dans l'explorateur Windows.

#### `POST /api/test_reset`

**Signature** : `test_reset(min_video_bytes: int = 0) -> Dict[str, Any]`

**Description** : Remet l'app dans un etat propre pour les tests E2E. Desactive en production.

#### `POST /api/is_demo_mode_active`

**Signature** : `is_demo_mode_active() -> Dict[str, Any]`

**Description** : V3-05 : True si au moins un run is_demo est présent en BDD.

#### `POST /api/start_demo_mode`

**Signature** : `start_demo_mode() -> Dict[str, Any]`

**Description** : V3-05 : active le mode démo (15 films fictifs + run + plan.jsonl).

#### `POST /api/stop_demo_mode`

**Signature** : `stop_demo_mode() -> Dict[str, Any]`

**Description** : V3-05 : désactive le mode démo (supprime runs + quality_reports + run_dir).


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
