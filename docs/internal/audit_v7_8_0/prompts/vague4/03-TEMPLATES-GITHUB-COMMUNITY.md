# V4-03 — Templates GitHub Community

**Branche** : `docs/github-community-templates`
**Worktree** : `.claude/worktrees/docs-github-community-templates/`
**Effort** : 2-3h
**Mode** : 🟢 Parallélisable (pure création fichiers)
**Fichiers à créer** :
- `.github/ISSUE_TEMPLATE/bug_report.yml`
- `.github/ISSUE_TEMPLATE/feature_request.yml`
- `.github/ISSUE_TEMPLATE/question.yml`
- `.github/ISSUE_TEMPLATE/config.yml`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- `tests/test_github_community_templates.py` (validation YAML/markdown)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b docs/github-community-templates .claude/worktrees/docs-github-community-templates audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/docs-github-community-templates

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu ne crées QUE des fichiers de templates GitHub + CONTRIBUTING/
CODE_OF_CONDUCT/SECURITY. Aucun changement sur le code de l'app.

LANGUE : tout en **français** (le projet vise les francophones). Le `CODE_OF_CONDUCT`
peut être bilingue FR/EN si tu adaptes Contributor Covenant 2.1.

---

## CONTEXTE

CineSort va être public sur GitHub. Pour faciliter la contribution et bien gérer la
communauté, GitHub propose des "Community Standards" : templates issues, PR, code de
conduite, contributing, security. Sans ces fichiers, le score "Community Standards"
GitHub reste bas et donne une mauvaise impression aux contributeurs potentiels.

---

## MISSION

### Étape 1 — Lire CONTEXTE projet

- `LICENSE` (V1-01 — MIT)
- `README.md` (état actuel — sera enrichi en V4-04)
- `CLAUDE.md` (contexte projet — pour comprendre le ton et la stack)

### Étape 2 — Templates ISSUE

#### `.github/ISSUE_TEMPLATE/bug_report.yml`

```yaml
name: 🐛 Signaler un bug
description: Un comportement inattendu, un crash, ou un truc qui marche mal.
title: "[Bug] "
labels: ["bug", "triage"]
body:
  - type: markdown
    attributes:
      value: |
        Merci de signaler ce bug ! Avant tout, regarde si quelqu'un a déjà ouvert
        une issue similaire dans la liste.

  - type: input
    id: version
    attributes:
      label: Version de CineSort
      description: Visible dans Paramètres > À propos (ex. v7.6.0)
      placeholder: v7.6.0
    validations:
      required: true

  - type: input
    id: os
    attributes:
      label: Version Windows
      description: Win10 / Win11 / build (ex. Win11 26200)
    validations:
      required: true

  - type: textarea
    id: what-happened
    attributes:
      label: Description du bug
      description: Que s'est-il passé ? Qu'est-ce que tu attendais à la place ?
      placeholder: |
        J'ai cliqué sur X, puis Y est arrivé.
        Je m'attendais à ce que Z arrive.
    validations:
      required: true

  - type: textarea
    id: reproduction
    attributes:
      label: Étapes pour reproduire
      placeholder: |
        1. Ouvrir CineSort
        2. Aller dans Bibliothèque
        3. Cliquer sur ...
        4. Bug visible
    validations:
      required: true

  - type: textarea
    id: logs
    attributes:
      label: Logs (optionnel mais aide énormément)
      description: Aide > Ouvrir les logs > copie-colle le contenu de cinesort.log
      render: text

  - type: checkboxes
    id: terms
    attributes:
      label: Vérifications
      options:
        - label: J'ai vérifié qu'aucune issue similaire n'existait déjà
          required: true
        - label: J'utilise la dernière version stable de CineSort
          required: true
```

#### `.github/ISSUE_TEMPLATE/feature_request.yml`

```yaml
name: 💡 Proposer une amélioration
description: Une idée pour rendre CineSort meilleur.
title: "[Feature] "
labels: ["enhancement", "triage"]
body:
  - type: textarea
    id: problem
    attributes:
      label: Quel problème ça résout ?
      description: |
        Ex. "Quand j'ai 5000 films, c'est lent de chercher par acteur"
    validations:
      required: true

  - type: textarea
    id: solution
    attributes:
      label: Solution proposée
      description: Décris ce que tu aimerais voir.
    validations:
      required: true

  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives envisagées
      description: D'autres approches que tu as considérées (optionnel)

  - type: textarea
    id: context
    attributes:
      label: Contexte additionnel
      description: Captures, liens, exemples
```

