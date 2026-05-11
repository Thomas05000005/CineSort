# Audit complet CineSort — 2 avril 2026

---

## Verdict global

| Catégorie | Note | Justification |
|-----------|------|---------------|
| Architecture & structure | **7 / 10** | Couches cinesort/ bien définies, mais modules legacy racine massifs et couplage fort UI→core |
| Qualité du code | **6.5 / 10** | Nommage cohérent et type hints, mais fonctions géantes, docstrings absentes et duplication significative |
| Fiabilité & gestion d'erreurs | **7 / 10** | Dry-run, undo et validation de chemins solides, mais try/except trop larges et cas extrêmes non testés |
| Interface utilisateur | **8 / 10** | HTML sémantique, ARIA complet, thème clair/sombre, wording FR de qualité professionnelle |
| Maintenabilité | **6.5 / 10** | Bonne couverture de tests (34 fichiers), mais classes géantes et duplication freinent l'évolution |
| Documentation | **7.5 / 10** | CHANGELOG, AGENTS.md, docs/ bien organisés, mais docstrings Python quasi absentes |

**Note globale : 7.1 / 10** — Application fonctionnelle et fiable avec une UI soignée, freinée par une dette technique concentrée dans les modules legacy et un manque de documentation inline.

---

## Flux fonctionnel reconstitué

```
                         CYCLE DE VIE D'UN FILM DANS CINESORT
                         =====================================

 [1] LANCEMENT                    app.py → pywebview → index.html → app.js
     │                            CineSortApi instancie JobRunner + SQLiteStore
     │                            Settings lus depuis settings.json
     ▼
 [2] CONFIGURATION                Vue "Réglages" : dossier racine, clé TMDb,
     │                            mode dry-run, prudence, probe tools
     ▼
 [3] ANALYSE (scan)               Vue "Analyse" → start_plan()
     │                            JobRunner lance thread → core_plan_support.plan_library()
     │
     ├─ Pour chaque dossier :
     │   ├─ [3a] Cache incrémental : folder_signature() vérifie si dossier changé
     │   │       → Si inchangé : réutilise rows du cache (hit)
     │   │       → Si changé : scan complet (miss)
     │   │
     │   ├─ [3b] Détection vidéos : iter_videos() filtre par extension + taille min
     │   │       → Détection single vs collection (detect_single_with_extras)
     │   │       → Filtrage TV (looks_tv_like → skip)
     │   │
     │   ├─ [3c] Extraction titre/année (3 sources, par priorité) :
     │   │       1. NFO (.nfo XML) → parse_movie_nfo() → nfo_consistent()
     │   │          Coverage ≥0.75 + séquence ≥0.78 requis
     │   │       2. Dossier/Filename → infer_name_year() + clean_title_guess()
     │   │          Années parenthésées (YYYY) prioritaires, regex bruit
     │   │       3. TMDb fallback → build_candidates_from_tmdb()
     │   │          Recherche API, cache JSON local, throttling
     │   │
     │   ├─ [3d] Scoring candidats : pick_best_candidate()
     │   │       Facteurs : similarité titre, delta année, crédibilité source,
     │   │       consensus multi-sources, popularité TMDb
     │   │
     │   ├─ [3e] Confiance : compute_confidence()
     │   │       High ≥80 | Med ≥60 | Low <60
     │   │
     │   └─ [3f] PlanRow créé avec : titre, année, source, confiance,
     │           warning_flags, dossier cible, type changement
     │
     ▼
 [4] VUE DU RUN                   Vue "Vue du run" : KPIs (score moyen,
     │                            films scorés, anomalies), historique
     ▼
 [5] CAS À REVOIR                 Vue "Cas à revoir" : preset "À relire (risque)"
     │                            Score de risque = f(confiance, source, warnings,
     │                            type changement, état qualité)
     │                            Tri automatique par risque décroissant
     ▼
 [6] DÉCISIONS                    Vue "Décisions" : table de validation
     │                            Filtres : confiance, source, recherche texte
     │                            Actions : approuver / rejeter / override titre-année
     │                            Persistance : decisions{} en mémoire + localStorage
     ▼
 [7] CONFLITS                     Vue "Conflits" : détection doublons
     │                            find_duplicate_targets() → groupes de collision
     │                            Types : blocage, à relire, déjà présent, dans sélection
     ▼
 [8] QUALITÉ (optionnel)          Vue "Qualité" : scoring CinemaLux
     │                            ProbeService (ffprobe/mediainfo) → NormalizedProbe
     │                            compute_quality_score() → score, tier, raisons
     │                            Presets : Remux strict, Équilibre, Light
     │                            Tiers : Premium ≥85, Bon 68-84, Moyen 54-67, Mauvais <54
     ▼
 [9] EXÉCUTION                    Vue "Exécution" → apply_changes()
     │
     ├─ [9a] Dry-run obligatoire : simulation sans aucun move/rename
     │
     ├─ [9b] Apply réel :
     │        core_apply_support.apply_rows()
     │        ├─ Migration collection legacy si nécessaire
     │        ├─ Boucle rows approuvées :
     │        │   ├─ ensure_inside_root() (sécurité chemin)
     │        │   ├─ windows_safe() (sanitisation noms)
     │        │   ├─ move_file_with_collision_policy()
     │        │   │   → conflit → _review/_conflicts
     │        │   │   → doublon identique → _duplicates_identical
     │        │   │   → orphelin → _review/_leftovers
     │        │   └─ record_apply_op() → journal SQLite
     │        ├─ Quarantine rows non approuvées → _review/
     │        └─ Cleanup dossiers vides/résiduels
     │
     ├─ [9c] Journal apply :
     │        apply_batches + apply_operations (SQLite)
     │        Chaque opération : type, src, dst, reversible, undo_status
     │
     └─ [9d] Résultat : ApplyResult avec compteurs + diagnostics
     ▼
[10] UNDO (si nécessaire)         undo_last_apply_preview() → preview
     │                            undo_last_apply() → rollback séquentiel
     │                            Jamais d'overwrite, conflits → _review/_undo_conflicts
     ▼
[11] HISTORIQUE                   Vue "Historique" : runs passés,
                                  exports JSON/CSV, journal d'exécution
```

