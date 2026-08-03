# Stratégie torch-cpu (préventif V3.2)

> Document de stratégie pour le jour où CineSort devra ajouter `torch` à ses
> dépendances. Aujourd'hui (v1.5.2-beta), **torch n'est PAS une dépendance** :
> on utilise `onnxruntime` pour LPIPS (§11) et les inférences perceptuelles.
> Ce document est préventif, à appliquer si/quand un module futur nécessite
> torch directement.

## Contexte

- **Etat actuel (2026-06-05)** : `pyproject.toml` ne déclare PAS `torch`.
  Vérifié dans `[project.dependencies]` et dans `requirements*.txt`.
- **Pourquoi anticiper ?** : `torch` par défaut tire la stack CUDA complète
  (~3.5 GB de DLLs nvidia/cublas), ce qui ferait exploser le bundle PyInstaller
  qui vise actuellement ~150 MB. La variante `torch-cpu` (~200 MB) est suffisante
  pour LPIPS et toute inférence CineSort, qui ne nécessite pas de GPU.
- **Mémoire utilisateur** : *"PAS DE BUNDLE DL au 1er usage (tout dans EXE
  accepté +120MB)"* — donc on bundle torch-cpu directement, on ne télécharge pas
  à l'exécution.

## Si jamais on doit ajouter torch

### 1. Installation : utiliser le canal CPU explicite

Le tarball PyPI par défaut (`pip install torch`) installe la variante CUDA.
Pour forcer la variante CPU (~10x plus petite), passer par l'index officiel :

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

Ou via `uv` :

```bash
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

### 2. pyproject.toml : pin via [tool.uv.sources]

Si on utilise `uv` comme installateur (recommandé pour CI reproductible) :

```toml
[project]
dependencies = [
    "torch>=2.5,<3",
    # ... autres deps
]

[tool.uv.sources]
torch = { index = "pytorch-cpu" }

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true
```

### 3. requirements-build.txt : ajouter `--index-url`

Si on garde la voie `pip install -r requirements-build.txt` (CI windows-latest) :

```
-r requirements.txt
--index-url https://download.pytorch.org/whl/cpu
--extra-index-url https://pypi.org/simple
torch>=2.5,<3
torchvision>=0.20,<1  # optionnel, seulement si transforms.functional utilisé
pyinstaller>=6.20.0
pillow>=12.2
```

Important : `--extra-index-url https://pypi.org/simple` sinon les autres deps
(pyinstaller, pillow, etc.) ne seront pas résolues depuis le canal CPU.

### 4. cinesort.spec : excludes torch.cuda + nvidia (déjà préventifs, voir ci-dessous)

Même avec `torch-cpu`, PyInstaller peut bundler des sous-modules CUDA inutiles
si un autre package les déclare optionnellement. **Les excludes torch.cuda*,
torch.distributed, nvidia*, cublas* sont déjà pré-ajoutés dans `cinesort.spec`**
(voir entrée "Vague V3.2 préventif" dans le bloc `excludes`).

Ces excludes sont **zéro-cost** quand torch est absent (PyInstaller ignore
silencieusement un module exclu qui n'existe pas dans l'environnement).

## Validation post-ajout

Quand torch sera réellement ajouté, lancer ces vérifications :

1. **Taille bundle** : `dist/CineSort.exe` < 400 MB (target : ~350 MB).
   Si > 500 MB, vérifier que les excludes nvidia/cublas ont bien matché
   (PyInstaller affiche `WARNING: Hidden import 'X' not found` pour excludes
   inutiles, mais ne dit rien quand l'exclude a effectivement retiré du code).
2. **Test de chargement** : `python -c "import torch; print(torch.cuda.is_available())"`
   doit retourner `False` (pas de CUDA dispo dans build CPU).
3. **Test runtime CineSort** : Run perceptual quality scoring sur un sample
   et vérifier qu'il n'y a pas de `RuntimeError: CUDA driver missing`.

## Excludes pré-ajoutés (V3.2 préventif, 2026-06-05)

Les excludes suivants sont déjà dans `cinesort.spec` même si torch est absent.
Si torch absent, ils sont ignorés silencieusement (zero-cost). Si torch ajouté
plus tard, ils protègent automatiquement contre l'inclusion CUDA.

```
torch.cuda
torch.distributed
torch.backends.cuda
torch.backends.cudnn
nvidia
nvidia_cublas_cu12
nvidia_cuda_cupti_cu12
nvidia_cuda_nvrtc_cu12
nvidia_cuda_runtime_cu12
nvidia_cudnn_cu12
nvidia_cufft_cu12
nvidia_curand_cu12
nvidia_cusolver_cu12
nvidia_cusparse_cu12
nvidia_nccl_cu12
nvidia_nvjitlink_cu12
nvidia_nvtx_cu12
cublas
cudnn
```

## Références

- PyTorch CPU wheels : https://pytorch.org/get-started/locally/ (sélectionner "CPU")
- uv sources : https://docs.astral.sh/uv/concepts/projects/dependencies/#index
- PyInstaller excludes : https://pyinstaller.org/en/stable/spec-files.html#using-spec-files
