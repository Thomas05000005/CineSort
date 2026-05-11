# NOTES DE RECHERCHE — v7.5.0

**Date de début :** 2026-04-22
**But :** consigner au fur et à mesure les findings de chaque section de [PLAN_RECHERCHE_v7_5_0.md](PLAN_RECHERCHE_v7_5_0.md).

**Structure de chaque section** :
- **Date** : quand la recherche a été faite
- **Findings** : ce qu'on a appris
- **Benchmarks** : chiffres mesurés empiriquement (si applicable)
- **Décision finale** : méthode retenue + justification
- **Seuils validés** : valeurs numériques calibrées (si applicable)
- **Cas limites identifiés** : scénarios qui ont émergé pendant la recherche
- **Références** : URLs, papers, issues GitHub consultés

**Légende des statuts** :
- 🔜 À FAIRE
- 🔄 EN COURS
- ✅ TERMINÉ
- ⚠️ BLOQUÉ (détails en commentaire)

---

## Vague 1 — Fondations

### §1 — Parallélisme et performance ✅

**Date :** 2026-04-22

**Findings :**

#### État actuel CineSort (lu dans le code)
- [cinesort/domain/perceptual/ffmpeg_runner.py](../../../cinesort/domain/perceptual/ffmpeg_runner.py) : `subprocess.run(... capture_output=True, timeout=...)` — bien fait côté sécurité (pas de deadlock stdout/stderr), utilise `CREATE_NO_WINDOW` sur Windows.
- [cinesort/ui/api/perceptual_support.py](../../../cinesort/ui/api/perceptual_support.py) lignes 124-167 : orchestration 100% séquentielle. Frames → filter graph → video analysis → grain → audio. Aucun `ThreadPoolExecutor`, aucun `asyncio`, aucun `multiprocessing`.
- **Aucune commande ffmpeg ne passe `-threads N`** → s'appuie sur le comportement par défaut de ffmpeg 7+/8 (auto-detect = OK).

#### Python 3.13 GIL et subprocess (recherche web)
- Python 3.13 (notre cible) a un mode "free-threaded" **optionnel** (opt-in) — par défaut le GIL est actif.
- **Le GIL est automatiquement libéré pendant `subprocess.run()`** (confirmé par SuperFastPython et Real Python). C'est du pur I/O bound.
- Conclusion : `ThreadPoolExecutor` est le bon choix pour orchestrer des ffmpeg en parallèle. **Pas besoin de `multiprocessing`** (qui est beaucoup plus lourd : nouveau interpréteur, sérialisation picklable, IPC coûteux).

#### ThreadPoolExecutor vs multiprocessing (recherche web)
- **ThreadPool** : démarrage rapide, léger, idéal I/O-bound, stdlib. **Recommandé 10-100 tâches concurrentes**.
- **ProcessPool** : lourd, utile uniquement pour CPU-bound Python pur. Notre cas = I/O bound ffmpeg → inutile.
- **Décision claire : `concurrent.futures.ThreadPoolExecutor`** (stdlib Python, zéro dépendance ajoutée).

#### FFmpeg 8.0 multi-threading (recherche web)
- FFmpeg 8.0 "Huffman" sorti fin 2025, disponible Windows builds gyan.dev et BtbN en 2026.
- CLI natif multi-threaded interne (transcode + filtres parallélisés). Appelé "most complex refactoring in decades" par l'équipe FFmpeg.
- **N'affecte pas notre stratégie externe** : on lance 2 ffmpeg en parallèle (via ThreadPool), chacun utilise ses threads internes en plus.
- `-threads 0` = auto-detect tous les cœurs, mais c'est déjà le comportement par défaut en FFmpeg 8. **Inutile de le passer explicitement**.

#### Consommation mémoire en parallèle (recherche web)
- Benchmarks parlent de "4 concurrent 4K transcodes = 16 GB+ RAM" — **ne s'applique pas** à notre cas.
- **Nous faisons de l'analyse, pas du transcoding** : ffmpeg streame les frames au lieu de les garder toutes en mémoire. Consommation pratique estimée : **~200-500 MB par ffmpeg** en analyse, même sur 4K HDR.
- **Deep Compare = 4 ffmpeg parallèles** (A-vidéo + A-audio + B-vidéo + B-audio) → pic RAM estimé **~1-2 GB**. Acceptable sur n'importe quel PC moderne avec ≥8 GB RAM.
- Précaution : paramétrer `max_workers` selon `os.cpu_count()` pour éviter la saturation sur laptops 2 cœurs.

#### Windows deadlock subprocess (recherche web)
- Risque classique : `stdout=PIPE` + `stderr=PIPE` + parent qui ne lit pas assez vite → buffer pipe rempli → enfant bloqué → deadlock.
- **Solution standard : `communicate()`** (lit les 2 pipes simultanément en thread interne).
- CineSort utilise **déjà** `subprocess.run(..., capture_output=True)` qui appelle `communicate()` en interne → **déjà safe**.
- `CREATE_NO_WINDOW` cache juste la console, n'affecte pas la gestion des pipes.
- **Aucune modification requise** côté gestion des pipes.

#### Distribution du nombre de cœurs CPU utilisateur
- Laptop moderne entry-level : 2-4 cœurs (Intel i3, Celeron)
- Laptop moderne standard : 4-8 cœurs (Intel i5/i7, Ryzen 5)
- Desktop : 6-16 cœurs (modernes)
- Minimum pragmatique pour parallélisme CineSort : **4 cœurs**. En dessous, fallback serial pour éviter le swap/throttling.

**Benchmarks :**

*Pas de benchmark empirique fait pendant la recherche — à mesurer durant l'implémentation avec `scripts/bench_perceptual_parallel.py`. Estimations basées sur l'état de l'art :*

