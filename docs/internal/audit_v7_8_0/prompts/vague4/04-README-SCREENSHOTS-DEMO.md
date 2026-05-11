# V4-04 — README enrichi + screenshots automatiques + démo GIF

**Branche** : `docs/readme-enriched-screenshots`
**Worktree** : `.claude/worktrees/docs-readme-enriched-screenshots/`
**Effort** : 4-6h
**Mode** : 🟢 Parallélisable (Playwright pour captures + texte structuré)
**Fichiers concernés** :
- `README.md` (enrichissement majeur)
- `docs/screenshots/` (nouveau — captures pour README)
- `scripts/capture_readme_screenshots.py` (nouveau — automatisation)
- `tests/test_readme_completeness.py` (nouveau)

---

## ⚠️ ÉTAPE 0 — SETUP WORKTREE (OBLIGATOIRE)

```bash
cd /c/Users/blanc/projects/CineSort
git worktree add -b docs/readme-enriched-screenshots .claude/worktrees/docs-readme-enriched-screenshots audit_qa_v7_6_0_dev_20260428
cd .claude/worktrees/docs-readme-enriched-screenshots

pwd && git branch --show-current && git status
```

---

## RÈGLES GLOBALES

RÈGLE PARALLÉLISATION : tu touches UNIQUEMENT README.md + docs/screenshots/ + le
script de capture. Aucun changement de code applicatif.

LANGUE : README en **français** (cible 2000 users francophones).

---

## CONTEXTE

Le README actuel est minimal (cf V1-01). Pour un public release qui doit attirer 2000
users (et idéalement plus via le bouche-à-oreille), il faut un README qui :
1. **Vend en 30 secondes** (héro avec capture du dashboard + 1 phrase + 3 bullets killer)
2. **Montre le produit** (5-8 captures clés)
3. **Démarre rapidement** (Quick Start en 3 commandes)
4. **Documente l'essentiel** (features, FAQ, screenshots, install, build)
5. **Donne envie** (badges, stack tech, roadmap)

---

## MISSION

### Étape 1 — Lire l'existant

- `README.md` actuel
- `LICENSE` (MIT — V1-01)
- `CLAUDE.md` (pour comprendre les features clés à mettre en avant)

### Étape 2 — Script capture screenshots

Crée `scripts/capture_readme_screenshots.py` :

```python
"""V4-04 — Capture les screenshots du README via Playwright sur le dashboard local.

Usage:
  1. Lancer l'app dans un autre terminal : python app.py
  2. Lancer ce script : python scripts/capture_readme_screenshots.py

Génère:
  docs/screenshots/01_home.png
  docs/screenshots/02_library.png
  docs/screenshots/03_quality.png
  docs/screenshots/04_validation.png
  docs/screenshots/05_settings.png
  docs/screenshots/06_film_detail.png
  docs/screenshots/07_dashboard_distant.png
  docs/screenshots/08_themes_4.png  (mosaïque 4 thèmes)
"""
from __future__ import annotations
import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DASHBOARD_URL = "http://127.0.0.1:8642/dashboard/"
OUTPUT_DIR = Path("docs/screenshots")
VIEWPORTS = {"default": (1280, 800)}

CAPTURES = [
    {"route": "#/status", "filename": "01_home.png", "wait_text": "Accueil"},
    {"route": "#/library", "filename": "02_library.png", "wait_text": "Bibliothèque"},
    {"route": "#/quality", "filename": "03_quality.png", "wait_text": "Qualité"},
    {"route": "#/validation", "filename": "04_validation.png", "wait_text": "Validation"},
    {"route": "#/settings", "filename": "05_settings.png", "wait_text": "Paramètres"},
    # film detail nécessite un row valide → adapter ou skip si vide
]


async def main():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("⚠ Playwright non installé. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("CINESORT_API_TOKEN", "")
    if not token:
        print("⚠ Variable CINESORT_API_TOKEN manquante (cf settings.json -> rest_api_token)")
        sys.exit(1)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()

        # Login via injection token (skip page de login)
        await page.goto(f"{DASHBOARD_URL}?ntoken={token}&native=1")
        await page.wait_for_load_state("networkidle")

        for cap in CAPTURES:
            await page.evaluate(f"window.location.hash = '{cap['route']}'")
            await page.wait_for_timeout(800)  # laisser la transition + render
            try:
                await page.wait_for_selector(f"text={cap['wait_text']}", timeout=5000)
            except Exception:
                logger.warning(f"Texte '{cap['wait_text']}' pas trouvé, on capture quand même")
            output = OUTPUT_DIR / cap["filename"]
            await page.screenshot(path=str(output), full_page=False)
            print(f"✅ {output}")

        # Capture mosaïque 4 thèmes (bonus visuel)
        for theme in ["studio", "cinema", "luxe", "neon"]:
            await page.evaluate(f"document.body.dataset.theme = '{theme}'")
            await page.wait_for_timeout(400)
            output = OUTPUT_DIR / f"theme_{theme}.png"
            await page.screenshot(path=str(output), full_page=False)
            print(f"✅ {output}")

        await browser.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
```

