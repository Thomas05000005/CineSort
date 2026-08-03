# assets/models/

<!-- Fix audit 2026-05-25 (v1.5.3) Vague H : documenter les datas optionnels du bundle PyInstaller -->

Ce dossier contient les modèles ML utilisés par l'analyse perceptuelle de CineSort.

## Fichier attendu

### `lpips_alexnet.onnx`

Modèle ONNX **LPIPS (Learned Perceptual Image Patch Similarity)** basé sur AlexNet pré-entraîné.

- **Utilisation** : comparaison perceptuelle entre 2 frames (détection de doublons visuels v7.5.0 §11)
- **Module concerné** : `cinesort.domain.perceptual.lpips_compare`
- **Taille typique** : ~5-10 MB
- **Source de téléchargement** : voir `docs/build/lpips_model.md` (à jour pour chaque release)

## Comportement du bundle EXE

Le `CineSort.spec` bundle ce modèle **conditionnellement** :

```python
# CineSort.spec L228-230
if Path("assets/models/lpips_alexnet.onnx").exists():
    datas += [("assets/models/lpips_alexnet.onnx", "assets/models")]
```

Si le fichier est absent au moment du build :
- Le bundle se construit sans erreur.
- L'EXE fonctionne normalement, **LPIPS est désactivé gracieusement** (fallback sur SSIM/PSNR).
- L'utilisateur peut tout de même utiliser tout le reste de l'analyse perceptuelle (audio, grain, HDR, etc.).

## Pour les développeurs

Pour activer LPIPS dans une build dev :
1. Télécharger `lpips_alexnet.onnx` depuis la source officielle (lien dans `docs/build/lpips_model.md`).
2. Placer le fichier dans ce dossier.
3. Relancer `build_windows.bat` ou `pyinstaller --clean --noconfirm CineSort.spec`.
