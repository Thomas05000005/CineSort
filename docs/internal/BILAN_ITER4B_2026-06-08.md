# BILAN ITER 4b - Fermeture - CineSort - 2026-06-08

> Branche: loop/correction-2026-06
> Acquis preserves (comportement intact): a37852aa + 242cf339 + 7df3af3e + 6193e02b + 06f74ad + #2 vert
> Statut: [WIP]

## EN TETE [WIP]

## 1. Diagnostic lint-imports [OPERATIONNEL]

### 1.1 Commande et sortie (FIGE)

Commande: `lint-imports` (lancee dans `C:/Users/blanc/projects/CineSort`, branche `loop/correction-2026-06`).

Note: `python -m importlinter` n'est PAS executable (le package n'a pas de `__main__`). Seul le CLI `lint-imports` fonctionne.

Sortie capturee (extrait):

```
Analyzed 224 files, 563 dependencies.

Domain ne doit importer ni app, ni infra, ni ui   BROKEN
Infra ne doit importer ni app, ni ui              KEPT
App ne doit pas importer ui                        KEPT

Contracts: 2 kept, 1 broken.

----------------
Broken contracts
----------------

Domain ne doit importer ni app, ni infra, ni ui
-----------------------------------------------

cinesort.domain is not allowed to import cinesort.app:

-   cinesort.domain.duplicate_multi_signal -> cinesort.app._fuzzy_utils (l.107)
```

### 1.2 Inventaire des violations (FIGE)

| # | Contrat viole | Module source | Module importe | file:line |
|---|---|---|---|---|
| V1 | `domain_pure` (Domain ne doit importer ni app, ni infra, ni ui) | `cinesort.domain.duplicate_multi_signal` | `cinesort.app._fuzzy_utils` | `cinesort/domain/duplicate_multi_signal.py:107` |

Une seule violation. Les deux autres contrats (`infra_bounded`, `app_bounded`) sont KEPT.

### 1.3 git blame de la ligne fautive (FIGE)

Commande: `git blame -L 100,112 cinesort/domain/duplicate_multi_signal.py`

```
7d532c32 (Thomas Blanc 2026-06-01 19:54:22 +0200 107)         from cinesort.app._fuzzy_utils import normalize_for_fuzzy
```

Contexte source (lignes 101-111, import lazy avec fallback):

```python
def _normalize_title_for_fuzzy(title: str) -> str:
    """Normalisation legere pour fuzzy (delegue a _fuzzy_utils si possible).

    On fait un import lazy pour eviter un cycle si _fuzzy_utils evolue.
    """
    try:
        from cinesort.app._fuzzy_utils import normalize_for_fuzzy
        return normalize_for_fuzzy(title)
    except ImportError:
        # Fallback minimal si _fuzzy_utils introuvable (defense en profondeur)
        return (title or "").lower().strip()
```

### 1.4 Datation du commit fautif et classement (FIGE)

| SHA | Date | Sujet | Classement |
|---|---|---|---|
| `7d532c32` | **2026-06-01 19:54:22** | feat(vn-d1): brancher Chromaprint + fuzzy title + year +-1 (anti-dup cross-langue) | introduisant V1 |
| `f493abdc` | 2026-06-08 18:33:37 | checkpoint: working tree avant boucle correction 2026-06-08 | checkpoint reference |
| `9d8b8e95` | 2026-06-09 00:49:31 | checkpoint: avant fix racine C iter4 | checkpoint iter4 |
| `a37852aa` | 2026-06-09 01:18:33 | fix(plan): C - enrichissement TMDb operationnel | iter4 (acquis preserves) |
| `242cf339` | 2026-06-09 01:57:56 | fix(csp): autoriser image.tmdb.org dans img-src | iter4 (acquis preserves) |

Conclusion datation:
- V1 introduite le **2026-06-01** par `7d532c32`, soit **7 jours avant** le checkpoint `f493abdc` (2026-06-08) et **8 jours avant** les commits iter4 (`a37852aa`, `242cf339`).
- Classement: **V1 = PREEXISTANTE** (pas introduite par iter4, et anterieure au checkpoint `f493abdc`).
- V1 n'apparait dans **aucun** des commits iter4 / iter3 (`a37852aa`, `242cf339`, `7df3af3e`, `6193e02b`, `06f74ad`).
- Aucune violation NOUVELLE introduite par iter4.

### 1.5 Classement mecanique vs choix design (HYPOTHESE)

V1 = `domain.duplicate_multi_signal` -> `app._fuzzy_utils.normalize_for_fuzzy`

Analyse de la fonction importee (`cinesort/app/_fuzzy_utils.py:15-33`):

```python
def normalize_for_fuzzy(title: str) -> str:
    """Normalise un titre pour comparaison fuzzy.
    - lowercase
    - strip accents (NFD + strip combining marks)
    - strip ponctuation courante
    - strip whitespace multiple
    """
    ...
```