⚠ Adapter le pattern de login si Playwright a changé. Si l'app a déjà un script de
captures dans `tests/e2e/visual_catalog.py`, tu peux le réutiliser/adapter.

### Étape 3 — Lance et collecte les screenshots

```bash
# Terminal 1
.venv313/Scripts/python.exe app.py

# Terminal 2 (en parallèle)
CINESORT_API_TOKEN=<ton-token> .venv313/Scripts/python.exe scripts/capture_readme_screenshots.py
```

Les screenshots vont dans `docs/screenshots/`.

### Étape 4 — Mosaïque 4 thèmes (optionnel — combinaison Pillow)

Si Pillow installé, combine les 4 thèmes en une seule image 2x2 :

```python
# scripts/combine_themes_grid.py
from PIL import Image
from pathlib import Path

themes = ["studio", "cinema", "luxe", "neon"]
imgs = [Image.open(f"docs/screenshots/theme_{t}.png") for t in themes]
w, h = imgs[0].size
grid = Image.new("RGB", (w * 2, h * 2))
for i, img in enumerate(imgs):
    x, y = (i % 2) * w, (i // 2) * h
    grid.paste(img, (x, y))
grid.thumbnail((1600, 1200))  # réduire pour README
grid.save("docs/screenshots/themes_grid.png", optimize=True, quality=85)
```

### Étape 5 — Démo GIF (optionnel — si capacité)

Pour un GIF demo, deux options :
- **A** : utiliser Playwright + `page.video()` pour enregistrer un workflow
  (scan → review → apply), puis convertir avec ffmpeg en GIF. Lourd.
- **B** : laisser un placeholder dans le README (`<!-- TODO: ajouter GIF demo -->`)
  et l'utilisateur enregistrera plus tard avec un outil comme ScreenToGif (Windows
  natif). C'est plus pratique pour avoir un GIF de qualité avec curseur visible.

→ Préfère **B** (laisse placeholder + instructions). Documente ça dans le README.

### Étape 6 — Réécrire le README

Remplace `README.md` par :

```markdown
<div align="center">

<img src="assets/cinesort.ico" width="128" alt="CineSort logo" />

# CineSort

**Le tri-renommage automatique de ta bibliothèque de films, sans prise de tête.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)
![Windows](https://img.shields.io/badge/platform-Windows-lightgrey.svg)
[![Tests](https://img.shields.io/badge/tests-3643%20passing-green.svg)](#)
[![Coverage](https://img.shields.io/badge/coverage-82%25-green.svg)](#)

[Quick Start](#-quick-start) · [Features](#-fonctionnalités) · [Captures](#-captures-décran) · [FAQ](#-faq) · [Contribuer](CONTRIBUTING.md)

</div>

---

![Capture du dashboard](docs/screenshots/02_library.png)

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

1. Télécharge le `.exe` depuis [Releases](https://github.com/PLACEHOLDER/cinesort/releases/latest)
2. Lance — pas d'install, pas d'admin, autonome
3. Au premier démarrage, suis le wizard (5 étapes)

### Option 2 : Source

```bash
git clone https://github.com/PLACEHOLDER/cinesort.git
cd cinesort
python -m venv .venv313
.venv313\Scripts\activate
pip install -r requirements.txt
python app.py
```

Prérequis : Python 3.13, Windows 10/11.

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

<!-- TODO : démo GIF (workflow scan → review → apply en ~10s) -->
<!-- Outil recommandé : ScreenToGif (https://www.screentogif.com/) -->

## 🎯 Fonctionnalités

### Détection et renommage
- Extraction titre/année depuis NFO, dossier, filename, TMDb (avec fallback intelligent)
- Profils de renommage (default, plex, jellyfin, quality, custom) — 20 variables
- Détection séries TV (S01E01, 1x01, "Saison N Episode N")
- Multi-root (plusieurs dossiers racine en un seul scan)

### Analyse qualité
- Probe ffprobe + mediainfo (résolution, codec, bitrate, audio, sous-titres)
- Score perceptuel **réel** (LPIPS, HDR10+, Dolby Vision, banding, grain v2)
- Détection upscale suspect, re-encode dégradé, faux 4K (FFT 2D)
- Comparaison qualité doublons (7 critères pondérés)

### Sécurité opérations
- `dry-run` obligatoire avant tout apply
- Journal write-ahead (atomicité crash-safe)
- Undo par film (granulaire)
- Backup auto SQLite (avant migration + après apply, rotation 5)
- Pre-check espace disque avant apply

### Intégrations
- **TMDb** — métadonnées + posters + sagas
- **Jellyfin** — refresh library, sync watched-state, validation cohérence
- **Plex** — refresh library, sync report
- **Radarr** — sync bidirectionnelle, propose upgrades qualité

### Interface
- 4 thèmes atmosphériques (tier colors invariantes)
- Mode débutant / expert (cache options avancées)
- Tooltips ⓘ glossaire métier (18 termes)
- Compteurs sidebar dynamiques
- Drawer mobile pour validation distante
- Raccourcis clavier complets (Alt+1-7, Ctrl+K palette, ?, Esc, etc.)
- Empty states + skeleton loaders + draft auto

## 📚 Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — comment contribuer
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — code de conduite
- [SECURITY.md](SECURITY.md) — politique de sécurité
- [BILAN_CORRECTIONS.md](BILAN_CORRECTIONS.md) — historique des phases
- Vue Aide intégrée dans l'app (FAQ + glossaire)

## 🛠️ Stack technique

- Python 3.13 + pywebview ≥ 5.0
- SQLite WAL (19 migrations)
- requests + segno (QR) + rapidfuzz (matching)
- onnxruntime + numpy (LPIPS perceptuel)
- ffprobe / mediainfo (probe vidéo)
- Ruff (lint+format) + unittest (3643 tests, 82% coverage)
- PyInstaller (~51 MB onefile EXE)

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
est dans la roadmap long terme (cf [issues](https://github.com/PLACEHOLDER/cinesort/issues)).

### Comment configurer le dashboard distant ?

Paramètres → API REST → activer + définir un token long (≥ 32 chars). Accède au
dashboard depuis ton téléphone via `http://<ip-pc>:8642/dashboard/`.

