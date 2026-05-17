# Suite E2E a 3 niveaux

Document interne — strategie de tests E2E pour valider le code avant
la sortie de v1.0.0 stable.

## Vue d'ensemble

Trois niveaux complementaires, du plus rapide au plus fragile :

| Niveau | Fichier | Duree | Pre-requis | Frequence |
|--------|---------|-------|------------|-----------|
| 1 — API offline | `tests/test_e2e_api_golden_flows.py` | ~2 s | aucun | a chaque push |
| 2 — Smoke EXE | `tests/e2e/smoke_exe.py` | ~30 s | EXE buildé | release / workflow_dispatch |
| 3 — Playwright UI | `tests/e2e/test_ui_playwright.py` | ~1-2 min | EXE buildé + Chromium | release / workflow_dispatch |

---

## Niveau 1 — pytest sur CineSortApi (golden flows)

### Objectif

Valider le tronc commun fonctionnel (plan -> validate -> apply -> undo) avec
les vraies dependances (DB SQLite, filesystem), mais sans reseau.

### 5 scenarios

1. **Golden path complet** : plan -> validate -> apply -> filesystem + DB -> undo -> rollback verifie.
2. **Conflit duplicate** : 2 fichiers meme film -> `check_duplicates` detecte le conflit -> resolution via decision override.
3. **Apply partial failure** (Windows only) : destination bloquee par un fichier preexistant -> undo restaure les ops appliquees.
4. **Settings DPAPI roundtrip** (Windows only) : `tmdb_api_key` enregistree, chiffrement DPAPI verifie sur disque, dechiffrement cross-instance.
5. **Run history** : 3 runs consecutifs -> `list_runs()` retourne 3 entries ordonnees desc par started_ts.

### Lancement

```powershell
# Tous les tests du niveau 1
python -m pytest tests/test_e2e_api_golden_flows.py -v

# Un seul scenario
python -m pytest tests/test_e2e_api_golden_flows.py::GoldenPathFlowTests -v
```

### Mocking