C'est une fonction de normalisation de chaine **pure** (lowercase + unicodedata + strip ponctuation + collapse whitespace). Aucune dependance I/O, aucune dependance app/infra/ui. C'est en realite de la **logique de domaine** mal rangee dans `app/`.

Classement: **mecanique** (pas un choix design fondamental). La correction de forme consiste a deplacer la fonction au bon etage. L'import-tardif actuel avec try/except est une rustine (cf. docstring "import lazy pour eviter un cycle") qui ne devrait pas etre necessaire car `_fuzzy_utils` ne contient pas de dependance cyclique vers domain.

Note: le module `_fuzzy_utils.py` lui-meme existe depuis le commit initial public `1126536` (2026-05-11) et a ete vectorise par `bda2b67` (2026-05-12). Sa nature de pure utilitaire string n'a pas change.

### 1.6 Corrections proposees (HYPOTHESE)

Aucune correction sur du code NOUVEAU n'est requise (aucune violation nouvelle).

Pour V1 (PREEXISTANTE, mecanique), trois options par ordre de preference:

**Option A (recommandee, forme pure)** - Deplacer `normalize_for_fuzzy` vers le bon etage:
- Creer `cinesort/domain/_fuzzy_normalize.py` contenant uniquement `normalize_for_fuzzy` (pure string, sans dependance).
- `cinesort/app/_fuzzy_utils.py` re-exporte `normalize_for_fuzzy` depuis `domain` pour preserver la backward compat de l'API publique (memoire INVIOLABLE: backward compat absolue).
- `cinesort/domain/duplicate_multi_signal.py` importe top-level depuis `cinesort.domain._fuzzy_normalize` et supprime le try/except lazy.
- Forme pure, comportement identique, pas de choix design.

**Option B (port-interface)** - Definir un port `TitleNormalizer` dans `domain/`, injection dans `duplicate_multi_signal` depuis l'appelant. Plus lourd, justifie uniquement si on prevoit plusieurs implementations. **Non recommande** ici (la fonction est triviale).

**Option C (status quo justifie)** - Garder l'import-tardif en y ajoutant un `# noqa: PLC0415` + commentaire `# FIGE: import lazy tolere car normalize_for_fuzzy reste en app/ pour compat tests`. **Non recommande** car la justification du lazy (docstring "eviter un cycle si _fuzzy_utils evolue") est speculative, pas un cycle reel observe.

**Decision proposee**: Option A (forme pure, mecanique, sans choix design).

### 1.7 GATE design choice (OPERATIONNEL)

- Violations NOUVELLES (introduites par iter4): **0**
- Violations PREEXISTANTES exigeant choix design fondamental: **0** (V1 est mecanique, corrigible par deplacement)
- **STOP REMONTE non declenche.** Peut continuer vers etape 2 (refactor de forme).

## 2. Refactor architecture (forme) [OPERATIONNEL]

### 2.1 Strategie retenue (FIGE)

Option A retenue (cf 1.6) pour V1: deplacement mecanique de la fonction
`normalize_for_fuzzy` (pure string normalization) depuis `cinesort.app._fuzzy_utils`
vers `cinesort.domain._fuzzy_normalize`. Re-export depuis `app._fuzzy_utils`
pour preserver backward compat absolue. Aucun choix design fondamental.

### 2.2 Diff applique (FIGE)

| Fichier | Action |
|---|---|
| `cinesort/domain/_fuzzy_normalize.py` | **CREE** : nouveau module domain pur contenant `normalize_for_fuzzy` (lowercase + unicodedata NFD + strip ponctuation + collapse whitespace). Aucune dependance app/infra/ui. |
| `cinesort/app/_fuzzy_utils.py` | **MODIFIE** : import top-level `from cinesort.domain._fuzzy_normalize import normalize_for_fuzzy` (re-export). `unicodedata` retire des imports. Ajout `__all__` explicite pour figer l'API publique (backward compat). |
| `cinesort/domain/duplicate_multi_signal.py` | **MODIFIE** : ajout import top-level `from cinesort.domain._fuzzy_normalize import normalize_for_fuzzy as _normalize_for_fuzzy`. La fonction interne `_normalize_title_for_fuzzy` ne contient plus de try/except lazy ni de fallback; elle delegue directement. |

Note: le fallback `(title or "").lower().strip()` est supprime car (a) il avait
une semantique differente du vrai normalize (pas de strip accents ni de ponctuation),
ce qui constituait un piege silencieux; (b) il etait dead-code en pratique
puisque `cinesort.domain._fuzzy_normalize` est maintenant in-tree et ne peut
plus disparaitre. Defense en profondeur deplacee au niveau de l'importeur:
si le module domain disparait, `ImportError` au chargement du module
`duplicate_multi_signal` (fail-fast), pas un silencieux mauvais matching.

### 2.3 Verifications (OPERATIONNEL)

