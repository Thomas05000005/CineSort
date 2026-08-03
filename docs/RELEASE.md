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

## Build hybride PyInstaller + Nuitka (V2.5)

> V2.5 SCAFFOLDING — Le build officiel reste **PyInstaller** (CineSort.exe).
> Nuitka est OPT-IN, additionnel, jamais substitutif. Backward compat ABSOLUE :
> tout pipeline existant (ci.yml, build_windows.bat, scripts/sign_windows_release.ps1)
> continue de fonctionner sans modification.

### Quand utiliser quoi

| Scenario | Backend | Commande / declencheur |
|----------|---------|------------------------|
| **PR / smoke test CI** | PyInstaller seul | `ci.yml` (pas de tag, rapide ~5 min) |
| **Build local dev** | PyInstaller | `build_windows.bat` (officiel) |
| **Benchmark startup / antivirus** | Nuitka | `.\scripts\build_nuitka.ps1` (local, ~30-60 min) |
| **Release publiee (tag v*)** | **les deux** | `release.yml` (PyInstaller + Nuitka en parallele) |

PyInstaller reste preferable au quotidien :
- Compile : ~30s vs 30-60 min pour Nuitka (C compiler invoque).
- Stack confirmee : 1.5.2-beta validee en prod, smoke tests verts.

Nuitka offre :
- Demarrage plus rapide (binaire C natif vs interpreteur Python embarque).
- Moins de faux positifs antivirus (pas de bootloader PyInstaller suspect).
- Tradeoff : compilation longue, debug plus difficile en cas d'echec.

### Build local Nuitka

```powershell
# Pre-requis : .venv active avec requirements.txt + nuitka installes
.\scripts\build_nuitka.ps1
# Variantes :
#   -SkipUpx       (UPX absent du PATH)
#   -KeepBuildDir  (debug : garder dist-nuitka/ intermediaire)
```

Sortie : `dist-nuitka/CineSortNuitka.exe`. Le binaire **PyInstaller** dans
`dist/CineSort.exe` reste le binaire de reference.

### Build CI (tag release)

Le workflow `.github/workflows/release.yml` se declenche sur `git push tag v*` :
1. Job `build-pyinstaller` : build officiel, gate taille < 60 MB.
2. Job `build-nuitka` : build alternatif, `continue-on-error: true` au niveau
   job pour ne JAMAIS bloquer la release si Nuitka echoue.
3. Job `publish-release` : cree un draft GitHub Release avec les deux EXE
   attaches (`CineSort.exe` et `CineSortNuitka.exe`). Nuitka absent =
   release publiee avec PyInstaller seul (continue-on-error sur le download).

Le `nuitka.config.cfg` a la racine documente les exclusions (torch.cuda, nvidia,
scipy, tkinter, etc.) alignees sur la section `excludes` de `CineSort.spec`.

### Migration progressive

- **Phase 1 (actuelle)** : PyInstaller officiel, Nuitka asset secondaire des
  releases. Pas de communication utilisateur.
- **Phase 2 (a evaluer)** : si Nuitka stable sur 3 releases consecutives,
  promouvoir `CineSortNuitka.exe` en asset documente (changelog), garder
  PyInstaller en officiel.
- **Phase 3 (hypothetique)** : bascule eventuelle quand metriques (taille,
  startup, faux positifs AV) le justifient. PyInstaller restera disponible
  pendant 1 release pour fallback (cf principe backward compat ABSOLUE).

## Bundle WebView2 (release seulement)

> V3.1 SCAFFOLDING — Etape OPT-IN pour les releases qui doivent embarquer un
> runtime WebView2 Fixed Version (independant du runtime Evergreen installe
> sur le poste utilisateur). Non utilise par les builds standards.

### Pourquoi ce mode existe

- L'EXE CineSort utilise par defaut le **runtime WebView2 Evergreen** installe
  par Microsoft Edge. Sur certaines machines (Windows LTSC, comptes admin
  restreints, profils corrompus), ce runtime peut etre absent ou casse
  -> ecran noir au boot.
- En embarquant le runtime **Fixed Version** directement dans le `.exe`, on
  s'assure que CineSort dispose d'un WebView2 fonctionnel meme sans Edge
  recent installe. Le tradeoff est une taille `.exe` plus grande
  (+120 MB acceptes, cf principes projet : qualite > optimisation taille).
- Ce mode est OPT-IN : sans variable d'env `CINESORT_BUNDLE_WEBVIEW2=1`,
  le build standard se comporte comme historiquement (backward-compat
  ABSOLUE).

### Preparer le bundle (manuel-only, jamais en CI)

1. Telecharger le bundle Fixed Version depuis Microsoft :

   ```bash
   python scripts/download_webview2_fixed.py
   ```

   Par defaut le script affiche les instructions de telechargement manuel
   (URL Microsoft, EULA a accepter, extraction `expand`). Pour les
   mainteneurs ayant deja recupere un lien CDN direct, utiliser :

   ```bash
   python scripts/download_webview2_fixed.py --url <URL_CDN_DIRECTE>
   ```

2. Valider que le bundle est complet :

   ```bash
   python scripts/download_webview2_fixed.py --check-only
   ```

   Doit lister `webview2_fixed/msedgewebview2.exe` et
   `webview2_fixed/EBWebView/x64/msedge.dll`.

### Builder l'EXE avec le bundle embarque

```bash
set CINESORT_BUNDLE_WEBVIEW2=1
build_windows.bat
```

Le `CineSort.spec` detecte la variable d'env et inclut tout le contenu de
`webview2_fixed/` dans le bundle PyInstaller. Au demarrage, `app.py`
(via `_configure_webview2_runtime()`) expose les chemins via les variables
d'environnement standards `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER` et
`WEBVIEW2_USER_DATA_FOLDER` AVANT l'import de `webview`. Si la variable
d'env n'est pas definie ou si le bundle est absent, le runtime Evergreen
est utilise comme avant.

### Verification post-build

- Taille `dist/CineSort.exe` augmentee (~120-180 MB attendu, gate CI taille
  a desactiver pour les builds bundle).
- Smoke test sur une VM **sans Edge installe** : doit demarrer normalement
  et afficher le dashboard sans ecran noir.
- Verifier dans les logs `%LOCALAPPDATA%/CineSort/logs/` la presence de la
  ligne `[WEBVIEW2] Runtime Fixed bundle actif: ...`.

### Ne PAS commit `webview2_fixed/`

Le repertoire `webview2_fixed/` doit etre dans `.gitignore`. Chaque
mainteneur le regenere localement quand necessaire. Ne PAS distribuer le
bundle Microsoft separement (EULA).

## Versions historiques

Historique complet : voir [`CHANGELOG.md`](../CHANGELOG.md).
Audits et bilans : voir [`internal/BILAN_CORRECTIONS.md`](internal/BILAN_CORRECTIONS.md) et `internal/audits/`.

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
