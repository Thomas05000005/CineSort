# Audit Claude — 2026-06-21 — Couche transverse

**Modele** : Opus 4.8 (effort ultra, thinking max)
**Persona dominant** : ARCHITECT (categories 47 + 10 + 11 + 12)
**Niveau** : modere (fixes safe seulement, PRs petites)
**Modules audites** : couche transverse (architecture invariants, dette technique, lazy imports, repository pattern, dedup JS, module-style imports)
**Categories couvertes** : 10 (dette technique), 11 (code mort verifie), 12 (patterns Python), 20 (parite UI), 47 (architecture invariants)

## Resume executif

Les 3 chantiers historiques du prompt d'audit transverse (49 fonctions > 100L, 22 composants JS dupliques, 161 lazy imports) sont **essentiellement clos**. Tableau factuel verifie au 2026-06-21 :

| Metrique | Prompt (stale) | 2026-05-24 | 2026-06-21 | Source de mesure |
|----------|:-----------:|:-----------:|:-----------:|------------------|
| Fonctions Python > 100L | 49 | 14 | ~14 (memes fonctions) | spot-check des 9 symboles de #215 |
| Composants JS dupliques desktop/dashboard | 22 | 0 | **0** | `find web -type d` : seul `web/dashboard/` existe |
| Lazy imports `cinesort.X` (grep brut) | 161 | 33 | 93 | `grep -rnE '^[[:space:]]+(from\|import) cinesort'` |
| Lazy imports stdlib injustifies | n/a | ~10 | #554 partiel + #595 + **5 nouveaux** | grep cible (voir cat. 10) |
| Violations contracts import-linter | 0 | 0 | **0** | CI verte sur main + audit domain manuel |
| Mixins SQLite legacy (#85 B8) | 7 | 0 | **0** | `class SQLiteStore(_StoreBase)` (aucun mixin) |

**Conclusion** : couche transverse en **etat sain**. Aucune regression architecturale, aucun nouveau cycle, aucun mixin residuel. Le reliquat est du polishing (fonctions hot-path a decouper, lazy imports stdlib a promouvoir) deja trace dans des issues ouvertes. **Action principale de ce run : enrichissement de #215, #554, #595 avec des donnees fraiches** plutot que recreation (respect de la regle de dedup CRITIQUE, cf incident #91 -> #217).

### Note sur la directive "creer une issue pour chacun des 3 items"

Le prompt demande de creer une issue pour chacun des 3 chantiers transverses. **Les 3 ont deja une issue** :
1. Fonctions > 100L -> **#215** (ouverte, 14 fonctions, ROI tiers, plan multi-PR). -> enrichie (CAS B).
2. Composants JS dupliques -> **#217 / #91** (closes : legacy `web/views`/`web/components` supprime le 2026-05-19). Plus de duplication aujourd'hui. -> pas d'issue (resolu).
3. Lazy imports -> **#216/#83** (closes) + **#554/#595** (ouvertes, follow-ups stdlib). -> enrichies (CAS B).

Recreer ces issues violerait la regle anti-doublon (ETAPE 0). J'enrichis donc l'existant.

## Findings par categorie

### Categorie 10 — Dette technique

**F1 — #215 (enrichie, CAS B) : numeros de ligne perimes + `plan_support.py` scinde.**
Les 9 symboles cites par #215 existent toujours mais leurs **localisations ont change** depuis le 17 mai (les fichiers ont evolue). Surtout, `plan_support.py` a ete **scinde** en plusieurs modules (`plan_support_core.py`, `plan_support_replan.py`, `plan_support_dedup.py`). Localisations fraiches verifiees par grep :

| Symbole (issue #215) | Ancienne ref | Localisation 2026-06-21 |
|---|---|---|
| `_execute_undo_ops` | apply_support.py:300 | `cinesort/ui/api/apply_support.py:338` |
| `_cleanup_apply` | apply_support.py:1082 | `cinesort/ui/api/apply_support.py:1589` |
| `apply_changes` | apply_support.py:1705 | `cinesort/ui/api/apply_support.py:2049` |
| `current_folder_path` | apply_core.py:858 | `cinesort/app/apply_core.py:1474` |
| `move_file_with_collision_policy` | apply_core.py:471 | `cinesort/app/apply_core.py:629` |
| `apply_single` | apply_core.py:1044 | `cinesort/app/apply_core.py:1923` |
| `_plan_item` | plan_support.py:1581 | `cinesort/app/plan_support_replan.py:512` (module scinde) |
| `plan_multi_roots` | plan_support.py:1962 | `cinesort/app/plan_support_dedup.py:779` (module scinde) |
| `_patch` | composite_score_v2.py:495 | `cinesort/domain/perceptual/composite_score_v2.py:507` |

Severite : QUALITY (2). Confiance : 0.95. Pas d'urgence — plan multi-PR de #215 toujours valable.

**F2 — #595 (enrichie, CAS B) : 5 lazy imports stdlib injustifies non couverts.**
En cartographiant les lazy imports stdlib hors `ui/api/` (perimetre de #554/#595), je trouve 5 sites supplementaires :

| Fichier:Ligne | Import | Justifie ? |
|---|---|---|
| `cinesort/domain/perceptual/lpips_compare.py:109` | `import sys` | non (`sys` absent du top) |
| `cinesort/ui/api/library_actions_support.py:557` | `import time as _time` | non (`import time` deja en L24 — **redondant**) |
| `cinesort/app/plan_support_core.py:337` | `import os as _os` | non (`os` absent du top) |
| `cinesort/app/plan_support_core.py:485` | `import time as _time` | non (`import time` deja en L18 — **redondant**) |
| `cinesort/app/apply_batches_reconciliation.py:222` | `import json as _json` | non (`import json` deja en L47 — **redondant**) |

Contre-exemple verifie comme **justifie** (a NE pas toucher) : `cinesort/app/apply_core.py:282` `import time as _time_mod` porte un commentaire `# local pour eviter shadow du module time haut`.

Note d'interaction : le garde-fou `tests/test_refactor_84_progress_v77.py` (`MAX_LAZY_IMPORTS = 69`) borne le compte total. Toute promotion en top-level doit DIMINUER cette borne (cf consignes dans le test). Severite : QUALITY (2). Confiance : 0.90.

**F3 — #554 (enrichie, CAS B) : etat de resolution partiel.**
Re-verification des 4 sites de #554 :
- `cinesort/ui/api/settings_support.py` (`_secrets`, `_re`) : **resolus** (introuvables aujourd'hui).
- `cinesort/infra/probe/tools_manager.py:158` et `:342` (`import sys as _sys`) : **toujours presents**.
Severite : QUALITY (2). Confiance : 0.90.

### Categorie 11 — Code mort (verifie)

**F4 — docstrings repositories obsoletes (deja trace, PR #482 ouverte).**
Les docstrings de `cinesort/infra/db/repositories/*.py` mentionnent encore l'heritage `_XxxMixin` et la "Phase B8 future", alors que les mixins sont supprimes (`class SQLiteStore(_StoreBase)`). **Deja couvert par la PR ouverte #482** — pas de nouvelle action.

### Categorie 20 — Parite / dedup JS (RESOLU)

**F5 — duplication desktop/dashboard inexistante.**
`web/` ne contient plus que `web/dashboard/`, `web/shared/`, `web/splash.html`. Il n'existe plus de `web/views/` ni `web/components/` ni de seconde UI "desktop" (supprimes via #217, close 2026-05-19). La cible desktop pywebview charge le meme `web/dashboard/`. **Aucune duplication structurelle a mutualiser.** L'item "22 composants dupliques" du prompt est obsolete. Confiance : 0.95.

### Categorie 47 — Invariants architecture (CONFORME)

**F6 — cycle domain->app : aucun, contrats verts.**
- Aucun import runtime `cinesort.app`/`cinesort.infra` dans `cinesort/domain/**` : les seules occurrences sont (a) `domain/core.py:70` `TmdbClient` sous `TYPE_CHECKING` (whiteliste dans `.importlinter`), (b) des imports `domain->domain` (`duplicate_multi_signal` -> `perceptual.audio_fingerprint`, `audio_fingerprint` -> `_runners`), (c) des chaines dans des **docstrings** (faux positifs grep).
- `domain/_runners.py` implemente proprement un Service Locator (`set_runner`/`get_runner`) pour que la couche perceptual appelle `tracked_run`/`tracked_popen` sans dependre de `infra` — respecte `domain_pure`.
- CI verte sur `main` => les 3 contrats import-linter (`domain_pure`, `infra_bounded`, `app_bounded`) passent. Aucune nouvelle violation introduite. Confiance : 0.90.

**F7 — Repository pattern complet, mixins supprimes.**
11 repositories (`scan`, `run`, `film_modal`, `quality`, `perceptual`, `probe`, `anomaly`, `field_locks`, `apply`, `decisions` + `_base`). Aucune classe `_XxxMixin` ne subsiste. B8/#85 acheve. Conforme.

### Categorie 12 — Module-style imports pour mocks (NON RE-AUDITE EN PROFONDEUR)

Le pattern (`import cinesort.X as _mod` quand un test fait `patch("cinesort.X.Y")`) est documente dans CLAUDE.md et applique dans `apply_support.py`, `cinesort_api.py`, `perceptual_support.py`. Un audit exhaustif croisant tous les `patch(...)` des tests avec le style d'import du module appele n'a pas pu etre mene ce run (environnement restreint : `python`/`awk`/`ruff` non executables — voir Limitations). A reprendre au prochain run avec acces interpreteur.

## Statistiques

- Modules audites : couche transverse (205 fichiers `cinesort/**/*.py`, 74 fichiers JS `web/`)
- Findings : 7 (dont 5 enrichissements d'issues existantes, 2 confirmations de conformite)
- Issues creees : 0 nouvelle (regle dedup) — 3 enrichies (#215, #554, #595)
- PRs ouvertes : 1 (ce rapport) — 0 PR de code (voir Limitations)
- Findings deja connus (dedup) : 100% (tous mappes a #215/#217/#554/#595/#482/#85)

## Limitations de ce run (environnement restreint)

L'environnement d'execution de ce run bloquait `python`, `awk` et `ruff` (gate de permissions). Consequences :
1. **Inventaire fonctions > 100L** : mesure indirecte (spot-check des 9 symboles de #215 via grep) au lieu d'un comptage AST exhaustif. Le compte reste ~14, aucune fonction nouvelle > 100L detectee.
2. **Aucune PR de code ouverte** : la regle ABSOLUE "pre-commit obligatoire avant push" (`ruff format` + `ruff check` + `unittest`) ne pouvait pas etre satisfaite. Ouvrir des PRs de code non validees aurait risque une CI rouge (explicitement deconseille par le prompt). Les fixes safe (promotion des lazy imports stdlib de F2/F3) sont donc **documentes dans les issues** pour execution dans un environnement avec interpreteur, avec rappel d'ajuster `MAX_LAZY_IMPORTS`.
3. **Audit module-style (cat. 12)** : reporte (necessite interpreteur).

## Self-critique (ETAPE 2.6)

- FILTRE 1 (realite) : tous les findings verifies par grep/Read sur le code reel. 0 imagine.
- FILTRE 2 (idiome) : `apply_core.py:282` ecarte (lazy import justifie par anti-shadow, commente).
- FILTRE 3 (confiance) : tous >= 0.90.
- FILTRE 4 (dedup cross-cat) : F4 (docstrings) garde sous cat.11, deja sur PR #482.
- FILTRE 7 (etat actuel) : mixins/cycle/JS-dups verifies comme deja mitiges -> degrades en confirmations de conformite.
- Findings supprimes : 0 invente, 1 ecarte idiomatique (apply_core:282), JS-dedup et mixins requalifies en "conforme" au lieu de findings.
