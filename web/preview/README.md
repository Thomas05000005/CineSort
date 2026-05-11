# CineSort Preview Workflow

Le mode preview web sert a auditer l'UI locale sans lancer le shell desktop.

- il reutilise l'UI stable (`web/index.html` + `web/app.js` + `web/styles.css`),
- il n'impacte pas l'application desktop,
- il injecte seulement un mock `pywebview.api` quand `?preview=1` est present.

## Lancement du preview

```bash
set DEV_MODE=1
python scripts/run_ui_preview.py --dev
python scripts/run_ui_preview.py --dev --scenario quality_anomalies --view quality
python scripts/run_ui_preview.py --dev --scenario first_launch --view home --no-browser
```

Sans `--dev` ni `DEV_MODE=1`, le preview refuse de demarrer.

Le serveur ouvre par defaut:

- `http://127.0.0.1:8765/web/index_preview.html?preview=1&scenario=<scenario>&view=<vue>`

## Changer de scenario

Tu peux changer de scenario de trois facons:

1. dans la toolbar preview du navigateur (`Scenario` + `Vue`)
2. en relancant la commande avec `--scenario` et `--view`
3. en modifiant directement l'URL:

```text
/web/index_preview.html?preview=1&scenario=run_to_review&view=review
```

Scenarios utiles fournis:

- `first_launch`
- `app_ready`
- `run_recent_safe`
- `run_to_review`
- `quality_anomalies`
- `validation_loaded`
- `apply_dry_run`
- `apply_result`
- `settings_complete`
- `logs_artifacts`

## Captures manuelles

Jeu recommande par vue:

```bash
python scripts/capture_ui_preview.py --dev --recommended
```

Jeu unique sur un scenario:

```bash
python scripts/capture_ui_preview.py --dev --scenario run_recent_safe --views home,quality,validate,apply,settings,logs
```

Captures ciblees supplementaires:

```bash
python scripts/capture_ui_preview.py --dev --scenario validation_loaded --views review,duplicates
```

Sortie par defaut:

- `build/ui_preview_captures/<scenario-ou-recommended>/`
- un `manifest.json` accompagne chaque lot

## Controle visuel leger

Les vues critiques controlees par defaut sont:

- `Accueil`
- `Vue du run`
- `Qualite`
- `Decisions`
- `Execution`
- `Reglages`

### Regenerer la baseline

```bash
python scripts/visual_check_ui_preview.py --dev --refresh-baseline
```

Baseline par defaut:

- `tests/ui_preview_baselines/critical/`
- les PNG et le `manifest.json` de ce dossier sont la reference canonique versionnee
- les autres variantes de baseline restent locales et hors du gate par defaut

### Lancer une comparaison

```bash
python scripts/visual_check_ui_preview.py --dev
```

Sortie par defaut:

- `build/ui_preview_visual_check/latest/report.html`
- `build/ui_preview_visual_check/latest/report.json`
- `build/ui_preview_visual_check/latest/current/`
- `build/ui_preview_visual_check/latest/diff/`

Le script retourne un code non nul si une regression depasse les seuils.

## Dependance capture

```bash
python -m pip install -r requirements-preview.txt
python -m playwright install chromium
```

Pour le gate local complet:

```bash
python -m pip install -r requirements-dev.txt
pre-commit install
pre-commit run --all-files
check_project.bat
```

## Extension future

Pour ajouter une vue ou un etat:

1. ajouter le scenario dans `web/preview/preview_scenarios.js`
2. ajouter la vue dans `scripts/capture_ui_preview.py`
3. si necessaire, l'ajouter au mapping recommande
4. regenerer la baseline avec `--refresh-baseline`
