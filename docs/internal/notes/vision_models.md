# Vision models — V4.2 DINOv3/CLIP embeddings (SCAFFOLD)

> Document de strategie pour la pipeline V4.2 "similar films via vision
> embeddings". Le scaffold est en place dans `cinesort/domain/vision_embedding.py`
> et `cinesort/infra/integrations/dinov3_model.py`. Feature flag
> `visual_similarity` DESACTIVEE par defaut (cf
> `VISUAL_SIMILARITY_FEATURE_FLAG` dans le module domain).

## Contexte

- **Etat actuel (2026-06-05)** : V4.2 est en phase scaffold. Aucun appel
  runtime, le flag est OFF.
- **Objectif** : produire un embedding visuel (vecteur 384 ou 512 floats)
  par film, stocke dans `vec_films_hash` (cf
  `cinesort/infra/vector_search/sqlite_vec_adapter.py`), pour de la
  recherche kNN "films visuellement similaires".
- **Pipeline cible** :
  1. `extract_keyframes(video_path, n=10)` — ffmpeg subprocess direct.
  2. `embed_frames(frames, model_loader=load_model)` — ONNX Runtime CPU.
  3. `aggregate_embeddings(...)` — mean pool L2-normalise, 1 vecteur/film.
  4. Stockage via `SqliteVecAdapter.add_embedding(film_id, vec)`.

## Choix du modele

### Option A (preferable) — DINOv3-small ONNX (~80 MB)

- **Pourquoi** : self-supervised vision transformer Meta, excellent pour
  similarite visuelle sans entrainement specifique. Dimension 384,
  fonctionne tres bien en CPU pour des images 224x224.
- **Pour** : taille raisonnable (~80 MB), pas de tokenizer requis (vs
  CLIP qui necessite la branche texte si on veut faire du text->image).
- **Source ONNX** : convertir depuis `facebook/dinov3-small` via
  `optimum-cli export onnx` (script a documenter ici quand fait).

### Option B (fallback) — OpenCLIP ViT-B/32 ONNX (~150 MB)

- **Pourquoi** : standard de l'industrie, ecosysteme mature, accepte aussi
  des requetes texte ("trouve les films qui ressemblent a un film noir").
  Dimension 512.
- **Contre** : ~2x plus gros que DINOv3-small (mais memoire user "bundle
  size pas un frein, +120MB accepte" couvre largement).
- **Source ONNX** : `openclip` distribue deja des poids ONNX prets.

### Decision actuelle

DINOv3-small par defaut (`MODEL_FILENAME_DEFAULT = "dinov3_small.onnx"`,
`EMBEDDING_DIM_DEFAULT = 384` dans `dinov3_model.py`). Pour basculer sur
OpenCLIP : changer ces deux constantes + mettre a jour
`DEFAULT_EMBEDDING_DIM` dans `vision_embedding.py` (384 -> 512).

## Bundling PyInstaller (a faire manuellement)

> Memoire user : *"PAS DE BUNDLE DL au 1er usage (tout dans EXE accepte
> +120MB)"*. Le `.onnx` doit etre DANS le bundle, pas telecharge au runtime.

### Etapes

1. **Recuperer le modele ONNX** :

   ```bash
   # Option A — DINOv3-small via optimum
   pip install optimum[exporters]
   optimum-cli export onnx --model facebook/dinov3-small dinov3_small_export/
   # Le fichier final est `dinov3_small_export/model.onnx` (~80 MB).
   ```

2. **Placer le `.onnx` dans le repo** :

   ```
   cinesort/data/models/dinov3_small.onnx
   ```

   (cree le dossier `cinesort/data/models/` si absent — c'est le 3e
   candidat dans `_default_model_path()`.)

3. **Mettre a jour `CineSort.spec`** pour PyInstaller :

   ```python
   # CineSort.spec — section Analysis.datas
   datas=[
       # ... entrees existantes ...
       ("cinesort/data/models/dinov3_small.onnx", "models"),
   ],
   ```

   Le 2e argument `"models"` correspond au sous-dossier dans `_MEIPASS`
   (cf `_default_model_path()` qui cherche `_MEIPASS/models/<filename>`).

4. **Verifier l'ajout dans le bundle** :

   ```powershell
   pyinstaller --noconfirm CineSort.spec
   # Verifier la taille du dist/CineSort.exe (~80 MB de plus qu'avant)
   # et que le .onnx est embarque (extraire l'EXE pour debug si besoin).
   ```

5. **Verifier `onnxruntime` dans `requirements.txt`** : deja present pour
   LPIPS (cf `cinesort/domain/perceptual/lpips_compare.py`). Aucun ajout
   de dependance Python necessaire pour V4.2. Surtout PAS d'ajout de
   `torch` (cf `torch_cpu_strategy.md`).

## Feature flag

Deux niveaux :

- `cinesort/domain/vision_embedding.py:VISUAL_SIMILARITY_FEATURE_FLAG`
  (defaut `False`) — gate la pipeline domain.
- `cinesort/ui/api/similar_films_facade.py:SIMILAR_FILMS_FEATURE_FLAG`
  (defaut `False`) — gate les endpoints UI.

Activation V4.2 runtime : passer les deux a `True` simultanement, ET
verifier que `vec0.dll` (sqlite-vec) est aussi bundle.

## Backward compat

- Le scaffold actuel n'introduit AUCUNE API publique sur `CineSortApi`.
- `cinesort/data/models/` est un nouveau dossier optionnel : son absence
  ne casse pas le scaffold (les fonctions retournent `[]` quand flag OFF).
- La table `vec_films_hash` existe deja (cf V3.3 scaffold sqlite-vec) et
  n'a pas besoin de migration supplementaire pour stocker les embeddings
  V4.2 — la dimension est definie a la creation de la table.

## Tests recommandes (a creer en meme temps que le runtime V4.2)

- `tests/test_vision_embedding_scaffold.py` :
  - flag OFF : `extract_keyframes`/`embed_frames` retournent `[]`.
  - `cosine_similarity` : cas norme nulle, shapes incompat, valeurs bornees.
  - `aggregate_embeddings` : mean pool + L2 norm correct.
- `tests/test_dinov3_model_scaffold.py` :
  - `load_model()` leve `VisionModelUnavailableError` si .onnx absent.
  - `cosine_similarity` : symetrie, identite (sim(v,v)==1.0).
  - `reset_cache()` force re-load.

## References

- Modele Meta DINOv3 : <https://github.com/facebookresearch/dinov3>
- OpenCLIP : <https://github.com/mlfoundations/open_clip>
- sqlite-vec (storage) : `docs/internal/notes/sqlite_vec_setup.md`
- Torch strategy (pourquoi ONNX et PAS torch) : `docs/internal/notes/torch_cpu_strategy.md`

---

*Last updated : 2026-06-05 (scaffold V4.2 cree, runtime a venir).*
