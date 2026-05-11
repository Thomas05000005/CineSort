<div align="center">

<img src="assets/cinesort.ico" width="128" alt="CineSort logo" />

# CineSort

**Le tri-renommage automatique de ta bibliothèque de films, sans prise de tête.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)
![Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
[![Status: Beta](https://img.shields.io/badge/status-beta-orange.svg)](#statut-beta)
[![CI](https://github.com/Thomas05000005/CineSort/actions/workflows/ci.yml/badge.svg)](https://github.com/Thomas05000005/CineSort/actions/workflows/ci.yml)
[![CodeQL](https://github.com/Thomas05000005/CineSort/actions/workflows/codeql.yml/badge.svg)](https://github.com/Thomas05000005/CineSort/actions/workflows/codeql.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Thomas05000005/CineSort/badge)](https://scorecard.dev/viewer/?uri=github.com/Thomas05000005/CineSort)
[![Tests](https://img.shields.io/badge/tests-4243%20passing-green.svg)](#tests-et-qualité)
[![Coverage](https://img.shields.io/badge/coverage-80%25%2B-green.svg)](#tests-et-qualité)

> ⚠️ **v1.0.0-beta** — première publication publique. Le code est mature (~50 000 lignes, 4200+ tests, audit complet), mais la beta sert à recueillir des retours sur des bibliothèques réelles avant la v1.0 stable. Les changements de structure ne sont pas attendus, mais possibles selon vos retours. **Ne pas activer en production critique sans dry-run préalable.**

[Quick Start](#-quick-start) · [Fonctionnalités](#-fonctionnalités) · [Captures](#-captures-décran) · [FAQ](#-faq) · [Contribuer](CONTRIBUTING.md)

</div>

---

![Capture du dashboard CineSort](docs/screenshots/01_home.png)

## ✨ Pourquoi CineSort

- 🎬 **Renommage TMDb-aware** — détecte titre/année depuis tes fichiers même mal nommés
- 🔍 **Score qualité perceptuel** — analyse réelle vidéo (LPIPS, HDR, banding) + audio (loudness, clipping)
- 🛡️ **Zéro casse** — `dry-run` obligatoire, journal write-ahead, undo par film
- 🔌 **Intégrations natives** — Jellyfin, Plex, Radarr, TMDb (sync watched, refresh post-apply)
- 🌐 **Dashboard LAN** — accède à ta bibliothèque depuis ton téléphone via le réseau local
- 🌙 **4 thèmes** — Studio, Cinema, Luxe, Neon
- 🇫🇷 **100% francophone** — UI, doc, glossaire métier
- 🔒 **Privacy-first** — zéro télémétrie, zéro tracking, tout reste sur ton disque

## 🚀 Quick Start

### Option 1 : Binaire (recommandé)

1. Télécharge `CineSort.exe` depuis la page Releases du repo
2. Lance — pas d'install, pas d'admin, autonome
3. Au premier démarrage, suis le wizard (5 étapes)

### Option 2 : Sources

```bash
git clone <url-du-repo> cinesort
cd cinesort
python -m venv .venv313
.venv313\Scripts\activate
pip install -r requirements.txt
python app.py
```

Prérequis : Python 3.13, Windows 10/11, WebView2 Runtime (déjà présent sur Win 11).

### Modes de lancement

```bash
python app.py                     # UI normale (production)
python app.py --dev               # Mode développeur (console visible)
python app.py --api               # API REST seule, sans UI desktop
python app.py --api --port 9000   # API REST sur port custom
```

## 📸 Captures d'écran

### Bibliothèque
![Bibliothèque](docs/screenshots/02_library.png)

### Validation
![Validation](docs/screenshots/04_validation.png)

### Qualité (analyse perceptuelle)
![Qualité](docs/screenshots/03_quality.png)

### Paramètres
![Paramètres](docs/screenshots/05_settings.png)

### 4 thèmes (Studio / Cinema / Luxe / Neon)
![Thèmes](docs/screenshots/themes_grid.png)

<!-- Démo GIF : à enregistrer manuellement avec ScreenToGif (https://www.screentogif.com/) -->
<!-- Workflow recommandé : scan -> review -> apply, ~10 secondes -->

## 🎯 Fonctionnalités

### Détection et renommage
- Extraction titre/année depuis NFO, dossier, filename, TMDb (avec fallback intelligent)
- Profils de renommage (default, plex, jellyfin, quality, custom) — 20 variables
- Détection séries TV (S01E01, 1x01, "Saison N Episode N")
- Multi-root (plusieurs dossiers racine en un seul scan)
- Lookup IMDb ID depuis `.nfo` (endpoint `/find`)

### Analyse qualité
- Probe ffprobe + mediainfo (résolution, codec, bitrate, audio, sous-titres)
- Score perceptuel **réel** (LPIPS, HDR10+, Dolby Vision, banding, grain v2)
- Détection upscale suspect, re-encode dégradé, faux 4K (FFT 2D)
- Comparaison qualité doublons (7 critères pondérés)
- Vérification intégrité (magic bytes MKV/MP4/AVI/TS/WMV + tail check)

### Sécurité opérations
- `dry-run` obligatoire avant tout apply
- Journal write-ahead (atomicité crash-safe)
- Undo par film (granulaire, pas seulement par batch)
- Backup auto SQLite (avant migration + après apply, rotation 5)
- Pre-check espace disque avant apply
- Doublons SHA1 isolés, conflits vers `_review/`

### Intégrations
- **TMDb** — métadonnées + posters + sagas
- **Jellyfin** — refresh library, sync watched-state, validation cohérence
- **Plex** — refresh library, sync report
- **Radarr** — sync bidirectionnelle, propose upgrades qualité
- **Letterboxd / IMDb** — import watchlist CSV (matching fuzzy)

### Interface
- 4 thèmes atmosphériques (tier colors invariantes)
- Mode débutant / expert (cache options avancées)
- Tooltips ⓘ glossaire métier (18 termes)
- Compteurs sidebar dynamiques
- Drawer mobile pour validation distante
- Raccourcis clavier complets (Alt+1-7, Ctrl+K palette, ?, Esc, etc.)
- Empty states + skeleton loaders + draft auto

## 🌐 Dashboard distant

Accessible depuis tout navigateur du réseau local à `http://<ip-pc>:8642/dashboard/` après activation dans Paramètres → API REST.

- 10 vues : login, status, logs live, bibliothèque, runs, review, qualité, Jellyfin, Plex, Radarr, réglages
- Auth par Bearer token, rate limiting (5 échecs / 60s → 429)
- Polling adaptatif (2s durant un run, 15s sinon)
- HTTPS optionnel (cert+key via openssl)
- QR code dans les réglages desktop pour appairer ton téléphone

## 🛠️ Stack technique

- Python 3.13 + pywebview ≥ 5.0
- SQLite WAL (19 migrations)
- requests + segno (QR) + rapidfuzz (matching)
- onnxruntime + numpy (LPIPS perceptuel)
- ffprobe / mediainfo (probe vidéo)
- Ruff (lint+format) + unittest (3643 tests, 82% coverage)
- PyInstaller (~51 MB onefile EXE)

## 🧪 Tests et qualité

```bash
check_project.bat                                # CI locale : compile + lint + format + tests + coverage
python -m unittest discover -s tests -p "test_*.py" -v
python tests/e2e/run_e2e.py                      # E2E dashboard (Playwright)
```

Garanties :
- CI GitHub Actions bloquante à **80 % de couverture**
- **0 fonction > 100 lignes**, **0 duplication** (post-audit), **0 `except Exception`** non justifié
- Rapport HTML coverage disponible en artifact CI

## ❓ FAQ

### CineSort modifie-t-il mes fichiers vidéo ?

Non. CineSort renomme/déplace les **fichiers** sur disque, mais ne ré-encode jamais
le contenu vidéo/audio. Tes fichiers restent bit-pour-bit identiques.

### Comment annuler un apply raté ?

Vue **Application** → onglet **Historique** → tu peux annuler par batch ou
sélectivement film par film.

### Mes données sont-elles envoyées quelque part ?

**Non**. CineSort fait des appels HTTP uniquement vers : TMDb (si activé), Jellyfin/
Plex/Radarr (si configurés), GitHub Releases (si auto-check MAJ activé). Aucune
télémétrie, aucun tracking, aucune analytics.

### Puis-je utiliser CineSort sur Mac/Linux ?

Pas pour l'instant. Le projet cible Windows 10/11 nativement. Le port Linux/Mac
est dans la roadmap long terme.

### Comment configurer le dashboard distant ?

Paramètres → API REST → activer + définir un token long (≥ 32 chars). Accède au
dashboard depuis ton téléphone via `http://<ip-pc>:8642/dashboard/`. Le QR code
affiché dans les réglages desktop te permet d'appairer ton téléphone en un scan.

## 🗺️ Roadmap

- ✅ v7.6.0 — Refonte UI v5 (4 thèmes, design system)
- ✅ v7.6.0-dev — Audit complet, polish public-launch
- ⬜ v7.7.0 — Fusion desktop/dashboard (1 seule UI)
- ⬜ v8.0.0 — Port Linux/Mac, i18n EN, plugin marketplace
- ⬜ Long terme — App mobile companion, analyse audio musique

## 📚 Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — comment contribuer
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — code de conduite
- [SECURITY.md](SECURITY.md) — politique de sécurité
- [CLAUDE.md](CLAUDE.md) — contexte projet, architecture, conventions
- [ROADMAP.md](ROADMAP.md) — feuille de route V1/V2/V3
- [CHANGELOG.md](CHANGELOG.md) — historique des versions
- [BILAN_CORRECTIONS.md](BILAN_CORRECTIONS.md) — bilan des phases d'audit

## 📄 Licence

[MIT](LICENSE) — utilise, modifie, distribue librement.

## 🙏 Crédits

- TMDb pour les métadonnées
- ffmpeg/mediainfo pour le probe vidéo
- Contributor Covenant pour le code de conduite
- Tous les early adopters qui ont testé en bêta privée 🍿

---

<div align="center">

**Tu as aimé CineSort ?** Mets une ⭐ sur le repo, partage à tes potes cinéphiles.

</div>