#### `.github/ISSUE_TEMPLATE/question.yml`

```yaml
name: ❓ Question
description: Une question sur l'utilisation, la configuration, ou le fonctionnement.
title: "[Question] "
labels: ["question"]
body:
  - type: markdown
    attributes:
      value: |
        Pour les questions générales, préfère **GitHub Discussions** : c'est plus adapté
        et la communauté peut t'aider plus vite. Les issues sont réservées aux bugs/features.

  - type: textarea
    id: question
    attributes:
      label: Ta question
    validations:
      required: true
```

#### `.github/ISSUE_TEMPLATE/config.yml`

```yaml
blank_issues_enabled: false
contact_links:
  - name: 💬 Discussion communautaire
    url: https://github.com/PLACEHOLDER/cinesort/discussions
    about: Pour les questions générales, partager ta config, ou discuter de l'évolution du projet.
  - name: 📚 Documentation
    url: https://github.com/PLACEHOLDER/cinesort#readme
    about: Lis le README et la doc avant d'ouvrir une issue.
```

⚠ **PLACEHOLDER** : remplacer après création du repo.

### Étape 3 — Pull Request Template

Crée `.github/PULL_REQUEST_TEMPLATE.md` :

```markdown
## Description

<!-- Quoi ? Pourquoi ? -->

## Type de changement

- [ ] 🐛 Bug fix (changement non-breaking qui résout un bug)
- [ ] ✨ Feature (changement non-breaking qui ajoute une fonctionnalité)
- [ ] 💥 Breaking change (fix ou feature qui casse la compatibilité)
- [ ] 📚 Documentation
- [ ] 🎨 Style/UI
- [ ] ♻️ Refactor (pas de changement de comportement)
- [ ] ⚡ Performance
- [ ] ✅ Tests

## Comment tester

<!-- Étapes claires pour qu'un reviewer puisse vérifier -->

## Checklist

- [ ] Mes commits ont des messages clairs (`type(scope): description`)
- [ ] J'ai ajouté des tests qui couvrent mon changement
- [ ] Tous les tests passent (`python -m unittest discover -s tests -p "test_*.py"`)
- [ ] Le lint passe (`python -m ruff check .`)
- [ ] J'ai mis à jour la doc si nécessaire (README, CLAUDE.md)
- [ ] J'ai testé manuellement sur Windows 10/11

## Issues liées

<!-- Closes #123 / Refs #456 -->
```

### Étape 4 — CONTRIBUTING.md

Crée `CONTRIBUTING.md` (en français, ton concret et accueillant) :

```markdown
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
```

### Étape 5 — CODE_OF_CONDUCT.md

Adapte Contributor Covenant 2.1 en français. Crée `CODE_OF_CONDUCT.md` :

```markdown
# Code de Conduite — Contributor Covenant

## Notre engagement

Nous, contributeurs et mainteneurs, nous engageons à faire de la participation à
notre projet et à notre communauté une expérience exempte de harcèlement pour
tous, peu importe l'âge, le physique, le handicap visible ou invisible, l'origine
ethnique, les caractéristiques sexuelles, l'identité ou l'expression de genre, le
niveau d'expérience, l'éducation, le statut socio-économique, la nationalité,
l'apparence personnelle, la race, la religion, ou l'identité ou l'orientation
sexuelle.

Nous nous engageons à agir et interagir de façon à contribuer à une communauté
ouverte, accueillante, diverse, inclusive et saine.

## Nos standards

Exemples de comportements qui contribuent à un environnement positif :

- Faire preuve d'empathie et de bienveillance
- Respecter les opinions, points de vue et expériences différents
- Accepter les critiques constructives avec grâce
- Se concentrer sur ce qui est meilleur pour la communauté

Exemples de comportements inacceptables :

- L'usage de langage ou d'imagerie sexualisés
- Les commentaires insultants ou désobligeants, attaques personnelles ou politiques
- Le harcèlement public ou privé
- La publication d'informations privées d'autrui sans permission
- Toute autre conduite raisonnablement considérée comme inappropriée

## Application

Les cas de comportement abusif, harcelant ou inacceptable peuvent être signalés
aux mainteneurs à l'adresse : **PLACEHOLDER@example.com**

Les mainteneurs sont tenus de respecter la confidentialité du déclarant.

## Conséquences

Les mainteneurs qui ne suivent ou n'appliquent pas le Code de Conduite de bonne
foi peuvent être confrontés à des conséquences temporaires ou permanentes
déterminées par les autres membres de la direction du projet.

## Attribution

Ce Code de Conduite est adapté du [Contributor Covenant 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
```

