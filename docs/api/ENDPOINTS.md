# CineSort REST API — Endpoints

> Auto-genere depuis l'introspection de `CineSortApi` (V3-06, mai 2026).
> Regenerer apres changement d'API : `python scripts/gen_endpoints_doc.py`

## Vue d'ensemble

- **Total endpoints publics** : 99
- **Methode HTTP** : `POST /api/{method_name}` avec body JSON
- **Auth** : `Authorization: Bearer <token>` (token configure dans les Reglages)
- **Format reponse** : `{"ok": true, ...}` ou `{"ok": false, "message": "..."}`
- **Endpoints publics** : `GET /api/health` (sans auth) et `GET /api/spec` (OpenAPI)
- **Body max** : 16 MB ; **Rate limit auth** : 5 echecs / 60s par IP

## Endpoints groupes par categorie

### 1. Configuration & Settings

#### `POST /api/get_settings`

**Signature** : `get_settings() -> Dict[str, Any]`

**Description** : _(pas de docstring)_

#### `POST /api/save_settings`

**Signature** : `save_settings(settings: Dict[str, Any]) -> Dict[str, Any]`

**Description** : _(pas de docstring)_

#### `POST /api/get_server_info`

**Signature** : `get_server_info() -> Dict[str, Any]`

**Description** : Retourne les infos du serveur REST (IP, port, URL dashboard).

#### `POST /api/get_log_paths`

**Signature** : `get_log_paths() -> Dict[str, Any]`

**Description** : V3-13 — Retourne les chemins des logs (pour affichage UI + copie).

#### `POST /api/restart_api_server`

**Signature** : `restart_api_server() -> Dict[str, Any]`

**Description** : Arrete et relance le serveur REST avec les settings actuels.

#### `POST /api/get_event_ts`

**Signature** : `get_event_ts() -> Dict[str, Any]`

**Description** : Retourne le timestamp du dernier evenement significatif (scan/apply/settings).


### 2. Scan & Plan

#### `POST /api/start_plan`

**Signature** : `start_plan(settings: Dict[str, Any]) -> Dict[str, Any]`

**Description** : Demarre un scan+plan en thread background. Retourne {run_id, ok}.

#### `POST /api/get_status`

**Signature** : `get_status(run_id: str, last_log_index: int = 0) -> Dict[str, Any]`

**Description** : Retourne l'etat courant d'un run : progression, logs incrementaux, sante.

#### `POST /api/cancel_run`

**Signature** : `cancel_run(run_id: str) -> Dict[str, Any]`

**Description** : Demande l'annulation d'un run en cours (pose cancel_requested=1).

#### `POST /api/get_plan`

**Signature** : `get_plan(run_id: str) -> Dict[str, Any]`

**Description** : Retourne la liste des PlanRow persistees dans plan.jsonl pour ce run.

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

#### `POST /api/build_apply_preview`

**Signature** : `build_apply_preview(run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]`

**Description** : P1.3 : plan structuré "avant/après" des déplacements, par film.

#### `POST /api/list_apply_history`

**Signature** : `list_apply_history(run_id: str) -> Dict[str, Any]`

**Description** : Liste les batches apply (reels + dry-run) d'un run, plus recent en premier.

#### `POST /api/export_apply_audit`

**Signature** : `export_apply_audit(run_id: str, batch_id: Optional[str] = None, as_format: str = 'json') -> Dict[str, Any]`

**Description** : P2.3 : journal d'audit JSONL d'un apply (complémentaire à apply_operations).

#### `POST /api/undo_last_apply`

**Signature** : `undo_last_apply(run_id: str, dry_run: bool = True, atomic: bool = True) -> Dict[str, Any]`

**Description** : Annule le dernier batch apply reel (undo v1). `dry_run=True` ne touche rien.

#### `POST /api/undo_last_apply_preview`

**Signature** : `undo_last_apply_preview(run_id: str) -> Dict[str, Any]`

**Description** : Preview (dry) de l'annulation du dernier batch apply reel (undo v1).

#### `POST /api/undo_by_row_preview`

**Signature** : `undo_by_row_preview(run_id: str, batch_id: str = None) -> Dict[str, Any]`

**Description** : Preview de l'annulation par film : resume par row_id du batch cible (undo v5).

#### `POST /api/undo_selected_rows`

**Signature** : `undo_selected_rows(run_id: str, row_ids: list = None, dry_run: bool = True, batch_id: str = None, atomic: bool = True) -> Dict[str, Any]`

