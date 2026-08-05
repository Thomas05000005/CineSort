# Plan refactor #84 — God class CineSortApi → 5 façades par bounded context

**Version** : 1.4 (M-03 — inventaire lazy imports residuels + 4 conversions stdlib safes)
**Auteur** : Claude Code (sessions 2026-05-14, 2026-05-21 Sprint 7/C1, 2026-06-01 M-03 Vague M)
**Statut** : ✅ Phase 1 + Phase 2 + Sprint 7 + Sprint C1 **TERMINÉES** — Lot D restant (migration callers JS legacy) + lazy imports residuels documentes

## M-03 (Vague M, juin 2026) — Inventaire lazy imports residuels + conversions safes

**Contexte** : item M-03-FINISH-REFACTOR-84 vise la cloture des etapes 2-4 du refactor.
L'estimation initiale de 179 lazy imports etait pessimiste : apres Issue #83 (mai 2026,
150 lazy imports convertis sur ~165), il restait **73 lazy imports** dans le code source
au demarrage du sprint M-03.

**Strategie pragmatique** : refactor minimal viable a haut risque/faible rendement.
La majorite des 73 restants sont des choix volontaires documentes (deps optionnelles,
platform-specific, cycles intentionnels). Sprint M-03 :

- Convertit **4 lazy imports stdlib** dont la conversion etait clairement safe :
  - `cinesort/ui/api/settings_support.py` : `import re as _re` (L1444), `import secrets as _secrets` (L817) -> top-level
  - `cinesort/ui/api/quality_simulator_support.py` : `import re` (L443) -> top-level
  - `cinesort/infra/db/migration_manager.py` : `from pathlib import Path as _P` (L206) -> `Path` deja top-level, doublon supprime
- Compte final : **69 lazy imports** (verifie par AST visitor)
- Ajoute `tests/test_refactor_84_progress_v77.py` qui borne le compte a `MAX_LAZY_IMPORTS=69`
  pour prevenir toute regression future
- Documente ci-dessous les 69 lazy imports residuels par categorie

### Inventaire lazy imports residuels (69 total au M-03)

| Categorie | Count | Exemples / Justification |
|-----------|-------|--------------------------|
| **Dependances optionnelles** | ~17 | `segno` (QR), `onnxruntime` (LPIPS), `rapidfuzz` (fuzzy), `msvcrt`/`fcntl` (platform), `requests` ; bundle accepte ces deps mais le code reste robuste si absentes |
| **Cycles intentionnels documentes** | ~24 | `runtime_support.py` (evite cycle avec settings_support au load), `library_actions_support.py` (cross-module run_flow/plan/tmdb), `cleanup.py <-> apply_core`, `cinesort_api.py` endpoints rarement utilises |
| **Stdlib lazy par WHY documente** | ~8 | `apply_core.sha1_quick` `import time as _time_mod` (commentaire : eviter shadow), `cinesort_api._get_app_version_impl` (subprocess + datetime + sys, endpoint ponctuel) |
| **Cas restants a auditer** | ~20 | Petit gain attendu, risque potentiel de cycle ; reportes a un sprint futur (Vague N+) |

### Top fichiers avec lazy imports residuels

| Fichier | Count | Type dominant |
|---------|-------|---------------|
| `cinesort/ui/api/perceptual_support.py` | 7 | Cross-module + dep optionnelle onnxruntime |
| `cinesort/ui/api/cinesort_api.py` | 6 | Endpoints ponctuels documentes (`# noqa: PLC0415`) + dep segno |
| `cinesort/ui/api/library_actions_support.py` | 5 | Cross-module run_flow / plan_support / tmdb_client (cycle potentiel) |
| `cinesort/domain/perceptual/audio_perceptual.py` | 4 | Dep onnxruntime + numpy |
| `cinesort/domain/perceptual/lpips_compare.py` | 4 | Dep onnxruntime |
| `cinesort/infra/single_instance.py` | 4 | Platform-specific (msvcrt vs fcntl) |
| `cinesort/ui/api/library_audit_support.py` | 4 | Cross-module library_support + tmdb_client |
| `cinesort/ui/api/run_flow_support.py` | 4 | Cross-module quality_audit / perceptual / run_data_support |

### Travail residuel (Vague N+ ou futur sprint dedie)

- **Resolution des ~20 cas restants** : audit fichier par fichier de cinesort_api.py, run_flow_support.py
  et library_actions_support.py. Necessite analyse fine du graphe d'imports pour chaque cas.