### Étape 6 — SECURITY.md

Crée `SECURITY.md` :

```markdown
# Politique de Sécurité

## Versions supportées

Les correctifs de sécurité sont appliqués sur la dernière version stable.

| Version | Supportée |
|---------|-----------|
| 7.6.x   | ✅ |
| < 7.6   | ❌ |

## Signaler une vulnérabilité

Si tu découvres une vulnérabilité de sécurité dans CineSort, **NE PAS ouvrir d'issue
publique**. Utilise plutôt les [GitHub Security Advisories privées](https://github.com/PLACEHOLDER/cinesort/security/advisories/new).

Tu recevras un accusé de réception sous 48h. Les vulnérabilités confirmées seront
corrigées et publiées dans un délai raisonnable selon la sévérité (typiquement 7-30 jours).

## Surface d'attaque

CineSort est une app desktop locale Windows. Les surfaces sensibles :

- **Dashboard distant** (port 8642 par défaut) — protégé par token Bearer + rate limiting.
  Si exposé sur internet (à éviter), utiliser HTTPS + un token long ≥ 32 chars.
- **Stockage des clés API** (TMDb, Jellyfin, Plex, Radarr) — chiffré via DPAPI Windows.
- **Logs** — secrets scrubés avant écriture (`log_scrubber.py`).
- **Opérations destructives** — toujours via journal write-ahead + confirmation utilisateur.

## Hors scope

- Vulnérabilités dépendant d'un attaquant ayant déjà un accès local au compte Windows
- Bypass des restrictions DRM ou des protections antivirus

Merci !
```

### Étape 7 — Tests de validation

Crée `tests/test_github_community_templates.py` :

```python
"""V4-03 — Vérifie l'existence et la validité des fichiers community GitHub."""
from __future__ import annotations
import unittest
from pathlib import Path


REQUIRED_FILES = [
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/question.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
]


class CommunityTemplatesTests(unittest.TestCase):
    def test_all_required_files_present(self):
        for f in REQUIRED_FILES:
            with self.subTest(file=f):
                self.assertTrue(Path(f).is_file(), f"Manquant: {f}")

    def test_yaml_files_valid_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML non installé (CI a yaml)")

        for f in REQUIRED_FILES:
            if f.endswith(".yml"):
                with self.subTest(file=f):
                    content = Path(f).read_text(encoding="utf-8")
                    parsed = yaml.safe_load(content)
                    self.assertIsNotNone(parsed)
                    self.assertIsInstance(parsed, dict)

    def test_contributing_has_essential_sections(self):
        content = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
        for section in ["Setup", "Conventions", "Tests", "Pull Requests", "Licence"]:
            self.assertIn(section, content, f"CONTRIBUTING manque section: {section}")

    def test_security_has_contact(self):
        content = Path("SECURITY.md").read_text(encoding="utf-8")
        self.assertTrue(
            "PLACEHOLDER" in content or "advisories/new" in content,
            "SECURITY.md doit indiquer comment signaler une vulnérabilité"
        )

    def test_code_of_conduct_french(self):
        content = Path("CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
        self.assertIn("engagement", content.lower())
        self.assertIn("Contributor Covenant", content)


if __name__ == "__main__":
    unittest.main()
```

### Étape 8 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_github_community_templates -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
```

### Étape 9 — Commits

- `docs(github): add issue + PR templates (bug, feature, question, config) (V4-03)`
- `docs(community): add CONTRIBUTING.md`
- `docs(community): add CODE_OF_CONDUCT.md (Contributor Covenant 2.1 FR)`
- `docs(security): add SECURITY.md with disclosure policy`
- `test(community): structural validation of GitHub templates`

---

## LIVRABLES

- 4 templates ISSUE + 1 PR template
- CONTRIBUTING.md complet (setup, conventions, tests, PR)
- CODE_OF_CONDUCT.md (Contributor Covenant FR)
- SECURITY.md (politique disclosure)
- Test structurel
- Tous les `PLACEHOLDER` documentés (à remplacer après création repo public)
- 5 commits sur `docs/github-community-templates`
