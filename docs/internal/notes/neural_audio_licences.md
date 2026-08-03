# Audit licences — Neural audio fingerprinting (V4.3 R&D)

> Document de strategie R&D pour la V4.3 (neural audio fingerprint).
> Etat : SCAFFOLD R&D, **PAS d'integration prod**, feature flag
> `audio_neural` DESACTIVE par defaut. Aucune dependance ajoutee a
> `pyproject.toml` tant que l'audit licence n'est pas valide en revue.

## Contexte

CineSort detecte deja les doublons par fingerprint audio Chromaprint
(fpcalc.exe, MIT) dans `domain/perceptual/audio_fingerprint.py` (§3
v7.5.0). La V4.3 explore un **second signal audio neuronal** pour
muscler la detection de re-encodes / re-masterings ou Chromaprint
faiblit (compression aggressive, EQ different, segments tronques).

Le score audio neural ne remplace pas Chromaprint : il vient en
**fusion ponderee** (cf. `fusion_score` dans le scaffold) avec
Chromaprint et le score video perceptuel.

`perceptual_reports != quality_reports` reste valide : ce signal est
un signal perceptuel de doublon, il n'entre **pas** dans le
quality_profile ni le global_score.

## Modeles evalues — verdict licence

| Modele | Licence | Distribution `CineSort.exe` | Verdict |
|--------|---------|------------------------------|---------|
| **panns-inference** | **MIT** | OK (compatible MIT) | **Choix #1 (par defaut)** |
| **wav2vec2** (facebook/wav2vec2-base) | **MIT** | OK (compatible MIT) | **Choix #2 (fallback general)** |
| neural-music-fp | **AGPLv3** | **INCOMPATIBLE** (proprietaire) | **REJETE** |

### 1. panns-inference (MIT) — CHOIX RETENU

- Repo : https://github.com/qiuqiangkong/panns_inference
- Licence : **MIT** (cf. `LICENSE` racine du repo)
- Fonction : tagging audio + embeddings (CNN14 / ResNet38 / Wavegram).
  Embedding 2048-d adapte au fingerprinting (similarite cosine).
- **OK pour distribution dans `dist/CineSort.exe`** : la licence MIT
  autorise la distribution binaire dans un produit proprietaire,
  moyennant inclusion de la notice MIT dans les credits (NOTICE.md
  ou panneau "A propos").
- Poids modele : ~80 MB (Cnn14_mAP=0.431.pth). Acceptable pour le
  bundle PyInstaller (memoire user : "PAS DE BUNDLE DL au 1er
  usage (tout dans EXE accepte +120MB)").
- **Strategie deploiement** : export ONNX du modele PyTorch en
  amont (offline, cote dev), bundle du `.onnx` dans `assets/models/`,
  inference via `onnxruntime` (deja dans pyproject.toml pour LPIPS).
  **Pas de torch a runtime** => bundle reste sous controle.

### 2. wav2vec2 (MIT) — FALLBACK GENERAL

- Repo : https://github.com/facebookresearch/fairseq + checkpoints
  HuggingFace (`facebook/wav2vec2-base-960h`).
- Licence : **MIT** (modele et code fairseq sous MIT depuis 2024).
- Fonction : feature extraction self-supervised (768-d hidden states).
  Plus general (parole + musique), moins specifique tagging que PANNs.
- OK pour distribution. Poids ~360 MB (base) ou ~95 MB (`base-960h`
  quantize int8). Export ONNX possible (`optimum-cli`).
- **Decision** : retenu en fallback si PANNs montre des faiblesses
  sur la musique de film (BO orchestrales, ambiance complexe).

### 3. neural-music-fp (AGPLv3) — REJETE

- Licence : **AGPL-3.0**.
- AGPL impose que toute distribution incluant ce code (meme binaire,
  meme via un service reseau) **oblige a fournir la source complete
  sous AGPL**, ce qui contamine `dist/CineSort.exe`.
- CineSort est distribue en binaire proprietaire (cf. `LICENSE`
  racine) -> **incompatible**. Rejete sans discussion.
- Note : si un jour CineSort passe en open-source AGPL, ce modele
  redevient eligible.

## Conformite distribution

Si on integre PANNs ou wav2vec2 en prod (V4.3+), il faut :

1. **NOTICE.md** racine : ajouter section "Third-party MIT models"
   citant PANNs / wav2vec2 + lien repo + texte de la licence MIT.
2. **UI "A propos"** : afficher la liste des modeles tiers et leur
   licence (pattern deja utilise pour fpcalc / ffmpeg / mediainfo).
3. **`assets/models/panns_cnn14.onnx`** : exporte offline cote dev,
   verifier le hash SHA256 au build, log warning si checksum invalide.

## Strategie integration (futur, hors scope V4.3 R&D)

- Phase R&D (aujourd'hui) : scaffold `domain/audio_neural_fp.py` +
  feature flag `audio_neural=False`, **aucune inference reelle**,
  pas d'ajout de dependance.
- Phase pilote : worktree dedie, ajout `onnxruntime` deja present,
  bundle du modele ONNX, A/B test sur biblio virtuelle (1000 films).
- Phase prod : si gain mesurable sur F1 doublons > 5% vs
  Chromaprint seul, on bascule le flag a `True` par defaut en
  version mineure (v1.6.x).

## Pieces a joindre en revue

- Lien commit PANNs declarant la licence MIT.
- Lien commit fairseq declarant MIT pour wav2vec2 (2024).
- Capture de l'AGPL de neural-music-fp pour justifier le rejet.

---

*Document cree le 2026-06-05 dans le cadre de la R&D V4.3.
Aucune integration prod ne sera faite sans validation legale
ecrite des choix MIT.*
