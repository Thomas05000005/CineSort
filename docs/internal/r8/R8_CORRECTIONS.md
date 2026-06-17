# R8 — JOURNAL DES CORRECTIONS (différentiel prouvé contre BASELINE_R8)

> **Régime** : on n'est plus en read-only. On corrige, **1 commit par finding**, chaque message portant le
> différentiel baseline en preuve. Branche `loop/correction-2026-06` ; checkpoint **`f493abdc`** = point de
> retour INTACT (non touché). **Pas de push** tant que F1+F2 ne sont pas clos et prouvés. Pas de `git stash`.
> Règle d'acceptation : un fix bascule une observation baseline « cassé→correct » **sans** régresser une autre.
> Registre source : [`../baseline_r8/BASELINE_R8.md`](../baseline_r8/BASELINE_R8.md). Artefacts : `./` (ce dossier).

---

## R8-081 — F-TEST-01 — Réparer l'instrument : assertion tautologique → vérification réelle
**Famille** : F6 (qualité de test / instrument) — corrigé **EN PREMIER** (avant F1) : tant qu'un test ment,
valider un fix sur un « vert » ne prouve rien. **Commit** : `<hash à compléter>` (loop/correction-2026-06).

### 1. Localisation + intention réelle
- **Fichier** : `tests/test_auto_install.py:35-37`, méthode `TestGetToolsDir.test_creates_dir`.
- **Assertion bidon (AVANT)** : `self.assertTrue(d.exists() or True)  # peut ne pas exister en CI`
  → `X or True` vaut **toujours** `True` (court-circuit Python) : `d.exists()` n'est **jamais** décisif.
  Le commentaire « peut ne pas exister en CI » est **faux** : `get_tools_dir()` crée toujours le dossier.
- **Intention réelle** (nom du test = `test_creates_dir`) : vérifier que `get_tools_dir()` **CRÉE** le dossier
  `tools/` qu'il retourne. **Contrat prouvé** : `cinesort/infra/probe/auto_install.py:162-170` — `get_tools_dir`
  fait `tools_dir.mkdir(exist_ok=True)` **puis** `return tools_dir` → après l'appel, le dossier DOIT exister
  (inconditionnellement, CI incluse).

### 2. Correction de l'assertion (test seul, pas le code de prod)
```diff
-        self.assertTrue(d.exists() or True)  # peut ne pas exister en CI
+        # get_tools_dir() fait tools_dir.mkdir(exist_ok=True) puis retourne :
+        # le dossier DOIT exister apres l'appel (cf auto_install.py:169).
+        self.assertTrue(d.exists(), "get_tools_dir() doit creer le dossier tools/")
```

