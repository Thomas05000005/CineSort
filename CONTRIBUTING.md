# Contribuer à CineSort

Merci de vouloir contribuer ! 🎬

## Avant de commencer

- **Bug** ? Ouvre une [issue avec le template Bug Report](https://github.com/PLACEHOLDER/cinesort/issues/new?template=bug_report.yml)
- **Question** ? Va sur [GitHub Discussions](https://github.com/PLACEHOLDER/cinesort/discussions)
- **Idée** ? Ouvre une [issue Feature Request](https://github.com/PLACEHOLDER/cinesort/issues/new?template=feature_request.yml) **avant** de coder pour qu'on en discute

## Setup environnement de dev

Prérequis : Python 3.13, Git, Windows 10/11.

```bash
git clone https://github.com/PLACEHOLDER/cinesort.git
cd cinesort
python -m venv .venv313
.venv313\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # tests + linters
python app.py  # lance l'app
```

## Conventions

### Code

- **Python 3.13**, ligne 120 chars max (Ruff)
- `from __future__ import annotations` en tête de chaque module
- Docstrings sur toutes les fonctions publiques
- Pas de `except Exception:` — toujours typer (`except (ValueError, OSError):`)
- Pas de magic numbers — utiliser des constantes nommées
- Logging : `logger = logging.getLogger(__name__)`
- UI/strings en français, code/variables en anglais

### Architecture

- `cinesort/domain/` — modèles purs, scoring (zéro I/O)
- `cinesort/infra/` — DB, HTTP clients, fichiers
- `cinesort/app/` — orchestration métier
- `cinesort/ui/api/` — bridge pywebview <-> JS
- `web/dashboard/` — UI principale (servie en local par pywebview)
- Pas de logique métier dans `web/`, pas d'I/O dans `domain/`

### Commits

Format : `type(scope): description`

Types : `feat`, `fix`, `refactor`, `test`, `docs`, `style`, `perf`, `chore`, `ci`.

Exemples :
- `feat(scan): support for HEVC bitrate analysis`
- `fix(ui): empty state CTA not clickable on mobile`
- `refactor(quality): split scoring into pure functions`

### Tests

```bash
# Tous les tests
python -m unittest discover -s tests -p "test_*.py"

# Avec couverture
python -m coverage run -m unittest discover -s tests -p "test_*.py"
python -m coverage report

# Lint + format
python -m ruff check .
python -m ruff format .
```

Coverage doit rester ≥ 80% (CI bloque sinon).

### Pull Requests

- Branche depuis `main` (ou la branche d'audit en cours)
- Commits granulaires et lisibles (1 commit = 1 changement logique)
- PR description avec : description, comment tester, checklist du template
- Si la PR est lourde, propose-la en draft d'abord pour discuter de l'approche

## Communication

- **Code review** : feedback constructif, on critique le code pas la personne
- **Délais** : pas de garantie de timing, on fait au mieux
- **Décisions** : pour les changements d'architecture, on discute en issue avant

## Licence

En contribuant, tu acceptes que ton code soit publié sous licence MIT (cf [LICENSE](LICENSE)).