## 🗺️ Roadmap

- ✅ v7.6.0 — Refonte UI v5 (4 thèmes, design system)
- ✅ v7.6.0-dev — Audit complet, polish public-launch
- ⬜ v7.7.0 — Fusion desktop/dashboard (1 seule UI)
- ⬜ v8.0.0 — Port Linux/Mac, i18n EN, plugin marketplace
- ⬜ Long terme — App mobile companion, analyse audio musique

## 📄 Licence

[MIT](LICENSE) — utilise, modifie, distribue librement.

## 🙏 Crédits

- TMDb pour les métadonnées
- ffmpeg/mediainfo pour le probe vidéo
- Contributor Covenant pour le code de conduite
- Tous les early adopters qui ont testé en beta privée 🍿

---

<div align="center">

**Tu as aimé CineSort ?** Mets une ⭐ sur GitHub, partage à tes potes cinéphiles.

[Signaler un bug](https://github.com/PLACEHOLDER/cinesort/issues/new?template=bug_report.yml) · [Discussions](https://github.com/PLACEHOLDER/cinesort/discussions) · [Releases](https://github.com/PLACEHOLDER/cinesort/releases)

</div>
```

⚠ Tous les `PLACEHOLDER` sont à remplacer manuellement après création du repo public.

### Étape 7 — Tests README

Crée `tests/test_readme_completeness.py` :

```python
"""V4-04 — Vérifie la complétude du README."""
from __future__ import annotations
import unittest
from pathlib import Path


class ReadmeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = Path("README.md").read_text(encoding="utf-8")

    def test_essential_sections(self):
        for section in ["Quick Start", "Captures", "Fonctionnalités",
                        "Stack technique", "FAQ", "Licence"]:
            self.assertIn(section, self.readme, f"Section manquante: {section}")

    def test_has_badges(self):
        # Au moins 3 badges (license, python, tests)
        self.assertGreaterEqual(self.readme.count("![]("), 0)
        self.assertGreaterEqual(self.readme.count("img.shields.io"), 3)

    def test_has_screenshots(self):
        # Au moins 4 références à docs/screenshots
        self.assertGreaterEqual(self.readme.count("docs/screenshots/"), 4)

    def test_links_to_community_files(self):
        for f in ["CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "LICENSE"]:
            self.assertIn(f, self.readme, f"Lien manquant: {f}")

    def test_no_lorem_ipsum(self):
        for placeholder in ["lorem ipsum", "TODO:", "FIXME"]:
            self.assertNotIn(placeholder.lower(), self.readme.lower(),
                            f"Placeholder non remplacé: {placeholder}")

    def test_screenshots_exist(self):
        screenshots_dir = Path("docs/screenshots")
        self.assertTrue(screenshots_dir.is_dir(), "docs/screenshots/ manquant")
        # Au moins 4 PNG
        pngs = list(screenshots_dir.glob("*.png"))
        self.assertGreaterEqual(len(pngs), 4, f"Trop peu de screenshots: {len(pngs)}")


if __name__ == "__main__":
    unittest.main()
```

### Étape 8 — Vérifications

```bash
.venv313/Scripts/python.exe -m unittest tests.test_readme_completeness -v 2>&1 | tail -10
.venv313/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3
```

### Étape 9 — Commits

- `docs(readme): rewrite README with hero + features + screenshots + FAQ (V4-04)`
- `feat(scripts): playwright capture script for README screenshots`
- `docs(screenshots): add README captures (5 vues + 4 themes grid)`
- `test(readme): assert essential sections + screenshots presence`

---

## LIVRABLES

- README.md totalement réécrit (hero + 6 sections + FAQ)
- Script `scripts/capture_readme_screenshots.py` reproductible
- 5+ screenshots PNG dans `docs/screenshots/`
- (Optionnel) mosaïque thèmes via Pillow
- Test de complétude
- Tous les `PLACEHOLDER` URL/email documentés (à remplacer après création repo)
- 4 commits sur `docs/readme-enriched-screenshots`