### 3. Issue = **3a** (le test PASSE → comportement sous-jacent correct, test juste mal écrit)
Test corrigé lancé seul → **PASSED** (`tests/test_auto_install.py::TestGetToolsDir::test_creates_dir`).
Le `mkdir(exist_ok=True)` est bien présent en prod ; aucun bug masqué (pas d'issue 3b).

#### Preuve de FALSIFIABILITÉ (3 états) — le test teste VRAIMENT
**(a) Preuve « live »** (plant/revert de la vraie ligne `auto_install.py:169`, sur copie de travail, prod
restaurée byte-for-byte — `git diff` vide après revert) :
| État | Manip | Résultat |
|---|---|---|
| **1. vert honnête** | code de prod réel | `test_creates_dir` **PASSED** |
| **2. rouge sur bug planté** | `tools_dir = base/"tools_R8PLANT"` + `mkdir` commenté (nom frais car `tools/` existant masquerait un simple retrait de mkdir) | **FAILED** : `AssertionError: False is not true : get_tools_dir() doit creer le dossier tools/` |
| **3. vert après revert** | revert exact des 3 lignes | **PASSED** ; `git diff cinesort/infra/probe/auto_install.py` **vide** |

**(b) Preuve REJOUABLE sans éditer la prod** : `r8_081_falsifiability.py` (+ `.out.txt`) — monkeypatch de
`get_tools_dir` par une version buggée (pas de mkdir, chemin frais). Verdict figé :
`etat1_vert_honnete: PASS` · `etat2_rouge_sur_bug: RED OK (assertion levee)` · `etat3_vert_apres_revert: PASS`
→ **VERDICT : FALSIFIABLE PROUVÉE (vert/rouge/vert)**.

> Pourquoi un nom de dossier « frais » dans le plant : le dossier `tools/` existe déjà à la racine du dépôt,
> donc retirer seulement le `mkdir` laisserait `d.exists()==True` (le bug serait masqué). Le plant simule
> fidèlement « `get_tools_dir` ne crée pas le dossier qu'il retourne » = exactement le bug que le test doit attraper.

### 4. Balayage du pattern tautologique (borné — listé, NON corrigé ici)
Grep ciblé sur `tests/` (`or True`, `or 1`, `assert True`, `assertTrue(True)`, assertions à constante) :
| Occurrence | Verdict |
|---|---|
| `tests/test_auto_install.py:37` | **= R8-081, corrigé ci-dessus.** |
| `tests/test_rest_security.py:279` `self.assertTrue(True)` | **TAUTOLOGIE réelle** — `test_cors_configurable_explicit_still_emitted` est un **placeholder no-op** (docstring : « Couvert par `test_cors_can_be_restricted_explicitly` ci-dessous »). À traiter (candidat **R8-086** : supprimer le placeholder ou lui donner une vraie assertion). **Listé, non corrigé.** |
| `tests/test_phase4_parametres_endpoints.py:61` `int(... or 1)` | **FAUX POSITIF** : idiome de valeur par défaut dans un mock de setup, pas une assertion. |
| `tests/test_quality_score.py:393` `int(... or 1) + 1` | **FAUX POSITIF** : idem (default dans le setup). |

**Conclusion balayage** : le pattern tautologique est **quasi isolé** — **2 occurrences réelles** (R8-081 traité
+ 1 placeholder no-op à `test_rest_security.py:279`). Ce n'est **pas** une couture systématique de la couche test
(≠ les seams de prod). Le placeholder est trivial → proposé comme **R8-086** (F6), à traiter séparément.

### 5. Non-régression (suite complète, 6199 tests)
- **Baseline PRÉ-FIX** (`suite_baseline_prefix.txt`, 30 min) : **107 failed, 5813 passed, 183 skipped, 170 errors,
  230 subtests passed**. Échecs/erreurs pré-existants (majorité = `test_runtime_contrast_wcag` chromium/Playwright,
  env-dépendants — recoupe R8-076). **264 nœuds en échec/erreur** snapshotés dans `prefix_failures.txt` ;
  `test_auto_install` **absent** de cet ensemble (mon fichier était déjà vert).
- **POST-FIX** (`suite_postfix.txt`, 30 min) : **107 failed, 5813 passed, 183 skipped, 170 errors, 230 subtests
  passed** — **compteurs IDENTIQUES** au pré-fix.
- **Delta** (`postfix_failures.txt` vs `prefix_failures.txt`, `comm`) : **264 nœuds en échec/erreur des deux côtés** ;
  **NOUVEAUX échecs = ∅** (0), **disparus = ∅** (0) → ensemble byte-identique. `test_auto_install` **absent** des
  échecs post-fix (vert). ✅ **NON-RÉGRESSION OK : 0 nouvel échec.**

> Le changement est **isolé à une assertion** d'un seul test (qui passe) sans aucune dépendance partagée ni
> modification de prod → aucun autre test ne peut casser de ce fait. La comparaison de l'ensemble des nœuds en
> échec pré/post valide formellement la non-régression.

### Artefacts rejouables
- `r8_081_falsifiability.py` + `r8_081_falsifiability.out.txt` (preuve vert/rouge/vert sans edit prod).
- `suite_baseline_prefix.txt` (baseline pré-fix), `prefix_failures.txt` (264 nœuds pré-existants), `suite_postfix.txt`.