- TMDb/OMDb : mockes via `unittest.mock.patch` (jamais d'appel reseau).
- DB SQLite : **reelle**, pas de mock. On veut attraper les vrais bugs de schema.
- Filesystem : reel sous `tempfile.mkdtemp(...)`, cleanup automatique.

### Limites

- Ne couvre pas l'UI HTML/JS (niveau 3 pour ca).
- Ne couvre pas le binding `pywebview` -> JS (niveau 2 verifie au moins le boot).
- `test_apply_partial_failure_then_undo_rollback_only_successful_ops` depend du comportement Windows pour les conflits dossier/fichier ; peut etre flaky sous Linux/Mac (skip propre).

---

## Niveau 2 — Smoke EXE post-build

### Objectif

Valider que l'EXE PyInstaller se lance, charge ses DLLs, boot le serveur REST,
sans erreur fatale dans stderr. Detecte les regressions de packaging (hidden
import oublie, DLL manquante, runtime hook casse).

### Script standalone

`tests/e2e/smoke_exe.py` — NON inclus dans `pytest tests/` par defaut, car :
- Build PyInstaller ~10 min, on ne veut pas le faire tourner a chaque push.
- Le mode GUI pywebview interagit mal avec les pipes pytest (stderr).

### Modes

- **`--api`** : lance l'EXE en mode REST server, verifie qu'un port HTTP est ouvert. Plus simple a verifier en CI.
- **(defaut)** : lance l'EXE en mode GUI complet, verifie qu'il survit 10 s sans crasher. Scanne les ports 8080-9100 pour info.

### Lancement

```powershell
# Smoke en mode --api (recommande en CI)
python tests/e2e/smoke_exe.py --api

# Smoke GUI complet (plus realiste, peut laisser pywebview ouvert)
python tests/e2e/smoke_exe.py --wait 10
```

### Exit codes

| Code | Sens |
|------|------|
| 0 | Succes |
| 1 | EXE absent (skip propre) |
| 2 | Process crashe pendant la fenetre d'attente |
| 3 | Erreur fatale detectee dans stderr (`ImportError|ModuleNotFoundError|DLL`) |
| 4 | Port HTTP attendu non ouvert |

### CI

Workflow `.github/workflows/smoke-exe.yml` :
- `workflow_dispatch` only (manual trigger).
- Build complet PyInstaller puis smoke `--api`.

### Limites

- Ne valide pas l'UI HTML (juste le boot du backend).
- Le mode GUI cleanup pywebview peut etre fragile sur certains setups (le finally `_terminate()` essaye SIGTERM puis SIGKILL).

---

## Niveau 3 — Playwright sur Webview2

### Objectif

Valider que l'UI HTML/JS embarquee dans Webview2 se charge, que la
navigation entre vues fonctionne, et que les principaux flows interactifs
(login, settings, scan) sont accessibles.

### Approche pragmatique

L'option "vraie attache Webview2 via Chrome DevTools Protocol" demande
4-8 heures de setup (config WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS,
decouverte de port, robustesse aux versions Edge). Voir
[Microsoft Edge — Debug WebView2 with CDP](https://learn.microsoft.com/en-us/microsoft-edge/webview2/how-to/debug-cdp).

**Choix retenu** : utiliser Chromium (Playwright) attache au **serveur HTTP
local servi par l'EXE** (`http://127.0.0.1:<port>/dashboard/`). C'est la MEME
UI HTML/JS que celle chargee dans Webview2 — donc test pertinent pour les
regressions UI sans le bricolage CDP.

Le squelette `TestUIPlaywrightViaCDP` reste dans le fichier, marque
`@pytest.mark.skip(reason="Webview2 CDP setup pending")`, pour reactiver
plus tard si le besoin est confirme.

### 3 scenarios

1. **Lancement** : ouvre `/dashboard/`, verifie que le titre HTML contient `CineSort`.
2. **Settings + champ TMDb** : authentification, navigation vers Settings, presence d'un input `#tmdbApiKey` ou equivalent.
3. **Navigation vers Runs** : presence du bouton "Nouveau scan" (le scan complet est deja couvert par le niveau 1).

### Lancement

```powershell
# Pre-requis : installer Playwright Chromium (~150 MB)
python -m playwright install chromium

# Lancer (auto-skip si dist/CineSort.exe absent)
python -m pytest tests/e2e/test_ui_playwright.py -v

# Forcer un EXE specifique
CINESORT_EXE=C:\path\to\CineSort.exe python -m pytest tests/e2e/test_ui_playwright.py
```

### Limites

- Fragile aux changements UI (selecteurs DOM).
- Le scenario 3 a ete adapte : "lancer scan + DONE" demandait un dossier de test reel + scan complet (~10-30 s, flaky). Le niveau 1 couvre deja ce flow.
- Le module-scope du fixture `exe_server` lance UN seul EXE pour les 3 tests : si l'un casse l'etat, les suivants peuvent flaker.

---

## Comment lancer les 3 niveaux

```powershell
# Niveau 1 (rapide, no-deps)
python -m pytest tests/test_e2e_api_golden_flows.py -v

# Niveau 2 (requiert dist/CineSort.exe)
python tests/e2e/smoke_exe.py --api

# Niveau 3 (requiert dist/CineSort.exe + Playwright Chromium)
python -m playwright install chromium  # une seule fois
python -m pytest tests/e2e/test_ui_playwright.py -v
```

## Resume des garanties

| Garantie | Niveau couvrant |
|---------|-----------------|
| Le code Python compile et les imports tiennent | 1 |
| DB schema + migrations sont coherents | 1 |
| TMDb/OMDb mocks ne masquent pas un bug | n/a (mock externes uniquement) |
| L'EXE PyInstaller demarre (DLL, hidden imports, runtime hooks) | 2 |
| Le serveur REST de l'EXE ecoute sur son port | 2 |
| L'UI HTML charge sans erreur Chromium fatale | 3 |
| La navigation entre vues fonctionne | 3 |
| Webview2 specifiquement (vs Chromium standalone) | non couvert — squelette CDP a activer si besoin |
