# V2-02 — Refactor 4 fonctions complexité E (≥30)

**Branche** : `refactor/cyclomatic-e-functions`
**Worktree** : `.claude/worktrees/refactor-cyclomatic-e-functions/`
**Effort** : 2-3 jours
**Priorité** : 🔴 MAJEUR (audit ID-CODE-002)
**Fichiers concernés** :
- `cinesort/ui/api/quality_support.py`
- `cinesort/ui/api/run_flow_support.py`
- `cinesort/ui/api/run_data_support.py`
- tests existants à conserver verts (test_quality*, test_run_flow*, test_run_data*)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b refactor/cyclomatic-e-functions .claude/worktrees/refactor-cyclomatic-e-functions audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/refactor-cyclomatic-e-functions

pwd && git branch --show-current && git status
```

À partir de maintenant : tout dans ce worktree.

---

## RÈGLES GLOBALES

EXIGENCE QUALITÉ : recherche, lis, vérifie, teste, ruff. Zéro régression.
RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT les 3 fichiers source listés.

---

## CONTEXTE

L'audit a relevé 4 fonctions à complexité **E (≥30)** :

1. `analyze_quality_batch` — `cinesort/ui/api/quality_support.py:8` — **E=39**
2. `_build_analysis_summary` — `cinesort/ui/api/run_flow_support.py:24` — **E=32**
3. `_enrich_groups_with_quality_comparison` — `cinesort/ui/api/run_flow_support.py:781` — **E=32**
4. `row_from_json` — `cinesort/ui/api/run_data_support.py:48` — **D=29** (limite E)

Cible : viser complexité ≤ **C (15)** par fonction en extrayant des helpers.

---

## MISSION

### Étape 1 — Mesurer baseline

```bash
.venv313/Scripts/python.exe -m radon cc cinesort/ui/api/quality_support.py -s | head
.venv313/Scripts/python.exe -m radon cc cinesort/ui/api/run_flow_support.py -s | head
.venv313/Scripts/python.exe -m radon cc cinesort/ui/api/run_data_support.py -s | head
```

Note les valeurs actuelles.

### Étape 2 — Pour CHAQUE fonction

#### 2a. Lire le code

Identifie les blocs logiques (chaque branche `if/else` complexe, chaque traitement par
type, chaque section "etape X").

#### 2b. RECHERCHE WEB sur le pattern de refactor

WebSearch :
- "Strategy pattern Python dispatcher dict 2025"
- "Chain of Responsibility Python data pipeline"

Pour `analyze_quality_batch` qui dispatche selon le type de probe : peut-être un dict
de handlers `{type: handler_fn}` est plus propre que des `if elif elif`.

#### 2c. Extraire en helpers privés

Garde la signature publique inchangée. Extraits internes en `_helper_xxx`.

Exemples :
- `analyze_quality_batch(rows)` → `_collect_probes(rows)`, `_score_each(probes, profile)`,
  `_aggregate_warnings(scores)`, etc.
- `_build_analysis_summary(...)` → `_summarize_counts(...)`, `_summarize_durations(...)`,
  `_summarize_warnings(...)`
- `_enrich_groups_with_quality_comparison(...)` → `_load_quality_for_group(...)`,
  `_compare_pair(...)`, `_attach_comparison(...)`
- `row_from_json(...)` → `_parse_basic_fields(...)`, `_parse_subtitle_fields(...)`,
  `_parse_perceptual_fields(...)`, `_parse_v3_fields(...)`

#### 2d. Lance les tests existants

```bash
.venv313/Scripts/python.exe -m unittest tests.test_quality* tests.test_run_flow* tests.test_run_data* -v 2>&1 | tail -10
```

Capturer baseline. Refactor. Re-tester. **Zéro régression**.

#### 2e. Vérifie complexité après

```bash
.venv313/Scripts/python.exe -m radon cc <fichier> -s | grep <fonction>
```

Cible : ≤ C (15).

### Étape 3 — Vérifications globales

```bash
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5
.venv313/Scripts/python.exe -m ruff check . 2>&1 | tail -2
```

### Étape 4 — Commits

4-8 commits (1-2 par fonction refactorée) :
- `refactor(quality_support): extract helpers from analyze_quality_batch (E=39 → C)`
- `refactor(run_flow_support): split _build_analysis_summary (E=32 → C)`
- `refactor(run_flow_support): extract _enrich_groups helpers (E=32 → C)`
- `refactor(run_data_support): split row_from_json into typed parsers (D=29 → B)`

---

## LIVRABLES

Récap :
- 4 fonctions refactorées, complexité avant/après pour chaque
- Tests : 0 régression
- 4-8 commits sur `refactor/cyclomatic-e-functions`
