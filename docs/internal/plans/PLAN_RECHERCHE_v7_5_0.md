# PLAN DE RECHERCHE — v7.5.0

**Date de rédaction :** 2026-04-22
**But :** pour chaque point technique du plan v7.5.0, conduire une recherche approfondie (comme ce qui a été fait pour l'analyse du grain par époque) afin de couvrir un maximum de cas, d'identifier les meilleures méthodes, de trouver les dépendances utiles éventuelles, et de documenter les cas limites.

**Principe :** ne pas se contenter d'une méthode "qui marche". Chercher systématiquement :
1. Les limites / cas où la méthode échoue
2. Les alternatives plus robustes ou plus récentes
3. Les librairies/dépendances utiles qu'on aurait pu rater
4. Les benchmarks / datasets publics pour calibrer les seuils
5. Les publications récentes (2024-2026) qui remettent en cause les "bonnes pratiques"

---

## Sommaire

1. [Parallélisme et performance](#1-parallélisme-et-performance)
2. [GPU hardware acceleration](#2-gpu-hardware-acceleration)
3. [Chromaprint / AcoustID](#3-chromaprint--acoustid)
4. [Scene detection](#4-scene-detection)
5. [HDR metadata](#5-hdr-metadata)
6. [Dolby Vision](#6-dolby-vision)
7. [Fake 4K / upscale detection](#7-fake-4k--upscale-detection)
8. [Interlacing, crop, judder](#8-interlacing-crop-judder)
9. [Spectral cutoff audio](#9-spectral-cutoff-audio)
10. [VMAF no-reference](#10-vmaf-no-reference)
11. [LPIPS](#11-lpips)
12. [Mel spectrogram](#12-mel-spectrogram)
13. [SSIM self-referential](#13-ssim-self-referential)
14. [DRC detection](#14-drc-detection)
15. [Grain intelligence avancée](#15-grain-intelligence-avancée)
16. [Score composite et visualisation](#16-score-composite-et-visualisation)

---

## 1. Parallélisme et performance

### 1.1 Questions à creuser

- ThreadPoolExecutor vs multiprocessing vs asyncio → quel est le bon choix pour du I/O bound ffmpeg ?
- Python GIL : le GIL libère-t-il correctement pendant `subprocess.run()` ?
- Combien de cœurs disponibles typiquement sur un PC utilisateur CineSort ? (distribution statistique)
- Risque de saturation RAM si on lance 4 ffmpeg en parallèle sur un film 4K ?
- Problèmes Windows spécifiques : `CREATE_NO_WINDOW`, handles subprocess, deadlocks ?

### 1.2 Recherches à faire

- [ ] Benchmark empirique : mesurer le temps d'analyse mono-thread vs ThreadPool 2 workers vs 4 workers sur 10 films de tailles variées (720p, 1080p, 4K, HDR).
- [ ] Lire la documentation Python 3.13 sur `concurrent.futures.ThreadPoolExecutor` et `subprocess` pour confirmer que le GIL est libéré pendant `wait()`.
- [ ] Chercher si FFmpeg 8.0 (2026) change quelque chose pour notre cas : la nouvelle API `-threads` multi-instance améliore-t-elle le comportement ?
- [ ] Étude de cas : comment Jellyfin orchestre-t-il ses analyses multi-fichiers en parallèle ?
- [ ] Tester la contention disque : 2 ffmpeg lisant le même fichier causent-ils un slowdown disque ?

### 1.3 Dépendances alternatives à évaluer

- **joblib** : wrapper parallélisme plus simple que concurrent.futures. ~1 MB. Utile si on veut du multiprocessing facilement. Reconnu scikit-learn.
- **anyio** : abstraction async cross-framework. Inutile si on reste sur threads.

### 1.4 Cas limites à documenter

- Utilisateur sur laptop 2 cœurs : la parallélisation risque de tout ralentir (swap, thermal throttling). Détecter `os.cpu_count()` et adapter.
- NAS réseau lent : lecture concurrent de 2 fichiers gros peut saturer la bande passante. Option : détecter si `disk_root` est réseau et sérialiser.
- Antivirus Windows Defender : scan on-access peut bloquer ffmpeg 1-2s par frame. Tester impact.

### 1.5 Livrables de recherche

- Document `docs/internal/benchmarks/PERF_PARALLEL.md` avec les chiffres empiriques.
- Code de benchmark réutilisable : `scripts/bench_perceptual_parallel.py`.

---

## 2. GPU hardware acceleration

### 2.1 Questions à creuser

- Quelle fraction des utilisateurs CineSort a un GPU NVIDIA compatible CUDA / Intel QSV / AMD AMF ?
- FFmpeg shippé avec Windows officiel supporte-t-il CUDA d'emblée ou faut-il une build custom ?
- Le hwaccel gagne-t-il sur le décodage mais pas sur les filtres CPU (blockdetect, blurdetect) : goulet réel ?
- `-hwaccel cuda` vs `-hwaccel_output_format cuda` : quelle différence en pratique ?
- Que se passe-t-il si on combine hwaccel decode + filter CPU + encode software ? (transfert GPU→CPU coûteux)

### 2.2 Recherches à faire

- [ ] Tester les 4 accélérateurs sur le même fichier 4K HEVC : CUDA, QSV, VAAPI, DXVA2. Mesurer temps total.
- [ ] Vérifier la compatibilité des builds FFmpeg populaires (gyan.dev, BtbN) avec CUDA.
- [ ] Lire la doc NVIDIA [FFmpeg with NVIDIA GPU Hardware Acceleration](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/ffmpeg-with-nvidia-gpu/) pour identifier les flags optimaux.
- [ ] Explorer `torch.cuda.is_available()` pour détecter GPU NVIDIA sans dépendre de ffmpeg.
- [ ] Benchmark du filtre `scale_cuda` vs `scale` CPU → gain sur downscale 4K → 1080p.
- [ ] Investiguer si VMAF-CUDA de NVIDIA (37x plus rapide) peut remplacer notre VMAF ONNX.

### 2.3 Dépendances alternatives

- **VMAF-CUDA** : branche officielle Netflix pour GPU. Pas de Python bindings directs, mais accessible via ffmpeg `libvmaf_cuda`.
- **OpenCL** : abstraction multi-vendor, plus portable que CUDA. Mais ffmpeg OpenCL est moins mature.

### 2.4 Cas limites

- Utilisateur sur iGPU Intel HD : QSV disponible mais performance variable. Tester sur Skylake/Kaby Lake anciens.
- GPU NVIDIA mais driver trop vieux (<= 470) : NVENC/NVDEC peut-être incompatibles avec codecs récents (AV1).
- Laptop avec GPU dédié mais app lancée sur iGPU (Optimus) : CineSort doit-il demander le GPU dédié ?
- Carte graphique virtualisée (VM, Parsec, Steam Remote Play) : détection peut retourner un faux positif.

### 2.5 Livrables de recherche

- Document `docs/internal/benchmarks/GPU_HWACCEL.md` avec tableaux par GPU testé.
- Script `scripts/diagnose_gpu.py` pour détecter et tester le GPU utilisateur au setup.

---

## 3. Chromaprint / AcoustID

### 3.1 Questions à creuser

- Chromaprint est-il robuste à un pitch shift (ex: conversion 25→24fps = audio pitch +4%) ?
- Chromaprint est-il robuste à une compression lossy (MP3 128k vs FLAC) ?
- Limite de distance maximale pour déclarer "même source" : seuil 0.85 bon ou à ajuster ?
- Quel segment du film choisir pour éviter les silences (noirs début/fin) ?
- Temps de calcul pour un fingerprint 30s : acceptable en modale interactive ?

### 3.2 Recherches à faire

- [ ] Tester `pyacoustid` sur notre corpus interne : 10 films avec doublons connus (même source + encode différent).
- [ ] Tester sur des pitch-shift simulés (ffmpeg `asetrate` +4%) pour valider la robustesse.
- [ ] Comparer avec **AudFprint** (Google Research) : méthode différente basée sur peaks spectraux.
- [ ] Lire la doc [Chromaprint](https://acoustid.org/chromaprint) pour les caveat (silence, fichiers < 10s).
- [ ] Chercher si pyacoustid a une version récente avec GPU support ou batch processing.
- [ ] Tester si les fingerprints sont stables entre versions de libchromaprint (notre cache reste valide ?).

### 3.3 Dépendances alternatives

- **audfprint** (Google, GitHub) : méthode plus ancienne mais très robuste. Python pur.
- **dejavu** (GitHub Will Drevo) : 2013 mais encore utilisée. Utilise MySQL, pas idéal pour nous.
- **auditok** : détection de voice activity, utile pour trouver les segments non-silencieux.
- **panako** (Java) : plus robuste que Chromaprint sur transformations fortes, mais Java.

### 3.4 Cas limites

- Film avec beaucoup de silence (art et essai) : fingerprint peu discriminant.
- Film doublé (VF vs VO) : mêmes images, piste audio totalement différente → Chromaprint dira "différent".
- Remaster 5.1 vs 7.1 : même source mais downmix différent → similarité élevée mais pas 1.0.
- Films courts (<5 min, bonus/trailer) : segment milieu de 30s peut couvrir 10% du film.

### 3.5 Livrables de recherche

- Corpus de test `tests/fixtures/audio_fingerprint/` avec 10 paires étiquetées.
- Document `docs/internal/benchmarks/CHROMAPRINT_VALIDATION.md` avec seuils calibrés.

---

## 4. Scene detection

### 4.1 Questions à creuser

- Seuil `scene=0.3` standard ou à ajuster selon le type de film ?
- Film avec beaucoup de coupes rapides (action) vs plan-séquence long : même seuil ne fonctionne pas.
- FFmpeg `select='gt(scene,X)'` vs `select='between(t,X,Y)'` vs PySceneDetect ?
- Comment détecter les transitions fondues (fade to black) vs coupes franches ?
- Performance : parse de stderr ffmpeg pour extraire timestamps, pas fiable selon version ?

### 4.2 Recherches à faire

- [ ] Tester `ffmpeg -vf "select='gt(scene,0.3)',showinfo"` sur 5 films de styles variés.
- [ ] Comparer avec [PySceneDetect](https://pyscenedetect.readthedocs.io/) → plus précis ? Coût dépendance ?
- [ ] Explorer l'algorithme **content-aware** de PySceneDetect (compare histogrammes HSV).
- [ ] Lire la doc FFmpeg `select` filter pour comprendre précisément la métrique `scene` (MAFD, SAD ?).
- [ ] Tester la combinaison `scene + blackdetect` pour exclure les transitions noires.
- [ ] Benchmark : PySceneDetect vs ffmpeg `select` sur un corpus de 20 films.

### 4.3 Dépendances alternatives

- **PySceneDetect** (MIT, ~5 MB avec OpenCV light) : plus précis, plus d'options (content-aware, threshold-based, adaptive).
- **scenecut-extractor** (npm-style, Python port) : focalisé sur les coupes violentes.
- **katna** : toolkit extraction keyframes intelligent, backed par YouTube research.

### 4.4 Cas limites

- Animation (tout en aplats) : scene detection rate des transitions lentes → sous-échantillonnage.
- Film noir et blanc : métrique différente (pas de couleur), seuil à ajuster.
- Film avec beaucoup de montage rapide (films d'action) : risque de saturer à `max_count=20` en 5 min.
- Film avec fondus longs : ratés par scene detection standard.

### 4.5 Livrables de recherche

- Corpus `tests/fixtures/scene_detection/` avec 10 films étiquetés manuellement (timestamps vrais keyframes).
- Rapport comparatif `docs/internal/benchmarks/SCENE_DETECTION_COMPARISON.md`.

---

## 5. HDR metadata

### 5.1 Questions à creuser

- HDR10, HDR10+, Dolby Vision, HLG : comment différencier les 4 sans ambiguïté ?
- MaxCLL et MaxFALL peuvent-ils être absents même sur vrai HDR (ré-encodage mal fait) ?
- Les valeurs MaxCLL typiques sont 1000-4000 cd/m². Une valeur aberrante (0, 10000+) indique quoi ?
- `color_primaries=bt2020` sans MaxCLL : est-ce un vrai HDR ou un SDR tagué incorrectement ?
- Dolby Vision profile 5 (BL-only) vs 7 (BL+EL) vs 8.1 (HDR10 compatible) : quel impact qualité ?

### 5.2 Recherches à faire

- [ ] Lire [Dolby official calculation MaxCLL/MaxFALL](https://professionalsupport.dolby.com/s/article/Calculation-of-MaxFALL-and-MaxCLL-metadata?language=en_US).
- [ ] Tester ffprobe sur fichiers HDR10 connus (UHD Blu-ray rips) : vérifier `side_data_list`.
- [ ] Tester sur fichiers Dolby Vision profile 5 vs 7 vs 8.1 : quelles clés dans side_data_list ?
- [ ] Chercher des fichiers HDR10+ pour tester (format Samsung, moins répandu).
- [ ] Explorer le tool [dovi_tool](https://github.com/quietvoid/dovi_tool) pour valider nos parsings.
- [ ] Lire les specs SMPTE ST 2086 (mastering display metadata) et CTA-861.3 (MaxCLL/MaxFALL).

### 5.3 Dépendances alternatives

- **dovi_tool** (Rust binary, pas Python) : référence pour extraction DV, très précis mais externe.
- **MediaInfo** (déjà dans CineSort) : donne aussi les infos HDR, à cross-checker.

### 5.4 Cas limites

- Fichier SDR avec `color_primaries=bt2020` (erreur encode) : notre flag doit le détecter.
- Fichier HDR10 sans metadata MaxCLL (fréquent sur UHD Blu-ray anciens) : fallback sur analyse luminance pixels.
- Dolby Vision avec RPU corrompu : le fichier est HDR mais le RPU ne peut pas être parsé → flag warning.
- HLG (TV broadcast) : détecter via `color_transfer=arib-std-b67`.

### 5.5 Livrables de recherche

- Base de connaissances `docs/internal/reference/HDR_DETECTION.md` avec tableau des clés ffprobe par format HDR.
- Fixtures test `tests/fixtures/hdr_probes/` avec 10 JSON ffprobe étiquetés.

---

## 6. Dolby Vision

### 6.1 Questions à creuser

- Profile 5 (BL, proprietary) vs Profile 7 (BL+EL+RPU) vs Profile 8.1 (BL+RPU, HDR10 compatible) vs Profile 8.4 (HLG compatible) : caractéristiques techniques ?
- Quel profile est le plus qualitatif ? Le plus compatible (players) ?
- Ré-encodage DV : profile 7 dual-layer → profile 8 single-layer, perte qualité ?
- Détection RPU valide vs corrompu ?

### 6.2 Recherches à faire

- [ ] Lire la spec Dolby Vision officielle (si publique).
- [ ] Explorer les rapports de mediainfo sur fichiers DV réels.
- [ ] Comparer ffprobe side_data_list vs `dovi_tool info -i file.mkv`.
- [ ] Chercher des fixtures DV dans `tests/fixtures/` ou sur GitHub (vous-même bibliothèque Hoffman test).

### 6.3 Dépendances alternatives

- Utiliser directement `dovi_tool` via subprocess pour validation RPU (embarqué binary dans `assets/tools/`).

### 6.4 Cas limites

- UHD Blu-ray ripped avec MakeMKV : préserve profile 7, mais certains players ne lisent que profile 8.
- Fichiers Disney+ WEB-DL : souvent profile 5 proprietary, incompatible non-Dolby players.

### 6.5 Livrables

- Document `docs/internal/reference/DOLBY_VISION_PROFILES.md` avec comparatif.

---

## 7. Fake 4K / upscale detection

### 7.1 Questions à creuser

- FFT 2D : quel seuil HF/LF discrimine fiablement 4K natif vs upscale ?
- SSIM self-referential : plus fiable que FFT 2D ? Combinaison ?
- Risque de faux positifs : film 4K natif mais avec beaucoup de blur artistique (faible HF).
- Risque de faux négatifs : upscale de haute qualité (Topaz AI) qui ajoute du détail artificiel.
- Film 4K restored from 35mm : vrai 4K mais énergie HF limitée par la résolution du scanner.

### 7.2 Recherches à faire

- [ ] Lire l'article [Probe.dev Video Analysis Workflows](https://www.probe.dev/resources/video-quality-metrics-analysis).
- [ ] Étudier les outils existants : MSU 4K tester, FidelityFX, NVIDIA DLSS upscale detection.
- [ ] Tester sur 10 films étiquetés manuellement : 5 vrais 4K, 5 upscales connus.
- [ ] Calibrer les seuils FFT 2D HF/LF par type de contenu (film / digital / animation).
- [ ] Explorer les méthodes deep learning (upscale detection CNN) dispos en ONNX.

### 7.3 Dépendances alternatives

- **Topaz Video AI detection** : propriétaire, pas utilisable.
- **upscayl-detector** (hypothétique) : chercher sur GitHub.
- Réseau CNN custom entraîné sur dataset upscale vs natif.

### 7.4 Cas limites

- Films remastered en 4K depuis 35mm : vrai 4K mais moins de détails HF que 4K digital.
- Films avec flou artistique intentionnel (The Revenant, Blade Runner 2049) : faux positifs.
- Animation 4K : pas de grain, HF pure → faux positifs possibles.
- Upscale AI moderne (Topaz Gigapixel) : ajoute du détail plausible, FFT peut ne pas suffire.

### 7.5 Livrables

- Corpus étiqueté `tests/fixtures/fake_4k/` : 20 vidéos (10 natives, 10 upscales).
- Document `docs/internal/benchmarks/FAKE_4K_DETECTION.md` avec seuils validés.

---

## 8. Interlacing, crop, judder

### 8.1 Questions à creuser

- FFmpeg `idet` : quel seuil TFF+BFF/Progressive signale un vrai interlacing ?
- `cropdetect` : limiter à `limit=24` OK pour fond noir, mais pour fond blanc ?
- `mpdecimate` : quel seuil de décimation signale un vrai pulldown 3:2 ?
- Variable frame rate (VFR) : comment détecter ? Impact sur nos métriques ?

### 8.2 Recherches à faire

- [ ] Lire la doc FFmpeg `idet`, `cropdetect`, `mpdecimate`, `decimate`.
- [ ] Tester sur un corpus : 5 interlaced (old TV rips), 5 progressive, 5 pulldown, 5 VFR.
- [ ] Chercher outils de détection VFR : `mkvinfo`, `ffprobe show_frames`.
- [ ] Étudier les cas des films anime avec 3:2 pulldown partiel (mixte 24/30 fps).

### 8.3 Dépendances alternatives

- **mkvtoolnix** : précis sur l'info VFR dans MKV.
- **yavideos** ou autres tools spécialisés.

### 8.4 Cas limites

- VFR honest : anime avec timestamps exacts par scène.
- VFR faux : conversion 60fps → 24fps mal faite, judder partout.
- Letterbox vs pillarbox vs windowbox : détecter les 3.
- Crop asymétrique (top 60px, bottom 40px) : rare mais possible.

---

## 9. Spectral cutoff audio

### 9.1 Questions à creuser

- Cutoff 22 kHz = lossless ? Et les codecs modernes (Opus) qui coupent parfois à 20 kHz honnêtement ?
- MP3 VBR à haut bitrate : cutoff peut atteindre 20.5 kHz, confusion avec FLAC.
- AAC LC vs HE-AAC : cutoffs très différents.
- Impact du mastering : certains masters 44.1 kHz n'ont rien au-dessus de 18 kHz naturellement.

### 9.2 Recherches à faire

- [ ] Lire [Spek](https://www.spek.cc/) doc et code source (open-source).
- [ ] Lire [Verifying Lossless Audio with Spectral Analysis](https://djbasilisk.com/resources/verifying-lossless-audio-quality-with-spectral-analysis/).
- [ ] Tester notre algo sur corpus : FLAC 24-bit, FLAC 16-bit, MP3 320, MP3 128, AAC 128, Opus 128.
- [ ] Étudier les signatures par codec : MP3 coupe brutal à X, AAC roll-off progressif, Opus quasi-lossless.
- [ ] Calibrer les seuils avec des fichiers de référence connus.

### 9.3 Dépendances alternatives

- **sox** : spectrogram en ligne de commande, pas Python mais précis.
- **librosa** (si on le prend pour Mel) : fait aussi le cutoff.

### 9.4 Cas limites

- Mastering vintage 20 kHz natif (années 80) : peut sembler lossy mais ne l'est pas.
- Audio mono 22 kHz : cutoff à 11 kHz (Nyquist), notre algo ne doit pas crier au lossy.
- Audio DSD convertir en PCM : cutoff bizarre (bruit de requantification).

---

## 10. VMAF no-reference

### 10.1 Questions à creuser

- **CRITIQUE** : NR-VMAF surestime les films avec grain argentique (étude IEEE 2024). Ajustement nécessaire.
- Netflix VMAF 4K model vs VMAF 1080p model : lequel utiliser ?
- VMAF est-il calibré sur notre type de contenu (films) ou plutôt streaming (séries TV) ?
- Existe-t-il des modèles NR-VMAF spécialisés film ?
- Quelle version ONNX (fp32, fp16, int8) pour bon compromis taille/précision ?

### 10.2 Recherches à faire

- [ ] Lire [No-Reference VMAF IEEE paper](https://ieeexplore.ieee.org/document/10564175/) complet (pas juste abstract).
- [ ] Explorer [Netflix/vmaf](https://github.com/Netflix/vmaf) pour les releases, modèles disponibles.
- [ ] Chercher les modèles NR-VMAF pré-entraînés sur GitHub (hors Netflix) en ONNX.
- [ ] Tester [ffmpeg-quality-metrics](https://pypi.org/project/ffmpeg-quality-metrics/) comme alternative wrapper.
- [ ] Mesurer l'impact du grain sur VMAF : comparer 10 films pellicule vs 10 films digital.
- [ ] Explorer pVMAF de Synamedia (annoncé 35x plus rapide, licence ?).
- [ ] Chercher si Netflix a publié NR-VMAF officiellement ou si c'est uniquement recherche académique.

### 10.3 Dépendances alternatives

- **libvmaf** via FFmpeg : classique, nécessite référence (pas notre cas).
- **ffmpeg-quality-metrics** (PyPI) : wrapper Python, mais nécessite référence.
- **pVMAF** (Synamedia) : propriétaire, pas accessible public.
- **DeViQ** : alternative no-reference mentionnée dans ResearchGate.
- **VQEG evaluation datasets** : pour calibrer nos seuils.

### 10.4 Cas limites

- Film 16mm avec grain élevé : VMAF sous-estime la qualité → **DOIT ÊTRE AJUSTÉ** via notre grain_classifier.
- Film digital propre : VMAF précis.
- Film animé : VMAF sur-estime (pas de grain attendu mais aplats propres = VMAF satisfait).
- Film noir et blanc : VMAF entraîné surtout sur couleur → potentiellement biaisé.
- Film 4K HDR : VMAF 1080p model inapproprié.

### 10.5 Livrables

- Document `docs/internal/benchmarks/VMAF_VALIDATION.md` avec 30 films étiquetés MOS.
- Table de pondération dynamique `vmaf_weight_by_era.json`.
- Script `scripts/evaluate_vmaf_on_corpus.py`.

---

## 11. LPIPS

### 11.1 Questions à creuser

- LPIPS AlexNet vs VGG vs SqueezeNet : lequel pour notre use case (légèreté vs précision) ?
- LPIPS fonctionne-t-il bien sur des frames alignées temporellement (pas juste pixels) ?
- Distance LPIPS 0.1-0.3 : que signifie pour l'utilisateur ? Comment la traduire en langage FR compréhensible ?
- LPIPS est-il robuste aux différences de couleur (mastering HDR vs SDR du même film) ?

### 11.2 Recherches à faire

- [ ] Lire l'article [The Unreasonable Effectiveness of Deep Features as a Perceptual Metric](https://arxiv.org/abs/1801.03924).
- [ ] Tester le dépôt [richzhang/PerceptualSimilarity](https://github.com/richzhang/PerceptualSimilarity).
- [ ] Convertir le modèle AlexNet LPIPS en ONNX via PyTorch.
- [ ] Tester LPIPS ONNX sur 5 paires étiquetées (identiques, similaires, différents).
- [ ] Étudier les alternatives : DISTS, DreamSim, AHIQ (métriques perceptuelles plus récentes).
- [ ] Chercher des métriques spécialisées "détection du même film" (pas général image similarity).

### 11.3 Dépendances alternatives

- **DISTS** (2020) : plus léger, meilleures performances sur certains benchmarks.
- **DreamSim** (2023, Facebook) : combine plusieurs modèles, très précis mais lourd.
- **AHIQ** : spécifique image quality assessment.
- **pyiqa** (PyPI) : collection de métriques IQA incluant LPIPS, DISTS, etc.

### 11.4 Cas limites

- 2 versions du même film (mastering différent) : LPIPS peut donner distance élevée alors qu'il s'agit bien du même film.
- Version colorisée vs noir et blanc : LPIPS donnera grande distance.
- Différence de crop (letterbox vs full frame) : LPIPS sensible au cadrage.

---

## 12. Mel spectrogram

### 12.1 Questions à creuser

- 64 bandes Mel vs 128 : quelle granularité pour notre use case ?
- Fenêtre FFT 2048 vs 4096 : trade-off temps vs fréquence.
- Log-scale vs linéaire pour le spectrogramme : impact sur nos analyses dérivées ?
- Scipy vs pur numpy : quelle différence réelle en perf ?

### 12.2 Recherches à faire

- [ ] Lire [Tim Sainburg — Spectrograms without librosa](https://timsainburg.com/python-mel-compression-inversion.html).
- [ ] Benchmark : scipy `signal.stft` vs numpy manual FFT (5 fichiers 30s).
- [ ] Tester différentes valeurs de n_mels, window_size sur nos signatures visées.
- [ ] Étudier les datasets audio : URBANSOUND8K, FSD50K pour validation.

### 12.3 Dépendances alternatives

- **librosa** (~80 MB avec deps) : plus complet mais lourd.
- **torchaudio** : si on a déjà PyTorch... mais on ne l'a pas.
- **tensorflow-io** : overkill.
- **python-audio-analysis** (PyPI) : toolkit complet.

### 12.4 Cas limites

- Audio très court (< 1s) : spectrogram peu discriminant.
- Audio DC offset fort : affecte les basses fréquences → pré-normaliser.
- Audio multi-canal : downmix mono avant analyse.

---

## 13. SSIM self-referential

### 13.1 Questions à creuser

- SSIM `flags=bicubic` est-il le bon algorithme upscale ? Et lanczos, spline ?
- Seuils 0.85 / 0.95 : à calibrer sur notre corpus.
- SSIM natif ffmpeg vs skimage.metrics.structural_similarity : même résultat ?
- Combien de frames utiliser ? 5 représentatives ou échantillonnage uniforme ?

### 13.2 Recherches à faire

- [ ] Tester les 4 algos de resampling (bicubic, lanczos, spline16, spline36) sur le même fichier.
- [ ] Comparer SSIM ffmpeg vs skimage sur 10 frames.
- [ ] Tester sur corpus 10 films (5 natifs 4K, 5 upscales) pour calibrer les seuils.
- [ ] Lire [SSIM original paper (Wang 2004)](https://ece.uwaterloo.ca/~z70wang/publications/ssim.pdf).

### 13.3 Dépendances alternatives

- **scikit-image** : `structural_similarity` natif. +50 MB (trop lourd si on ne l'utilise que pour ça).
- **piq** (PyTorch Image Quality) : collection IQA, nécessite PyTorch.
- **ffmpeg filter ssim** : déjà là, zero dep.

### 13.4 Cas limites

- Film avec beaucoup de grain : le downscale+upscale dégrade le grain → SSIM artificiellement bas.
- Film très statique (plans fixes longs) : SSIM élevé car peu d'info à perdre.

---

## 14. DRC detection

### 14.1 Questions à creuser

- Crest factor 15-20 dB = cinéma, < 10 dB = broadcast : valeurs industrie confirmées ?
- Film cinéma moderne (Mad Max Fury Road : DR très élevé) vs broadcast home Netflix (compressé) : mesure réelle ?
- Le crest factor est-il influencé par les pistes audio supplémentaires (commentaires ~ stéréo compressée) ?
- Loudness LUFS + crest factor : combinaison donne meilleure info ?

### 14.2 Recherches à faire

- [ ] Lire l'article [Loudness War Wikipedia](https://en.wikipedia.org/wiki/Loudness_war).
- [ ] Lire les specs EBU R128 et ATSC A/85 (broadcast normalisé).
- [ ] Tester sur corpus : 10 films cinéma + 10 ré-encodages stream.
- [ ] Chercher les tools DR meter (dynamicrange.de, MAAT DRMeter).
- [ ] Explorer l'algorithme Official DR (TT DR Offline Meter).

### 14.3 Dépendances alternatives

- **pyloudnorm** : implémentation EBU R128 Python pure, ~1 MB. Utile si on veut plus que crest_factor.
- **r128gain** : wrapper ffmpeg pour loudness.

### 14.4 Cas limites

- Film musical : musique dynamique forte = crest factor élevé, pas forcément "cinéma".
- Dialogue-heavy : crest factor modéré malgré mixage cinéma.
- Midnight mode / night listening : dynamique compressée intentionnellement (bonus feature).

---

## 15. Grain intelligence avancée

### 15.1 Questions à creuser

- Les 6 bandes d'ère proposées : couvrent-elles bien ou faut-il plus de granularité (ex: distinguer 16mm vs super8) ?
- Grain 70mm vs 35mm vs 16mm : signatures distinctes mesurables ?
- Grain Kodak 5219 (Vision3 500T) vs Kodak 5203 (50D) : distributions différentes ?
- Détection "grain rehaussé en post" (grain ajouté numériquement sur pellicule scannée) : possible ?
- Grain intentionnel moderne (Fincher, Paul Thomas Anderson sur Kodak) : signature différente d'un vrai 35mm des années 90 ?

### 15.2 Recherches à faire

- [ ] Lire [Film grain: the power of nostalgia](https://medium.com/storm-shelter/the-importance-of-film-grain-255f0246cd64).
- [ ] Étudier les papers de recherche sur film grain synthesis (NETFLIX's film grain AV1).
- [ ] Lire la spec AV1 Film Grain Synthesis pour comprendre les paramètres modélisés.
- [ ] Analyser un corpus de 30 films par ère/stock pellicule → extraire signatures statistiques.
- [ ] Explorer [Film Grain Analysis papers arxiv](https://arxiv.org/search/?query=film+grain+analysis) 2023-2026.
- [ ] Étudier les outils professionnels : Neat Video, Dehancer, DaVinci Neutral Film.

### 15.3 Dépendances alternatives

- **OpenCV** (cv2) : pour analyse texturale avancée (GLCM, Haralick features). Déjà lourd (~50 MB) mais très puissant.
- **scikit-image** : filtres et métriques textures.
- **noise2noise** : réseau neuronal de débruitage, pourrait indiquer quantité de bruit.

### 15.4 Cas limites

- Film muet années 1920 : pellicule très ancienne, grain extrême non représenté dans nos bandes.
- Film IMAX 70mm : grain faible malgré pellicule → bande d'ère ne suffit pas.
- Film hybride (tournage pellicule 35mm + VFX numériques) : grain hétérogène.
- Remaster HDR d'un film pellicule : grain peut être partiellement traité.

### 15.5 Livrables

- Base de données signatures grain : `cinesort/domain/perceptual/grain_signatures.json`.
- Corpus étiqueté `tests/fixtures/grain_era/` avec 30 films (5 par ère).
- Document `docs/internal/reference/GRAIN_SIGNATURES.md` avec tableaux statistiques.

---

## 16. Score composite et visualisation

### 16.1 Questions à creuser

- Comment expliquer à un non-expert la différence entre VMAF, LPIPS, SSIM, score perceptuel, etc. ?
- Visualisation : jauge circulaire, bar chart, spider chart, tree map ?
- Pondération dynamique : le user doit-il pouvoir ajuster (slider "priorité vidéo / audio / cohérence") ?
- Règles de surpondération : VMAF /2 si grain argentique → autres cas où on doit ajuster ?

### 16.2 Recherches à faire

- [ ] Étudier les UI de DaVinci Resolve, Premiere Pro, Final Cut pour inspirations visuelles.
- [ ] Lire [Netflix tech blog](https://netflixtechblog.com/) sur la présentation de VMAF aux utilisateurs.
- [ ] Tester différentes visualisations sur 3 utilisateurs non-techniques (user testing light).
- [ ] Étudier l'UX d'outils grand public : Plex "Auto Quality", Jellyfin stats.
- [ ] Lire les best practices d'infographie pour scores multi-critères (Edward Tufte).

### 16.3 Dépendances alternatives

- Pas de dépendance frontend supplémentaire envisagée (vanilla SVG / Canvas suffit).
- **Chart.js** ou **D3** : overkill pour notre besoin.

### 16.4 Cas limites

- Score composite élevé mais 1 sous-score critique bas (ex: audio lossless mais vidéo blockiness extrême) : mettre en avant le sous-score bas en warning.
- Confidence basse sur tous les sous-scores : signaler "analyse incertaine" plutôt qu'afficher un score trompeur.

### 16.5 Livrables

- Mockups Figma `docs/internal/design/deep_compare_mockups.fig`.
- Document `docs/internal/design/SCORE_VISUALIZATION.md`.

---

## Méthodologie générale

Pour chaque point ci-dessus :

1. **Phase recherche (1-3h par point)** : lire les sources, tester sur corpus, identifier les limites.
2. **Phase décision (30 min)** : choisir la méthode optimale, documenter le choix et ses alternatives.
3. **Phase implémentation** (cf PLAN_v7_5_0.md) : code + tests + documentation.
4. **Phase validation (1h)** : benchmark sur corpus, comparaison avec les attentes.

**Ordre recommandé :**
1. D'abord Phase 0 du plan d'implémentation (parallélisme, progress, chromaprint, scene detect, hwaccel, métadonnées) — les fondations.
2. Ensuite les gros modules ML (VMAF, LPIPS) — plus de recherche nécessaire.
3. Ensuite les analyses avancées (grain intelligence, score composite).
4. Les 3 phases UI en parallèle une fois que le backend est stable.

**Temps total de recherche estimé : 25-35h** réparti sur les 16 points. Effort complémentaire au 100-120h d'implémentation.

---

## Fin du plan de recherche v7.5.0
