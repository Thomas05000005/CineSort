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

## 2. Refactor architecture (forme) [WIP]
_En cours._

## GATE Archi [WIP]
## GATE Non-regression posters [WIP]

## 3. Solder 4 tests rouges [WIP]
_En cours._

## 4. Cloture iter4 [WIP]
_En cours._
