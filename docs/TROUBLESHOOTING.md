# CineSort — Dépannage

> Guide de résolution de problèmes courants. Pour le manuel utilisateur, voir [MANUAL.md](MANUAL.md).
> Pour l'API REST, voir [api/ENDPOINTS.md](api/ENDPOINTS.md).

Ce document recense les symptômes les plus fréquents rencontrés en production, leur cause probable
et la procédure de résolution. Chaque section référence les chemins de logs et modules concernés.

## Sommaire

1. [Démarrage de l'app](#1-démarrage-de-lapp)
2. [Probe vidéo (ffprobe / mediainfo)](#2-probe-vidéo-ffprobe--mediainfo)
3. [APIs externes (TMDb, Jellyfin, Plex, Radarr)](#3-apis-externes)
4. [Performance et scan lent](#4-performance-et-scan-lent)
5. [Apply / Undo / Conflits](#5-apply--undo--conflits)
6. [Réseau & Dashboard distant](#6-réseau--dashboard-distant)
7. [Notifications desktop](#7-notifications-desktop)
8. [Base de données SQLite](#8-base-de-données-sqlite)

### Emplacements clés

| Fichier | Chemin Windows |
|---|---|
| Log principal (rotation 50 MB × 5) | `%LOCALAPPDATA%\CineSort\logs\cinesort.log` |
| Crash au démarrage | `%LOCALAPPDATA%\CineSort\startup_crash.txt` |
| Settings utilisateur | `%LOCALAPPDATA%\CineSort\settings.json` |
| Backups DB automatiques | `%LOCALAPPDATA%\CineSort\backups\` |
| State runs (plans, reports) | `%LOCALAPPDATA%\CineSort\runs\<run_id>\` |
| Cache TMDb | `%LOCALAPPDATA%\CineSort\tmdb_cache\` |

> Astuce : depuis l'app, **Aide → Ouvrir le dossier des logs** ouvre directement le bon dossier.

---

## 1. Démarrage de l'app

### Symptôme : « CineSort - Erreur de démarrage » au lancement

- **Vérifier** : `%LOCALAPPDATA%\CineSort\startup_crash.txt` (généré par `app.py:_write_crash_dump()`).
- **Causes courantes** :
  - DLL Windows manquante (Visual C++ Redistributable, WebView2).
  - Antivirus en quarantaine sur `CineSort.exe` (faux positif PyInstaller onefile).
  - `ffprobe.exe` introuvable mais critique pour la suite.
- **Solutions** :
  - Whitelister `CineSort.exe` dans l'antivirus puis re-télécharger depuis la GitHub Release officielle.
  - Installer Microsoft Edge WebView2 Runtime (requis par pywebview).
  - Lancer `CineSort.exe --dev` une fois pour voir la stacktrace en console.

### Symptôme : Splash screen reste affiché 8 s ou plus

- **Causes** :
  - Migration DB en cours sur une grosse base (centaines de runs, milliers de quality_reports).
  - Backup DB automatique avant migration (V2-G) sur un disque lent.
  - Reconciliation des `pending_moves` au boot (apply interrompu lors d'une session précédente).
- **Logs à consulter** : `cinesort.log` au niveau `INFO`, chercher `migration_manager` ou
  `reconcile_at_boot`.
- **Solution** : laisser terminer (un message « Vous pouvez fermer cette fenêtre » apparaît si la
  migration dure plus de 60 s). Si l'app reste bloquée 5 min, voir [section 8](#8-base-de-données-sqlite).

### Symptôme : `.exe` ne lance rien (rien au double-clic)

- **Causes** :
  - `.exe` corrompu (interruption du téléchargement).
  - Faux positif AV en quarantaine silencieuse.
  - Manque de privilèges sur `%LOCALAPPDATA%`.
- **Solutions** :
  - Re-télécharger depuis la source officielle, vérifier le hash SHA256 si fourni.
  - Lancer en mode console : `cmd.exe` → `cd %USERPROFILE%\Downloads` → `CineSort.exe` (les
    erreurs Python remontent dans la console).
  - Tester un lancement « Exécuter en tant qu'administrateur » (juste pour diagnostic).

---

## 2. Probe vidéo (ffprobe / mediainfo)

### Symptôme : « Outils probe absents — analyse limitée »

- **Cause** : aucun de `ffprobe.exe` / `mediainfo.exe` détecté dans le PATH ni dans `tools/`.
- **Logs** : `cinesort.log` → `tools_manager` ou `probe_support: ffmpeg introuvable`.
- **Solutions** :
  - **Réglages → Outils vidéo → Installer/Détecter** lance `auto_install.py` qui télécharge
    une build statique ffmpeg dans `%LOCALAPPDATA%\CineSort\tools\`.
  - Manuel : poser `ffprobe.exe` dans le dossier `tools/` à côté de `CineSort.exe`.
  - Sans probe, le scoring qualité reste à 0 mais le scan / rename fonctionne.

### Symptôme : Probe FAILED sur certains films

- **Causes** :
  - Fichier corrompu (header invalide, file integrity check `magic bytes`).
  - Container exotique non supporté (`.evo`, `.mpls`, `.3gp`).
  - Timeout dépassé (`PROBE_TIMEOUT_S` dans `cinesort/infra/probe/constants.py`).
- **Logs** : `cinesort.log` → `ProbeService.probe failed: ... timeout=...`.
- **Solutions** :
  - L'app injecte le warning `integrity_probe_failed` visible dans la validation. Vérifier le
    fichier dans VLC : si VLC ne lit pas non plus, le fichier est corrompu.
  - Augmenter le timeout via `Réglages → Analyse vidéo → Timeout probe` (limite raisonnable : 60 s).
  - Pour un container exotique : convertir en MKV avec `ffmpeg -i input.evo -c copy output.mkv`.

### Symptôme : Quality reports absents pour de nombreux films

- **Causes** :
  - Probe désactivée ou outils absents (cf. supra).
  - Cache `probe_cache` corrompu.
  - Interruption du scan avant la phase scoring.
- **Solutions** :
  - **Réglages → Analyse vidéo → Vider le cache** (bouton « Réinitialiser le cache probe »).
  - Relancer un scan complet (les hits incrémental peuvent ignorer les films manquants → cocher
    « Forcer rescan » sur la vue Processing).

---

## 3. APIs externes

### TMDb

#### Symptôme : « Clé API TMDb invalide »
- **Cause** : clé vide, expirée ou tapée avec espaces.
- **Logs** : `tmdb_client.py` → `TMDb 401 Unauthorized` ou `TMDb 404 not found`.
- **Solution** : régénérer une clé sur <https://www.themoviedb.org/settings/api>, la coller dans
  **Réglages → TMDb → Clé API**, cliquer **Tester la connexion**.

#### Symptôme : Films inconnus / candidats vides
- **Causes** : titre trop déformé (release scene), film amateur absent de TMDb, accents perdus.
- **Solutions** :
  - L'app retire l'édition (`-EXTENDED-DC.mkv` → `Film`) avant la recherche TMDb (cf.
    `edition_helpers.py`).
  - Renseigner un `.nfo` Kodi avec `<tmdbid>` à côté du film : la recherche est court-circuitée.
  - Fallback : pose IMDb ID dans le `.nfo` → `find_by_imdb_id()` interroge l'endpoint `/find`.

#### Symptôme : Rate limit TMDb (429)
- **Cause** : 40 requêtes / 10 s par IP côté TMDb.
- **Logs** : `TMDb HTTP 429`.
- **Solution** : `make_session_with_retry` (urllib3) gère le backoff automatique. Si le scan
  reste bloqué, vérifier qu'aucune autre app TMDb ne tourne en parallèle sur la même IP.

### Jellyfin

#### Symptôme : Connexion refusée
- **Causes** : URL incorrecte (oublier `http://` ou `:8096`), serveur arrêté, clé API invalide.
- **Logs** : `jellyfin_client.py` → `Jellyfin connection failed: ...`.
- **Solutions** :
  - Tester l'URL dans le navigateur : `http://serveur:8096/web/`.
  - Régénérer une clé API : Tableau de bord Jellyfin → API Keys → Nouvelle clé.
  - **Réglages → Jellyfin → Tester la connexion** affiche le code HTTP exact.

#### Symptôme : Sync watched fails / restore incomplet
- **Cause** : Jellyfin n'a pas re-indexé assez vite après le rename (latence file system).
- **Logs** : `jellyfin_sync.py` → `restore: still waiting for re-index, retry n/5`.
- **Solution** : v7.6.0 retry x5 avec backoff exponentiel (jusqu'à 135 s total). Si le restore
  échoue tout de même, le snapshot reste dans `<run_dir>/jellyfin_watched_snapshot.json` et peut
  être rejoué.

#### Symptôme : Library mismatch (films présents dans CineSort mais pas dans Jellyfin)
- **Solution** : utiliser **Jellyfin → Vérifier la cohérence** (endpoint `get_jellyfin_sync_report`).
  Le rapport liste `missing_in_jellyfin` (à ajouter manuellement) et `ghost_in_jellyfin` (entrées
  Jellyfin sans fichier source).

### Plex

#### Symptôme : « X-Plex-Token invalide » / 401
- **Cause** : token expiré ou pas le bon (token de compte vs token de serveur).
- **Solution** : récupérer le token via [plex.tv account → XML view](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)
  et le coller dans **Réglages → Plex → Token**.

#### Symptôme : « Sections films non trouvées »
- **Cause** : la section Plex n'est pas de type `movie`.
- **Logs** : `plex_client.py` → `get_libraries("movie")` retourne `[]`.
- **Solution** : vérifier le type de la bibliothèque Plex (Films vs Séries vs Photos).

### Radarr

#### Symptôme : « Radarr API v3 incompatible »
- **Cause** : Radarr v2 (déprécié) ou clé API `X-Api-Key` vide.
- **Logs** : `radarr_client.py` → `Radarr 404 /api/v3/system/status`.
- **Solution** : mettre à jour Radarr en v4+, copier la clé depuis Settings → General → Security.

#### Symptôme : Movie ID mismatch
- **Cause** : Radarr ne connaît pas le film (pas dans sa bibliothèque ou tmdb_id différent).
- **Solution** : `build_radarr_report()` matche en 3 niveaux (tmdb_id → chemin → titre+année).
  Si tous échouent, ajouter le film manuellement dans Radarr ou vérifier le `tmdb_id` dans le
  `.nfo`.

---

## 4. Performance et scan lent

### Symptôme : Scan dure 10 h ou plus sur grosse bibliothèque

- **Causes** :
  - Bibliothèque > 5000 films sur HDD lent (read random ~50 MB/s).
  - Analyse perceptuelle activée pour tous les films (très coûteuse, 2-5 min/film).
  - Pas de cache incremental (premier scan, nouveau dossier).
- **Logs** : `cinesort.log` → `plan_support: scanned X files in Y s`.
- **Solutions** :
  - **L'analyse perceptuelle est désactivée par défaut.** Activable à la demande sur un film
    via l'inspecteur. Pour la batcher : **Qualité → Analyser perceptuel (sélection)**.
  - Le cache incremental v2 (couche dossier + couche vidéo) accélère les scans suivants : un
    scan complet sans modif = quasi 0 s.
  - Parallélisation perceptuelle prévue v7.7.0 (V5-02 multiprocessing.Pool, V5-04 probe
    ThreadPoolExecutor).

### Symptôme : UI freeze pendant le rendu library

- **Cause** : > 2000 films rendus en une seule passe (no virtualization).
- **Solution** : virtualisation tabulaire (windowing 30-50 rows) prévue v7.7.0 (V5-01). En
  attendant, utiliser les filtres tier / résolution pour réduire la liste affichée.

### Symptôme : Memory growth visible sur sessions 8 h ou plus

- **Cause** : event listener leaks (1-3 MB/8 h, accepté).
- **Solution** : redémarrer l'app. Les memory leaks majeurs ont été corrigés v7.7.0 V2-05
  (notification-center, journal-polling, router).

---

## 5. Apply / Undo / Conflits

### Symptôme : Apply échoue à mi-chemin (coupure courant, crash)

- **Cause** : `shutil.move` interrompu, journal SQLite incomplet.
- **Mécanisme** : pattern WAL `apply_pending_moves` (migration 019). Chaque move est écrit dans
  le journal AVANT exécution, et supprimé APRÈS confirmation.
- **Solution** : au prochain boot, `reconcile_at_boot()` (`move_reconciliation.py`) inspecte les
  pending_moves et leur attribue un verdict : `completed` / `rolled_back` / `duplicated` / `lost`.
  Une notification UI est levée s'il reste des conflits à trancher.
- **Logs** : `cinesort.log` → `move_reconciliation: verdict=...`.

### Symptôme : Undo ne retrouve pas le fichier déplacé

- **Cause** : l'utilisateur a déplacé / renommé le fichier hors de l'app entre apply et undo.
- **Solution** : les conflits sont placés dans `<root>\_review\_undo_conflicts\` avec le détail
  (chemin attendu vs réalité). Restaurer manuellement depuis cette zone.
- **Logs** : `apply_support.py` → `_execute_undo_ops: conflict for row_id=...`.

### Symptôme : Films dupliqués créés par apply

- **Cause** : 2 films distincts ciblent le même dossier de destination (collision).
- **Mécanisme** : `_check_file_collisions` (`duplicate_support.py`) détecte ces cas avant apply.
  Le dashboard affiche un encart « Conflits détectés » dans la phase Validation.
- **Solution** : utiliser **Comparer la qualité** (vue côte-à-côte avec 7 critères + score
  perceptuel V2 + sous-titres FR), garder le meilleur, déplacer l'autre vers
  `<root>\_duplicates_identical\` ou `_review/_conflicts/`.

### Symptôme : `_Vide`, `_Collection`, `_review` non créés

- **Cause** : permissions insuffisantes sur le dossier racine (NAS read-only, partition full).
- **Pré-check** : `disk_space_check.py` refuse l'apply si l'espace libre < `max(somme*1.10, 100MB)`.
- **Solution** : vérifier les ACL Windows (`Sécurité → Modifier`) ou monter le NAS en R/W.

---

## 6. Réseau & Dashboard distant

### Symptôme : Dashboard distant ne charge pas

- **Causes possibles** :
  - Token absent dans l'URL ou expiré (le dashboard utilise sessionStorage par défaut).
  - Port `8642` bloqué par le firewall Windows.
  - Token < 32 caractères + bind `0.0.0.0` → rétrogradation automatique vers `127.0.0.1` (sécurité).
- **Logs** : `rest_server.py` → `LAN bind demoted to 127.0.0.1: token too short`.
- **Solutions** :
  - Générer un token long (>= 32 caractères) dans **Réglages → API REST → Token**.
  - Ouvrir le port : `Pare-feu Windows → Règles entrantes → Nouvelle règle → Port TCP 8642`.
  - Récupérer l'URL avec QR code dans **Réglages → API REST → Lien dashboard**.

### Symptôme : 401 répétés sur toutes les requêtes API

- **Causes** : token incorrect, token modifié sans re-login dans le dashboard.
- **Logs** : `cinesort.log` → `REST 401 invalid token from <ip>`.
- **Solutions** :
  - Re-saisir le token dans le dashboard (Login).
  - Si suspect d'attaque : changer le token dans Réglages, redémarrer le serveur REST à chaud
    (bouton « Redémarrer API REST »).

### Symptôme : 429 Too Many Requests

- **Cause** : `_RateLimiter` — 5 échecs 401 par IP en 60 s déclenchent un blocage 60 s.
- **Logs** : `rest_server.py` → `REST 429 rate limit <ip>`.
- **Solution** : attendre 60 s, vérifier le token, ne pas tester en boucle. Le rate-limiter est
  per-IP : un autre poste sur le même réseau n'est pas affecté.

### Symptôme : HTTPS ne fonctionne pas

- **Cause** : certificats `cert.pem` / `key.pem` introuvables → fallback HTTP automatique.
- **Logs** : `rest_server.py` → `HTTPS disabled: cert not found, fallback HTTP`.
- **Solution** : générer un cert auto-signé :
  ```
  openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=CineSort"
  ```
  puis renseigner les chemins absolus dans **Réglages → API REST → HTTPS**.

---

## 7. Notifications desktop

### Symptôme : Aucun toast Windows à la fin du scan / apply

- **Vérifications** :
  - **Réglages → Notifications → Activer les notifications** est coché.
  - Le toggle par type (`scan_done`, `apply_done`, `undo_done`, `error`) est activé pour
    l'évènement attendu.
  - **Windows → Paramètres → Système → Notifications** : CineSort n'est pas en mode silencieux
    (Focus assist actif sans whitelist).
- **Comportement attendu** : si la fenêtre CineSort a le focus (`document.hasFocus() === true`),
  **aucun toast** n'est émis (intentionnel, évite le bruit).
- **Logs** : `notify_service.py` → `notify queued: scan_done` puis `notify dispatched`.
- **Diagnostic** : si le log montre `notify queued` mais pas de toast, le drain_timer du main
  thread est peut-être bloqué (rare). Redémarrer l'app.

### Symptôme : Toasts dupliqués dans le notification center web

- **Cause** : `NotifyService.set_center_hook()` mirror inconditionnel + `emit_from_insights()`
  sans dédup.
- **Solution** : fixé v7.6.0 — dédup par `(code, source)` dans `NotificationStore`. Si le bug
  ressurgit, vider le store via **API → clear_notifications**.

---

## 8. Base de données SQLite

### Symptôme : « DB integrity check FAILED » au boot

- **Cause** : corruption SQLite (coupure courant pendant écriture WAL, secteur disque défectueux).
- **Mécanisme** : `PRAGMA integrity_check` exécuté au boot (V2-G). Si KO → tentative de restore
  automatique depuis le backup le plus récent.
- **Logs** : `sqlite_store.py` → `integrity check FAILED, attempting auto-restore from <path>`.
- **Solution** :
  - Vérifier `%LOCALAPPDATA%\CineSort\backups\` (5 backups gardés en rotation).
  - L'app restaure automatiquement le backup le plus récent. Les runs/scans postérieurs au
    backup sont perdus, mais les fichiers vidéo physiques ne sont pas touchés.
  - En dernier recours : supprimer `data.db` (et `data.db-wal`, `data.db-shm`) → l'app crée une
    base vierge au prochain boot. Settings sont préservés (fichier `settings.json` séparé).

### Symptôme : Migration échoue

- **Cause** : ALTER TABLE sur une colonne déjà présente, incompatibilité de schéma.
- **Mécanisme** : SAVEPOINT avec garde idempotence (catch « duplicate column » / « already
  exists »). Backup auto déclenché AVANT chaque série de migrations.
- **Logs** : `migration_manager` → `migration NNN failed: ...` et `restoring from backup`.
- **Solution** : copier `data.db` ailleurs pour analyse, restaurer le backup pré-migration
  depuis `backups/`, ouvrir une issue GitHub avec les logs.

### Symptôme : « database is locked »

- **Cause** : autre processus tient une transaction longue (rare avec WAL + busy_timeout=5000ms).
- **Solution** : fermer toute autre instance CineSort. Si persistant, redémarrer Windows pour
  libérer les handles.

---

## Pour aller plus loin

- **Manuel utilisateur** : [MANUAL.md](MANUAL.md) — tutoriel pas-à-pas + glossaire + FAQ.
- **API REST** : [api/ENDPOINTS.md](api/ENDPOINTS.md) — référence des 98 endpoints.
- **Architecture** : [architecture.mmd](architecture.mmd) — diagrammes Mermaid des modules.
- **Signaler un bug** : Aide → **Exporter le diagnostic** (zip avec logs scrubbés sans clés API),
  joindre à une issue GitHub.