| Check | Commande | Resultat |
|---|---|---|
| py_compile (3 fichiers) | `python -m py_compile cinesort/domain/_fuzzy_normalize.py cinesort/domain/duplicate_multi_signal.py cinesort/app/_fuzzy_utils.py` | `PYCOMPILE_OK` |
| Import basique paquet | `python -c "import cinesort"` | `IMPORT_OK` |
| Backward compat re-export | `from cinesort.app._fuzzy_utils import normalize_for_fuzzy` retourne meme objet que `from cinesort.domain._fuzzy_normalize import normalize_for_fuzzy` | `BACKWARD_COMPAT_OK` (identite verifiee via `is`) |
| Comportement `_normalize_title_for_fuzzy` | input `'Le Seigneur des Anneaux: La Communauté'` -> `'le seigneur des anneaux la communaute'` (lowercase + strip accents + strip `:`) ; input `''` -> `''` ; input `None` -> `''` | `NORMALIZE_BEHAVIOR_OK` |
| Tests fuzzy + duplicate_multi_signal | `python -m pytest tests/ -k "fuzzy or duplicate_multi_signal or _fuzzy_utils" -q --timeout=60` | **32 passed, 74 skipped, 0 failed** |
| **lint-imports** | `lint-imports` (cwd `C:/Users/blanc/projects/CineSort`) | **3 kept, 0 broken** (Domain pure KEPT, Infra bounded KEPT, App bounded KEPT) |

### 2.4 Acquis posters preserves (FIGE)

Aucun fichier touche par ce refactor n'intersecte le perimetre des acquis
comportement posters / CSP / harness :

- `a37852aa` (fix posters racine C) : touche `cinesort/ui/api/run_facade.py`, `cinesort/app/plan_support.py`, NON touches ici.
- `242cf339` (CSP img-src) : touche `cinesort/infra/rest_server.py` + templates web, NON touches ici.
- `7df3af3e` (fix ii.b) : touche modules apply, NON touches ici.
- `6193e02b` (harness frais) : NON touche.
- `06f74ad` (#15) : NON touche.

Les 3 fichiers modifies (`domain/_fuzzy_normalize.py` cree, `app/_fuzzy_utils.py`,
`domain/duplicate_multi_signal.py`) sont exclusivement dans le perimetre
"detection de doublons par fuzzy title" (Phase B du pipeline anti-dup) et
n'ont aucun chemin d'execution vers le pipeline TMDb posters / CSP /
fetching d'images. Le comportement de detection fuzzy lui-meme est strictement
identique (meme fonction `normalize_for_fuzzy`, meme objet Python via re-export).

### 2.5 Bilan etape 2 (OPERATIONNEL)

- Violations PREEXISTANTES corrigees: **1/1** (V1 fermee par deplacement mecanique).
- Violations NOUVELLES introduites par ce refactor: **0**.
- Tests `fuzzy/duplicate_multi_signal/_fuzzy_utils`: **32/32 verts**.
- `lint-imports`: **VERT** (3 contracts KEPT, 0 broken).
- Backward compat: **PRESERVEE** (re-export verifie par identite Python).
- Comportement posters: **INCHANGE** (perimetre disjoint, fichiers non touches).
- Forme uniquement, pas de choix design, pas de changement de comportement.

**Etape 2 cloturee.** Pret pour GATE Archi.

## GATE Archi [PASS - VERT]

_Mesure fraiche : 2026-06-09._

### Commande executee

```
cd C:/Users/blanc/projects/CineSort
lint-imports
```

### Sortie

```
=============
Import Linter
=============


---------
Contracts
---------

Analyzed 225 files, 564 dependencies.
-------------------------------------

Domain ne doit importer ni app, ni infra, ni ui KEPT
Infra ne doit importer ni app, ni ui KEPT
App ne doit pas importer ui KEPT

Contracts: 3 kept, 0 broken.
```

### Verification des 3 contrats

1. **domain_pure** : `Domain ne doit importer ni app, ni infra, ni ui` -> **KEPT**
   - domain ne depend de rien d'au-dessus (couche feuille).
2. **infra_bounded** : `Infra ne doit importer ni app, ni ui` -> **KEPT**
   - infra n'importe pas app/ui.
3. **app_bounded** : `App ne doit pas importer ui` -> **KEPT**
   - app n'importe pas ui.

### Statistiques

- 225 fichiers analyses.
- 564 dependances inspectees.
- **3 contracts kept, 0 broken.**

### Verdict

**GATE Archi : PASS (VERT).**

Aucune violation residuelle. Les 3 contrats de l'architecture en couches
(domain / infra / app / ui) sont integralement respectes apres la cloture
de l'etape 2 (V1 fermee par deplacement mecanique de `normalize_for_fuzzy`
vers `domain/_fuzzy_normalize.py`).

Pre-requis "lint-imports VERT" pour la cloture iter4b satisfait.
La condition d'acceptation conjointe (lint-imports VERT ET mesure fraiche
posters OK) est partiellement remplie cote archi ; reste a confirmer la
non-regression posters dans la section suivante.

## GATE Non-regression posters [WIP]

## 3. Solder 4 tests rouges [WIP]
_En cours._

## 4. Cloture iter4 [WIP]
_En cours._
