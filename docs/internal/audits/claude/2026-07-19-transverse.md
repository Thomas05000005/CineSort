# Audit Claude — 2026-07-19 — Couche transverse

**Modele** : Opus 4.8 (effort ultra, thinking max)
**Persona dominant** : ARCHITECT (categorie 47 + 10 + 12)
**Modules audites** : couche transverse (invariants architecture, dette, imports lazy, fonctions > 100L, repository pattern, dups JS)
**Categories couvertes** : 10 (dette technique), 11 (code mort verifie), 12 (patterns Python), 47 (architecture invariants)
**Issues creees** : 1 nouvelle (#779) + 2 enrichies (#215, #677)
**PRs creees** : #778 (garde-fou anti-regression taille des fonctions, Closes #677)

## Resume executif

Les 3 "gros chantiers" heritees du prompt audit transverse (49 fonctions > 100L, 22 composants JS dupliques, 161 imports lazy avec cycle `domain <-> app`) sont **tous perimes ou resolus** au 2026-07-19. Mesures AST factuelles ce jour :

| Metrique | Prompt stale | Mesure 2026-07-19 | Statut |
|----------|:-----------:|:-----------------:|--------|
| Fonctions Python > 100L (cinesort/) | 49 | **117** | ⚠️ drift a la hausse (#215/#677) |
| Imports lazy `cinesort.*` (dans fonctions) | 161 | **111** | dont 89 intra-`ui/api` (#779) |
| Imports lazy `domain -> app` | "cycle a casser" | **0** | resolu #83, verrouille import-linter |
| Composants JS legacy dupliques | 22 | **0** | resolu #217 (web/views supprime) |
| Violations contracts import-linter | 0 | **0** | 3 contracts respectes |
| Mixins SQLite legacy | 7 | **0** | #85 B8 closed |

**Conclusion** : la premisse historique du prompt (cycle `domain <-> app` via imports lazy) est **caduque**. Le vrai reliquat transverse est double :
1. **Fonctions > 100L** : le compte a *augmente* de 49 → 117 depuis le budget d'origine. Concentre sur hot-path `apply_*`. Un garde-fou CI anti-regression est desormais en place (**PR #778**).
2. **Imports lazy intra-`ui/api`** : 89 des 111 imports lazy internes sont des cycles *intra-couche* entre modules `*_support` (sequelle du decoupage god-class #84), pas des violations de couche. Nouvelle issue dediee (**#779**).

## Findings par categorie

### Categorie 10 — Dette technique (2 findings actionnable)

1. **#677 (garde-fou) → PR #778** — Il n'existait aucune barriere CI empechant l'ajout de nouvelles fonctions > 100L. Le compte a derive de 49 (prompt) a **117** aujourd'hui. **PR #778** implemente l'Option B de #677 : `tests/test_function_size_budget.py` avec `MAX_LINES=100`, une ALLOWLIST gelee des 117 offenders existants, et 2 tests :
   - `test_no_new_oversized_function` : echoue si un `(fichier, fonction)` hors allowlist depasse 100L.
   - `test_allowlist_has_no_stale_entries` : echoue si une entree allowlist n'est plus oversized (force le nettoyage a chaque refactor). Effet cliquet : le compte ne peut que baisser.
   - Test-only, refactor 0, aucune modif de code prod. Closes #677.

2. **#215 (enrichie)** — Inventaire AST complet regenere : **117 fonctions > 100L** (vs 14 relevees le 24 mai — l'ecart s'explique par le seuil de mesure et la croissance du code apres la campagne verif-totale de juillet). Top concentration sur `apply_support.py`, `apply_core.py`, `plan_support.py`. Plan multi-PR de #215 toujours actionnable. Commentaire d'enrichissement poste avec l'inventaire complet + le pointeur vers le garde-fou #778.

### Categorie 12 — Patterns Python / architecture des modules (1 finding → #779)

- **#779 (nouvelle)** — 89 imports lazy `cinesort.*` sont *intra-`ui/api`*, sequelle du decoupage de la god-class `CineSortApi` (#84) en modules `*_support`, dont l'enchevetrement de dependances circulaires a ete resolu ponctuellement par des imports deplaces dans les corps de fonctions. 5 clusters de cycles identifies (voir issue). Ce n'est **pas** une violation de couche (tout est dans `ui/api`), mais une dette structurelle : cout de demarrage disperse, signal d'acyclicite absente du graphe de modules. Strategie proposee "extraire les feuilles partagees" (multi-PR, FILTRE 8) : PR pilote = extraire `_get_store` vers `ui/api/_store_access.py` (casse le cluster no.2 a lui seul). Label `needs-discussion` suggere (valider l'approche vs priorite #215).

### Categorie 47 — Architecture invariants (verifie, 0 violation)

`grep -rnE "from cinesort\.(app|infra|ui)" cinesort/domain/` :
- `cinesort/domain/core.py` — `from cinesort.infra.tmdb_client import TmdbClient` sous `if TYPE_CHECKING:` ✓ (allowed par `.importlinter`)
- `cinesort/domain/_runners.py` — occurrence dans une **docstring**, pas un vrai import ✓

Mesure AST du 2026-07-19 : **0** import lazy `domain -> app`. Les 3 imports lazy residuels dans `domain/` sont tous **intra-domaine** (`duplicate_multi_signal` → `perceptual.audio_fingerprint`, `naming` → `title_helpers`, `perceptual.audio_fingerprint` → `_runners`). **La premisse "casser le cycle domain <-> app" du prompt est perimee** (#83 closed, verrouille par CI).

`grep -rnE "from cinesort\.(app|ui)" cinesort/infra/` : 0 hit ✓
`grep -rnE "from cinesort\.ui" cinesort/app/` : 0 hit ✓
**3 contracts import-linter respectes.**

### Categorie 11 — Code mort / dups JS (verifie, 0 nouveau)

- **22 composants JS dupliques** : premisse perimee. `web/views/` legacy supprime (#217/#92 closed). Il n'existe pas de frontend desktop distinct du dashboard. Aucune issue a (re)creer — respect de la cloture #91/#217 et de l'avertissement d'incident du prompt.
- `_XxxMixin` legacy SQLite : deja supprimes (#85 B8). `class SQLiteStore(_StoreBase)` (single base) confirme.

## Repartition des imports lazy internes (mesure AST 2026-07-19)

| Categorie | Nb |
|-----------|---:|
| Total lazy (stdlib + internes) | 166 |
| Internes `cinesort.*` | 111 |
| dont **`ui/api` (intra-couche)** | **89** |
| `app` | 13 |
| `infra` | 3 |
| `domain` (intra-domaine) | 3 |
| `__init__` (wiring DI, justifie) | 3 |

## Statistiques

| Metrique | Valeur |
|----------|------:|
| Findings totaux | 4 (2 dette, 1 architecture modules, 1 verif clean) |
| dont severity QUALITY (2) | 4 |
| dont severity BUG (3) | 0 |
| dont severity BLOCKER (4) | 0 |
| Issues nouvelles | 1 (#779) |
| Issues enrichies (commentaire) | 2 (#215, #677) |
| PRs creees | 1 (#778) |
| Doublons strict detectes | 0 |
| Findings "deja mitige" filtres (FILTRE 7) | 3 (cycle domain->app, dups JS, mixins) |

## Self-critique pass

**Filtres appliques (cf etape 2.6 audit-prompt.md)** :
- Filtre 1 (realite) : tous les findings verifies via walk AST reel (`_audit_lazy.py`, `_audit_gen_guard.py`) + `grep -rn` + `Read` ciblee.
- Filtre 2 (idiome) : les imports lazy intra-`ui/api` sont non-idiomatiques (deplaces pour casser des cycles, pas par choix PEP 8).
- Filtre 3 (confidence) : tous >0.85 (mesures AST factuelles).
- Filtre 4 (dedup) : #779 distinct de #83 (domain/app, hors sujet), #216 (45 lazy), #554/#595 (regressions stdlib ponctuelles). Angle neuf = graphe de modules internes `ui/api`.
- Filtre 5 (severite) : tous QUALITY (2), aucune escalade artificielle.
- Filtre 6 (actionabilite) : #778 = PR concrete ; #779 = plan multi-PR documente avec PR pilote nommee ; #215 = plan existant.
- **Filtre 7 (etat actuel)** : **3 findings supprimes** car deja mitiges — cycle `domain->app` (0 mesure, verrouille), 22 dups JS (web/views supprime), 7 mixins (B8 closed).
- **Filtre 8 (proportionnalite)** : PR #778 test-only (0 LOC prod). #779 decoupe en PRs < 300 LOC, refactor pur.

## Correction des premisses du prompt (important)

Le prompt audit transverse (audit-prompt.md L1407) demande 3 livrables dont deux reposent sur des **premisses perimees** :
1. "49 fonctions > 100L" → en realite **117** aujourd'hui (drift a la hausse, pas a la baisse). Traite via #215 (enrichie) + garde-fou #778.
2. "22 composants JS dupliques desktop/dashboard" → **0** (pas de frontend desktop, web/views supprime #217). Aucune issue creee.
3. "161 lazy imports + cycle domain <-> app a decoupler" → cycle `domain <-> app` **inexistant** (0 mesure). Le vrai reliquat = 89 lazy intra-`ui/api` → issue **#779** (reframe).

## Annexe — artefacts de ce run

- PR #778 : `tests/test_function_size_budget.py` (garde-fou, Closes #677)
- Issue #779 : `refactor(ui-api)` 89 lazy imports intra-couche (cycles `*_support`)
- Enrichissements : commentaires sur #215 (inventaire 117 fonctions) + #677 (drift confirme)
- Ce rapport : `docs/internal/audits/claude/2026-07-19-transverse.md`
- JSONL findings : `docs/internal/audits/findings/2026-07-19-transverse.jsonl`