- **Suppression des `# noqa: PLC0415`** : si le lazy import devient inutile, retirer le noqa.
- **CI ajouter rule ruff PLC0415** : non strict pour eviter regression, mais signaler dans la review.
- **Re-verifier MAX_LAZY_IMPORTS** : si le code grossit, mettre a jour la borne (ou faire du cleanup).

### Acceptance de M-03 (Vague M)

- [x] Inventaire des lazy imports residuels documente (69 categorises)
- [x] 4 conversions stdlib safes appliquees sans regression
- [x] Test regression `tests/test_refactor_84_progress_v77.py` qui borne le compte
- [x] CLAUDE.md / REFACTOR_PLAN_84.md mis a jour
- [ ] **Status PARTIAL** : 4 conversions sur ~20 candidats convertibles. Effort restant
      ~10-15h reporte a un sprint dedie (Vague N+) car risk/reward non-favorable pour M-03
      (la majorite des candidats demandent une analyse cycle import par cas).

---

## Résumé d'avancement (au 2026-05-21)

| PR | Bounded context | Méthodes | Tests | Commit | Statut |
|----|-----------------|----------|-------|--------|--------|
| #129 (PR 1) | Squelette 5 façades pilote | 5 × 1 méthode | 12 | b40a977 | ✅ Mergée |
| #130 (PR 2) | RunFacade complète | 7 | +11 | e042af2 | ✅ Mergée |
| #131 (PR 3) | SettingsFacade complète | 6 | +10 | 882cb6f | ✅ Mergée |
| #132 (PR 4) | QualityFacade complète | 21 | +27 | 854e9a7 | ✅ Mergée |
| #133 (PR 5) | IntegrationsFacade complète | 11 | +15 | 3689e98 | ✅ Mergée |
| #134 (PR 6) | LibraryFacade complète | 9 | +16 | 7dafb5a | ✅ Mergée |
| **Phase 1 total** | **5 façades, 54 méthodes** | **54** | **+91** | — | ✅ **TERMINÉE** |
| PR 7 | Documentation finale | — | — | (cette PR) | 🟡 En cours |
| PR 8 | Migration frontend JS | — | — | — | ✅ Mergée |
| PR 9 | Migration REST dispatch | — | — | — | ✅ Mergée |
| PR 10 | Suppression méthodes directes | — | — | — | ✅ Mergée (Pass 1 legacy mai 2026) |
| Sprint 7 (#335) | RuntimeFacade probe tools | 10 | +12 | 68165fd | ✅ Mergée |
| Sprint C1 | Extraction 8 méthodes orphelines + clamping C7 | 8 + 6 clamps | +17 | (cette PR) | 🟡 En cours |

## Sprint C1 (mai 2026) — Extraction des 8 méthodes orphelines + input clamping (audit C7 P1)

**Contexte** : suite de PR #335 (Sprint 7) qui a terminé la couverture probe tools. Restent 8 méthodes `_X_impl` orphelines (non exposées par façade). Le sprint C1 :
- les extrait toutes les 8 vers leur façade respective ;
- ajoute le clamp d'entrée sur 5 endpoints `test_X_connection` + `test_reset` (audit C7 P1).

### Partie 1 — Extraction Sprint C1 (8 méthodes orphelines)

**Méthodes ajoutées** :

| Méthode | Façade cible | Notes |
|---------|--------------|-------|
| `get_naming_presets()` | `SettingsFacade.get_naming_presets` | Liste presets renommage |
| `preview_naming_template(template, sample_row_id)` | `SettingsFacade.preview_naming_template` | Preview template |
| `export_shareable_profile(name, author, description)` | `QualityFacade.export_shareable_profile` | Export profil communautaire (P4.3) |
| `import_shareable_profile(content, activate)` | `QualityFacade.import_shareable_profile` | Import profil communautaire (P4.3) |
| `get_auto_approved_summary(run_id, threshold, enabled, quarantine_corrupted)` | `RunFacade.get_auto_approved_summary` | Résumé auto-approve batch |
| `undo_last_apply_preview(run_id)` | `RunFacade.undo_last_apply_preview` | Preview undo v1 |
| `undo_by_row_preview(run_id, batch_id)` | `RunFacade.undo_by_row_preview` | Preview undo v5 par row |
| `undo_selected_rows(run_id, row_ids, dry_run, batch_id, atomic)` | `RunFacade.undo_selected_rows` | Undo v5 sélection |

**Pattern** : Strangler Fig identique aux PRs précédentes — la façade délègue vers `self._api._X_impl(...)`, l'`_impl` reste inchangé, backward-compat 100% préservée.

### Partie 2 — Input clamping (audit C7 P1)

**Constat** : 5 endpoints `_test_X_connection_impl` acceptaient `timeout_s` sans aucune validation. Un caller (REST distant compromis, test E2E mal calibré, frontend buggué) pouvait passer `timeout_s=0` (division par zéro), `99999` (DoS thread API), `"abc"` (TypeError), `None` (TypeError), `NaN`, `Inf` — tous causant des crashes ou comportements imprévus.

**Solution** : helper centralisé dans `cinesort/ui/api/_validators.py`.

```python
def clamp_timeout(value, default=10.0, lo=1.0, hi=60.0) -> float:
    """Borne `value` entre [lo, hi], fallback sur `default` si parsing
    impossible (None, str non-numérique, NaN, inf)."""
```

Appliqué à 5 méthodes :
- `_test_tmdb_key_impl`
- `_test_jellyfin_connection_impl`
- `_test_plex_connection_impl` (remplace `max(1, min(30, timeout_s))` — range élargi à 60s)
- `_test_radarr_connection_impl` (idem)
- `_test_omdb_connection_impl` (idem)

Plus `clamp_non_negative_int(value, default=0)` pour `test_reset(min_video_bytes)` : normalise vers `int >= 0`, fallback à 0 sur input invalide.

**Tests** : +17 tests dans `tests/test_cinesort_api_facades.py` :
- 8 tests délégation pour les 8 nouvelles méthodes (sanity + signature defaults).
- 6 tests unitaires sur les helpers `clamp_timeout` / `clamp_non_negative_int`.
- 7 tests d'intégration vérifiant que les 5 endpoints connexion + `test_reset` appellent bien le clamp.

**Lot D restant** :

Reste à faire dans des PRs séparées (non bloquant pour la prod) :
- **Migration des callers JS legacy** : audit grep `pywebview.api.{method}(...)` pour les 8 méthodes ci-dessus, remplacement par `pywebview.api.{facade}.{method}(...)`.
- **Audit C7 P2-P5** : autres opportunités de hardening des inputs (taille listes batch, longueur strings, etc.) — hors scope sprint C1.
- **Nettoyage final REFACTOR_PLAN_84** : marquer Sprint C1 comme mergé, archiver les sections obsolètes (Phase 2 callers JS déjà terminée).

**Backward-compat 100% préservée** : les 104 méthodes directes de `CineSortApi` coexistent avec les 5 façades. Les anciens call sites (`api.X(...)`) et les nouveaux (`api.context.X(...)`) fonctionnent en parallèle. La suppression des méthodes directes ne se fera qu'à la PR 10, après migration complète des callers JS et REST.

**Snapshot de sécurité** : `tests/test_cinesort_api_snapshot.py` garde les 104 signatures publiques (échoue si une méthode disparaît ou change de signature). Régénération via `regenerate_snapshot()` si suppression intentionnelle.

---

## Utilisation des façades (guide rapide)

### Pour ajouter une nouvelle méthode dans un bounded context

```python
# 1. Ajouter la méthode dans CineSortApi (cinesort/ui/api/cinesort_api.py)
def my_new_method(self, arg: str) -> Dict[str, Any]:
    """Doc complète ici."""
    return some_support.my_new_method(self, arg)

# 2. Ajouter la délégation dans la façade correspondante
# Exemple : cinesort/ui/api/facades/quality_facade.py
def my_new_method(self, arg: str) -> Dict[str, Any]:
    """Référence vers CineSortApi.my_new_method.

    Cf CineSortApi.my_new_method pour la doc complète.
    """
    return self._api.my_new_method(arg)

# 3. Ajouter un test de délégation
# Exemple : tests/test_cinesort_api_facades.py
def test_my_new_method_delegates(self) -> None:
    sentinel = {"ok": True}
    with patch.object(self.api, "my_new_method", return_value=sentinel) as mocked:
        result = self.api.quality.my_new_method("foo")
    mocked.assert_called_once_with("foo")
    self.assertEqual(result, sentinel)
```

### Pour utiliser une façade depuis du code Python

```python
# Ancien style (toujours fonctionnel jusqu'à PR 10)
result = api.start_plan(settings)

# Nouveau style (préféré pour nouveau code)
result = api.run.start_plan(settings)
```

### Mapping rapide bounded context → façade

- **Run** (cycle de vie scan/plan/apply preview) → `api.run`
- **Settings** (configuration, locale, reset, restart) → `api.settings`
- **Quality** (scoring, profiles, perceptual, feedback) → `api.quality`
- **Integrations** (TMDb, Jellyfin, Plex, Radarr) → `api.integrations`
- **Library** (films filtres, smart playlists, history, export RGPD) → `api.library`

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

---

## 11. Journal des bornes d'imports différés (`MAX_LAZY_IMPORTS_BY_LAYER`)

Le cliquet de `tests/test_refactor_84_progress_v77.py::test_lazy_imports_bounded` est posé
**à zéro marge** sur la mesure réelle. Toute PR qui ajoute un import différé le fait donc
rougir — c'est voulu : chaque ajout doit être une décision, pas une dérive. Ce journal
enregistre les décisions.

Règle : on ne remonte une borne que si l'import différé est **nécessaire** (cycle réel), et
on en profite pour **redescendre** toute couche qui aurait pris de la marge dormante — une
marge non reprise laisse passer une récidive gratuite.

| date | couche | avant → après | raison |
|---|---|---|---|
| 2026-08-03 | toutes | — | valeurs initiales, mesurées à zéro marge |
| 2026-08-04 | `app` | 24 → **23** | marge dormante reprise (mesure réelle = 23) |
| 2026-08-04 | `ui` | 110 → **111** | PR#853 : `film_support` importe tardivement `history_support.get_plan_row`. Les deux modules se référencent mutuellement ; un import de tête crée un cycle à l'import du paquet. Le total global reste à 170, `app` rendant le point que `ui` prend. |
| 2026-08-04 | `ui` | 111 → **113** | PR#847, +2 : `quality_report_support` importe tardivement `run_read_support.full_langs_from_embedded` et `domain.subtitle_helpers._normalize_iso639`. **Aucun cycle dur établi** — `run_read_support` n'importe pas `quality_report_support` en retour. Relevée quand même parce que ces deux imports suivent le motif déjà en place dans le module (`dashboard_support.py:300-309` importe `run_read_support` tardivement à quatre endroits) : les convertir isolément n'aurait pas de sens, c'est le motif entier qui demande un nettoyage. **Dette assumée, à reprendre dans le chantier de conversion de la couche `ui`.** |
| 2026-08-04 | `app` | 23 → **25** | PR#852, +2, les deux vérifiés un par un. (a) `cleanup` → `apply_core._append_error_message` : **vrai cycle**, `apply_core.py:15` importe déjà `cleanup`. (b) `apply_batches_reconciliation` → `apply_audit.read_apply_audit` : **pas** de cycle ; conservé pour la raison que révèle le `except ImportError` en dessous — sur un build EXE **amputé**, un import de tête tuerait tout le module de réconciliation, l'import local ne dégrade que la lecture du marqueur. Le commentaire du code affichait une autre raison (« éviter de charger au boot »), corrigée. |
| 2026-08-05 | `ui` | 113 → **111** | Issue #599, **−2 : conversion, pas relèvement**. `film_support._fetch_tmdb_extras` portait deux imports différés : `from cinesort.infra.tmdb_client import TmdbClient` et `import requests as _req`. Aucun cycle ne les justifiait — le contrat `infra_bounded` interdit à `infra` de remonter vers `ui`, donc un import de tête est sûr, et il est écrit **module-style** (`from cinesort.infra import tmdb_client as _tmdb_client`) pour que les `patch("cinesort.infra.tmdb_client.TmdbClient", …)` des tests restent opérants. Le second a purement disparu : le `requests.get` direct est rapatrié sur `TmdbClient.get_movie_extras`. Nouveau total mesuré : **172**. |
| 2026-08-04 | — | 170 → **174** | Fusion PR#852 ↔ main. Rien à arbitrer côté bornes : les deux apports portent sur des couches **disjointes** (`app` +2, `ui` +2), et la mesure post-fusion retombe **exactement** sur chaque borne — aucune couche n'a pris de marge dormante. Deux affirmations sont en revanche devenues fausses et ont été corrigées : (a) « le total reste à 170 » — la compensation `app`/`ui` de PR#853 était une coïncidence, pas une règle, seule la borne **par couche** fait foi ; (b) « `apply_audit` n'importe que la stdlib » — main y a ajouté `infra.log_scrubber` (issue #414), qui tire `infra.log_context`. Le verdict de (b) tient quand même : `infra_bounded` interdit à `infra` de remonter vers `app`, donc toujours aucun cycle, et l'argument du build EXE amputé se **renforce** puisque la chaîne d'import s'allonge. |
| 2026-08-05 | `app` | 25 → **19** | Issues #554/#595, **−6 : conversions stdlib**. Trois n'étaient que des **alias redondants** — le module était déjà importé en tête : `apply_core.sha1_quick` (`import time as _time_mod`, dont le commentaire « local pour éviter shadow du module `time` haut » décrit un shadow qui **n'existe plus** : vérifié, aucun paramètre ni variable locale nommée `time` dans la fonction), `apply_batches_reconciliation._close_batch` (`json`), `plan_support_core.wait_while_paused` (`time`). Trois vrais ajouts en tête : `os` (`plan_support_core.folder_signature`), `contextlib` (`plan_support_replan._resolve_tmdb_collection`), `concurrent.futures.ThreadPoolExecutor` (`_local_candidate`). |
| 2026-08-05 | `domain` | 16 → **15** | Issue #595 (élargie), **−1** : `perceptual/lpips_compare._resolve_model_path` importait `sys` dans la fonction pour lire `sys.frozen`. |
| 2026-08-05 | `infra` | 17 → **11** | Issues #554/#595, **−6**. Les **2 sites nommés par #554** (`probe/tools_manager` lignes 154/338 à l'époque, 158/342 aujourd'hui, `import sys as _sys`) sont les seuls de cette issue encore présents : les 2 autres (`settings_support` `secrets`/`re`) avaient déjà été convertis en M-03 — **#554 était à moitié périmée**. S'y ajoutent `poster_proxy` ×2 (`json`), `rest_server._handle_get` (`urllib.parse.parse_qs`, alors que le module importe déjà `urlsplit` de la même provenance en tête) et `probe/service.__init__` (`shutil.which`). **Restent 6 imports différés stdlib**, tous justifiés et volontairement conservés : `msvcrt`/`fcntl` ×4 (`single_instance`, spécifiques à la plateforme — `import msvcrt` lève `ImportError` sur Linux) et `ctypes` ×1 (`db/pragma_profile.detect_storage_type`, sous garde `except ImportError` : un import de tête transformerait une dégradation best-effort en échec de chargement du module). |
| 2026-08-05 | `ui` | 111 → **66** | Issues #554/#595/#779, **−45**. C'est le « chantier de conversion de la couche `ui` » que la ligne PR#847 ci-dessus renvoyait à plus tard. **11 stdlib** (#595) : `cinesort_api` (`io`, `webbrowser`, `datetime`, `subprocess`, `sys`), `perceptual_support` (`base64` ×3, `io`), plus deux alias redondants (`time` dans `library_actions_support`, `threading` dans `run_flow_support`, déjà en tête). **34 internes** (#779) : les clusters n°2 et n°3 nommés par l'issue — `dashboard_support` 13 → 0, `history_support` 11 → 1, plus `library_audit_support` ×4, `quality_audit_support` ×2, `profiles_support_import_export` ×3, `library_actions_support` ×1. Les cibles `ui/api` sont importées **module-style** (`from cinesort.ui.api import run_read_support` puis `run_read_support.effective_flags(...)`), jamais par symbole : cf. §11.2, un import de symbole en tête casse silencieusement les `patch(...)` des tests. Nouveau total mesuré : **114**. |

### 11.1 Cartographie des cycles `ui/api` (issue #779, mesure du 2026-08-05)

L'issue #779 annonçait « 89 imports différés intra-couche formant un
enchevêtrement de cycles ». La mesure AST au moment d'attaquer le lot en compte
**59** (le décompte de l'issue, daté du 2026-07-19, est périmé — plusieurs PR
sont passées entre-temps).

Méthode : construire le graphe des imports de **tête** (module-level) du paquet,
puis, pour chaque import différé `A → B`, chercher un chemin `B → … → A` **par
imports de tête uniquement**. S'il existe, un import de tête `A → B` fermerait le
cycle et casserait le chargement du paquet : l'import différé est nécessaire.
Sinon c'est un import différé posé « au cas où ».

| | nb |
|---|---:|
| imports différés intra-`ui/api` (avant lot) | 59 |
| dont posés sur une **vraie** arête de retour | **4** |
| dont sans aucun cycle à contourner | 55 |

Les 4 vrais cycles :

- `library_support` → `library_actions_support` ×3 (`migrate_legacy_deletion_marks`,
  `remove_legacy_deletion_mark`) — retour direct : `library_actions_support`
  importe en tête `library_support._build_library_rows`.
- `reset_support` → `cinesort_api` — retour direct : `cinesort_api` importe
  `reset_support` en tête (ligne 60, dans le bloc des 26 `*_support`).

**Le second argument invoqué par ces imports différés — le coût de démarrage —
n'existe pas non plus** : `cinesort/ui/api/__init__.py` importe `cinesort_api`,
qui importe **en tête** 26 modules `*_support`. Ils sont donc tous chargés au
boot quoi qu'il arrive ; différer un import de l'un vers l'autre ne fait
qu'échanger l'ordre, jamais le coût.

**Ce que ce lot laisse volontairement en place** (et pourquoi) :

| site | raison |
|---|---|
| `library_support` ↔ `library_actions_support` (3), `reset_support` → `cinesort_api` (1) | vrai cycle, mesuré |
| `run_flow_support` ×5, `quality_audit_support` ×1 | le `try` englobant attrape **`ImportError` en tête de tuple** : l'import différé y est un contrat de dégradation (enrichissements post-scan best-effort). Un import de tête transformerait la panne d'une option en échec de boot — sur un build EXE amputé, c'est le même raisonnement que celui déjà retenu pour `apply_batches_reconciliation` (PR#852) |
| `runtime_support._safe_read_settings_for_diag` | sa docstring dit « on évite tout import top-level pour ne pas créer de cycle » : **c'est faux**, la mesure ne trouve aucune arête de retour `settings_support → runtime_support`. Mais la fonction est un **diagnostic** entouré d'un `except Exception` — elle doit rendre `{}` plutôt que d'exploser quand `settings_support` est cassé, ce qui est justement le cas où on l'appelle. Conservé pour cette raison-là, pas pour la raison affichée |
| `film_support` ↔ `history_support` | référence mutuelle réelle : une des deux directions doit rester différée. Arbitrer laquelle (et sur quel critère de « couche basse ») dépasse ce lot |
| imports différés `ui → app`/`infra`/`domain` restants | hors périmètre #779 (intra-couche). Aucun ne peut être un cycle : `app_bounded`/`infra_bounded` interdisent le retour vers `ui` |

### 11.2 Le piège qui a mordu : `from X import f` fige le binding

Première rédaction de ce lot : `history_support` importait en tête
`from cinesort.ui.api.library_support import _get_store`. C'est **faux**, et le
mode de panne est silencieux dans un cas et bruyant dans l'autre :

`tests/test_get_plan_ignored_alerts_v77.py` fait
`patch("cinesort.ui.api.library_support._get_store", return_value=store)`. Avec
l'import **différé**, l'import s'exécute pendant l'appel, donc *après* la pose du
patch : le test contrôle réellement le store. Avec un import de **symbole en
tête**, `history_support._get_store` est lié à l'objet original au chargement du
module, et le patch ne l'atteint plus. Ici le test a viré au rouge (il assertait
sur le résultat filtré) — mais le même mécanisme, sur un patch dont le test
n'observe que l'absence d'effet, laisserait un test **vert qui ne teste plus
rien**.

Règle appliquée dans ce lot, et déjà énoncée par la convention « module-style
imports pour tests mockés » : quand la cible est un module `ui/api`, on importe
le **module** (`from cinesort.ui.api import run_read_support`) et on appelle
`run_read_support.effective_flags(...)`. La résolution reste tardive, donc
patchable. Les imports de symbole en tête ne sont conservés que pour les
helpers `domain.*` purs (`to_int`, `_normalize_iso639`,
`strip_trailing_year_if_equal`) et les constantes, qui ne sont jamais mockés.

Ce défaut a été trouvé par la mutation, pas par la relecture.

**Ce qui reste à faire sur #779** : mesure après ce lot = **32** imports différés
intra-`ui/api` (59 − 27 convertis), dont **4 nécessaires** (les vrais cycles
ci-dessus) et 6 conservés pour leur `except ImportError`. Le solde (~22) est du
découplage réel, pas de la conversion mécanique — extraire
`library_support._get_store` dans un module feuille (la « PR pilote » proposée
par l'issue) casserait à lui seul le cluster n°2 (`run_read_support` ×2,
`history_support` ×2), et arbitrer le couple `film_support`/`history_support` en
réglerait un de plus.
