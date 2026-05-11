# CineSort — Process de release

> Documentation pour les mainteneurs : comment publier une nouvelle version de CineSort.

## Pre-requis

Avant de demarrer une release, verifier l'environnement :

- Branche source a jour (au minimum `main` ou branche release dediee, ex. `polish_total_v7_7_0`)
- Tests a 100% pass : `python -m unittest discover -s tests -p "test_*.py"`
- Coverage >= 80% : `python -m coverage run -m unittest discover -s tests -p "test_*.py" && python -m coverage report`
- Ruff propre : `python -m ruff check .`
- Build .exe teste localement OK (`build_windows.bat` reussit)
- Venv build = Python 3.13 (pas 3.14+, pythonnet incompatible — voir `build_windows.bat:24-31`)

## Process step-by-step

### 1. Bump de version

- Modifier le fichier `VERSION` a la racine (lu par `CineSort.spec:42`)
- Format : `7.7.0`, `7.7.1`, etc. — les suffixes `-dev`, `-beta`, `-rc` sont detectes comme prerelease (`CineSort.spec:50`)
- Conventions semver :
  - **MAJOR** : breaking change utilisateur (settings.json incompatible, schema DB rewrite, suppression d'endpoint)
  - **MINOR** : nouvelle feature (integration, vue, endpoint, theme)
  - **PATCH** : bugfix, polish, micro-optimisation

Le numero injecte dans `version_info.txt` apparait dans Proprietes du `.exe` Windows.

### 2. CHANGELOG.md

- Ajouter une nouvelle section en haut du fichier `CHANGELOG.md`
- Titre format : `## [v7.7.0] - 2026-05-XX — Titre court`
- Format Keep a Changelog : sections `Added` / `Changed` / `Fixed` / `Removed` / `Security`
- Referencer les findings resolus (CRIT-X, R4-Y, V1-01, etc.) pour la tracabilite avec `PLAN_RESTE_A_FAIRE.md` et `AUDIT_TRACKING.md`
- Pour les opérations multi-vagues (Polish Total, Audit QA), consolider en une entrée unique

### 3. Tag git

```bash
git tag -a v7.7.0 -m "Release v7.7.0 - Polish Total"
git push origin v7.7.0
```

Pour les releases majeures, conserver les tags backup intermediaires (`backup-before-vague-N`) pendant au moins 3 mois.

### 4. Build .exe

```bash
build_windows.bat
```

Sortie attendue :
- `dist/CineSort.exe` — onefile release (~50 MB cible < 60 MB)
- `dist/CineSort_QA/` — onedir QA (debug-friendly, lancement rapide)
- `dist/CineSort.zip` + `dist/CineSort_QA.zip` — produits par `scripts/package_zip.py --qa --release`

Validation post-build (obligatoire) :
- Taille `dist/CineSort.exe` < 60 MB (gate CI)
- Smoke test : double-clic sur `dist/CineSort.exe`, attendre splash, verifier que le dashboard s'affiche
- Verifier l'icone du `.exe` (clic droit > Proprietes > Details : ProductName=CineSort, FileVersion correcte)
- Verifier qu'aucun warning critique PyInstaller n'apparait dans la sortie (notamment hidden imports manquants pour `cinesort.domain.perceptual.*`)

### 5. GitHub Release

1. Aller sur la page Releases du repository (`https://github.com/<org>/CineSort/releases/new`)
2. Selectionner le tag `v7.7.0`
3. Title : `v7.7.0 - Polish Total`
4. Description : copier integralement la section CHANGELOG.md de la version
5. Upload assets :
   - `dist/CineSort.exe` (binaire principal)
   - `dist/CineSort_QA.zip` (build debug, optionnel)
   - `dist/CineSort.zip` (sources packaging, optionnel)
6. Cocher "Set as the latest release" si version stable
7. Cocher "Set as a pre-release" si version `-beta` / `-rc`
8. Publier

### 6. Communication post-release

- Mettre a jour `README.md` (badge version, screenshots si UI a change)
- Mettre a jour `CLAUDE.md` section "Etat de sante du projet" (note finale, version courante)
- Mettre a jour `BILAN_CORRECTIONS.md` avec le bilan de l'operation
- Annoncer sur les canaux externes (Reddit, forums, Discord) si applicable

## Rollback

Si une release contient un bug critique decouvert apres publication :

1. Identifier la derniere version stable precedente (consulter le tag git)
2. Sur GitHub : marquer la release fautive comme "Pre-release" pour qu'elle ne s'affiche plus comme "Latest"
3. Creer une branche hotfix : `git checkout -b hotfix/v7.7.1 v7.7.0`
4. Appliquer le correctif minimal, ajouter un test de non-regression
5. Bumper `VERSION` -> `7.7.1`, mettre a jour `CHANGELOG.md` (section "Fixed")
6. Suivre le process complet a partir de l'etape 3 (tag + build + release)
7. Communiquer aux utilisateurs (issue GitHub epinglee, message dans canaux externes)

## Versions historiques

Historique complet : voir [`CHANGELOG.md`](../CHANGELOG.md).
Audits et bilans : voir [`BILAN_CORRECTIONS.md`](../BILAN_CORRECTIONS.md) et `docs/internal/audits/`.

## Checklist release express

A copier dans une issue GitHub ou un commit body au moment de la release :

- [ ] Tests 100% pass (`python -m unittest discover`)
- [ ] Coverage >= 80% (`python -m coverage report`)
- [ ] Ruff propre (`python -m ruff check .`)
- [ ] Smoke test E2E Playwright dashboard OK
- [ ] `VERSION` bumpe (sans suffixe `-dev` pour stable)
- [ ] `CHANGELOG.md` mis a jour avec la date du jour
- [ ] Build `.exe` teste localement (smoke test manuel)
- [ ] Taille `dist/CineSort.exe` < 60 MB
- [ ] Tag git cree et pousse (`git push origin v7.7.0`)
- [ ] GitHub Release creee avec assets uploades
- [ ] `README.md` badge version mis a jour
- [ ] `CLAUDE.md` etat de sante du projet mis a jour
- [ ] Communication externe envoyee (si applicable)
