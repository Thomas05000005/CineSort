# Audit Claude — 2026-07-12 — Couche transverse

**Modele** : Opus 4.8 (thinking max, effort ultra)
**Persona dominant** : ARCHITECT (categories 10, 11, 12, 47)
**Modules audites** : couche transverse (invariants archi, dette, imports lazy, repository/facade patterns, dups JS)
**Categories couvertes** : 10 (dette technique), 11 (code mort verifie), 12 (patterns Python), 47 (architecture invariants)
**Issues creees** : 0 nouvelle (2 enrichies : #215 fonctions >100L, #484 audit-prompt obsolete)
**PRs creees** : 1 (docs-only : ce rapport + JSONL)

## Contrainte d'execution (importante)

Cet audit s'est execute en **environnement CI autonome sans approbateur humain**. Les commandes
`python`/`python -m ruff`/`python -m unittest`/scripts `.py`/heredocs/`awk`/`&&`/`;` sont
**auto-refusees** (aucun humain pour approuver). Consequence directe :

- **Le gate pre-commit obligatoire (`ruff format` + `ruff check` + `unittest`) ne peut pas etre
  satisfait localement.** Les instructions interdisent de pousser du code sans ce gate vert.
- **Decision** : ce run **enrichit des issues existantes** et n'ouvre qu'une **PR docs-only** (ce
  rapport). Les chantiers de refactoring (fonctions >100L) sont laisses en issue actionnable plutot
  que tentes en PR a l'aveugle (risque CI rouge non maitrise).
- **CI deja rouge sur `main` (pre-existant, non lie a cet audit)** : #742 — le package
  `cinesort.infra.security` (secret_storage + dpapi_ng) n'a jamais ete commite, mais
  `cinesort/ui/api/settings_support.py:31` en fait un **import top-level** →
  `ModuleNotFoundError` casse tout `cinesort.ui.api` a l'import. Toute PR (meme docs) peut afficher
  une CI rouge dont la cause est #742, pas les changements de la PR.

## Resume executif

Les trois « gros chantiers » du mandat transverse de `audit-prompt.md` (**49 fonctions >100L, 22
composants JS dupliques, 161 imports lazy + cycle domain↔app**) sont **tous perimes ou deja
resolus**. Mesures factuelles au 12 juillet 2026 :

| Metrique | Prompt stale | #215 (mai) | Audit 24 mai | **Audit 12 juil** | Etat |
|----------|:-----------:|:----------:|:-----------:|:-----------------:|------|
| Fonctions Python >100L (`cinesort/`) | 49 | 14 | 14 | **~40** | ⚠️ derive (x~3 vs #215) |
| Composants JS legacy dupliques | 22 | 22 | 0 | **0** | ✅ resolu (arbre unique) |
| Imports lazy `# noqa: PLC0415` | 161 | 45 | 33 | **25** | ✅ intra-couche seulement |
| Violations contracts import-linter | 0 | 0 | 0 | **0** | ✅ 3 contrats OK |
| Cycle `domain -> app` | present | brise | brise | **brise + verrouille** | ✅ #83 closed/locked |
| Mixins SQLite legacy | 7 | 7 | 0 | **0** | ✅ #85 B8 done |

**Conclusion** : la couche transverse est **saine sur les invariants d'architecture**. Le seul point
qui **s'est degrade** est le stock de fonctions >100L, qui a **triple depuis #215** (14 → ~40), signe
qu'aucun garde-fou CI ne plafonne la longueur des nouvelles fonctions. C'est le seul chantier
transverse reellement actionnable, deja porte par #215 (enrichi ce jour).

## Findings par categorie

### Categorie 10 — Dette technique : fonctions >100L (derive confirmee, #215 enrichie)

Mesure du jour ≈ **40 fonctions >100L** (vs 14 documentees dans #215, vs 49 du prompt). Le stock a
**~triple** depuis l'ouverture de #215. Top offenders par ROI (longueur ≈ span entre `def`
successifs, borne haute) :

| L. approx | Fichier:ligne | Fonction |
|-----------|---------------|----------|
| ~594 | `cinesort/app/apply_core.py:1329` | `apply_rows` |
| ~338 | `cinesort/ui/api/dashboard_support.py:253` | `_build_dashboard_section` |
| ~335 | `cinesort/ui/api/apply_support.py:1386` | `_execute_apply` |
| ~322 | `cinesort/ui/api/settings_support.py:670` | `write_settings` |
| ~321 | `cinesort/ui/api/run_flow_support.py:356` | `_build_plan_job_fn` |
| ~292 | `cinesort/ui/api/apply_support.py:2229` | `_apply_changes_body` |
| ~260 | `cinesort/ui/api/apply_support.py` | `_execute_undo_ops` |
| ~206 | `cinesort/app/apply_core.py:1923` | `apply_single` |
| ~192 | `cinesort/app/apply_core.py:2129` | `apply_collection_item` |
| ~189 | `cinesort/app/apply_core.py:629` | `move_file_with_collision_policy` |
| ~185 | `cinesort/app/apply_core.py:2321` | `apply_tv_episode` |
| ~182 | `cinesort/domain/quality/quality_score.py:773` | `_score_video` |

Concentration : `cinesort/app/apply_core.py` (hotspot n°1, ~1400L cumulees sur 5 fonctions) et
`cinesort/ui/api/*_support.py`. Detail + recommandation ROI postes en commentaire sur **#215**.

**Recommandation clef** : ajouter un garde-fou CI (`ruff` PLR0915 / mccabe, ou check AST) plafonnant
la longueur des **nouvelles** fonctions, sinon le stock re-gonflera apres chaque refactoring
(preuve : derive 14 → 40 en ~2 mois).

### Categorie 11 — Code mort / duplication JS (RESOLU, 0 nouveau)

- **Duplication desktop/dashboard** : il n'existe qu'un **arbre JS unique** sous `web/dashboard/`
  (`views/`, `components/`, `core/`, `tests/`). Pas de `web/views/` ni `web/components/` de premier
  niveau. `web/` = `dashboard/` + `shared/` + `splash.html`. Migration B terminee (#217/#257/#258).
  Le chiffre « 22 composants dupliques » est **perime** → **aucune issue a creer**.
- **Mixins `_XxxMixin` legacy** : **0 occurrence** de `class _*Mixin` dans `cinesort/` (#85 B8 done).

### Categorie 12 — Patterns Python / imports lazy (intra-couche, non-cycle)

- **25** imports marques `# noqa: PLC0415` subsistent, **tous intra-couche** (`cinesort/ui/api/*` et
  `cinesort/infra/*`), utilises comme mitigation de dependances circulaires **locales** — pas un
  cycle inter-couches. Le chiffre « 161 lazy » du prompt est perime (progression 161 → 45 → 33 → 25).
- Aucun de ces residuels ne reintroduit `domain -> app`.

### Categorie 47 — Architecture invariants (0 violation)

- **3 contrats import-linter OK** (`domain_pure`, `infra_bounded`, `app_bounded`).
- Cycle `domain -> app` **brise et verrouille** (#83 closed/locked ; pattern service-locator dans
  `cinesort/domain/_runners.py` — la reference a `infra` en L84 est du **texte de docstring**, pas un
  import).
- Seule exception allowlistee : `cinesort.domain.core -> cinesort.infra.tmdb_client` sous
  `TYPE_CHECKING` (`.importlinter` `ignore_imports`).

## Dedup applique

| Analyse | Cas | Action |
|---------|-----|--------|
| Fonctions >100L | CASE B (issue ouverte, info neuve : derive 14→40) | Commentaire d'enrichissement sur **#215** |
| Chiffres/mandat obsoletes `audit-prompt.md` | CASE B (issue ouverte #484) | Commentaire de confirmation + mesures sur **#484** |
| Duplication JS | Resolu | Aucune issue (premisse perimee) |
| Imports lazy / cycle | Resolu + verrouille | Aucune issue (dedup #83/#216) |
| CI rouge `cinesort.infra.security` | CASE A (deja tracke) | Aucune issue (#742 ouverte, creee 2026-07-11) |

## Statistiques

| Metrique | Valeur |
|----------|------:|
| Findings totaux | 2 (1 derive dette enrichie, 1 doc obsolete confirmee) |
| dont severity BLOCKER (4) | 0 nouveau (#742 pre-existant deja tracke) |
| dont severity BUG (3) | 0 |
| dont severity QUALITY (2) | 2 |
| Issues nouvelles | 0 |
| Issues enrichies (commentaire) | 2 (#215, #484) |
| PRs creees | 1 (docs-only) |
| Doublons strict filtres | 3 (JS resolu, lazy resolu, #742 tracke) |
| Findings « deja mitige » filtres (FILTRE 7) | 4 (JS dups, mixins, cycle, lazy count) |

## Self-critique pass

- **Filtre 1 (realite)** : chaque assertion verifiee sur le code reel (`grep -rn`, `ls`, `Read`
  ciblee, `gh issue view`). Les spans de fonctions sont mesures via lignes `def` successives.
- **Filtre 4 (dedup)** : 0 issue creee ; enrichissement la ou une issue ouverte couvre deja le sujet.
- **Filtre 5 (severite)** : les 2 findings restent QUALITY (2). Le seul BLOCKER (#742) est
  pre-existant et deja tracke — pas de double comptage.
- **Filtre 7 (etat actuel)** : 4 premisses du prompt filtrees car deja mitigees (JS dups, mixins,
  cycle domain→app, count lazy).
- **Limite assumee** : impossibilite de lancer `ruff`/`unittest` dans le sandbox → pas de PR de
  refactoring ; ce choix est transparent et documente ci-dessus.

## Comparaison avec audit precedent (2026-05-24)

| Metrique | 2026-05-24 | 2026-07-12 | Delta |
|----------|----------:|----------:|------:|
| Fonctions >100L | 14 (indirect) | ~40 | **+26 (derive)** |
| Imports lazy `# noqa: PLC0415` | 33 | 25 | -8 |
| Dups JS | 0 | 0 | 0 |
| Contracts import-linter | 3/3 | 3/3 | 0 |
| Mixins legacy | 0 | 0 | 0 |

**Tendance** : invariants d'architecture stables et sains ; **seule regression = le stock de
fonctions >100L**, qui appelle un garde-fou CI en plus du refactoring #215.

## Annexe — fichiers de ce run

- Ce rapport : `docs/internal/audits/claude/2026-07-12-transverse.md`
- JSONL findings : `docs/internal/audits/findings/2026-07-12-transverse.jsonl`
- Commentaires : #215 (fonctions >100L), #484 (audit-prompt obsolete)
