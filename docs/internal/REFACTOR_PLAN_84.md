# Plan refactor #84 — God class CineSortApi → 5 façades par bounded context

**Version** : 1.0 (préparation, en attente validation utilisateur)
**Auteur** : Claude Code (session 2026-05-14)
**Statut** : ⏳ En attente validation avant exécution

---

## 1. Contexte et motivation

### État actuel

- `cinesort/ui/api/cinesort_api.py` : **2203 lignes, 168 méthodes** (104 publiques + 61 privées + 3 décorateurs)
- Constructeur `__init__` : 23 attributs d'instance (4 locks, 2 sets, 3 caches, 3 refs lazy, 1 NotifyService, etc.)
- 50+ imports en tête
- **Méthodes publiques = 3-liners de délégation** vers `*_support` modules (15 modules délégués)
- 54 méthodes "Misc" non clairement délégables

### Exposition

L'API est **doublement exposée** :
1. **pywebview** (frontend desktop natif) : `window.pywebview.api.{method}(...)`
2. **REST API** (dashboard distant) : `POST /api/{method}` via introspection `inspect.dir(api)` + filtre callable + 4 exclusions

### Pourquoi refactor

| Bénéfice | Détail |
|----------|--------|
| **Navigabilité** | Trouver une méthode dans 168 = aiguille dans botte de foin |
| **Testabilité** | Façade isolable, FakeStore injectable (cf. pattern Repository #85) |
| **Cognitive load** | 5 façades de 30-40 méthodes < 1 classe de 168 |
| **Évolution** | Nouvelles features s'ajoutent dans la bonne façade, pas dans le god class |

### Sources de recherche

Best practices industry consultées (recherche web 2026-05-14) :

- **Facade Pattern** : créer un intermédiaire qui route vers les nouvelles classes
- **Strangler Fig Pattern** (Martin Fowler 2004) : wrapper old code, remplacer progressivement
- **PEP 702 — `@warnings.deprecated()`** : décorateur standard pour deprecation Python
- **PEP 562 — Module `__getattr__`** : interception dynamique d'accès attribut

Sources :
- [Refactoring God Class in Python (Better Programming)](https://betterprogramming.pub/refactoring-the-god-class-in-python-5c13942d0e75)
- [Strangler Fig Pattern (Shopify Engineering)](https://shopify.engineering/refactoring-legacy-code-strangler-fig-pattern)
- [Facade Pattern (Refactoring Guru)](https://refactoring.guru/design-patterns/facade/python/example)
- [PEP 702 (deprecation)](https://peps.python.org/pep-0702/)

---

## 2. Architecture cible

### Découpage 5 façades par bounded context

```
cinesort/ui/api/
├── cinesort_api.py          (~200 lignes, juste adapteur pywebview)
├── facades/
│   ├── __init__.py
│   ├── _base.py             (base class commune)
│   ├── run_facade.py        (~7 méthodes : start/cancel/status/plan)
│   ├── settings_facade.py   (~3 méthodes : get/save/locale)
│   ├── quality_facade.py    (~20 méthodes : profile/report/perceptual)
│   ├── integrations_facade.py (~11 méthodes : Jellyfin/Plex/Radarr/TMDb)
│   └── library_facade.py    (~5 méthodes : library/film/history/export)
└── _support modules         (inchangés, restent les helpers métier)
```

### Méthodes par façade (catégorisation détaillée)

#### RunFacade (7 méthodes)
- `start_plan`, `get_status`, `get_plan`, `export_run_report`
- `cancel_run`, `build_apply_preview`, `list_apply_history`

#### SettingsFacade (3 méthodes + apparentés)
- `get_settings`, `save_settings`, `set_locale`
- Possiblement aussi : `reset_all_user_data`, `get_user_data_size`, `restart_api_server`

#### QualityFacade (20 méthodes)
- **Profile** (8) : `get_quality_profile`, `get_quality_presets`, `apply_quality_preset`, `simulate_quality_preset`, `save_quality_profile`, `reset_quality_profile`, `export_quality_profile`, `import_quality_profile`
- **Report** (4) : `get_quality_report`, `analyze_quality_batch`, `save_custom_quality_preset`, `get_custom_rules_templates`
- **Perceptual** (4) : `get_perceptual_report`, `get_perceptual_details`, `analyze_perceptual_batch`, `compare_perceptual`
- **Custom rules** (4) : `get_custom_rules_catalog`, `validate_custom_rules`, `get_calibration_report`, `submit_score_feedback`

#### IntegrationsFacade (11 méthodes)
- **Jellyfin** (3) : `test_jellyfin_connection`, `get_jellyfin_libraries`, `get_jellyfin_sync_report`
- **Plex** (3) : `test_plex_connection`, `get_plex_libraries`, `get_plex_sync_report`
- **Radarr** (3) : `test_radarr_connection`, `get_radarr_status`, `request_radarr_upgrade`
- **TMDb** (2) : `test_tmdb_key`, `get_tmdb_posters`

#### LibraryFacade (5 méthodes)
- `get_library_filtered`, `get_film_full`, `get_film_history`, `list_films_with_history`, `export_full_library`

#### Misc (54 méthodes, restent sur CineSortApi)
Trop hétérogènes pour mériter une façade dédiée :
- **Validation & Apply** (12) : `load_validation`, `save_validation`, `check_duplicates`, `apply`, `undo_*`, etc.
- **Probe Tools** (7) : `get_probe_tools_status`, `install_probe_tools`, etc.
- **Demo Mode** (3) : `start/stop/is_demo_mode_active`
- **Dashboard** (5) : `get_dashboard`, `get_global_stats`, etc.
- **Notifications** (5) : `get_notifications`, `dismiss_notification`, etc.
- **Server & Updates** (8) : `get_server_info`, `check_for_updates`, etc.
- **Misc** (14) : `log_api_exception`, `reset_incremental_cache`, etc.

Décision : ces 54 méthodes restent sur `CineSortApi` directement. Une 6ème façade "AdminFacade" est possible mais nécessite analyse séparée — phase ultérieure.

---

## 3. Stratégie de migration (Strangler Fig)

### Principe

Au lieu de refactor d'un coup (risque élevé), on applique le Strangler Fig Pattern :

1. **Créer la façade en parallèle** de l'ancienne méthode
2. **Ancienne méthode reste fonctionnelle** (backward-compat 100%)
3. **Optionnellement : marquer ancienne méthode `@deprecated`** pour tracker callers
4. **Migrer call sites un par un** vers la façade
5. **Quand 0 caller** : supprimer l'ancienne méthode

### Phases proposées (10 PRs séquentielles)

| Phase | Scope | Effort | Risque |
|-------|-------|--------|--------|
| **PR 1** | Squelette : 5 façades vides + 1 méthode pilote chacune + tests | 6-8h | Faible |
| **PR 2** | Migrer toutes les méthodes vers RunFacade | 1 jour | Faible |
| **PR 3** | Migrer toutes les méthodes vers SettingsFacade | 1 jour | Faible |
| **PR 4** | Migrer toutes les méthodes vers QualityFacade | 1 jour | Moyen (20 méthodes) |
| **PR 5** | Migrer toutes les méthodes vers IntegrationsFacade | 1 jour | Moyen |
| **PR 6** | Migrer toutes les méthodes vers LibraryFacade | 1 jour | Faible |
| **PR 7** | Documentation + tests d'intégration | 1 jour | Faible |
| **PR 8** | Migration frontend JS vers `api.{facade}.X()` | 1-2 jours | **Élevé** |
| **PR 9** | Migration REST API dispatch | 1 jour | **Élevé** |
| **PR 10** | Suppression des anciennes méthodes directes + nettoyage | 0.5 jour | Moyen |

**Total** : 8-10 jours étalés sur ~5-8 sessions de travail (1-2 PRs par session).

### Backward-compat 100% jusqu'à PR 10

Pendant les phases 1-7 :
- `api.start_plan(...)` continue de marcher (méthode directe)
- `api.run.start_plan(...)` marche aussi (façade)
- Frontend JS et REST inchangés

Phase 8-9 : migration JS et REST (le moment critique).
Phase 10 : nettoyage final (seulement quand 0 caller de l'ancienne forme).

---

## 4. Stratégies de sécurité

### 4.1 Adapter pattern (duplication backward-compat)

Chaque méthode façade est créée **EN PLUS** de la méthode directe (pas à la place) :

```python
class CineSortApi:
    def start_plan(self, payload):
        """Ancienne forme (backward-compat)."""
        return run_flow_support.start_plan(self, payload)
    
    # ...

class RunFacade:
    def start_plan(self, payload):
        """Nouvelle forme via façade."""
        return run_flow_support.start_plan(self._api, payload)
```

Les **deux chemins existent en parallèle**. Aucun call site n'est cassé.

### 4.2 Decorator `@deprecated` (PEP 702)

Optionnel : marquer les anciennes méthodes pour tracker les callers :

```python
import warnings

def deprecated(replacement):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            warnings.warn(
                f"{fn.__name__} is deprecated, use {replacement} instead",
                DeprecationWarning,
                stacklevel=2,
            )
            return fn(*args, **kwargs)
        return wrapper
    return decorator

class CineSortApi:
    @deprecated("api.run.start_plan")
    def start_plan(self, payload):
        return run_flow_support.start_plan(self, payload)
```

**Avantage** : on voit dans les logs quels callers utilisent encore l'ancienne forme.
**Inconvénient** : spam dans les logs si non géré.
**Décision** : activer SEULEMENT pendant les tests CI (via env var), pas en runtime utilisateur.

### 4.3 Capture/replay test d'intégration

**AVANT** la migration, on génère un snapshot des comportements actuels :

```python
# tests/test_cinesort_api_snapshot.py
def test_api_methods_signatures():
    """Snapshot : 168 méthodes publiques avec leurs signatures."""
    api = CineSortApi()
    snapshot = {
        name: str(inspect.signature(getattr(api, name)))
        for name in dir(api)
        if not name.startswith("_") and callable(getattr(api, name))
    }
    # Si snapshot diverge → fail (= signature change détectée)
    expected = load_json("tests/snapshots/api_methods_v1.json")
    assert snapshot == expected
```

Ce test **fail** si on supprime ou renomme une méthode par erreur.

### 4.4 Feature flag (optionnel)

Activer le nouveau code via env var, désactivable instantanément :

```python
USE_FACADES = os.environ.get("CINESORT_USE_FACADES", "1") == "1"
```

**Décision** : pas nécessaire car backward-compat 100% via adapter pattern. Le code dual est toujours actif.

### 4.5 Audit de surface avant chaque PR

Avant chaque PR migration, exécuter :

```bash
grep -rn "api\.{method_name}\|pywebview\.api\.{method_name}" web/ tests/
```

Pour avoir la **liste exhaustive** des callers à vérifier après migration.

### 4.6 Tests E2E après chaque PR

Si possible, build local + lancer le pywebview + scan dossier de test. Vérifier visuellement que les features marchent.

---

## 5. Plan détaillé PR par PR

### PR 1 — Squelette façades

**Fichiers créés** :
- `cinesort/ui/api/facades/__init__.py`
- `cinesort/ui/api/facades/_base.py` (BaseFacade avec injection api)
- `cinesort/ui/api/facades/run_facade.py` (1 méthode : `start_plan`)
- `cinesort/ui/api/facades/settings_facade.py` (1 méthode : `get_settings`)
- `cinesort/ui/api/facades/quality_facade.py` (1 méthode : `get_quality_profile`)
- `cinesort/ui/api/facades/integrations_facade.py` (1 méthode : `test_jellyfin_connection`)
- `cinesort/ui/api/facades/library_facade.py` (1 méthode : `get_library_filtered`)

**Fichiers modifiés** :
- `cinesort_api.py` : `__init__` instancie les 5 façades. Anciennes méthodes inchangées.

**Tests** :
- `tests/test_cinesort_api_facades.py` : 15 tests (5 façades × {existe, type correct, méthode pilote OK})

**Validation** :
- `python -m unittest tests/` : 3900+ tests doivent tous passer
- ruff check + format
- Sanity check : `api.run.start_plan(payload) == api.start_plan(payload)` (mêmes résultats)

**Effort** : 6-8h. **Risque** : faible. **Rollback** : `git revert`.

### PR 2-6 — Migration par bounded context

Pour chaque PR :
1. Lire les méthodes du context (ex: RunFacade : 7 méthodes)
2. Ajouter chacune dans la façade comme délégation
3. Tests : 1 test par méthode (qu'elle existe et marche)
4. Snapshot test : signatures préservées
5. Lint + tests + commit + PR

### PR 7 — Documentation

- Documenter les 5 façades dans `docs/internal/ARCHITECTURE.md`
- Mettre à jour CLAUDE.md
- Mettre à jour les docstrings des façades

### PR 8 — Migration frontend JS (RISQUE ÉLEVÉ)

Pour chaque appel `pywebview.api.{method}(...)` dans `web/` :
1. Identifier le bounded context (Run/Settings/Quality/etc.)
2. Remplacer par `pywebview.api.{facade}.{method}(...)`

Vérification : tester chaque feature dans l'app avec build local.

### PR 9 — Migration REST API dispatch

Modifier `cinesort/infra/rest_server.py` pour découvrir aussi les méthodes des façades. Format URL :
- Ancien : `POST /api/start_plan`
- Nouveau : `POST /api/run/start_plan` (ou alias `/api/start_plan` pour compat)

### PR 10 — Cleanup final

Quand toutes les anciennes méthodes ont **0 caller** (validé par grep + tests passants) :
- Supprimer les méthodes directes de CineSortApi
- Garder seulement les façades + 54 méthodes Misc + privées + helpers

---

## 6. Métriques de succès

| Métrique | Avant | Après (cible) |
|----------|-------|---------------|
| Lignes CineSortApi | 2203 | < 800 |
| Méthodes publiques CineSortApi | 104 | 54 (Misc) |
| Façades exposées | 0 | 5 |
| Tests passants | 3900+ | 3900+ (preserved) |
| Backward-compat | 100% | 100% (jusqu'à PR 10) |

---

## 7. Points de vérification avant chaque PR

**Checklist obligatoire** (à valider avant push) :

- [ ] Tests ciblés sur les modules touchés : OK
- [ ] Tests non-régression sur CineSortApi : OK
- [ ] `ruff check` : clean
- [ ] `ruff format --check` : clean
- [ ] Lint des JS modifiés (si applicable) : `node --check`
- [ ] Snapshot test des signatures CineSortApi : OK
- [ ] Sanity check manuel : 2-3 méthodes appelées via les deux formes (ancienne + façade)
- [ ] Documentation du commit : précise + close issues si applicable

---

## 8. Risques résiduels et mitigation

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Frontend JS casse silencieusement (PR 8) | Moyen | Élevé | Migration progressive par fichier + test E2E |
| REST API casse les clients externes | Faible | Moyen | Garder les URLs `/api/{method}` en alias |
| Tests E2E flakys masquent un vrai bug | Moyen | Élevé | Test snapshot des signatures comme garde |
| Plugin user appelle une méthode supprimée | **Nul** (vérifié) | N/A | Les plugins n'appellent pas l'API directement |
| Performance dégradée (extra délégation) | Très faible | Très faible | Délégation = 1 niveau de plus, négligeable |

---

## 9. Décisions architecturales (DDR)

### DDR-1 : Pourquoi Adapter pattern (dual API) au lieu de remplacement immédiat ?

**Décision** : Garder les anciennes méthodes ET ajouter les façades en parallèle.

**Raison** : Backward-compat 100%. Aucun call site (JS, REST, tests) ne casse à la PR 1. Migration progressive sans pression.

**Alternative rejetée** : Remplacement immédiat. Risque trop élevé, debug compliqué.

### DDR-2 : Pourquoi 5 façades et pas 6+ ?

**Décision** : Run/Settings/Quality/Integrations/Library + Misc reste sur CineSortApi.

**Raison** : Les 54 méthodes Misc sont trop hétérogènes (validation, apply, demo, dashboard, notifications, server). Créer 6+ façades = sur-segmentation. Mieux : laisser sur le god class réduit.

**Alternative** : Créer AdminFacade pour Apply/Validation. Pertinent mais nécessite analyse séparée, hors scope PR 1.

### DDR-3 : Pourquoi pas `@deprecated` en runtime ?

**Décision** : Pas de DeprecationWarning runtime sur les anciennes méthodes.

**Raison** : Spam dans les logs utilisateur. Le grep manuel + snapshot test suffisent pour tracker.

**Alternative envisagée** : activer SEULEMENT en CI via env var. Faisable mais sur-engineering pour le bénéfice.

### DDR-4 : Quel ordre pour les façades ?

**Décision** : Run → Settings → Quality → Integrations → Library.

**Raison** :
- Run et Settings : peu de méthodes (~10), faible risque, validation rapide
- Quality : grand nombre de méthodes (20) mais bounded context net
- Integrations : 11 méthodes, externe (Jellyfin/Plex/Radarr), bien isolé
- Library : peu de méthodes mais surface frontend large

---

## 10. Validation utilisateur attendue

Avant exécution, l'utilisateur doit valider :

- [ ] Le découpage 5 façades + Misc est OK ?
- [ ] Le découpage 10 PRs étalées sur plusieurs sessions est OK ?
- [ ] Les noms des façades sont OK (RunFacade, SettingsFacade, etc.) ?
- [ ] Les stratégies de sécurité (adapter pattern, snapshot test) sont suffisantes ?
- [ ] OK pour démarrer par PR 1 (squelette + 1 méthode pilote par façade) ?

---

**Note finale** : ce document est la **source de vérité** pour le refactor #84. Toute déviation doit être justifiée et documentée ici.

---

*Préparation 2026-05-14 par Claude Code. Validé par utilisateur le [DATE_VALIDATION]. Exécution démarrée le [DATE_DEMARRAGE].*
