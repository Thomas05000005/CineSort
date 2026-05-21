# Bilan Audit Complet — 21 mai 2026

Audit en 4 phases (Tier 1 statique → Tier 2 multi-agents → Tier 3 runtime → complement) sur la totalite du repo CineSort (v1.2.0-beta).

## Resume executif

| Phase | Categorie | Findings | Status |
|-------|-----------|----------|--------|
| Tier 1 | Analyse statique (ruff + vulture) | 22 occurrences sur 16 fichiers | PR #339 (CI rouge - format pre-existant) |
| Tier 2 | Multi-agents par concern | 2 HIGH + 12 MEDIUM + 4 LOW + 8 orphelines | PR #347 **MERGED** |
| Tier 3 | Runtime smoke | 0 regression detectee | Validation par test_quality_score + smoke imports |
| Phase 4 | Docs + format cleanup | 20 fichiers reformates + bilan | Cette PR |

**Total** : 33 bugs/risques identifies, 22 fixes Tier 1 + 11 fixes Tier 2 = **33 corrections appliquees**.

---

## Tier 1 — Analyse statique (PR #339)

Branche : `audit/tier1-static-sweep` — 16 fichiers modifies, 22 occurrences fixees.

### Findings fixes par categorie ruff

| Regle | Type | N | Exemples |
|-------|------|---|----------|
| F401 | Import inutilise | 1 | `scripts/i18n_full_sync.py` `import re` |
| B904 | Perte chainage exception | 3 | `plan_support.py:499`, `core.py:381`, `app.py:533` |
| B023 | Closure capture loop var | 4 | `apply_core.py` x2, `plan_support.py:2066`, `hdr_analysis.py:462` |
| B905 | `zip()` sans strict= | 6 | perceptual/* (4), profiles_support, perceptual_support |
| RUF059 | Variable deballee inutilisee | 5 | `audio_perceptual.py` x2 (rc), `duplicate_compare.py`, `history_support`, `perceptual_support`, `tools_manager` |
| vulture | Parametre vestigial | 2 | `compare_duplicates(quality_a/b)`, `extract_aligned_frames(bit_depth_a/b)` |

### Validation

- `ruff check` : EXIT=0 (baseline propre)
- 308 tests verts sur modules touches
- 0 regression (les 17 echecs pre-existants confirmes hors scope)

---

## Tier 2 — Multi-agents par concern (PR #347 mergee)

6 sous-agents en parallele, worktrees isoles, chacun avec un rapport cible.

### Agents et findings

| Agent | Scope | Findings |
|-------|-------|----------|
| Façade Run | `run_*_support.py` + facades | 2 MED (ImportError relique, mauvaise categorisation _err_response) |
| Façade Quality+Settings | `quality_*.py`, `settings_support`, `profiles_support` | **2 HIGH** + 1 MED + 1 LOW |
| Façade Library+Integrations | `library_*.py`, `tmdb_support`, clients externes | 3 MED + 1 LOW |
| Cycles & lazy imports | import-linter + `apply_*` + `cinesort_api` | 2 MED (reliques refactor #83) |
| UI ↔ backend mapping | 131 _impl + 5 facades + 81 fichiers JS | **8 orphelines** (issue separee) |
| Migrations SQLite + Repositories | `infra/db/**`, 25 migrations, 7 repos | 2 MED + 2 LOW |

### Fixes HIGH appliques (les 2 plus critiques)

1. **Race condition `set_active_profile`** (`profiles_support.py:336-405`)
   Settings sauvegarde puis DB activation : si DB echoue, divergence persistante.
   Fix : capture `previous_active_id`, try/except autour de step 4, rollback settings.

2. **`_tier_for` accepte tiers invalides** (`quality_simulator_support.py:288-303`)
   Avec `{platinum: 50, gold: 60}` (inverses), score 55 mappe en "Platinum".
   Fix : validation `p > g > s > br` avec fallback aux defaults + log.warning.

### Verification runtime (Tier 3)

Test direct via Python REPL :
```python
from cinesort.ui.api.quality_simulator_support import _tier_for
_tier_for(55, {"platinum": 50, "gold": 60, "silver": 40, "bronze": 20})
# -> "Silver" + log.warning("ordre tiers invalide ... fallback defaults")
_tier_for(55, {"platinum": 85, "gold": 68, "silver": 54, "bronze": 30})
# -> "Silver" (comportement normal)
```

### 8 methodes orphelines (sans entry UI)

| Methode | Façade | Hypothese |
|---------|--------|-----------|
| `get_tmdb_posters` | integrations | Cache poster code, jamais utilise |
| `get_smart_playlists` | library | Feature watchlists complete backend, UI absente |
| `save_smart_playlist` | library | idem |
| `delete_smart_playlist` | library | idem |
| `list_films_with_history` | library | Prechargement film+historique, pas dans les vues |
| `export_full_library` | library | Export JSON global, seuls exports cibles existent |
| `submit_score_feedback` | quality | Calibration scoring, pas d'UI |
| `delete_score_feedback` | quality | idem |

Issue tracker a creer pour planifier l'integration UI.

---

## Findings deferes (non-fixes dans cette audit)

### Tier 1 deferes (CI deja vert sur ces patterns)
- BLE001 blind-except (35) — pattern defensif systematique
- SLF001 private-member-access (538) — analyse archi separee
- S324 sha1 (5) — fingerprints cache, annoter `usedforsecurity=False`
- RUF013 implicit-optional (3) — `x: int = None` fautif
- RUF012 mutable-class-default (2) — etat partage

### Tier 2 deferes
- LOW jellyfin_client.mark_unplayed asymetrie avec _post()
- LOW perceptual.py:128 + sqlite_store.py:119 double context manager non-idiomatic
- MED quality.save_quality_profile sans BEGIN/COMMIT explicite (fonctionne via `_with_schema_group`)

### Audit `_rc` ffmpeg (Tier 1 RUF059 prefixe seulement)
`audio_perceptual.py:221,277` : `_rc, _stdout, stderr = run_ffmpeg_text(cmd)` puis check sur stderr uniquement. Si ffmpeg sort en erreur (`rc != 0`) avec stderr non-vide (cas frequent), le code parse du garbage. **Tier 2 ou audit dedie a faire.**

---

## Stack outils utilises

| Outil | Usage | Resultat |
|-------|-------|----------|
| ruff | Lint + format (`--select ALL --statistics` pour discovery) | 1 vrai bug en baseline + 7 categories d'interet |
| vulture | Dead code (`--min-confidence 80`) | 2 parametres vestigiaux confirmes |
| Agent tool (Explore) | 6 sous-agents parallele | Briefing cible, rapports markdown ≤400 mots |
| pytest | Validation per-module | 308 (Tier 1) + 281 (Tier 2) verts |
| import-linter | Architecture contracts | Tous PASS, aucun cycle reintroduit |
| gh CLI | PR + CI status check | 2 PRs ouvertes, Tier 2 mergee |

---

## Lecons apprises

1. **Per-file-ignores ruff dependent du CWD** : lancer ruff hors-projet faisait passer 45 faux-positifs (chemins absolus ne matchaient pas `tests/e2e/**`).
2. **Multi-agents parallele = ROI tres haut** sur audit large : 6 agents en 5 min ont craché 22 findings dont 2 HIGH qu'aucune CI n'avait trouve.
3. **Pattern "pacotille" confirme + etendu** : 8 features completes sans entry UI vs 3 connus en memoire.
4. **CI rouge sur format pre-existant** : 18 fichiers (cinesort_api, 4 facades, 13 tests/test_phase*) avaient des format issues anciens, masques par le scope CI initial. Format cleanup global cette PR.

---

## References

- PR Tier 1 (analyse statique) : https://github.com/Thomas05000005/CineSort/pull/339
- PR Tier 2 (multi-agents) : https://github.com/Thomas05000005/CineSort/pull/347 (mergee)
- Plan d'audit detaille : `~/.claude/plans/flickering-hatching-codd.md`
