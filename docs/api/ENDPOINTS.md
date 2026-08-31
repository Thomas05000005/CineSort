# CineSort REST API — Endpoints

> Auto-genere depuis l'introspection de `CineSortApi` (V3-06, mai 2026).
> Regenerer apres changement d'API : `python scripts/gen_endpoints_doc.py`

## Vue d'ensemble

- **Total endpoints publics** : 172
- **Methode HTTP** : `POST /api/{facade}/{method_name}` avec body JSON
- **Chemins directs `POST /api/{method_name}`** : desactives par defaut (P0 #233) — le serveur repond `410 Gone` avec `Use /api/<facade>/<method> instead`
- **Auth** : `Authorization: Bearer <token>` (token configure dans les Reglages)
- **Format reponse** : `{"ok": true, ...}` ou `{"ok": false, "message": "..."}`
- **Endpoints publics** : `GET /api/health` (sans auth) et `GET /api/spec` (OpenAPI)
- **Body max** : 16 MB ; **Rate limit auth** : 5 echecs / 60s par IP

## Endpoints groupes par categorie

### 1. Configuration & Settings

#### `POST /api/settings/get_settings`

**Signature** : `get_settings() -> Dict[str, Any]`

**Description** : Charge la configuration utilisateur depuis settings.json.

#### `POST /api/settings/save_settings`

**Signature** : `save_settings(settings: Dict[str, Any]) -> Dict[str, Any]`

**Description** : Persiste les settings + applique side effects (state_dir, locale, etc).

#### `POST /api/settings/get_server_info`

**Signature** : `get_server_info() -> Dict[str, Any]`

**Description** : Retourne les infos du serveur REST (IP, port, URL dashboard).

#### `POST /api/runtime/get_log_paths`

**Signature** : `get_log_paths() -> Dict[str, Any]`

**Description** : V3-13 — Retourne les chemins des logs (pour affichage UI + copie).

#### `POST /api/settings/restart_api_server`

**Signature** : `restart_api_server() -> Dict[str, Any]`

**Description** : Arrete et relance le serveur REST avec les settings actuels.


### 2. Scan & Plan

#### `POST /api/run/start_plan`

**Signature** : `start_plan(settings: Dict[str, Any]) -> Dict[str, Any]`

**Description** : Demarre un scan+plan en thread background.

#### `POST /api/run/get_status`

**Signature** : `get_status(run_id: str, last_log_index: int = 0) -> Dict[str, Any]`

**Description** : Progression + logs + sante d'un run.

#### `POST /api/run/cancel_run`

**Signature** : `cancel_run(run_id: str) -> Dict[str, Any]`

**Description** : Demande l'annulation d'un run en cours (pose cancel_requested=1).

#### `POST /api/run/get_plan`

**Signature** : `get_plan(run_id: str) -> Dict[str, Any]`

**Description** : Retourne la liste des PlanRow persistees dans plan.jsonl.

#### `POST /api/run/load_validation`

**Signature** : `load_validation(run_id: str) -> Dict[str, Any]`

**Description** : Recharge les decisions (approve/reject) persistees pour ce run.

#### `POST /api/run/save_validation`

**Signature** : `save_validation(run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]`

**Description** : Persiste les decisions de validation dans validation.json (atomique).

#### `POST /api/runtime/validate_dropped_path`

**Signature** : `validate_dropped_path(path: str = '') -> Dict[str, Any]`

**Description** : Valide qu'un chemin droppe est un dossier existant.

#### `POST /api/run/get_sidebar_counters`

**Signature** : `get_sidebar_counters() -> Dict[str, Any]`

**Description** : V3-04 : compteurs sidebar pour badges UI (validation/application/quality).


### 3. Apply & Undo

#### `POST /api/run/apply`

**Signature** : `apply(run_id: str, decisions: Dict[str, Dict[str, Any]], dry_run: bool, quarantine_unapproved: bool, apply_atomic: bool = False) -> Dict[str, Any]`

**Description** : Applique les decisions de validation (deplacements/renommages reels ou dry-run).

#### `POST /api/run/build_apply_preview`

**Signature** : `build_apply_preview(run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]`

**Description** : Plan structure "avant/apres" des deplacements, par film.

#### `POST /api/run/list_apply_history`

**Signature** : `list_apply_history(run_id: str) -> Dict[str, Any]`

**Description** : Historique de tous les applies d'un run (batches reels + dry-run).

#### `POST /api/run/export_apply_audit`

**Signature** : `export_apply_audit(run_id: str, batch_id: Optional[str] = None, as_format: str = 'json') -> Dict[str, Any]`

**Description** : P2.3 : journal d'audit JSONL d'un apply (complementaire a apply_operations).

#### `POST /api/run/undo_last_apply`

**Signature** : `undo_last_apply(run_id: str, dry_run: bool = True, atomic: bool = True) -> Dict[str, Any]`

**Description** : Annule le dernier batch apply reel (undo v1). `dry_run=True` ne touche rien.

#### `POST /api/run/get_cleanup_residual_preview`

**Signature** : `get_cleanup_residual_preview(run_id: str) -> Dict[str, Any]`

**Description** : Preview du nettoyage de fin de run : dossiers vides + residuels identifies.


### 4. Quality & Scoring

#### `POST /api/quality/analyze_quality_batch`

**Signature** : `analyze_quality_batch(run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Analyse qualite batch sur plusieurs films (probe + scoring).

#### `POST /api/quality/get_quality_report`

**Signature** : `get_quality_report(run_id: str, row_id: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Rapport de scoring qualite d'un film (score, tier, reasons, metrics).

#### `POST /api/quality/get_quality_profile`

**Signature** : `get_quality_profile() -> Dict[str, Any]`

**Description** : Profil de scoring actif (poids, seuils, toggles).

#### `POST /api/quality/save_quality_profile`

**Signature** : `save_quality_profile(profile_json: Any) -> Dict[str, Any]`

**Description** : Enregistre un profil de scoring custom (valide, persiste, active).

#### `POST /api/quality/reset_quality_profile`

**Signature** : `reset_quality_profile(dry_run: bool = True) -> Dict[str, Any]`

**Description** : Reinitialise le profil de scoring aux valeurs par defaut.

#### `POST /api/quality/get_quality_presets`

**Signature** : `get_quality_presets() -> Dict[str, Any]`

**Description** : Catalogue des presets de scoring (Remux strict / Equilibre / Light).

#### `POST /api/quality/apply_quality_preset`

**Signature** : `apply_quality_preset(preset_id: str) -> Dict[str, Any]`

**Description** : Applique un preset du catalogue comme profil de scoring actif.

#### `POST /api/quality/save_custom_quality_preset`

**Signature** : `save_custom_quality_preset(name: str, profile_json: Dict[str, Any]) -> Dict[str, Any]`

**Description** : Persiste un profil qualite custom et l'active (G5).

#### `POST /api/quality/simulate_quality_preset`

**Signature** : `simulate_quality_preset(run_id: str = 'latest', preset_id: str = 'equilibre', overrides: Optional[Dict[str, Any]] = None, scope: str = 'run') -> Dict[str, Any]`

**Description** : Simule l'application d'un preset qualite sans persister (G5).

#### `POST /api/quality/export_quality_profile`

**Signature** : `export_quality_profile() -> Dict[str, Any]`

**Description** : Exporte le profil de scoring actif en JSON.

#### `POST /api/quality/import_quality_profile`

**Signature** : `import_quality_profile(profile_json: Any) -> Dict[str, Any]`

**Description** : Importe un profil de scoring depuis JSON (valide, persiste, active).

#### `POST /api/quality/get_calibration_report`

**Signature** : `get_calibration_report() -> Dict[str, Any]`

**Description** : P4.1 : agrege tous les feedbacks et propose un ajustement de poids.

#### `POST /api/library/get_scoring_rollup`

**Signature** : `get_scoring_rollup(by: str = 'franchise', limit: int = 20, run_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 7 : scoring agrege par dimension (franchise / decade / codec / era_grain).

#### `POST /api/quality/submit_score_feedback`

**Signature** : `submit_score_feedback(run_id: str, row_id: str, user_tier: str, category_focus: Optional[str] = None, comment: Optional[str] = None) -> Dict[str, Any]`

**Description** : P4.1 : enregistrer un feedback utilisateur sur le scoring d'un film.

#### `POST /api/quality/delete_score_feedback`

**Signature** : `delete_score_feedback(feedback_id: int) -> Dict[str, Any]`

**Description** : P4.1 : supprime un feedback utilisateur (cleanup / correction).

#### `POST /api/quality/get_custom_rules_catalog`

**Signature** : `get_custom_rules_catalog() -> Dict[str, Any]`

**Description** : Fields, operators et actions disponibles pour le builder UI (G6).

#### `POST /api/quality/get_custom_rules_templates`

**Signature** : `get_custom_rules_templates() -> Dict[str, Any]`

**Description** : 3 templates starter de regles custom (G6).

#### `POST /api/quality/validate_custom_rules`

**Signature** : `validate_custom_rules(rules: Any) -> Dict[str, Any]`

**Description** : Valide une liste de regles custom sans persister (G6).


### 5. Perceptual analysis

#### `POST /api/quality/analyze_perceptual_batch`

**Signature** : `analyze_perceptual_batch(run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Analyse perceptuelle batch sur plusieurs films.

#### `POST /api/quality/get_perceptual_report`

**Signature** : `get_perceptual_report(run_id: str, row_id: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Analyse perceptuelle d'un film (a la demande).

#### `POST /api/quality/compare_perceptual`

**Signature** : `compare_perceptual(run_id: str, row_id_a: str, row_id_b: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Comparaison perceptuelle profonde entre 2 fichiers.


### 6. Probe tools

#### `POST /api/runtime/get_probe_tools_status`

**Signature** : `get_probe_tools_status() -> Dict[str, Any]`

**Description** : Retourne le statut de detection de ffprobe + MediaInfo (version, chemin, dispo).

#### `POST /api/runtime/auto_install_probe_tools`

**Signature** : `auto_install_probe_tools() -> Dict[str, Any]`

**Description** : Telecharge et installe ffprobe + MediaInfo depuis les sources officielles.


### 7. Integrations (TMDb / Jellyfin / Plex / Radarr)

#### `POST /api/integrations/test_tmdb_key`

**Signature** : `test_tmdb_key(api_key: str, state_dir: str, timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : Test la cle TMDb et retourne les capacites.

#### `POST /api/integrations/get_tmdb_posters`

**Signature** : `get_tmdb_posters(tmdb_ids: List[int], size: str = 'w92', force_refresh: bool = False) -> Dict[str, Any]`

**Description** : Recupere les URL posters TMDb pour une liste d'IDs.

#### `POST /api/integrations/test_jellyfin_connection`

**Signature** : `test_jellyfin_connection(url: str = '', api_key: str = '', timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : Test la connexion au serveur Jellyfin.

#### `POST /api/integrations/get_jellyfin_libraries`

**Signature** : `get_jellyfin_libraries() -> Dict[str, Any]`

**Description** : Retourne les bibliotheques Jellyfin configurees.

#### `POST /api/integrations/get_jellyfin_sync_report`

**Signature** : `get_jellyfin_sync_report(run_id: str = '') -> Dict[str, Any]`

**Description** : Rapport de sync Jellyfin pour un run (ou dernier run).

#### `POST /api/integrations/test_plex_connection`

**Signature** : `test_plex_connection(url: str = '', token: str = '', timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : Test la connexion au serveur Plex.

#### `POST /api/integrations/get_plex_libraries`

**Signature** : `get_plex_libraries(url: str = '', token: str = '', timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : Retourne les bibliotheques Plex configurees.

#### `POST /api/integrations/get_plex_sync_report`

**Signature** : `get_plex_sync_report(run_id: str = '') -> Dict[str, Any]`

**Description** : Rapport de sync Plex pour un run (ou dernier run).

#### `POST /api/integrations/test_radarr_connection`

**Signature** : `test_radarr_connection(url: str = '', api_key: str = '', timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : Test la connexion au serveur Radarr.

#### `POST /api/integrations/get_radarr_status`

**Signature** : `get_radarr_status(run_id: str = '') -> Dict[str, Any]`

**Description** : Statut Radarr pour un run (films trouves vs absents).

#### `POST /api/integrations/request_radarr_upgrade`

**Signature** : `request_radarr_upgrade(radarr_movie_id: int) -> Dict[str, Any]`

**Description** : Declenche un upgrade Radarr pour un film.

#### `POST /api/run/import_watchlist`

**Signature** : `import_watchlist(csv_content: str, source: str) -> Dict[str, Any]`

**Description** : Importe une watchlist CSV (Letterboxd/IMDb) et compare avec la bibliotheque locale.


### 8. Library, Films & UI

#### `POST /api/library/get_library_filtered`

**Signature** : `get_library_filtered(run_id: Optional[str] = None, filters: Optional[Dict[str, Any]] = None, sort: str = 'title', page: int = 1, page_size: int = 50) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 3 : library filtree, triee, paginee.

#### `POST /api/library/get_film_full`

**Signature** : `get_film_full(row_id: str, run_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 4 : toutes les infos d'un film pour la page standalone.

#### `POST /api/library/get_film_history`

**Signature** : `get_film_history(film_id: str) -> Dict[str, Any]`

**Description** : Timeline complete d'un film a travers tous les runs.

#### `POST /api/library/list_films_with_history`

**Signature** : `list_films_with_history(limit: int = 50) -> Dict[str, Any]`

**Description** : Liste des films du dernier run avec resume d'historique.

#### `POST /api/run/get_dashboard`

**Signature** : `get_dashboard(run_id: str = 'latest') -> Dict[str, Any]`

**Description** : Dashboard d'un run (KPIs, distribution scores, anomalies, timeline).

#### `POST /api/settings/get_dashboard_qr`

**Signature** : `get_dashboard_qr() -> Dict[str, Any]`

**Description** : Retourne un QR code SVG inline pour l'URL du dashboard distant.

#### `POST /api/run/get_global_stats`

**Signature** : `get_global_stats(limit_runs: int = 20) -> Dict[str, Any]`

**Description** : Global dashboard : statistiques multi-run pour la bibliotheque.

#### `POST /api/library/get_smart_playlists`

**Signature** : `get_smart_playlists() -> Dict[str, Any]`

**Description** : v7.6.0 Vague 3 : liste des smart playlists (presets + custom).

#### `POST /api/library/save_smart_playlist`

**Signature** : `save_smart_playlist(name: str, filters: Dict[str, Any], playlist_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 3 : cree ou met a jour une smart playlist custom.

#### `POST /api/library/delete_smart_playlist`

**Signature** : `delete_smart_playlist(playlist_id: str) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 3 : supprime une smart playlist custom.

#### `POST /api/run/export_run_report`

**Signature** : `export_run_report(run_id: str, fmt: str = 'json') -> Dict[str, Any]`

**Description** : Exporte le rapport du run au format json / csv / html.

#### `POST /api/run/export_run_nfo`

**Signature** : `export_run_nfo(run_id: str, overwrite: bool = False, dry_run: bool = True) -> Dict[str, Any]`

**Description** : Genere des fichiers .nfo (Kodi/Jellyfin) pour chaque film du run.

#### `POST /api/run/check_duplicates`

**Signature** : `check_duplicates(run_id: str, decisions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]`

**Description** : Detecte les collisions de destination entre rows approuvees avant apply.


### 9. Notifications & System

#### `POST /api/runtime/get_notifications`

**Signature** : `get_notifications(unread_only: bool = False, limit: int = 100, category: Optional[str] = None) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : liste les notifications en memoire (LIFO).

#### `POST /api/runtime/get_notifications_unread_count`

**Signature** : `get_notifications_unread_count() -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : compteur pour le badge top bar.

#### `POST /api/runtime/mark_notification_read`

**Signature** : `mark_notification_read(notification_id: str) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : marque une notification comme lue.

#### `POST /api/runtime/mark_all_notifications_read`

**Signature** : `mark_all_notifications_read() -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : marque toutes les notifications comme lues.

#### `POST /api/runtime/dismiss_notification`

**Signature** : `dismiss_notification(notification_id: str) -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : supprime une notification du centre.

#### `POST /api/runtime/clear_notifications`

**Signature** : `clear_notifications() -> Dict[str, Any]`

**Description** : v7.6.0 Vague 9 : vide completement le centre de notifications.

#### `POST /api/runtime/check_for_updates`

**Signature** : `check_for_updates() -> Dict[str, Any]`

**Description** : V3-12 — Force un check MAJ immediat (bouton "Verifier maintenant").

#### `POST /api/runtime/get_update_info`

**Signature** : `get_update_info(force_refresh: bool = False) -> Dict[str, Any]`

**Description** : V3-12 — Retourne le dernier resultat connu (cache).

#### `POST /api/runtime/open_logs_folder`

**Signature** : `open_logs_folder() -> Dict[str, Any]`

**Description** : V3-13 — Ouvre le dossier des logs dans l'explorateur Windows.

#### `POST /api/settings/reset_all_user_data`

**Signature** : `reset_all_user_data(confirmation: str = '') -> Dict[str, Any]`

**Description** : V3-09 — Reset toutes les donnees user (avec backup ZIP automatique).

#### `POST /api/settings/get_user_data_size`

**Signature** : `get_user_data_size() -> Dict[str, Any]`

**Description** : V3-09 — Taille actuelle du user-data (pour affichage UI Danger Zone).

#### `POST /api/runtime/is_demo_mode_active`

**Signature** : `is_demo_mode_active() -> Dict[str, Any]`

**Description** : V3-05 : True si au moins un run is_demo est present en BDD.

#### `POST /api/runtime/start_demo_mode`

**Signature** : `start_demo_mode() -> Dict[str, Any]`

**Description** : V3-05 : active le mode demo (15 films fictifs + run + plan.jsonl).

#### `POST /api/runtime/stop_demo_mode`

**Signature** : `stop_demo_mode() -> Dict[str, Any]`

**Description** : V3-05 : desactive le mode demo (supprime runs + quality_reports + run_dir).


### 10. Autres endpoints — facade `integrations`

#### `POST /api/integrations/enrich_tmdb_ids_by_title`

**Signature** : `enrich_tmdb_ids_by_title(run_id: str, row_ids: Any) -> Dict[str, Any]`

**Description** : R5-H2 : resout + persiste le tmdb_id de films identifies sans tmdb_id

#### `POST /api/integrations/refresh_jellyfin_library_now`

**Signature** : `refresh_jellyfin_library_now() -> Dict[str, Any]`

**Description** : Cf #92 quick win #1 : declenche un refresh Jellyfin a la demande.

#### `POST /api/integrations/refresh_plex_library_now`

**Signature** : `refresh_plex_library_now() -> Dict[str, Any]`

**Description** : Cf #92 quick win #1 : declenche un refresh Plex a la demande.

#### `POST /api/integrations/test_email_report`

**Signature** : `test_email_report() -> Dict[str, Any]`

**Description** : Envoie un email test avec des donnees mock pour valider la config SMTP.

#### `POST /api/integrations/test_omdb_connection`

**Signature** : `test_omdb_connection(api_key: str = '', timeout_s: float = 10.0) -> Dict[str, Any]`

**Description** : Teste la cle OMDb (cross-check IMDb pour identification).


### 11. Autres endpoints — facade `library`

#### `POST /api/library/clear_field_lock`

**Signature** : `clear_field_lock(film_id: str, field_name: str) -> Dict[str, Any]`

**Description** : VP-G : retire un verrou champ-par-champ.

#### `POST /api/library/clear_tmdb_override`

**Signature** : `clear_tmdb_override(run_id: Optional[str], row_id: str) -> Dict[str, Any]`

**Description** : R7-12 : annule l'override TMDb manuel. Cf _clear_tmdb_override_impl.

#### `POST /api/library/export_films`

**Signature** : `export_films(row_ids: list, format: str = 'csv', run_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : Phase 4 spec 07 : export CSV / JSON / NDJSON des films selectionnes.

#### `POST /api/library/export_full_library`

**Signature** : `export_full_library() -> Dict[str, Any]`

**Description** : RGPD Art. 20 — export portable de toute la bibliotheque.

#### `POST /api/library/get_films_by_decade`

**Signature** : `get_films_by_decade(filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Distribution des films par decennie (1930s -> 2020s).

#### `POST /api/library/get_incomplete_sagas`

**Signature** : `get_incomplete_sagas() -> Dict[str, Any]`

**Description** : Liste les sagas TMDb avec films manquants dans la bibliotheque.

#### `POST /api/library/get_library_counters_by_chip`

**Signature** : `get_library_counters_by_chip(filters: Optional[Dict[str, Any]] = None, run_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : Phase 4 spec 07 : compteurs par chip (tier x6, problemes x3, structurels x2).

#### `POST /api/library/get_library_podiums`

**Signature** : `get_library_podiums(run_id: Optional[str] = None, limit: int = 10) -> Dict[str, Any]`

**Description** : Top N release groups + codecs + sources pour le run cible.

#### `POST /api/library/get_library_timeline`

**Signature** : `get_library_timeline(months: int = 12, run_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : Films ajoutes par mois (timeline N mois) via Jellyfin DateCreated + fallback mtime.

#### `POST /api/library/list_field_locks`

**Signature** : `list_field_locks(film_id: str) -> Dict[str, Any]`

**Description** : VP-G : liste tous les verrous d'un film (pour render cadenas UI).

#### `POST /api/library/mark_alert_ignored`

**Signature** : `mark_alert_ignored(row_id: str, alert_code: str) -> Dict[str, Any]`

**Description** : Spec 06 §3.3 : persiste "j'ai vu cette alerte, on continue".

#### `POST /api/library/mark_for_deletion`

**Signature** : `mark_for_deletion(run_id: Optional[str], row_id: str) -> Dict[str, Any]`

**Description** : Spec 06 §3.7 : marque un film pour le bucket suppression utilisateur.

#### `POST /api/library/mark_for_deletion_bulk`

**Signature** : `mark_for_deletion_bulk(row_ids: list, run_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : Phase 4 spec 07 : version bulk de mark_for_deletion.

#### `POST /api/library/search_tmdb`

**Signature** : `search_tmdb(query: str, year: Optional[int] = None) -> Dict[str, Any]`

**Description** : Spec 06 3.4 : recherche manuelle TMDb (sous-modal du Modal Film).

#### `POST /api/library/set_field_lock`

**Signature** : `set_field_lock(film_id: str, field_name: str, locked_value: Any = None, source: str = 'ui_lock') -> Dict[str, Any]`

**Description** : VP-G : pose un verrou champ-par-champ Jellyfin-style.

#### `POST /api/library/set_film_tmdb_candidate`

**Signature** : `set_film_tmdb_candidate(run_id: Optional[str], row_id: str, tmdb_id: int) -> Dict[str, Any]`

**Description** : Spec 06 §3.4 : choisir un autre candidat TMDb pour un film.

#### `POST /api/library/unmark_for_deletion`

**Signature** : `unmark_for_deletion(run_id: Optional[str], row_id: str) -> Dict[str, Any]`

**Description** : R7-12 : annule le marquage pour suppression. Cf _unmark_for_deletion_impl.


### 12. Autres endpoints — facade `quality`

#### `POST /api/quality/export_recyclarr_yaml`

**Signature** : `export_recyclarr_yaml(profile_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : Exporte un profil au format Recyclarr v6+ YAML (round-trip lossless).

#### `POST /api/quality/export_shareable_profile`

**Signature** : `export_shareable_profile(name: str = '', author: str = '', description: str = '') -> Dict[str, Any]`

**Description** : P4.3 : exporte le profil qualite actif au format communautaire.

#### `POST /api/quality/get_breakdown_5_axes`

**Signature** : `get_breakdown_5_axes() -> Dict[str, Any]`

**Description** : Retourne le breakdown 5 axes du profil actif pour affichage UI.

#### `POST /api/quality/get_embedded_presets`

**Signature** : `get_embedded_presets() -> Dict[str, Any]`

**Description** : Retourne le preset TRaSH 2026 + alternatifs (puriste DV, qualite max audio).

#### `POST /api/quality/get_films_by_tier`

**Signature** : `get_films_by_tier(tier: str, limit: int = 8) -> Dict[str, Any]`

**Description** : Liste les films d'un tier V2 (default top 8 pires Reject par score asc).

#### `POST /api/quality/get_history`

**Signature** : `get_history(period_days: int = 30) -> Dict[str, Any]`

**Description** : KPIs evolution score V2 + deltas sur N derniers jours.

#### `POST /api/quality/get_perceptual_compare_audio`

**Signature** : `get_perceptual_compare_audio(run_id: str, row_id_a: str, row_id_b: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Phase 4 doublons : waveform PNG + clip MP3 court cote-a-cote.

#### `POST /api/quality/get_perceptual_compare_frames`

**Signature** : `get_perceptual_compare_frames(run_id: str, row_id_a: str, row_id_b: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Cf #94 : N paires de frames cote-a-cote en PNG base64.

#### `POST /api/quality/get_perceptual_details`

**Signature** : `get_perceptual_details(run_id: str, row_id: str) -> Dict[str, Any]`

**Description** : Toutes les metriques perceptuelles persistees (lecture DB).

#### `POST /api/quality/get_perceptual_job_status`

**Signature** : `get_perceptual_job_status(job_id: str) -> Dict[str, Any]`

**Description** : Phase 4 doublons : statut d'un job perceptuel batch.

#### `POST /api/quality/get_profiles`

**Signature** : `get_profiles() -> Dict[str, Any]`

**Description** : Liste tous les profils qualite (presets + custom).

#### `POST /api/quality/get_recompute_job_status`

**Signature** : `get_recompute_job_status(job_id: str) -> Dict[str, Any]`

**Description** : Polling du status d'un job de recalcul lance par recompute_all_scores.

#### `POST /api/quality/get_upgrade_until_score`

**Signature** : `get_upgrade_until_score() -> Dict[str, Any]`

**Description** : Retourne le upgrade_until_score du profil actif (default 10000).

#### `POST /api/quality/import_recyclarr_yaml`

**Signature** : `import_recyclarr_yaml(yaml_text: str, activate: bool = False) -> Dict[str, Any]`

**Description** : Importe un profil depuis YAML Recyclarr, persiste comme custom.

#### `POST /api/quality/import_shareable_profile`

**Signature** : `import_shareable_profile(content: str, activate: bool = True) -> Dict[str, Any]`

**Description** : P4.3 : importe un profil depuis un JSON communautaire (avec metadata).

#### `POST /api/quality/queue_perceptual_analyses`

**Signature** : `queue_perceptual_analyses(pairs: Any, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Phase 4 doublons : queue batch d'analyses perceptuelles en background.

#### `POST /api/quality/queue_perceptual_batch`

**Signature** : `queue_perceptual_batch(run_id: str, row_ids: Any, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : R5-C : analyse perceptuelle batch SINGLE-film (biblio) en background.

#### `POST /api/quality/recompute_all_scores`

**Signature** : `recompute_all_scores() -> Dict[str, Any]`

**Description** : Lance le recalcul background du Score V2 pour tous les films.

#### `POST /api/quality/save_profile`

**Signature** : `save_profile(profile: Dict[str, Any]) -> Dict[str, Any]`

**Description** : Sauve un profil qualite custom (avec validation tiers + poids).

#### `POST /api/quality/set_active_profile`

**Signature** : `set_active_profile(profile_id: str) -> Dict[str, Any]`

**Description** : Active un profil qualite (preset ou custom).

#### `POST /api/quality/set_upgrade_until_score`

**Signature** : `set_upgrade_until_score(score: Any) -> Dict[str, Any]`

**Description** : Met a jour le upgrade_until_score du profil actif (borne [0..100000]).


### 13. Autres endpoints — facade `run`

#### `POST /api/run/check_duplicates_fusion`

**Signature** : `check_duplicates_fusion(run_id: str, decisions: Dict[str, Dict[str, Any]], audio_weight: Optional[float] = None, video_weight: Optional[float] = None) -> Dict[str, Any]`

**Description** : V2.4 — Detection fusion Chromaprint + videohash (feature flag).

#### `POST /api/run/cleanup_old_runs`

**Signature** : `cleanup_old_runs(retention_days: int = 90, dry_run: bool = True) -> Dict[str, Any]`

**Description** : Supprime tous les runs > N jours (defaut 90).

#### `POST /api/run/delete_run`

**Signature** : `delete_run(run_id: str) -> Dict[str, Any]`

**Description** : Supprime un run de l'historique (DB seulement, pas les fichiers video).

#### `POST /api/run/get_auto_approved_summary`

**Signature** : `get_auto_approved_summary(run_id: str, threshold: Optional[int] = None, enabled: bool = False, quarantine_corrupted: bool = False) -> Dict[str, Any]`

**Description** : Resume des rows auto-approuvees selon le seuil de confiance (mode batch).

#### `POST /api/run/get_history_stats`

**Signature** : `get_history_stats(run_id: str) -> Dict[str, Any]`

**Description** : Detail complet d'un run pour l'inspecteur Historique.

#### `POST /api/run/list_pending_runs`

**Signature** : `list_pending_runs() -> Dict[str, Any]`

**Description** : Liste les runs PAUSED / SAVED / AWAITING_VALIDATION.

#### `POST /api/run/list_quarantine_bucket`

**Signature** : `list_quarantine_bucket(limit: int = 500) -> Dict[str, Any]`

**Description** : Inventaire du bucket `_review` pour le viewer UI.

#### `POST /api/run/mark_duplicate_winner`

**Signature** : `mark_duplicate_winner(run_id: str, group_key: str, winner_row_id: str, notes: Optional[str] = None) -> Dict[str, Any]`

**Description** : Phase 4 doublons : persiste la decision utilisateur "garder ce winner".

#### `POST /api/run/mark_duplicate_winners_bulk`

**Signature** : `mark_duplicate_winners_bulk(run_id: str, decisions: list = None) -> Dict[str, Any]`

**Description** : Issue #406 : persiste N decisions de doublons en UN aller-retour.

#### `POST /api/run/pause_run`

**Signature** : `pause_run(run_id: str) -> Dict[str, Any]`

**Description** : Suspend un run actif (signaling + DB PAUSED).

#### `POST /api/run/purge_quarantine_bucket`

**Signature** : `purge_quarantine_bucket(ttl_days: int = 30, dry_run: bool = True) -> Dict[str, Any]`

**Description** : Purge les fichiers du bucket `_review` > `ttl_days` jours (defaut 30).

#### `POST /api/run/purge_quarantine_bucket_all`

**Signature** : `purge_quarantine_bucket_all(dry_run: bool = True) -> Dict[str, Any]`

**Description** : Vider integralement le bucket `_review` (sauf `_duplicates_user_decided`).

#### `POST /api/run/rescan_row`

**Signature** : `rescan_row(run_id: str, row_id: str) -> Dict[str, Any]`

**Description** : Spec 06 §3.6 : relance probe + analyse perceptuelle pour 1 row.

#### `POST /api/run/rescan_rows_bulk`

**Signature** : `rescan_rows_bulk(row_ids: list, run_id: Optional[str] = None) -> Dict[str, Any]`

**Description** : Phase 4 spec 07 : version bulk de rescan_row (lance un JobRunner).

#### `POST /api/run/resume_run`

**Signature** : `resume_run(run_id: str) -> Dict[str, Any]`

**Description** : Reprend un run PAUSED ou SAVED (signaling + DB RUNNING).

#### `POST /api/run/save_for_later`

**Signature** : `save_for_later(run_id: str) -> Dict[str, Any]`

**Description** : Sauvegarde un run pour plus tard (signaling + DB SAVED).

#### `POST /api/run/undo_by_row_preview`

**Signature** : `undo_by_row_preview(run_id: str, batch_id: str = None) -> Dict[str, Any]`

**Description** : Preview de l'annulation par film : resume par row_id du batch cible (undo v5).

#### `POST /api/run/undo_last_apply_preview`

**Signature** : `undo_last_apply_preview(run_id: str) -> Dict[str, Any]`

**Description** : Preview (dry) de l'annulation du dernier batch apply reel (undo v1).


### 14. Autres endpoints — facade `runtime`

#### `POST /api/runtime/get_app_version`

**Signature** : `get_app_version() -> Dict[str, Any]`

**Description** : Retourne la version applicative + metadonnees build pour l'ecran About.

#### `POST /api/runtime/get_diagnostic`

**Signature** : `get_diagnostic() -> Dict[str, Any]`

**Description** : Retourne le diagnostic complet pour le bouton "Copier diagnostic".

#### `POST /api/runtime/get_doc`

**Signature** : `get_doc(file: str) -> Dict[str, Any]`

**Description** : Retourne le contenu markdown brut d'un document whiteliste.

#### `POST /api/runtime/get_event_ts`

**Signature** : `get_event_ts() -> Dict[str, Any]`

**Description** : Retourne le timestamp du dernier evenement significatif (scan/apply/settings).

#### `POST /api/runtime/get_probe`

**Signature** : `get_probe(run_id: str, row_id: str) -> Dict[str, Any]`

**Description** : Retourne la probe normalisee (video/audio/sous-titres) d'un film du run.

#### `POST /api/runtime/get_recent_logs`

**Signature** : `get_recent_logs(limit: int = 100) -> Dict[str, Any]`

**Description** : Lit les N dernieres lignes du log courant (cap a 1000).

#### `POST /api/runtime/get_tools_status`

**Signature** : `get_tools_status() -> Dict[str, Any]`

**Description** : Alias historique de `get_probe_tools_status` (compat v7.0/v7.1).

#### `POST /api/runtime/install_probe_tools`

**Signature** : `install_probe_tools(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Installe ffprobe + MediaInfo via winget (ou options fournies).

#### `POST /api/runtime/open_external_url`

**Signature** : `open_external_url(url: str = '') -> Dict[str, Any]`

**Description** : Fix audit 2026-05-24 — Ouvre une URL externe (http/https) dans le

#### `POST /api/runtime/purge_probe_cache`

**Signature** : `purge_probe_cache() -> Dict[str, Any]`

**Description** : Fix audit 2026-05-25 (v1.5.5) Vague K (FIX 5) : purge totale du cache probe.

#### `POST /api/runtime/recheck_probe_tools`

**Signature** : `recheck_probe_tools() -> Dict[str, Any]`

**Description** : Force une redetection des outils probe (utile apres installation manuelle).

#### `POST /api/runtime/reset_incremental_cache`

**Signature** : `reset_incremental_cache() -> Dict[str, Any]`

**Description** : Purge TOTALE du cache incremental (3 tables, tous roots confondus).

#### `POST /api/runtime/run_nas_benchmark`

**Signature** : `run_nas_benchmark(n_writes: int = 1000, n_reads: int = 10000) -> Dict[str, Any]`

**Description** : VO-A-NAS : declenche un benchmark perf SQLite sur le stockage cible.

#### `POST /api/runtime/search_docs`

**Signature** : `search_docs(query: str) -> Dict[str, Any]`

**Description** : Recherche full-text dans tous les documents whitelistes.

#### `POST /api/runtime/set_probe_tool_paths`

**Signature** : `set_probe_tool_paths(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Enregistre des chemins manuels vers ffprobe / MediaInfo (si hors PATH).

#### `POST /api/runtime/update_probe_tools`

**Signature** : `update_probe_tools(options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]`

**Description** : Met a jour ffprobe + MediaInfo via winget.


### 15. Autres endpoints — facade `settings`

#### `POST /api/settings/get_advanced_pragma_settings`

**Signature** : `get_advanced_pragma_settings() -> Dict[str, Any]`

**Description** : VO-A : retourne l'etat des PRAGMA SQLite avances (profil + locking_mode).

#### `POST /api/settings/get_confidence_thresholds`

**Signature** : `get_confidence_thresholds() -> Dict[str, Any]`

**Description** : Retourne les seuils HIGH/MEDIUM/LOW partages backend+frontend.

#### `POST /api/settings/get_naming_presets`

**Signature** : `get_naming_presets() -> Dict[str, Any]`

**Description** : Retourne la liste des presets de renommage disponibles.

#### `POST /api/settings/get_profiles`

**Signature** : `get_profiles() -> Dict[str, Any]`

**Description** : Liste tous les profils qualite (presets + custom).

#### `POST /api/settings/get_scan_max_workers`

**Signature** : `get_scan_max_workers() -> Dict[str, Any]`

**Description** : VO-B-CONFIG : retourne l'etat actuel du setting scan_max_workers.

#### `POST /api/settings/preview_naming_template`

**Signature** : `preview_naming_template(template: str = '', sample_row_id: str = '') -> Dict[str, Any]`

**Description** : Preview du resultat d'un template de renommage sur un film exemple.

#### `POST /api/settings/reset_database`

**Signature** : `reset_database(dry_run: bool = True) -> Dict[str, Any]`

**Description** : Wipe complet de la DB SQLite (films/runs/perceptual/scores) + backup.

#### `POST /api/settings/reset_settings`

**Signature** : `reset_settings(scope: str = 'all', dry_run: bool = True) -> Dict[str, Any]`

**Description** : Reinitialise les settings par categorie (ou tout).

#### `POST /api/settings/reveal_rest_token`

**Signature** : `reveal_rest_token() -> Dict[str, Any]`

**Description** : R7-10 : revele le Bearer REST en clair (LOCALHOST uniquement) pour les

#### `POST /api/settings/save_profile`

**Signature** : `save_profile(profile: Dict[str, Any]) -> Dict[str, Any]`

**Description** : Sauve un profil qualite custom (avec validation tiers + poids).

#### `POST /api/settings/set_active_profile`

**Signature** : `set_active_profile(profile_id: str) -> Dict[str, Any]`

**Description** : Active un profil qualite (preset ou custom).

#### `POST /api/settings/set_advanced_pragma_settings`

**Signature** : `set_advanced_pragma_settings(profile_name: str, locking_mode_exclusive: bool = False) -> Dict[str, Any]`

**Description** : VO-A : applique le profil PRAGMA et persiste dans settings.json.

#### `POST /api/settings/set_locale`

**Signature** : `set_locale(locale: str) -> Dict[str, Any]`

**Description** : Change la locale active (fr|en) et active immediatement le backend i18n.

#### `POST /api/settings/set_scan_max_workers`

**Signature** : `set_scan_max_workers(mode: str, value: Any = None) -> Dict[str, Any]`

**Description** : VO-B-CONFIG : persiste le setting scan_max_workers + retourne l'etat.


## Endpoints exclus du REST

Les methodes suivantes existent sur `CineSortApi` mais sont volontairement filtrees par `_EXCLUDED_METHODS` (`cinesort/infra/rest_server.py`) :

- `log` — Helper interne logging (frontend → backend).
- `log_api_exception` — Helper interne logging, pas un endpoint metier.
- `open_path` — Prend un chemin arbitraire — vector path-traversal en supervision distante.
- `progress` — Helper interne progress reporting (frontend → backend).
- `test_reset` — Remet l'application dans un etat propre (efface les runs en memoire) — #483. Reste appelable par les E2E via l'objet Python et le pont pywebview, qui ne passent pas par ce dispatcher.

## Exemples requete / reponse

Tous les exemples supposent que le serveur ecoute sur `localhost:8642`
et qu'un token Bearer valide est configure cote serveur.

### 1. Lancer un scan

```bash
curl -X POST http://localhost:8642/api/run/start_plan \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"settings": {"sources": ["D:/Films"], "destination": "D:/Library", "tmdb_key": "***"}}'
```

**Reponse** : `{"ok": true, "run_id": "20260504_120000_001"}`

### 2. Recuperer les settings actuels

```bash
curl -X POST http://localhost:8642/api/settings/get_settings \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Reponse** : `{"ok": true, "data": {"sources": [...], "destination": "...", ...}}`

### 3. Sauvegarder de nouveaux settings

```bash
curl -X POST http://localhost:8642/api/settings/save_settings \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"settings": {"destination": "D:/NewLibrary", "auto_apply_threshold": 90}}'
```

**Reponse** : `{"ok": true}`

### 4. Suivre la progression d'un run

```bash
curl -X POST http://localhost:8642/api/run/get_status \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id": "20260504_120000_001", "last_log_index": 0}'
```

**Reponse** : `{"ok": true, "status": "running", "progress": 42, "logs": [...]}`

### 5. Recuperer le plan complet d'un run

```bash
curl -X POST http://localhost:8642/api/run/get_plan \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id": "20260504_120000_001"}'
```

**Reponse** : `{"ok": true, "rows": [...], "stats": {...}}`

### 6. Appliquer les decisions de validation

```bash
curl -X POST http://localhost:8642/api/run/apply \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id": "20260504_120000_001", "decisions": {"row_id_1": {"approved": true}}, "dry_run": false, "quarantine_unapproved": true}'
```

**Reponse** : `{"ok": true, "applied_count": 42, "errors": []}`

### 7. Annuler la derniere operation apply

```bash
curl -X POST http://localhost:8642/api/run/undo_last_apply \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Reponse** : `{"ok": true, "undone_count": 42}`

### 8. Tester la cle TMDb

```bash
curl -X POST http://localhost:8642/api/integrations/test_tmdb_key \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"api_key": "abcd1234"}'
```

**Reponse** : `{"ok": true, "valid": true}`

### 9. Tester une connexion Jellyfin

```bash
curl -X POST http://localhost:8642/api/integrations/test_jellyfin_connection \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "http://jellyfin.local:8096", "api_key": "***"}'
```

**Reponse** : `{"ok": true, "version": "10.9.6"}`

### 10. Recuperer le dashboard d'un run

```bash
curl -X POST http://localhost:8642/api/run/get_dashboard \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"run_id": "latest"}'
```

**Reponse** : `{"ok": true, "kpis": {...}, "distribution": [...], "anomalies": [...]}`

---

_Genere par `scripts/gen_endpoints_doc.py` — ne pas editer manuellement._
_Pour regenerer : `.venv313/Scripts/python.exe scripts/gen_endpoints_doc.py`_
