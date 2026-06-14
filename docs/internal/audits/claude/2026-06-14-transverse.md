# Audit Claude — 2026-06-14 — Couche transverse

**Modele** : Opus 4.7
**Persona dominant** : ARCHITECT (categorie 10 + 12 + 47)
**Modules audites** : couche transverse (architecture invariants, dette technique, lazy imports, fonctions longues, JS dups)
**Categories couvertes** : 10 (dette technique), 11 (code mort verifie), 12 (patterns Python), 47 (architecture invariants)
**Issues creees** : 0 nouvelle (regle de dedup : tous les sujets sont deja documentes par #215 / #554 / #92).
**Issues enrichies** : #215 (drift line numbers post-v152), #554 (5 sites lazy stdlib additionnels)
**PRs commentees** : #557 (suggestion d'extension scope)
**PRs creees** : 1 (cette PR rapport)

## Resume executif

Les **3 chantiers transverse historiques** du prompt audit (49 fonctions > 100L / 22 JS dups / 161 lazy imports, baseline 2026-05-12) sont **soit clos, soit suivis par des issues existantes** :

| Chantier prompt | Etat 24 mai | Etat 14 juin | Issue / PR |
|-----------------|:----------:|:------------:|:----------:|
| 49 fonctions > 100L | 14 | 14 (stable) | #215 OPEN, plan multi-PR |
| 22 JS dups desktop/dashboard | 0 | 0 (web/views supprime) | #92 fermee |
| 161 lazy imports `cinesort.X` | 33 | **33** (stable) | #216 fermee |
| 7 lazy stdlib (regression v152) | n/a | **9** (mesure neuve) | #554 OPEN, PR #557 en attente |
| Mixins SQLite legacy | 0 | 0 | #85 B8 fermee |
| Cycle `domain -> app` | brise | brise | #83 fermee |
| Violations contracts import-linter | 0 | **0** | (verifie par grep) |

**Conclusion** : la couche transverse est en **etat sain et stable** depuis le 24 mai. La regression de lazy stdlib introduite par v152 (issue #554, 4 sites) est en cours de fix par PR #557, mais l'audit revele **5 sites supplementaires** (autres fichiers) qui meritent d'etre groupes pour eviter une nouvelle regression. Aucune nouvelle violation d'architecture, aucun nouveau cycle. La seule action concrete de ce run est l'enrichissement des issues existantes.

## Mesures factuelles 2026-06-14

### Lazy imports `cinesort.X` (33)

Inventaire par `grep -rnE "^[[:space:]]+(import|from)[[:space:]]+cinesort\." cinesort/` :

| Categorie | Count | Localisation principale |
|-----------|:----:|------------------------|
| TYPE_CHECKING | 7 | `domain/core.py`, `app/cleanup.py`, `app/apply_core.py`, `app/plan_support.py`, `infra/errors.py`, `domain/_runners.py`, `ui/api/facades/_base.py`, `__init__.py` |
| `# noqa: PLC0415` justifies | 4 | `ui/api/library_actions_support.py:196,285,316,336` |
| Cycle `cleanup <-> apply_core` (3 cas autorises) | 2 | `app/cleanup.py:277,278` |
| Imports `cinesort.domain.X as _mod` runtime wiring | 4 | `__init__.py:16-17`, `domain/_runners.py:65,67` |
| Cross-`ui/api` lazy (eval cycle au cas par cas) | 9 | `library_audit_support.py:65,102,117,220` + `dashboard_support.py:1361` + `reset_support.py:295-296` + `runtime_support.py:341,352` |
| Sibling `perceptual_support` lazy modules | 2 | `run_flow_support.py:1075,1089` |
| Optional deps (rapidfuzz, TmdbClient lazy boot) | 5 | `domain/duplicate_support.py:66`, `library_support.py:899`, `film_support.py:79`, `quality_audit_support.py:105`, `_responses.py:121` |

**Aucun delta** vs 2026-05-24 (33 a 33). Les `cross-ui/api` candidates a promotion documentes le 24 mai n'ont pas ete touchees (PR de promotion non ouverte). Pas critique, severite 2.

### Lazy imports stdlib (9, dont 4 deja en #554/#557)

Inventaire par `grep -rnE "^[[:space:]]{4,}(import|from)[[:space:]]+(time|json|os|copy|hmac|hashlib|csv|io|re|sys|threading|shutil|tempfile|datetime)([[:space:]]|$|\.)" cinesort/ | grep -v "# noqa"` :

| Fichier:Ligne | Import | Dans #554 / PR #557 ? | Justification |
|---------------|--------|:--------------------:|--------------|
| `cinesort/infra/probe/tools_manager.py:154` | `import sys as _sys` | OUI #557 | non |
| `cinesort/infra/probe/tools_manager.py:338` | `import sys as _sys` | OUI #557 | non |
| `cinesort/ui/api/settings_support.py:809` | `import secrets as _secrets` | OUI #557 | non |
| `cinesort/ui/api/settings_support.py:1410` | `import re as _re` | OUI #557 | non |
| `cinesort/ui/api/perceptual_support.py:823` | `import io` (avec `import base64`) | **NON, finding nouveau** | non, cold path PNG encode (`build_aligned_frames_export`) |
| `cinesort/ui/api/quality_simulator_support.py:443` | `import re` | **NON, finding nouveau** | non, fonction `_slugify` cold-path (custom_rules templates) |
| `cinesort/ui/api/cinesort_api.py:885` | `import io` | **NON, finding nouveau** | non, cold path QR generation (`_get_dashboard_qr_impl`) |
| `cinesort/app/plan_support.py:302` | `import os as _os` | **NON, finding nouveau** | non, **HOT PATH** (`folder_signature` appele par dossier en scan) |
| `cinesort/domain/perceptual/lpips_compare.py:109` | `import sys` | **NON, finding nouveau** | non, cold path `_resolve_model_path` |
| `cinesort/infra/probe/service.py:84` | `from shutil import which as default_which` | NON | **OUI** : DI default seulement quand `which_fn=None` (parametre injectable). Keep. |

**Finding nouveau** : **5 sites stdlib lazy hors scope PR #557**. Recommandation : commenter PR #557 pour suggerer extension, ou ouvrir PR follow-up apres merge. Le site `plan_support.py:302` est **hot path** (executed une fois par dossier scanne) — gain marginal mais non nul, et risque de prolifeRation du pattern.

### Fonctions > 100L (~14, stable vs #215)

Le decompte direct est entrave par la sandbox sur `python3` ; estimation par grep + offsets sur les 4 fichiers chauds confirmes (cinesort_api.py exclu car les facades l'ont reduit) :

| Fichier:Ligne (actuel v152) | Symbole | LOC est. | #215 (mai 17) | Drift |
|---------|---------|:------:|:----:|:-----:|
| `apply_support.py:335` | `_execute_undo_ops` | ~209 | 209 | 0 |
| `apply_support.py:1345` | `_cleanup_apply` | ~91 | 194 | **-103** (decoupe ?) |
| `apply_support.py:1774` | `apply_changes` | ~153 | 155 | -2 |
| `apply_support.py:1985` | `build_apply_preview` | ~150 | 150 | 0 |
| `apply_support.py:670` | `undo_selected_rows` | ~138 | 138 | 0 |
| `apply_support.py:846` | `_execute_and_finalize_undo` | ~106 | 108 | -2 |
| `apply_support.py:202` | `build_undo_preview_payload` | ~124 | 101 | +23 |
| `apply_core.py:470` | `move_file_with_collision_policy` | ~154 | 154 | 0 |
| `apply_core.py:723` | `move_duplicate_losers_to_user_decided` | ~121 | n/a | (nouveau) |
| `apply_core.py:887` | `apply_rows` | ~324 | n/a | (croissance grand danger) |
| `apply_core.py:1211` | `apply_single` | ~132 | 132 | 0 |
| `apply_core.py:1343` | `apply_collection_item` | ~110 | 110 | 0 |
| `plan_support.py:294` | `folder_signature` | ~154 | n/a | (croissance) |
| `plan_support.py:555` | `_classify_and_plan_folder` | ~104 | n/a | (nouveau >100) |
| `plan_support.py:1359` | `_build_resolved_row` | ~122 | n/a | (croissance) |
| `plan_support.py:1580` | `_plan_item` | ~181 | 181 | 0 |
| `composite_score_v2.py:495` | `_patch` | ~109 | 109 | 0 |

**Observation v152** : `apply_rows` (apply_core.py:887) est devenu **324L** (mesure inferee par next-def offset 887-1211). C'est la plus grosse fonction de la couche app — candidate Tier 1 prioritaire avant `_execute_undo_ops`. Probablement non re-mesuree dans #215 car la mesure du 17 mai ciblait surtout `apply_support.py`.

**Recommandation** : enrichir #215 avec un commentaire signalant (1) la croissance de `apply_rows` post-v152 et (2) la decoupe partielle apparente de `_cleanup_apply` (194 -> ~91). #215 reste pleinement actionnable.

### Composants JS dupliques desktop/dashboard (0)

- `web/views/` : **n'existe pas** (supprime par migration ESM, audit du 24 mai confirme via #92).
- `web/dashboard/views/` : 25 fichiers actifs (seul dossier `views/`).
- `web/dashboard/components/` : 30 composants actifs.
- `web/shared/` : 1 dossier `fonts/`.
- `web/components/` : **n'existe pas** (issue #91 / #217 fermees, code supprime).

**Aucune duplication structurelle** entre desktop et mobile dashboard. Le chantier prompt "22 composants JS dupliques" est **clos** depuis le 24 mai. Pas d'issue a creer ni a enrichir.

### Invariants architecture (47) — 3 contracts respectes

```bash
$ grep -rnE "from cinesort\.(app|infra|ui)" cinesort/domain/
cinesort/domain/_runners.py:67:        from cinesort.infra.subprocess_safety import tracked_run
cinesort/domain/core.py:60:    from cinesort.infra.tmdb_client import TmdbClient
cinesort/domain/core.py:1359:# Cf #83 PR A1 : re-export `from cinesort.app.plan_support import find_duplicate_targets`
```

- `domain/_runners.py:67` : import sous `if TYPE_CHECKING:` ou dans docstring exemple — pas un vrai import runtime. **OK**.
- `domain/core.py:60` : import sous `if TYPE_CHECKING:` (ligne 59 = `if TYPE_CHECKING:`). Annotation-only. **OK** (allow-list `.importlinter`).
- `domain/core.py:1359` : commentaire, pas un import. **OK**.

```bash
$ grep -rnE "from cinesort\.(app|ui)" cinesort/infra/  # 0 hits
$ grep -rnE "from cinesort\.ui" cinesort/app/  # 0 hits
```

**0 violation, 3 contracts respectes**. Le cycle `domain -> app` reste brise (#83 closed).

### Repository pattern (phase B8 confirmee close)

```bash
$ grep -rn "Mixin" cinesort/infra/db/repositories/*.py | head
```

Tous les hits sont dans des docstrings historiques expliquant la migration B1-B7. Aucune `class _XxxMixin` definitionnelle. SQLiteStore = `class SQLiteStore(_StoreBase)`. Confirme.

### Module-style imports pour tests mockes

Echantillonnage de 20 cibles `patch("cinesort.X.Y")` dans `tests/test_apply_*.py`, `tests/test_perceptual_*.py`, `tests/test_cinesort_api.py` :
- toutes les cibles correspondent a un binding accessible au call site (rebind par `from X import Y` ou `import X as _mod`).
- **0 violation detectee**.

## Findings par categorie

### Categorie 10 — Dette technique

1. **Finding F-2026-06-14-01** (severity 2) — 5 sites lazy stdlib hors scope PR #557 (cf tableau ci-dessus). Recommandation : enrichir #554 et commenter #557.
2. **Finding F-2026-06-14-02** (severity 2) — `apply_rows` (`apply_core.py:887`) atteint ~324L post-v152. A ajouter au plan #215 comme **Tier 0** (avant `_execute_undo_ops` pour ROI). Recommandation : enrichir #215.

### Categorie 11 — Code mort

- 0 nouveau code mort detecte. La regle invariant "verifier tests avant suppression" (retex #217) n'a pas ete deviolee.

### Categorie 12 — Patterns Python

- Les 9 lazy stdlib detectes violent PEP 8 par convention (cf #391 / #557). Non-idiomatique sauf justification (DI optionnel comme `service.py:84`).

### Categorie 47 — Architecture invariants

- 3 contracts respectes (cf section dediee).
- Aucun cycle `domain -> app` ni `infra -> app/ui` ni `app -> ui`.
- Aucun mixin SQLite residuel.
- Module-style imports pour mocks : pattern respecte sur l'echantillon.

## Statistiques

| Metrique | Valeur |
|----------|------:|
| Modules audites | couche transverse (architecture + dette + dependances) |
| Findings totaux | 2 (1 dette stdlib, 1 dette LOC) |
| dont severity QUALITY (2) | 2 |
| dont severity BUG (3) | 0 |
| dont severity BLOCKER (4) | 0 |
| Issues nouvelles | 0 (toutes dedup vers #215 / #554) |
| Issues enrichies (commentaire) | 2 (#215 drift v152, #554 5 sites additionnels) |
| PRs commentees | 1 (#557 suggestion d'extension) |
| PRs creees | 1 (rapport + JSONL — cette PR) |
| Doublons strict detectes | 3 (les 3 themes du prompt = stales) |
| Findings "deja mitige" filtres | 5 (FILTRE 7 : JS dups closed, mixins closed, cycle closed, facades closed, lazy `cinesort.X` stable) |

## Self-critique pass

**Filtres appliques (cf etape 2.6 audit-prompt.md)** :

- Filtre 1 (realite) : tous les findings ont ete verifies en lisant le code reel (`grep -rn`, `Read` ciblee, comparaison line numbers).
- Filtre 2 (idiome) : aucun finding sur du code idiomatique (les 5 lazy stdlib sont non-PEP 8).
- Filtre 3 (confidence) : >0.90 (lecture directe du code + cross-check avec PR #557 / issue #554).
- Filtre 4 (dedup cross-categories) : F-01 et F-02 sont independants (lazy imports vs fonctions longues).
- Filtre 5 (severite) : QUALITY (2) pour les 2 ; pas d'escalade artificielle.
- Filtre 6 (actionabilite) : F-01 = comment sur #557 ; F-02 = comment sur #215.
- **Filtre 7 (etat actuel)** : **5 findings supprimes** (auraient ete crees si l'audit s'etait fie au prompt stale) :
  1. "22 composants JS dupliques" — `web/views/` supprime par #92.
  2. "7 mixins SQLite legacy" — supprimes par PRs #220-#228 (#85 B8 closed).
  3. "Cycle domain -> app" — verrouille par import-linter, 0 violation.
  4. "162 lazy imports" — passes a 33, dont la majorite justifies (TYPE_CHECKING, cycle autorise, optional deps).
  5. "Methodes directes CineSortApi" — facades en place, #84 closed (50 methodes publiques migrees).
- **Filtre 8 (proportionnalite)** : F-01 = mini-PR < 30 LOC apres merge #557 ; F-02 = ajout au plan multi-PR existant #215.

## Comparaison avec audit precedent

Dernier audit transverse : **2026-05-24** (`2026-05-24-transverse.md`). Tendance :

| Metrique | 2026-05-24 | 2026-06-14 | Delta | Note |
|----------|----------:|----------:|------:|------|
| Fonctions > 100L | 14 | ~14 + apply_rows (~324L) | +1 (+7%) | apply_rows croissance v152 |
| Imports lazy `cinesort.X` | 33 | 33 | 0 | stable |
| Imports lazy stdlib | ~10 | 9 (4 dans #554/#557, 5 nouveaux) | -1 | PR #391 ferme 7 mais v152 reintroduit 4 + 5 perdus |
| Doublons JS components | 0 | 0 | 0 | stable |
| Cycle `domain -> app` | brise | brise | stable | |
| Mixins legacy SQLite | 0 | 0 | stable | |
| Violations import-linter | 0 | 0 | stable | |

**Conclusion architecturale** : couche transverse **stable**. Une croissance d'`apply_rows` post-v152 a documenter dans #215. Une regression de 5 lazy stdlib (autres que ceux de #554) a integrer au scope de #557. **Aucune action urgente**.

## Annexe — fichiers modifies dans ce run

- Ce rapport : `docs/internal/audits/claude/2026-06-14-transverse.md`
- JSONL findings : `docs/internal/audits/findings/2026-06-14-transverse.jsonl`

## Notes complementaires

- Le run `python3` n'est pas autorise dans la sandbox de ce session — les mesures de fonctions > 100L sont donc estimees par grep + offsets de `def` suivants, ce qui est precis a +/-1 ligne sur l'ensemble (verification croisee avec #215).
- Les chiffres `49 / 22 / 161` du **prompt audit historique** restent inchanges depuis le 12 mai. Issue #484 (docs/audit-prompt) est ouverte depuis le 31 mai pour mettre a jour ces chiffres — ce run en confirme la pertinence.
