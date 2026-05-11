# Documentation dev CineSort

Point d'entree court pour le travail dev, le preview UI et les documents de chantier.

## Build et verification
- Installation dev: `python -m pip install -r requirements-dev.txt`
- Verification locale: `check_project.bat`
- Hooks locaux: `pre-commit install`
- Verification hooks: `pre-commit run --all-files`
- Build Windows QA + release: `build_windows.bat`
- ZIP source: `python scripts/package_zip.py --source`
- ZIP QA onedir: `python scripts/package_zip.py --qa`
- ZIP release onefile: `python scripts/package_zip.py --release`
- Tous les ZIP: `python scripts/package_zip.py --all`

## Packaging Windows
- Build QA: `dist/CineSort_QA/CineSort.exe`
- Build release: `dist/CineSort.exe`
- ZIP QA: `packages/CineSort_<version>_qa_win64.zip`
- ZIP release: `packages/CineSort_<version>_win64.zip`
- `build_windows.bat` verifie et package les artefacts QA + release.
- CI Windows: `.github/workflows/windows-ci.yml`
- La CI rejoue `check_project.bat`, les captures/visual check preview, puis `build_windows.bat`.
- La signature code est optionnelle en CI: si `WINDOWS_CODESIGN_CERT_BASE64` et `WINDOWS_CODESIGN_CERT_PASSWORD` sont absents, l'etape annonce un `SKIP` explicite et continue sans faux-semblant.
- Si la signature est activee, la CI resigne `dist/CineSort.exe` et `dist/CineSort_QA/CineSort.exe`, puis regenere les ZIP QA/release.
- Le workflow CI supporte aussi `workflow_dispatch` pour relancer un build Windows sans nouveau commit.
- La validation d'un vrai run GitHub Actions ne peut pas etre prouvee localement sans remote/push actif: la coherence locale entre script, workflow et doc est verifiee ici, mais le run distant reste a confirmer sur la forge.

## Secret local TMDb
- Si `remember_key` est active, la cle TMDb est stockee via la protection Windows DPAPI du compte utilisateur courant.
- Le fichier `settings.json` ne conserve plus la cle en clair.
- Si la protection Windows n'est pas disponible, CineSort n'enregistre pas la cle et le signale.
- Une ancienne cle legacy en clair reste lisible pour compatibilite, puis est migree vers le stockage protege au prochain enregistrement des parametres.

## Preview UI et captures
- Lancement preview: `python scripts/run_ui_preview.py --dev`
- Captures: `python scripts/capture_ui_preview.py --dev --recommended`
- Controle visuel leger: `python scripts/visual_check_ui_preview.py --dev`
- Refresh baseline critique: `python scripts/visual_check_ui_preview.py --dev --refresh-baseline`
- Guide detaille: `web/preview/README.md`
- L'ancien prototype UI Next est archive dans `docs/internal/archive/ui_next_20260319/` et ne fait plus partie du runtime actif.

## Preuves live opt-in
- La verification standard reste `check_project.bat`.
- Les preuves live externes n'en font pas partie et ne doivent pas rendre le gate standard fragile.
- Commande orchestree: `python scripts/run_live_verification.py`
- Suite TMDb: definir `CINESORT_LIVE_TMDB=1` et `CINESORT_TMDB_API_KEY`, puis lancer `python -m unittest discover -s tests/live -p "test_tmdb_live.py" -v`
- Sans `CINESORT_TMDB_API_KEY`, la suite TMDb doit rester en `SKIP` explicite: cela signifie que la preuve live n'a pas ete rejouee, pas qu'elle est validee.
- Suite probe: definir `CINESORT_LIVE_PROBE=1`, optionnellement `CINESORT_FFPROBE_PATH` / `CINESORT_MEDIAINFO_PATH`, puis lancer `python -m unittest discover -s tests/live -p "test_probe_tools_live.py" -v`
- Suite pywebview native: definir `CINESORT_LIVE_PYWEBVIEW=1`, puis lancer `python -m unittest discover -s tests/live -p "test_pywebview_native_live.py" -v`
- Media de test probe: si aucun fichier n'est fourni via `CINESORT_MEDIA_SAMPLE_PATH`, la suite tente de generer un media temporaire via `ffmpeg` present dans `PATH`.
- Des `SKIP` sont normaux si le mode live n'est pas active ou si un prerequis manque. Les messages de `SKIP` indiquent quoi fournir.

## Stress opt-in
- Les scenarios gros volumes ne font pas partie du gate standard.
- Suite stress: definir `CINESORT_STRESS=1`, puis lancer `python -m unittest tests.stress.large_volume_flow -v`
- Les scenarios actuels couvrent `1000` et `5000` dossiers synthetiques pour prouver l'absence de crash et la coherence generale du plan/duplicates/apply.

## Documents stables utiles
- Vision produit: `docs/product/VISION_V7_FR.md`
- Notes de version: `docs/releases/V7_1_NOTES_FR.md`
- Design undo: `docs/design/UNDO_7_2_0_A_DESIGN_FR.md`
- Design apply: `docs/design/APPLY_ROWS_7E_DESIGN_FR.md`

## Documents internes
- Audits et memos ponctuels: `docs/internal/audits/`
- Worklogs et historiques de chantier: `docs/internal/worklogs/`
- Plans et cadrages internes: `docs/internal/plans/`
