# Audit Claude — 2026-05-31 — Couche transverse

**Modele** : Opus 4.7
**Persona dominant** : ARCHITECT (categorie 47 + 10 + 12)
**Modules audites** : couche transverse (architecture invariants, dette, lazy imports, repository pattern, facades, docstrings, alignement doc/code)
**Categories couvertes** : 10 (dette technique), 11 (code mort verifie), 47 (architecture invariants)
**Issues creees** : 3 nouvelles (#483, #484, #485), 1 enrichie (#215)
**PRs creees** : #482 (cleanup docstrings B8), #486 (rapport + JSONL — cette PR)

## Resume executif

L'audit transverse precedent (2026-05-24, [docs/internal/audits/claude/2026-05-24-transverse.md](2026-05-24-transverse.md)) avait conclu que la couche transverse etait en etat sain et que les 3 chantiers historiques (49 fonctions > 100L, 22 JS dups, 161 lazy imports) etaient essentiellement clos. Sept jours plus tard, le constat est identique mais avec deux ecarts a documenter :

| Metrique | 17 mai | 24 mai | **31 mai** | Delta vs 24 mai |
|----------|:------:|:------:|:----------:|:---------------:|
| Fonctions Python > 100L (cinesort/) | 14 | 14 | **~18** | **+4** ⚠ |
| Imports lazy `cinesort.X` + stdlib | 45 | 33 | **~71** (recompte inclusif) | recompte differentiel |
| Composants JS legacy dupliques | 22 | 0 | **0** | 0 |
| Violations contracts import-linter | 0 | 0 | **0** | 0 |
| Mixins SQLite legacy (#85 B8) actifs | 7 | 0 | **0** | 0 |
| Methodes publiques directes sur CineSortApi | 5 | 5 | **5** | 0 |
| **Facades** | 5 | 5 | **6** (ajout `runtime`) | +1 |
| Docstrings repositories obsoletes (post-B8) | 7 | 7 | **7** -> PR #482 | -7 (en cours) |

**Conclusions** :

1. **Re-augmentation legere des fonctions > 100L** : 14 -> ~18. Les hot-paths apply absorbent de nouvelles fonctions qui ont franchi le seuil (`_execute_apply` apply_support.py:1101, **244L** ; `_build_dashboard_section` dashboard_support.py:186, **219L** ; `get_global_stats` dashboard_support.py:1241, **175L**). Issue #215 enrichie en commentaire (CAS B), pas de nouvelle issue.

2. **Sept docstrings de Repositories obsoletes** : phase B8 CLOSED depuis 2 semaines mais les en-tetes de `cinesort/infra/db/repositories/*.py` parlent encore de "thin wrapper backward-compat" et "Phase B8 future". **PR #482 deja ouverte** (pure cleanup docstring, 7 fichiers, +59/-49).

3. **Cinq methodes publiques residuelles sur CineSortApi** : `open_path`, `test_reset`, `log_api_exception` (+ `log` et `progress` qui sont en realite sur `RunState`, helper interne). Le pattern Strangler Fig (#84) merite une finalisation. **Issue #483 creee** avec plan multi-PR.

4. **Aucun garde-fou anti-regression du pattern Facade** : un dev future peut ajouter une nouvelle methode directe sur CineSortApi sans qu'aucun test n'echoue. **Issue #485 creee** avec proposition d'un test invariant simple.

5. **Documentation audit-prompt.md desynchronisee** : noms de contracts (`infra_no_upstream` vs reel `infra_bounded`), nombre de facades (5 vs 6 reels), compteurs ligne 1407 (49/22/161 vs ~18/0/71). **Issue #484 creee**.

## Findings par categorie

### Categorie 10 — Dette technique

**#1 (PR #482 — fix immediat)** : 7 docstrings d'en-tete des Repositories parlent de mixins legacy supprimes. Lieu : `cinesort/infra/db/repositories/{probe,anomaly,scan,perceptual,quality,run,apply}.py`. Source de verite : `cinesort/infra/db/sqlite_store.py:562-601` qui declare explicitement "phase B8 COMPLETE (B8a -> B8g)". Persona ARCHITECT, severite QUALITY (2), confiance 0.95.

**#2 (issue #215 enrichie)** : fonctions > 100L. Re-comptage par grep sur les hot-paths apply/dashboard. Nouvelles entrees :
- `cinesort/ui/api/apply_support.py:1101 _execute_apply` ~244L (nouveau record absolu)
- `cinesort/ui/api/dashboard_support.py:186 _build_dashboard_section` ~219L
- `cinesort/ui/api/dashboard_support.py:1241 get_global_stats` ~175L
- `cinesort/app/plan_support.py:1359 _build_resolved_row` ~122L
- `cinesort/app/plan_support.py:555 _classify_and_plan_folder` ~104L

Le tier 1 historique reste prioritaire. Commentaire poste sur #215 (CAS B - enrichissement), pas de nouvelle issue.

**#3 (issue #483)** : 5 methodes publiques directes sur `CineSortApi`. Le pattern Strangler Fig (#84) n'est pas tout a fait acheve : `api.open_path()` et `api.test_reset()` meritent de migrer sur `api.runtime`. Plan multi-PR documente (< 100 LOC + tests par PR).

**#4 (issue #484)** : `.github/audit-prompt.md` desynchronise du reel. Noms de contracts import-linter incorrects, compteurs ligne 1407 stales, mention de "5 facades" et "mixins legacy coexistent" obsoletes. Faible ROI fonctionnel, haut ROI sur la qualite des futurs runs d'audit (evite hallucinations).

### Categorie 11 — Code mort (verifie, 0 nouveau)

- `web/ui/` : confirme **deja supprime** (la verification du 24 mai etait correcte).
- `web/views/` : confirme **deja supprime**.
- `_XxxMixin` : confirme **deja supprime** dans le code actif (`grep -rln '_ProbeMixin\\|_ApplyMixin\\|_QualityMixin\\|_PerceptualMixin\\|_RunMixin\\|_ScanMixin\\|_AnomalyMixin' cinesort/` ne trouve que des **commentaires** dans `cinesort/infra/db/repositories/*.py` — d'ou PR #482).
- 2 tests (`tests/test_home_v5.py`, `tests/test_perceptual_infra.py`) mentionnent encore `Mixin` en string : a verifier dans une session ulterieure que c'est un commentaire de contexte historique, pas un usage actif.

### Categorie 47 — Architecture invariants

Verifications a 2026-05-31 :

```
grep -rnE "from cinesort\.(app|infra|ui)" cinesort/domain/  | grep -v TYPE_CHECKING
# -> 0 violation
grep -rnE "from cinesort\.(app|ui)" cinesort/infra/         | grep -v TYPE_CHECKING
# -> 0 violation
grep -rnE "from cinesort\.ui" cinesort/app/                  | grep -v TYPE_CHECKING
# -> 0 violation
```

Aucune violation des 3 contracts (`domain_pure`, `infra_bounded`, `app_bounded`).

**Risque structurel detecte (issue #485)** : pas de test invariant qui empeche un dev futur d'ajouter une nouvelle methode publique directe sur CineSortApi. Le pattern Strangler Fig n'a aucun garde-fou automatise — il repose uniquement sur la vigilance des audits manuels. Proposition : ajouter `tests/test_architecture_invariants.py::test_cinesortapi_no_new_public_methods` (~50 LOC).

### Categorie 12 — Patterns Python (lazy imports)

Re-comptage detaille au 2026-05-31 (grep sur indents 4, 8, 12) :

| Categorie | Compte | Exemple |
|-----------|:------:|---------|
| `cinesort/app/cleanup.py` — cycle accepte | 3 | `from cinesort.app.apply_core import record_apply_op` |
| 3rd party conditional (PIL, onnxruntime) | ~6 | `from PIL import Image` |
| Stdlib (base64, io, subprocess, sys, datetime, contextlib) | ~30 | `cinesort/ui/api/perceptual_support.py:822 import base64` |
| Intra-package `cinesort.ui.api.X` | ~15 | `cinesort/ui/api/library_audit_support.py:65 from cinesort.ui.api import library_support` |
| Cross-couche legitime (ui -> app/infra) | ~17 | `cinesort/ui/api/library_actions_support.py:285 from cinesort.app.plan_support import ...` |
| **Total** | **~71** | |

L'inventaire du 24 mai mentionnait 33 (en excluant stdlib). Le delta n'est pas une vraie regression mais un changement de scope du comptage. Aucune nouvelle violation cross-couche detectee. **Pas de nouvelle issue** : le sujet est deja couvert par #216 (CLOSED) et continuer a chasser des stdlib lazy un par un est peu ROI.

## Statistiques

- **Modules audites** : couche transverse complete (architecture, dette, lazy imports, repositories, facades, docstrings, alignement docs)
- **Findings totaux** : 5 (4 high-confidence + 1 deferred mention)
  - HIGH-CONFIDENCE : 4 (PR #482, #483, #484, #485)
  - ENRICHISSEMENT : 1 (commentaire sur #215)
- **Issues creees** : 3 nouvelles + 1 enrichie
- **PRs creees** : 1 (#482) + cette PR (#486)
- **Findings deja connus (dedup)** : couverts par #215, #216, #217, #83, #85

## Self-critique

Application des filtres ETAPE 2.6 :

- **FILTRE 1 (REALITE)** : tous les findings ont ete verifies par grep + lecture de code reel.
- **FILTRE 2 (IDIOME)** : aucun finding sur un pattern idiomatique.
- **FILTRE 3 (CONFIDENCE)** : tous les findings retenus sont >= 0.85.
- **FILTRE 4 (DEDUP)** : un finding initial sur "mock pattern" a ete supprime (faux positif de l'agent Explore qui confondait `patch("X.ClassName.method")` avec `patch("X.imported_name")`).
- **FILTRE 5 (SEVERITE)** : tous calibre QUALITY (2), aucun BLOCKER ou BUG severity.
- **FILTRE 6 (ACTIONABILITE)** : chaque finding a un fix concret (PR ou plan multi-PR documente).
- **FILTRE 7 (ETAT ACTUEL)** : verifie qu'aucune mitigation deja en place. Notamment : la categorie 47 est entierement verrouillee par import-linter ; le seul "trou" est l'absence de test sur le pattern Facade (d'ou #485).
- **FILTRE 8 (PROPORTIONNALITE)** : #483 a un plan multi-PR de 3 etapes pilotees (~100 LOC chacune).

**Findings supprimes** : 1 (mock pattern faux positif).

## Tendance vs audit precedent

- Sante architecturale stable : aucune regression de contract, aucun cycle reintroduit, mixins toujours absents.
- **Mais** : la dette > 100L progresse legerement (apply_support.py et dashboard_support.py absorbent des fonctions qui depassent le seuil). Suggere un effort sur le tier 1 de #215 (en particulier `_execute_apply` apply_support.py:1101 qui devient le nouveau record absolu a 244L).
- Decouverte d'un sujet "polish documentation" non vu precedemment : 7 docstrings de Repositories + 1 audit-prompt.md desynchronises. PR #482 + issue #484 traitent ces deux points.

## Actions creees

| Action | Type | Lieu | Statut |
|--------|------|------|--------|
| PR #482 | docs cleanup | repositories | Ouverte |
| Issue #215 | enrichissement (CAS B) | refactor transverse | Commentee |
| Issue #483 | nouvelle | facade-isation CineSortApi | Ouverte |
| Issue #484 | nouvelle | audit-prompt.md desync | Ouverte |
| Issue #485 | nouvelle | test invariant Facade | Ouverte |
| PR #486 | nouvelle | ce rapport + JSONL | Ouverte |