---

## Findings confirmés

### Critiques

Aucun bug bloquant identifié. L'application est fonctionnelle et les garde-fous (dry-run, ensure_inside_root, undo) protègent contre les pertes de données.

---

### Importants

**F-01** `core.py` — God module monolithique
- **Fichier** : [core.py](core.py) (1192 lignes)
- **Description** : Mélange parsing NFO, scoring candidats, gestion fichiers, réexports de 6 modules. Centralise toute la logique métier dans un seul fichier.
- **Impact** : Difficulté à comprendre, modifier et tester individuellement. Toute modification risque des effets de bord.

**F-02** `quality_score.py:423-936` — Fonction géante compute_quality_score()
- **Fichier** : [cinesort/domain/quality_score.py:423](cinesort/domain/quality_score.py#L423) (513 lignes)
- **Description** : Une seule fonction gère validation, calculs vidéo/audio/extras, pondération, tiers, et génération de raisons narratives.
- **Impact** : Impossible à tester unitairement par section. Nesting 4-5 niveaux.

**F-03** `normalize.py:308-844` — Fonction géante normalize_probe()
- **Fichier** : [cinesort/infra/probe/normalize.py:308](cinesort/infra/probe/normalize.py#L308) (537 lignes)
- **Description** : Extraction + fusion + détermination qualité en un seul bloc.
- **Impact** : Difficile à maintenir si un nouveau backend probe est ajouté.

**F-04** `apply_support.py:283-672` — Fonction géante apply_changes()
- **Fichier** : [cinesort/ui/api/apply_support.py:283](cinesort/ui/api/apply_support.py#L283) (390 lignes)
- **Description** : Validation, exécution, reporting et cleanup dans une seule fonction.
- **Impact** : Logique UI mélangée avec orchestration apply. Testabilité faible.

**F-05** `core_plan_support.py:239-458` — Fonction monolithique plan_library()
- **Fichier** : [core_plan_support.py:239](core_plan_support.py#L239) (220 lignes + 3 fonctions imbriquées)
- **Description** : Gère scan, cache incrémental, collection/single, cancellation, logging et progress en un seul bloc.
- **Impact** : Les fonctions imbriquées rendent le flow difficile à suivre.

**F-06** `core_plan_support.py:461-838` — Duplication _plan_single / _plan_collection_item
- **Fichier** : [core_plan_support.py:461](core_plan_support.py#L461) et [core_plan_support.py:648](core_plan_support.py#L648)
- **Description** : ~170 lignes de logique identique (NFO matching, TMDb, candidats, confiance) copiées-collées entre les deux fonctions. Seules les différences single vs collection justifient la séparation.
- **Impact** : Toute correction doit être appliquée deux fois. Risque d'oubli élevé.

**F-07** `sqlite_store.py` — Classe monolithique SQLiteStore
- **Fichier** : [cinesort/infra/db/sqlite_store.py](cinesort/infra/db/sqlite_store.py) (~1350 lignes)
- **Description** : Une seule classe gère runs, erreurs, probe cache, quality, anomalies, apply journal et scan incrémental.
- **Impact** : Navigation difficile, 50+ méthodes, chaque modification touche un fichier critique.

**F-08** Couplage fort UI → modules legacy
- **Fichiers** : [cinesort/ui/api/cinesort_api.py:13-14](cinesort/ui/api/cinesort_api.py#L13-L14), [cinesort/ui/api/apply_support.py](cinesort/ui/api/apply_support.py), [cinesort/ui/api/settings_support.py](cinesort/ui/api/settings_support.py)
- **Description** : La couche UI importe directement `core` et `state` (modules racine legacy) au lieu de passer par la couche app.
- **Impact** : Empêche la migration progressive des modules legacy vers cinesort/. L'architecture en couches est partiellement court-circuitée.

**F-09** Duplication de code — fonctions de conversion
- **Fichiers** : [cinesort/domain/quality_score.py](cinesort/domain/quality_score.py) (lignes ~308-320), [cinesort/ui/api/settings_support.py](cinesort/ui/api/settings_support.py) (lignes 16-62), [cinesort/infra/probe/normalize.py](cinesort/infra/probe/normalize.py) (lignes 4-40)
- **Description** : `_to_int()`, `_to_float()`, `_to_bool()` implémentées 3 fois de manière quasi identique.
- **Impact** : Comportement potentiellement divergent entre modules. Maintenance x3.

**F-10** Duplication — `_connect()` SQLite
- **Fichiers** : [cinesort/infra/db/sqlite_store.py:70](cinesort/infra/db/sqlite_store.py#L70), [cinesort/infra/db/migration_manager.py:19](cinesort/infra/db/migration_manager.py#L19)
- **Description** : Même logique de connexion SQLite (WAL, FK, busy_timeout) écrite 2 fois.
- **Impact** : Si les pragmas changent, risque d'oubli.

**F-11** `core_cleanup.py` — Duplication _move_residual / _move_empty
- **Fichier** : [core_cleanup.py:238](core_cleanup.py#L238) et [core_cleanup.py:275](core_cleanup.py#L275)
- **Description** : Les deux fonctions suivent le même pattern (collect, filter skip_names, move) avec des différences minimes.
- **Impact** : Correction à appliquer en double.

**F-12** `core_duplicate_support.py` — Duplication can_merge_*
- **Fichier** : [core_duplicate_support.py:134](core_duplicate_support.py#L134) et [core_duplicate_support.py:168](core_duplicate_support.py#L168)
- **Description** : `can_merge_single_without_blocking()` et `can_merge_collection_item_without_blocking()` partagent la logique d'itération fichiers et détection collision.
- **Impact** : Même bug corrigé une seule fois sur deux.

---

### Mineurs

**F-13** Docstrings absentes dans les modules legacy
- **Fichiers** : `core.py`, `core_plan_support.py`, `core_apply_support.py`, `core_duplicate_support.py`, `core_cleanup.py`, `core_title_helpers.py`, `core_scan_helpers.py`
- **Description** : La quasi-totalité des fonctions publiques manquent de docstrings. Seuls quelques commentaires inline existent.
- **Impact** : Temps d'onboarding élevé pour comprendre le comportement attendu de chaque fonction.

**F-14** Magic numbers dans le scoring
- **Fichiers** : [core.py:639-660](core.py#L639), [core_title_helpers.py:241-242](core_title_helpers.py#L241)
- **Description** : Valeurs numériques codées en dur (0.65, 0.58, 0.42, 0.25, 0.55) sans constantes nommées.
- **Impact** : Impossible de comprendre la logique de scoring sans analyser le contexte complet.

**F-15** try/except trop larges
- **Fichiers** : [core.py:407-410](core.py#L407) (`parse_movie_nfo` → `except Exception: return None`), [core_plan_support.py:62](core_plan_support.py#L62), [core_cleanup.py:66-81](core_cleanup.py#L66)
- **Description** : Les catch `Exception` masquent les vraies erreurs (permissions, encodage, corruption).
- **Impact** : Diagnostic difficile en production. Un fichier NFO corrompu passe silencieusement.

**F-16** Imports circulaires contournés par import local
- **Fichier** : [core.py:11-39](core.py#L11) et multiples `import core as core_mod` dans core_plan_support, core_apply_support
- **Description** : Pattern `import core as core_mod` dans les fonctions pour éviter la circularité.
- **Impact** : Fragilité du graphe d'imports. Risque de régression si les réexports changent.

**F-17** Regex compilées dynamiquement
- **Fichier** : [cinesort/infra/probe/normalize.py](cinesort/infra/probe/normalize.py) (_to_int recompile regex à chaque appel)
- **Description** : Patterns regex non compilés à module level dans les hot paths.
- **Impact** : Micro-performance inutilement dégradée sur les boucles de tracks.

**F-18** Pas de tests pour erreurs extrêmes
- **Fichier** : `tests/` (34 fichiers)
- **Description** : Aucun test pour disque plein, permissions refusées, corruption SQLite, ou 2 instances concurrentes.
- **Impact** : Comportement inconnu en conditions dégradées.

**F-19** État global monolithique en JavaScript
- **Fichier** : [web/app.js](web/app.js) (~4400 lignes)
- **Description** : Un objet `state` unique concentre tout l'état UI. Pas de framework réactif.
- **Impact** : Acceptable pour la taille actuelle, mais risque d'incohérences d'état si l'UI grossit.

**F-20** Timeouts hardcodés
- **Fichiers** : [cinesort/infra/probe/tooling.py:101](cinesort/infra/probe/tooling.py#L101) (6s), [cinesort/infra/probe/tools_manager.py:165](cinesort/infra/probe/tools_manager.py#L165) (8s), [cinesort/infra/probe/tools_manager.py:415](cinesort/infra/probe/tools_manager.py#L415) (1800s)
- **Description** : Valeurs de timeout non centralisées ni configurables.
- **Impact** : Impossible d'ajuster sans modifier le code source.

**F-21** `_build_quality_presets_catalog()` recalculé à chaque appel
- **Fichier** : [cinesort/domain/quality_score.py](cinesort/domain/quality_score.py)
- **Description** : Les presets sont reconstruits via deep copy à chaque appel de `list_quality_presets()`.
- **Impact** : Performance mineure, mais facilement cacheable.

**F-22** JSON stocké en TEXT sans validation à la lecture
- **Fichier** : [cinesort/infra/db/sqlite_store.py](cinesort/infra/db/sqlite_store.py) (méthode `_decode_row_json`)
- **Description** : Si un champ JSON est corrompu, `_decode_row_json()` retourne silencieusement la valeur par défaut.
- **Impact** : Corruption de données passera inaperçue jusqu'à un symptôme visible.

---

### Cosmétiques

**F-23** Fichiers backup orphelins à la racine
- **Fichiers** : `_BACKUP_patch_after.txt`, `_BACKUP_patch_after_v7_1_3.txt`, `_BACKUP_patch_after_v7_1_4.txt`, `_BACKUP_patch_after_v7_1_5_ui.txt`, `_BACKUP_patch_before*.txt`, `_LOCAL_uncommitted_changes_backup.patch` (~600 Ko total)
- **Impact** : Bruit dans l'arborescence, aucune utilité en production.

**F-24** Double stockage des backups UI
- **Fichiers** : `.ui_backups/` (3 fichiers) ET `web/_backup_20260301_ui_refonte/` (3 fichiers .bak)
- **Impact** : Confusion sur la source de vérité des backups. Un seul emplacement suffit.

**F-25** Dossiers archivés dans le repo principal
- **Fichiers** : `archive_ui_next_20260308/`, `web_next_zero/`
- **Impact** : Prototypes archivés qui alourdissent l'arborescence.

**F-26** `data.db` vide (0 octets) à la racine
- **Fichier** : `data.db`
- **Impact** : Artefact de test non versionné (.gitignore OK via `??` status).

**F-27** `.tmp_test/` contient des artefacts de tests manuels
- **Fichier** : `.tmp_test/` (dossiers `cinesort_tmdb_*`, `manual_dir/`)
- **Impact** : Bruit, à nettoyer périodiquement.

**F-28** `save_settings_payload()` trop longue
- **Fichier** : [cinesort/ui/api/settings_support.py:284](cinesort/ui/api/settings_support.py#L284) (129 lignes)
- **Description** : Fonction de sauvegarde settings avec trop de validations imbriquées.
- **Impact** : Lisibilité réduite, mais fonctionnellement correcte.

---

## Captures d'écran de l'interface

Toutes les captures sont dans le dossier `audit_screenshots/` à la racine du projet.

| Fichier | Vue | Commentaire |
|---------|-----|-------------|
| `audit_screenshots/01_home.png` | Accueil (thème sombre) | Layout clair, hub de pilotage bien structuré avec "Prochaine étape", "Hub de pilotage" et "Run utile". Typographie Manrope + Newsreader élégante. Sidebar bien organisée en 3 groupes. |
| `audit_screenshots/02_analyse.png` | Analyse | Vue scan avec progression (dossiers traités, débit, temps restant). Interface minimaliste et fonctionnelle. Bouton "Démarrer l'analyse" bien mis en avant. |
| `audit_screenshots/03_vue_du_run.png` | Vue du run | Dashboard KPIs (score moyen 79.6/100, 4/4 films scorés, 1 anomalie). Lecture rapide efficace. |
| `audit_screenshots/04_cas_a_revoir.png` | Cas à revoir | File de relecture avec filtres (raisons, priorités) et recherche. Table vide avec message d'état clair. Bonne gestion de l'état vide. |
| `audit_screenshots/05_decisions.png` | Décisions | Table de validation avec contexte run + film actif. Filtres confiance/source. Bouton "Méthode rapide" bien visible. |
| `audit_screenshots/06_execution.png` | Exécution | Cadre prudent avec checklist pré-exécution. Messages de prudence bien rédigés en français. Excellent wording sécuritaire. |
| `audit_screenshots/07_qualite.png` | Qualité | Résumé run + profil actif (CinemaLux_v1). Structure en 2 sections "Lire le résumé" + "Comprendre l'état global". |
| `audit_screenshots/08_conflits.png` | Conflits | Gate de validation avec KPIs (blocage, à relire, déjà présent, dans sélection). Message "Aucun blocage" rassurant et bien affiché. |
| `audit_screenshots/09_historique.png` | Historique | Mémoire du produit : run actif, runs récents, alertes ouvertes. Exports JSON/CSV disponibles. |
| `audit_screenshots/10_reglages.png` | Réglages | Assistant premier lancement, configuration TMDb, outils d'analyse. Interface concise. |
| `audit_screenshots/11_home_theme_clair.png` | Accueil (thème clair) | Thème clair cohérent. Bons contrastes, lisibilité préservée. Transition propre sans artefacts. |

**Observations visuelles globales :**
- Typographie premium (Manrope variable + Newsreader variable), cohérence excellente
- Espacement cohérent (multiples de 4px), radii 16-20px
- Couleurs sémantiques bien utilisées (accent bleu, vert success, or warning, rouge bad)
- Sidebar fixe 308px avec groupes logiques clairs (Flux principal / Modules / Utilitaires)
- Thème sombre = défaut, thème clair = complet et cohérent
- Desktop-first assumé (mention "Optimisé bureau 1250px+" visible)
- Wording français professionnel, pédagogique et rassurant
- Focus states visibles (`focus-visible`), ARIA rôles corrects
- Aucun problème d'alignement ou d'overflow détecté

---

## Points forts

1. **Garde-fous de fiabilité** — Dry-run obligatoire, `ensure_inside_root()`, `windows_safe()`, journal undo, quarantine : la chaîne de sécurité est complète et bien pensée.

2. **Écriture atomique** — Le pattern `tmp + os.replace()` dans `state.py` et `tmdb_client.py` garantit qu'aucun fichier JSON n'est jamais partiellement écrit.

3. **Architecture cinesort/** — La structuration en domain/infra/app/ui est propre. Les modèles de domaine (RunStatus, NormalizedProbe, quality profiles) sont immutables (frozen dataclasses). Les violations d'architecture au sein du package sont nulles.

4. **Interface utilisateur** — HTML sémantique avec ARIA complet (tablist, tabpanel, modal, live regions). Deux thèmes cohérents. Wording français de qualité professionnelle qui guide l'utilisateur.

5. **Système de preview** — Mode preview complet avec 10 scénarios, mock API fidèle, toolbar de contrôle, capture Playwright et baseline visuelle versionnée. Rare et précieux pour une app desktop.

6. **Couverture de tests** — 34 fichiers de tests couvrant logique métier, API bridge, UI contracts, flows d'intégration, avec en option des tests live TMDb/probe et stress à 5000 dossiers.

7. **Client TMDb** — Cache local JSON threadsafe avec throttling sauvegarde, clé API protégée DPAPI, dégradation gracieuse.

8. **Scan incrémental** — Cache par dossier avec signatures (config + contenu), invalidation automatique, réutilisation de rows. Accélère significativement les re-scans.

9. **Heuristiques de titre robustes** — Chaîne NFO → folder/filename → TMDb avec scoring de confiance multi-facteurs, détection remaster, gestion des articles multilingues.

10. **CI local complète** — `check_project.bat` enchaîne compile check, ruff lint, ruff format, unittest et coverage en un seul appel.

---

## Plan de correction ordonné

### Phase 1 — Fiabilité (priorité maximale)

| Étape | Action | Fichiers | Complexité | Dépendances |
|-------|--------|----------|------------|-------------|
| 1.1 | Resserrer les try/except dans `parse_movie_nfo()` : attraper `ET.ParseError` et `FileNotFoundError` au lieu de `Exception` | `core.py:407-410` | Simple | Aucune |
| 1.2 | Resserrer les try/except dans `plan_row_from_jsonable()` et `_classify_cleanable_residual_dir()` | `core_plan_support.py:62`, `core_cleanup.py:66-81` | Simple | Aucune |
| 1.3 | Logger un warning dans `_decode_row_json()` quand le JSON est corrompu au lieu de retourner silencieusement le défaut | `cinesort/infra/db/sqlite_store.py` | Simple | Aucune |
| 1.4 | Ajouter tests pour erreurs extrêmes : permissions refusées, dossier supprimé pendant scan, fichier locked | `tests/` (nouveau fichier) | Moyen | Aucune |

### Phase 2 — Structure (dette technique principale)

| Étape | Action | Fichiers | Complexité | Dépendances |
|-------|--------|----------|------------|-------------|
| 2.1 | Extraire un module `cinesort/domain/utils.py` avec `_to_int()`, `_to_float()`, `_to_bool()` partagés | `quality_score.py`, `settings_support.py`, `normalize.py` | Simple | Aucune |
| 2.2 | Extraire une factory de connexion SQLite partagée (`cinesort/infra/db/connection.py`) | `sqlite_store.py`, `migration_manager.py` | Simple | Aucune |
| 2.3 | Factoriser `_plan_single()` / `_plan_collection_item()` en une fonction commune avec paramètre `mode` | `core_plan_support.py:461-838` | Moyen | Tests de régression sur plan |
| 2.4 | Factoriser `_move_residual_top_level_dirs()` / `_move_empty_top_level_dirs()` | `core_cleanup.py:238-329` | Simple | Tests cleanup |
| 2.5 | Factoriser `can_merge_single_without_blocking()` / `can_merge_collection_item_without_blocking()` | `core_duplicate_support.py:134-206` | Moyen | Tests duplicates |
| 2.6 | Scinder `compute_quality_score()` en 5 fonctions privées : `_score_video()`, `_score_audio()`, `_score_extras()`, `_apply_weights()`, `_determine_tier()` | `cinesort/domain/quality_score.py` | Complexe | Tests quality_score complets |
| 2.7 | Scinder `normalize_probe()` en `_extract_tracks()`, `_merge_probes()`, `_determine_quality()` | `cinesort/infra/probe/normalize.py` | Complexe | Tests probe |
| 2.8 | Scinder `apply_changes()` en `_validate_apply()`, `_execute_apply()`, `_cleanup_apply()`, `_summarize_apply()` | `cinesort/ui/api/apply_support.py` | Complexe | Tests critical_flow |
| 2.9 | Scinder `SQLiteStore` en sous-stores par domaine (RunStore, ProbeStore, QualityStore, ApplyStore, ScanStore) ou au minimum en mixins | `cinesort/infra/db/sqlite_store.py` | Complexe | Tous les tests utilisant SQLiteStore |

### Phase 3 — Compréhension (documentation et lisibilité)

| Étape | Action | Fichiers | Complexité | Dépendances |
|-------|--------|----------|------------|-------------|
| 3.1 | Nommer les magic numbers du scoring en constantes : `TITLE_SIM_WEIGHT`, `SEQ_WEIGHT`, etc. | `core.py:639-660`, `core_title_helpers.py:241` | Simple | Aucune |
| 3.2 | Ajouter docstrings aux 15 fonctions publiques les plus critiques (plan_library, apply_rows, compute_confidence, pick_best_candidate, etc.) | `core.py`, `core_plan_support.py`, `core_apply_support.py` | Moyen | Aucune |
| 3.3 | Compiler les regex de `normalize.py:_to_int()` à module level | `cinesort/infra/probe/normalize.py` | Simple | Aucune |
| 3.4 | Centraliser les timeouts probe en constantes dans `cinesort/infra/probe/constants.py` | `tooling.py`, `tools_manager.py` | Simple | Aucune |

### Phase 4 — Vitesse d'usage

| Étape | Action | Fichiers | Complexité | Dépendances |
|-------|--------|----------|------------|-------------|
| 4.1 | Cacher `_build_quality_presets_catalog()` en variable de module (calculé une seule fois) | `cinesort/domain/quality_score.py` | Simple | Aucune |

### Phase 5 — Hygiène du repo

| Étape | Action | Fichiers | Complexité | Dépendances |
|-------|--------|----------|------------|-------------|
| 5.1 | Supprimer les fichiers `_BACKUP_patch_*.txt` et `_LOCAL_uncommitted_changes_backup.patch` | Racine | Simple | Aucune |
| 5.2 | Unifier les backups UI dans un seul dossier (`.ui_backups/` ou `web/_backup*/`) et supprimer le doublon | `.ui_backups/`, `web/_backup_20260301_ui_refonte/` | Simple | Aucune |
| 5.3 | Déplacer `archive_ui_next_20260308/` et `web_next_zero/` vers `docs/internal/archive/` ou supprimer | Racine | Simple | Aucune |
| 5.4 | Nettoyer `.tmp_test/` | `.tmp_test/` | Simple | Aucune |
| 5.5 | Ajouter `data.db` au `.gitignore` si ce n'est pas déjà fait | `.gitignore` | Simple | Aucune |

---

## Plan de tests / non-régression

### Après chaque correction, vérifier :

**Phase 1 (Fiabilité)** :
- `python -m unittest discover -s tests -p "test_*.py" -v` — Tous les tests existants passent
- Vérifier manuellement qu'un NFO corrompu produit un warning loggé (pas un silence)
- Vérifier qu'un dossier sans permission ne crashe pas l'app

**Phase 2 (Structure)** :
- `check_project.bat` — Gate CI complète après chaque refactoring
- `python -m coverage run -m unittest discover -s tests -p "test_*.py" && python -m coverage report` — Couverture ne diminue pas
- Pour F-06 (plan_single/collection) : `python -m unittest tests.test_core_heuristics tests.test_backend_flow tests.test_critical_flow_integration -v`
- Pour F-07 (SQLiteStore) : `python -m unittest tests.test_v7_foundations tests.test_dashboard tests.test_incremental_scan tests.test_undo_apply -v`
- Pour F-02 (quality_score) : `python -m unittest tests.test_quality_score -v`
- Pour F-03 (normalize) : `python -m unittest tests.test_probe_auto -v`
- Pour F-04 (apply) : `python -m unittest tests.test_critical_flow_integration tests.test_undo_apply -v`

**Phase 3 (Compréhension)** :
- `python -m ruff check .` — Lint propre
- `python -m ruff format --check .` — Format propre
- Vérifier que les constantes nommées sont utilisées (grep ancien magic number → 0 résultat)

**Phase 4 (Vitesse)** :
- `python -m unittest tests.test_quality_score -v` — Pas de régression fonctionnelle
- Vérifier que `list_quality_presets()` ne recalcule pas (debug log ou breakpoint)

**Phase 5 (Hygiène)** :
- `git status` — Pas de fichier tracké supprimé par erreur
- `python scripts/package_zip.py --source` — Le ZIP source ne contient pas de backup/tmp

### Tests de régression visuels (après toute modification UI) :
```bash
python scripts/run_ui_preview.py --dev --no-browser &
python scripts/capture_ui_preview.py --dev --recommended
python scripts/visual_check_ui_preview.py --dev
```

### Tests live optionnels (avant release) :
```bash
CINESORT_LIVE_TMDB=1 python -m unittest discover -s tests/live -p "test_tmdb_live.py" -v
CINESORT_LIVE_PROBE=1 python -m unittest discover -s tests/live -p "test_probe_tools_live.py" -v
CINESORT_STRESS=1 python -m unittest tests.stress.large_volume_flow -v
```