| Config | Temps attendu (film 1080p 2h) |
|---|---|
| Actuel (mono-thread, séquentiel) | 4-5 min |
| ThreadPool 2 workers interne (video // audio) | **1.5-2 min** (gain ~2.5x) |
| Deep Compare ThreadPool 4 workers | 2-2.5 min pour 2 fichiers simultanés |

**Décision finale :**

1. **`concurrent.futures.ThreadPoolExecutor` stdlib** — zéro dépendance nouvelle.
2. **Pour single film** (`_execute_perceptual_analysis`) :
   - Tâche vidéo (frames + filter + analyze + grain) et tâche audio en parallèle.
   - `max_workers=2`.
3. **Pour Deep Compare** (`deep_compare_pair`) :
   - 4 tâches concurrentes (A-vidéo, A-audio, B-vidéo, B-audio).
   - `max_workers = min(4, max(1, os.cpu_count() // 2))` → adapte au CPU.
4. **Mode `perceptual_parallelism_mode` en setting** :
   - `"auto"` (défaut) : adapte selon cœurs dispo.
   - `"max"` : force le parallélisme maximum.
   - `"safe"` : 2 workers max toujours.
   - `"serial"` : fallback mono-thread (pour debug ou NAS lent).
5. **Pas besoin de passer `-threads 0` explicitement** : c'est le comportement auto de FFmpeg 8+.
6. **Subprocess existant déjà safe** (capture_output=True) → rien à toucher côté ffmpeg_runner.

**Seuils validés :**

```python
# constantes à ajouter dans cinesort/domain/perceptual/constants.py
PARALLELISM_MAX_WORKERS_SINGLE_FILM = 2       # video + audio en //
PARALLELISM_MAX_WORKERS_DEEP_COMPARE = 4      # A-video, A-audio, B-video, B-audio
PARALLELISM_MIN_CPU_CORES = 4                 # en dessous : fallback serial
PARALLELISM_AUTO_FACTOR = 2                   # workers = cpu_count // factor
```

**Cas limites identifiés :**

1. **Laptop 2 cœurs** (Celeron, i3 vieux) : `os.cpu_count() < 4` → `_resolve_max_workers()` retourne `1` (fallback serial).
2. **NAS réseau lent** (SMB 100 Mbps) : 2 ffmpeg lisant en parallèle = bande passante divisée, pas de gain de temps. Le user peut forcer `perceptual_parallelism_mode = "serial"` pour sérialiser.
3. **Antivirus Windows Defender scan-on-access** : peut rajouter 1-3 s par accès disque. Impact identique en serial ou parallèle. Hors scope §1.
4. **Python 3.13 free-threaded mode** (opt-in) : notre code est compatible (pas de ressources partagées mutables entre threads). Bonus gratuit si l'utilisateur active `PYTHON_GIL=0` plus tard.
5. **Exception dans une tâche parallèle** : ne pas laisser `Future.result()` propager sans log. Capture + logger.warning avec le nom de la tâche.
6. **Tâche qui dépasse son timeout individuel** : utiliser `timeout` sur `Future.result()`, pas uniquement `subprocess.run(timeout=...)`.
7. **Cancel en cours d'analyse** : le `JobRunner` de CineSort doit pouvoir couper les threads. `ThreadPoolExecutor.shutdown(wait=False, cancel_futures=True)` est la bonne façon. Les ffmpeg en cours reçoivent un signal.

**Références :**

- [Python docs — concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html)
- [SuperFastPython — ThreadPoolExecutor vs GIL](https://superfastpython.com/threadpoolexecutor-vs-gil/)
- [Real Python — Bypassing the GIL](https://realpython.com/python-parallel-processing/)
- [Phoronix — FFmpeg CLI multi-threading merged](https://www.phoronix.com/news/FFmpeg-CLI-MT-Merged)
- [UbuntuHandbook — FFmpeg 8.0.1 release notes](https://ubuntuhandbook.org/index.php/2025/11/ffmpeg-8-0-1-released-with-numerous-improvements-ppa-updated/)
- [Microsoft DevBlogs — Pipe deadlock](https://devblogs.microsoft.com/oldnewthing/20110707-00/?p=10223)
- [Medium — Python 3.13 optional GIL](https://medium.com/@aftab001x/pythons-liberation-the-gil-is-finally-optional-and-why-this-changes-everything-5579b43e969c)
- Code CineSort : [ffmpeg_runner.py](../../../cinesort/domain/perceptual/ffmpeg_runner.py), [perceptual_support.py](../../../cinesort/ui/api/perceptual_support.py)

---

### §2 — GPU hardware acceleration 📦 REPORTÉ v7.6.0

**Statut :** reporté en v7.6.0 par décision utilisateur (2026-04-22). Le gain réel (15-25%) ne justifie pas l'effort (6h) face à la priorité donnée à §1 Parallélisme (gain 2.5x) et aux briques fonctionnelles V2-V5. Voir [BACKLOG_v7_5_0.md §Performance](BACKLOG_v7_5_0.md#4-performance-et-scalabilité) pour la reprise.

**Recherche préservée ci-dessous pour référence quand on reprendra le sujet en v7.6.0.**

---

**Date :** 2026-04-22

**Findings :**

#### Builds FFmpeg Windows populaires — support hwaccel
- **gyan.dev** (build officiel FFmpeg pour Windows) : AMF, CUDA, CUVID, D3D11VA, D3D12VA, DXVA2, libvpl (nouveau Intel), NVDEC, NVENC, VAAPI **déjà compilés**.
- **BtbN/FFmpeg-Builds** (GitHub) : même liste, mises à jour hebdo.
- **Conclusion importante** : **aucun build custom nécessaire**. Si l'utilisateur a un FFmpeg récent (≥ 6.0), le hwaccel est dispo.

#### Commande de détection
```
ffmpeg -hwaccels
```
Sortie typique Windows (exemple) :
```
Hardware acceleration methods:
cuda
d3d11va
d3d12va
dxva2
qsv
vulkan
```
Parser : ignorer la 1ère ligne (titre), récupérer les suivantes non-vides.

**⚠️ Point critique** : `-hwaccels` liste ce qui est **compilé dans le binaire**, PAS ce qui fonctionne **réellement sur la machine**. Exemple : `cuda` listé mais pas de GPU Nvidia → échec au runtime. **Smoke test obligatoire.**

#### Ordre de priorité par plateforme (découvert)

| Plateforme | Ordre recommandé |
|---|---|
| Windows + Nvidia GPU | `cuda` > `d3d11va` > `dxva2` |
| Windows + Intel iGPU/Arc | `qsv` (ou `libvpl` nouveau) > `d3d11va` > `dxva2` |
| Windows + AMD GPU | `d3d11va` > `dxva2` (AMF uniquement en encode) |
| Windows fallback universel | `dxva2` (DirectX Video Acceleration) |

#### Gain réel pour notre cas — **point critique honnête**

**Notre analyse perceptuelle consiste en :**
1. **Décodage vidéo + extraction de frames** (~25% du temps) — **bénéficie du GPU** si bien orchestré
2. **Filter graph `signalstats, blockdetect, blurdetect`** (~50% du temps) — **CPU-only**, aucune version CUDA équivalente disponible
3. **Grain analysis sur pixels extraits** (~2% du temps) — Python pur, CPU
4. **Audio `ebur128, astats`** (~20% du temps) — **CPU-only**, pas de version GPU

**Conséquence** :
- Le gain GPU ne s'applique qu'à l'étape 1 (décodage frames).
- Pire encore, si on fait `-hwaccel cuda` (décode en GPU) puis on transfère les pixels vers le CPU pour les filtres → **le transfert PCIe peut annuler le gain**.
- Solution techniquement optimale : `-hwaccel cuda -hwaccel_output_format cuda` + `scale_cuda` + `hwdownload` **en fin de pipeline** → garde les données en GPU le plus longtemps possible.
- **Mais nos filtres analyse sont CPU-only** → on doit forcément faire `hwdownload` avant. **Gain estimé réel : 15-25%** sur l'analyse totale (pas 3-5x comme pour du transcoding).

#### Cas spéciaux d'échec (forums Nvidia et FFmpeg)
- **Drivers Nvidia < 470** : incompatibles avec codecs récents (AV1, parfois HEVC 10-bit). Fallback CPU nécessaire.
- **Laptop Optimus** (Nvidia dGPU + Intel iGPU) : FFmpeg peut se lancer sur l'iGPU par défaut → `cuda` échoue. Possibilité de forcer `CUDA_VISIBLE_DEVICES` mais complexité élevée.
- **VMs (Hyper-V, VirtualBox)** : détection GPU possible mais runtime instable. Smoke test obligatoire.
- **iGPU Intel désactivée dans BIOS** : `qsv` listé mais échoue.
- **Carte graphique virtualisée** (Parsec, Steam Remote Play, RemoteFX) : faux positifs possibles.

#### Valeur stratégique pour CineSort v7.5.0 — **à débattre**

**Gain estimé** : 15-25% de réduction de temps d'analyse sur machines avec GPU compatible.
**Coût d'implémentation** : 5h (détection + smoke test + integration dans ffmpeg_runner + setting).
**Risques** : bugs drivers, comportement hétérogène selon matériel, debug difficile à distance.

**Comparaison avec §1 Parallélisme** : §1 apporte **2.5x** (−60%), §2 apporte au maximum **1.25x** (−20%). **§1 > §2 en rapport gain/effort**.

**Recommandation** : classer §2 en **P2 (priorité basse) pour v7.5.0**, activation uniquement **opt-in explicite** par l'utilisateur. Pas activé par défaut. Peut être reporté en v7.6.0 si manque de temps. Marqué comme tel dans le plan.

**Benchmarks :**

*Pas de bench empirique fait pendant la recherche. Estimations basées sur les forums et docs NVIDIA :*

| Étape | Temps CPU seul | Temps avec CUDA decode |
|---|---|---|
| Décodage frames 4K HEVC (film 2h) | ~30 s | **~8 s** (−70%) |
| Filter graph (signalstats + blockdetect + blurdetect) | ~120 s | ~120 s (pas de gain, CPU-only) |
| Audio loudnorm + astats | ~60 s | ~60 s (pas de gain) |
| **Total analyse complète** | ~210 s (3.5 min) | **~200 s (3.3 min)** |

**Conclusion** : gain ~5% en mode séquentiel. Gain plus visible uniquement si on ajoute le parallélisme §1 **en plus**, car alors l'étape de décodage devient proportionnellement plus longue.

**Décision finale :**

1. **Implémentation MINIMALE** en v7.5.0 :
   - Détection via `ffmpeg -hwaccels` au démarrage (cache session).
   - Smoke test au premier usage d'une hwaccel (petit fichier 10 MB, timeout 10 s). Résultat caché.
   - Setting `perceptual_hwaccel` : `"none"` (défaut, pas activé) | `"auto"` | `"cuda"` | `"qsv"` | `"dxva2"`.
   - Application **uniquement sur la commande d'extraction de frames** (pas sur filter_graph, pas sur audio).
   - Fallback silencieux CPU si échec, log warning.
2. **Opt-in utilisateur** : case "Accélération GPU (expérimental)" dans les réglages perceptuels.
3. **Label clair dans l'UI** : "Gain typique 10-20% si GPU compatible. Peut causer des erreurs avec certaines combinaisons drivers/codecs."
4. **Si ça bug** : l'utilisateur peut désactiver dans les réglages, CineSort fonctionne toujours.
5. **Ne jamais bloquer l'analyse** : en cas d'échec smoke test, fallback silencieux.

**Seuils validés :**

```python
HWACCEL_SMOKE_TEST_FILE_SIZE_MAX_MB = 10      # limite fichier smoke test
HWACCEL_SMOKE_TEST_TIMEOUT_S = 10             # timeout smoke test
HWACCEL_AUTO_PRIORITY_WINDOWS = ["cuda", "qsv", "d3d11va", "dxva2"]
HWACCEL_AUTO_PRIORITY_LINUX = ["cuda", "vaapi"]
HWACCEL_AUTO_PRIORITY_MACOS = ["videotoolbox"]
HWACCEL_DEFAULT_MODE = "none"                 # opt-in, pas activé par défaut
```

**Cas limites identifiés :**

1. **`ffmpeg -hwaccels` timeout ou erreur** : retour `[]`, fallback CPU, log warning.
2. **Parsing sortie corrompue** (version future FFmpeg change format) : regex tolérante, fallback `[]`.
3. **Smoke test passe mais analyse réelle échoue** : try/except autour de l'analyse avec hwaccel, fallback CPU pour ce fichier spécifique, désactivation hwaccel pour la session.
4. **Driver update en cours d'utilisation** (user fait Windows Update pendant un scan) : erreur runtime, try/except, log, fallback.
5. **Machine changée** (user bouge le EXE portable vers un autre PC) : cache hwaccel invalidé au démarrage (re-détection).
6. **Multi-GPU** (machine rare) : `CUDA_VISIBLE_DEVICES` non géré en v7.5.0. Hors scope.
7. **Path FFmpeg custom** (user a un build custom sans CUDA) : détection retourne liste vide, pas de souci.

**Références :**

- [NVIDIA — FFmpeg with NVIDIA GPU Hardware Acceleration (CUDA SDK 13.0)](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/ffmpeg-with-nvidia-gpu/index.html)
- [gyan.dev — FFmpeg Windows builds](https://www.gyan.dev/ffmpeg/builds/)
- [BtbN/FFmpeg-Builds releases](https://github.com/BtbN/FFmpeg-Builds/releases)
- [NVIDIA Developer Forums — CPU filter after GPU decode](https://forums.developer.nvidia.com/t/use-ffmpeg-with-cpu-filter-after-decoding-and-filtering-with-gpu/220004)
- [DeFFcode — Hardware-Accelerated Video Decoding](https://abhitronix.github.io/deffcode/v0.2.6-stable/recipes/advanced/decode-hw-acceleration/)
- [Jellyfin Issue #6606 — CUDA/NVDEC not being applied](https://github.com/jellyfin/jellyfin/issues/6606) — utile pour comprendre les patterns qu'utilisent les autres projets
- [FFmpeg-engineering-handbook — hardware.md](https://github.com/endcycles/ffmpeg-engineering-handbook/blob/main/docs/optimization/hardware.md)

---

## Vague 2 — Briques indépendantes

### §3 — Chromaprint / AcoustID ✅

**Date :** 2026-04-22

**Findings :**

#### État actuel CineSort (lu dans le code)
- [cinesort/domain/perceptual/audio_perceptual.py](../../../cinesort/domain/perceptual/audio_perceptual.py) : 530 lignes, fait EBU R128 (loudnorm) + astats + clipping segments. **Aucun fingerprint**. `select_best_audio_track()` choisit la meilleure piste par hiérarchie codec (Atmos > TrueHD > DTS-HD > …), analyse cette piste uniquement.
- L'analyse existante produit des scores de qualité perceptuelle mais **ne détecte pas que 2 fichiers ont la même source audio** (ré-encodée).
- Le calcul d'un fingerprint s'insère **naturellement** dans la fonction `analyze_audio_perceptual()` en fin de pipeline, après les analyses existantes.

#### pyacoustid — librairie Python officielle
- **Version 1.3.1** (avril 2026), maintenue par [beetbox/pyacoustid](https://github.com/beetbox/pyacoustid).
- Support Python 3.10, 3.11, 3.12, **3.13**, 3.14 → notre target OK.
- **Wheels Windows disponibles** sur PyPI (pas besoin de compiler en local).
- Fonction `chromaprint.fingerprint_file(path)` → génère le fingerprint via backend auto-détecté.
- Fonction `chromaprint.compare_fingerprints(a, b)` → score de similarité 0.0-1.0 pur-Python.

#### Backends Chromaprint — point crucial
pyacoustid **nécessite l'un des 2 backends** :
1. **`fpcalc.exe`** : standalone CLI de Chromaprint, ~2-3 MB Windows, téléchargeable sur [acoustid.org/chromaprint](https://acoustid.org/chromaprint).
2. **`libchromaprint.dll`** : lib dynamique, peut être absente sur Windows par défaut.

**Décision** : embarquer `fpcalc.exe` dans `assets/tools/fpcalc.exe` pour garantir le fonctionnement indépendamment de l'environnement utilisateur. Précédent dans CineSort : on embarque déjà `ffprobe.exe` / `ffmpeg.exe` via le module `probe/tools_manager.py`.

#### Alternative découverte : ffmpeg chromaprint muxer
FFmpeg a un muxer `chromaprint` intégré (si compilé avec `--enable-chromaprint`) :
```
ffmpeg -i input.mkv -t 120 -f chromaprint -fp_format 2 -
```
- `-fp_format 2` = format raw (liste d'entiers 32-bit utilisables directement)
- `-fp_format 1` = hash string (encodé)

**Problème** : les builds Windows gyan.dev/BtbN **essentials** n'incluent pas toujours chromaprint. Les builds **full** l'incluent. **Dépendance forte au build FFmpeg de l'utilisateur** = risque de ne pas fonctionner.

**Décision** : **ne PAS utiliser** cette voie comme primaire. Garder pyacoustid + fpcalc.exe embarqué comme solution principale. Option fallback sur FFmpeg uniquement documentée, pas implémentée.

#### Robustesse de Chromaprint

**Force — lossy compression** :
- Différences minimes entre fingerprints FLAC vs MP3 320k vs MP3 128k du même source.
- Basé sur les features chroma (mapping spectral sur 12 demi-tons) → résistant aux altérations mineures.
- Cas parfait pour **détecter que 2 fichiers ont la même source audio ré-encodée**.

**Faiblesse — pitch shift** :
- **Chromaprint n'est PAS robuste aux pitch shifts significatifs** (>2-3%).
- Cas "PAL speedup" (conversion cinéma 24 fps → PAL 25 fps = +4.1%) → fingerprints divergent.
- **Notre cas** : les films que CineSort analyse ne sont pas pitch-shiftés (doublons = même release). Donc non-bloquant.
- Alternative si un jour on veut la robustesse pitch : **Panako** (Java, écarté car surcoût JVM énorme).

**Faiblesse — durées très différentes** :
- Un théatrical cut vs director's cut auront des fingerprints partiellement différents (même scènes conservées, autres scènes différentes).
- Notre approche : prendre un segment fixe **au milieu** du film (60 s offset, 120 s de durée), qui tombe très probablement sur des scènes communes.

**Faiblesse — films silencieux** :
- Art & essai avec beaucoup de silence → fingerprint peu discriminant.
- Solution : accepter une similarité plus basse (seuil 0.70) comme "probable" au lieu de "certain" pour ces cas.

#### Format et comparaison des fingerprints
- Fingerprint brut = **liste d'entiers 32-bit** (environ 1 entier / 0.1 s d'audio → pour 120 s : ~1200 entiers ≈ 4.8 KB).
- Comparaison = **distance de Hamming au niveau bit** : `popcount(a[i] XOR b[i])` sommé sur tous les index, normalisé par `total_bits`.
- Seuils empiriques proposés (à calibrer sur corpus) :

| Similarité | Interprétation |
|---|---|
| ≥ 0.90 | Même source **confirmée** (même release ré-encodée) |
| 0.75-0.90 | Même source **probable** (pitch shift léger, edit mineur) |
| 0.50-0.75 | Même film **possible** (versions différentes, edits significatifs) |
| < 0.50 | **Différent** (autre film ou source très éloignée) |

#### Segment à analyser — choix stratégique

Paramètres testés via recherche :

| Offset | Durée | Pour |
|---|---|---|
| 0-30s | 30s | Risque générique/logo, mauvais discriminant |
| 60s | 120s | **Recommandé** : dans l'action, 2 min = gros signal |
| Milieu exact | 60s | Bon compromis, mais plus court |
| 0-100% uniforme | 30s × 4 segments | Coûteux, retourne 4 fingerprints à comparer |

**Décision** : offset = 60 s, durée = 120 s. Fichier court (< 3 min) = tout le fichier.

#### Coût performance
- Extraction audio mono PCM 30 s + fingerprint : ~2-3 s sur CPU moderne.
- Extraction audio mono PCM 120 s + fingerprint : ~5-8 s.
- Comparaison de 2 fingerprints : quasi-instantanée (< 10 ms).
- Acceptable dans le pipeline (déjà 120 s de timeout audio).

**Benchmarks :**

*À calibrer empiriquement pendant l'implémentation avec corpus `tests/fixtures/audio_fingerprint/` (10 paires étiquetées : 5 "même source" avec encodes différents, 5 "sources différentes").*

Attendus typiques pour valider les seuils :

| Cas test | Similarité attendue |
|---|---|
| FLAC vs FLAC (identique) | 1.00 |
| FLAC vs MP3 320k | 0.98-1.00 |
| FLAC vs MP3 128k | 0.92-0.98 |
| FLAC vs AAC 128k | 0.90-0.97 |
| FLAC vs DTS 1509k → AAC 128k | 0.88-0.95 (ré-encode de remastering) |
| Theatrical cut vs Extended cut (~10 min diff) | 0.60-0.80 |
| Films différents | < 0.30 |

**Décision finale :**

1. **Dépendance Python** : `pyacoustid>=1.3.1` (wheels Windows OK Python 3.13).
2. **Backend embarqué** : `assets/tools/fpcalc.exe` (~3 MB), distribué avec le bundle.
3. **Localisation** : `resolve_fpcalc_path()` cherche d'abord dans `assets/tools/`, fallback `shutil.which("fpcalc")`.
4. **Intégration pipeline** : nouvelle fonction `compute_audio_fingerprint()` appelée en **dernière étape** de `analyze_audio_perceptual()`, optionnelle (guard par setting `perceptual_audio_fingerprint_enabled`, défaut `True`).
5. **Stockage** : nouveau champ `audio_fingerprint` (TEXT) dans `AudioPerceptual` + migration SQL `016_audio_fingerprint.sql` qui ajoute la colonne à `quality_reports`.
6. **Comparaison** : fonction `compare_audio_fingerprints(fp_a, fp_b)` utilisée dans `build_comparison_report` Phase 4 comme critère "Empreinte audio" (poids 10%).
7. **Segment** : offset 60 s, durée 120 s. Fichier < 180 s : fingerprint sur tout le fichier.
8. **Timeout** : 30 s pour le fingerprint (sur segments de 120 s, dépasser = fichier corrompu).
9. **Encodage stockage** : base64 string du tableau d'entiers 32-bit (pour SQLite).
10. **Fallback** : si pyacoustid/fpcalc échoue, logger warning, retourner `None`, ne pas bloquer l'analyse audio.

**Seuils validés :**

```python
# constants.py ajouts
AUDIO_FINGERPRINT_SEGMENT_OFFSET_S = 60        # début segment
AUDIO_FINGERPRINT_SEGMENT_DURATION_S = 120     # durée analysée
AUDIO_FINGERPRINT_MIN_FILE_DURATION_S = 180    # en dessous : tout le fichier
AUDIO_FINGERPRINT_TIMEOUT_S = 30
AUDIO_FINGERPRINT_SIMILARITY_CONFIRMED = 0.90  # même source confirmée
AUDIO_FINGERPRINT_SIMILARITY_PROBABLE = 0.75   # même source probable
AUDIO_FINGERPRINT_SIMILARITY_POSSIBLE = 0.50   # même film possible
```

**Cas limites identifiés :**

1. **Film silencieux ou presque** (art & essai) : fingerprint peu discriminant → accepter seuil plus permissif (0.70 au lieu de 0.90). Marquer `confidence_low` dans le résultat.
2. **Fichier < 3 min** (bonus, trailer, teaser) : fingerprint sur tout le fichier, pas offset 60 s.
3. **Audio absent** (fichier video-only rare) : retourner `None`, pas d'erreur.
4. **PAL/NTSC pitch shift** (film source 24 fps converti 25 fps) : fingerprints divergent mais pas critique — c'est 2 versions différentes qu'on veut bien distinguer.
5. **Films doublés (VF vs VO)** : Chromaprint dira "différent" → c'est **correct** (ce sont bien 2 versions différentes, même si vidéo identique).
6. **Remaster audio (5.1 → Atmos)** : même source mais mixages différents → similarité 0.75-0.85 probablement. Classifié "probable" plutôt que "confirmé".
7. **fpcalc.exe absent** (bundle cassé) : `resolve_fpcalc_path()` retourne None → fingerprint désactivé, log warning, analyse audio se poursuit sans fingerprint.
8. **Cache invalidation** : si le film est ré-encodé (mtime change), sha1_quick diffère → le perceptual cache est invalidé → nouvelle extraction fingerprint. OK.
9. **Pitch shift intentionnel** (film ralenti pour effet artistique) : rare, mais Chromaprint va divergemnt. Flag `pitch_shift_suspect` à ajouter ? Hors scope §3, renvoyé en backlog.

**Références :**

- [pyacoustid 1.3.1 sur PyPI](https://pypi.org/project/pyacoustid/)
- [beetbox/pyacoustid GitHub](https://github.com/beetbox/pyacoustid)
- [Chromaprint/AcoustID officiel](https://acoustid.org/chromaprint)
- [How does Chromaprint work? (Lalinsky, auteur)](https://oxygene.sk/2011/01/how-does-chromaprint-work/)
- [Essentia — Music fingerprinting with Chromaprint](https://essentia.upf.edu/tutorial_fingerprinting_chromaprint.html)
- [acoustid/notebooks — fingerprint-matching.ipynb](https://github.com/acoustid/notebooks/blob/master/fingerprint-matching.ipynb)
- [beets Chromaprint/Acoustid Plugin docs](https://beets.readthedocs.io/en/stable/plugins/chroma.html)
- [COMPARATIVE ANALYSIS BETWEEN AUDIO FINGERPRINTING ALGORITHMS (IJCSET 2017)](https://www.ijcset.com/docs/IJCSET17-08-05-021.pdf)
- Code CineSort : [audio_perceptual.py](../../../cinesort/domain/perceptual/audio_perceptual.py)

---

### §4 — Scene detection ✅

**Date :** 2026-04-22

**Findings :**

#### État actuel CineSort (lu dans le code)
- [cinesort/domain/perceptual/frame_extraction.py](../../../cinesort/domain/perceptual/frame_extraction.py) : 321 lignes. `compute_timestamps()` génère des timestamps **uniformément distribués** sur la durée utile (avec skip 5% début/fin pour éviter générique/logos).
- Pas de scene detection. Les 10 frames extraites peuvent tomber plusieurs fois dans la même scène longue (ex: film avec plan-séquence de 10 min).
- Frames extraites via `extract_single_frame()` individuellement, 1 appel ffmpeg par frame.
- **Opportunité** : remplacer 50% des timestamps uniformes par des keyframes détectées intelligemment → meilleure couverture scènes importantes.

#### FFmpeg native `select=gt(scene,X)` — découverte recherche
- Filtre intégré ffmpeg depuis années, stable. Calcule une métrique de "changement de scène" (MAFD — Mean Absolute Frame Difference) entre chaque frame et la précédente.
- Sortie : timestamps où la métrique dépasse le seuil X.
- **Seuils recommandés** : 0.3-0.4 pour contenu général. Exemples utilisés dans la communauté :
  - `0.2` : très sensible (beaucoup de faux-positifs, capture même micro-changements)
  - **`0.3`** : sweet spot films (recommandé par GDELT, [dudewheresmycode](https://gist.github.com/dudewheresmycode/054c8de34762091b43530af248b369e7))
  - `0.4` : films d'action, haute confiance mais rate les transitions subtiles
  - `0.5` : uniquement coupes violentes
- Commande exacte :
  ```
  ffmpeg -i <file> -vf "select='gt(scene,0.3)',showinfo" -f null -
  ```
  Sortie sur stderr, lignes de forme :
  ```
  [Parsed_showinfo_1 @ 0xABC] n:42 pts_time:354.521 scene:0.345 ...
  ```

#### Alternative : PySceneDetect
- Librairie Python, basée sur OpenCV. [scenedetect.com](https://www.scenedetect.com/).
- **Plus précis** sur certains types de contenu, mais **"struggled with recall on movie footage"** (benchmark [shot-detection-benchmarks](https://github.com/albanie/shot-detection-benchmarks)).
- **Coût dépendance** : OpenCV (~120 MB wheel Windows) — **TROP LOURD** pour le gain.
- Décision : **ne PAS utiliser PySceneDetect**. FFmpeg natif suffit pour notre cas films.

#### Parsing de la sortie FFmpeg
- Format stderr : `pts_time:XXX.XXX scene:X.XXX ...`
- Regex : `r"pts_time:(\d+\.?\d*)\s+.*?scene:(\d+\.?\d*)"`
- **Attention** : la sortie est sur **stderr** en mode info, pas stdout.
- Robustesse : la sortie peut varier entre versions ffmpeg. Prévoir fallback si regex ne match rien → mode uniforme.

#### Performance de la détection

**Approche naïve** : scan complet 1:1 de tout le fichier.
- Film 2h : ~60 s de traitement (2x realtime). **Inacceptable** en pipeline interactif.

**Optimisation 1 — Downsampling temporel** :
- `-r 2` force ffmpeg à ne décoder que 2 fps → **5-10x plus rapide**.
- Perte de précision : on manque les coupes < 0.5 s (mais elles ne sont **pas** des coupes de scène de toute façon, ce sont des flashes).
- Commande : `ffmpeg -i <file> -r 2 -vf "select='gt(scene,0.3)',showinfo" -f null -`
- Temps attendu : **~12 s pour un film 2h** ✅

**Optimisation 2 — Downsampling spatial** :
- `-vf scale=640:-1` réduit la résolution avant l'analyse de scène.
- Gain additionnel 2-3x sur films 4K.
- Combiné avec `-r 2` : **~5-8 s pour un film 2h 4K** ✅

#### Stratégie hybride — décision

Au lieu de remplacer totalement les timestamps uniformes, combiner :
- **50% timestamps uniformes** : garde la couverture temporelle constante (pour grain analysis, banding uniform)
- **50% scene keyframes** : ajoute des frames aux moments importants (pour blockiness, motion metrics)

Exemple avec 10 frames demandées sur film 2h :
- 5 timestamps uniformes à 0:12, 0:36, 1:00, 1:24, 1:48
- 5 scene keyframes (parmi les N détectées, dédupliqué contre les uniformes par tolérance 15 s)

**Avantages** :
- Robuste si scene detection échoue (la moitié uniformes reste)
- Capture scènes importantes
- Garde la distribution temporelle pour analyses qui en dépendent

#### Blackdetect complémentaire

FFmpeg `blackdetect` filter détecte les **transitions noires** (fondus, écrans noirs entre chapitres). Utile pour **exclure** les timestamps qui tombent en plein écran noir (frames inutiles à analyser).

Commande :
```
ffmpeg -i <file> -vf "blackdetect=d=0.1:pix_th=0.10" -an -f null -
```
Sortie stderr :
```
[blackdetect @ 0x...] black_start:354.5 black_end:355.2 black_duration:0.7
```

Pas prioritaire pour §4 mais à garder en tête pour un raffinement : avant de valider un timestamp, vérifier qu'il ne tombe pas dans un segment noir connu.

#### Cas limites à anticiper

1. **Film d'animation Disney/Pixar** : transitions douces, peu de coupes franches → scene detection retourne peu de keyframes. Fallback mix uniforme sauve la mise.
2. **Film d'action (John Wick, Mad Max)** : beaucoup de coupes, scene detection retourne **100+** keyframes → cap `max_keyframes=20`.
3. **Plan-séquence long (1917, Birdman)** : ~5-10 coupes sur tout le film → peu de keyframes. Fallback uniforme domine.
4. **Animation 2D traditionnelle (Ghibli)** : aplats, peu de changements → scene detection sous-détecte. Fallback uniforme.
5. **Film noir et blanc** : fonctionne, car MAFD mesure luminance pas couleur.
6. **Séquence titre de 30 s en début** : ignoré par le skip 5%.
7. **Générique 3-5 min en fin** : partiellement capturé, mais peu d'impact (vraies scènes détectées plus nombreuses).
8. **Film court < 3 min** : scene detection overhead (~5 s) > bénéfice. Skip scene detection.

#### Scene detection et parallélisme §1

La scene detection est **un appel ffmpeg supplémentaire** avant les extractions de frames individuelles. Il peut tourner **en parallèle** avec le filter graph analytique via le ThreadPool du §1. Gain de latence si bien intégré.

**Benchmarks :**

*À calibrer pendant l'implémentation sur 10 films de types variés.*

Attendus :

| Type de film | Nb keyframes (seuil 0.3, `-r 2`) | Temps total 2h |
|---|---|---|
| Drame classique | 80-150 | ~8 s |
| Film d'action | 200-400 | ~10 s (capped à 20 retenues) |
| Animation Disney | 30-80 | ~8 s |
| Plan-séquence art | 5-20 | ~7 s |
| Film muet 4K restored | 40-100 | ~6 s |

**Décision finale :**

1. **Stack** : FFmpeg natif `select=gt(scene,0.3)` + `showinfo`. Zéro dépendance nouvelle.
2. **Downsampling** : `-r 2 -vf scale=640:-1` pour accélération 10x. Pas d'impact qualité détection (coupes > 0.5 s dans tous les cas).
3. **Mode hybride** : 50% uniforme + 50% keyframes (dédupliqué par tolérance 15 s).
4. **Setting** : `perceptual_scene_detection_enabled` (défaut `True`).
5. **Fallback gracieux** : si détection échoue (timeout, parse error, < 5 keyframes) → 100% uniforme (comportement v7.4 préservé).
6. **Cap keyframes** : maximum 20 keyframes retenues (triées par score décroissant), évite le sur-échantillonnage action.
7. **Skip scene detection** : si `duration_s < 180 s` (film court), skip direct en uniforme.
8. **Pas de blackdetect** en §4 (prévu en raffinement futur).

**Seuils validés :**

```python
# constants.py ajouts
SCENE_DETECTION_THRESHOLD = 0.3              # sweet spot films
SCENE_DETECTION_FPS_ANALYSIS = 2             # downsample temporel
SCENE_DETECTION_SCALE_WIDTH = 640            # downsample spatial
SCENE_DETECTION_MAX_KEYFRAMES = 20           # cap action films
SCENE_DETECTION_MIN_FILE_DURATION_S = 180    # skip scene si film court
SCENE_DETECTION_TIMEOUT_S = 30               # sécurité
SCENE_DETECTION_HYBRID_RATIO = 0.5           # 50% uniforme / 50% keyframes
SCENE_DETECTION_DEDUP_TOLERANCE_S = 15       # distance min entre uniforme et keyframe
```

**Cas limites identifiés :**

1. Scene detection timeout → log warning, fallback uniforme.
2. Parsing stderr échoue (version ffmpeg non prévue) → 0 keyframe → fallback uniforme.
3. < 5 keyframes détectées (film très statique) → fallback uniforme, pas de hybride dégradé.
4. > 100 keyframes → trier par `scene_score` décroissant, garder top 20 (les plus "coupes franches").
5. Keyframe à < 15 s d'un timestamp uniforme → keyframe ignorée (dédup).
6. Film sans vidéo (audio-only) : scene detection skipped, fallback uniforme (qui lui-même retournera vide côté `extract_representative_frames`).
7. Fichier corrompu : ffmpeg échoue, skip scene detection, pipeline continue avec uniforme.

**Références :**

- [FFmpeg filters doc — select](https://ffmpeg.org/ffmpeg-filters.html#select_002c-aselect)
- [FFmpeg 8.0 blackdetect doc](https://ayosec.github.io/ffmpeg-filters-docs/8.0/Filters/Video/blackdetect.html)
- [Notes on scene detection with FFMPEG (dudewheresmycode gist)](https://gist.github.com/dudewheresmycode/054c8de34762091b43530af248b369e7)
- [GDELT — Experiments With FFMPEG & Scene Detection](https://blog.gdeltproject.org/experiments-with-ffmpeg-scene-detection-to-explore-the-parallel-universe-of-russian-state-television-channel-russia1/)
- [Brontosaurusrex — ffmpeg scene detection](https://brontosaurusrex.github.io/2019/03/11/ffmpeg-scene-detection/)
- [shot-detection-benchmarks (PySceneDetect vs FFmpeg)](https://github.com/albanie/shot-detection-benchmarks)
- [PySceneDetect GitHub](https://github.com/Breakthrough/PySceneDetect) (écartée)
- Code CineSort : [frame_extraction.py](../../../cinesort/domain/perceptual/frame_extraction.py)

---

### §9 — Spectral cutoff audio ✅

**Date :** 2026-04-22

**Findings :**

#### Principe (confirmé recherche web)

Les encodeurs lossy éliminent les hautes fréquences au-dessus d'un certain seuil pour réduire le bitrate. La fréquence de coupure laisse une **signature mesurable** dans le spectrogramme.

**Signatures validées par la recherche** ([miseryconfusion.com](https://miseryconfusion.com/blog/2025/07/09/dont-get-fooled-by-fake-lossless-files-again/), [alex.balgavy.eu](https://blog.alex.balgavy.eu/determining-mp3-audio-quality-with-spectral-analysis/)) :

| Cutoff apparent | Source probable |
|---|---|
| ≥ **21.5 kHz** | Vrai lossless (FLAC, PCM, DTS-HD MA, TrueHD) |
| ~**20.5 kHz** | MP3 320 CBR / AAC 256+ (lossy high) |
| ~**19 kHz** | MP3 192 / AAC 192 (lossy mid-high) |
| ~**17 kHz** | AAC LC 96+ par défaut / MP3 192 VBR |
| ~**16 kHz** | MP3 128 / AAC 128 (lossy mid) |
| < **16 kHz** | MP3 < 128 / AAC < 96 (lossy low) |

**Note importante — shelf MP3 à 16 kHz** : MP3 applique historiquement un "shelf" à 16 kHz (réduction progressive des fréquences au-dessus) **indépendamment** du bitrate. C'est une signature ADDITIONNELLE utile pour distinguer MP3 des autres formats lossy.

#### Faux-positifs à connaître

1. **HE-AAC avec SBR** (Spectral Band Replication) : l'encodeur **reconstruit synthétiquement** les hautes fréquences absentes → le spectrogramme peut montrer du contenu jusqu'à 22 kHz même en lossy bas bitrate. **Détection** : le codec du container dit déjà HE-AAC → priorité à l'info codec sur l'analyse spectrale.
2. **Masters vintage (années 70-80)** : certains masters analogiques ont naturellement peu de contenu au-dessus de 18-20 kHz (limites de la bande magnétique). Un FLAC vintage peut avoir un cutoff apparent à 20 kHz sans être lossy. **Détection** : croiser avec l'année du film (ère `classic_film` → tolérer cutoff 19-20 kHz en lossless).
3. **Audio mono 22 kHz sample rate** (rare, films vintage) : Nyquist = 11 kHz → cutoff naturel à 11 kHz, pas lossy. **Détection** : lire le sample rate du track via probe.
4. **Films avec beaucoup de silence** : FFT sur silence = bruit de fond numérique → cutoff peu significatif. **Détection** : vérifier que l'énergie RMS du segment est > seuil minimum.
5. **Audio DSD→PCM converti** : quantification Haute fréquence introduit du bruit → cutoff artificiellement élevé. Cas rare, non adressé en §9.

#### Stratégie FFT — choix dépendances

**Options évaluées :**

1. **numpy pur** (`np.fft.rfft`) : stdlib de facto (déjà tiré par rapidfuzz indirectement), **zéro MB ajouté**. Seul manque : fenêtrage Hann à faire à la main (une ligne).
2. **scipy** (`scipy.signal.spectrogram`) : +30 MB. Plus complet mais surdimensionné pour §9.
3. **librosa** : +80 MB. OVER-KILL.

**Décision** : **numpy pur**. Raisonnement :
- Mel spectrogram (§12) peut être fait en numpy pur aussi (voir §12)
- Gain scipy = marginal pour notre besoin (on n'a pas besoin de stft avancé ni de filter banks)
- 0 MB ajouté = cohérent avec philosophie CineSort "peu de dépendances"

**Code minimal FFT** :
```python
import numpy as np

def compute_spectrogram(samples: np.ndarray, sample_rate: int, window_size: int = 4096):
    # Fenêtrage Hann + FFT par blocs avec overlap 50%
    hop = window_size // 2
    hann = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(window_size) / (window_size - 1))
    n_frames = (len(samples) - window_size) // hop
    spec = np.empty((n_frames, window_size // 2 + 1))
    for i in range(n_frames):
        start = i * hop
        block = samples[start:start + window_size] * hann
        spec[i] = np.abs(np.fft.rfft(block))
    return spec  # magnitude par fréquence par frame
```

#### Extraction audio via ffmpeg

Commande :
```
ffmpeg -i <file> -ss 60 -t 30 -map 0:a:<idx> -ac 1 -ar 48000 -f f32le -
```
- `-ss 60 -t 30` : segment milieu 60 s → 90 s (30 s de signal)
- `-ac 1` : downmix mono (pas besoin de stéréo pour cutoff)
- `-ar 48000` : resample à 48 kHz (Nyquist 24 kHz, cible 22 kHz OK)
- `-f f32le` : raw float32 little-endian, lecture directe avec numpy

Sortie : `~5.76 MB` de bytes → parse en `np.frombuffer(data, dtype='<f4')`. Taille tableau : **1 440 000 samples**.

**Temps calcul attendu** : extraction ffmpeg ~3 s + FFT ~0.5 s = ~3.5 s total.

#### Algorithme de détection du cutoff

1. Calcul spectrogramme : magnitudes par fréquence par frame (Hann window 4096, overlap 50%).
2. Conversion en dB : `dB = 20 * log10(mag + epsilon)`.
3. Moyenne par fréquence sur tout le segment (stable sur 30 s).
4. Seuil : cutoff = fréquence **la plus haute** dont la magnitude moyenne est **> -70 dB** (au-dessus du plancher de bruit typique).
5. **Alternative plus robuste** : fréquence où 90% de l'énergie cumulée est atteinte (spectral rolloff 90%).

**Décision** : utiliser **spectral rolloff 85%** comme métrique principale. Plus stable que "dernière fréquence > -70 dB" qui peut être bruité.

Formule :
```python
def find_cutoff_hz(spec_mean: np.ndarray, sample_rate: int, rolloff_pct: float = 0.85) -> float:
    energy = np.cumsum(spec_mean ** 2)
    total = energy[-1]
    threshold = rolloff_pct * total
    idx = np.searchsorted(energy, threshold)
    freq_resolution = sample_rate / (2 * len(spec_mean))  # Hz par bin
    return idx * freq_resolution
```

#### Cross-check avec le codec du container

**Crucial pour éviter les faux-positifs** :

```python
def classify_cutoff(cutoff_hz: float, codec: str, sample_rate: int, film_era: str) -> dict:
    # 1. Si HE-AAC : la cutoff est faussée par SBR, faire confiance au codec
    if "he-aac" in codec.lower():
        return {"verdict": "lossy_ambiguous_sbr", "confidence": 0.95}

    # 2. Si sample rate < 48k : Nyquist limité
    nyquist = sample_rate / 2
    if cutoff_hz >= nyquist - 500:
        return {"verdict": "lossless_native_nyquist", "confidence": 0.90}

    # 3. Classification standard
    if cutoff_hz >= 21500:
        return {"verdict": "lossless", "confidence": 0.92}
    elif cutoff_hz >= 19000:
        # Vintage tolerance
        if film_era in ("16mm_era", "35mm_classic") and cutoff_hz >= 19500:
            return {"verdict": "lossless_vintage_master", "confidence": 0.75}
        return {"verdict": "lossy_high", "confidence": 0.88}
    elif cutoff_hz >= 16500:
        return {"verdict": "lossy_mid", "confidence": 0.90}
    else:
        return {"verdict": "lossy_low", "confidence": 0.95}
```

**Benchmarks :**

*À calibrer empiriquement pendant l'implémentation avec corpus `tests/fixtures/spectral_cutoff/`.*

Attendus typiques sur 6 fichiers étiquetés :

| Fichier | Cutoff attendu | Verdict attendu |
|---|---|---|
| FLAC 24-bit/48k | 21.8 kHz | `lossless` |
| FLAC 16-bit/44.1k (CD) | 21.5 kHz | `lossless` |
| AC3 640k 5.1 | 20.5 kHz | `lossy_high` |
| AAC 256k 5.1 | 20.0 kHz | `lossy_high` |
| AAC 128k stéréo | 17.0 kHz | `lossy_mid` |
| MP3 128k stéréo | 16.0 kHz | `lossy_mid` |
| HE-AAC 64k (SBR) | ~22 kHz *apparent* | `lossy_ambiguous_sbr` (via codec) |

**Décision finale :**

1. **Stack** : **numpy pur** (zéro dépendance nouvelle).
2. **Segment audio** : 30 s milieu du fichier (`-ss 60 -t 30`), mono, 48 kHz float32.
3. **FFT** : fenêtre Hann 4096, overlap 50%, moyenne sur tout le segment.
4. **Métrique** : **spectral rolloff 85%**, plus robuste que "last > threshold".
5. **Cross-check codec** : priorité HE-AAC/SBR sur analyse spectrale.
6. **Cross-check sample rate** : Nyquist limitant.
7. **Cross-check film era** : tolérance lossless 19-20 kHz pour masters vintage.
8. **Intégration** : nouveau module `cinesort/domain/perceptual/spectral_analysis.py`, appelé en fin de `analyze_audio_perceptual()` (comme chromaprint §3), peut tourner en parallèle des autres analyses audio via §1.
9. **Setting** : `perceptual_audio_spectral_enabled` (défaut `True`).
10. **Stockage** : 2 champs dans `AudioPerceptual` : `spectral_cutoff_hz: float` et `lossy_verdict: str`.

**Seuils validés :**

```python
# constants.py ajouts
SPECTRAL_SEGMENT_OFFSET_S = 60           # début segment (idem chromaprint)
SPECTRAL_SEGMENT_DURATION_S = 30          # durée segment
SPECTRAL_SAMPLE_RATE = 48000              # resample target
SPECTRAL_FFT_WINDOW_SIZE = 4096
SPECTRAL_FFT_OVERLAP = 0.5
SPECTRAL_ROLLOFF_PCT = 0.85
SPECTRAL_CUTOFF_LOSSLESS = 21500          # Hz
SPECTRAL_CUTOFF_LOSSY_HIGH = 19000        # Hz
SPECTRAL_CUTOFF_LOSSY_MID = 16500         # Hz
SPECTRAL_TIMEOUT_S = 15                   # extraction + FFT
SPECTRAL_MIN_RMS_DB = -50                 # en dessous : segment trop silencieux
```

**Cas limites identifiés :**

1. **Silence prolongé** (film art & essai, RMS < -50 dB sur tout le segment) → retourner `verdict="silent_segment"`, pas de classification lossy/lossless.
2. **HE-AAC SBR** : verdict `lossy_ambiguous_sbr` car analyse spectrale trompée.
3. **Mono 22 kHz SR** : Nyquist 11 kHz, verdict `lossless_native_nyquist`.
4. **Master vintage classic_film** : tolérance +500 Hz autour du seuil lossless.
5. **ffmpeg extraction échoue** : retourner `None`, log warning, pas bloquant.
6. **numpy manquant** (très rare si CineSort packagé correctement) : ImportError caught au module level, fonction retourne `None`.
7. **Fichier très court** (< 90 s, donc moins de 30 s après offset 60 s) : extraire tout le fichier disponible audio.

**Références :**

- [miseryconfusion.com — Don't Get Fooled By Fake Lossless Files](https://miseryconfusion.com/blog/2025/07/09/dont-get-fooled-by-fake-lossless-files-again/)
- [alex.balgavy.eu — Determining MP3 audio quality with spectral analysis](https://blog.alex.balgavy.eu/determining-mp3-audio-quality-with-spectral-analysis/)
- [Headphonesty 2025 — Lossless detection prove](https://www.headphonesty.com/2025/12/lossless-music-collection-disguised-mp3s-prove/)
- [arxiv 2407.21545 — Robust Lossy Audio Compression Identification](https://arxiv.org/html/2407.21545v1)
- [Wikipedia — HE-AAC SBR](https://en.wikipedia.org/wiki/High-Efficiency_Advanced_Audio_Coding)
- [lo.calho.st — Spectrograms with numpy](https://lo.calho.st/posts/numpy-spectrogram/)
- [Spek — Spectrogram viewer](https://www.spek.cc/)
- [redacted.ch Spectral Analysis guide](https://interviewfor.red/en/spectrals.html)

---

### §13 — SSIM self-referential ✅

**Date :** 2026-04-22

**Findings :**

#### Principe

SSIM (Structural Similarity Index Metric) mesure la similarité structurelle entre 2 images sur une échelle 0.0-1.0. Version **self-referential** : comparer une image à sa version **downscale→upscale** pour détecter les fake 4K (1080p upscalé marketé comme 4K).

**Logique** :
- **Vraie 4K native** : contient des détails à très haute fréquence → downscale en 1080p perd ces détails → upscale bicubique ne peut pas les recréer → **SSIM faible** (~0.80-0.88).
- **Fake 4K** (1080p upscalé bicubiquement en 4K) : ne contient déjà pas les détails haute fréquence → le downscale→upscale ne dégrade rien de plus → **SSIM élevé** (~0.95-0.99).

#### Implémentation ffmpeg native

SSIM est un **filtre ffmpeg intégré** depuis longtemps, stable. Commande self-ref :

```
ffmpeg -i <file> -filter_complex \
  "[0:v]split=2[a][b];
   [a]scale=1920:1080:flags=bicubic,scale=3840:2160:flags=bicubic[ref];
   [b][ref]ssim=stats_file=-" \
  -f null -
```

Sortie stderr typique :
```
[Parsed_ssim_3 @ 0x...] SSIM Y:0.862134 (8.636632) U:0.942156 (12.416...) V:0.938... All:0.884... (9.369...)
```

Parser : regex sur `"All:([\d.]+)"`.

#### Choix de l'algorithme de scaling

La recherche confirme :
- **bicubic** (défaut ffmpeg) : standard. Bon compromis qualité/vitesse.
- **lanczos** : meilleure qualité sur détails fins, plus lent. **~10% meilleur SSIM** d'après streaminglearningcenter.com.
- **spline16/spline36** : alternatives avancées, rarement utilisées.

**Décision** : utiliser **bicubic** pour le scaling self-ref, car c'est la méthode **dominante dans les workflows d'upscale commercial**. Un upscale fake 4K est généralement fait en bicubic (logiciels grand public, ffmpeg par défaut, HandBrake par défaut). Si on utilisait lanczos, on divergerait de la méthode utilisée côté "fake" et nos détections seraient biaisées.

#### Performance

- Film 4K 2h : ~30-40 s de calcul SSIM (single pass ffmpeg).
- **Coût acceptable** dans le pipeline §1 (peut tourner en parallèle avec d'autres analyses).
- Optimisation possible : limiter à 60 s de vidéo (`-t 60`) → réduit à ~5-8 s. **Mais risque de tomber sur des scènes uniformes non représentatives**.
- Compromis : `-t 120` (2 min au milieu du film) = ~10-15 s de calcul, représentatif.

#### Seuils à calibrer

Benchmarks empiriques à faire, mais valeurs de départ basées sur la littérature :

| SSIM self-ref | Verdict |
|---|---|
| ≥ 0.95 | **Upscale fake** probable |
| 0.90-0.95 | **Ambigu** (upscale IA de qualité, master 4K remastered depuis 2K intermédiaire) |
| 0.85-0.90 | **Vraie 4K** typique |
| < 0.85 | **Vraie 4K très détaillée** (film HDR récent) |

**Important** : ces seuils sont **indicatifs**. Le verdict final doit croiser avec :
- FFT 2D énergie HF (§7 fake 4K detection, Vague 3) → double validation
- Bitrate déclaré du fichier (upscale fake a souvent un bitrate anormalement bas pour sa résolution)
- Runtime vs original TMDb (master direct vs remaster)

#### Complémentarité avec §7 (FFT 2D fake 4K detection)

Les deux techniques sont **complémentaires, pas redondantes** :
- **SSIM self-ref** : détecte un upscale bicubique simple (95% des cas).
- **FFT 2D HF/LF ratio** : détecte tout type de déficit HF, y compris upscale IA.

Combinaison idéale :
- Si **les deux** concluent à "fake 4K" → **confidence très haute** (~0.95).
- Si **un seul** → **confidence moyenne** (~0.75).
- Si **aucun** → 4K native, confidence haute (~0.95).

Cette combinaison sera faite dans §7 quand on y arrivera. §13 produit seulement le score SSIM self-ref.

#### Cas limites

1. **Vidéo < 1080p** : scaling self-ref non pertinent (pas assez de détails à préserver). Skip si height < 1800.
2. **Vidéo non-4K mais 1440p** : seuil différent ? Pour l'instant on le traite comme 4K (scale → 960p → 1440p back). Rare, pas prioritaire.
3. **Scènes entièrement uniformes** (fond blanc, écran noir long) : SSIM 0.99+ par défaut sur ces zones. Échantillonner un segment de 2 min au milieu du film mitige.
4. **Animation 2D** : aplats → SSIM self-ref 0.99 même si c'est une vraie 4K → **faux positif**. Croiser avec `tmdb.genres`: si "Animation" → verdict `not_applicable_animation`.
5. **Film avec flou artistique intentionnel** (Blade Runner 2049) : peu de HF même en vraie 4K → SSIM élevé possible. **Faux positif**. Croiser avec bitrate (≥ 40 Mbps → probable vraie 4K malgré SSIM élevé).
6. **Master remastered 4K depuis 2K DI** (très courant au cinéma depuis 2010) : scanne en 4K mais le master intermédiaire est en 2K → HF réelles limitées. Peut donner SSIM 0.92-0.95 → **classé "ambigu"** ce qui est correct.

**Benchmarks :**

*À calibrer sur corpus `tests/fixtures/ssim_self_ref/` avec 6 fichiers étiquetés :*

| Fichier | SSIM attendu |
|---|---|
| UHD Blu-ray native 4K (Dune 2021) | ~0.85 |
| 4K HDR native (The Mandalorian) | ~0.86 |
| 4K remastered 2K DI (Blade Runner 2049) | ~0.93 |
| Fake 4K bicubic upscale 1080p | ~0.97 |
| Fake 4K AI upscale (Topaz) | ~0.92 |
| Animation 4K (Soul, Pixar) | ~0.98 (→ skip via genre) |

**Décision finale :**

1. **Stack** : **ffmpeg natif** (`ssim` filter). Zéro dépendance nouvelle.
2. **Scaling algorithm** : bicubic (cohérent avec workflows fake).
3. **Segment analysé** : 2 min au milieu du film (`-ss mid -t 120`).
4. **Setting** : `perceptual_ssim_self_ref_enabled` (défaut `True`).
5. **Skip** : si `video_height < 1800` (pas 4K), si `animation` genre TMDb.
6. **Output** : score SSIM Y (luminance), float 0.0-1.0, + verdict textuel.
7. **Intégration** : peut tourner en parallèle (§1) avec les autres analyses vidéo. Coût ~10-15 s.
8. **Stockage** : champ `ssim_self_ref: float` dans `VideoPerceptual`.

**Seuils validés :**

```python
# constants.py ajouts
SSIM_SELF_REF_SEGMENT_DURATION_S = 120            # 2 min au milieu
SSIM_SELF_REF_MIN_HEIGHT = 1800                    # skip si pas 4K
SSIM_SELF_REF_TIMEOUT_S = 45
SSIM_SELF_REF_FAKE_THRESHOLD = 0.95                # ≥ : upscale probable
SSIM_SELF_REF_AMBIGUOUS_THRESHOLD = 0.90           # 0.90-0.95 : ambigu
SSIM_SELF_REF_NATIVE_THRESHOLD = 0.85              # < : native
```

**Cas limites identifiés :**

1. Vidéo non-4K : skip, verdict `"not_applicable_resolution"`.
2. Animation : skip via cross-check genre TMDb, verdict `"not_applicable_animation"`.
3. ffmpeg timeout : retour `None`, log warning.
4. Parsing regex échoue : retour `None`.
5. Filter SSIM absent du build ffmpeg : très rare (stable depuis ffmpeg 2.x), fallback `None`.
6. Film avec flou artistique : flag `ambiguous`, l'utilisateur décide.

**Références :**

- [FFmpeg Scaler Documentation](https://ffmpeg.org/ffmpeg-scaler.html)
- [streaminglearningcenter.com — Maximizing Quality and Throughput in FFmpeg Scaling](https://streaminglearningcenter.com/ffmpeg/maximizing-quality-and-throughput-in-ffmpeg-scaling.html)
- [OTTVerse — Calculate PSNR, VMAF, SSIM using FFmpeg](https://ottverse.com/calculate-psnr-vmaf-ssim-using-ffmpeg/)
- [slhck/ffmpeg-quality-metrics GitHub](https://github.com/slhck/ffmpeg-quality-metrics) — wrapper Python, ne l'utilisons pas mais patterns utiles
- [SSIM original paper (Wang 2004)](https://ece.uwaterloo.ca/~z70wang/publications/ssim.pdf)

---

### §14 — DRC detection ✅

**Date :** 2026-04-22

**Findings :**

#### État actuel CineSort

**Excellente nouvelle** : le `crest_factor` est **déjà calculé** par [audio_perceptual.py](../../../cinesort/domain/perceptual/audio_perceptual.py) via `analyze_astats()` (regex `_RE_CREST`). Il est stocké dans `AudioPerceptual.crest_factor` et utilisé dans le scoring audio.

Le `LRA` (Loudness Range) est également calculé via `analyze_loudnorm()`.

**Ce qui manque pour §14** : juste un **verdict textuel** classifiant le niveau de compression dynamique (cinéma / standard / broadcast compressé), exposé séparément pour affichage UI et pondération dans le score composite.

#### Standards et seuils (confirmés par la recherche)

**EBU R 128** (Europe broadcast) :
- Target loudness : **-23 LUFS**
- LRA typique broadcast : **5-10 LU**
- LRA cinéma : **15-25 LU** (beaucoup plus dynamique)

**ATSC A/85** (USA broadcast) :
- Target : **-24 LKFS**
- Similaire EBU

**Crest factor — valeurs industrielles** :

| Crest factor (dB) | Type de contenu |
|---|---|
| ≥ **20 dB** | Classical music, jazz dynamique |
| 15-20 dB | **Cinéma home (Blu-ray, UHD)** ← pleine dynamique |
| 12-15 dB | Cinéma broadcast (TV, streaming UHD) |
| 8-12 dB | Streaming compressé (Netflix SDR, broadcast TV) |
| < 8 dB | **Broadcast très compressé** / podcast / midnight mode |

**LRA (Loudness Range) — complémentaire** :

| LRA (LU) | Interprétation |
|---|---|
| ≥ **18 LU** | Cinéma pleine dynamique |
| 10-18 LU | Cinéma TV / streaming standard |
| 6-10 LU | Broadcast compressé |
| < 6 LU | Très compressé (ads, pop music moderne) |

#### Cross-check crest factor + LRA

Utiliser **les deux métriques ensemble** améliore la robustesse :

```python
def classify_drc(crest_factor: float, lra: float) -> dict:
    # Score de dynamique pondéré
    score_crest = 0
    if crest_factor >= 15: score_crest = 2          # cinéma
    elif crest_factor >= 10: score_crest = 1        # standard
    elif crest_factor >= 0: score_crest = 0         # compressé
    # sinon: pas de donnée

    score_lra = 0
    if lra >= 18: score_lra = 2
    elif lra >= 10: score_lra = 1

    combined = score_crest + score_lra

    if combined >= 3:     return {"drc_category": "cinema", "confidence": 0.95}
    elif combined >= 2:   return {"drc_category": "cinema", "confidence": 0.75}
    elif combined >= 1:   return {"drc_category": "standard", "confidence": 0.80}
    else:                 return {"drc_category": "broadcast_compressed", "confidence": 0.85}
```

#### Cas particuliers

1. **Piste Atmos/TrueHD** : presque toujours "cinema" (pleine dynamique volontaire).
2. **Piste AC3 5.1 Blu-ray** : généralement "cinema" ou "standard".
3. **Piste AAC 128k streaming** : typiquement "standard" à "broadcast_compressed".
4. **Piste "midnight mode" secondaire** : **volontairement compressée** pour écoute de nuit. Détection possible via `track.title` ou `disposition`. Flag `midnight_mode` (hors scope §14 strict).
5. **Film musical/concert** : LRA naturellement élevé, pas forcément cinéma mais dynamique. Pas bloquant.
6. **Film avec effet artistique de compression** (Gravity, Dunkirk climax) : certaines scènes sont volontairement "compressées" pour la tension. L'analyse globale film reste correcte car mesurée sur l'ensemble.
7. **Track stéréo commentaire** : souvent très compressé (parole uniforme). À exclure de l'analyse ? Déjà géré : `select_best_audio_track()` évite les commentaires.

#### Impact sur la comparaison de doublons

Dans la modale deep-compare Phase 4, le DRC sera un **critère de comparaison audio** :
- Fichier A avec `drc_category="cinema"` vs B avec `drc_category="broadcast_compressed"` → **A gagne +10 pts** sur ce critère.
- Texte explicatif FR : "Fichier A a une dynamique cinéma complète (crest 18 dB). Fichier B est compressé comme un stream broadcast (crest 9 dB) — expérience d'écoute moins riche en salle."

#### Coût

- **Zéro calcul supplémentaire** : tout se base sur les valeurs déjà calculées par astats et loudnorm.
- Juste une fonction de classification à ajouter. Effort total : **1 h**.

**Benchmarks :**

*À valider sur 5 fichiers corpus pendant l'implémentation :*

| Fichier | Crest attendu | LRA attendu | Verdict attendu |
|---|---|---|---|
| UHD Blu-ray Dolby Atmos (Dune) | 18-22 dB | 20-28 LU | cinema |
| Blu-ray AC3 640k (Matrix) | 14-17 dB | 15-20 LU | cinema |
| Streaming Netflix 4K AAC 256k | 10-13 dB | 8-12 LU | standard |
| DVD AC3 448k | 12-15 dB | 10-15 LU | standard |
| Stream broadcast TV compressé | 6-9 dB | 4-8 LU | broadcast_compressed |

**Décision finale :**

1. **Stack** : **zéro dépendance nouvelle**. Utilise les valeurs `crest_factor` + `lra` existantes.
2. **Fonction unique** : `classify_drc(crest_factor, lra) -> tuple[str, float]` dans `audio_perceptual.py`.
3. **Valeurs retournées** : `("cinema" | "standard" | "broadcast_compressed", confidence)`.
4. **Champ ajouté** : `AudioPerceptual.drc_category: str` et `drc_confidence: float`.
5. **Pondération dans score composite** : **15%** du score audio final (voir §16 Score composite).
6. **Pas de setting dédié** : toujours actif (coût nul).

**Seuils validés :**

```python
# constants.py ajouts
DRC_CREST_CINEMA = 15.0            # dB
DRC_CREST_STANDARD = 10.0          # dB
DRC_LRA_CINEMA = 18.0              # LU
DRC_LRA_STANDARD = 10.0            # LU
```

**Cas limites identifiés :**

1. **crest_factor is None** (astats échoué) : utiliser seulement LRA.
2. **LRA is None** (loudnorm échoué) : utiliser seulement crest_factor.
3. **Les 2 sont None** : verdict `drc_category="unknown"`, confidence 0.
4. **Film musical/concert** : verdict `cinema` (correct) + note optionnelle "contenu musical dynamique".
5. **Commentaire track analysé par erreur** : n'arrive pas en pratique car `select_best_audio_track()` l'exclut.

**Références :**

- [Wikipedia — Dynamic range compression](https://en.wikipedia.org/wiki/Dynamic_range_compression)
- [EBU R 128 specification (PDF)](https://tech.ebu.ch/docs/r/r128.pdf)
- [EBU TechReview — Loudness and Dynamic Range in broadcast audio](https://tech.ebu.ch/docs/techreview/trev_293-spath.pdf)
- [Sound on Sound — Dynamic Range & The Loudness War](https://www.soundonsound.com/sound-advice/dynamic-range-loudness-war)
- [Genesis Mix Lab — Dynamic Range in Mastering](https://genesismixlab.com/guides/mastering-delivery/dynamic-range-mastering/)
- [iConnectivity — EBU R128 explained](https://www.iconnectivity.com/blog/2017/6/10/ebu-r128-the-important-audio-breakthrough-youve-never-heard-of)
- Code CineSort : [audio_perceptual.py](../../../cinesort/domain/perceptual/audio_perceptual.py) (crest/LRA déjà extraits)

---

## Vague 3 — Métadonnées techniques

### §5 — HDR metadata ✅

**Date :** 2026-04-22

**Findings :**

#### État actuel CineSort

[cinesort/infra/probe/normalize.py](../../../cinesort/infra/probe/normalize.py) extrait déjà `color_space`, `color_primaries`, `color_transfer` et un flag `hdr_detected` basique. **Mais** :
- Pas d'extraction MaxCLL / MaxFALL (luminance réelle du contenu).
- Pas d'extraction des primaires du mastering display.
- Pas de validation (film tagué HDR mais luminance = 0 → fake HDR).

Donc **la base est là**, il faut l'**enrichir**.

#### Commande ffprobe standard (confirmée par la recherche)

```bash
ffprobe -hide_banner -loglevel warning \
  -select_streams v -print_format json \
  -show_frames -read_intervals "%+#1" \
  -show_entries "frame=color_space,color_primaries,color_transfer,side_data_list,pix_fmt" \
  <file>
```

Le paramètre `-read_intervals "%+#1"` = lire **1 seule frame** → ultra-rapide (< 1 s même sur 4K).

#### Structure de `side_data_list` — découverte recherche

JSON retourné pour un HDR10 :

```json
"side_data_list": [
  {
    "side_data_type": "Mastering display metadata",
    "red_x": "34000/50000",
    "red_y": "16000/50000",
    "green_x": "13250/50000",
    "green_y": "34500/50000",
    "blue_x": "7500/50000",
    "blue_y": "3000/50000",
    "white_point_x": "15635/50000",
    "white_point_y": "16450/50000",
    "min_luminance": "50/10000",
    "max_luminance": "10000000/10000"
  },
  {
    "side_data_type": "Content light level metadata",
    "max_content": 1000,      // = MaxCLL (nits)
    "max_average": 400        // = MaxFALL (nits)
  }
]
```

**Points clés** :
- Les valeurs chromatiques sont des **ratios (numerator/denominator)** → parser via split `/` + division.
- `max_luminance` / `min_luminance` sont en **0.0001 cd/m²** (nits) → diviser par 10000.
- MaxCLL typique : **1000-4000 nits** (films modernes). 0 ou absent = MaxCLL non fourni.
- MaxFALL typique : **100-500 nits**.

#### HDR10 vs HDR10+ vs HLG — distinction claire

**HDR10** (standard de base) :
- `color_primaries: bt2020`
- `color_transfer: smpte2084` (PQ)
- `color_space: bt2020nc` ou `bt2020c`
- `side_data_list` contient `Mastering display metadata` + `Content light level metadata`

**HDR10+** (Samsung / 20th Century Studios / Amazon, SMPTE ST 2094-40) :
- Mêmes caractéristiques HDR10 de base (bt2020, smpte2084).
- **Plus** : métadonnées dynamiques **par scène** (Dynamic Tone Mapping — DTM) qui ajustent le mapping de luminance en fonction du contenu. Principe similaire à Dolby Vision mais **open royalty-free**.
- Dans `side_data_list` : entrée de type `"HDR Dynamic Metadata SMPTE2094-40 (HDR10+)"` ou variantes. Format :
  ```json
  {
    "side_data_type": "HDR Dynamic Metadata SMPTE2094-40 (HDR10+)",
    "application_version": 1,
    "num_windows": 1,
    "targeted_system_display_maximum_luminance": 1000,
    ...
  }
  ```
- **Rareté** : moins déployé que Dolby Vision. Principalement Samsung TVs, quelques UHD Blu-rays (20th Century), streams Amazon Prime Video.
- **Compatibilité** : un fichier HDR10+ est **toujours** compatible HDR10 (la metadata dynamique est un layer optionnel).
- **Détection** : présence du `side_data_type` HDR10+ dans n'importe quelle frame analysée → flag.
- **Avantage qualité** : picture par picture brightness adjustment → meilleures ombres et hautes lumières vs HDR10 statique.
- **Vs Dolby Vision** : technique similaire mais HDR10+ est libre de droits, DV nécessite licence Dolby. Qualité perçue comparable.

**Détection subtile** : `ffprobe -show_frames -read_intervals "%+#1"` (1 frame seulement) peut **rater** le HDR10+ si la frame lue n'a pas de metadata dynamique (elles sont par scène, pas par frame). **Solution** : scanner plusieurs frames (ex: 5 réparties dans le film) et vérifier si **au moins une** contient le type HDR10+.

**HLG** (Hybrid Log-Gamma, BBC/NHK broadcast) :
- `color_primaries: bt2020`
- `color_transfer: arib-std-b67` ← signature clé HLG
- Pas de mastering metadata généralement (c'est un standard broadcast live)

**SDR classique** :
- `color_primaries: bt709`
- `color_transfer: bt709`
- `color_space: bt709`

**Détection robuste — algorithme** :

```python
def detect_hdr_type(color_primaries, color_transfer, side_data_list):
    # HLG d'abord (le plus spécifique)
    if color_transfer == "arib-std-b67":
        return "hlg"
    # Dolby Vision (via side_data)
    if any(sd.get("side_data_type") == "DOVI configuration record" for sd in side_data_list):
        return "dolby_vision"
    # HDR10+ (dynamic metadata)
    if any("HDR10+" in str(sd.get("side_data_type", "")) for sd in side_data_list):
        return "hdr10_plus"
    # HDR10 classique
    if color_transfer == "smpte2084" and color_primaries == "bt2020":
        return "hdr10"
    # SDR
    return "sdr"
```

#### Validation HDR — détection des faux HDR

**Cas pathologique** : fichier tagué HDR10 (`color_primaries=bt2020, color_transfer=smpte2084`) mais **pas de MaxCLL/MaxFALL** → signe de :
- Ré-encodage mal fait qui a gardé les tags sans transférer la metadata.
- Container rebuild suspect.
- Pseudo-HDR artificiel.

**Règle proposée** :
```python
def validate_hdr(hdr_type, max_cll, max_fall):
    if hdr_type == "hdr10" and (max_cll is None or max_cll == 0):
        return {"hdr_valid": False, "flag": "hdr_metadata_missing"}
    if hdr_type == "hdr10" and max_cll < 500:
        # HDR sans punch réel ? Suspect mais pas bloquant
        return {"hdr_valid": True, "flag": "hdr_low_punch"}
    return {"hdr_valid": True, "flag": None}
```

#### Ajout : détection HDR10+ robuste (multi-frames)

Pour détecter HDR10+ de façon fiable, la lecture d'1 seule frame n'est pas suffisante. Les métadonnées SMPTE2094-40 sont **par scène**, pas par frame.

**Commande dédiée HDR10+** :
```bash
ffprobe -hide_banner -loglevel warning \
  -select_streams v -print_format json \
  -show_frames -read_intervals "%+#5" \
  -show_entries "frame=side_data_list" \
  <file>
```
`%+#5` = lire 5 frames. Le parcours vérifie si `side_data_type` HDR10+ apparaît dans au moins une.

**Intégration** : on peut combiner §5 en 2 passes :
- Pass 1 (1 frame) : détection HDR10/DV/HLG + extraction MaxCLL/MaxFALL/mastering display.
- Pass 2 (5 frames, **uniquement si HDR10 détecté**) : vérification HDR10+.

Coût total : ~1.5-3 s (pass 1 rapide + pass 2 conditionnel).

**Hiérarchie qualité finale** (pour scoring et UI) :

| Rang | Type HDR | Score (pour comparaison §16) |
|---|---|---|
| 1 | Dolby Vision Profile 8.1 | 100 |
| 2 | Dolby Vision Profile 7 | 95 |
| 3 | **HDR10+** | 90 |
| 4 | HDR10 (MaxCLL ≥ 1000) | 85 |
| 5 | Dolby Vision Profile 5 | 80 (pénalisé incompatibilité) |
| 6 | HLG | 75 |
| 7 | HDR10 low punch (MaxCLL < 500) | 65 |
| 8 | HDR10 invalid (no metadata) | 50 |
| 9 | SDR | 40 |

#### Parsing des ratios chromatiques

Les valeurs type `"34000/50000"` doivent être converties :

```python
def parse_ratio(s: str) -> float:
    if not s or "/" not in s:
        return 0.0
    num, denom = s.split("/", 1)
    try:
        return float(num) / float(denom) if float(denom) != 0 else 0.0
    except ValueError:
        return 0.0
```

Pour `max_luminance` en nits : `parse_ratio(s) / 1.0` (déjà divisé par 10000 dans le dénominateur).

Exemple : `"10000000/10000"` → 1000.0 cd/m². Standard.

#### Coût performance

- ffprobe 1 frame : ~500 ms - 2 s selon complexité du codec.
- **Acceptable** en pipeline, même en single-thread.

**Décision finale :**

1. **Stack** : ffprobe natif, zéro dépendance nouvelle.
2. **Extraction** : commande ffprobe sur 1 frame, parse JSON.
3. **Stockage** : 7 nouveaux champs dans `NormalizedProbe` (puis dans `VideoPerceptual` pour l'analyse) :
   - `hdr_type` : `"sdr" | "hdr10" | "hdr10_plus" | "hlg" | "dolby_vision"`
   - `max_cll` : float (nits, 0 si absent)
   - `max_fall` : float (nits, 0 si absent)
   - `min_luminance` : float (nits)
   - `max_luminance` : float (nits)
   - `hdr_valid` : bool
   - `hdr_validation_flag` : str (ex: "hdr_metadata_missing")
4. **Validation** : détecter les HDR invalides (pas de MaxCLL) et les flags de punch faible.
5. **Pas de setting user** : toujours actif (coût nul, toujours utile).

**Seuils validés :**

```python
# constants.py ajouts
HDR_MAX_CLL_WARNING_THRESHOLD = 500      # nits — en dessous : HDR low punch
HDR_MAX_CLL_TYPICAL_MIN = 1000            # nits — cible normale films
HDR_MAX_FALL_TYPICAL = 100                # nits — cible normale
```

**Cas limites identifiés :**

1. HDR10 sans MaxCLL → flag `hdr_metadata_missing`, verdict "HDR douteux".
2. HDR10 avec MaxCLL = 400 → flag `hdr_low_punch`, HDR valide mais mou.
3. HLG (broadcast) → pas de mastering metadata attendu, normal.
4. Dolby Vision → passe au §6 pour analyse détaillée.
5. SDR avec color_primaries bt2020 (erreur encode) → flag `color_mismatch_sdr_bt2020`.
6. Vidéo animation HDR : MaxCLL peut être artificiellement élevé (aplats saturés). Pas de faux positif, juste à documenter.
7. ffprobe parse échoue → retour `hdr_type="sdr"` par défaut, flag `hdr_parse_failed`.

**Références :**

- [probe.dev — HDR Video Analysis Workflows](https://www.probe.dev/resources/hdr-video-analysis-workflows)
- [Dolby — Calcul MaxCLL/MaxFALL](https://professionalsupport.dolby.com/s/article/Calculation-of-MaxFALL-and-MaxCLL-metadata?language=en_US)
- [FastFlix Issue #102 — Color space/primaries parsing HDR](https://github.com/cdgriffith/FastFlix/issues/102)
- [FFmpegCore Issue #216 — Mastering Display MetaData 4K](https://github.com/rosenbjerg/FFMpegCore/issues/216)
- [Code Calamity — Encoding UHD 4K HDR10 Videos](https://codecalamity.com/encoding-uhd-4k-hdr10-videos-with-ffmpeg/)
- [Daejeon Chronicles — MaxCLL MaxFALL DaVinci Resolve](https://daejeonchronicles.com/2022/03/23/generate-maxcll-and-maxfall-hdr10-metadata-in-davinci-resolve/)
- Code CineSort : [normalize.py](../../../cinesort/infra/probe/normalize.py)

---

### §6 — Dolby Vision ✅

**Date :** 2026-04-22

**Findings :**

#### Les 4 profils Dolby Vision qui comptent

Source : [Dolby Professional Support](https://professionalsupport.dolby.com/s/article/What-is-Dolby-Vision-Profile?language=en_US) + forums MakeMKV.

| Profil | BL | EL | RPU | Compatibilité | Usage typique |
|---|---|---|---|---|---|
| **Profile 5** | IPTPQc2 (proprietary) | — | Oui | **AUCUNE** (pure DV only) | Netflix, Disney+, Amazon streams |
| **Profile 7** | HEVC HDR10 | Enhancement Layer | Oui | HDR10 (BL seulement) | UHD Blu-ray originaux |
| **Profile 8.1** | HEVC HDR10 | — | Oui | **HDR10 full** | Ré-encodages modernes (x265 hybrid) |
| **Profile 8.2** | HEVC SDR | — | Oui | SDR | Rare |
| **Profile 8.4** | HEVC HLG | — | Oui | HLG | Broadcast HDR |

**Point stratégique** : Profile 5 a une **couleur proprietary IPTPQc2** → sans player DV licensé, les couleurs sont **complètement fausses** (vert délavé, rose partout). Un utilisateur non-équipé DV doit **éviter** les fichiers Profile 5.

**Point pratique** : Profile 8.1 est **le sweet spot** pour une compatibilité maximale (marche sur player DV **et** player HDR10 normal).

**Profile 7** : marche mais l'Enhancement Layer est ignoré par les players HDR10 → on voit le HDR10 de base, pas l'amélioration DV. Acceptable.

#### Détection via ffprobe

La même commande que §5 montre un nouveau `side_data_type` :

```json
"side_data_list": [
  {
    "side_data_type": "DOVI configuration record",
    "dv_version_major": 1,
    "dv_version_minor": 0,
    "dv_profile": 8,
    "dv_level": 7,
    "rpu_present_flag": 1,
    "el_present_flag": 0,
    "bl_present_flag": 1,
    "dv_bl_signal_compatibility_id": 1
  }
]
```

**Champs décodés** :
- `dv_profile` : 5, 7, 8 (sub-profiles via compatibility_id)
- `rpu_present_flag` : métadonnées dynamiques présentes (toujours 1 pour DV valide)
- `el_present_flag` : enhancement layer présent (1 = Profile 7)
- `bl_present_flag` : base layer présent (toujours 1)
- `dv_bl_signal_compatibility_id` : définit le sous-profile :
  - `0` : Profile 5 (IPTPQc2 proprietary)
  - `1` : Profile 8.1 (HDR10 compatible)
  - `2` : Profile 8.2 (SDR)
  - `4` : Profile 8.4 (HLG)

**Règle de classification** :

```python
def classify_dv_profile(dv_profile, compat_id, el_present):
    if dv_profile == 5:
        return {"profile_name": "5", "label": "Profile 5 (IPTPQc2 proprietary)",
                "compat": "none", "warning": "Player Dolby Vision requis pour couleurs correctes"}
    if dv_profile == 7 or el_present == 1:
        return {"profile_name": "7", "label": "Profile 7 (BL+EL+RPU)",
                "compat": "hdr10_partial", "warning": "Fallback HDR10 ignore l'enhancement layer"}
    if dv_profile == 8:
        if compat_id == 1:
            return {"profile_name": "8.1", "label": "Profile 8.1 (HDR10 compatible)",
                    "compat": "hdr10_full", "warning": None}
        elif compat_id == 2:
            return {"profile_name": "8.2", "label": "Profile 8.2 (SDR)", ...}
        elif compat_id == 4:
            return {"profile_name": "8.4", "label": "Profile 8.4 (HLG)", ...}
    return {"profile_name": "unknown", "label": "Dolby Vision (profil non identifié)",
            "compat": "unknown", "warning": "Profile DV non reconnu"}
```

#### Alternative : dovi_tool

[quietvoid/dovi_tool](https://github.com/quietvoid/dovi_tool) est le **reference tool** pour Dolby Vision (Rust, standalone CLI, ~15 MB). Permet de :
- Inspecter précisément le RPU (`dovi_tool info -i file.mkv`)
- Convertir entre profiles (7 → 8.1 pour rendre compatible HDR10)
- Valider l'intégrité RPU

**Décision** : **ne PAS embarquer dovi_tool** en v7.5.0. ffprobe suffit pour la **détection** (notre besoin). dovi_tool serait nécessaire uniquement si on voulait **convertir** les profils — hors scope CineSort.

#### Pondération dans la comparaison

Dans la modale deep-compare Phase 4, si 2 fichiers sont tous deux DV :
- Profile 8.1 > Profile 7 > Profile 5 (classement par compatibilité + qualité)
- Score : +15 pts pour 8.1, +10 pts pour 7, +5 pts pour 5 (pénalisé car incompatible)

Si un fichier est DV et l'autre HDR10 :
- DV 8.1 > HDR10 (l'inverse possible si DV 5 vs HDR10 propre)

#### Coût performance

Même commande ffprobe que §5 → **coût combiné** = 1 seule exécution ffprobe pour §5 + §6.

#### Cas limites

1. **Profile 5 sans player DV** : l'utilisateur voit les couleurs fausses mais le fichier est valide. Flag `dv_profile_5_warning` pour avertir dans l'UI.
2. **Profile 7 EL manquant** (rip incomplet) : `el_present_flag=1` mais pas d'EL dans le stream → détection via bitstream plus profond, hors scope.
3. **Fichier tagué DV mais sans RPU** (faux DV) : `rpu_present_flag=0` → flag `dv_invalid_no_rpu`.
4. **ffprobe trop vieux** (< 4.3) peut ne pas parser `DOVI configuration record` → fallback `hdr_type` depuis §5.
5. **DV sur container MP4** : supporté par DV profile 5 et 8, rarement 7 (plutôt MKV).

**Décision finale :**

1. **Stack** : ffprobe natif (même commande que §5, donc coût zéro supplémentaire).
2. **Intégration** : mutualiser le call ffprobe entre §5 HDR et §6 DV → 1 seul appel.
3. **Stockage** : 5 champs ajoutés à `NormalizedProbe` :
   - `dv_present` : bool
   - `dv_profile` : str (`"5" | "7" | "8.1" | "8.2" | "8.4" | "unknown"`)
   - `dv_compatibility` : str (`"none" | "hdr10_full" | "hdr10_partial" | "sdr" | "hlg"`)
   - `dv_el_present` : bool
   - `dv_warning` : Optional[str] (messages UI FR)
4. **Pas de dovi_tool** : pas besoin pour la détection, seul la conversion le nécessiterait.
5. **Pas de setting user** : toujours actif.

**Seuils/constantes validés :**

```python
# constants.py ajouts
DV_PROFILE_LABELS = {
    "5": "Dolby Vision Profile 5 (IPTPQc2)",
    "7": "Dolby Vision Profile 7 (BL+EL+RPU)",
    "8.1": "Dolby Vision Profile 8.1 (HDR10 compatible)",
    "8.2": "Dolby Vision Profile 8.2 (SDR)",
    "8.4": "Dolby Vision Profile 8.4 (HLG)",
}
DV_COMPAT_RANKING = {"hdr10_full": 3, "hlg": 2, "hdr10_partial": 2, "sdr": 1, "none": 0}
```

**Cas limites identifiés :**

1. Fichier DV mais ffprobe trop vieux → fallback HDR10 detection (§5).
2. Profile 5 pur (Netflix/Disney+ rip) : valide mais warning affiché dans UI.
3. Profile 7 avec EL perdu au remux : détecté, flag `dv_el_expected_missing`.
4. Mix DV+HDR10+ sur un même fichier (ultra rare) : priorité DV dans notre classification.

**Références :**

- [Dolby — Dolby Vision Profiles and Levels](https://professionalsupport.dolby.com/s/article/What-is-Dolby-Vision-Profile?language=en_US)
- [quietvoid/dovi_tool — GitHub](https://github.com/quietvoid/dovi_tool)
- [dovi_tool DeepWiki — Profile Conversion](https://deepwiki.com/quietvoid/dovi_tool/5.1-profile-conversion)
- [MakeMKV forum — Profile 5 to 8.1](https://forum.makemkv.com/forum/viewtopic.php?style=11&t=28854)
- [MakeMKV forum — DV x265 advantages/caveats](https://forum.makemkv.com/forum/viewtopic.php?t=26514)
- [Blackmagic forum — Encoding DV 8.4 Profile](https://forum.blackmagicdesign.com/viewtopic.php?f=21&t=150538)
- [Doom9 — How to detect Dolby Vision](https://forum.doom9.org/showthread.php?t=174954)

---

### §7 — Fake 4K / upscale detection ✅

**Date :** 2026-04-22

**Findings :**

#### Complémentarité avec §13 SSIM self-ref

§13 propose **SSIM self-referential** (downscale→upscale + comparer). §7 propose **FFT 2D spatial frequency analysis** (ratio énergie HF/LF des frames).

**Les deux sont complémentaires, pas redondants** :

| Détection | SSIM self-ref (§13) | FFT 2D (§7) |
|---|---|---|
| Upscale bicubique 1080p → 4K | ✅ très bon | ✅ bon |
| Upscale IA (Topaz, ESRGAN) | ⚠️ passe parfois | ✅ meilleur (détecte HF synthétiques incohérentes) |
| Master 4K remastered depuis 2K DI | ⚠️ ambigu (SSIM ~0.93) | ⚠️ ambigu (HF limitée) |
| Animation 4K aplats | ❌ faux positif (SSIM ~0.98) | ❌ faux positif (peu de HF naturelle) |
| Film flou artistique (Revenant) | ❌ faux positif possible | ⚠️ ambigu |

**Stratégie** : combiner les deux pour **double validation**. Pondération :
- Les 2 concluent "fake" → confidence **0.95**
- Un seul → confidence **0.70**
- Aucun ne conclut fake → 4K native, confidence 0.90

#### Principe FFT 2D

**Théorie** : une image 4K native contient des détails fins qui se traduisent par de l'énergie dans les **hautes fréquences spatiales** (HF). Un upscale bicubique 1080p → 4K produit des pixels interpolés qui **n'ajoutent pas de HF** → l'énergie HF est faible relativement aux basses fréquences (LF).

**Métrique** : ratio `energy_HF / energy_total` sur le spectre 2D.

#### Algorithme détaillé

```python
def fft2d_hf_ratio(frame_y: np.ndarray, hf_cutoff_ratio: float = 0.25) -> float:
    """Calcule le ratio d'énergie haute fréquence / totale.

    frame_y: array 2D (H, W) en float.
    hf_cutoff_ratio: seuil fréquentiel en fraction de Nyquist (0.25 = dernier quart).

    Returns:
        Ratio 0.0-1.0.
    """
    h, w = frame_y.shape
    # FFT 2D
    spectrum = np.fft.fftshift(np.fft.fft2(frame_y))
    magnitude = np.abs(spectrum)

    # Masque HF : anneau extérieur (distance > hf_cutoff * min(h, w)/2)
    cy, cx = h // 2, w // 2
    y, x = np.ogrid[:h, :w]
    distance = np.sqrt((y - cy)**2 + (x - cx)**2)
    max_radius = min(h, w) / 2
    hf_mask = distance > (hf_cutoff_ratio * max_radius)

    total_energy = np.sum(magnitude ** 2)
    hf_energy = np.sum((magnitude * hf_mask) ** 2)

    return hf_energy / total_energy if total_energy > 0 else 0.0
```

#### Calibration empirique — point crucial

Les seuils dépendent énormément du **contenu du film**. Un drame statique a naturellement moins de HF qu'un film d'action.

**Stratégie de calibration** :
1. Mesurer le ratio sur 5 frames du film.
2. Calculer la **médiane** (plus robuste que moyenne).
3. Comparer à des seuils de référence.

**Seuils de départ** (à valider sur corpus) :

| Ratio HF médian | Verdict |
|---|---|
| > **0.18** | **4K native** (forte confidence) |
| 0.12-0.18 | 4K native probable |
| 0.08-0.12 | **Ambigu** (master 2K DI, IA upscale) |
| < 0.08 | **Upscale fake** (bicubique depuis 1080p) |

**Attention** : ces seuils supposent une résolution proche 4K (3840×2160). Pour du 1440p, il faudrait des seuils différents → **skip §7 pour résolutions ≠ 4K**.

#### Choix des frames à analyser

- Utiliser **5 frames** déjà extraites par `extract_representative_frames()` (§4 hybride).
- Calculer le ratio sur chaque → médiane finale.
- Coût : ~50-100 ms par frame FFT 2D → **~500 ms total** pour 5 frames.
- **Très rapide** vs SSIM self-ref (10-15 s).

#### Cas limites

1. **Frames très sombres** (scène nuit) : peu de détails, ratio bas par nature → **filtrer** avec `y_avg > 20` (skip frames trop sombres).
2. **Frames uniformes** (scène fond bleu, écran titre) : ratio extrêmement bas → **filtrer** via check variance.
3. **Film noir et blanc** : fonctionne (on analyse juste la luminance Y).
4. **Animation** : aplats → peu de HF naturel → faux positif garanti. **Cross-check tmdb.genres** pour skip animation.
5. **Bruit de compression artificiellement présent dans les HF** : un upscale de **très haute qualité** peut ajouter du bruit qui ressemble à des HF → ratio artificiellement élevé → faux négatif. Combinaison avec SSIM self-ref §13 mitige.
6. **Film > 4K (ex: 6K, 8K scan cinéma)** : HF riche, ratio très élevé → "native". Correct.
7. **Upscale AI (Topaz Video AI)** : reconstruit des détails plausibles → ratio intermédiaire (0.10-0.15) → zone ambigu → à croiser avec SSIM self-ref.

#### Benchmarks attendus (à calibrer)

| Fichier test | Ratio HF médian attendu | Verdict |
|---|---|---|
| UHD Blu-ray Dune 2021 native | 0.20-0.24 | `4k_native` |
| 4K HDR The Mandalorian native | 0.19-0.22 | `4k_native` |
| 4K remastered Blade Runner 2049 (2K DI) | 0.11-0.14 | `ambiguous_2k_di` |
| Fake 4K bicubic upscale 1080p | 0.05-0.08 | `fake_4k_bicubic` |
| Fake 4K Topaz AI upscale | 0.10-0.13 | `ambiguous_ai_upscale` |
| 4K animation Pixar Soul | 0.04-0.07 | (skip via genre) |

**Décision finale :**

1. **Stack** : **numpy pur** (FFT via `np.fft.fft2`, zéro dépendance nouvelle, cohérent avec §9).
2. **Frames analysées** : 5 frames déjà extraites, filtrées (pas trop sombres, pas uniformes).
3. **Métrique** : ratio HF (dernier quart du spectre) / énergie totale.
4. **Cross-check** : combinaison avec SSIM self-ref §13 pour verdict final.
5. **Skip** : vidéo non-4K (height < 1800), animation.
6. **Stockage** : 3 champs dans `VideoPerceptual` :
   - `fft_hf_ratio_median` : float
   - `fake_4k_verdict_fft` : str (`"4k_native" | "ambiguous_2k_di" | "ambiguous_ai_upscale" | "fake_4k_bicubic" | "not_applicable_*"`)
   - `fake_4k_verdict_combined` : str (final verdict en combinant §7 et §13)
7. **Pas de setting** : toujours actif (coût minimal).

**Seuils validés :**

```python
# constants.py ajouts
FAKE_4K_FFT_HF_CUTOFF_RATIO = 0.25             # dernier quart de Nyquist spatial
FAKE_4K_FFT_THRESHOLD_NATIVE = 0.18
FAKE_4K_FFT_THRESHOLD_AMBIGUOUS = 0.08
FAKE_4K_FFT_MIN_Y_AVG = 20                      # skip frames trop sombres
FAKE_4K_FFT_MIN_VARIANCE = 200                  # skip frames uniformes
FAKE_4K_MIN_HEIGHT = 1800                       # skip si pas 4K
```

**Fonction de combinaison §7 + §13 :**

```python
def combine_fake_4k_verdicts(
    fft_ratio: Optional[float],
    ssim_self_ref: Optional[float],
) -> tuple[str, float]:
    """Combine les 2 verdicts pour un final robuste."""
    fft_says_fake = fft_ratio is not None and fft_ratio < FAKE_4K_FFT_THRESHOLD_AMBIGUOUS
    ssim_says_fake = ssim_self_ref is not None and ssim_self_ref >= SSIM_SELF_REF_FAKE_THRESHOLD

    if fft_says_fake and ssim_says_fake:
        return ("fake_4k_confirmed", 0.95)
    elif fft_says_fake or ssim_says_fake:
        return ("fake_4k_probable", 0.70)
    else:
        return ("4k_native", 0.90)
```

**Cas limites identifiés :**

1. < 2 frames valides après filtrage (film sombre) → `insufficient_frames`, pas de verdict.
2. Résolution != 4K → `not_applicable_resolution`.
3. Animation → `not_applicable_animation` (via genre TMDb).
4. Frame corrompue lors du FFT → skip, continuer avec les autres.
5. Film avec plans fixes très longs (Koyaanisqatsi) → frames uniformes, peu utilisables.

**Références :**

- [Real Versus Fake 4k - Authentic Resolution Assessment (ResearchGate)](https://www.researchgate.net/publication/352171133_Real_Versus_Fake_4k_-_Authentic_Resolution_Assessment)
- [Fourier Transform 2D - Gwyddion](https://gwyddion.net/documentation/user-guide-en/fourier-transform.html)
- [Spatial Frequency Domain — University of Auckland](https://www.cs.auckland.ac.nz/courses/compsci773s1c/lectures/ImageProcessing-html/topic1.htm)
- [Image scaling - Wikipedia](https://en.wikipedia.org/wiki/Image_scaling)
- [DeepFake detection HF network — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0957417424005980) — patterns HF similaires
- [ATOTO — How to Spot Fake 4K Dashcams (vulgarisation)](https://www.atotodirect.com/blogs/guides/dashcam-resolution-interpolation-guide)

---

### §8 — Interlacing, crop, judder ✅

**Date :** 2026-04-22

**Findings :**

Cette section regroupe 3 filtres FFmpeg natifs, indépendants, peu coûteux. Je les traite ensemble car la logique d'intégration est similaire.

---

#### 8.1 Interlacing detection — `idet`

**Commande** :
```bash
ffmpeg -i <file> -ss 30 -t 30 -vf idet -an -f null -v info -
```
(`-ss 30 -t 30` : analyse sur 30 s au début, évite génériques logo, suffisant pour détection)

**Sortie stderr** (exemple typique) :
```
[Parsed_idet_0 @ 0x...] Repeated Fields: Neither: 720 Top: 0 Bottom: 0
[Parsed_idet_0 @ 0x...] Single frame detection: TFF: 719 BFF: 0 Progressive: 1 Undetermined: 0
[Parsed_idet_0 @ 0x...] Multi frame detection: TFF: 718 BFF: 0 Progressive: 2 Undetermined: 0
```

**Parser** (regex) :
```python
_RE_IDET_MULTI = re.compile(
    r"Multi frame detection:\s*TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*Progressive:\s*(\d+)\s*Undetermined:\s*(\d+)"
)
```

**Règle** :
- `tff + bff` dominant → **interlaced** (TFF = top field first, BFF = bottom field first)
- `progressive` dominant → **progressive** (cas normal films modernes)
- Détection : `(tff + bff) / (tff + bff + progressive) > 0.3` → flag `interlaced_detected`

**Cas limites** :
- DVD rip mal désentrelacé → 50/50 TFF/BFF → detect OK.
- Télécinéma 3:2 pulldown (film 24p transféré 30i) → progressive majoritaire mais avec patterns → voir `mpdecimate` §8.3.
- Source 25p européenne convertie 30p → peu d'impact, rare.

**Coût** : ~5-10 s pour 30 s de vidéo analysée.

---

#### 8.2 Crop / black bars detection — `cropdetect`

**Commande** :
```bash
ffmpeg -i <file> -ss 120 -t 60 -vf "cropdetect=limit=24:round=16" -an -f null -v info -
```
(`-ss 120 -t 60` : saute le générique début, analyse 1 min au milieu. `limit=24` = seuil luminance pour considérer "noir", `round=16` = arrondi à multiples de 16 pour compatibilité codecs)

**Sortie stderr** (chaque frame) :
```
[Parsed_cropdetect_0 @ 0x...] x1:0 x2:1919 y1:139 y2:940 w:1920 h:800 x:0 y:140 pts:... t:120.0 crop=1920:800:0:140
```

**Stratégie parsing** : prendre la **dernière ligne** `crop=W:H:X:Y` (la plus stable après analyse sur 60 s).

```python
_RE_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")
matches = _RE_CROP.findall(stderr)
final_crop = matches[-1] if matches else None
```

**Analyse** :
- `W:H` détecté = résolution "utile" (sans bandes noires)
- Container `orig_w:orig_h`
- Si `(W, H) != (orig_w, orig_h)` → bandes noires présentes
- Aspect ratio détecté : `W/H` → compare aux standards (16:9=1.778, 2.35:1=2.35, 2.39:1=2.39, 4:3=1.333)

**Verdict** :
```python
def classify_crop(orig_w, orig_h, crop_w, crop_h):
    if crop_w == orig_w and crop_h == orig_h:
        return {"has_bars": False, "verdict": "full_frame"}

    # Bandes horizontales (letterbox, plus courant)
    if crop_w == orig_w and crop_h < orig_h:
        ar_detected = crop_w / crop_h
        if abs(ar_detected - 2.35) < 0.05:
            return {"has_bars": True, "verdict": "letterbox_2_35"}
        if abs(ar_detected - 2.39) < 0.05:
            return {"has_bars": True, "verdict": "letterbox_2_39"}
        return {"has_bars": True, "verdict": "letterbox_other", "aspect": ar_detected}

    # Bandes verticales (pillarbox, rare)
    if crop_h == orig_h and crop_w < orig_w:
        return {"has_bars": True, "verdict": "pillarbox"}

    # Windowbox (cas rare, les deux)
    return {"has_bars": True, "verdict": "windowbox"}
```

**Importance comparaison** : 2 fichiers du même film, l'un letterboxed 2.35 intégré au conteneur 1920×800 vs l'autre 1920×1080 avec bandes noires → préférer le 1920×800 (pas de gaspillage, bitrate mieux utilisé).

**Coût** : ~5-10 s pour 60 s.

---

#### 8.3 Motion judder / 3:2 pulldown — `mpdecimate`

**Commande** :
```bash
ffmpeg -i <file> -ss 60 -t 30 -vf mpdecimate -an -f null -v info -
```

**Sortie stderr** : 1 ligne par frame décimée :
```
[Parsed_mpdecimate_0 @ 0x...] drop pts:90090 pts_time:1.001 drop_count:1
[Parsed_mpdecimate_0 @ 0x...] keep pts:93093 pts_time:1.035 drop_count:-1
```

**Règle** :
- Compter `drop` et `keep` → ratio `drop / (drop + keep)`
- Film moderne 24p : ratio très faible (< 5%)
- Télécinéma 3:2 pulldown : ratio ~20% (1 frame sur 5 est dupliquée)
- Conversion 30p→60p mal faite : ratio proche 50%

**Seuils** :

| Ratio décimation | Verdict |
|---|---|
| < 0.05 | `judder_none` (normal) |
| 0.05-0.15 | `judder_light` (rare, à vérifier) |
| 0.15-0.25 | `pulldown_3_2_suspect` (télécinéma probable) |
| > 0.25 | `judder_heavy` (conversion framerate problématique) |

**Coût** : ~3-5 s pour 30 s.

**Note** : ce filtre est **moins utile** pour les films modernes (tous 24p natifs). Surtout pertinent pour :
- Rips DVD NTSC (telecine 3:2 préservé)
- Vieux fichiers broadcast TV

**Décision** : implémenter §8.3 mais en le gardant **opt-in** (setting `perceptual_judder_detection_enabled`, défaut `False`) car cas rares.

---

#### 8.4 IMAX detection (ajout post-review utilisateur)

**Pourquoi c'est important** : l'IMAX est un format **de prestige** avec des caractéristiques techniques distinctes. Détecter un fichier IMAX Enhanced change fondamentalement le jugement qualité dans la comparaison de doublons.

**3 types d'IMAX à détecter** :

| Type IMAX | Aspect ratio | Caractéristique |
|---|---|---|
| **IMAX Film (70mm natif)** | 1.43:1 | Très rare, projection IMAX uniquement |
| **IMAX Digital** | 1.90:1 | Cinéma IMAX Digital (GT/Laser) |
| **IMAX Enhanced / Expansion** | Variable (2.39:1 ↔ 1.43:1 ou 1.90:1) | Scènes IMAX intégrées dans un film 2.39:1 (Dark Knight, Interstellar, Dune, Oppenheimer, Mission Impossible 7/8) |

**Détection**

##### Méthode 1 — Aspect ratio du container (rapide)
```python
def detect_imax_by_container_ar(width: int, height: int) -> str:
    ar = width / height if height > 0 else 0
    if 1.40 <= ar <= 1.46:
        return "imax_full_frame"      # 1.43:1 IMAX 70mm natif
    if 1.88 <= ar <= 1.92:
        return "imax_digital"          # 1.90:1 IMAX Digital
    return "unknown"
```

##### Méthode 2 — Variabilité de cropdetect (IMAX Expansion)
Les films avec scènes IMAX alternent l'aspect ratio entre scènes. On peut :
1. Lancer `cropdetect` sur **3 segments** (début, milieu, fin).
2. Comparer les aspect ratio détectés.
3. Si `max(ar) - min(ar) > 0.3` → **IMAX Expansion confirmé**.

**Exemple Oppenheimer (2023)** :
- Segment 1 (scène émotionnelle) : crop 1920×800 → ar = 2.40 (standard letterbox 2.39)
- Segment 2 (scène IMAX) : crop 1920×1080 → ar = 1.78 (pleine hauteur container)
- Différence : 0.62 → flag `imax_expansion_detected`

##### Méthode 3 — Résolution native très élevée (indice)
IMAX natif scanné en 6K ou 8K. Les rares fichiers 6K+ (> 4320p) sont presque certainement IMAX.
```python
if height > 2600:     # au-dessus de 4K standard 2160p
    flag_imax_native_resolution = True
```

##### Méthode 4 — Cross-check tmdb.keywords (compl.)
TMDb a parfois `"imax"` dans les keywords du film → confirmation.

**Stratégie combinée** :

```python
def classify_imax(probe, cropdetect_segments, tmdb_keywords) -> dict:
    container_ar = probe.width / probe.height if probe.height > 0 else 0
    
    # Priorité 1 : expansion détectée via crops variables
    if len(cropdetect_segments) >= 2:
        ars = [s["aspect_ratio"] for s in cropdetect_segments]
        if max(ars) - min(ars) > 0.3:
            return {"imax_type": "expansion", "confidence": 0.90}
    
    # Priorité 2 : aspect ratio container 1.43 ou 1.90
    if 1.40 <= container_ar <= 1.46:
        return {"imax_type": "full_frame_143", "confidence": 0.85}
    if 1.88 <= container_ar <= 1.92:
        return {"imax_type": "digital_190", "confidence": 0.75}
    
    # Priorité 3 : résolution anormalement élevée
    if probe.height > 2600:
        return {"imax_type": "native_high_resolution", "confidence": 0.70}
    
    # Cross-check tmdb comme boost de confidence
    if any("imax" in kw.lower() for kw in (tmdb_keywords or [])):
        return {"imax_type": "tmdb_keyword", "confidence": 0.60}
    
    return {"imax_type": "none", "confidence": 1.0}
```

**Impact sur la comparaison** :

Dans la modale deep-compare, si A est IMAX Expansion et B est standard 2.39:1 → **A gagne +20 points** sur le critère "format de prestige" car :
- Image 2x plus grande dans les scènes IMAX (1.78 vs 2.39)
- Préservé des versions home cinema premium
- Rare (UHD Blu-ray Disney/WB/Paramount spécifiques)

**UI dédiée** :
- Badge `[IMAX Enhanced]` violet dans la modale A/B
- Info contextuelle : "Version IMAX avec 25% de l'image en plein écran (format 1.90:1)"

**Cas limites IMAX** :

1. **Film avec aspect variable non-IMAX** (certains films d'auteur utilisent aussi des changements d'aspect) : méthode 2 faux positif. Mitigation : cross-check tmdb keywords.
2. **Rip "letterboxed" d'un IMAX** : l'aspect expansion est perdu (tout letterboxed en 2.39:1) → ne détecte plus qu'IMAX. Normal, le fichier n'est plus IMAX Enhanced.
3. **Version OpenMatte** (18:9 ou 16:9 plein écran, sans respecter 2.39) : ar container ~1.78 → peut matcher IMAX Digital 1.90 par erreur. Tolérance 1.88-1.92 stricte évite ça.
4. **IMAX 15/70 scan cinéma** (>8K) : très rare en home cinema, mais possible (sources archives). Flag `imax_native_high_resolution`.

**Seuils validés additionnels :**

```python
# constants.py ajouts
IMAX_AR_FULL_FRAME_MIN = 1.40
IMAX_AR_FULL_FRAME_MAX = 1.46
IMAX_AR_DIGITAL_MIN = 1.88
IMAX_AR_DIGITAL_MAX = 1.92
IMAX_EXPANSION_AR_DELTA = 0.3        # différence min entre segments pour détecter expansion
IMAX_NATIVE_RESOLUTION_MIN_HEIGHT = 2600
IMAX_EXPANSION_SEGMENTS_COUNT = 3    # nb de segments cropdetect pour détecter expansion
```

**Films IMAX Enhanced notables (corpus de référence)** :
- **The Dark Knight** (2008) — Nolan, premier IMAX Expansion majeur
- **The Dark Knight Rises** (2012) — expansion étendue
- **Interstellar** (2014) — ~1 heure de IMAX
- **Dunkirk** (2017) — 75% en IMAX
- **Mission Impossible - Fallout** (2018)
- **Avengers: Infinity War / Endgame** (2018-19) — full IMAX 1.90:1
- **Tenet** (2020), **Oppenheimer** (2023) — Nolan
- **Dune** (2021), **Dune: Part Two** (2024) — Villeneuve
- **Top Gun: Maverick** (2022)
- **Mission Impossible - Dead Reckoning** (2023)

**Références complémentaires IMAX** :

- [IMAX Enhanced explained (Digital Trends)](https://www.digitaltrends.com/home-theater/what-is-imax-enhanced/)
- [Reddit r/4kbluray — IMAX Expansion list](https://www.reddit.com/r/4kbluray/)
- [AVS Forum — IMAX 1.90 vs 1.43](https://www.avsforum.com/)

---

#### 8.5 Implémentation groupée

Ces 3 analyses partagent :
- Même technique (ffmpeg filter + parse stderr)
- Même coût (~5-10 s chacun)
- Même intégration (après extraction frames, parallèle via §1)

**Option optimisation** : les 3 peuvent s'exécuter dans **3 sub-threads parallèles** via le ThreadPool §1 → coût total **~10 s** au lieu de **~25 s séquentiel**.

**Option alternative** : combiner en 1 seule commande ffmpeg avec `-filter_complex` séparant les streams pour chaque analyse. Plus complexe à parser, **pas recommandé**.

**Décision** : 3 fonctions indépendantes, parallélisées via §1.

**Décision finale :**

1. **Stack** : ffmpeg natif (idet + cropdetect + mpdecimate).
2. **Module** : `cinesort/domain/perceptual/metadata_analysis.py` (nouveau module, regroupe §5 + §6 + §7 + §8).
3. **Segments analysés** :
   - idet : 30 s au début (`-ss 30 -t 30`)
   - cropdetect : 60 s au milieu (`-ss 120 -t 60`)
   - mpdecimate : 30 s au milieu (`-ss 60 -t 30`)
4. **Parallélisation** : via §1 ThreadPool.
5. **Settings** :
   - `perceptual_interlacing_detection_enabled` (défaut `True`, utile pour DVD rips)
   - `perceptual_crop_detection_enabled` (défaut `True`)
   - `perceptual_judder_detection_enabled` (défaut `False`, car rare)
6. **Stockage** : 6 champs dans `VideoPerceptual` :
   - `interlaced_detected: bool`
   - `interlace_type: str` (`"progressive" | "tff" | "bff" | "mixed"`)
   - `crop_detected: str` (`"full_frame" | "letterbox_2_35" | "letterbox_2_39" | "pillarbox" | ...`)
   - `detected_aspect_ratio: float`
   - `judder_ratio: float`
   - `judder_verdict: str`

**Seuils validés :**

```python
# constants.py ajouts
IDET_SEGMENT_DURATION_S = 30
IDET_INTERLACE_RATIO_THRESHOLD = 0.3       # (tff+bff)/(tff+bff+prog) > 0.3 = interlaced
CROPDETECT_SEGMENT_DURATION_S = 60
CROPDETECT_LIMIT = 24                       # luminance seuil
CROPDETECT_ROUND = 16
MPDECIMATE_SEGMENT_DURATION_S = 30
MPDECIMATE_JUDDER_LIGHT = 0.05
MPDECIMATE_JUDDER_PULLDOWN = 0.15
MPDECIMATE_JUDDER_HEAVY = 0.25
```

**Cas limites identifiés :**

1. **idet sur animation** : résultats peuvent être bruyants sur aplats → confidence réduite si `tmdb.is_animation`.
2. **cropdetect sur scène uniforme noire** : crop détecté = 0×0 → skip, réessayer sur autre segment.
3. **cropdetect fluctuant** (film avec plan IMAX format change) : garder la plus grande dimension détectée.
4. **mpdecimate pour film action** : coupes rapides peuvent être confondues avec pulldown → analyse segment plus long (60 s) pour lisser.
5. **ffmpeg error sur un filtre** : skip ce filtre, continuer avec les autres.

**Références :**

- [FFmpeg Filters Documentation](https://ffmpeg.org/ffmpeg-filters.html)
- [idet filter doc](http://underpop.online.fr/f/ffmpeg/help/idet.htm.gz)
- [cropdetect FFmpeg 8.0 doc](https://ayosec.github.io/ffmpeg-filters-docs/8.0/Filters/Video/cropdetect.html)
- [aktau.be — Detecting interlaced video with ffmpeg](http://www.aktau.be/2013/09/22/detecting-interlaced-video-with-ffmpeg/)
- [ffmpeg detect interlacing gist](https://gist.github.com/aktau/6660848)
- [VideoHelp Forum — interpret idet output](https://forum.videohelp.com/threads/418172-How-to-interpret-ffmpeg-idet-information-to-decide-if-vide-is-interlaced)

---

## Vague 4 — Cœur expert

### §15 — Grain intelligence avancée ✅ (section phare v7.5.0)

**Date :** 2026-04-23

**Findings :**

#### État actuel CineSort (rappel rapide)

Le module [grain_analysis.py](../../../cinesort/domain/perceptual/grain_analysis.py) fait déjà **l'essentiel** :
- 3 bandes d'ère (classic_film < 2002, transition 2002-2012, digital ≥ 2012)
- Estimation grain via variance des blocs plats (16×16 px)
- Détection grain artificiel (uniformité > 0.9 → suspect post-production)
- Détection DNR extrême (grain ≈ 0 + blur > 0.04)
- Contextualisation TMDb : skip animation, pondération budget/studio

**Ce que la v7.5.0 va ajouter** — 5 améliorations structurelles qui positionnent CineSort au niveau des outils pro :

1. **Classification d'ère en 6 bandes** (plus précise)
2. **Lecture directe AV1 Film Grain Synthesis metadata** (game-changer si AV1)
3. **Signature grain attendue par contexte** (base de connaissances)
4. **Discrimination grain sain vs bruit d'encodage** (FFT temporelle + autocorrélation)
5. **Détection DNR partiel** (texture loss ratio)
6. **Verdict "Contexte historique" UI**

---

#### 15.1 Classification d'ère en 6 bandes

**Rationale** : les 3 bandes actuelles sont trop grossières. Un film 1970 (ISO élevés, 16mm fréquent) a des attendus très différents d'un film 2000 (35mm moderne, scans Kodak DLT).

**Découvertes recherche** ([Kodak tech data](https://www.kodak.com/en/motion/product/camera-films/500t-5219-7219/), [Advanced Film Grain analysis paper](https://mcl.usc.edu/wp-content/uploads/2014/01/200912-Advanced-Film-grain-noise-analysis-and-synthesis-for-high-definition-video-coding.pdf)) :

| Bande | Années | Caractéristique grain | ISO typique |
|---|---|---|---|
| **`16mm_era`** | < 1980 | Grain très prononcé, structure grossière | ISO 200-400 |
| **`35mm_classic`** | 1980-1998 | Grain standard pellicule, stock pré-Vision | ISO 100-500 |
| **`late_film`** | 1999-2005 | Fin pellicule, Kodak Vision premiers stocks, scans HQ | ISO 50-800 |
| **`transition`** | 2006-2012 | Mixte (Red One, Alexa v1, pellicule finale) | Variable |
| **`digital_modern`** | 2013-2020 | Capteurs Alexa propre, Sony, pas de grain natif | Digital |
| **`digital_hdr_era`** | ≥ 2021 | Capteurs HDR, signature distincte (low noise floor) | Digital |

**Formules de classification** (année → bande) :

```python
def classify_film_era_v2(year: int) -> str:
    if year <= 0: return "unknown"
    if year < 1980: return "16mm_era"
    if year < 1999: return "35mm_classic"
    if year < 2006: return "late_film"
    if year < 2013: return "transition"
    if year < 2021: return "digital_modern"
    return "digital_hdr_era"
```

**Attendus statistiques par bande** (à calibrer sur corpus 30 films) :

```python
GRAIN_PROFILE_BY_ERA_V2 = {
    "16mm_era":      {"level_mean": 4.5, "level_tolerance": 1.5, "uniformity_max": 0.75},
    "35mm_classic":  {"level_mean": 3.0, "level_tolerance": 1.0, "uniformity_max": 0.80},
    "late_film":     {"level_mean": 2.0, "level_tolerance": 0.8, "uniformity_max": 0.82},
    "transition":    {"level_mean": 1.5, "level_tolerance": 1.0, "uniformity_max": 0.85},
    "digital_modern":{"level_mean": 0.5, "level_tolerance": 0.5, "uniformity_max": 0.90},
    "digital_hdr_era":{"level_mean": 0.3, "level_tolerance": 0.3, "uniformity_max": 0.92},
}
```

---

#### 15.2 AV1 Film Grain Synthesis metadata — DÉCOUVERTE MAJEURE

**C'est un game-changer** découvert pendant la recherche : les fichiers AV1 peuvent transporter des **métadonnées de grain synthétique** (AOMedia Film Grain Synthesis, AFGS1 — [spec officielle](https://aomediacodec.github.io/afgs1-spec/)).

**Principe AV1 film grain** :
- L'encodeur détecte le grain de la source.
- Il le **supprime** avant compression (le grain compresse mal).
- Il injecte les **paramètres du grain** dans le bitstream (`apply_grain`, `grain_seed`, `ar_coeffs`, `scaling_values`).
- Le décodeur **re-synthétise** le grain au décodage, visuellement identique à l'original.

**Exploitable pour CineSort** :
- Si un fichier AV1 a AFGS1 → on **sait** que le grain était préservé à l'encodage (pas de DNR agressif).
- Les paramètres AR (coefficients auto-régressifs) et scaling values donnent une **signature numérique directe** du grain.
- **Pas besoin d'analyser les pixels** pour ces fichiers — la metadata dit tout.

**Détection** :

```python
def extract_av1_film_grain_params(ffprobe_path, media_path) -> dict | None:
    """Extrait les paramètres film grain d'un fichier AV1 via ffprobe.

    Commande :
      ffprobe -select_streams v -show_entries "stream=codec_name,profile,
        side_data_list" -print_format json <file>

    Cherche :
      - codec_name == "av1"
      - side_data_type "AV1 Film Grain Parameters" ou similaire
      - T.35 metadata avec country=0xB5 + provider=0x5890 (AOMedia)
    """
```

**Note** : ffmpeg actuel (≥ 6.0) expose les metadata T.35 dans `side_data_list`. Pour ffmpeg < 6.0, fallback sur `grav1synth` ([rust-av/grav1synth](https://github.com/rust-av/grav1synth)) en binary externe (non embarqué en v7.5.0).

**Décision** : détection best-effort via ffprobe. Si présent → boost confiance verdict grain. Si absent → fallback analyse pixel classique.

**Impact sur le scoring** :
- Fichier AV1 avec AFGS1 préservé → bonus **+15 pts** sur le score visuel (garantie encodage respectueux du master).
- Fichier AV1 sans AFGS1 mais grain détecté → comportement normal.
- Fichier AV1 sans AFGS1 ET sans grain détecté → pas pénalisé (peut-être source déjà propre).

---

#### 15.3 Signature grain attendue par contexte

**Principe** : construire une **base de connaissances interne** des signatures grain attendues selon (ère, genre, budget, studio, pays). Un écart significatif de la mesure réelle → flag.

**Exemples concrets** :

| Contexte | Signature grain attendue |
|---|---|
| (`16mm_era`, horror, low_budget, Hammer Films, UK) | Grain élevé (4-5), très variable, uniformité < 0.7 |
| (`35mm_classic`, drama, medium_budget, A24, US) | Grain modéré (2.5-3.5), uniforme naturel 0.72-0.78 |
| (`late_film`, sci-fi, high_budget, Warner Bros, US) | Grain fin Kodak Vision (1.8-2.2), uniformité 0.80 |
| (`digital_modern`, animation, high_budget, Disney, US) | Aucun grain (0-0.3), uniformité 0.95+ |
| (`digital_hdr_era`, action, high_budget, Marvel, US) | Quasi propre (0.2-0.4), uniformité 0.92+ |
| (`digital_modern`, drama, low_budget, A24, US) | Grain Kodak 250D ajouté post-prod, signature spécifique |

**Règles de matching** (par ordre de spécificité, plus spécifique l'emporte) :

```python
GRAIN_SIGNATURES_EXCEPTIONS = [
    # Règles très spécifiques
    {"era": "*", "genres": ["animation"], "level_max": 0.5, "label": "animation_aplats"},
    {"era": "16mm_era", "genres": ["horror"], "level_min": 3.5, "label": "16mm_horror_grain"},
    {"era": "digital_modern", "companies": ["A24", "Focus Features"],
     "level_mean": 2.0, "tolerance": 1.0, "label": "a24_filmic_aesthetic"},
    # (10-15 règles construites à partir de la connaissance cinéma)
]

def get_expected_grain_signature(era, genres, budget, companies, country) -> dict:
    # 1. Match exceptions ordonnées
    for rule in GRAIN_SIGNATURES_EXCEPTIONS:
        if _rule_matches(rule, era, genres, budget, companies, country):
            return rule
    # 2. Fallback sur profil par ère
    return GRAIN_PROFILE_BY_ERA_V2[era]
```

**Cas d'écart** :
- Mesure 0.3 mais attendu 3.0 (15mm classic horror) → flag `grain_unexpectedly_low` → DNR suspect.
- Mesure 4.5 mais attendu 0.5 (digital modern Disney) → flag `grain_unexpectedly_high` → bruit numérique ou grain ajouté ?

---

#### 15.4 Grain sain (argentique) vs grain encode (bruit compression)

**Le test crucial qui change tout.** Cette distinction demande une analyse **à la fois spatiale ET temporelle**.

**Différences fondamentales** (confirmées par recherche — [Film grain noise modeling in advanced video coding](https://www.researchgate.net/publication/228666259_Film_grain_noise_modeling_in_advanced_video_coding)) :

| Propriété | Grain argentique | Bruit d'encodage |
|---|---|---|
| **Spatialement** | Gaussien, isotropique, 1/f spectrum | Bloc-aligné (8×8 ou 16×16), DCT pattern |
| **Temporellement** | **Indépendant** (chaque frame différente) | **Corrélé** (pattern répété) |
| **Autocorrélation spatiale** | Décroissance rapide | Pics aux multiples de 8/16 |
| **Cross-color** | Fortement corrélé (R/G/B ensemble) | Peu corrélé (compression séparée) |
| **Intensité** | Dépend du signal | Constant ou dépend du niveau quantization |

**Mesures proposées** :

##### 15.4.1 Autocorrélation temporelle (le plus discriminant)

Principe : comparer la **même zone plate** dans 2 frames consécutives extraites.

```python
def compute_temporal_correlation(frame_a: np.ndarray, frame_b: np.ndarray,
                                  flat_zones: list[tuple]) -> float:
    """Corrélation temporelle du bruit entre 2 frames.

    flat_zones: liste de boîtes (y, x, h, w) — zones plates détectées.
    """
    correlations = []
    for (y, x, h, w) in flat_zones:
        block_a = frame_a[y:y+h, x:x+w].astype(np.float64)
        block_b = frame_b[y:y+h, x:x+w].astype(np.float64)
        # Soustraire la moyenne (on analyse le bruit, pas le signal)
        noise_a = block_a - block_a.mean()
        noise_b = block_b - block_b.mean()
        # Pearson correlation
        num = np.sum(noise_a * noise_b)
        denom = np.sqrt(np.sum(noise_a**2) * np.sum(noise_b**2))
        if denom > 0:
            correlations.append(num / denom)
    return np.mean(correlations) if correlations else 0.0
```

**Interprétation** :
- `temporal_corr < 0.2` → **grain argentique confirmé** (aléatoire chaque frame)
- `temporal_corr > 0.7` → **bruit d'encodage** (pattern répété)
- Entre 0.2-0.7 → ambigu (mix, ou film avec grain ajouté post-prod numérique)

##### 15.4.2 Autocorrélation spatiale multi-directions

Selon [Rapid and Reliable Detection of Film Grain Noise](https://ieeexplore.ieee.org/document/4106554/), le grain authentique a une autocorrélation qui **décroît vite** dans toutes les directions. Un bruit d'encodage bloc-aligné a des **pics** aux multiples de 8 ou 16 pixels.

```python
def spatial_autocorr_8directions(block: np.ndarray) -> dict:
    """Autocorrélation dans 8 directions à lag 1, 8, 16.

    Returns:
        {"lag1_iso": float,          # isotropie lag 1 (attendu ~uniforme pour grain)
         "lag8_peaks": float,        # élévation au lag 8 (suspect = encode bloc 8x8)
         "lag16_peaks": float,       # élévation au lag 16 (suspect = encode bloc 16x16)
         "verdict": str}
    """
```

**Règle** :
- `lag8_peaks > 1.3 * lag1_iso` → bruit DCT 8×8 (H.264, MPEG-2) probable.
- `lag16_peaks > 1.3 * lag1_iso` → bruit HEVC (transform 16×16 ou 32×32).
- `lag1_iso` élevé et homogène → grain argentique.

##### 15.4.3 Cross-color correlation

Le grain argentique est **fortement corrélé** entre R/G/B (la lumière traverse les couches sensibles ensemble). Le bruit d'encodage est souvent **faiblement corrélé** car les canaux sont compressés séparément (YUV420).

```python
def cross_color_correlation(frame_rgb: np.ndarray, flat_zones) -> float:
    """Corrélation moyenne R-G, G-B, R-B sur zones plates."""
    # ... Pearson 3 paires, retourne la moyenne
```

**Règle** :
- `cross_corr > 0.6` → grain argentique.
- `cross_corr < 0.3` → bruit compression.

##### 15.4.4 Verdict composite grain nature

```python
def classify_grain_nature(frames: list[np.ndarray], flat_zones) -> dict:
    """Classifie la nature du bruit détecté.

    Combinaison :
        - temporal_corr (poids 50%) — le plus discriminant
        - spatial_autocorr lag8/16 (poids 30%)
        - cross_color_corr (poids 20%, si RGB disponible)

    Verdicts :
        "film_grain"     : grain argentique authentique
        "encode_noise"   : bruit de compression
        "post_added"     : grain ajouté numériquement en post-prod (pattern spécifique)
        "ambiguous"      : incertain
    """
```

---

#### 15.5 Détection DNR partiel (texture loss ratio)

**Gap actuel** : le code existant détecte uniquement le DNR **extrême** (grain ≈ 0 + blur > 0.04). Un DNR **modéré** préserve un peu de grain mais **lisse les textures fines** (peau, tissus, feuillage) → perte qualité réelle non détectée.

**Principe** : mesurer la **variance des textures** (zones non-plates, intermédiaires) et comparer à un baseline attendu par ère.

```python
def detect_partial_dnr(
    frames: list[np.ndarray],
    grain_result: GrainAnalysis,
    video_result: VideoPerceptual,
    era_profile: dict,
) -> dict:
    """Détecte le DNR partiel via ratio texture_actual / texture_baseline.

    Méthode :
        1. Identifier zones non-plates (10 < variance < 500 → textures)
        2. Calculer variance moyenne dans ces zones.
        3. Comparer à baseline par ère (measurement empirique).
        4. Si ratio < 0.7 → DNR partiel suspect.

    Returns:
        {"texture_loss_ratio": float,  # 0.0-1.0
         "is_partial_dnr": bool,
         "detail": str}  # texte FR explicatif
    """
    # Zones textures (pas uniformes, pas de détails forts)
    texture_variances = []
    for frame in frames:
        for block in _iter_blocks(frame, block_size=16):
            var = np.var(block)
            if 10 < var < 500:  # ni plat, ni ultra-détaillé
                texture_variances.append(var)

    if not texture_variances:
        return {"texture_loss_ratio": 0.0, "is_partial_dnr": False, "detail": "N/A"}

    texture_actual = np.median(texture_variances)
    texture_baseline = era_profile.get("texture_variance_baseline", 150.0)

    ratio = texture_actual / texture_baseline
    is_dnr = (ratio < 0.7 and grain_result.grain_level < 1.5)

    return {
        "texture_loss_ratio": round(ratio, 2),
        "is_partial_dnr": is_dnr,
        "detail": (
            f"Texture variance {texture_actual:.0f} vs baseline {texture_baseline:.0f} "
            f"(ratio {ratio:.2f}) — {'DNR partiel suspect' if is_dnr else 'texture préservée'}"
        ),
    }
```

**Baseline par ère** (à ajouter dans `GRAIN_PROFILE_BY_ERA_V2`) :

```python
{
    "16mm_era": {..., "texture_variance_baseline": 250.0},
    "35mm_classic": {..., "texture_variance_baseline": 180.0},
    "late_film": {..., "texture_variance_baseline": 150.0},
    "transition": {..., "texture_variance_baseline": 130.0},
    "digital_modern": {..., "texture_variance_baseline": 120.0},
    "digital_hdr_era": {..., "texture_variance_baseline": 140.0},  # HDR = plus de détails shadow
}
```

---

#### 15.6 Verdict "Contexte historique" — UI dédiée

**Gap actuel** : les verdicts existants sont corrects mais arides (`grain_naturel_preserve`, `dnr_suspect`). L'utilisateur non-technique n'a pas de **contextualisation pédagogique**.

**Nouveau verdict enrichi** : section dédiée dans la modale deep-compare.

**Format** :

```
┌─ Contexte historique du film ───────────────────────────────┐
│                                                               │
│ Blade Runner (1982)                                          │
│ Ère : 35mm classic (années 1980)                             │
│ Budget : 28 M$ / Studio : Warner Bros.                       │
│                                                               │
│ Attendu : grain prononcé (niveau 3.0 ± 1.0),                 │
│ variation naturelle (uniformité < 0.80),                     │
│ cross-color correlation élevée.                              │
│                                                               │
│ ─── Fichier A ────────────  ─── Fichier B ────────────       │
│ Grain : 3.2 ✓                Grain : 0.4 ⚠                    │
│ Uniformité : 0.73 ✓          Uniformité : 0.94 ⚠              │
│ Temporal corr : 0.15 ✓       Temporal corr : 0.12 ✓           │
│ Texture ratio : 0.95 ✓       Texture ratio : 0.52 ⚠           │
│                                                               │
│ Verdict A : grain authentique préservé, respect du master.   │
│ Verdict B : DNR agressif, perte textures fines (~48 %).      │
│                                                               │
│ Recommandation : Fichier A est le meilleur master.           │
│ Le fichier B a subi un traitement Blu-ray commercial         │
│ courant dans les années 2007-2010 ("waxy skin look").        │
└─────────────────────────────────────────────────────────────┘
```

**Génération** : fonction `build_grain_historical_context(grain_a, grain_b, era, budget, studio)` qui construit ce bloc de texte FR avec les mesures comparatives + interprétation humaine.

---

**Benchmarks attendus (corpus à constituer) :**

Corpus `tests/fixtures/grain_intelligence/` avec 30 films étiquetés :

| Film | Ère | Grain attendu | Grain mesuré (UHD master) | Verdict |
|---|---|---|---|---|
| Blade Runner (1982) UHD | 35mm_classic | 3.0 ± 1.0 | 3.2 | `grain_authentique` |
| Blade Runner (1982) Blu-ray 2007 | 35mm_classic | 3.0 | 0.4 | `dnr_aggressive` |
| The Shining (1980) UHD | 35mm_classic | 3.5 | 3.7 | `grain_authentique` |
| Oppenheimer (2023) IMAX UHD | digital_hdr_era | 0.3 | 1.8 | `grain_added_post` (grain intentionnel Nolan) |
| Soul (Pixar 2020) 4K | digital_modern / animation | 0.0 | 0.1 | `animation_skip` |
| Mad Max Fury Road (2015) UHD | digital_modern | 0.5 | 0.3 | `propre_natif` |
| 2001 A Space Odyssey (1968) 70mm UHD | 16mm_era* | 4.5 | 2.5 | `grain_reduced_70mm` (70mm = moins grain) |
| The Grand Budapest Hotel (2014) | digital_modern | 0.5 | 1.8 | `grain_added_post` (35mm cible artistique) |

*Note : 70mm (Imax/Cinerama) a **moins** de grain que 35mm → il faudra ajouter une bande `70mm_era_large_format` pour gérer ces exceptions.

---

**Décision finale :**

1. **Classification d'ère** : passer à 6 bandes + gérer exception 70mm large format via `film_format` kwarg optionnel (dérivé résolution ou tmdb.production_notes).
2. **AV1 Film Grain metadata** : détection best-effort via ffprobe, bonus +15 pts si présent.
3. **Signatures contextuelles** : 15 règles exceptions + fallback par ère.
4. **Grain sain vs encode** : 3 métriques (temporal_corr principal, spatial_autocorr 8-lag, cross_color_corr) pondérées.
5. **DNR partiel** : texture_loss_ratio avec baseline par ère.
6. **Contexte historique UI** : bloc FR généré dynamiquement.
7. **Stockage** : 14 nouveaux champs dans `GrainAnalysis`.
8. **Setting** : `perceptual_grain_intelligence_enabled` (défaut `True`).

**Seuils validés :**

```python
# constants.py ajouts
# Ère granulaire
GRAIN_ERA_V2 = {
    "16mm_era": 1980, "35mm_classic": 1999, "late_film": 2006,
    "transition": 2013, "digital_modern": 2021, "digital_hdr_era": 9999,
}

# Profils attendus par ère (level_mean, level_tolerance, uniformity_max, texture_baseline)
GRAIN_PROFILE_BY_ERA_V2 = { ... }   # voir 15.1

# Discrimination temporal/spatial
GRAIN_TEMPORAL_CORR_AUTHENTIC = 0.2
GRAIN_TEMPORAL_CORR_ENCODE = 0.7
GRAIN_SPATIAL_LAG_PEAK_RATIO = 1.3   # seuil pics lag8/lag16 vs lag1
GRAIN_CROSS_COLOR_CORR_AUTHENTIC = 0.6

# DNR partiel
DNR_PARTIAL_TEXTURE_RATIO = 0.7

# Bonus AV1 AFGS1
GRAIN_AV1_AFGS1_BONUS = 15           # points visuel si metadata présente
```

**Cas limites identifiés :**

1. **70mm Imax/Cinerama** (2001, Lawrence of Arabia) : grain plus fin que 35mm attendu. Exception via `film_format="70mm"` (à deriver si tmdb.runtime_minutes > 150 et année < 2000 ? ou marqueur manuel).
2. **Film post-2020 à grain intentionnel** (Nolan Oppenheimer) : mesure haute, attendu bas → verdict `grain_added_post`, pas pénalisant.
3. **Animation** : déjà géré par l'actuel (skip via tmdb.genres).
4. **Film noir & blanc** : cross_color_corr non applicable → poids 0 sur cette métrique, pondérer les autres 50/50.
5. **Film 2K DI remasterisé 4K** : textures lisses par nature (DI intermediate smoothing) → ratio texture peut faussement indiquer DNR. Flag `ambiguous_2k_di` si cross-check avec métadonnées DI disponible.
6. **AV1 avec AFGS1 mais bit rate très bas** : grain synthétique mal re-créé → fallback sur analyse pixel classique.
7. **ffprobe ne parse pas T.35** (versions < 5.0) : détection AFGS1 échoue silencieusement, pas bloquant.
8. **Utilisation sur film court (trailer, bonus)** : < 90 s → skip analyse temporelle (pas assez de frames), fallback grain level seul.

**Références :**

- [AOMedia Film Grain Synthesis 1 (AFGS1) spec officielle](https://aomediacodec.github.io/afgs1-spec/)
- [Technical report on AOMedia film grain synthesis](https://aomedia.org/docs/CWG-C051o_TR_AOMedia_film_grain_synthesis_technology_v2.pdf)
- [Andrey Norkin — Film Grain Synthesis in AV1 (DCC 2018)](https://norkin.org/pdf/DCC_2018_AV1_film_grain.pdf)
- [Visionular — Beauty Of Film Grain: Encoding](https://visionular.ai/how_to_retain_film_grain_when_encoding_video/)
- [Film grain noise modeling in advanced video coding (ResearchGate)](https://www.researchgate.net/publication/228666259_Film_grain_noise_modeling_in_advanced_video_coding)
- [Rapid and Reliable Detection of Film Grain Noise (IEEE 2007)](https://ieeexplore.ieee.org/document/4106554/)
- [Advanced Film Grain Noise Extraction and Synthesis (USC)](https://mcl.usc.edu/wp-content/uploads/2014/01/200912-Advanced-Film-grain-noise-analysis-and-synthesis-for-high-definition-video-coding.pdf)
- [Kodak VISION3 500T 5219 Tech Data](https://www.kodak.com/content/products-brochures/Film/VISION3_5219_7219_Technical-data.pdf)
- [In Depth Cine — The Last Colour Negative Film (Kodak Vision 3)](https://www.indepthcine.com/videos/kodak-vision-3)
- [Cinedrome — DNR on DVD: Background and Examples](https://www.cinedrome.ch/hometheater/dvd/dnr/)
- [ryesofthegeek — Remastering Film, the perils of DNR](https://ryesofthegeek.wordpress.com/2012/11/06/remastering-film-the-perils-of-dnr/)
- [rust-av/grav1synth (GitHub)](https://github.com/rust-av/grav1synth)
- Code CineSort : [grain_analysis.py](../../../cinesort/domain/perceptual/grain_analysis.py), [constants.py](../../../cinesort/domain/perceptual/constants.py)

---

### §12 — Mel spectrogram ✅

**Date :** 2026-04-23

**Findings :**

#### Principe de l'échelle Mel

L'échelle Mel est une **échelle perceptuelle** de hauteur tonale qui mimique la sensibilité fréquentielle de l'oreille humaine. Contrairement à l'échelle linéaire Hz :
- 100 Hz → 150 Hz = différence perçue **forte**
- 10000 Hz → 10050 Hz = différence perçue **faible**

Formule standard (Slaney 1998) : `mel = 2595 * log10(1 + hz/700)`

**Pourquoi l'utiliser ?** Sur un spectrogramme linéaire, les artefacts de compression dans les hautes fréquences sont **comprimés visuellement** et difficiles à analyser. Sur un Mel spectrogramme, ils sont **étirés** → détection plus précise.

#### Complémentarité avec §9 Spectral cutoff

| Aspect | §9 Spectral cutoff | §12 Mel spectrogram |
|---|---|---|
| Objectif | Trouver la fréquence max (lossy ou lossless) | Analyser la **forme** du spectre |
| Détection | Cutoff brutal MP3/AAC | Soft clipping, holes de compression, shelf MP3 |
| Granularité | 1 valeur (Hz) | N bandes Mel (ex: 64) |
| Coût | Léger (~50ms FFT) | Modéré (~200ms Mel filter bank) |

**Les deux sont complémentaires** : §9 dit "est-ce lossy ?", §12 dit "quel type d'artefact ?".

#### 4 analyses dérivées du Mel spectrogram

##### 12.1 Soft clipping detection (au-delà du simple peak)

**Gap actuel** : le clipping est détecté par CineSort via peak level > -0.1 dBFS (hard clipping). Un **soft clipping** (saturation progressive) n'atteint jamais -0.1 dBFS mais introduit des harmoniques parasites visibles dans le Mel spectrogramme.

**Détection** : chercher des **harmoniques régulières** dans les HF (2×f, 3×f, 4×f du fondamental). Signature typique : quand une voix/instrument clippe, on voit apparaître des pics à intervalles réguliers.

```python
def detect_soft_clipping_mel(mel_spec_db: np.ndarray, mel_freqs: np.ndarray) -> dict:
    """Détection soft clipping via harmoniques régulières.

    Algorithme :
        1. Identifier pics locaux dans chaque frame Mel.
        2. Pour les pics < 6000 Hz (fondamental probable), chercher harmoniques à 2f, 3f, 4f.
        3. Ratio frames avec harmoniques détectées / total.
        4. Si > 15% → soft clipping probable.
    """
```

**Seuils** :
- < 5% : normal
- 5-15% : harmoniques naturelles (musique, voix nette)
- > 15% : **soft clipping suspect**
- > 30% : clipping probable, mix déficient

##### 12.2 Détection MP3 signature shelf

Recherche confirmée : **MP3 applique un "shelf" à 16 kHz** (réduction progressive des fréquences au-dessus) **indépendamment** du bitrate. Cette signature est visible dans le Mel spectrogramme comme une **chute brutale** sur les bandes Mel correspondant à > 16 kHz.

```python
def detect_mp3_shelf(mel_spec_db: np.ndarray, mel_freqs: np.ndarray) -> dict:
    """Détecte la signature shelf MP3.

    Mesure :
        - puissance moyenne bandes 14-16 kHz (P_avant_shelf)
        - puissance moyenne bandes 16-18 kHz (P_apres_shelf)
        - drop = P_avant - P_apres (en dB)

    Si drop > 20 dB sur au moins 70% des frames → MP3 signature confirmée.
    """
```

**Intérêt** : permet de distinguer **MP3** de **AAC/Opus** même à bitrate comparable. MP3 a cette shelf, AAC roll-off plus progressif, Opus coupe encore plus progressivement.

##### 12.3 Détection "holes" AAC

Les encodeurs AAC bas bitrate utilisent **Perceptual Noise Substitution (PNS)** et **Spectral Band Replication (SBR)** pour gagner en bitrate. Résultat : des **"trous" spectraux** (bandes entières à -infinity dB) et/ou des bandes **synthétiques** (trop régulières, variance très faible).

```python
def detect_aac_holes(mel_spec_db: np.ndarray, mel_freqs: np.ndarray) -> dict:
    """Détecte les trous spectraux signature AAC/Opus bas bitrate.

    Mesure :
        - Ratio bandes Mel avec puissance < -80 dB (holes)
        - Variance temporelle par bande (bandes synthétiques = variance faible)

    Verdict :
        - hole_ratio > 10% ET variance_synthetic > 5% → AAC bas bitrate
        - hole_ratio > 5% seulement → AAC standard
    """
```

##### 12.4 Spectral flatness (indicateur général)

Mesure de **"blancheur"** du spectre. 1.0 = bruit blanc parfait. 0 = ton pur.

Formule : `flatness = geometric_mean(power) / arithmetic_mean(power)`

**Utilisation** :
- Audio compressé agressivement → flatness **basse** sur certaines bandes (trous).
- Audio non compressé / musique dynamique → flatness **élevée** et stable.
- Outil **secondaire** pour confirmer les autres analyses.

#### Implémentation pure numpy — choix confirmé

**Décision §9 était "numpy pur"**. Pour cohérence, §12 pareil. Environ **120 lignes** de code DSP pour :
1. STFT (Short-Time Fourier Transform) → déjà dans §9.
2. Filter bank Mel triangulaire → 30 lignes supplémentaires.
3. Conversion en dB → 5 lignes.
4. 4 analyses dérivées → 50 lignes.

**Pas de scipy requis**. Tim Sainburg a un [tutorial de référence](https://timsainburg.com/python-mel-compression-inversion.html) qui montre comment faire en < 100 lignes numpy.

#### Formule filter bank Mel triangulaire

```python
def mel_filter_bank(
    n_filters: int = 64,
    sample_rate: int = 48000,
    n_fft: int = 4096,
    fmin: float = 0.0,
    fmax: Optional[float] = None,
) -> np.ndarray:
    """Construit un filter bank Mel triangulaire.

    Returns:
        np.ndarray de shape (n_filters, n_fft//2 + 1).
        Chaque ligne = un filtre triangulaire centré sur une fréquence Mel.
    """
    if fmax is None:
        fmax = sample_rate / 2

    # Conversion Hz → Mel et retour
    def hz_to_mel(hz): return 2595 * np.log10(1 + hz / 700)
    def mel_to_hz(mel): return 700 * (10**(mel / 2595) - 1)

    # Points Mel équidistants
    mel_min, mel_max = hz_to_mel(fmin), hz_to_mel(fmax)
    mel_points = np.linspace(mel_min, mel_max, n_filters + 2)
    hz_points = mel_to_hz(mel_points)

    # Correspondance bins FFT
    bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

    # Filter bank triangulaire
    filters = np.zeros((n_filters, n_fft // 2 + 1))
    for m in range(1, n_filters + 1):
        left, center, right = bin_points[m-1], bin_points[m], bin_points[m+1]
        filters[m-1, left:center] = np.linspace(0, 1, center - left)
        filters[m-1, center:right] = np.linspace(1, 0, right - center)

    return filters
```

#### Intégration dans le score audio

Pondération dans `_compute_audio_score()` — ajouter **15% de poids Mel** en réduisant les autres :

**Avant (constants.py actuel)** :
- LRA : 30, Noise floor : 25, Clipping : 20, Dynamic range : 15, Crest : 10

**Après** :
- LRA : 25, Noise floor : 20, Clipping : 15, Dynamic range : 15, Crest : 10, **Mel : 15** (total 100)

Le score Mel est composite des 4 sous-analyses :
- Soft clipping : 40%
- MP3 shelf : 20% (présent = pénalité)
- AAC holes : 30%
- Spectral flatness cohérence : 10%

#### Coût et intégration pipeline

- Extraction audio : déjà faite par §9 (même segment 30 s à 60 s offset).
- FFT : déjà calculée par §9 → réutiliser directement.
- Filter bank Mel : ~50 ms à construire une fois.
- Application à tous les frames STFT : ~100 ms pour 30 s d'audio.
- Analyses dérivées : ~50 ms.
- **Total : ~200 ms** si on réutilise le FFT de §9. Acceptable.

**Décision finale :**

1. **Stack** : **numpy pur**, cohérent avec §9.
2. **Réutilisation FFT §9** : `spectral_analysis.compute_spectrogram()` → Mel filter bank appliqué par-dessus.
3. **Même segment** que §9 (30 s à offset 60 s, 48 kHz mono).
4. **4 analyses** : soft clipping, MP3 shelf, AAC holes, spectral flatness.
5. **15% du poids** dans le score audio final.
6. **Setting** : `perceptual_audio_mel_enabled` (défaut `True`).
7. **Stockage** : 6 champs dans `AudioPerceptual` :
   - `mel_soft_clipping_pct: float`
   - `mel_mp3_shelf_detected: bool`
   - `mel_aac_holes_ratio: float`
   - `mel_spectral_flatness: float`
   - `mel_score: int` (composite 0-100)
   - `mel_verdict: str` (`"clean" | "soft_clipped" | "mp3_encoded" | "aac_low_bitrate" | "unknown"`)

**Seuils validés :**

```python
# constants.py ajouts
MEL_N_FILTERS = 64
MEL_FMIN = 0.0
MEL_FMAX = 24000.0                       # Nyquist à 48kHz SR

# Soft clipping
MEL_SOFT_CLIP_HARMONICS_MIN_PCT = 5.0
MEL_SOFT_CLIP_HARMONICS_WARN_PCT = 15.0
MEL_SOFT_CLIP_HARMONICS_SEVERE_PCT = 30.0

# MP3 shelf
MEL_MP3_SHELF_DROP_DB = 20.0
MEL_MP3_SHELF_MIN_FRAMES_PCT = 70.0

# AAC holes
MEL_AAC_HOLE_THRESHOLD_DB = -80.0
MEL_AAC_HOLE_RATIO_WARN = 0.05
MEL_AAC_HOLE_RATIO_SEVERE = 0.10
MEL_AAC_SYNTHETIC_VARIANCE_THRESHOLD = 0.05

# Score composite Mel
MEL_WEIGHT_SOFT_CLIP = 40
MEL_WEIGHT_MP3_SHELF = 20
MEL_WEIGHT_AAC_HOLES = 30
MEL_WEIGHT_FLATNESS = 10
```

**Cas limites identifiés :**

1. Silence prolongé (art et essai) : Mel spec tout à -infinity → verdict `silent_audio`.
2. Audio court < 3 s : FFT peu significative, skip analyses Mel.
3. Sample rate 22 kHz (vieux films) : Nyquist 11 kHz, bandes Mel au-dessus ignorées.
4. Bruitage artificiel / film muet (musique seule) : flatness élevée partout, analyses peu discriminantes.
5. Film N&B musette classique : passé HP analog → signature spectrale différente des films modernes. À ne pas confondre avec compression.
6. Masters vintage analogiques : absence de HF naturelle, faux positif lossy si combiné avec §9 sans cross-check.

**Références :**

- [librosa — mel spectrogram doc](https://librosa.org/doc/main/generated/librosa.feature.melspectrogram.html) (référence)
- [Tim Sainburg — Spectrograms, MFCCs, Inversion in Python](https://timsainburg.com/python-mel-compression-inversion.html)
- [Ketan Doshi — Why Mel Spectrograms perform better](https://ketanhdoshi.github.io/Audio-Mel/)
- [Compression Robust Synthetic Speech Detection (arxiv 2024)](https://arxiv.org/html/2402.14205v1)
- Code CineSort : [spectral_analysis.py](../../../cinesort/domain/perceptual/spectral_analysis.py) (à créer §9)

---

## Vague 5 — ML

### §10 — VMAF no-reference 📦 REPORTÉ v7.6.0+ (pas de modèle public)

**Statut :** reporté en v7.6.0+ après **découverte critique** lors de la recherche approfondie : **aucun modèle NR-VMAF pré-entraîné public n'est disponible en ONNX (ni dans d'autre format prêt à l'emploi)** au 2026-04-23.

---

**Date :** 2026-04-23

**Findings — pourquoi reporter :**

#### Le constat honnête

La recherche initiale (§10 Vague 5 du plan) partait de l'hypothèse que NR-VMAF serait accessible via un modèle ONNX quantifié (~50-80 MB). **Cette hypothèse est fausse** après vérification approfondie :

1. **Le papier IEEE 2024** ([No-Reference VMAF: A Deep Neural Network-Based Approach](https://ieeexplore.ieee.org/document/10564175/)) décrit l'architecture (patch extraction sharpness-based + CNN + DNN) mais **ne distribue ni le code ni les poids**.
2. **Le repo officiel [Netflix/vmaf](https://github.com/Netflix/vmaf)** contient uniquement les modèles **Full-Reference** (FR) qui nécessitent une vidéo de référence — **pas notre cas** (on compare 2 fichiers utilisateur sans référence absolue).
3. **Aucun fork ou implémentation publique** de NR-VMAF n'a été trouvé sur GitHub/PyPI/HuggingFace (recherches ciblées multiples, avril 2026).
4. **Netflix** n'a pas mentionné d'intention de publier ces modèles dans sa roadmap publique.

#### Ce que ça changerait d'implémenter sans modèle

Pour délivrer quand même §10 en v7.5.0, 3 options possibles — **toutes mauvaises** :

**Option A — Entraîner notre propre NR-VMAF**
- Nécessite un dataset MOS annoté (Mean Opinion Score) par des humains
- ~500-2000 vidéos notées subjectivement = plusieurs mois de collecte
- Infrastructure GPU pour training (~A100 × 100 heures minimum)
- Risque de sous-performance vs modèle Netflix originial
- **Effort incompatible avec le périmètre v7.5.0**

**Option B — Utiliser ffmpeg-quality-metrics en mode "self-reference"**
- Downscale→upscale virtuel puis VMAF FR classique
- **C'est ce que fait déjà §13 SSIM self-ref** !
- Aucun gain vs §13, juste ajout dépendance ONNX inutilement
- **Redondant avec §13**

**Option C — Pivot vers MANIQA ou NIQE (NR IQA)**
- MANIQA est NR mais IMAGE quality, pas VIDEO. Modèle ONNX ~25 MB.
- NIQE est plus ancien, moins précis, mais sans réseau neuronal.
- Applique image-par-image → moyenne = proxy VQA
- **Approche viable mais pas "score VMAF industrie standard"** — on n'a pas le badge marketing.
- Si on le fait, **le communiquer clairement** : "score NR-IQA MANIQA" ≠ VMAF.

#### Décision finale : reporter §10 entièrement

**Raisonnement** :
- Notre valeur différenciante v7.5.0 est déjà **énorme** avec §15 Grain intelligence, §7 Fake 4K, §13 SSIM self-ref, §9 Spectral cutoff, §12 Mel.
- Ajouter un "score NR quelconque" pour la pub ("on a du ML !") sans solidité technique = **mauvaise ingénierie**.
- CineSort se positionne comme "app pro" → pas de faux-semblants techniques.
- LPIPS §11 reste viable et apporte une vraie valeur (comparaison perceptuelle A/B).

**Ce qui est mis dans le BACKLOG pour reprise v7.6.0+** :

1. **Surveiller la publication éventuelle du modèle NR-VMAF** par Netflix ou équipe académique.
2. **Alternative MANIQA** : si demandée par users, implémenter avec communication claire "MANIQA IQA" (pas VMAF).
3. **Alternative pVMAF Synamedia** : si licence devient accessible (actuellement proprio).
4. **Alternative training interne** : si la communauté CineSort grandit, possibilité de collecter du MOS via opt-in users.

#### Impact sur le score composite §16

Le plan initial §16 prévoyait 25% de poids VMAF dans le score vidéo. **Redistribution** :
- Score perceptuel classique (blockiness/blur/banding/grain) : 40% → **50%** (+10)
- **VMAF NR** : 25% → **0%** (supprimé v7.5.0)
- LPIPS vs référence : 15% (inchangé, §11)
- Métadonnées HDR : 10% → **15%** (+5)
- Résolution effective (fake 4K) : 10% → **20%** (+10)

Le score vidéo total reste **robuste et justifié** sans VMAF.

#### Si l'utilisateur insiste pour avoir un score "industrie standard"

Alternative viable : **afficher le score `vmaf_fr_self_referential`** (via SSIM self-ref §13 converti en échelle 0-100). Ce n'est pas du "vrai VMAF" mais c'est une approximation reconnue. Communication UI : "Score qualité auto-référentiel (style VMAF, 0-100)".

**Références :**

- [No-Reference VMAF — IEEE paper 2024](https://ieeexplore.ieee.org/document/10564175/)
- [Netflix/vmaf official repo (FR only)](https://github.com/Netflix/vmaf)
- [ffmpeg-quality-metrics PyPI (FR uniquement)](https://pypi.org/project/ffmpeg-quality-metrics/)
- [DeViQ — alternative NR VQA (pas de modèle public trouvé)](https://www.researchgate.net/publication/322869205_DeViQ_-_A_deep_no_reference_video_quality_model)
- [MANIQA GitHub (NR IQA alternative)](https://github.com/IIGROUP/MANIQA)
- [VQEG NORM project (groupe de recherche No-Reference)](https://vqeg.org/projects/norm/)

---

### §11 — LPIPS ✅

**Date :** 2026-04-23

**Findings :**

#### LPIPS reste viable (contrairement à VMAF NR)

Au terme de la recherche approfondie, **LPIPS est implémentable en v7.5.0** :
- Code source officiel disponible : [richzhang/PerceptualSimilarity](https://github.com/richzhang/PerceptualSimilarity)
- Export ONNX documenté via [alexlee-gk/lpips-tensorflow](https://github.com/alexlee-gk/lpips-tensorflow) :
  ```
  python export_to_tensorflow.py --model net-lin --net alex
  ```
- Licence BSD (utilisation libre).
- Modèle AlexNet LPIPS quantifié ONNX : **~50-60 MB**.
- ONNX Runtime (~30-50 MB Windows wheel) → bundle total **~100 MB ajoutés**.

#### Pourquoi LPIPS est parfait pour notre cas

Notre use case = **comparaison de 2 fichiers doublons** (modale deep-compare §4 Phase 4). Dans ce contexte :
- Le fichier A joue le rôle de **référence**
- Le fichier B est le **candidat** à évaluer
- LPIPS mesure la **distance perceptuelle humaine** entre frames alignées A/B
- Résultat : valeur 0.0-1.0 (plus petit = plus similaire)

**C'est PARFAITEMENT aligné** avec la comparaison doublons. Pas besoin de référence absolue (on a les deux fichiers comme référence mutuelle).

#### Variantes du modèle — choix

Les 3 backbones LPIPS officiels :

| Backbone | Taille ONNX | Performance | Recommandation |
|---|---|---|---|
| **AlexNet** | ~55 MB | **Le meilleur** comme forward metric (cité officiellement) | **Notre choix** |
| VGG16 | ~300 MB | Meilleur pour backprop (entraînement) — pas notre cas | Écarté (trop lourd) |
| SqueezeNet | ~10 MB | Ultra-light, légèrement moins précis | Option si bundle critique |

**Décision** : **AlexNet**. 55 MB est acceptable, et le backbone recommandé pour notre usage (inférence forward).

#### ONNX Runtime — specs découvertes

- Version stable 1.24.4 (avril 2026) avec wheels Python 3.13 Windows.
- Taille wheel CPU : **~30-50 MB** Windows x64.
- Python 3.13 free-threaded (GIL-less) support **expérimental** ([discussion #24319](https://github.com/microsoft/onnxruntime/discussions/24319)) — OK avec GIL standard qui reste.
- Backend par défaut : CPU (suffisant pour notre cas).
- GPU possible via onnxruntime-gpu séparé (optionnel en v7.6.0+ backlog).

#### Quantization INT8 — considérations

**Finding critique** ([issue #6030 onnx/onnx](https://github.com/onnx/onnx/issues/6030)) : **INT8 peut être PLUS LENT** que FP32 sur CPU sans VNNI/AVX512. Sur CPU anciens, la surcharge de quantize/dequantize excède le gain de calcul.

**Décision packaging** :
- Modèle **FP32** par défaut (compatible tous CPUs, ~55 MB).
- Pas de quantization INT8 v7.5.0 (risque regression perf sur CPU user moyen).
- Future optimisation (backlog) : détecter VNNI/AVX512 runtime et proposer modèle INT8 alternatif (~15 MB, 3-5x plus rapide sur hardware compatible).

#### Coût runtime par appel LPIPS

Mesures empiriques attendues sur CPU moyen (Intel i5/i7 8th gen) :
- Initialisation ONNX session (au boot) : ~500 ms
- Inférence 1 paire frames 256×256 : ~100-200 ms
- 5 paires frames (analyse deep-compare) : **~750 ms total**

**Acceptable** vs durée analyse totale (~2 min). Peut tourner en parallèle via §1.

#### Interprétation des scores LPIPS

Valeurs typiques (documentées par le projet officiel) :

| Distance LPIPS | Interprétation humain-perceptuelle |
|---|---|
| **< 0.05** | Quasi-identique (même source, même encode) |
| **0.05-0.15** | Très similaire (même source, encodes différents) |
| **0.15-0.30** | Similaire (même film mais versions/masters différents) |
| **0.30-0.50** | Différent (theatrical vs director's cut, ou remaster color-grade différent) |
| **> 0.50** | Très différent (films différents, ou erreur sélection frames) |

#### Intégration dans la comparaison deep-compare

Dans la modale Phase 4, LPIPS apporte une **métrique humaine** en complément des mesures pixel :
- **Pixel diff classique** (§13 existant `compare_per_frame`) : mesure la différence numérique brute.
- **LPIPS** : mesure la **différence perçue par un humain**.

Exemple scénario : 2 fichiers Matrix 1999 :
- Fichier A : UHD HDR10 master récent.
- Fichier B : Blu-ray 2008 SDR.
- Pixel diff = **énorme** (HDR vs SDR = tout les pixels changent).
- LPIPS = **modéré** (~0.25) car structure et contenu restent identifiables.

Le LPIPS distingue "les pixels diffèrent mais c'est visuellement le même film" vs "c'est un film totalement différent".

#### Cas limites identifiés

1. **Film colorisé vs N&B** : LPIPS élevé (>0.4) même si c'est le même film. Flag `colorization_variant_suspect` à cross-check avec tmdb/versions.
2. **Master restauré vs original endommagé** : LPIPS élevé car corrections visuelles multiples. À contextualiser avec année/remaster.
3. **Versions cropped vs full frame** : si les frames alignées n'ont pas le même cadrage (letterbox vs open matte), LPIPS faussé. Pré-crop recommandé avant inférence.
4. **Frame extraction échoue sur un des 2 fichiers** : impossible de calculer, retour `None`.
5. **Frames noires** (début de séquence) : LPIPS très bas (quasi identique sur tout noir) → exclure ces frames comme pour §7 FFT.

#### Tests et corpus de validation

Corpus `tests/fixtures/lpips_compare/` à constituer avec 8 paires étiquetées :
- 2 paires identiques (encodes différents du même master)
- 2 paires remaster (ancien Blu-ray vs UHD HDR)
- 2 paires theatrical vs director cut
- 1 paire colorisation (N&B vs coloré)
- 1 paire films différents (contrôle négatif)

**Décision finale :**

1. **Stack** : `onnxruntime>=1.24` + modèle LPIPS AlexNet ONNX FP32 (~55 MB) embarqué dans `assets/models/lpips_alexnet.onnx`.
2. **Module** : `cinesort/domain/perceptual/lpips_compare.py`.
3. **Appel** : uniquement dans `deep_compare_pair()` (pas dans l'analyse single-film). N'impacte pas le scan standard.
4. **Nombre de frames** : 5 paires alignées (réutilise `extract_aligned_frames` §7 comparison).
5. **Score global** : médiane des 5 distances LPIPS.
6. **Pondération score composite §16** : **15% du score visuel** dans deep-compare uniquement.
7. **Setting** : `perceptual_lpips_enabled` (défaut `True`).
8. **Fallback gracieux** : si ONNX Runtime ou modèle indisponible, log warning, `lpips_distance = None`, ne bloque pas la comparaison.

**Seuils validés :**

```python
# constants.py ajouts
LPIPS_MODEL_PATH = "assets/models/lpips_alexnet.onnx"
LPIPS_INPUT_SIZE = 256                         # LPIPS entraîné sur 256x256
LPIPS_N_FRAMES_PAIRS = 5                       # nombre de paires analysées
LPIPS_DISTANCE_IDENTICAL = 0.05
LPIPS_DISTANCE_VERY_SIMILAR = 0.15
LPIPS_DISTANCE_SIMILAR = 0.30
LPIPS_DISTANCE_DIFFERENT = 0.50
LPIPS_INFERENCE_TIMEOUT_S = 30
```

**Cas limites identifiés :**

1. `onnxruntime` non installé (bundle cassé) → ImportError catchée au module load, feature désactivée silencieusement.
2. Modèle ONNX corrompu ou absent → log error, fallback `lpips = None`.
3. Frames non 256×256 → resize bicubique avant inférence.
4. Frames en niveau de gris (N&B) → conversion 3 canaux identiques (Y→RGB).
5. Timeout inférence → fallback `None`.
6. Moins de 3 paires frames valides → verdict `insufficient_data`.

**Références :**

- [richzhang/PerceptualSimilarity (repo officiel)](https://github.com/richzhang/PerceptualSimilarity)
- [alexlee-gk/lpips-tensorflow (export ONNX)](https://github.com/alexlee-gk/lpips-tensorflow)
- [LPIPS original paper (Zhang 2018)](https://arxiv.org/abs/1801.03924) — "The Unreasonable Effectiveness of Deep Features as a Perceptual Metric"
- [lpips PyPI](https://pypi.org/project/lpips/)
- [S-aiueo32/lpips-pytorch (implémentation simplifiée)](https://github.com/S-aiueo32/lpips-pytorch)
- [onnxruntime release notes](https://github.com/microsoft/onnxruntime/releases)
- [TransferLab blog — Perceptual similarity metrics](https://transferlab.ai/blog/perceptual-metrics/)
- [Torchmetrics LPIPS doc](https://lightning.ai/docs/torchmetrics/stable/image/learned_perceptual_image_patch_similarity.html)

---

## Vague 6 — Synthèse

### §16 — Score composite et visualisation ✅ (section de synthèse)

**Date :** 2026-04-23

**Findings :**

#### Le défi — rendre lisible un score composé de 14+ sous-scores

Les Vagues 1-5 ont produit un arsenal de **14+ métriques** :
- **Vidéo (10)** : blockiness, blur, banding, bit-depth, grain v2 (§15), temporal consistency, HDR validation (§5), Dolby Vision (§6), fake 4K FFT+SSIM (§7+§13), interlacing/crop/judder/IMAX (§8)
- **Audio (6)** : LRA, noise floor, clipping, dynamic range, crest, Mel (§12), spectral cutoff (§9), DRC (§14), chromaprint (§3)
- **Cohérence (2)** : runtime vs TMDb, NFO consistency

Un utilisateur non-expert doit pouvoir **comprendre en 5 secondes** si un fichier est bon. Un expert doit pouvoir **creuser en profondeur** en 30 secondes. **C'est le défi de §16.**

#### Principes de conception (issus de la recherche UX)

1. **Hiérarchie progressive** : global → 3 catégories → détail
2. **Couleurs universelles** : rouge/jaune/vert/bleu/or (codes compréhensibles sans légende)
3. **Confidence intégrée** : scores à faible confidence **moins visibles** (transparence)
4. **Warnings contextualisés** : encarts jaunes pour les cas spéciaux (VMAF surestimé, version différente, etc.)
5. **Tooltip éducatif** : explication FR courte de chaque score (ce qu'il mesure, pourquoi c'est important)
6. **Pas de jargon** : "Détails fins des textures" plutôt que "Texture variance ratio"

#### Architecture du score composite (post suppression VMAF NR)

```
SCORE GLOBAL CINESORT : 0-100
│
├── SCORE VIDÉO (60% du total)                         0-100
│   │
│   ├── Perceptuel classique         (50% du vidéo)    0-100
│   │   ├── Blockiness    (25%)                        0-100
│   │   ├── Blur          (20%)                        0-100
│   │   ├── Banding       (15%)                        0-100
│   │   ├── Bit depth     (15%)                        0-100
│   │   ├── Grain verdict (15%) ← enrichi §15 v2      0-100
│   │   └── Temporal      (10%)                        0-100
│   │
│   ├── Résolution effective         (20% du vidéo)    0-100
│   │   ├── Fake 4K FFT          (50%) §7              bool→100/50/0
│   │   └── SSIM self-ref         (50%) §13            bool→100/50/0
│   │
│   ├── Métadonnées HDR              (15% du vidéo)    0-100
│   │   ├── HDR type             (60%) §5              table 40-100
│   │   ├── HDR validation       (20%) §5              bool→100/65/50
│   │   ├── Dolby Vision profile (20%) §6              table 80-100
│   │
│   └── LPIPS (deep-compare only)    (15% du vidéo)    0-100 (inversé distance)
│
├── SCORE AUDIO (35% du total)                         0-100
│   │
│   ├── Perceptuel classique         (50% de l'audio)  0-100
│   │   ├── LRA                   (25%)                0-100
│   │   ├── Noise floor           (20%)                0-100
│   │   ├── Clipping              (15%)                0-100
│   │   ├── Dynamic range         (15%)                0-100
│   │   ├── Crest factor          (10%)                0-100
│   │   └── Mel score             (15%) §12            0-100
│   │
│   ├── Spectral cutoff              (20% de l'audio)  0-100 (via verdict §9)
│   │
│   ├── DRC category                 (15% de l'audio)  0-100 (via §14 cinema=100/std=70/broadcast=40)
│   │
│   ├── Chromaprint                  (5% de l'audio)   informationnel, pas noté
│   │
│   └── (5% réservé pour extensions futures)
│
└── SCORE COHÉRENCE (5% du total)                      0-100
    ├── Runtime vs TMDb            (60%)               bool→100/70/40
    └── NFO consistency             (40%)               existant
```

**Vérification** : total pondérations = 60 + 35 + 5 = 100. Sous-scores vidéo = 50 + 20 + 15 + 15 = 100. Sous-scores audio = 50 + 20 + 15 + 5 + 5 = 95 (+5 réserve). OK.

#### Confidence pondération — le subtle qui change tout

Chaque score calculé a une **confidence 0.0-1.0** qui reflète sa fiabilité. Exemples :
- HDR MaxCLL présent, film HDR10 clair → confidence 0.95
- Fichier court, 5 frames analysées seulement → confidence 0.60
- Tmdb metadata manquante → confidence 0.50 sur grain verdict

**Calcul du score final** : moyenne pondérée **par le produit poids × confidence**, pas juste par poids seul.

```python
def weighted_score_with_confidence(scores: list[tuple[float, float, float]]) -> float:
    """Chaque élément = (score, weight, confidence).

    Formula: sum(score_i * weight_i * confidence_i) / sum(weight_i * confidence_i)
    """
    weights_effectifs = [w * c for (_, w, c) in scores]
    if sum(weights_effectifs) == 0:
        return 50.0  # neutre si rien d'utilisable
    total = sum(s * w * c for (s, w, c) in scores)
    return total / sum(weights_effectifs)
```

**Conséquence** : un score faible-confidence **contribue peu** au score final → pas de bruit parasite. Un score haute-confidence domine.

#### Ajustements dynamiques contextuels

Certains scores doivent être **recalibrés** selon le contexte du film. Les règles :

##### Règle 1 — Grain v2 bonus/malus
- `grain_nature == "film_grain"` ET `is_partial_dnr == False` → **+10 pts** sur score vidéo (master respectueux)
- `is_partial_dnr == True` → **−15 pts** (perte qualité masquée)
- `grain_nature == "encode_noise"` → **−8 pts** (compression destructive)

##### Règle 2 — AV1 Film Grain Metadata
- `av1_afgs1_present == True` → **+15 pts** sur score vidéo (encodage grain-respectueux confirmé)

##### Règle 3 — Dolby Vision Profile 5 warning
- `dv_profile == "5"` → **−8 pts** sur score vidéo (incompatibilité players non-DV)
- Warning UI clair affiché.

##### Règle 4 — HDR metadata manquante
- `hdr_validation_flag == "hdr_metadata_missing"` → **−10 pts** sur composante HDR

##### Règle 5 — IMAX Expansion bonus
- `imax_type == "expansion"` → **+15 pts** (format prestige, master IMAX Enhanced)
- `imax_type == "full_frame_143"` ou `"digital_190"` → **+10 pts**

##### Règle 6 — Spectral cutoff / codec cross-validation
- Si codec audio dit lossless (FLAC) ET `lossy_verdict == "lossy_mid"` → **flag suspect** + **−10 pts** (fake lossless)
- Si codec MP3 ET `lossy_verdict == "lossless"` (faux positif, rare) → **warning** pour user, pas de malus

##### Règle 7 — Version hint
- `runtime_vs_tmdb_verdict in ("theatrical_cut", "extended_cut", "director_cut")` → **pas de malus**, mais **warning clair** dans UI : "version possible différente, vérifier avant décision".

##### Règle 8 — Animation skip
- Si `tmdb.genres contient Animation` → **ignorer** les pénalités grain, fake 4K (contexte non applicable).

##### Règle 9 — Vintage master (classic_film era) tolérance
- Si `era in ("16mm_era", "35mm_classic")` ET `lossy_verdict == "lossy_high"` (cutoff 19-20 kHz) → **tolérance**, flag `lossless_vintage_master` au lieu de malus.

#### Tier final

Le score global est converti en **tier CinemaLux** existant (cohérence avec le reste de l'app) :

| Score global | Tier | Couleur | Badge |
|---|---|---|---|
| ≥ 90 | **Platinum** | Or | Excellence, master UHD |
| 80-89 | **Gold** | Vert | Très bon, standard UHD/Blu-ray |
| 65-79 | **Silver** | Bleu | Bon, DVD/Blu-ray standard |
| 50-64 | **Bronze** | Orange | Acceptable, compressions notables |
| < 50 | **Reject** | Rouge | Déficient, à remplacer |

Note : les tiers existants CineSort sont `Premium/Bon/Moyen/Mauvais/Reject`. En v7.5.0 on garde la cohérence avec la **nouvelle maquette Platinum/Gold/Silver/Bronze/Reject** que l'utilisateur a validé en phase d'audit (demande initiale).

#### Visualisation — 3 niveaux de détail

##### Niveau 1 — Score global (vue rapide, 1 seconde)

Un grand **cercle SVG animé** au-dessus de la modale deep-compare :
```
            ╭──────╮
           │  94  │    ← valeur animée comptage 0→94
           ╰──●───╯    ← arc coloré tier (or)
            PLATINUM   ← label tier
```
- Remplissage circulaire (stroke dasharray SVG).
- Couleur du stroke selon tier.
- Animation 1.5 s (easing CinemaLux standard).
- Confidence affichée en petit : "confiance 92%".

##### Niveau 2 — 3 jauges catégorie (vue structurée, 5 secondes)

Sous le cercle global, 3 jauges horizontales :
```
┌── Vidéo (60%) ──────────────────────────────────────┐
│ ████████████████████████░░░░░░░░ 92/100  Gold       │
└──────────────────────────────────────────────────────┘
┌── Audio (35%) ──────────────────────────────────────┐
│ ███████████████████░░░░░░░░░░░░░ 80/100  Gold       │
└──────────────────────────────────────────────────────┘
┌── Cohérence (5%) ───────────────────────────────────┐
│ █████████████████████████░░░░░░░ 88/100  Gold       │
└──────────────────────────────────────────────────────┘
```
- Largeur de la barre représente la pondération (60% = large, 35% = moyen, 5% = petit).
- Couleur selon tier de la catégorie.
- Nombre à droite.

##### Niveau 3 — Accordéon détaillé (vue expert, 30 secondes)

Chaque catégorie cliquable → développe le détail des sous-scores avec **bar charts individuels** :
```
▼ Vidéo · Détail
  ├─ Perceptuel classique              50%     92 Gold
  │   ├─ Blockiness     25%  98 ●●●●●
  │   ├─ Blur           20%  94 ●●●●○
  │   ├─ Banding        15%  88 ●●●●○
  │   ├─ Bit depth      15%  95 ●●●●●
  │   ├─ Grain verdict  15%  90 ●●●●○  [Film grain authentique, +10 bonus]
  │   └─ Temporal       10%  89 ●●●●○
  │
  ├─ Résolution effective              20%     100 Platinum
  │   └─ 4K native confirmée (FFT ratio 0.21, SSIM 0.86)
  │
  ├─ Métadonnées HDR                   15%     95 Platinum
  │   ├─ Dolby Vision Profile 8.1  ✓
  │   ├─ MaxCLL 1000 nits ✓
  │   └─ Chroma 4:2:0 ✓
  │
  └─ LPIPS (comparaison A/B)           15%     87 Gold
      └─ Distance 0.12 → "très similaire"
```
- Hover tooltip FR : explication du score.
- Couleurs graduées par confidence.
- Clic sur un sous-score → détail métrique brute.

##### Warnings en encarts jaunes (top-level)

Au-dessus du cercle global, si warnings :
```
⚠ Attention : runtime 145 min vs TMDb 162 min (−17 min).
   Possible version Theatrical Cut. Vérifiez avant de comparer avec Director's Cut.

ℹ Film Dolby Vision Profile 5 : couleurs nécessitent un player DV licensé.
   Sur un player HDR10 standard, le rendu sera incorrect (vert délavé, teintes roses).
```

#### Alternative : radar chart pour vue "d'un coup d'œil"

Pour les power users, option toggle "Vue radar" :

```
          Vidéo perceptuel
                ●
               ╱ │ ╲
              ╱  │  ╲
  Cohérence ●───●───● Résolution
              ╲  │  ╱
               ╲ │ ╱
                ●  DR Audio
            Audio perceptuel
```

5 axes : vidéo perceptuel, résolution, cohérence, audio perceptuel, DR audio. Polygone rempli en orange/vert selon score. **Force du radar** : on voit immédiatement les **points faibles**.

**Décision** : toggle optionnel, pas le mode par défaut (moins lisible pour non-experts).

#### Customisation utilisateur (optionnel, backlog)

Un power user peut vouloir ajuster les pondérations (ex: un cinéphile audiophile veut 50% audio / 50% vidéo au lieu de 60/35). **Reporté en v7.6.0** (backlog) : setting "Profil scoring personnalisé" avec sliders.

En v7.5.0 : **pondérations fixes, documentées**. Pas de configuration user pour éviter les scores "tweakés" incomparables entre users.

**Décision finale :**

1. **Architecture** : global → 3 catégories (vidéo 60% / audio 35% / cohérence 5%) → sous-scores détaillés.
2. **Pondération par confidence** : score_final = Σ(score × poids × confidence) / Σ(poids × confidence).
3. **9 règles d'ajustement contextuel** (grain v2, AV1 AFGS1, DV Profile 5, HDR metadata, IMAX, spectral cross-check, version hint, animation skip, vintage tolerance).
4. **5 tiers** : Platinum/Gold/Silver/Bronze/Reject (cohérence avec la maquette de départ).
5. **3 niveaux de visualisation** : cercle global → 3 jauges → accordéon détaillé.
6. **Warnings contextualisés** en encarts jaunes.
7. **Tooltip FR éducatif** sur chaque score pour users non-experts.
8. **Animations CinemaLux** cohérentes avec le reste de l'app.
9. **Radar chart optionnel** pour power users (toggle).
10. **Pas de customisation pondérations** en v7.5.0 (reporté v7.6.0).

**Cas limites identifiés :**

1. **Score vidéo très haut, audio très bas** (ou inverse) : le score global masque le problème. **Solution** : warning "Audio déficient" ou "Vidéo déficient" si delta > 40 pts entre les 2.
2. **Confidence très basse partout** (fichier probe incomplet) : affichage score avec grande transparence + warning "Analyse partielle, confidence limitée".
3. **Toutes les métriques optionnelles échouent** (LPIPS, Mel, Spectral) : score dégradé mais non bloqué, poids effectifs recalculés.
4. **User debug mode** : exposer les poids effectifs utilisés (pour comprendre d'où vient un score bizarre).
5. **Version hint flag `unknown_version`** : diff > 30 min vs TMDb → warning très visible, comparaison de doublons déconseillée.

**Références :**

- [Weighted scoring model — Tempo](https://www.tempo.io/blog/weighted-scoring-model)
- [UX Scorecards — MeasuringU](https://measuringu.com/ux-scorecard/)
- [User Experience Score — Dynatrace](https://www.dynatrace.com/news/blog/user-experience-score-the-one-metric-to-rule-them-all/)
- [Confidence Visualization UI Patterns](https://agentic-design.ai/patterns/ui-ux-patterns/confidence-visualization-patterns)
- [Visualizing Uncertainty — FlowingData](https://flowingdata.com/2018/01/08/visualizing-the-uncertainty-in-data/)
- [Origami plot — radar chart improvement (PMC 2023)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10599795/)
- [Fundamentals of Data Visualization — Visualizing Uncertainty](https://clauswilke.com/dataviz/visualizing-uncertainty.html)
- [VMAF score explanation (Netflix tech blog)](https://netflixtechblog.com/toward-a-better-quality-metric-for-the-video-community-7ed94e752a30)
- [VMAF Reproducibility IEEE paper](https://realnetworks.com/sites/default/files/vmaf_reproducibility_ieee.pdf)
- Code CineSort existant : [composite_score.py](../../../cinesort/domain/perceptual/composite_score.py), [web/views/validation.js](../../../web/views/validation.js)

---

## Fin des notes de recherche