**Description** : Annule selectivement les rows choisies (undo v5). `dry_run=True` ne touche rien.

#### `POST /api/get_cleanup_residual_preview`

**Signature** : `get_cleanup_residual_preview(run_id: str) -> Dict[str, Any]`

**Description** : Preview du nettoyage de fin de run : dossiers vides + residuels identifies.


### 4. Quality & Scoring

#### `POST /api/analyze_quality_batch`

**Signature** : `analyze_quality_batch(run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Analyse qualite batch sur plusieurs films (probe + scoring).

#### `POST /api/get_quality_report`

**Signature** : `get_quality_report(run_id: str, row_id: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Retourne le rapport de scoring qualite d'un film (score, tier, reasons, metrics).

#### `POST /api/get_quality_profile`

**Signature** : `get_quality_profile() -> Dict[str, Any]`

**Description** : Retourne le profil de scoring qualite actif (poids, seuils, toggles).

#### `POST /api/save_quality_profile`

**Signature** : `save_quality_profile(profile_json: Any) -> Dict[str, Any]`

**Description** : Enregistre un profil de scoring custom (valide, persiste, active).

#### `POST /api/reset_quality_profile`

**Signature** : `reset_quality_profile() -> Dict[str, Any]`

**Description** : Reinitialise le profil de scoring aux valeurs par defaut.

#### `POST /api/get_quality_presets`

**Signature** : `get_quality_presets() -> Dict[str, Any]`

**Description** : Retourne le catalogue des presets de scoring (Remux strict / Equilibre / Light).

#### `POST /api/apply_quality_preset`

**Signature** : `apply_quality_preset(preset_id: str) -> Dict[str, Any]`

**Description** : Applique un preset du catalogue comme profil de scoring actif.

#### `POST /api/save_custom_quality_preset`

**Signature** : `save_custom_quality_preset(name: str, profile_json: Dict[str, Any]) -> Dict[str, Any]`

**Description** : Persiste un profil qualite custom et l'active (G5).

#### `POST /api/simulate_quality_preset`

**Signature** : `simulate_quality_preset(run_id: str = 'latest', preset_id: str = 'equilibre', overrides: Optional[Dict[str, Any]] = None, scope: str = 'run') -> Dict[str, Any]`

**Description** : Simule l'application d'un preset qualite sans persister (G5).

#### `POST /api/export_quality_profile`

**Signature** : `export_quality_profile() -> Dict[str, Any]`

**Description** : Exporte le profil de scoring actif en JSON (pour partage / backup).

#### `POST /api/import_quality_profile`

**Signature** : `import_quality_profile(profile_json: Any) -> Dict[str, Any]`

**Description** : Importe un profil de scoring depuis JSON (valide, persiste, active).

#### `POST /api/export_shareable_profile`

**Signature** : `export_shareable_profile(name: str = '', author: str = '', description: str = '') -> Dict[str, Any]`

**Description** : P4.3 : exporte le profil qualité actif au format communautaire.

#### `POST /api/import_shareable_profile`

**Signature** : `import_shareable_profile(content: str, activate: bool = True) -> Dict[str, Any]`

**Description** : P4.3 : importe un profil depuis un JSON communautaire (avec metadata).

#### `POST /api/get_calibration_report`

**Signature** : `get_calibration_report() -> Dict[str, Any]`

**Description** : P4.1 : agrège tous les feedbacks et propose un ajustement de poids.

#### `POST /api/get_scoring_rollup`

**Signature** : `get_scoring_rollup(by: str = 'franchise', limit: int = 20, run_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 7 : scoring agrege par dimension (franchise / decade / codec / era_grain).

#### `POST /api/submit_score_feedback`

**Signature** : `submit_score_feedback(run_id: str, row_id: str, user_tier: str, category_focus: Optional[str] = None, comment: Optional[str] = None) -> Dict[str, Any]`

**Description** : P4.1 : enregistrer un feedback utilisateur sur le scoring d'un film.

#### `POST /api/delete_score_feedback`

**Signature** : `delete_score_feedback(feedback_id: int) -> Dict[str, Any]`

**Description** : P4.1 : supprime un feedback utilisateur (cleanup / correction).

#### `POST /api/get_custom_rules_catalog`

**Signature** : `get_custom_rules_catalog() -> Dict[str, Any]`

**Description** : Retourne les fields, operators et actions disponibles pour le builder UI (G6).

#### `POST /api/get_custom_rules_templates`

**Signature** : `get_custom_rules_templates() -> Dict[str, Any]`

**Description** : Retourne les 3 templates starter de regles custom (G6).

#### `POST /api/validate_custom_rules`

**Signature** : `validate_custom_rules(rules: Any) -> Dict[str, Any]`

**Description** : Valide une liste de regles custom sans persister (G6).


### 5. Perceptual analysis

#### `POST /api/analyze_perceptual_batch`

**Signature** : `analyze_perceptual_batch(run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Analyse perceptuelle batch sur plusieurs films.

#### `POST /api/get_perceptual_report`

**Signature** : `get_perceptual_report(run_id: str, row_id: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Analyse perceptuelle d'un film (a la demande).

#### `POST /api/compare_perceptual`

**Signature** : `compare_perceptual(run_id: str, row_id_a: str, row_id_b: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Comparaison perceptuelle profonde entre 2 fichiers.


### 6. Probe tools

#### `POST /api/get_probe`

**Signature** : `get_probe(run_id: str, row_id: str) -> Dict[str, Any]`

**Description** : Retourne la probe normalisee (video/audio/sous-titres) d'un film du run.

#### `POST /api/get_probe_tools_status`

**Signature** : `get_probe_tools_status() -> Dict[str, Any]`

**Description** : Retourne le statut de detection de ffprobe + MediaInfo (version, chemin, dispo).

#### `POST /api/auto_install_probe_tools`

**Signature** : `auto_install_probe_tools() -> Dict[str, Any]`

**Description** : Telecharge et installe ffprobe + MediaInfo depuis les sources officielles.

#### `POST /api/install_probe_tools`

**Signature** : `install_probe_tools(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Installe ffprobe + MediaInfo via winget (ou options fournies).

#### `POST /api/update_probe_tools`

**Signature** : `update_probe_tools(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Met a jour ffprobe + MediaInfo via winget.

#### `POST /api/recheck_probe_tools`

**Signature** : `recheck_probe_tools() -> Dict[str, Any]`

**Description** : Force une redetection des outils probe (utile apres installation manuelle).

#### `POST /api/set_probe_tool_paths`

**Signature** : `set_probe_tool_paths(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Enregistre des chemins manuels vers ffprobe / MediaInfo (si hors PATH).

#### `POST /api/get_tools_status`

**Signature** : `get_tools_status() -> Dict[str, Any]`

**Description** : _(pas de docstring)_


### 7. Integrations (TMDb / Jellyfin / Plex / Radarr)

#### `POST /api/test_tmdb_key`

**Signature** : `test_tmdb_key(api_key: str, state_dir: str, timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : _(pas de docstring)_

#### `POST /api/get_tmdb_posters`

**Signature** : `get_tmdb_posters(tmdb_ids: List[int], size: str = 'w92') -> Dict[str, Any]`

**Description** : Retourne les URLs de posters TMDb pour les IDs demandes (cache local).

#### `POST /api/test_jellyfin_connection`

**Signature** : `test_jellyfin_connection(url: str = '', api_key: str = '', timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : Teste la connexion au serveur Jellyfin.

#### `POST /api/get_jellyfin_libraries`

**Signature** : `get_jellyfin_libraries() -> Dict[str, Any]`

**Description** : Retourne les bibliothèques Jellyfin configurées.

#### `POST /api/get_jellyfin_sync_report`

**Signature** : `get_jellyfin_sync_report(run_id: str = '') -> Dict[str, Any]`

**Description** : Compare la bibliotheque locale avec Jellyfin. Retourne le rapport de coherence.

#### `POST /api/test_plex_connection`

**Signature** : `test_plex_connection(url: str = '', token: str = '', timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : Teste la connexion au serveur Plex.

#### `POST /api/get_plex_libraries`

**Signature** : `get_plex_libraries(url: str = '', token: str = '', timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : Retourne les sections movie du serveur Plex.

#### `POST /api/get_plex_sync_report`

**Signature** : `get_plex_sync_report(run_id: str = '') -> Dict[str, Any]`

**Description** : Compare la bibliotheque locale avec Plex.

#### `POST /api/test_radarr_connection`

**Signature** : `test_radarr_connection(url: str = '', api_key: str = '', timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : Teste la connexion au serveur Radarr.

#### `POST /api/get_radarr_status`

**Signature** : `get_radarr_status(run_id: str = '') -> Dict[str, Any]`

**Description** : Rapport Radarr : matching, upgrade candidates.

#### `POST /api/request_radarr_upgrade`

**Signature** : `request_radarr_upgrade(radarr_movie_id: int) -> Dict[str, Any]`

**Description** : Demande a Radarr de chercher une meilleure version d'un film.

#### `POST /api/import_watchlist`

**Signature** : `import_watchlist(csv_content: str, source: str) -> Dict[str, Any]`

**Description** : Importe une watchlist CSV et compare avec la bibliotheque locale.

#### `POST /api/test_email_report`

**Signature** : `test_email_report() -> Dict[str, Any]`

**Description** : Envoie un email test avec des donnees mock.


### 8. Library, Films & UI

#### `POST /api/get_library_filtered`

**Signature** : `get_library_filtered(run_id: Optional[str] = None, filters: Optional[Dict[str, Any]] = None, sort: str = 'title', page: int = 1, page_size: int = 50) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 3 : Library filtree, triee, paginee.

#### `POST /api/get_film_full`

**Signature** : `get_film_full(row_id: str, run_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 4 : toutes les infos d'un film pour la page standalone.

#### `POST /api/get_film_history`

**Signature** : `get_film_history(film_id: str) -> Dict[str, Any]`

**Description** : Timeline complete d'un film a travers tous les runs.

#### `POST /api/list_films_with_history`

**Signature** : `list_films_with_history(limit: int = 50) -> Dict[str, Any]`

**Description** : Liste des films du dernier run avec resume d'historique.

#### `POST /api/get_dashboard`

**Signature** : `get_dashboard(run_id: str = 'latest') -> Dict[str, Any]`

**Description** : Dashboard d'un run (KPIs, distribution scores, anomalies, timeline).

#### `POST /api/get_dashboard_qr`

**Signature** : `get_dashboard_qr() -> Dict[str, Any]`

**Description** : Retourne un QR code SVG inline pour l'URL du dashboard distant.

#### `POST /api/get_global_stats`

**Signature** : `get_global_stats(limit_runs: int = 20) -> Dict[str, Any]`

**Description** : Global dashboard: multi-run statistics for the library.

#### `POST /api/get_smart_playlists`

**Signature** : `get_smart_playlists() -> Dict[str, Any]`

**Description** : v7.6.0 Vague 3 : liste des smart playlists (presets + custom).

#### `POST /api/save_smart_playlist`

**Signature** : `save_smart_playlist(name: str, filters: Dict[str, Any], playlist_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 3 : cree ou met a jour une smart playlist custom.

#### `POST /api/delete_smart_playlist`

**Signature** : `delete_smart_playlist(playlist_id: str) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 3 : supprime une smart playlist custom.

#### `POST /api/get_naming_presets`

**Signature** : `get_naming_presets() -> Dict[str, Any]`

**Description** : Retourne la liste des presets de renommage disponibles.

#### `POST /api/preview_naming_template`

**Signature** : `preview_naming_template(template: str = '', sample_row_id: str = '') -> Dict[str, Any]`

**Description** : Preview du resultat d'un template de renommage sur un film exemple.

#### `POST /api/export_run_report`

**Signature** : `export_run_report(run_id: str, fmt: str = 'json') -> Dict[str, Any]`

**Description** : Exporte le rapport du run au format json / csv / html.

#### `POST /api/export_run_nfo`

**Signature** : `export_run_nfo(run_id: str, overwrite: bool = False, dry_run: bool = True) -> Dict[str, Any]`

**Description** : Génère des fichiers .nfo (Kodi/Jellyfin) pour chaque film du run.

#### `POST /api/get_auto_approved_summary`

**Signature** : `get_auto_approved_summary(run_id: str, threshold: int = 85, enabled: bool = False, quarantine_corrupted: bool = False) -> Dict[str, Any]`

**Description** : Resume des rows auto-approuvees selon le seuil de confiance (mode batch).

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

#### `POST /api/reset_incremental_cache`

**Signature** : `reset_incremental_cache() -> Dict[str, Any]`

**Description** : Purge TOTALE du cache incremental (3 tables, tous roots confondus).

#### `POST /api/reset_all_user_data`

**Signature** : `reset_all_user_data(confirmation: str = '') -> Dict[str, Any]`

**Description** : V3-09 — Reset toutes les donnees user (avec backup ZIP automatique).

#### `POST /api/get_user_data_size`

**Signature** : `get_user_data_size() -> Dict[str, Any]`

**Description** : V3-09 — Taille actuelle du user-data (pour affichage UI Danger Zone).

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
