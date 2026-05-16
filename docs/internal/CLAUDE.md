# CLAUDE.md — Instructions pour Claude Code

Ce fichier est le contexte projet pour les sessions Claude (CLI, GitHub Action, IDE).
L'historique complet des sessions passees est dans [CLAUDE_HISTORY.md](CLAUDE_HISTORY.md).

---

## Instructions

### Langue et style
- **Reponds en francais** sauf si le code est en anglais.
- Apres chaque lot de modifications, rapporte : ce qui a change, pourquoi, fichiers touches, tests lances, ce qui reste.
- Prefere les refactors incrementaux. Preserve le comportement existant sauf demande explicite.
- Pas de travail GitHub/CI/release sauf demande.

### MCP servers (utilisation proactive, sans attendre la demande)
- **context7** : doc a jour d'un framework ou lib avant de coder (pywebview, requests, Playwright, Ruff, PyInstaller).
- **memory** : stocke et recupere les decisions d'architecture et le contexte entre sessions.
- **sequential-thinking** : raisonnement complexe (debug, refactoring, design d'archi).
- **filesystem** : lecture/ecriture de fichiers dans le workspace.
- **playwright** : teste et observe l'interface UI dans un vrai navigateur.

### Securite (titre des films)
**Ne JAMAIS modifier le titre des films au-dela du renommage configure.** Les noms doivent rester syncro avec les torrents pour permettre le seed. Toute modification de naming doit etre opt-in via les settings et reversible.

---

## Etat actuel du projet (16 mai 2026)

### Version
- **v1.0.0-beta** (publique). Roadmap : v1.1 features, v2.0 port Linux/Mac.

### Architecture en couches (verrouillee par import-linter en CI)

```
ui/      <- (anti-corruption layer cote desktop + web)
  api/   <- Facades par bounded context (run/settings/quality/integrations/library)
    ^
    | (depend de)
    v
app/     <- Orchestration (apply_core, plan_support, jellyfin_sync, etc.)
  ^
  | (depend de)
  v
domain/  <- Logique metier pure (scoring, parsing, perceptual, naming)
  ^
  | (depend de)
  v
infra/   <- I/O (SQLite + Repositories, TMDb/Jellyfin/Plex/Radarr clients, REST server)
```

**Contracts d'architecture** (`.importlinter`) :
1. `domain` ne peut PAS importer `app`, `infra`, `ui`
2. `infra` ne peut PAS importer `app`, `ui`
3. `app` ne peut PAS importer `ui`

Le cycle historique `domain -> app` a ete brise en mai 2026 (issue #83, phases A1-A8). Toute regression est bloquee par `lint-imports` en CI (job `Architecture contracts` dans `.github/workflows/ci.yml`).

### Patterns architecturaux

- **Repository pattern (infra/db/repositories/)** : chaque domaine SQL (probe, anomaly, scan, perceptual, quality, run, apply) a son repository. `SQLiteStore` les instancie et expose `store.probe`, `store.anomaly`, etc. Le pattern coexiste encore avec les `_XxxMixin` legacy (thin wrappers de delegation) pour preserver `store.upsert_probe()`. Future : phase B8 supprimera l'heritage MRO une fois valide en prod.
- **Strangler Fig / Facade pattern (ui/api/facades.py)** : 5 facades (`run`, `settings`, `quality`, `integrations`, `library`) groupent 50 methodes publiques sur `CineSortApi`. Les anciennes methodes directes `api.X(...)` sont marquees `_X_impl` (deprecated).
- **Module-style imports pour tests mockes** : quand un test fait `patch("cinesort.infra.plex_client.PlexClient")`, le module qui appelle PlexClient doit l'importer en `import ... as _mod` pas en `from ... import`. Pattern documente dans `cinesort/ui/api/apply_support.py`, `cinesort_api.py`, `perceptual_support.py`.

### Stack technique

- **Python 3.13** + pywebview >= 5.0 (UI desktop) + http.server stdlib (REST server)
- **SQLite WAL** (21 migrations, schema v21)
- **Dependances clefs** : `requests`, `rapidfuzz` (matching), `segno` (QR), `onnxruntime` + `numpy` (LPIPS perceptuel)
- **Probe** : ffprobe + mediainfo (binaires externes)
- **Tests** : pytest (>= 9.0.3) + hypothesis + Playwright (E2E dashboard)
- **Qualite** : ruff (lint + format), import-linter, pre-commit, codecov (coverage), bandit, mypy
- **Build** : PyInstaller (~50 MB onefile EXE Windows)

### Conventions de code

- **Imports** : top-level uniquement, sauf cycle inevitable (3 cas restants dans `cinesort/app/cleanup.py` -> `apply_core.py`).
- **Erreurs API** : utiliser `_err_response()` (`cinesort/ui/api/_responses.py`), categories `validation|state|resource|permission|config|runtime`.
- **Logs** : `logger = logging.getLogger(__name__)` + scrubber installe globalement (8 patterns secrets).
- **Tests** : `unittest` + `pytest` discovery. Pas de mock de DB (integration tests sur vraie SQLite).
- **Pas de docstrings multi-paragraphes** dans le code. Pas de comments WHAT (le code se lit), seulement les WHY non-evidents.

---

## Sessions recentes

### 16 mai 2026 (soir) — #83 phases A6-A8 terminees, #85 phases B1-B7 ✅

**12 PRs mergees en cascade** apres la cassure du cycle (#193, #197, #202, #203) :

| PR | Phase | Module(s) | Lazy imports |
|----|-------|-----------|--------------|
| #194-#201 | B1-B7 | 7 Repositories migres (mixin -> Repository) | — |
| #204 | A8 | import-linter en CI (.importlinter + workflow) | — |
| #205 | A6 | 6 small files (quality_score, settings_support, ...) | 28 |
| #206 | A7a | perceptual_support.py | 13 |
| #207 | A7b | apply_core.py | 18 |
| #208 | A7c | plan_support.py | 36 |
| #209 | A7d-1 | cinesort_api.py (imports safes) | 34 |
| #211 | A7d-2 | cinesort_api.py (module-style mockes) | 21 |
| **Total A6+A7** | — | **11 fichiers** | **150** |

**Bilan** :
- 150 lazy imports convertis en top-level (sur ~165 au depart)
- 3 imports restent volontairement lazy dans `cleanup.py` (cycle `cleanup <-> apply_core` non lie a domain->app)
- Architecture verrouillee : `lint-imports` echoue en CI si quelqu'un ressuscite un cycle
- 7 Repositories pattern installes (composition au lieu d'heritage MRO)
- Tests : 4277 passent, 0 regression
- Issue #83 fermee, B8 reste (suppression des `_XxxMixin` apres validation prod)

**Security** :
- 9 alerts CodeQL B608 (SQL injection f-string) marquees false-positive : pattern recommande `f"... IN ({','.join('?' for _ in ids)})"` avec valeurs en parametres.
- 1 alert log-injection medium (rest_server.py:502) fixee dans PR #212 (sanitize CR/LF + cap 200 chars).

### 16 mai 2026 (matin) — Cleanup audit-bot + #94 + premieres etapes #83 ✅

9 PRs mergees, 5 issues fermees. Detail dans `CLAUDE_HISTORY.md`.

### 15 mai 2026 — Refactor god class CineSortApi (#84) + Logging structure API (#103) ✅

10 PRs Strangler Fig : 104 -> 50 methodes publiques sur CineSortApi via 5 facades. 198 sites `return {"ok": False}` migres vers `_err_response()`. Detail dans `CLAUDE_HISTORY.md`.

---

## Workflows GitHub Actions

| Workflow | Trigger | Role |
|----------|---------|------|
| `ci.yml` | push main + PR | lint (ruff) + format + **import-linter** + tests + coverage 80% + build EXE + smoke |
| `audit-module.yml` | cron daily 04h UTC + manual | Audit Claude par couche (rotation lun-ven) avec prompt dans `.github/audit-prompt.md` (46 categories, 6 personas) |
| `claude.yml` | @mention + cron weekly (lundi 04h UTC) | Claude Code Action sur PR/issue |
| `codeql.yml`, `bandit.yml`, `gitleaks.yml`, `pip-audit.yml`, `mypy.yml` | push + PR | Security + typing |
| `scorecard.yml` | weekly | OpenSSF Scorecard |
| `windows-ci.yml` | push + PR | CI Windows-specific |

---

## Issues ouvertes (3)

| # | Sujet | Statut | Effort |
|---|-------|--------|--------|
| #14 | Umbrella audit | A laisser ouverte | — |
| #85 | Mixins SQLite -> Repositories (B8 cleanup) | Repositories faits (B1-B7), reste suppression mixins | 3-4h, 1 PR |
| (autres) | — | — | — |

---

## Verifications rapides

```bash
# Quality gate locale
check_project.bat                                                # Windows : compile + lint + format + tests + coverage
python -m pytest tests/ --ignore=tests/e2e --timeout=60 -q       # Tests rapides

# Architecture
lint-imports                                                     # 3 contracts (domain/infra/app boundaries)

# Build EXE
pyinstaller --noconfirm CineSort.spec                            # ~50 MB output dans dist/

# Lancement
python app.py                                                    # UI normale
python app.py --dev                                              # Console visible
python app.py --api                                              # REST seul, sans UI
```

---

## Documents utiles

- [README.md](../../README.md) — entree publique
- [CLAUDE_HISTORY.md](./CLAUDE_HISTORY.md) — historique complet des sessions
- [.github/audit-prompt.md](../../.github/audit-prompt.md) — prompt audit du matin (46 categories)
- [REFACTOR_PLAN_83.md](./REFACTOR_PLAN_83.md) — plan original casser cycle (acheve)
- [REFACTOR_PLAN_84.md](./REFACTOR_PLAN_84.md) — plan facades (acheve)
- [BILAN_CORRECTIONS.md](./BILAN_CORRECTIONS.md) — bilan audits successifs
