# 05 QA Polish

Objectif:
- verifier l'execution finale de chaque lot UI/design

Checklist minimale:
- capture preview avant/apres
- verification Playwright sur l'ecran reel
- coherence de wording
- alignements et espacements
- etats vides, denses et critiques
- lisibilite desktop
- non-regression fonctionnelle

Commandes utiles:
- `python scripts/capture_ui_preview.py --dev --recommended`
- `python scripts/visual_check_ui_preview.py --dev`
- `pre-commit run --all-files`
- `check_project.bat`
