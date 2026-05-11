"""Constantes et seuils pour l'analyse perceptuelle."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Version du moteur perceptuel
# ---------------------------------------------------------------------------
PERCEPTUAL_ENGINE_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Selection de frames
# ---------------------------------------------------------------------------
FRAME_MIN_VARIANCE_8BIT = 50.0  # skip pure black / blank frames (8-bit Y)
FRAME_MIN_VARIANCE_10BIT = 800.0  # equivalent 10-bit
FRAME_SKIP_PERCENT = 5  # ignorer premier / dernier 5 % de la duree
FRAME_MIN_INTER_DIFF = 500.0  # diff minimum entre frames selectionnees
FRAME_REPLACEMENT_ATTEMPTS = 3  # tentatives de remplacement si frame non representative
FRAME_DOWNSCALE_THRESHOLD = 1920  # width > 1920 => downscale pour analyse pixel

# ---------------------------------------------------------------------------
# Blockiness (blockdetect output, 0-100)
# ---------------------------------------------------------------------------
BLOCK_NONE = 10.0  # < 10 : pas d'artefacts visibles
BLOCK_SLIGHT = 25.0  # 10-25 : legers, visibles sur grands ecrans
BLOCK_MODERATE = 50.0  # 25-50 : moderes, visibles en mouvement
BLOCK_SEVERE = 75.0  # > 50 : artefacts de compression severes

# ---------------------------------------------------------------------------
# Blur (blurdetect output, 0-1)
# ---------------------------------------------------------------------------
BLUR_SHARP = 0.01  # < 0.01 : tres net, excellent detail
BLUR_NORMAL = 0.03  # 0.01-0.03 : douceur cinematique normale
BLUR_SOFT = 0.06  # 0.03-0.06 : doux, possible DNR / upscale
BLUR_VERY_SOFT = 0.10  # > 0.06 : tres doux, DNR probable

# ---------------------------------------------------------------------------
# Banding (score calcule, 0-100)
# ---------------------------------------------------------------------------
BANDING_NONE = 5
BANDING_SLIGHT = 15  # visible dans degrades sombres
BANDING_MODERATE = 30
BANDING_SEVERE = 50  # 8-bit encode d'une source 10-bit probable

# ---------------------------------------------------------------------------
# Bit depth effectif
# ---------------------------------------------------------------------------
EFFECTIVE_BITS_EXCELLENT = 9.5  # vrai 10-bit exploite
EFFECTIVE_BITS_GOOD = 8.5
EFFECTIVE_BITS_MEDIOCRE = 7.5
EFFECTIVE_BITS_POOR = 6.5

# ---------------------------------------------------------------------------
# Grain
# ---------------------------------------------------------------------------
GRAIN_NONE = 0.5  # image propre numerique
GRAIN_LIGHT = 1.5  # leger, naturel pour digital moderne
GRAIN_MODERATE = 3.0  # modere, typique pellicule
GRAIN_HEAVY = 5.0  # lourd, vieux stock ou mauvais scan
GRAIN_UNIFORMITY_NATURAL = 0.7  # < 0.7 : grain naturel varie
GRAIN_UNIFORMITY_ARTIFICIAL = 0.9  # > 0.9 : suspicieusement uniforme (ajoute)

# ---------------------------------------------------------------------------
# Scene sombre et N&B
# ---------------------------------------------------------------------------
DARK_SCENE_Y_AVG_THRESHOLD = 50  # Y_avg < 50 = scene sombre (0-255)
BW_SATURATION_THRESHOLD = 5.0  # saturation moyenne < 5 = N&B

# ---------------------------------------------------------------------------
# Consistance temporelle
# ---------------------------------------------------------------------------
TEMPORAL_CONSISTENCY_GOOD = 15.0
TEMPORAL_CONSISTENCY_POOR = 35.0

# ---------------------------------------------------------------------------
# Color space
# ---------------------------------------------------------------------------
BT2020_THRESHOLDS_MULTIPLIER = 1.15  # seuils 15 % plus indulgents en BT.2020

# ---------------------------------------------------------------------------
# Audio — EBU R128
# ---------------------------------------------------------------------------
LRA_EXCELLENT = 15.0  # > 15 LU : dynamique cinema
LRA_GOOD = 10.0  # 10-15 LU : bonne dynamique
LRA_COMPRESSED = 7.0  # 7-10 LU : moderement compresse
LRA_FLAT = 4.0  # < 7 LU : fortement compresse (streaming)

TP_MAX = -1.0  # True peak < -1 dBTP (EBU R128)
TP_CLIPPING = 0.0  # >= 0 dBTP = clipping

# ---------------------------------------------------------------------------
# Audio — astats
# ---------------------------------------------------------------------------
NOISE_FLOOR_EXCELLENT = -70.0
NOISE_FLOOR_GOOD = -60.0
NOISE_FLOOR_MEDIOCRE = -50.0
NOISE_FLOOR_POOR = -40.0

DYNAMIC_RANGE_EXCELLENT = 60.0
DYNAMIC_RANGE_GOOD = 45.0
DYNAMIC_RANGE_MEDIOCRE = 30.0

CREST_FACTOR_EXCELLENT = 20.0
CREST_FACTOR_GOOD = 14.0
CREST_FACTOR_COMPRESSED = 8.0

# ---------------------------------------------------------------------------
# Clipping
# ---------------------------------------------------------------------------
CLIPPING_THRESHOLD_DBFS = -0.1  # Peak >= -0.1 dBFS = clipping
CLIPPING_ACCEPTABLE_PCT = 2.0
CLIPPING_MODERATE_PCT = 5.0
CLIPPING_SEVERE_PCT = 10.0

# ---------------------------------------------------------------------------
# Grain / DNR — contextualisation production
# ---------------------------------------------------------------------------
ERA_CLASSIC_FILM = 2002  # pre-2002 : pellicule, grain attendu
ERA_TRANSITION = 2012  # 2002-2012 : transition film / digital
BUDGET_HIGH = 50_000_000  # > 50M : master pro, attente haute
BUDGET_MEDIUM = 10_000_000

MAJOR_STUDIOS: frozenset[str] = frozenset(
    {
        "Warner Bros.",
        "Warner Bros. Pictures",
        "Universal Pictures",
        "20th Century Fox",
        "20th Century Studios",
        "Paramount Pictures",
        "Columbia Pictures",
        "Sony Pictures",
        "Walt Disney Pictures",
        "Metro-Goldwyn-Mayer",
        "Lionsgate",
        "Lionsgate Films",
        "New Line Cinema",
        "DreamWorks",
        "DreamWorks Pictures",
        "A24",
        "Focus Features",
        "Searchlight Pictures",
        "StudioCanal",
    }
)

DNR_BLUR_THRESHOLD = 0.04
DNR_GRAIN_ABSENT_THRESHOLD = 0.8

# ---------------------------------------------------------------------------
# Score composite
# ---------------------------------------------------------------------------

# Score visuel (somme = 100)
VISUAL_WEIGHT_BLOCKINESS = 25
VISUAL_WEIGHT_BLUR = 20
VISUAL_WEIGHT_BANDING = 15
VISUAL_WEIGHT_BIT_DEPTH = 15
VISUAL_WEIGHT_GRAIN_VERDICT = 15
VISUAL_WEIGHT_TEMPORAL = 10

# Score audio (somme = 100)
AUDIO_WEIGHT_LRA = 25  # §12 v7.5.0 : 30 -> 25 (redistribution pour AUDIO_WEIGHT_MEL)
AUDIO_WEIGHT_NOISE_FLOOR = 20  # §12 v7.5.0 : 25 -> 20
AUDIO_WEIGHT_CLIPPING = 15  # §12 v7.5.0 : 20 -> 15
AUDIO_WEIGHT_DYNAMIC_RANGE = 15
AUDIO_WEIGHT_CREST = 10
AUDIO_WEIGHT_MEL = 15  # §12 v7.5.0 : nouveau poids Mel spectrogram (total = 100)

# Global
GLOBAL_WEIGHT_VIDEO = 60
GLOBAL_WEIGHT_AUDIO = 40

# Tiers perceptuels (distincts des tiers techniques)
TIER_REFERENCE = 90  # "Reference" (badge or)
TIER_EXCELLENT = 75  # "Excellent" (badge vert)
TIER_GOOD = 60  # "Bon" (badge bleu)
TIER_MEDIOCRE = 40  # "Mediocre" (badge orange)
# < 40 : "Degrade" (badge rouge)

TIER_LABELS = {
    "reference": "Reference",
    "excellent": "Excellent",
    "bon": "Bon",
    "mediocre": "Mediocre",
    "degrade": "Degrade",
}

# ---------------------------------------------------------------------------
# Placeholder calibration (extension future — hors scope 9.24)
# L'utilisateur note manuellement 3-5 films connus. CineSort compare ses
# scores avec les notes humaines et ajuste automatiquement les seuils.
# Architecture prevue : UserCalibration dataclass + adjust_thresholds()
# dans un futur module perceptual/calibration.py.
# ---------------------------------------------------------------------------
CALIBRATION_ENABLED = False
CALIBRATION_MIN_FILMS = 3

# Seuil de duree pour adapter le nombre de frames
SHORT_FILM_DURATION_S = 120.0  # < 2 min = film tres court

# ---------------------------------------------------------------------------
# Parallelisme (§1 v7.5.0)
# ---------------------------------------------------------------------------
PARALLELISM_MAX_WORKERS_SINGLE_FILM = 2  # video + audio en parallele
PARALLELISM_MAX_WORKERS_DEEP_COMPARE = 4  # A-video, A-audio, B-video, B-audio
PARALLELISM_MIN_CPU_CORES = 4  # en dessous : fallback serial
PARALLELISM_AUTO_FACTOR = 2  # workers = cpu_count // factor

# ---------------------------------------------------------------------------
# V5-02 Polish Total v7.7.0 (R5-STRESS-5) — Parallelisme batch (inter-films)
# ---------------------------------------------------------------------------
# Le batch perceptuel etait sequentiel : 10k films x 3 min = 14 jours.
# Avec N workers (ThreadPoolExecutor : ffmpeg subprocess libere le GIL),
# on cible ~2 jours sur 8 cores. Le pool externe limite le nb de films
# analyses en parallele, chaque worker delegue ses sous-taches video/audio
# au pool interne (cf parallelism.py) qui est force en mode "serial" pour
# eviter la sur-souscription (8 externes x 2 internes = 16 ffmpeg).
BATCH_PARALLELISM_MAX_WORKERS = 16  # garde-fou hard cap (memoire + I/O disque)
BATCH_PARALLELISM_AUTO_CAP = 8  # cap raisonnable en mode auto (defaut 0)
BATCH_PARALLELISM_MIN_FILMS_FOR_POOL = 2  # < 2 films : sequentiel direct
BATCH_PARALLELISM_DEFAULT_WORKERS = 0  # 0 = auto = min(cpu_count(), 8)

# ---------------------------------------------------------------------------
# Fingerprint audio Chromaprint (§3 v7.5.0)
# ---------------------------------------------------------------------------
AUDIO_FINGERPRINT_SEGMENT_OFFSET_S = 60  # debut segment (evite generique/logos)
AUDIO_FINGERPRINT_SEGMENT_DURATION_S = 120  # duree analysee (compromis signal/temps)
AUDIO_FINGERPRINT_MIN_FILE_DURATION_S = 180  # en dessous : tout le fichier
AUDIO_FINGERPRINT_TIMEOUT_S = 30  # timeout fpcalc.exe
AUDIO_FINGERPRINT_SIMILARITY_CONFIRMED = 0.90  # meme source confirmee
AUDIO_FINGERPRINT_SIMILARITY_PROBABLE = 0.75  # meme source probable
AUDIO_FINGERPRINT_SIMILARITY_POSSIBLE = 0.50  # meme film possible

# ---------------------------------------------------------------------------
# Scene detection (§4 v7.5.0)
# ---------------------------------------------------------------------------
SCENE_DETECTION_THRESHOLD = 0.3  # sweet spot films (doc FFmpeg)
SCENE_DETECTION_FPS_ANALYSIS = 2  # downsample temporel 5-10x
SCENE_DETECTION_SCALE_WIDTH = 640  # downsample spatial 2-3x pour 4K
SCENE_DETECTION_MAX_KEYFRAMES = 20  # cap films d'action
SCENE_DETECTION_MIN_FILE_DURATION_S = 180  # skip si court (overhead > benefice)
SCENE_DETECTION_TIMEOUT_S = 30  # securite anti-blocage
SCENE_DETECTION_HYBRID_RATIO = 0.5  # 50% keyframes / 50% uniforme
SCENE_DETECTION_DEDUP_TOLERANCE_S = 15.0  # distance min entre uniforme et keyframe

# ---------------------------------------------------------------------------
# Spectral cutoff audio (§9 v7.5.0)
# ---------------------------------------------------------------------------
SPECTRAL_SEGMENT_OFFSET_S = 60  # debut segment (idem chromaprint)
SPECTRAL_SEGMENT_DURATION_S = 30  # duree analysee
SPECTRAL_SAMPLE_RATE = 48000  # resample target (Nyquist 24 kHz)
SPECTRAL_FFT_WINDOW_SIZE = 4096  # resolution ~11.7 Hz/bin
SPECTRAL_FFT_OVERLAP = 0.5  # overlap standard
SPECTRAL_ROLLOFF_PCT = 0.85  # spectral rolloff 85% d'energie
SPECTRAL_CUTOFF_LOSSLESS = 21500  # Hz : seuil lossless vrai
SPECTRAL_CUTOFF_LOSSY_HIGH = 19000  # Hz : seuil lossy haut (MP3 320, AAC 256)
SPECTRAL_CUTOFF_LOSSY_MID = 16500  # Hz : seuil lossy mid (MP3 192, AAC 128)
SPECTRAL_TIMEOUT_S = 15  # extraction + FFT rapides
SPECTRAL_MIN_RMS_DB = -50.0  # en dessous : silence

# ---------------------------------------------------------------------------
# SSIM self-referential (§13 v7.5.0) — detection fake 4K
# ---------------------------------------------------------------------------
SSIM_SELF_REF_SEGMENT_DURATION_S = 120  # 2 min au milieu du film
SSIM_SELF_REF_MIN_HEIGHT = 1800  # skip si non-4K (pas pertinent)
SSIM_SELF_REF_TIMEOUT_S = 45  # calcul ~10-15s typique
SSIM_SELF_REF_FAKE_THRESHOLD = 0.95  # >= : upscale fake probable
SSIM_SELF_REF_AMBIGUOUS_THRESHOLD = 0.90  # 0.90-0.95 : zone grise
SSIM_SELF_REF_NATIVE_THRESHOLD = 0.85  # < : 4K native (info seulement)

# ---------------------------------------------------------------------------
# DRC detection (§14 v7.5.0) — classification compression dynamique
# Utilise crest_factor (astats) + LRA (loudnorm) deja calcules.
# ---------------------------------------------------------------------------
DRC_CREST_CINEMA = 15.0  # dB : pleine dynamique cinema
DRC_CREST_STANDARD = 10.0  # dB : dynamique standard
DRC_LRA_CINEMA = 18.0  # LU : loudness range cinema
DRC_LRA_STANDARD = 10.0  # LU : loudness range standard

# ---------------------------------------------------------------------------
# HDR metadata (§5 v7.5.0) — classification + scoring qualite HDR
# ---------------------------------------------------------------------------
HDR_MAX_CLL_WARNING_THRESHOLD = 500.0  # < : hdr_low_punch (HDR10 declare)
HDR_MAX_CLL_TYPICAL_MIN = 1000.0  # cible normale films HDR
HDR_MAX_FALL_TYPICAL = 100.0  # cible normale

HDR_QUALITY_SCORE = {
    "dolby_vision": 100,
    "hdr10_plus": 90,
    "hdr10_valid": 85,
    "hlg": 75,
    "hdr10_low_punch": 65,
    "hdr10_invalid": 50,
    "sdr": 40,
}

# ---------------------------------------------------------------------------
# Dolby Vision profiles (§6 v7.5.0) — classification des profils DV
# ---------------------------------------------------------------------------
DV_PROFILE_LABELS = {
    "5": "Dolby Vision Profile 5 (IPTPQc2 proprietary)",
    "7": "Dolby Vision Profile 7 (BL+EL+RPU)",
    "8.1": "Dolby Vision Profile 8.1 (HDR10 compatible)",
    "8.2": "Dolby Vision Profile 8.2 (SDR compatible)",
    "8.4": "Dolby Vision Profile 8.4 (HLG compatible)",
    "unknown": "Dolby Vision (profil non identifie)",
    "none": "Pas de Dolby Vision",
}

DV_COMPAT_RANKING = {
    "hdr10_full": 3,
    "hlg": 2,
    "hdr10_partial": 2,
    "sdr": 1,
    "none": 0,
}

DV_PROFILE_WARNINGS_FR = {
    "5": "Player Dolby Vision requis pour couleurs correctes (fichier proprietary).",
    "7": "Fallback HDR10 ignore l'enhancement layer sur players non-DV.",
    "unknown": "Profil Dolby Vision non reconnu, comportement player imprevisible.",
}

DV_QUALITY_SCORE = {
    "8.1": 100,  # sweet spot : HDR10 full compatibility
    "7": 95,
    "8.4": 88,
    "8.2": 82,
    "5": 80,  # penalise car incompatible sans player DV
    "unknown": 75,
    "none": 0,
}

# ---------------------------------------------------------------------------
# Fake 4K / upscale detection via FFT 2D (§7 v7.5.0)
# ---------------------------------------------------------------------------
FAKE_4K_FFT_HF_CUTOFF_RATIO = 0.25  # dernier quart de Nyquist spatial
FAKE_4K_FFT_THRESHOLD_NATIVE = 0.18  # >= : 4K native
FAKE_4K_FFT_THRESHOLD_AMBIGUOUS = 0.08  # < : fake 4K bicubique
FAKE_4K_FFT_MIN_Y_AVG = 20.0  # skip frames trop sombres
FAKE_4K_FFT_MIN_VARIANCE = 200.0  # skip frames uniformes
FAKE_4K_MIN_HEIGHT = 1800  # skip si pas 4K

# ---------------------------------------------------------------------------
# §8 v7.5.0 — Interlacing / Crop / Judder / IMAX
# ---------------------------------------------------------------------------
# 8.1 Interlacing (idet)
IDET_SEGMENT_DURATION_S = 30
IDET_INTERLACE_RATIO_THRESHOLD = 0.3  # (tff+bff)/(tff+bff+prog) > 0.3 -> interlaced

# 8.2 Crop (cropdetect)
CROPDETECT_SEGMENT_DURATION_S = 60
CROPDETECT_LIMIT = 24  # luminance seuil pour considerer "noir"
CROPDETECT_ROUND = 16  # arrondi dimensions (compat codecs)

# 8.3 Judder (mpdecimate)
MPDECIMATE_SEGMENT_DURATION_S = 30
MPDECIMATE_JUDDER_LIGHT = 0.05  # ratio drop/(drop+keep) > ce seuil = judder leger
MPDECIMATE_JUDDER_PULLDOWN = 0.15  # telecinema 3:2 probable
MPDECIMATE_JUDDER_HEAVY = 0.25  # conversion framerate problematique

# 8.4 IMAX
IMAX_AR_FULL_FRAME_MIN = 1.40  # IMAX 70mm natif (rare)
IMAX_AR_FULL_FRAME_MAX = 1.46
IMAX_AR_DIGITAL_MIN = 1.88  # IMAX Digital (GT/Laser)
IMAX_AR_DIGITAL_MAX = 1.92
IMAX_EXPANSION_AR_DELTA = 0.3  # delta aspect ratio min entre segments pour expansion
IMAX_NATIVE_RESOLUTION_MIN_HEIGHT = 2600  # hauteur > 4K standard = scan haute def
IMAX_EXPANSION_SEGMENTS_COUNT = 3  # nb segments cropdetect pour detection expansion

# ---------------------------------------------------------------------------
# §15 v7.5.0 — Grain Intelligence v2 (section phare)
# ---------------------------------------------------------------------------

# Eres v2 — 6 bandes (year threshold exclusif, ex: < 1980 = 16mm_era)
GRAIN_ERA_V2 = {
    "16mm_era": 1980,
    "35mm_classic": 1999,
    "late_film": 2006,
    "transition": 2013,
    "digital_modern": 2021,
    "digital_hdr_era": 9999,
}

# Profils attendus par ere
GRAIN_PROFILE_BY_ERA_V2 = {
    "16mm_era": {
        "level_mean": 4.5,
        "level_tolerance": 1.5,
        "uniformity_max": 0.75,
        "texture_variance_baseline": 250.0,
    },
    "35mm_classic": {
        "level_mean": 3.0,
        "level_tolerance": 1.0,
        "uniformity_max": 0.80,
        "texture_variance_baseline": 180.0,
    },
    "late_film": {
        "level_mean": 2.0,
        "level_tolerance": 0.8,
        "uniformity_max": 0.82,
        "texture_variance_baseline": 150.0,
    },
    "transition": {
        "level_mean": 1.5,
        "level_tolerance": 1.0,
        "uniformity_max": 0.85,
        "texture_variance_baseline": 130.0,
    },
    "digital_modern": {
        "level_mean": 0.5,
        "level_tolerance": 0.5,
        "uniformity_max": 0.90,
        "texture_variance_baseline": 120.0,
    },
    "digital_hdr_era": {
        "level_mean": 0.3,
        "level_tolerance": 0.3,
        "uniformity_max": 0.92,
        "texture_variance_baseline": 140.0,
    },
    "large_format_classic": {
        "level_mean": 1.8,
        "level_tolerance": 0.8,
        "uniformity_max": 0.85,
        "texture_variance_baseline": 140.0,
    },
}

# Regles d'exception (matchees en ordre, specifique d'abord)
# Cles possibles : era (str ou "*"), era_any (liste), genres_any, companies_any,
#                  budget_min, budget_max, country, + champs signature
GRAIN_SIGNATURES_EXCEPTIONS = [
    # Animation : jamais de grain, tous ere confondus
    {
        "era": "*",
        "genres_any": ["Animation", "animation"],
        "level_mean": 0.0,
        "level_tolerance": 0.3,
        "uniformity_max": 0.95,
        "texture_variance_baseline": 80.0,
        "label": "animation_aplats",
    },
    # Pixar/Dreamworks/Disney animation : aplats parfaits (priorite animation)
    {
        "era": "*",
        "companies_any": ["Pixar", "Pixar Animation Studios", "DreamWorks Animation", "Walt Disney Animation Studios"],
        "level_mean": 0.0,
        "level_tolerance": 0.2,
        "uniformity_max": 0.95,
        "texture_variance_baseline": 70.0,
        "label": "major_animation_studio",
    },
    # Horror 16mm : grain eleve typique
    {
        "era": "16mm_era",
        "genres_any": ["Horror", "horror"],
        "level_mean": 4.8,
        "level_tolerance": 1.2,
        "uniformity_max": 0.70,
        "texture_variance_baseline": 280.0,
        "label": "16mm_horror_grain",
    },
    # Nolan digital era : grain intentionnel IMAX/70mm (Syncopy)
    {
        "era_any": ["digital_modern", "digital_hdr_era"],
        "companies_any": ["Syncopy"],
        "level_mean": 1.5,
        "level_tolerance": 0.8,
        "uniformity_max": 0.82,
        "texture_variance_baseline": 150.0,
        "label": "nolan_intentional_grain",
    },
    # A24 / Focus Features : esthetique grain intentionnel meme en digital
    {
        "era": "digital_modern",
        "companies_any": ["A24", "Focus Features"],
        "level_mean": 1.8,
        "level_tolerance": 1.0,
        "uniformity_max": 0.82,
        "texture_variance_baseline": 160.0,
        "label": "a24_filmic_aesthetic",
    },
]

# Classifier thresholds
GRAIN_TEMPORAL_CORR_AUTHENTIC = 0.2  # < : grain argentique (frames independantes)
GRAIN_TEMPORAL_CORR_ENCODE = 0.7  # > : encode noise (blocs preserves)
GRAIN_SPATIAL_LAG_PEAK_RATIO = 1.3  # pics lag8/16 vs lag1 -> encode DCT 8x8
GRAIN_CROSS_COLOR_CORR_AUTHENTIC = 0.6  # high = film grain (touche tous canaux)
GRAIN_NATURE_WEIGHT_TEMPORAL = 0.5
GRAIN_NATURE_WEIGHT_SPATIAL = 0.3
GRAIN_NATURE_WEIGHT_CROSS_COLOR = 0.2

# DNR partiel
DNR_PARTIAL_TEXTURE_RATIO = 0.7  # < : DNR partiel probable
DNR_PARTIAL_GRAIN_LEVEL_MAX = 1.5  # DNR partiel impossible si grain deja eleve

# AV1 AFGS1 bonus
GRAIN_AV1_AFGS1_BONUS = 15  # points visuel si encodage grain-respectueux

# Flat zones detection
FLAT_ZONE_VARIANCE_THRESHOLD = 100.0
FLAT_ZONE_BLOCK_SIZE = 16
FLAT_ZONE_MAX_COUNT = 20

# Texture zones (pour DNR partiel)
TEXTURE_ZONE_VARIANCE_MIN = 10.0
TEXTURE_ZONE_VARIANCE_MAX = 500.0

# ---------------------------------------------------------------------------
# §12 v7.5.0 — Mel spectrogram (4 analyses audio derivees)
# ---------------------------------------------------------------------------
MEL_N_FILTERS = 64  # standard analyse audio
MEL_FMIN = 0.0  # Hz
MEL_FMAX = 24000.0  # Hz (Nyquist a 48kHz SR)

# Soft clipping (detection via harmoniques)
MEL_SOFT_CLIP_HARMONICS_MIN_PCT = 5.0  # % frames normale (< = clean)
MEL_SOFT_CLIP_HARMONICS_WARN_PCT = 15.0
MEL_SOFT_CLIP_HARMONICS_SEVERE_PCT = 30.0

# MP3 shelf detection (signature 16 kHz)
MEL_MP3_SHELF_DROP_DB = 20.0  # drop minimum pour detecter shelf
MEL_MP3_SHELF_MIN_FRAMES_PCT = 70.0  # % frames avec drop

# AAC holes (trous spectraux bas bitrate)
MEL_AAC_HOLE_THRESHOLD_DB = -80.0  # < ce seuil = bande "trouee"
MEL_AAC_HOLE_RATIO_WARN = 0.05  # 5% bandes avec trous
MEL_AAC_HOLE_RATIO_SEVERE = 0.10  # 10% bandes
MEL_AAC_SYNTHETIC_VARIANCE_THRESHOLD = 0.05  # variance bandes synthetiques

# Ponderations score composite Mel (total = 100)
MEL_WEIGHT_SOFT_CLIP = 40
MEL_WEIGHT_MP3_SHELF = 20
MEL_WEIGHT_AAC_HOLES = 30
MEL_WEIGHT_FLATNESS = 10

# ---------------------------------------------------------------------------
# §11 v7.5.0 — LPIPS (Learned Perceptual Image Patch Similarity)
# ---------------------------------------------------------------------------
# Modele AlexNet converti en ONNX via scripts/convert_lpips_to_onnx.py.
# Inclus dans le bundle PyInstaller (cf CineSort.spec datas).
LPIPS_MODEL_PATH = "assets/models/lpips_alexnet.onnx"
LPIPS_INPUT_SIZE = 256  # modele entraine sur 256x256
LPIPS_N_FRAMES_PAIRS = 5  # mediane sur 5 paires de frames alignees
LPIPS_INFERENCE_TIMEOUT_S = 30

# Seuils de classification distance (0.0 = identique, 1.0 = tres different)
LPIPS_DISTANCE_IDENTICAL = 0.05
LPIPS_DISTANCE_VERY_SIMILAR = 0.15
LPIPS_DISTANCE_SIMILAR = 0.30
LPIPS_DISTANCE_DIFFERENT = 0.50

# ---------------------------------------------------------------------------
# §16 v7.5.0 — Score composite et visualisation V2
# ---------------------------------------------------------------------------

# Ponderations globales (total = 100)
GLOBAL_WEIGHT_VIDEO_V2 = 60
GLOBAL_WEIGHT_AUDIO_V2 = 35
GLOBAL_WEIGHT_COHERENCE_V2 = 5

# Ponderations video (total = 100)
VIDEO_WEIGHT_PERCEPTUAL = 50
VIDEO_WEIGHT_RESOLUTION = 20
VIDEO_WEIGHT_HDR = 15
VIDEO_WEIGHT_LPIPS = 15

# Ponderations audio (total = 100)
AUDIO_WEIGHT_PERCEPTUAL_V2 = 50
AUDIO_WEIGHT_SPECTRAL = 20
AUDIO_WEIGHT_DRC = 15
AUDIO_WEIGHT_CHROMAPRINT = 5
AUDIO_WEIGHT_RESERVE = 10  # extensions futures (NR-VMAF custom, etc.)

# Ponderations coherence (total = 100)
COHERENCE_WEIGHT_RUNTIME = 60
COHERENCE_WEIGHT_NFO = 40

# Tiers v2 (aligne avec maquette Platinum/Gold/Silver/Bronze/Reject)
TIER_PLATINUM_THRESHOLD = 90
TIER_GOLD_THRESHOLD = 80
TIER_SILVER_THRESHOLD = 65
TIER_BRONZE_THRESHOLD = 50
# < 50 = reject

TIER_V2_LABELS = {
    "platinum": "Platinum",
    "gold": "Gold",
    "silver": "Silver",
    "bronze": "Bronze",
    "reject": "Reject",
}

TIER_V2_COLORS = {
    "platinum": "#FFD700",  # or
    "gold": "#22C55E",  # vert
    "silver": "#3B82F6",  # bleu
    "bronze": "#F59E0B",  # orange
    "reject": "#EF4444",  # rouge
}

# Ajustements contextuels (pts +/-, appliques apres le calcul pondere)
ADJUSTMENT_GRAIN_FILM_BONUS = 10
ADJUSTMENT_GRAIN_PARTIAL_DNR_MALUS = -15
ADJUSTMENT_GRAIN_ENCODE_NOISE_MALUS = -8
ADJUSTMENT_AV1_AFGS1_BONUS = 15
ADJUSTMENT_DV_PROFILE_5_MALUS = -8
ADJUSTMENT_HDR_METADATA_MISSING_MALUS = -10
ADJUSTMENT_IMAX_EXPANSION_BONUS = 15
ADJUSTMENT_IMAX_TYPED_BONUS = 10
ADJUSTMENT_FAKE_LOSSLESS_MALUS = -10

# Seuils warnings top-level
CATEGORY_IMBALANCE_WARN_DELTA = 40  # delta video-audio > 40 → warning
CONFIDENCE_LOW_WARN_THRESHOLD = 0.60  # confidence < 60% → warning "analyse partielle"
SHORT_FILE_WARN_DURATION_S = 90  # fichier < 90s → confidence reduite
