# PLAN v7.5.0 — Analyse approfondie doublons + Espace disque + Récap hebdo

**Date de rédaction :** 2026-04-22
**Cible version :** 7.5.0
**Effort estimé total :** 100-120 heures (~3 semaines de travail focus)
**Statut :** En attente de validation utilisateur

---

## Sommaire

1. [Vision globale](#1-vision-globale)
2. [Phase 0 — Renforcement du moteur perceptual](#2-phase-0--renforcement-du-moteur-perceptual)
3. [Phase 1 — Widget espace disque home](#3-phase-1--widget-espace-disque-home)
4. [Phase 2 — Modale récap hebdomadaire animée](#4-phase-2--modale-récap-hebdomadaire-animée)
5. [Phase 3 — Détection doublons renforcée + bouton d'analyse](#5-phase-3--détection-doublons-renforcée--bouton-danalyse)
6. [Phase 4 — Modale deep-compare ultra-complète](#6-phase-4--modale-deep-compare-ultra-complète)
7. [Phase 5 — Dashboard distant : parité](#7-phase-5--dashboard-distant-parité)
8. [Phase 6 — Tests](#8-phase-6--tests)
9. [Phase 7 — Documentation & build](#9-phase-7--documentation--build)
10. [Récapitulatif effort](#10-récapitulatif-effort)
11. [Dépendances ajoutées](#11-dépendances-ajoutées)

---

## 1. Vision globale

v7.5.0 transforme CineSort d'une app de scoring technique (note actuelle 9.9/10) en **plateforme d'analyse forensique de qualité film**, avec un niveau d'analyse comparable aux outils pro (MSU VQMT, Netflix VMAF, DaVinci Resolve).

**Principe directeur :** l'analyse approfondie est **déclenchée manuellement** par l'utilisateur sur 2 films précis, jamais en auto-run global. Elle fournit **tous les angles techniques** pour trancher un doublon, avec un score composite final pondéré et un visuel clair.

**Les 3 chantiers :**
- **Widget espace disque** enrichi sur la home (démasquer l'existant + sparkline 7j + modale clic)
- **Récap hebdomadaire animé** (films ajoutés/supprimés/doublons, 3 tabs, modale animée)
- **Analyse approfondie doublons** = le gros chantier (Phase 0 renforcement moteur + Phase 4 modale side-by-side)

---

## 2. Phase 0 — Renforcement du moteur perceptual

**Effort total : 52-62 heures.** C'est la phase la plus lourde. Elle prépare le terrain pour que la modale deep-compare (Phase 4) s'appuie sur un moteur grade-studio.

### 2.1 — Parallélisme audio/vidéo (3h)

**Objectif :** diviser par 2 le temps d'analyse en lançant l'audio en parallèle des frames vidéo.

**Fichiers touchés :**
- [cinesort/ui/api/perceptual_support.py](../../../cinesort/ui/api/perceptual_support.py) : refactor `_execute_perceptual_analysis`

**Modifications :**
- Créer un `ThreadPoolExecutor(max_workers=2)` dans la fonction orchestratrice.
- **Tâche 1 (vidéo)** : `extract_representative_frames` → `run_filter_graph` → `analyze_video_frames` → `analyze_grain`.
- **Tâche 2 (audio)** : `analyze_audio_perceptual` — totalement indépendante, peut tourner en parallèle.
- Utiliser `concurrent.futures.as_completed()` avec timeout global.
- Ajouter `-threads 0` à toutes les commandes ffmpeg dans [ffmpeg_runner.py](../../../cinesort/domain/perceptual/ffmpeg_runner.py) (utilise tous les cœurs dispo).

**Gain mesuré attendu :** ~2.5x (4-5 min → 1.5-2 min pour film 1080p 2h).

---

### 2.2 — Progress callbacks & UI temps réel (4h)

**Objectif :** widget d'analyse en cours avec 2 barres parallèles (vidéo + audio) + infos réelles sur l'étape en cours.

**Fichiers créés :**
- [cinesort/domain/perceptual/progress.py](../../../cinesort/domain/perceptual/progress.py) (nouveau)

**Contenu :**
```python
@dataclass
class ProgressEvent:
    task_id: str            # "pair_42_row17_row23"
    stream: str             # "video_a" | "video_b" | "audio_a" | "audio_b"
    step: str               # "frames_extraction" | "filter_graph" | "video_analysis" | "grain" | "audio_loudnorm" | "audio_astats" | "audio_clipping" | "audio_fingerprint" | "audio_mel"
    current: int | None     # ex: 18 (frame extraite 18)
    total: int | None       # ex: 30 (total frames)
    pct: float              # 0-100
    eta_seconds: float | None
    message: str            # texte localisé FR pour l'UI
    timestamp: float        # time.time()
```

Classe `PerceptualProgressRegistry` (singleton thread-safe) qui :
- Stocke les derniers événements par `task_id`
- Expose `emit(event)`, `snapshot(task_id)`, `clear(task_id)`
- TTL 5 min après complétion pour éviter fuites mémoire

**Nouvel endpoint** : `get_perceptual_progress(task_id) -> list[ProgressEvent]` dans [cinesort_api.py](../../../cinesort/ui/api/cinesort_api.py).

**Injection dans les fonctions existantes** :
- `extract_representative_frames()` émet après chaque frame extraite
- `run_filter_graph()` émet au début/fin du pass ffmpeg
- `analyze_audio_perceptual()` émet à chaque sous-étape (loudnorm pass 1, pass 2, astats, clipping, fingerprint, mel)

**UI frontend** : polling toutes les 500 ms depuis la modale deep-compare, mise à jour des 4 barres.

---

### 2.3 — Chromaprint audio fingerprint (4h)

**Objectif :** détecter si 2 fichiers ont **la même source audio** même ré-encodée.

**Nouvelle dépendance :** `pyacoustid>=1.3.0` (~5 MB).

**Fichiers touchés :**
- [cinesort/domain/perceptual/audio_perceptual.py](../../../cinesort/domain/perceptual/audio_perceptual.py)

**Nouvelles fonctions :**
- `compute_audio_fingerprint(ffmpeg_path, media_path, segment_start_s=60, duration_s=30) -> str` :
  - Extrait 30s du milieu du fichier via ffmpeg (skip générique/crédits).
  - Calcule le fingerprint Chromaprint via `acoustid.fingerprint_file()`.
  - Retourne le fingerprint encodé base64 (compact).
- `compare_audio_fingerprints(fp_a: str, fp_b: str) -> float` :
  - Décode les 2 fingerprints.
  - Calcule la similarité 0.0-1.0 via `acoustid.compare_fingerprints`.
  - Seuil typique : ≥0.85 = même source confirmée.

**Migration SQL [016_audio_fingerprint.sql](../../../cinesort/infra/db/migrations/016_audio_fingerprint.sql)** :
```sql
ALTER TABLE quality_reports ADD COLUMN audio_fingerprint TEXT;
```

**Intégration dans `build_comparison_report()`** (Phase 4) :
- Nouveau critère "Empreinte audio" dans la comparaison
- Poids : 10% (informationnel, confirme ou infirme que c'est bien le même film)

---

### 2.4 — Scene detection (3h)

**Objectif :** échantillonner les frames aux vrais moments importants du film, pas aux timestamps uniformes naïfs.

**Setting ajouté :** `perceptual_scene_detection_enabled` (default: `true`).

**Fichiers touchés :**
- [cinesort/domain/perceptual/frame_extraction.py](../../../cinesort/domain/perceptual/frame_extraction.py)

**Nouvelles fonctions :**
- `detect_scene_keyframes(ffmpeg_path, media_path, threshold=0.3, max_count=20) -> list[float]` :
  - Lance `ffmpeg -i <file> -vf "select='gt(scene,0.3)',showinfo" -f null -`
  - Parse stderr pour extraire les timestamps (`pts_time:X.XXX`)
  - Limite à `max_count` pour contrôler la durée.
- `compute_timestamps_hybrid(duration, count=10, scene_kfs=None) -> list[float]` :
  - Si `scene_kfs` fourni : merge 50% keyframes + 50% timestamps uniformes, dédoublonné.
  - Sinon : fallback sur `compute_timestamps()` existant.

**Fallback gracieux** : si scene detection échoue (corrompu, timeout), utiliser uniformes → comportement v7.4 préservé.

---

### 2.5 — Gestion erreurs granulaire (3h)

**Objectif :** transformer les erreurs opaques en messages utilisateur actionnables.

**Fichier créé :**
- [cinesort/domain/perceptual/exceptions.py](../../../cinesort/domain/perceptual/exceptions.py)

**Hiérarchie :**
```python
class PerceptualError(Exception):
    """Erreur de base du module perceptual."""
    code: str  # ex: "FFMPEG_MISSING"
    user_message_fr: str

class FFmpegMissingError(PerceptualError):
    code = "FFMPEG_MISSING"
    user_message_fr = "FFmpeg est introuvable. Installez-le via les Réglages → Outils."

class FFmpegTimeoutError(PerceptualError):
    code = "FFMPEG_TIMEOUT"
    user_message_fr = "L'analyse FFmpeg a dépassé le délai. Le fichier est peut-être corrompu."

class CorruptFileError(PerceptualError):
    code = "CORRUPT_FILE"
    user_message_fr = "Le fichier semble corrompu (header invalide)."

class ProbeFailedError(PerceptualError):
    code = "PROBE_FAILED"
    user_message_fr = "L'analyse probe a échoué. Codec ou conteneur non supporté."

class AudioAnalysisError(PerceptualError):
    code = "AUDIO_ANALYSIS_FAILED"
    user_message_fr = "L'analyse audio a échoué."

class FrameExtractionError(PerceptualError):
    code = "FRAME_EXTRACTION_FAILED"
    user_message_fr = "Impossible d'extraire des frames."

class GPUAccelError(PerceptualError):
    code = "GPU_ACCEL_FAILED"
    user_message_fr = "L'accélération GPU a échoué. Fallback sur CPU."
```

**Refactor des `try/except` trop larges** dans les 8 fichiers du module : chaque exception remonte avec son code et son message.

**Frontend** : dans la modale deep-compare, afficher `user_message_fr` au lieu de `str(exc)`.

---

### 2.6 — GPU hardware acceleration optionnel (5h)

**Objectif :** accélérer le décodage frames via GPU (NVDEC / Quick Sync / VAAPI) si disponible.

**Fichier touché :**
- [cinesort/domain/perceptual/ffmpeg_runner.py](../../../cinesort/domain/perceptual/ffmpeg_runner.py)

**Nouvelles fonctions :**
- `detect_available_hwaccels(ffmpeg_path) -> list[str]` :
  - Lance `ffmpeg -hwaccels` → parse les lignes.
  - Retourne liste triée : `["cuda", "qsv", "vaapi", ...]` ou `[]` si aucun.
  - Cache le résultat au démarrage de l'app (1 fois).

**Nouveau setting :** `perceptual_hwaccel` avec valeurs :
- `"auto"` (défaut) : premier disponible dans l'ordre `cuda > qsv > vaapi > dxva2`.
- `"none"` : force CPU.
- `"cuda" | "qsv" | "vaapi" | "dxva2"` : force un type spécifique.

**Application :**
- Préfixer les commandes ffmpeg **de décodage** avec `-hwaccel <type> -hwaccel_output_format <type>`.
- **Ne PAS appliquer** sur `ebur128` / `astats` (pure CPU, pas de gain).

**Smoke test au premier lancement :**
- Tenter une extraction de 3 frames d'un fichier 10 MB.
- Si échec ou timeout → fallback CPU + log warning + désactivation pour la session.
- Log persistant : "GPU acceleration disabled after smoke test failure. Restart app to retry."

**Gain typique :** 2-4x sur l'extraction frames (CUDA > QSV > VAAPI).

---

### 2.7 — Métadonnées avancées (10-12h)

**Objectif :** extraire toutes les métadonnées techniques utiles depuis ffprobe, pas juste les basiques.

**Fichiers touchés :**
- [cinesort/infra/probe/normalize.py](../../../cinesort/infra/probe/normalize.py) : enrichissement `NormalizedProbe`
- [cinesort/domain/perceptual/video_analysis.py](../../../cinesort/domain/perceptual/video_analysis.py) : nouveaux champs dans `VideoPerceptual`

**Métadonnées vidéo ajoutées (8) :**

#### 2.7.1 HDR validation (MaxCLL / MaxFALL) — 1h
- Parser `side_data_list[type=Mastering display metadata]` et `side_data_list[type=Content light level metadata]` depuis ffprobe.
- Extraire : `max_cll` (cd/m²), `max_fall` (cd/m²), `mastering_display_luminance_min`, `mastering_display_luminance_max`, `mastering_display_primaries_json`.
- **Flag `hdr_metadata_invalid`** si vidéo taguée HDR mais MaxCLL manquant ou valeurs nulles.

#### 2.7.2 Dolby Vision profile — 1h
- Parser `side_data_list[type=DOVI configuration record]`.
- Extraire : `dv_version`, `dv_profile` (5/7/8.1/8.4), `dv_bl_compatibility_id`.
- Profil 7 = BL+EL (ultra rare), profil 8.1 = compatible HDR10, profil 8.4 = compatible HLG.

#### 2.7.3 Chroma subsampling — 30 min
- Parser `streams[0].pix_fmt` → mapper :
  - `yuv420p`, `yuv420p10le` → `"4:2:0"`
  - `yuv422p`, `yuv422p10le` → `"4:2:2"`
  - `yuv444p`, `yuv444p10le` → `"4:4:4"`
  - `yuva420p` → `"4:2:0+alpha"` etc.

#### 2.7.4 Color space metadata — 1h
- Extraire : `color_primaries` (bt709, bt2020, bt601, etc.), `color_transfer` (bt709, smpte2084, arib-std-b67 pour HLG), `color_space` (bt709, bt2020nc, bt2020c).
- **Flag `color_mismatch`** si incohérence (ex: 4K avec primaries bt709 = suspect, devrait être bt2020).

#### 2.7.5 Fake 4K / upscale detection via FFT 2D — 4h
- Module [cinesort/domain/perceptual/upscale_detection.py](../../../cinesort/domain/perceptual/upscale_detection.py) (nouveau).
- Fonction `detect_fake_resolution(frames_data, declared_resolution) -> dict` :
  - Prend 5 frames représentatives.
  - Pour chaque frame : FFT 2D → calcule l'énergie dans les hautes fréquences (HF) vs basses fréquences (LF).
  - Ratio HF/LF < seuil (à calibrer, ~0.15 pour 4K natif vs ~0.05 pour upscale 1080p→4K).
  - Retourne : `{is_fake: bool, confidence: 0-1, real_resolution_estimate: "1080p"|"2160p", hf_lf_ratio: float}`.
- Utilise `numpy.fft.fft2` (dépend de numpy, déjà tiré).

#### 2.7.6 Interlacing detection — 1h
- `ffmpeg -i <file> -vf idet -f null -` sur 10s de vidéo.
- Parse stderr : `Multi frame detection: TFF:X BFF:Y Progressive:Z`.
- Si `(TFF + BFF) / Progressive > 0.3` → flag `interlaced_detected`.

#### 2.7.7 Crop / black bars detection — 1h
- `ffmpeg -i <file> -vf cropdetect=limit=24:round=16 -t 10 -f null -` sur 10s.
- Parse stderr : dernière ligne `crop=W:H:X:Y`.
- Si `(W, H) != (width, height) du container` → calcul de l'aspect ratio détecté vs déclaré.
- Flag `black_bars_detected` + champs `detected_aspect_ratio`, `declared_aspect_ratio`.

#### 2.7.8 Motion judder / 3:2 pulldown — 2h
- `ffmpeg -i <file> -vf mpdecimate -f null -` sur 30s.
- Parse nombre de frames décimées.
- Si `decimated / total > 0.15` → flag `pulldown_suspect` (possible transfert film→NTSC 30fps non retourné à 24fps).

**Métadonnées audio ajoutées (2) :**

#### 2.7.9 Dialnorm (AC3/EAC3) — 30 min
- Parser `streams[audio].dialog_normalization` depuis ffprobe.
- Valeur standard : -27 dB (home cinema) à -23 dB (broadcast).
- Flag `dialnorm_broadcast` si < -24 dB (potentiel volume boosté au ré-encodage).

#### 2.7.10 Spectral cutoff (lossy detection) — 3h
- Module [cinesort/domain/perceptual/spectral_analysis.py](../../../cinesort/domain/perceptual/spectral_analysis.py) (nouveau).
- Fonction `detect_spectral_cutoff(ffmpeg_path, media_path, segment_start_s=60, duration_s=30) -> dict` :
  - Extrait 30s d'audio via ffmpeg en raw PCM mono float32.
  - FFT sur fenêtres de 4096 samples, chevauchement 50%.
  - Moyenne la magnitude par bande de fréquences.
  - Trouve la fréquence `cutoff_hz` au-dessus de laquelle la puissance tombe sous -80 dB.
  - Retourne `{cutoff_hz: float, verdict: "lossless" | "lossy_high" | "lossy_mid" | "lossy_low", confidence: 0-1}`.
- Seuils :
  - `cutoff_hz >= 21000` → `lossless` (vrai FLAC/PCM)
  - `19000 <= cutoff_hz < 21000` → `lossy_high` (MP3 320k, AAC 256k)
  - `16000 <= cutoff_hz < 19000` → `lossy_mid` (MP3 192k, AAC 128k)
  - `cutoff_hz < 16000` → `lossy_low` (MP3 128k ou moins)

**Métadonnées cohérence (1) :**

#### 2.7.11 Runtime vs TMDb — 1h
- Comparer `probe.duration_s` vs `tmdb.runtime * 60`.
- Si différence > 5 min → flag `version_hint` avec une des valeurs :
  - `"theatrical_cut"` si probe < tmdb
  - `"extended_cut"` si probe > tmdb + 10 min
  - `"director_cut"` si probe > tmdb + 20 min
  - `"unknown_version"` si diff > 30 min
- Affiché comme **avertissement** dans la modale deep-compare (ne bloque pas, prévient l'utilisateur que c'est peut-être 2 versions différentes).

---

### 2.8 — Grain Intelligence avancée (10h)

**Objectif :** faire passer l'analyse grain de "3 bandes d'ère basique" à "système expert grain-aware".

**Fichiers touchés :**
- [cinesort/domain/perceptual/grain_analysis.py](../../../cinesort/domain/perceptual/grain_analysis.py)
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py)

#### 2.8.1 Classification d'ère granulaire (2h)
Remplacer `classify_film_era()` par 6 bandes :
```python
def classify_film_era_v2(year: int, tmdb_genres: list[str] = None) -> str:
    if year < 1980: return "16mm_era"         # Grain très prononcé (ISO élevés)
    if year < 1999: return "35mm_classic"     # Grain standard pellicule
    if year < 2006: return "late_film"        # Fin pellicule, scans haute qualité
    if year < 2013: return "transition"       # Mixte, capteurs bruyants
    if year < 2021: return "digital_modern"   # Capteurs propres
    return "digital_hdr_era"                   # Capteurs HDR, signature spécifique
```

**Table des attendus (constants.py)** :
```python
GRAIN_PROFILE_BY_ERA = {
    "16mm_era":      {"expected_level": 4.5, "tolerance": 1.5, "natural_uniformity_max": 0.75},
    "35mm_classic":  {"expected_level": 3.0, "tolerance": 1.0, "natural_uniformity_max": 0.80},
    "late_film":     {"expected_level": 2.0, "tolerance": 0.8, "natural_uniformity_max": 0.82},
    "transition":    {"expected_level": 1.5, "tolerance": 1.0, "natural_uniformity_max": 0.85},
    "digital_modern":{"expected_level": 0.5, "tolerance": 0.5, "natural_uniformity_max": 0.90},
    "digital_hdr_era":{"expected_level": 0.3, "tolerance": 0.3, "natural_uniformity_max": 0.92},
}
```

#### 2.8.2 Grain sain vs grain encode (4h)
Module [cinesort/domain/perceptual/grain_classifier.py](../../../cinesort/domain/perceptual/grain_classifier.py) (nouveau).

Fonction `classify_grain_nature(frames_data, frame_count=10) -> dict` :
- **Grain argentique** : distribution spatiale uniforme, temporellement aléatoire (FFT 2D de chaque frame ≠ FFT 2D des autres frames).
- **Bruit d'encodage** : corrélé spatialement en blocs 8x8 ou 16x16 (pattern de quantization), **identique** temporellement (FFT 2D très similaire entre frames).
- Mesure :
  - Autocorrélation 2D de chaque frame dans les zones plates → `spatial_corr_8x8`.
  - Corrélation inter-frames de ces autocorrélations → `temporal_corr`.
  - Verdict :
    - `temporal_corr > 0.85` + `spatial_corr_8x8 > 0.6` → `"encode_noise"` (bruit compression)
    - `temporal_corr < 0.4` + `spatial_corr_8x8 < 0.3` → `"film_grain"` (grain argentique)
    - Entre les deux → `"ambiguous"`
- Retourne `{nature: str, confidence: 0-1, spatial_corr: float, temporal_corr: float}`.

#### 2.8.3 Détection DNR partiel (2h)
Fonction `detect_partial_dnr(frames_data, video_perceptual, grain_result) -> dict` :
- Calcule `texture_variance_detected` = variance des blocs non-plats.
- Compare avec `texture_variance_baseline` (table attendus par ère).
- Formule : `texture_loss_score = (baseline - detected) / baseline`.
- Si `grain_level < GRAIN_LIGHT` mais `texture_loss_score > 0.25` → **DNR partiel suspect** (lisse les textures mais préserve un peu de grain pour tromper).
- Retourne `{is_partial_dnr: bool, texture_loss_score: float, detail: str}`.

#### 2.8.4 Signature grain attendue par contexte (2h)
Base de connaissance interne : signature grain par combinaison (ère, genre, budget, studio, pays).

Exemples :
- `(35mm_classic, horror, low_budget, Hammer, UK)` → grain élevé variable attendu
- `(digital_modern, animation, high_budget, Disney, US)` → aucun grain attendu (animé)
- `(late_film, drama, medium_budget, _, France)` → grain Kodak modéré attendu

Fonction `get_expected_grain_signature(era, genres, budget, production_companies, country) -> dict` :
- Matche les règles dans l'ordre de spécificité.
- Retourne `{expected_level: float, tolerance: float, confidence: float}` pour comparer avec la mesure réelle.
- Fallback sur les valeurs de `GRAIN_PROFILE_BY_ERA` si pas de règle spécifique.

#### 2.8.5 Verdict "Contexte historique" (1h, intégré Phase 4)
Dans la modale deep-compare, nouvelle section :
```
┌─ Contexte historique du film ─────────────────────────┐
│ Avatar (2009) — ère "late_film" (fin pellicule).       │
│ Grain attendu : niveau 2.0 ± 0.8.                      │
│                                                          │
│ Fichier A : grain niveau 1.8 → conforme, scan respecté │
│ Fichier B : grain niveau 0.3 + texture_loss 0.35       │
│   → DNR partiel suspect, perte de détails fins.        │
└──────────────────────────────────────────────────────┘
```

---

### 2.9 — VMAF no-reference via ONNX (6h)

**Objectif :** score qualité vidéo industrie-standard 0-100, reconnaissable internationalement.

**Dépendances ajoutées :**
- `onnxruntime>=1.17.0` (~30 MB)
- Modèle `nr_vmaf_quantized.onnx` (~40 MB, embarqué dans `assets/models/`)

**ATTENTION — nuance critique :** VMAF **surestime** la qualité sur les films avec beaucoup de grain argentique (étude IEEE 2024). Pour CineSort :
1. **Ne pas présenter VMAF comme score ultime** — c'est UN score parmi d'autres.
2. **Pondérer dynamiquement** selon le grain détecté : si `grain_nature == "film_grain"` et `era in {"16mm_era", "35mm_classic"}` → diviser le poids VMAF par 2 dans le score composite final.
3. **Afficher un avertissement** dans l'UI : "VMAF peut surestimer la qualité des films pellicule classique".

**Fichier créé :**
- [cinesort/domain/perceptual/vmaf_nr.py](../../../cinesort/domain/perceptual/vmaf_nr.py)

**Fonction `compute_vmaf_nr(frames_data, resolution) -> dict`** :
- Prend 8 frames alignées.
- Prépare l'entrée du modèle ONNX (tensor 1x3xHxW normalisé).
- Invoque `onnxruntime.InferenceSession.run()`.
- Retourne `{vmaf_score: 0-100, confidence: 0-1, per_frame_scores: list[float], grain_warning: bool}`.

**Sourcing du modèle :**
- Partir du modèle FR-VMAF officiel Netflix ([Netflix/vmaf](https://github.com/Netflix/vmaf)).
- Convertir en ONNX via `torch.onnx.export` (script one-shot dans [scripts/convert_vmaf_onnx.py](../../../scripts/convert_vmaf_onnx.py)).
- Quantifier INT8 pour réduire la taille.
- **Alternative à évaluer** : implémentation NR-VMAF publique disponible sur GitHub (voir Plan de recherche).

---

### 2.10 — LPIPS comparaison perceptuelle A/B (5h)

**Objectif :** score de distance perceptuelle humain entre frames A et B.

**Dépendances ajoutées :**
- `onnxruntime` (déjà inclus avec VMAF)
- Modèle `lpips_alexnet_quantized.onnx` (~55 MB, embarqué)

**Fichier créé :**
- [cinesort/domain/perceptual/lpips_compare.py](../../../cinesort/domain/perceptual/lpips_compare.py)

**Fonction `compute_lpips_distance(frames_a, frames_b) -> dict`** :
- Prend les frames alignées des 2 fichiers.
- Pour chaque paire (frame_a, frame_b) : invoque le modèle LPIPS ONNX.
- Retourne `{lpips_distance: 0-1 (plus petit = plus similaire), per_frame: list[float], verdict: "identical" | "very_similar" | "similar" | "different" | "very_different"}`.

**Interprétation :**
- `< 0.1` → frames quasi-identiques (même source, même encode)
- `0.1-0.3` → très similaires (même source, encodes différents)
- `0.3-0.5` → similaires (même film mais versions différentes possibles)
- `> 0.5` → différents (attention, possible theatrical vs director's cut)

**Avantage sur pixel diff basique** : LPIPS tient compte de la perception humaine. Un léger shift de couleur → distance faible. Un artefact de compression visible → distance élevée.

---

### 2.11 — Mel spectrogram (4h)

**Objectif :** analyse fréquentielle fine audio pour détecter soft clipping et compression artifacts.

**Choix de dépendance (à valider) :**
- **Option A** : `scipy>=1.11` (+30 MB) — utilise `scipy.signal.spectrogram` tout fait.
- **Option B** : pur numpy (+0 MB, +80L de code DSP à écrire et maintenir).

**Recommandation :** Option A (scipy) pour maintenabilité. Scipy est solide et documenté.

**Fichier créé :**
- [cinesort/domain/perceptual/mel_spectrogram.py](../../../cinesort/domain/perceptual/mel_spectrogram.py)

**Fonction `compute_mel_spectrogram(audio_pcm, sample_rate, n_mels=64) -> dict`** :
- Applique STFT via `scipy.signal.stft` (fenêtre Hanning 2048 samples, hop 512).
- Applique un filter bank Mel triangulaire (64 bandes de 0 à sample_rate/2).
- Retourne le spectrogramme Mel log-scale.

**Analyses dérivées :**
- `detect_soft_clipping(mel_spec) -> dict` : si puissance saturée (>-3 dB) sur plus de 20% du temps dans les hautes fréquences → soft clipping.
- `detect_compression_artifacts(mel_spec) -> dict` : pertes régulières sur certaines bandes (signature MP3/AAC).
- `compute_spectral_flatness(mel_spec) -> float` : mesure de "brun-ness" du spectre (1.0 = bruit blanc, 0 = ton pur).

**Contribution au score composite :** 10% du score audio final.

---

### 2.12 — SSIM self-referential (3h)

**Objectif :** détecter les fake 4K en comparant l'image à sa version downscale→upscale.

**Fichier touché :**
- [cinesort/domain/perceptual/upscale_detection.py](../../../cinesort/domain/perceptual/upscale_detection.py) (le même que fake 4K FFT 2D)

**Fonction `compute_ssim_self_ref(ffmpeg_path, media_path, frames_count=5) -> dict`** :
- Lance ffmpeg avec filter_complex :
  ```
  [0:v]split=2[a][b];
  [a]scale=1920:1080:flags=bicubic,scale=3840:2160:flags=bicubic[ref];
  [b][ref]ssim
  ```
- Parse la sortie SSIM (score 0-1).
- Retourne `{ssim_self: float, verdict: "native_4k" | "upscaled_fake_4k" | "ambiguous"}`.
- Seuils :
  - `ssim_self < 0.85` → `native_4k`
  - `ssim_self > 0.95` → `upscaled_fake_4k`

**Combine avec le FFT 2D du 2.7.5** pour une double validation → confiance plus élevée.

---

### 2.13 — DRC detection (1h)

**Objectif :** classer la dynamique audio (cinéma / standard / broadcast compressé).

**Fichier touché :**
- [cinesort/domain/perceptual/audio_perceptual.py](../../../cinesort/domain/perceptual/audio_perceptual.py)

**Logique :**
- Le `crest_factor` est **déjà calculé** par `astats`.
- Ajouter dans `AudioPerceptual` les champs :
  ```python
  crest_factor_db: float
  dynamic_range_category: str  # "cinema" | "standard" | "broadcast_compressed"
  ```
- Classification :
  ```python
  if crest_factor_db >= 15.0: "cinema"
  elif crest_factor_db >= 10.0: "standard"
  else: "broadcast_compressed"
  ```

**Affichage dans la comparaison** : si A = "cinema" et B = "broadcast_compressed" → point fort clair pour A.

---

### 2.14 — Score composite final unifié (5h)

**Objectif :** agréger tous les scores en UN score global lisible, avec détail cliquable et visuel clair.

**Principe :** l'utilisateur ne doit **jamais être perdu**. Un score global, puis 4 sous-scores majeurs, puis détail par critère.

**Architecture du score :**
```
Score global CineSort : 0-100
├── Score vidéo (60% du poids total)        : 0-100
│   ├── Score perceptuel classique (40%)   : blockiness, blur, banding, grain, bit-depth, temporal
│   ├── Score VMAF no-reference (25%)       : standard industrie
│   ├── Score LPIPS vs référence (15%)      : uniquement en comparaison A/B
│   ├── Score métadonnées HDR (10%)         : HDR valide, chroma, DV profile
│   └── Score résolution effective (10%)    : fake 4K detection, SSIM self-ref
├── Score audio (35% du poids total)        : 0-100
│   ├── Score perceptuel classique (50%)   : loudness, dynamic range, clipping
│   ├── Score spectral cutoff (20%)         : lossless vs lossy
│   ├── Score DRC (15%)                     : cinema vs broadcast
│   ├── Score Mel spectrogram (10%)         : compression artifacts
│   └── Score Chromaprint (5%)              : informationnel
└── Score cohérence (5% du poids total)     : 0-100
    ├── Runtime vs TMDb (60%)
    └── NFO consistency (40%)
```

**Fichier créé :**
- [cinesort/domain/perceptual/composite_score_v2.py](../../../cinesort/domain/perceptual/composite_score_v2.py)

**Fonction `compute_global_score_v2(perceptual_result, tmdb_metadata, comparison_result=None) -> GlobalScore`** :
- Applique les pondérations ci-dessus.
- **Ajustement dynamique VMAF** : si `grain_nature == "film_grain"` et `era in {"16mm_era", "35mm_classic"}` → poids VMAF divisé par 2.
- **Confidence pondération** : chaque score contributeur a une `confidence: 0-1`. Le score final est pondéré par les confidences aussi.

**Retour :**
```python
@dataclass
class GlobalScore:
    global_score: float                # 0-100
    global_tier: str                   # "Platinum" | "Gold" | "Silver" | "Bronze" | "Reject"
    confidence: float                  # 0-1
    video_score: float
    audio_score: float
    coherence_score: float
    sub_scores: dict[str, SubScore]    # detail par composant
    verdicts: list[str]                # textes FR lisibles
    warnings: list[str]                # avertissements (ex: "VMAF peut être sur-estimé car grain argentique détecté")
```

**Visualisation frontend (Phase 4) :**
- **Grand score global** en haut (ex: "94/100 Platinum") avec cercle de progression animé
- **3 jauges** sous : Vidéo / Audio / Cohérence
- **Accordéon détaillé** avec les 12+ sous-scores, chacun avec son poids et son explication FR claire
- **Warnings** en encart jaune (ex: "VMAF 92 mais attention, film à grain préservé → score peut être sur-estimé")

---

## 3. Phase 1 — Widget espace disque home

**Effort : 4h.**

### 3.1 — Backend (1.5h)

Fichier : [cinesort/ui/api/dashboard_support.py](../../../cinesort/ui/api/dashboard_support.py).

- Étendre `get_global_stats()` :
  - Chaque `timeline[i]` reçoit `space_bytes` = somme `quality_reports.metrics_json.file_size_bytes` du run.
  - Nouveau champ `disk_info`: `{"disk_used_bytes": int, "disk_total_bytes": int, "disk_root": str}` via `shutil.disk_usage(first_library_root)`.
  - Nouveau champ `space_delta_7d_bytes` : somme films ajoutés (`quality_reports.ts > now-7d`) - somme films supprimés (`apply_operations.ts > now-7d` with `op_type IN ('MOVE_FILE', 'MOVE_DIR', 'DELETE')`).

### 3.2 — Frontend (2h)

Fichiers :
- [web/index.html](../../../web/index.html) : démasquer `#homeSpaceCard`, enrichir le markup.
- [web/views/home.js](../../../web/views/home.js) : nouvelle fonction `_renderSpaceCardV2()` :
  - Valeur principale : `"2.4 TB"` (via `formatBytes`)
  - Sous-ligne : `"sur 4 TB · 60% utilisé"` + mini-barre de progression CSS
  - Badge delta 7j : `"+180 GB cette semaine"` (vert si +, ambre si −)
  - Sparkline SVG 7 points via [web/components/sparkline.js](../../../web/components/sparkline.js)
  - Bar chart tier existant conservé sous la sparkline
- Clic sur la card → `openModal('modalWeeklyRecap')` (Phase 2)

### 3.3 — Styles (30 min)

Fichier : [web/styles.css](../../../web/styles.css).
- Classes `.space-progress-bar`, `.space-delta-badge`, `.space-sparkline-wrap`
- Animations fluides (fade-in)
- Cohérence CinemaLux (tokens `--accent-gold`, `--bg-raised`)

---

## 4. Phase 2 — Modale récap hebdomadaire animée

**Effort : 6h.**

### 4.1 — Backend (2h)

Fichier : [cinesort/ui/api/dashboard_support.py](../../../cinesort/ui/api/dashboard_support.py).

Fonction `compute_weekly_activity(store, state_dir, days=7) -> dict` :
- **Ajoutés** : requête jointée `quality_reports` + `runs.started_ts > now-7d`, dédoublonné par `(tmdb_id or (title, year))`, top 50.
- **Supprimés** : requête `apply_operations` où `op_type IN ('MOVE_FILE', 'MOVE_DIR', 'DELETE')` et `ts > now-7d`.
- **Doublons détectés** : requête `quality_reports` du dernier run où `warning_flags` contient `duplicate_candidate`.

Retourne :
```python
{
  "added": [{"title": ..., "year": ..., "tier": ..., "score": ..., "size_bytes": ..., "ts": ...}, ...],
  "removed": [...],
  "duplicates": [{"group_id": ..., "title": ..., "count": 2, "paths": [...]}, ...],
  "stats": {
    "count_added": int,
    "count_removed": int,
    "count_duplicates": int,
    "size_added_bytes": int,
    "size_removed_bytes": int,
  }
}
```

Endpoint `get_weekly_activity(days=7)` dans [cinesort_api.py](../../../cinesort/ui/api/cinesort_api.py).

### 4.2 — Modale UI (3h)

Fichier : [web/index.html](../../../web/index.html).

Structure HTML `#modalWeeklyRecap`, classe `modal wide` :
```html
<div class="modal-header">
  <div class="recap-kpis">
    <div>+X films</div>
    <div>+Y GB</div>
    <div>Z doublons</div>
  </div>
</div>
<div class="modal-tabs">
  <button class="tab active" data-tab="added">Ajoutés (X)</button>
  <button class="tab" data-tab="removed">Supprimés (X)</button>
  <button class="tab" data-tab="duplicates">Doublons (X)</button>
</div>
<div class="modal-body">
  <ul class="weekly-recap-list" data-tab="added">
    <li class="weekly-recap-item">
      <div class="item-thumb">...</div>
      <div class="item-title">Avatar (2009)</div>
      <div class="item-tier"><span class="tier-pill tier-gold">Gold</span></div>
      <div class="item-size">2.4 GB</div>
      <div class="item-ts">il y a 2h</div>
    </li>
  </ul>
  <!-- idem pour removed et duplicates -->
  <ul class="weekly-recap-list hidden" data-tab="duplicates">
    <li class="weekly-recap-item duplicate-item">
      <div class="item-title">Avatar (2009)</div>
      <div class="item-count">2 fichiers</div>
      <button class="btn btn-primary deep-compare-btn"
              data-row-a="..." data-row-b="...">
        🎬 Analyse approfondie
      </button>
    </li>
  </ul>
</div>
<div class="modal-footer">
  <button class="btn btn-ghost" onclick="closeModal('modalWeeklyRecap')">Fermer</button>
  <button class="btn btn-primary" id="btnExportRecap">Export JSON</button>
</div>
```

### 4.3 — Animations (1h)

Fichier : [web/styles.css](../../../web/styles.css).

- Réutiliser `@keyframes modalEnter` (250ms existant).
- Stagger sur items :
  ```css
  .weekly-recap-item { animation: fadeSlide 220ms var(--ease) both; }
  .weekly-recap-item:nth-child(1) { animation-delay: 40ms; }
  .weekly-recap-item:nth-child(2) { animation-delay: 80ms; }
  /* ... jusqu'à 10 */
  ```
- Cross-fade entre tabs (150ms).

---

## 5. Phase 3 — Détection doublons renforcée + bouton d'analyse

**Effort : 3h.**

### 5.1 — Détection améliorée (1h)

Fichier : [cinesort/domain/duplicate_support.py](../../../cinesort/domain/duplicate_support.py).

- Vérifier détection par `tmdb_id` en priorité (plus fiable que titre).
- Fallback sur `(title_normalized, year, edition)` si pas de tmdb_id.
- Nouveau champ `duplicate_severity`: `"low" | "medium" | "high"`
  - `high` : chemin identique → bloquant
  - `medium` : même tmdb_id, chemins différents → analyse recommandée
  - `low` : titre/année identiques sans tmdb_id → ambigu, analyse recommandée

### 5.2 — Bouton contextuel (1h)

Fichiers :
- [web/views/review.js](../../../web/views/review.js) : section "Doublons détectés"
  - Conserver bouton existant "Voir détail critère par critère"
  - Ajouter **bouton primaire** : `🎬 Analyse approfondie (image + audio)`
  - Tooltip : `"Lance une analyse image-par-image et audio indépendante des métadonnées. Durée ~2 min. À utiliser quand la comparaison technique rapide laisse un doute."`
- [web/dashboard/views/library/lib-duplicates.js](../../../web/dashboard/views/library/lib-duplicates.js) : même bouton côté dashboard.

### 5.3 — Endpoint orchestrateur (1h)

Fichier : [cinesort/ui/api/perceptual_support.py](../../../cinesort/ui/api/perceptual_support.py).

Fonction `deep_compare_pair(run_id, row_id_a, row_id_b, hwaccel_override=None) -> dict` :
1. Génère `task_id` unique (ex: `"pair_abc123"`).
2. Lance `_execute_perceptual_analysis` pour A et B **en parallèle** (`ThreadPoolExecutor` 2 workers externes pour les 2 films).
3. Chaque film en interne fait vidéo+audio parallèle (2 workers internes, voir 2.1).
4. Total : 4 tâches concurrentes (A-vidéo, A-audio, B-vidéo, B-audio).
5. Attend la complétion des 2 analyses.
6. Appelle `compute_lpips_distance(a, b)` et `compare_perceptual_results(a, b)`.
7. Exporte frames alignées en JPG + waveforms SVG (voir Phase 4).
8. Retourne payload complet avec URLs des assets + score composite v2.

---

## 6. Phase 4 — Modale deep-compare ultra-complète

**Effort : 14-16h.**

### 6.1 — Layout (4h)

Structure HTML `#modalDeepCompare` (modal `full-bleed`) en 4 zones :

**Zone 1 — Phase "en cours" (affichée 2-4 min)** :
- 4 barres de progression (A-vidéo, A-audio, B-vidéo, B-audio)
- Chaque barre : pct + step actuel (ex: "Extraction frames 18/30" ou "EBU R128 pass 1/2")
- Bouton Annuler
- ETA calculé sur moyenne mobile

**Zone 2 — Phase "résultat" (après analyse)** :
- Grand score composite en haut (cercle SVG animé)
- 3 jauges : Vidéo / Audio / Cohérence

**Zone 3 — Side-by-side A et B** :
- 5 frames représentatives (début, 25%, 50%, 75%, fin) par fichier, cliquables pour zoom
- Métadonnées : résolution effective, codec, bit-depth, HDR (MaxCLL/MaxFALL), chroma, Dolby Vision profile
- Waveform audio SVG (couleur par tier codec audio)
- Audio codec + canaux + cutoff spectral + DRC category
- Chromaprint : "même source ✓" ou "sources différentes ⚠"
- Score perceptuel classique

**Zone 4 — Comparaison détaillée 14+ critères (accordéon)** :
- Chaque critère = 1 ligne : nom, valeur A, valeur B, gagnant, delta pts, explication FR
- Contexte historique (grain par ère) en encart coloré
- Warnings globaux en encart jaune (ex: runtime différent, VMAF possiblement sur-estimé)

**Zone 5 — Décision utilisateur (3 boutons)** :
- `Garder A (recommandé)` — auto-proposé selon score composite
- `Garder B`
- `Garder les 2 (versions différentes)` — si `version_hint != null`

### 6.2 — Export frames + waveform (4h)

Fichier : [cinesort/ui/api/perceptual_support.py](../../../cinesort/ui/api/perceptual_support.py).

Fonction `_export_comparison_assets(pair_id, result_a, result_b) -> dict` :
- **Frames** : sauvegarde des frames déjà extraites en JPG via ffmpeg `-f image2 -q:v 3`.
  - Path : `runs/<run_id>/perceptual_cache/<pair_id>/frame_XXXX_a.jpg` et `..._b.jpg`.
  - Sélection : 5 frames (début, 25%, 50%, 75%, fin).
- **Waveform SVG** : utilitaire `generate_waveform_svg(media_path, duration_s, width=800, height=80) -> str`.
  - Extrait audio mono 200 samples via `ffmpeg -af aresample=200`.
  - Mappe samples sur polyline SVG (RMS par bucket).
  - Couleur tier : or pour Atmos/DTS-HD, bleu pour AC3/AAC.

### 6.3 — Servir les assets (2h)

**Desktop (pywebview)** : endpoint `get_perceptual_asset(pair_id, asset_name) -> str (base64)` pour charger les JPG/SVG dans la modale.

**Dashboard** : route `GET /perceptual/<pair_id>/<asset>` via [rest_server.py](../../../cinesort/infra/rest_server.py) avec validation anti-path-traversal.

### 6.4 — UI JavaScript (4h)

Fichier : [web/views/review.js](../../../web/views/review.js).

Fonction `_openDeepCompareModal(rowIdA, rowIdB)` :
1. Ouvre la modale avec skeleton loader.
2. POST `deep_compare_pair(run_id, rowA, rowB)` → retourne `task_id` immédiatement.
3. Démarre le poll `get_perceptual_progress(task_id)` toutes 500 ms.
4. Met à jour les 4 barres de progression avec les événements reçus.
5. Quand `status === "done"`, masque la section "en cours", affiche les résultats.
6. Les boutons de décision appellent `submit_duplicate_decision(run_id, group_id, keep, reasoning)`.

### 6.5 — Persistance des décisions (1h)

Migration SQL [017_duplicate_decisions.sql](../../../cinesort/infra/db/migrations/017_duplicate_decisions.sql) :
```sql
CREATE TABLE IF NOT EXISTS duplicate_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  group_id TEXT NOT NULL,
  row_id_kept TEXT NOT NULL,
  row_ids_discarded TEXT NOT NULL,    -- JSON array
  decision TEXT NOT NULL,              -- 'keep_a' | 'keep_b' | 'keep_both'
  reasoning TEXT,
  analysis_task_id TEXT,               -- ref perceptual task
  created_ts REAL NOT NULL,
  UNIQUE(run_id, group_id)
);
```

### 6.6 — Intégration Apply (1h)

Fichier : [cinesort/app/apply_core.py](../../../cinesort/app/apply_core.py).

- Consulter `duplicate_decisions` pour le run courant.
- Les fichiers `discarded` vont en archive (`settings.archive_root`) ou suppression selon setting `duplicate_discard_strategy`.
- Nouveau log JSONL `duplicate_resolution` dans `apply_audit.jsonl`.

---

## 7. Phase 5 — Dashboard distant : parité

**Effort : 4h.**

### 7.1 — Widget espace disque dashboard (1h)

Fichier : [web/dashboard/views/home.js](../../../web/dashboard/views/home.js) (créer).

Identique au widget desktop (Phase 1), réutilise `sparklineSvg()`.

### 7.2 — Modale récap hebdo partagée (1.5h)

Fichier : [web/shared/weekly-recap-modal.js](../../../web/shared/weekly-recap-modal.js) (nouveau).

Module partagé importé depuis `web/views/` ET `web/dashboard/views/`. Seul le bouton déclencheur diffère.

### 7.3 — Modale deep-compare partagée (1.5h)

Fichier : [web/shared/deep-compare-modal.js](../../../web/shared/deep-compare-modal.js) (nouveau).

Module partagé. Les frames et waveforms sont servies via URL REST côté dashboard (pas base64).

---

## 8. Phase 6 — Tests

**Effort : 8h.**

### 8.1 — Tests backend (5h)

| Fichier | Tests | Objet |
|---|---|---|
| `test_perceptual_parallel.py` | 8 | ThreadPoolExecutor 2 workers, ordre events progress |
| `test_perceptual_progress.py` | 6 | Registry thread-safe, TTL, events format |
| `test_audio_fingerprint.py` | 8 | Chromaprint generation, comparison, edge cases |
| `test_scene_detection.py` | 5 | Keyframes merge, fallback timestamps uniformes |
| `test_perceptual_errors.py` | 12 | Chaque exception spécialisée, messages, codes |
| `test_hwaccel_detection.py` | 4 | Parse `ffmpeg -hwaccels`, fallback CPU |
| `test_hdr_validation.py` | 6 | MaxCLL, MaxFALL, Dolby Vision profiles |
| `test_fake_4k_detection.py` | 6 | FFT 2D + SSIM self-ref, upscale detection |
| `test_spectral_cutoff.py` | 5 | Cutoff à 16/19/22kHz, fake lossless |
| `test_mel_spectrogram.py` | 4 | STFT, filter bank, detection clipping |
| `test_vmaf_nr.py` | 6 | Inference ONNX, ajustement dynamique grain |
| `test_lpips_compare.py` | 6 | Distance perceptuelle, verdicts |
| `test_grain_classifier.py` | 8 | Grain sain vs encode noise, partial DNR |
| `test_composite_score_v2.py` | 10 | Pondérations, confidence, warnings, edge cases |
| `test_weekly_activity.py` | 10 | Agrégation added/removed/duplicates, 7j |
| `test_deep_compare_pair.py` | 8 | Orchestration, assets export, base64 |
| `test_duplicate_decisions.py` | 6 | Persistance, idempotence, integration Apply |

### 8.2 — Tests frontend (3h)

| Fichier | Tests | Objet |
|---|---|---|
| `test_home_space_v7_5_0.py` | 5 | Sparkline, badge delta, %utilisé |
| `test_weekly_recap_modal_v7_5_0.py` | 8 | 3 tabs, stagger animation, KPIs |
| `test_deep_compare_modal_v7_5_0.py` | 12 | Layout 4 zones, 14+ critères, 3 boutons |
| `test_progress_ui_v7_5_0.py` | 6 | 4 barres, events polling, UI update |
| `test_dashboard_parity_v7_5_0.py` | 15 | Parité complète desktop ↔ dashboard |

**Total : ~160 nouveaux tests.** Zéro régression sur les 1654 existants.

---

## 9. Phase 7 — Documentation & build

**Effort : 3h.**

- [CHANGELOG.md](../../../CHANGELOG.md) : section `[7.5.0]` avec toutes les features.
- [VERSION](../../../VERSION) → `7.5.0-dev`.
- [CLAUDE.md](../../../CLAUDE.md) : mise à jour architecture (nouveaux modules, endpoints, dépendances).
- Nouveau journal [docs/internal/worklogs/JOURNAL_V7_5_0.md](../worklogs/JOURNAL_V7_5_0.md) avec entrées par phase.
- [requirements.txt](../../../requirements.txt) : ajout `pyacoustid`, `onnxruntime`, `scipy` (si option A).
- [CineSort.spec](../../../CineSort.spec) :
  - Ajouter les nouveaux modules aux `hiddenimports` :
    - `cinesort.domain.perceptual.progress`
    - `cinesort.domain.perceptual.exceptions`
    - `cinesort.domain.perceptual.grain_classifier`
    - `cinesort.domain.perceptual.vmaf_nr`
    - `cinesort.domain.perceptual.lpips_compare`
    - `cinesort.domain.perceptual.mel_spectrogram`
    - `cinesort.domain.perceptual.upscale_detection`
    - `cinesort.domain.perceptual.spectral_analysis`
    - `cinesort.domain.perceptual.composite_score_v2`
  - Ajouter les modèles ONNX dans `datas` :
    ```python
    ("assets/models/nr_vmaf_quantized.onnx", "assets/models/"),
    ("assets/models/lpips_alexnet_quantized.onnx", "assets/models/"),
    ```
  - Ajouter `onnxruntime` aux `hiddenimports`.
- Build EXE via `build_windows.bat`.
- Smoke test `--api`, vérification metadata.

---

## 10. Récapitulatif effort

| Phase | Sous-phases | Effort |
|---|---|---|
| **0 — Renforcement moteur** | 14 sous-phases | **52-62h** |
| 1 — Espace disque home | Backend + front + styles | 4h |
| 2 — Récap hebdo modale | Backend + modale + anim | 6h |
| 3 — Détection renforcée + bouton | Détection + UI + endpoint | 3h |
| **4 — Modale deep-compare** | Layout + export + UI + persistance | **14-16h** |
| 5 — Dashboard parity | 3 modules partagés | 4h |
| 6 — Tests | ~160 tests | 8h |
| 7 — Doc + build | Journaux, CHANGELOG, spec | 3h |
| **TOTAL** | | **~100-120h** |

---

## 11. Dépendances ajoutées

| Dépendance | Taille | Usage | Justification |
|---|---|---|---|
| `pyacoustid` | ~5 MB | Chromaprint audio fingerprint | Standard industrie (beets, MusicBrainz) |
| `onnxruntime` | ~30 MB | Inférence modèles ONNX (VMAF, LPIPS) | Bien plus léger que PyTorch (~500 MB) |
| `scipy` (option A) | ~30 MB | Mel spectrogram FFT | Alternative : pur numpy +80L code |
| Modèle NR-VMAF ONNX | ~40 MB | Embarqué dans `assets/models/` | Score industrie 0-100 |
| Modèle LPIPS AlexNet ONNX | ~55 MB | Embarqué dans `assets/models/` | Distance perceptuelle humaine |

**Bundle EXE final estimé : ~110-140 MB** (actuel : 16 MB).

**Justification** : reste très raisonnable pour une app pro desktop Windows (DaVinci Resolve 4 GB, Lightroom 2 GB). L'utilisateur a confirmé que la taille n'est pas un bloqueur dans sa vision "app pro communautaire".

---

## Fin du plan implémentation v7.5.0
