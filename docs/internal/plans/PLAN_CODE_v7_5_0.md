# PLAN DE CODE — v7.5.0

**Date de début :** 2026-04-22
**But :** spec technique précise, construite à partir des findings de [NOTES_RECHERCHE_v7_5_0.md](NOTES_RECHERCHE_v7_5_0.md).

**Utilisation :**
- Chaque section est écrite APRÈS la recherche correspondante, pas avant.
- Une fois une section écrite ici, elle est prête à être codée sans ambiguïté.
- Ce fichier remplace les "Fichiers touchés / Nouvelles fonctions" génériques de [PLAN_v7_5_0.md](PLAN_v7_5_0.md) par des specs beaucoup plus précises (signatures exactes, ordre, seuils, cas limites).

**Structure de chaque section** :
- **Prérequis** : dépendances sur d'autres sections déjà implémentées
- **Fichiers touchés** : chemins précis, lignes concernées si modif
- **Signatures exactes** : types, paramètres, retours
- **Seuils et constantes** : valeurs numériques issues de la recherche
- **Ordre d'implémentation** : étape 1, 2, 3…
- **Tests à écrire** : nominaux + cas limites spécifiques
- **Effort réévalué** : chiffre précis basé sur la recherche

**Légende des statuts** :
- 🔜 À CODER (plan prêt, recherche terminée)
- 🔄 EN COURS
- ✅ IMPLÉMENTÉ
- ⏸️ EN ATTENTE (recherche non terminée)

---

## Vague 1 — Fondations

### §1 — Parallélisme et performance ✅

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §1](NOTES_RECHERCHE_v7_5_0.md#§1--parallélisme-et-performance-)

**Prérequis :** aucun (c'est la fondation).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : ajout de 4 constantes parallélisme.
- [cinesort/domain/perceptual/parallelism.py](../../../cinesort/domain/perceptual/parallelism.py) : **nouveau module** (résolution `max_workers`, helpers `ThreadPoolExecutor`, gestion cancel).
- [cinesort/ui/api/perceptual_support.py](../../../cinesort/ui/api/perceptual_support.py) : refactor `_execute_perceptual_analysis` pour utiliser le ThreadPool (lignes 97-187).
- [cinesort/ui/api/settings_support.py](../../../cinesort/ui/api/settings_support.py) : ajout du setting `perceptual_parallelism_mode`.
- [cinesort/ui/api/cinesort_api.py](../../../cinesort/ui/api/cinesort_api.py) : propagation du setting si nécessaire.

**Signatures exactes :**

```python
# cinesort/domain/perceptual/parallelism.py

from __future__ import annotations
import logging
import os
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import Callable, Iterable, Optional, TypeVar

from .constants import (
    PARALLELISM_MAX_WORKERS_SINGLE_FILM,
    PARALLELISM_MAX_WORKERS_DEEP_COMPARE,
    PARALLELISM_MIN_CPU_CORES,
    PARALLELISM_AUTO_FACTOR,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


def resolve_max_workers(
    mode: str,
    intent: str,
    cpu_count: Optional[int] = None,
) -> int:
    """Résout le nombre de workers selon le mode et l'intention.

    Args:
        mode: "auto" | "max" | "safe" | "serial".
        intent: "single_film" (2 workers max attendus) ou "deep_compare" (4 max).
        cpu_count: None = os.cpu_count(). Injection pour tests.

    Returns:
        Entier >= 1. Jamais 0.
    """


def run_parallel_tasks(
    tasks: dict[str, Callable[[], T]],
    max_workers: int,
    timeout_per_task_s: Optional[float] = None,
    cancel_event: Optional["threading.Event"] = None,
) -> dict[str, tuple[bool, T | Exception]]:
    """Exécute N tâches en parallèle et retourne leurs résultats.

    Args:
        tasks: mapping {nom_tache: callable_zero_arg}.
        max_workers: taille du pool.
        timeout_per_task_s: timeout par tâche individuelle (None = pas de timeout).
        cancel_event: threading.Event pour annulation coopérative.

    Returns:
        Mapping {nom_tache: (succes, resultat_ou_exception)}.
        Tâches annulées = (False, CancelledError).
        Exceptions capturées et loggées.
    """
```

```python
# cinesort/domain/perceptual/constants.py (ajouts)

PARALLELISM_MAX_WORKERS_SINGLE_FILM = 2       # video + audio en parallèle
PARALLELISM_MAX_WORKERS_DEEP_COMPARE = 4      # A-video, A-audio, B-video, B-audio
PARALLELISM_MIN_CPU_CORES = 4                 # en dessous : fallback serial
PARALLELISM_AUTO_FACTOR = 2                   # workers = cpu_count // factor
```

```python
# settings_support.py : ajout dans DEFAULT_SETTINGS
"perceptual_parallelism_mode": "auto",  # "auto" | "max" | "safe" | "serial"
```

**Seuils et constantes :**

| Constante | Valeur | Source |
|---|---|---|
| `PARALLELISM_MAX_WORKERS_SINGLE_FILM` | 2 | Décision §1 (video + audio) |
| `PARALLELISM_MAX_WORKERS_DEEP_COMPARE` | 4 | Décision §1 (2 films × 2 streams) |
| `PARALLELISM_MIN_CPU_CORES` | 4 | Analyse distribution CPU + safety margin |
| `PARALLELISM_AUTO_FACTOR` | 2 | Laisse la moitié des cœurs pour l'OS/autres apps |

**Table de résolution `resolve_max_workers`** :

| mode / intent | `cpu_count < 4` | `cpu_count = 4` | `cpu_count = 8` | `cpu_count = 16` |
|---|---|---|---|---|
| `serial` | 1 | 1 | 1 | 1 |
| `safe` | 1 | 2 | 2 | 2 |
| `auto` + `single_film` | 1 | 2 | 2 | 2 (capped) |
| `auto` + `deep_compare` | 1 | 2 | 4 | 4 (capped) |
| `max` + `single_film` | 2 | 2 | 2 | 2 |
| `max` + `deep_compare` | 4 | 4 | 4 | 4 |

**Ordre d'implémentation :**

1. **Étape 1 — Constantes** : ajouter les 4 constantes dans `perceptual/constants.py` (5 min).
2. **Étape 2 — Module parallelism.py** : créer avec `resolve_max_workers()` + `run_parallel_tasks()` (45 min).
3. **Étape 3 — Setting** : ajouter `perceptual_parallelism_mode` dans `DEFAULT_SETTINGS` + validation normaliste (15 min).
4. **Étape 4 — Tests parallelism.py** : écrire les 8 tests **AVANT** d'intégrer (1 h).
5. **Étape 5 — Refactor `_execute_perceptual_analysis`** : intégration ThreadPool avec 2 tâches (video + audio) (45 min).
6. **Étape 6 — Gestion cancel** : intégrer `JobRunner.should_cancel` via `cancel_event` (20 min).
7. **Étape 7 — Tests intégration** : 4 tests bout-en-bout (30 min).
8. **Étape 8 — Bench empirique** : `scripts/bench_perceptual_parallel.py` sur 3 fichiers de tailles variées (30 min).

**Tests à écrire :**

```python
# tests/test_perceptual_parallel.py

class TestResolveMaxWorkers(unittest.TestCase):
    def test_serial_always_one(self): ...
    def test_safe_mode_caps_at_2(self): ...
    def test_auto_single_film_uses_half_cpu(self): ...
    def test_auto_deep_compare_scales_to_4(self): ...
    def test_low_cpu_fallback_to_1(self): ...  # cpu_count < PARALLELISM_MIN_CPU_CORES
    def test_max_mode_ignores_cpu_count(self): ...

class TestRunParallelTasks(unittest.TestCase):
    def test_all_tasks_succeed(self): ...
    def test_one_task_raises_others_still_run(self): ...
    def test_cancel_event_aborts_pending(self): ...
    def test_timeout_per_task_isolates_slow_tasks(self): ...

class TestPerceptualAnalysisParallel(unittest.TestCase):
    def test_video_and_audio_run_in_parallel(self): ...  # mock ffmpeg, mesurer temps
    def test_fallback_serial_when_mode_serial(self): ...
    def test_cancel_during_analysis_stops_cleanly(self): ...
    def test_setting_max_workers_mode_persisted(self): ...
```

**Cas limites à tester explicitement :**

- `cpu_count() = None` (retour de Python sur certains systèmes virtualisés) → fallback 1.
- Tâche lève `SystemExit` ou `KeyboardInterrupt` → propagation propre.
- `ThreadPoolExecutor.shutdown(cancel_futures=True)` fonctionne sur Python 3.13 (ajouté en 3.9).
- Mode invalide (ex: "wrong_mode") → fallback "auto" + log warning.

**Effort réévalué :** **4h30** (plus précis que les 3h initiales, car on a ajouté le module dédié + setting + tests).

**Note packaging :** aucune nouvelle dépendance externe, aucun modèle embarqué. [CineSort.spec](../../../CineSort.spec) à mettre à jour simplement pour ajouter `cinesort.domain.perceptual.parallelism` aux `hiddenimports`.

---

### §2 — GPU hardware acceleration 📦 REPORTÉ v7.6.0

**Statut :** reporté en v7.6.0 par décision utilisateur (2026-04-22). Gain réel 15-25% insuffisant vs effort 6h. §1 Parallélisme apporte 2.5x, priorité donnée aux briques fonctionnelles V2-V5. Le plan de code reste rédigé ci-dessous pour reprise en v7.6.0.

**Entrée correspondante dans [BACKLOG_v7_5_0.md §Performance](BACKLOG_v7_5_0.md#4-performance-et-scalabilité).**

---

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §2](NOTES_RECHERCHE_v7_5_0.md#§2--gpu-hardware-acceleration-📦-reporté-v760)

**⚠️ Statut stratégique** : priorité **P2 (basse)** pour v7.5.0. Gain réel estimé 15-25% **uniquement** sur machines avec GPU compatible, opt-in. Peut être repoussé en v7.6.0 si pression de temps. **§1 Parallélisme apporte 2.5x**, §2 apporte au mieux 1.25x.

**Prérequis :** §1 Parallélisme terminé et stable. La hwaccel s'ajoute par-dessus, pas avant.

**Fichiers touchés :**
- [cinesort/domain/perceptual/hwaccel.py](../../../cinesort/domain/perceptual/hwaccel.py) : **nouveau module** (détection + smoke test + cache).
- [cinesort/domain/perceptual/ffmpeg_runner.py](../../../cinesort/domain/perceptual/ffmpeg_runner.py) : ajout d'un helper `build_hwaccel_args(hwaccel_mode)` qui retourne les arguments CLI à préfixer.
- [cinesort/domain/perceptual/frame_extraction.py](../../../cinesort/domain/perceptual/frame_extraction.py) : intégration des args hwaccel dans la commande ffmpeg d'extraction (SEULEMENT ici, pas ailleurs).
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : ajout des constantes hwaccel.
- [cinesort/ui/api/settings_support.py](../../../cinesort/ui/api/settings_support.py) : ajout du setting `perceptual_hwaccel` + validation.
- [web/index.html](../../../web/index.html) + [web/views/settings.js](../../../web/views/settings.js) : ajout du toggle + dropdown.
- [web/dashboard/views/settings.js](../../../web/dashboard/views/settings.js) : pareil côté dashboard.

**Signatures exactes :**

```python
# cinesort/domain/perceptual/hwaccel.py

from __future__ import annotations
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

from .ffmpeg_runner import run_ffmpeg_text
from .constants import (
    HWACCEL_SMOKE_TEST_TIMEOUT_S,
    HWACCEL_AUTO_PRIORITY_WINDOWS,
    HWACCEL_AUTO_PRIORITY_LINUX,
    HWACCEL_AUTO_PRIORITY_MACOS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HwaccelStatus:
    compiled_methods: tuple[str, ...]   # depuis `ffmpeg -hwaccels`
    tested_methods: dict[str, bool]     # méthode -> fonctionne ou non
    selected: Optional[str]              # méthode choisie, ou None si CPU
    detection_error: Optional[str]       # si erreur au detect


def detect_compiled_hwaccels(ffmpeg_path: str, timeout_s: float = 5.0) -> list[str]:
    """Liste les hwaccels compilés dans le binaire ffmpeg.

    Ne garantit PAS qu'ils fonctionnent sur la machine — voir smoke_test_hwaccel.
    Returns: liste triée, ou [] si erreur/timeout.
    """


def smoke_test_hwaccel(
    ffmpeg_path: str,
    hwaccel: str,
    sample_media_path: Optional[str] = None,
    timeout_s: float = HWACCEL_SMOKE_TEST_TIMEOUT_S,
) -> bool:
    """Teste si un hwaccel fonctionne réellement en décodant 1 s d'une source simple.

    Si sample_media_path=None, utilise une source synthétique (`testsrc`) :
    ```
    ffmpeg -hwaccel {hw} -f lavfi -i testsrc=duration=1:size=320x240:rate=10 -f null -
    ```
    Returns: True si decode réussi, False sinon.
    """


def resolve_hwaccel(
    mode: str,                         # "none" | "auto" | "cuda" | "qsv" | "dxva2" | ...
    ffmpeg_path: str,
    cache: Optional[HwaccelStatus] = None,
) -> Optional[str]:
    """Résout quelle hwaccel utiliser en fonction du mode demandé et de la plateforme.

    Si mode='auto' : itère la liste prioritaire OS, prend la première qui passe le smoke test.
    Si mode explicite : valide avec smoke test avant retour (ou None si échec).
    Si mode='none' : retourne None immédiatement.

    Returns: nom du hwaccel ou None (= CPU).
    """


def build_hwaccel_args(selected: Optional[str]) -> list[str]:
    """Construit les args CLI à insérer AVANT `-i <file>`.

    Exemples :
      - selected=None → []
      - selected="cuda" → ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]
      - selected="qsv" → ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"]
      - selected="dxva2" → ["-hwaccel", "dxva2"]
    """
```

```python
# cinesort/domain/perceptual/constants.py (ajouts)

# Hardware acceleration
HWACCEL_SMOKE_TEST_FILE_SIZE_MAX_MB = 10
HWACCEL_SMOKE_TEST_TIMEOUT_S = 10
HWACCEL_AUTO_PRIORITY_WINDOWS = ("cuda", "qsv", "d3d11va", "dxva2")
HWACCEL_AUTO_PRIORITY_LINUX = ("cuda", "vaapi")
HWACCEL_AUTO_PRIORITY_MACOS = ("videotoolbox",)
HWACCEL_DEFAULT_MODE = "none"
HWACCEL_SUPPORTED_MODES = ("none", "auto", "cuda", "qsv", "dxva2", "d3d11va", "vaapi", "videotoolbox")
```

```python
# settings_support.py : ajout
"perceptual_hwaccel": HWACCEL_DEFAULT_MODE,  # opt-in, "none" par défaut
```

```python
# frame_extraction.py : modification de la commande ffmpeg
# AVANT :
#   cmd = [ffmpeg_path, "-ss", str(ts), "-i", media_path, "-vframes", "1", ...]
# APRÈS :
#   hw_args = build_hwaccel_args(selected_hwaccel)
#   cmd = [ffmpeg_path, *hw_args, "-ss", str(ts), "-i", media_path, "-vframes", "1", ...]
```

**Seuils et constantes :**

| Constante | Valeur | Rôle |
|---|---|---|
| `HWACCEL_SMOKE_TEST_TIMEOUT_S` | 10 s | Timeout bref pour test rapide |
| `HWACCEL_AUTO_PRIORITY_WINDOWS` | `("cuda", "qsv", "d3d11va", "dxva2")` | Ordre préférentiel |
| `HWACCEL_DEFAULT_MODE` | `"none"` | Pas activé par défaut (opt-in utilisateur) |

**Ordre d'implémentation :**

1. **Étape 1 — Constantes** : ajouter dans `perceptual/constants.py` (5 min).
2. **Étape 2 — Module hwaccel.py** : créer avec les 4 fonctions publiques (1 h).
3. **Étape 3 — Tests hwaccel.py** : écrire **AVANT** intégration, avec mocks pour les sorties ffmpeg (1 h).
4. **Étape 4 — Setting + validation** : ajouter dans DEFAULT_SETTINGS + `_normalize_settings` (15 min).
5. **Étape 5 — Intégration frame_extraction.py** : injecter `build_hwaccel_args()` dans la construction de commande (30 min).
6. **Étape 6 — Init cache au démarrage app** : appel unique `detect_compiled_hwaccels()` dans `CineSortApi.__init__` avec cache stocké dans `self._hwaccel_status` (15 min).
7. **Étape 7 — UI desktop** : ajout section "Accélération GPU" dans réglages perceptuels avec dropdown 5 options + bouton "Tester" qui lance un smoke test live (1 h).
8. **Étape 8 — UI dashboard** : parité desktop (30 min).
9. **Étape 9 — Documentation inline** : tooltip "Expérimental. Gain 10-20% si GPU compatible. Désactivez si erreurs." (5 min).
10. **Étape 10 — Test d'intégration** : test bout-en-bout avec mock subprocess (30 min).

**Tests à écrire :**

```python
# tests/test_perceptual_hwaccel.py

class TestDetectCompiledHwaccels(unittest.TestCase):
    def test_parse_cuda_d3d11va_dxva2(self): ...       # sortie Windows typique
    def test_empty_list_returns_empty(self): ...        # ffmpeg sans hwaccel
    def test_ffmpeg_error_returns_empty(self): ...      # mock retourne stderr erreur
    def test_timeout_returns_empty(self): ...           # TimeoutExpired
    def test_parsing_tolerant_to_whitespace(self): ...

class TestSmokeTestHwaccel(unittest.TestCase):
    def test_synthetic_testsrc_cuda_success(self): ...  # mock returncode=0
    def test_synthetic_testsrc_cuda_failure(self): ...  # mock returncode!=0
    def test_smoke_timeout_returns_false(self): ...

class TestResolveHwaccel(unittest.TestCase):
    def test_mode_none_returns_none(self): ...
    def test_mode_auto_picks_first_working(self): ...
    def test_mode_auto_all_fail_returns_none(self): ...
    def test_explicit_mode_validates(self): ...
    def test_explicit_mode_fails_returns_none(self): ...
    def test_invalid_mode_fallback_to_none_warns(self): ...

class TestBuildHwaccelArgs(unittest.TestCase):
    def test_none_returns_empty(self): ...
    def test_cuda_returns_hwaccel_and_output_format(self): ...
    def test_dxva2_returns_only_hwaccel_no_output_format(self): ...

class TestIntegrationFrameExtraction(unittest.TestCase):
    def test_extraction_with_hwaccel_prefixes_args(self): ...
    def test_extraction_falls_back_to_cpu_on_hwaccel_error(self): ...
```

**Cas limites à tester explicitement :**

- Machine sans GPU : `mode="auto"` → retourne `None`, pas d'erreur.
- Machine avec `cuda` compilé mais driver absent : smoke test échoue, fallback CPU.
- Chemin ffmpeg invalide : `detect_compiled_hwaccels` retourne `[]`.
- User bascule setting en cours d'utilisation : prendre en compte au prochain scan, pas au milieu d'une analyse en cours.
- Smoke test avec fichier utilisateur réel (pas testsrc) : optionnel, plus robuste mais plus lent.

**Effort réévalué :** **6h** (5h initial + 1h pour la détection cache + UI test button).

**Note packaging :** pas de dépendance nouvelle. Ajouter `cinesort.domain.perceptual.hwaccel` aux `hiddenimports` de [CineSort.spec](../../../CineSort.spec).

**Si cette section est repoussée en v7.6.0 :** aucun impact sur les autres sections (indépendante du parallélisme §1 et des briques fonctionnelles V2-V6).

---

## Vague 2 — Briques indépendantes

### §3 — Chromaprint / AcoustID ✅

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §3](NOTES_RECHERCHE_v7_5_0.md#§3--chromaprint--acoustid-)

**Prérequis :** §1 Parallélisme (car le fingerprint est une étape supplémentaire dans le pipeline audio qui doit rester en parallèle avec la vidéo).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : ajout de 7 constantes fingerprint.
- [cinesort/domain/perceptual/models.py](../../../cinesort/domain/perceptual/models.py) : ajout du champ `audio_fingerprint: Optional[str]` dans `AudioPerceptual`.
- [cinesort/domain/perceptual/audio_fingerprint.py](../../../cinesort/domain/perceptual/audio_fingerprint.py) : **nouveau module** (fpcalc path + fingerprint + comparaison).
- [cinesort/domain/perceptual/audio_perceptual.py](../../../cinesort/domain/perceptual/audio_perceptual.py) : intégration du fingerprint en fin de `analyze_audio_perceptual()`.
- [cinesort/infra/db/migrations/016_audio_fingerprint.sql](../../../cinesort/infra/db/migrations/016_audio_fingerprint.sql) : **nouvelle migration** ajoutant colonne `audio_fingerprint` à `quality_reports`.
- [cinesort/ui/api/settings_support.py](../../../cinesort/ui/api/settings_support.py) : ajout setting `perceptual_audio_fingerprint_enabled` (défaut `True`).
- [requirements.txt](../../../requirements.txt) : ajout `pyacoustid>=1.3.1`.
- [CineSort.spec](../../../CineSort.spec) : ajout de `assets/tools/fpcalc.exe` dans les `datas` + ajout module aux `hiddenimports`.
- `assets/tools/fpcalc.exe` : **nouveau binaire** téléchargé depuis [acoustid.org](https://acoustid.org/chromaprint).

**Signatures exactes :**

```python
# cinesort/domain/perceptual/audio_fingerprint.py

from __future__ import annotations
import base64
import logging
import os
import struct
from pathlib import Path
from typing import Optional

from .constants import (
    AUDIO_FINGERPRINT_SEGMENT_OFFSET_S,
    AUDIO_FINGERPRINT_SEGMENT_DURATION_S,
    AUDIO_FINGERPRINT_MIN_FILE_DURATION_S,
    AUDIO_FINGERPRINT_TIMEOUT_S,
    AUDIO_FINGERPRINT_SIMILARITY_CONFIRMED,
    AUDIO_FINGERPRINT_SIMILARITY_PROBABLE,
    AUDIO_FINGERPRINT_SIMILARITY_POSSIBLE,
)

logger = logging.getLogger(__name__)


def resolve_fpcalc_path() -> Optional[str]:
    """Trouve fpcalc.exe : embarqué d'abord, système ensuite.

    Returns: chemin absolu ou None si introuvable.
    """


def compute_audio_fingerprint(
    media_path: str,
    duration_s: float,
    fpcalc_path: Optional[str] = None,
    timeout_s: float = AUDIO_FINGERPRINT_TIMEOUT_S,
) -> Optional[str]:
    """Calcule le fingerprint Chromaprint d'un segment audio.

    Args:
        media_path: chemin du fichier video/audio.
        duration_s: durée totale du fichier (pour décider offset).
        fpcalc_path: None = auto-détection via resolve_fpcalc_path.
        timeout_s: timeout du sous-process fpcalc.

    Returns:
        Fingerprint encodé base64 (chaîne compacte), ou None en cas d'erreur.
        Format base64 de la représentation binaire : 4 bytes little-endian par entier 32-bit.

    Stratégie de segment :
        - Si duration_s < AUDIO_FINGERPRINT_MIN_FILE_DURATION_S (180s) : tout le fichier.
        - Sinon : segment [OFFSET=60s, DURATION=120s].

    Robustesse :
        - Capture les erreurs fpcalc (fichier corrompu, audio absent) et retourne None.
        - Logger warning si échec, ne bloque pas l'analyse audio.
    """


def compare_audio_fingerprints(fp_a: Optional[str], fp_b: Optional[str]) -> Optional[float]:
    """Compare 2 fingerprints Chromaprint.

    Returns:
        Similarité 0.0-1.0, ou None si l'un des fingerprints est None ou mal formé.

    Algorithme :
        1. Décode base64 → tableau d'entiers 32-bit.
        2. Aligne sur la longueur commune minimale.
        3. Calcule la distance de Hamming : sum(popcount(a[i] ^ b[i])).
        4. Normalise par total_bits = len * 32.
        5. Retourne 1.0 - (hamming / total_bits).
    """


def classify_fingerprint_similarity(similarity: Optional[float]) -> str:
    """Classifie une similarité en verdict humain-lisible.

    Returns:
        "confirmed" (>= 0.90) | "probable" (>= 0.75) | "possible" (>= 0.50) |
        "different" (< 0.50) | "unknown" (similarity is None).
    """


# --- Helpers internes ---

def _encode_fingerprint(fp_ints: list[int]) -> str:
    """Encode une liste d'entiers 32-bit en base64 compact."""


def _decode_fingerprint(fp_b64: str) -> list[int]:
    """Décode une chaîne base64 en liste d'entiers 32-bit."""


def _hamming_distance_u32(a: int, b: int) -> int:
    """Distance de Hamming entre 2 entiers 32-bit (popcount XOR)."""
    return bin(a ^ b).count("1")  # stdlib, efficace en Python 3.13
```

```python
# cinesort/domain/perceptual/models.py — ajout dans AudioPerceptual

@dataclass
class AudioPerceptual:
    # ... champs existants ...
    audio_fingerprint: Optional[str] = None      # base64 du fingerprint Chromaprint
    fingerprint_source: str = "none"             # "fpcalc" | "none" | "error"
```

```python
# cinesort/domain/perceptual/constants.py (ajouts)

AUDIO_FINGERPRINT_SEGMENT_OFFSET_S = 60
AUDIO_FINGERPRINT_SEGMENT_DURATION_S = 120
AUDIO_FINGERPRINT_MIN_FILE_DURATION_S = 180
AUDIO_FINGERPRINT_TIMEOUT_S = 30
AUDIO_FINGERPRINT_SIMILARITY_CONFIRMED = 0.90
AUDIO_FINGERPRINT_SIMILARITY_PROBABLE = 0.75
AUDIO_FINGERPRINT_SIMILARITY_POSSIBLE = 0.50
```

```python
# audio_perceptual.py — ajout en fin de analyze_audio_perceptual()

# --- Fingerprint (si activé) ---
if settings.get("perceptual_audio_fingerprint_enabled", True):
    fpcalc = resolve_fpcalc_path()
    if fpcalc:
        duration_s = _get_duration_from_astats_or_probe(astats_data)
        fp = compute_audio_fingerprint(media_path, duration_s, fpcalc_path=fpcalc)
        if fp:
            result.audio_fingerprint = fp
            result.fingerprint_source = "fpcalc"
        else:
            result.fingerprint_source = "error"
    else:
        logger.warning("fpcalc.exe introuvable — fingerprint audio désactivé pour cette analyse")
        result.fingerprint_source = "none"
```

```sql
-- cinesort/infra/db/migrations/016_audio_fingerprint.sql
ALTER TABLE quality_reports ADD COLUMN audio_fingerprint TEXT;
-- Index pour comparaison future sur grandes bibliothèques (optionnel)
-- CREATE INDEX IF NOT EXISTS idx_quality_reports_audio_fingerprint
--   ON quality_reports(audio_fingerprint) WHERE audio_fingerprint IS NOT NULL;
```

**Seuils et constantes :**

| Constante | Valeur | Source |
|---|---|---|
| `AUDIO_FINGERPRINT_SEGMENT_OFFSET_S` | 60 s | Évite générique / logos |
| `AUDIO_FINGERPRINT_SEGMENT_DURATION_S` | 120 s | Bon compromis signal/temps |
| `AUDIO_FINGERPRINT_MIN_FILE_DURATION_S` | 180 s | En dessous : tout le fichier |
| `AUDIO_FINGERPRINT_TIMEOUT_S` | 30 s | Sécurité anti-blocage |
| `AUDIO_FINGERPRINT_SIMILARITY_CONFIRMED` | 0.90 | Même source confirmée |
| `AUDIO_FINGERPRINT_SIMILARITY_PROBABLE` | 0.75 | Même source probable |
| `AUDIO_FINGERPRINT_SIMILARITY_POSSIBLE` | 0.50 | Même film possible |

**Ordre d'implémentation :**

1. **Étape 1 — Dépendance** : ajouter `pyacoustid>=1.3.1` dans `requirements.txt` (1 min).
2. **Étape 2 — Binaire embarqué** : télécharger `fpcalc-1.5.1-windows-x86_64.zip` depuis [acoustid.org](https://acoustid.org/chromaprint), extraire `fpcalc.exe`, placer dans `assets/tools/fpcalc.exe` (5 min).
3. **Étape 3 — Constantes** : ajouter les 7 constantes dans `perceptual/constants.py` (5 min).
4. **Étape 4 — Migration SQL** : créer `016_audio_fingerprint.sql` (5 min).
5. **Étape 5 — Modèle** : ajouter champs `audio_fingerprint` + `fingerprint_source` dans `AudioPerceptual` (10 min).
6. **Étape 6 — Module fingerprint** : créer `audio_fingerprint.py` avec les 4 fonctions publiques + helpers (1 h 30).
7. **Étape 7 — Tests module** : écrire 8 tests AVANT intégration, avec fixtures d'audio connu (1 h).
8. **Étape 8 — Intégration dans `analyze_audio_perceptual`** : ajout du bloc fingerprint en fin de fonction, protégé par setting (30 min).
9. **Étape 9 — Setting** : ajouter `perceptual_audio_fingerprint_enabled` dans DEFAULT_SETTINGS (10 min).
10. **Étape 10 — CineSort.spec** : ajouter `assets/tools/fpcalc.exe` dans `datas` + `cinesort.domain.perceptual.audio_fingerprint` dans `hiddenimports` (15 min).
11. **Étape 11 — Tests intégration** : 4 tests bout-en-bout (mock fpcalc, cas erreur, cache hit) (30 min).
12. **Étape 12 — Corpus validation** : créer `tests/fixtures/audio_fingerprint/` avec 6 paires étiquetées (FLAC-FLAC, FLAC-MP3, FLAC-AAC, différents, silencieux, court), valider les seuils (1 h).

**Tests à écrire :**

```python
# tests/test_audio_fingerprint.py

class TestResolveFpcalcPath(unittest.TestCase):
    def test_finds_embedded_first(self): ...
    def test_fallback_to_system_path(self): ...
    def test_returns_none_if_absent(self): ...

class TestComputeAudioFingerprint(unittest.TestCase):
    def test_full_file_if_short(self): ...            # duration < 180s
    def test_segment_if_long(self): ...               # offset 60s, duration 120s
    def test_returns_none_on_fpcalc_error(self): ...
    def test_timeout_returns_none(self): ...
    def test_empty_audio_returns_none(self): ...
    def test_fingerprint_format_is_base64(self): ...

class TestCompareAudioFingerprints(unittest.TestCase):
    def test_identical_returns_1_0(self): ...
    def test_none_either_side_returns_none(self): ...
    def test_malformed_base64_returns_none(self): ...
    def test_different_lengths_aligned(self): ...     # prend min(len)
    def test_empty_fingerprints_returns_none(self): ...

class TestClassifyFingerprintSimilarity(unittest.TestCase):
    def test_095_returns_confirmed(self): ...
    def test_080_returns_probable(self): ...
    def test_060_returns_possible(self): ...
    def test_030_returns_different(self): ...
    def test_none_returns_unknown(self): ...

class TestFingerprintCorpus(unittest.TestCase):
    """Validation empirique seuils sur corpus réel."""
    def test_flac_vs_flac_similarity_gt_099(self): ...
    def test_flac_vs_mp3_320_similarity_gt_095(self): ...
    def test_flac_vs_mp3_128_similarity_gt_085(self): ...
    def test_different_films_similarity_lt_030(self): ...
    def test_silent_film_flagged_confidence_low(self): ...
    def test_short_film_uses_full_file(self): ...

class TestIntegrationAudioPerceptual(unittest.TestCase):
    def test_fingerprint_populated_in_audio_result(self): ...
    def test_setting_disabled_skips_fingerprint(self): ...
    def test_fpcalc_missing_logs_warning(self): ...
    def test_db_persists_fingerprint(self): ...
```

**Cas limites à tester explicitement :**

- `fpcalc.exe` absent : `resolve_fpcalc_path()` → None, fingerprint désactivé, pas d'erreur bloquante.
- Fichier audio corrompu : fpcalc retourne non-zéro, log warning, `audio_fingerprint = None`.
- Film silencieux : fingerprint généré mais très uniforme — flag `confidence_low` à ajouter dans un raffinement ultérieur (pas en §3 strict).
- Fichier < 3 minutes : segment = tout le fichier.
- Fichier audio inexistant (video-only) : analyse audio déjà skipped avant fingerprint, pas de régression.
- pyacoustid pas installé : ImportError catchée au module load, `resolve_fpcalc_path` retourne None, log warning.

**Effort réévalué :** **5h** (4h dev + 1h validation corpus).

**Note packaging :**
- Nouvelle dépendance Python : `pyacoustid>=1.3.1` (~100 KB wheel).
- Nouveau binaire embarqué : `fpcalc.exe` Windows x64 (~3 MB).
- Impact bundle EXE : **+3.5 MB** approx (négligeable vs 16 MB actuel).
- Mise à jour `CineSort.spec` :
  ```python
  datas += [("assets/tools/fpcalc.exe", "assets/tools/")]
  hiddenimports += ["cinesort.domain.perceptual.audio_fingerprint", "acoustid", "chromaprint"]
  ```

**Utilisation dans la comparaison deep-compare (Phase 4) :**

Dans `build_comparison_report` :
```python
fp_sim = compare_audio_fingerprints(result_a.audio_fingerprint, result_b.audio_fingerprint)
verdict = classify_fingerprint_similarity(fp_sim)
# Poids 10% dans le score composite audio.
# Si "confirmed" et résultats LPIPS disent aussi similaire vidéo → message UI :
#   "Les 2 fichiers ont la même source confirmée par empreinte audio."
```

---

### §4 — Scene detection ✅

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §4](NOTES_RECHERCHE_v7_5_0.md#§4--scene-detection-)

**Prérequis :** §1 Parallélisme (pour intégrer la scene detection dans le pipeline sans ralentir la vidéo).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : ajout de 7 constantes.
- [cinesort/domain/perceptual/scene_detection.py](../../../cinesort/domain/perceptual/scene_detection.py) : **nouveau module**.
- [cinesort/domain/perceptual/frame_extraction.py](../../../cinesort/domain/perceptual/frame_extraction.py) : ajout fonction `compute_timestamps_hybrid()`, intégration dans `extract_representative_frames()`.
- [cinesort/ui/api/settings_support.py](../../../cinesort/ui/api/settings_support.py) : ajout setting `perceptual_scene_detection_enabled` (défaut `True`).
- [CineSort.spec](../../../CineSort.spec) : ajout `cinesort.domain.perceptual.scene_detection` aux `hiddenimports`.

**Signatures exactes :**

```python
# cinesort/domain/perceptual/scene_detection.py

from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from .constants import (
    SCENE_DETECTION_THRESHOLD,
    SCENE_DETECTION_FPS_ANALYSIS,
    SCENE_DETECTION_SCALE_WIDTH,
    SCENE_DETECTION_MAX_KEYFRAMES,
    SCENE_DETECTION_TIMEOUT_S,
)
from .ffmpeg_runner import run_ffmpeg_text

logger = logging.getLogger(__name__)

# Regex pour parser la sortie showinfo
_RE_SCENE = re.compile(r"pts_time:(\d+\.?\d*)\s+.*?scene[_:]([-\d.]+)")


@dataclass(frozen=True)
class SceneKeyframe:
    timestamp_s: float
    score: float                    # scene_score de ffmpeg (0.0-1.0)


def detect_scene_keyframes(
    ffmpeg_path: str,
    media_path: str,
    threshold: float = SCENE_DETECTION_THRESHOLD,
    fps_analysis: int = SCENE_DETECTION_FPS_ANALYSIS,
    scale_width: int = SCENE_DETECTION_SCALE_WIDTH,
    max_keyframes: int = SCENE_DETECTION_MAX_KEYFRAMES,
    timeout_s: float = SCENE_DETECTION_TIMEOUT_S,
) -> List[SceneKeyframe]:
    """Détecte les keyframes de changement de scène via ffmpeg.

    Utilise `-r fps_analysis -vf scale=scale_width:-1,select='gt(scene,threshold)',showinfo`.
    Parse stderr pour extraire (pts_time, scene_score).

    Returns:
        Liste triée par timestamp croissant, max `max_keyframes` entrées.
        Liste vide si échec ou aucun keyframe détecté.

    Stratégie :
        1. Lance ffmpeg avec downsampling temporel ET spatial pour perf.
        2. Parse stderr (robuste à variations de format).
        3. Si > max_keyframes : garde les `max_keyframes` avec meilleur score, re-trie par timestamp.
        4. Logger les métriques (nb détecté, durée analyse).
    """


def merge_hybrid_timestamps(
    uniform_timestamps: List[float],
    keyframes: List[SceneKeyframe],
    target_count: int,
    dedup_tolerance_s: float = 15.0,
    hybrid_ratio: float = 0.5,
) -> List[float]:
    """Fusionne timestamps uniformes et keyframes selon la stratégie hybride.

    Args:
        uniform_timestamps: liste actuelle (uniforme) de `compute_timestamps`.
        keyframes: scene keyframes détectées (peut être vide).
        target_count: nombre total de frames voulues au final.
        dedup_tolerance_s: distance minimale entre un uniforme et un keyframe.
        hybrid_ratio: proportion de keyframes (0.5 = 50%).

    Returns:
        Liste de timestamps mergés, triés croissant, `<=target_count` entrées.

    Stratégie :
        1. Si pas de keyframes : retourne uniform_timestamps inchangés.
        2. Sinon :
           - count_keyframes = int(target_count * hybrid_ratio)
           - count_uniform = target_count - count_keyframes
           - Pick les N meilleurs keyframes (score décroissant).
           - Pick les M uniform_timestamps les mieux répartis.
           - Merge, dédup par tolérance, tri, clamp à target_count.
    """


def should_skip_scene_detection(duration_s: float, setting_enabled: bool) -> bool:
    """True si on doit skip la scene detection (conditions).

    Raisons de skip :
        - setting désactivé par user
        - duration < SCENE_DETECTION_MIN_FILE_DURATION_S (180 s)
    """
```

```python
# cinesort/domain/perceptual/frame_extraction.py (modifications)

def extract_representative_frames(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    width: int,
    height: int,
    bit_depth: int = 8,
    *,
    frames_count: int = 10,
    skip_percent: int = 5,
    timeout_s: float = _FRAME_EXTRACT_TIMEOUT_S,
    scene_detection_enabled: bool = True,  # NOUVEAU
) -> List[Dict[str, Any]]:
    """(docstring existante enrichie...)"""
    # ... code existant pour validation ...

    # NOUVEAU : scene detection hybride
    uniform_ts = compute_timestamps(duration_s, frames_count, skip_percent)

    if scene_detection_enabled and not should_skip_scene_detection(duration_s, scene_detection_enabled):
        keyframes = detect_scene_keyframes(ffmpeg_path, media_path)
        if keyframes:
            timestamps = merge_hybrid_timestamps(uniform_ts, keyframes, target_count=frames_count)
            logger.info(
                "scene_detection: %d keyframes detected, %d merged timestamps",
                len(keyframes), len(timestamps),
            )
        else:
            timestamps = uniform_ts  # fallback
            logger.debug("scene_detection: 0 keyframes, fallback uniform")
    else:
        timestamps = uniform_ts

    # ... reste du code existant : extract pour chaque timestamp ...
```

```python
# cinesort/domain/perceptual/constants.py (ajouts)

SCENE_DETECTION_THRESHOLD = 0.3
SCENE_DETECTION_FPS_ANALYSIS = 2
SCENE_DETECTION_SCALE_WIDTH = 640
SCENE_DETECTION_MAX_KEYFRAMES = 20
SCENE_DETECTION_MIN_FILE_DURATION_S = 180
SCENE_DETECTION_TIMEOUT_S = 30
SCENE_DETECTION_HYBRID_RATIO = 0.5
SCENE_DETECTION_DEDUP_TOLERANCE_S = 15
```

**Commande ffmpeg exacte utilisée :**

```bash
ffmpeg -i "<media_path>" \
  -r 2 \
  -vf "scale=640:-1,select='gt(scene,0.3)',showinfo" \
  -f null \
  -v info \
  -
```

**Seuils et constantes :**

| Constante | Valeur | Source |
|---|---|---|
| `SCENE_DETECTION_THRESHOLD` | 0.3 | Sweet spot films (doc FFmpeg, GDELT) |
| `SCENE_DETECTION_FPS_ANALYSIS` | 2 | Downsample temporel 5-10x |
| `SCENE_DETECTION_SCALE_WIDTH` | 640 | Downsample spatial 2-3x pour 4K |
| `SCENE_DETECTION_MAX_KEYFRAMES` | 20 | Cap action films (évite 200+ keyframes) |
| `SCENE_DETECTION_MIN_FILE_DURATION_S` | 180 | Skip si film court, overhead > bénéfice |
| `SCENE_DETECTION_TIMEOUT_S` | 30 | Sécurité anti-blocage |
| `SCENE_DETECTION_HYBRID_RATIO` | 0.5 | 50% keyframes / 50% uniforme |
| `SCENE_DETECTION_DEDUP_TOLERANCE_S` | 15 | Distance min entre uniforme et keyframe |

**Ordre d'implémentation :**

1. **Étape 1 — Constantes** : ajouter dans `perceptual/constants.py` (5 min).
2. **Étape 2 — Module scene_detection.py** : créer avec les 3 fonctions publiques + `SceneKeyframe` dataclass (1 h).
3. **Étape 3 — Regex robuste** : tester la regex `_RE_SCENE` sur des sorties ffmpeg réelles de plusieurs versions (15 min).
4. **Étape 4 — Tests module** : écrire 12 tests AVANT intégration (parsing, merge, skip, cap) (1 h).
5. **Étape 5 — Setting** : ajouter `perceptual_scene_detection_enabled` dans DEFAULT_SETTINGS (10 min).
6. **Étape 6 — Intégration dans `extract_representative_frames`** : modifier la signature et la logique (30 min).
7. **Étape 7 — Tests intégration** : 4 tests bout-en-bout (30 min).
8. **Étape 8 — Corpus validation** : créer `tests/fixtures/scene_detection/` avec 5 films étiquetés (fixtures courtes ~30 s chacune), valider les seuils (45 min).

**Tests à écrire :**

```python
# tests/test_scene_detection.py

class TestDetectSceneKeyframes(unittest.TestCase):
    def test_parses_pts_time_and_score(self): ...            # mock stderr
    def test_returns_sorted_by_timestamp(self): ...
    def test_caps_at_max_keyframes_by_score(self): ...       # 100 → 20 meilleurs
    def test_timeout_returns_empty(self): ...
    def test_ffmpeg_error_returns_empty(self): ...
    def test_empty_stderr_returns_empty(self): ...

class TestMergeHybridTimestamps(unittest.TestCase):
    def test_no_keyframes_returns_uniform(self): ...
    def test_50_50_split_respected(self): ...
    def test_dedup_by_tolerance(self): ...                   # keyframe à 12s d'un uniforme ignoré
    def test_target_count_respected(self): ...
    def test_keyframes_sorted_by_score(self): ...            # top N par score

class TestShouldSkipSceneDetection(unittest.TestCase):
    def test_setting_disabled_skips(self): ...
    def test_short_film_skips(self): ...                     # < 180s
    def test_long_film_enabled_runs(self): ...

class TestIntegrationExtract(unittest.TestCase):
    def test_scene_detection_enriches_timestamps(self): ...   # mock ffmpeg
    def test_fallback_on_scene_detection_error(self): ...
    def test_setting_false_bypasses_detection(self): ...

class TestCorpusValidation(unittest.TestCase):
    def test_action_film_caps_at_20_keyframes(self): ...
    def test_plan_sequence_few_keyframes(self): ...
    def test_drama_classic_moderate_keyframes(self): ...
    def test_short_film_bypasses_detection(self): ...
```

**Cas limites à tester explicitement :**

- Sortie ffmpeg avec 0 keyframe → retourne liste vide, fallback uniform dans l'appelant.
- Sortie avec 200+ keyframes (film action) → garde top 20 par score, re-trie par timestamp.
- Regex ne match aucune ligne (version ffmpeg future changée) → retour liste vide + log warning.
- Timeout (fichier corrompu) → retour liste vide, pas d'exception.
- Keyframe en < 5 s (près du début) → gardé, skip uniforme l'évitait mais le user peut préférer voir.
- Uniform `[10, 30, 50]` + keyframes `[12, 40]` + tolerance 15 → merged `[10, 40, 30, 50]` dédup → `[10, 30, 40, 50]` (12 ignoré car < 15 s de 10).

**Effort réévalué :** **4h15** (3h dev + 1h15 tests + corpus).

**Note packaging :** aucune dépendance nouvelle. Ajouter `cinesort.domain.perceptual.scene_detection` aux `hiddenimports` de [CineSort.spec](../../../CineSort.spec).

---

### §9 — Spectral cutoff audio ✅

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §9](NOTES_RECHERCHE_v7_5_0.md#§9--spectral-cutoff-audio-)

**Prérequis :** §1 Parallélisme (pour tourner en parallèle de chromaprint et des autres analyses audio).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : +11 constantes.
- [cinesort/domain/perceptual/spectral_analysis.py](../../../cinesort/domain/perceptual/spectral_analysis.py) : **nouveau module**.
- [cinesort/domain/perceptual/models.py](../../../cinesort/domain/perceptual/models.py) : +2 champs dans `AudioPerceptual` (`spectral_cutoff_hz`, `lossy_verdict`).
- [cinesort/domain/perceptual/audio_perceptual.py](../../../cinesort/domain/perceptual/audio_perceptual.py) : intégration en fin de `analyze_audio_perceptual()`.
- [cinesort/infra/db/migrations/017_audio_spectral.sql](../../../cinesort/infra/db/migrations/017_audio_spectral.sql) : **nouvelle migration** (colonnes `spectral_cutoff_hz`, `lossy_verdict` dans `quality_reports`).
- [cinesort/ui/api/settings_support.py](../../../cinesort/ui/api/settings_support.py) : setting `perceptual_audio_spectral_enabled`.
- [CineSort.spec](../../../CineSort.spec) : +`cinesort.domain.perceptual.spectral_analysis` aux `hiddenimports`.
- [requirements.txt](../../../requirements.txt) : **pas de changement** (numpy déjà tiré via rapidfuzz indirectement). À vérifier au build.

**Signatures exactes :**

```python
# cinesort/domain/perceptual/spectral_analysis.py

from __future__ import annotations
import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .constants import (
    SPECTRAL_SEGMENT_OFFSET_S, SPECTRAL_SEGMENT_DURATION_S,
    SPECTRAL_SAMPLE_RATE, SPECTRAL_FFT_WINDOW_SIZE, SPECTRAL_FFT_OVERLAP,
    SPECTRAL_ROLLOFF_PCT, SPECTRAL_CUTOFF_LOSSLESS,
    SPECTRAL_CUTOFF_LOSSY_HIGH, SPECTRAL_CUTOFF_LOSSY_MID,
    SPECTRAL_TIMEOUT_S, SPECTRAL_MIN_RMS_DB,
)
from .ffmpeg_runner import _runner_platform_kwargs

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpectralResult:
    cutoff_hz: float                       # 0.0 si échec
    lossy_verdict: str                     # "lossless" | "lossy_high" | "lossy_mid" | "lossy_low"
                                           # | "lossy_ambiguous_sbr" | "lossless_native_nyquist"
                                           # | "lossless_vintage_master" | "silent_segment" | "error"
    confidence: float                      # 0.0-1.0
    rms_db: float                          # pour debug


def extract_audio_segment(
    ffmpeg_path: str,
    media_path: str,
    track_index: int,
    offset_s: float = SPECTRAL_SEGMENT_OFFSET_S,
    duration_s: float = SPECTRAL_SEGMENT_DURATION_S,
    sample_rate: int = SPECTRAL_SAMPLE_RATE,
    timeout_s: float = SPECTRAL_TIMEOUT_S,
) -> Optional[np.ndarray]:
    """Extrait un segment audio mono PCM float32 via ffmpeg.

    Commande ffmpeg :
      -ss offset -t duration -map 0:a:idx -ac 1 -ar sr -f f32le -

    Returns:
        np.ndarray dtype float32 (mono samples), ou None si erreur/timeout.
    """


def compute_spectrogram(
    samples: np.ndarray,
    window_size: int = SPECTRAL_FFT_WINDOW_SIZE,
    overlap: float = SPECTRAL_FFT_OVERLAP,
) -> np.ndarray:
    """Calcule le spectrogramme via FFT + Hann window.

    Returns:
        Magnitudes moyennes par fréquence (np.ndarray 1D, longueur window_size//2+1).
    """


def find_cutoff_hz(
    spec_mean: np.ndarray,
    sample_rate: int,
    rolloff_pct: float = SPECTRAL_ROLLOFF_PCT,
) -> float:
    """Trouve la fréquence de cutoff par spectral rolloff (85% d'énergie).

    Returns:
        Fréquence en Hz où la puissance cumulée atteint `rolloff_pct` du total.
    """


def compute_rms_db(samples: np.ndarray) -> float:
    """RMS en dBFS (référence 1.0 = 0 dB)."""


def classify_cutoff(
    cutoff_hz: float,
    rms_db: float,
    codec: str,
    sample_rate: int,
    film_era: str = "unknown",
) -> tuple[str, float]:
    """Classifie le cutoff avec cross-check codec + sample rate + ère.

    Returns:
        (verdict, confidence) parmi les valeurs de SpectralResult.
    """


def analyze_spectral(
    ffmpeg_path: str,
    media_path: str,
    track_index: int,
    duration_total_s: float,
    codec: str = "",
    sample_rate: int = 48000,
    film_era: str = "unknown",
) -> SpectralResult:
    """Orchestre l'analyse spectrale complète (extraction + FFT + classification).

    Returns:
        SpectralResult avec verdict final.
        En cas d'erreur : SpectralResult(0.0, "error", 0.0, -inf).
    """
```

```python
# models.py — ajouts dans AudioPerceptual

@dataclass
class AudioPerceptual:
    # ... champs existants ...
    spectral_cutoff_hz: float = 0.0            # §9
    lossy_verdict: str = "unknown"              # §9
    lossy_confidence: float = 0.0               # §9
```

```python
# audio_perceptual.py — ajout en fin de analyze_audio_perceptual()

# --- Spectral analysis (si activé) ---
if settings.get("perceptual_audio_spectral_enabled", True):
    codec = str(best.get("codec") or "")
    sample_rate = int(best.get("sample_rate") or 48000)
    spectral = analyze_spectral(
        ffmpeg_path, media_path, idx,
        duration_total_s=duration_s,
        codec=codec, sample_rate=sample_rate,
        film_era=era,  # passé depuis grain_analysis
    )
    result.spectral_cutoff_hz = spectral.cutoff_hz
    result.lossy_verdict = spectral.lossy_verdict
    result.lossy_confidence = spectral.confidence
```

```sql
-- 017_audio_spectral.sql
ALTER TABLE quality_reports ADD COLUMN spectral_cutoff_hz REAL;
ALTER TABLE quality_reports ADD COLUMN lossy_verdict TEXT;
```

**Seuils et constantes :**

| Constante | Valeur | Rôle |
|---|---|---|
| `SPECTRAL_SEGMENT_OFFSET_S` | 60 | Cohérence avec chromaprint §3 |
| `SPECTRAL_SEGMENT_DURATION_S` | 30 | Segment plus court (cutoff stable vite) |
| `SPECTRAL_SAMPLE_RATE` | 48000 | Nyquist 24 kHz, cible 22 kHz OK |
| `SPECTRAL_FFT_WINDOW_SIZE` | 4096 | Résolution fréquentielle ~11.7 Hz/bin |
| `SPECTRAL_FFT_OVERLAP` | 0.5 | Standard |
| `SPECTRAL_ROLLOFF_PCT` | 0.85 | 85% d'énergie, robuste au bruit |
| `SPECTRAL_CUTOFF_LOSSLESS` | 21500 | Seuil lossless vrai |
| `SPECTRAL_CUTOFF_LOSSY_HIGH` | 19000 | Seuil lossy haut (MP3 320, AAC 256) |
| `SPECTRAL_CUTOFF_LOSSY_MID` | 16500 | Seuil lossy mid (MP3 192, AAC 128) |
| `SPECTRAL_TIMEOUT_S` | 15 | Extraction + FFT rapides |
| `SPECTRAL_MIN_RMS_DB` | -50 | En dessous : silence |

**Ordre d'implémentation :**

1. **Étape 1 — Vérifier numpy** : confirmer via `pip show numpy` que numpy est bien disponible (déjà tiré ?). Sinon ajouter à requirements.txt (5 min).
2. **Étape 2 — Constantes** : 11 constantes dans `perceptual/constants.py` (10 min).
3. **Étape 3 — Migration SQL** : `017_audio_spectral.sql` (5 min).
4. **Étape 4 — Modèle** : ajouter champs dans `AudioPerceptual` (10 min).
5. **Étape 5 — Module spectral_analysis.py** : créer avec les 6 fonctions publiques (2 h).
6. **Étape 6 — Tests module** : 10 tests AVANT intégration (FFT correctness, rolloff math, classify edge cases) (1 h).
7. **Étape 7 — Intégration** : ajout dans `analyze_audio_perceptual()` (30 min).
8. **Étape 8 — Setting** : `perceptual_audio_spectral_enabled` (10 min).
9. **Étape 9 — Tests intégration** : 4 tests avec mock ffmpeg (30 min).
10. **Étape 10 — Corpus validation** : 6 fichiers étiquetés dans `tests/fixtures/spectral_cutoff/` (FLAC, AC3, AAC 256, AAC 128, MP3 128, HE-AAC) (1 h).

**Tests à écrire :**

```python
# tests/test_spectral_analysis.py

class TestComputeSpectrogram(unittest.TestCase):
    def test_sine_wave_1000hz_detected(self): ...     # FFT test basique
    def test_silence_returns_low_magnitude(self): ...
    def test_window_size_affects_resolution(self): ...

class TestFindCutoffHz(unittest.TestCase):
    def test_pure_tone_10khz_cutoff_near_10k(self): ...
    def test_broadband_noise_cutoff_near_nyquist(self): ...
    def test_low_pass_filtered_at_16k_cutoff_near_16k(self): ...

class TestClassifyCutoff(unittest.TestCase):
    def test_22khz_flac_is_lossless(self): ...
    def test_20_5khz_is_lossy_high(self): ...
    def test_17khz_is_lossy_mid(self): ...
    def test_15khz_is_lossy_low(self): ...
    def test_he_aac_codec_overrides_cutoff(self): ...
    def test_22050_sample_rate_is_native_nyquist(self): ...
    def test_classic_film_era_tolerance(self): ...       # 19.5k FLAC = lossless vintage

class TestExtractAudioSegment(unittest.TestCase):
    def test_parse_f32le_bytes_correctly(self): ...
    def test_ffmpeg_error_returns_none(self): ...
    def test_timeout_returns_none(self): ...

class TestIntegrationAudioSpectral(unittest.TestCase):
    def test_flac_fixture_verdict_lossless(self): ...
    def test_mp3_128_fixture_verdict_lossy_mid(self): ...
    def test_silent_audio_verdict_silent_segment(self): ...
    def test_setting_disabled_skips(self): ...
```

**Cas limites à tester explicitement :**

- Audio totalement silencieux : `rms_db < -50` → verdict `silent_segment`.
- Codec = "he-aac" ou "aac (LC_SBR)" : verdict forcé `lossy_ambiguous_sbr`.
- Sample rate 22050 : cutoff ~11000 mais verdict `lossless_native_nyquist` (Nyquist).
- Film era `classic_film` + cutoff 19700 Hz + codec FLAC : verdict `lossless_vintage_master` (tolérance).
- ffmpeg inexistant : retour `None`, pas d'erreur bloquante.
- np.ndarray corrompu (< window_size samples) : retour verdict `error`.

**Effort réévalué :** **5h30** (2h module + 1h30 tests + 1h corpus + 30 min migration + 30 min intégration).

**Note packaging :**
- numpy doit être confirmé dans le bundle. Vérifier avec `pyinstaller` xref.
- Aucune nouvelle dépendance pip ajoutée.
- Migration SQL à ajouter au bundle (gérée par `migration_manager.py`).

---

### §13 — SSIM self-referential ✅

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §13](NOTES_RECHERCHE_v7_5_0.md#§13--ssim-self-referential-)

**Prérequis :** §1 Parallélisme (peut tourner en parallèle).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : +6 constantes.
- [cinesort/domain/perceptual/ssim_self_ref.py](../../../cinesort/domain/perceptual/ssim_self_ref.py) : **nouveau module**.
- [cinesort/domain/perceptual/models.py](../../../cinesort/domain/perceptual/models.py) : +2 champs dans `VideoPerceptual` (`ssim_self_ref`, `upscale_verdict`).
- [cinesort/domain/perceptual/video_analysis.py](../../../cinesort/domain/perceptual/video_analysis.py) : intégration après les analyses existantes.
- [cinesort/ui/api/settings_support.py](../../../cinesort/ui/api/settings_support.py) : setting `perceptual_ssim_self_ref_enabled`.
- [CineSort.spec](../../../CineSort.spec) : +`cinesort.domain.perceptual.ssim_self_ref` aux `hiddenimports`.

**Signatures exactes :**

```python
# cinesort/domain/perceptual/ssim_self_ref.py

from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Optional

from .constants import (
    SSIM_SELF_REF_SEGMENT_DURATION_S, SSIM_SELF_REF_MIN_HEIGHT,
    SSIM_SELF_REF_TIMEOUT_S, SSIM_SELF_REF_FAKE_THRESHOLD,
    SSIM_SELF_REF_AMBIGUOUS_THRESHOLD, SSIM_SELF_REF_NATIVE_THRESHOLD,
)
from .ffmpeg_runner import run_ffmpeg_text

logger = logging.getLogger(__name__)

_RE_SSIM_ALL = re.compile(r"All:([\d.]+)")
_RE_SSIM_Y = re.compile(r"Y:([\d.]+)")


@dataclass(frozen=True)
class SsimSelfRefResult:
    ssim_y: float                 # score luminance 0.0-1.0, -1 si erreur
    ssim_all: float               # score global 0.0-1.0
    upscale_verdict: str          # "native" | "ambiguous" | "upscale_fake" | "not_applicable_*" | "error"
    confidence: float             # 0.0-1.0


def compute_ssim_self_ref(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    video_height: int,
    is_animation: bool = False,
    segment_duration_s: float = SSIM_SELF_REF_SEGMENT_DURATION_S,
    timeout_s: float = SSIM_SELF_REF_TIMEOUT_S,
) -> SsimSelfRefResult:
    """Calcule le SSIM self-referential pour détecter les fake 4K.

    Skip si :
        - video_height < SSIM_SELF_REF_MIN_HEIGHT (1800) → `not_applicable_resolution`
        - is_animation → `not_applicable_animation`
        - duration_s < segment_duration_s + 30 → fichier trop court

    Segment analysé : 2 min au milieu du film.

    Returns:
        SsimSelfRefResult avec score + verdict.
    """


def classify_ssim_verdict(ssim_y: float) -> tuple[str, float]:
    """Classifie le score SSIM Y en verdict textuel.

    >= 0.95 : "upscale_fake" (confidence 0.85)
    >= 0.90 : "ambiguous" (confidence 0.60)
    < 0.85  : "native" (confidence 0.90)
    """


def build_ssim_self_ref_command(
    ffmpeg_path: str,
    media_path: str,
    start_offset_s: float,
    duration_s: float,
) -> list[str]:
    """Construit la commande ffmpeg filter_complex pour SSIM self-ref."""
```

**Commande ffmpeg exacte :**

```bash
ffmpeg -ss <mid_offset> -i <file> -t <duration> \
  -filter_complex \
    "[0:v]split=2[a][b];\
     [a]scale=1920:1080:flags=bicubic,scale=3840:2160:flags=bicubic[ref];\
     [b][ref]ssim" \
  -f null -v info -
```

Parser : regex `All:([\d.]+)` et `Y:([\d.]+)` sur stderr.

**Seuils et constantes :**

| Constante | Valeur | Rôle |
|---|---|---|
| `SSIM_SELF_REF_SEGMENT_DURATION_S` | 120 | 2 min au milieu, signal représentatif |
| `SSIM_SELF_REF_MIN_HEIGHT` | 1800 | Skip si pas 4K (pas de sens en dessous) |
| `SSIM_SELF_REF_TIMEOUT_S` | 45 | Calcul ~10-15s typique |
| `SSIM_SELF_REF_FAKE_THRESHOLD` | 0.95 | ≥ : upscale probable |
| `SSIM_SELF_REF_AMBIGUOUS_THRESHOLD` | 0.90 | Zone grise 0.90-0.95 |
| `SSIM_SELF_REF_NATIVE_THRESHOLD` | 0.85 | < : 4K native |

**Ordre d'implémentation :**

1. **Étape 1 — Constantes** (5 min).
2. **Étape 2 — Modèles** : ajouter `ssim_self_ref: float` et `upscale_verdict: str` dans `VideoPerceptual` (10 min).
3. **Étape 3 — Module ssim_self_ref.py** : créer avec 3 fonctions publiques + regex parsing (1 h).
4. **Étape 4 — Tests module** : 8 tests unitaires (parsing, thresholds, skip conditions) (45 min).
5. **Étape 5 — Intégration dans video_analysis** : appel conditionnel après les analyses existantes, parallélisable avec §1 (30 min).
6. **Étape 6 — Setting** : `perceptual_ssim_self_ref_enabled` (10 min).
7. **Étape 7 — Tests intégration** : 3 tests bout-en-bout (20 min).
8. **Étape 8 — Corpus validation** : 6 fichiers étiquetés (UHD native, 4K IA upscale, fake bicubic, animation, 1080p, short) (45 min).

**Tests à écrire :**

```python
# tests/test_ssim_self_ref.py

class TestClassifyVerdict(unittest.TestCase):
    def test_0_97_returns_upscale_fake(self): ...
    def test_0_92_returns_ambiguous(self): ...
    def test_0_84_returns_native(self): ...

class TestComputeSsimSelfRef(unittest.TestCase):
    def test_skip_if_not_4k(self): ...             # height < 1800
    def test_skip_if_animation(self): ...
    def test_skip_if_duration_too_short(self): ...
    def test_parse_ssim_y_and_all(self): ...       # mock stderr
    def test_ffmpeg_error_returns_error_verdict(self): ...
    def test_timeout_returns_error(self): ...

class TestIntegration(unittest.TestCase):
    def test_native_uhd_verdict_native(self): ...
    def test_fake_bicubic_verdict_upscale_fake(self): ...
    def test_setting_disabled_skips(self): ...
```

**Cas limites à tester explicitement :**

- Film 1080p : skip, verdict `not_applicable_resolution`.
- Animation (cross-check via tmdb.genres) : skip.
- Film très court (< 3 min) : skip ou utiliser toute la durée dispo.
- Parse ffmpeg échoue : retour `error`, continue l'analyse.
- Filter SSIM absent du build ffmpeg (rare) : log warning, fallback.

**Effort réévalué :** **3h45** (dev + tests + corpus).

---

---

### §14 — DRC detection ✅

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §14](NOTES_RECHERCHE_v7_5_0.md#§14--drc-detection-)

**Prérequis :** aucun (utilise valeurs déjà calculées par astats + loudnorm).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : +4 constantes DRC.
- [cinesort/domain/perceptual/audio_perceptual.py](../../../cinesort/domain/perceptual/audio_perceptual.py) : ajout fonction `classify_drc()` + appel en fin de `analyze_audio_perceptual()`.
- [cinesort/domain/perceptual/models.py](../../../cinesort/domain/perceptual/models.py) : +2 champs dans `AudioPerceptual` (`drc_category`, `drc_confidence`).

**Signatures exactes :**

```python
# cinesort/domain/perceptual/audio_perceptual.py — ajout

from .constants import (
    DRC_CREST_CINEMA, DRC_CREST_STANDARD,
    DRC_LRA_CINEMA, DRC_LRA_STANDARD,
)


def classify_drc(
    crest_factor: Optional[float],
    lra: Optional[float],
) -> tuple[str, float]:
    """Classifie la compression dynamique en verdict textuel.

    Args:
        crest_factor: en dB (peut être None si astats échoué).
        lra: Loudness Range en LU (peut être None si loudnorm échoué).

    Returns:
        (drc_category, confidence) où drc_category ∈
        {"cinema", "standard", "broadcast_compressed", "unknown"}.

    Stratégie :
        score_crest : 2 si >=15dB, 1 si >=10dB, 0 sinon
        score_lra   : 2 si >=18LU, 1 si >=10LU, 0 sinon
        combined    : somme (0-4)
        Verdict :
          >= 3 : "cinema" (confidence 0.95)
          == 2 : "cinema" (confidence 0.75)
          == 1 : "standard" (confidence 0.80)
          else : "broadcast_compressed" (confidence 0.85)
        Si les 2 sont None : "unknown" (confidence 0.0).
    """
```

```python
# models.py — ajouts dans AudioPerceptual

@dataclass
class AudioPerceptual:
    # ... champs existants ...
    drc_category: str = "unknown"          # §14
    drc_confidence: float = 0.0             # §14
```

```python
# audio_perceptual.py — ajout dans analyze_audio_perceptual() après le scoring

# --- DRC classification (aucun calcul supplémentaire) ---
drc_cat, drc_conf = classify_drc(
    crest_factor=result.crest_factor,
    lra=result.loudness_range,
)
result.drc_category = drc_cat
result.drc_confidence = drc_conf
```

**Seuils et constantes :**

| Constante | Valeur | Rôle |
|---|---|---|
| `DRC_CREST_CINEMA` | 15.0 dB | Seuil cinéma (pleine dynamique) |
| `DRC_CREST_STANDARD` | 10.0 dB | Seuil standard |
| `DRC_LRA_CINEMA` | 18.0 LU | LRA cinéma |
| `DRC_LRA_STANDARD` | 10.0 LU | LRA standard |

**Ordre d'implémentation :**

1. **Étape 1 — Constantes** (3 min).
2. **Étape 2 — Modèles** : ajouter `drc_category` + `drc_confidence` dans `AudioPerceptual` (5 min).
3. **Étape 3 — Fonction `classify_drc`** : dans `audio_perceptual.py` (10 min).
4. **Étape 4 — Appel dans `analyze_audio_perceptual`** : après le scoring existant (5 min).
5. **Étape 5 — Tests unitaires** : 7 tests (cinéma, standard, compressé, None partiel/total) (30 min).
6. **Étape 6 — Tests intégration** : 2 tests bout-en-bout avec fixtures existantes (10 min).

**Tests à écrire :**

```python
# tests/test_drc_classification.py (ou ajouts à test_audio_perceptual.py)

class TestClassifyDrc(unittest.TestCase):
    def test_crest_20_lra_22_returns_cinema_high_conf(self): ...
    def test_crest_16_lra_15_returns_cinema(self): ...
    def test_crest_12_lra_8_returns_standard(self): ...
    def test_crest_6_lra_5_returns_broadcast_compressed(self): ...
    def test_crest_none_lra_20_uses_lra_only(self): ...
    def test_crest_18_lra_none_uses_crest_only(self): ...
    def test_both_none_returns_unknown(self): ...

class TestIntegration(unittest.TestCase):
    def test_bluray_atmos_fixture_classified_cinema(self): ...
    def test_stream_aac_fixture_classified_standard(self): ...
```

**Cas limites à tester explicitement :**

- Crest = None, LRA = None : verdict `unknown`, confidence 0.
- Crest très élevé mais LRA faible (contenu percussif compressé rare) : priorité au combined score.
- LRA très élevé mais crest faible (musique classique sans pics) : priorité au combined score.
- Values négatives ou aberrantes : clamp à 0 dans la logique.

**Effort réévalué :** **1h** (très rapide, juste de la logique de classification).

**Note :** aucune dépendance nouvelle, aucune migration SQL (les champs `crest_factor`, `lra` et la nouvelle colonne `drc_category` sont dans le blob `metrics` JSON existant — pas besoin de colonne dédiée).

---

## Vague 3 — Métadonnées techniques

### §5 — HDR metadata ✅

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §5](NOTES_RECHERCHE_v7_5_0.md#§5--hdr-metadata-)

**Prérequis :** aucun — ffprobe natif. S'intègre dans le pipeline probe existant.

**Fichiers touchés :**
- [cinesort/infra/probe/normalize.py](../../../cinesort/infra/probe/normalize.py) : enrichissement extraction HDR metadata.
- [cinesort/infra/probe/ffprobe_backend.py](../../../cinesort/infra/probe/ffprobe_backend.py) : ajouter `show_frames` + `side_data_list` à la commande standard.
- [cinesort/domain/probe_models.py](../../../cinesort/domain/probe_models.py) : ajouter les champs HDR à `NormalizedProbe`.
- [cinesort/domain/perceptual/hdr_analysis.py](../../../cinesort/domain/perceptual/hdr_analysis.py) : **nouveau module** (classification + validation HDR).
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : +4 constantes HDR.
- [CineSort.spec](../../../CineSort.spec) : +`cinesort.domain.perceptual.hdr_analysis` aux `hiddenimports`.

**Signatures exactes :**

```python
# cinesort/domain/perceptual/hdr_analysis.py

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Optional

from .constants import (
    HDR_MAX_CLL_WARNING_THRESHOLD,
    HDR_MAX_CLL_TYPICAL_MIN,
    HDR_QUALITY_SCORE,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HdrInfo:
    hdr_type: str              # "sdr" | "hdr10" | "hdr10_plus" | "hlg" | "dolby_vision"
    max_cll: float              # nits, 0 si absent
    max_fall: float              # nits, 0 si absent
    min_luminance: float         # nits
    max_luminance: float         # nits
    color_primaries: str
    color_transfer: str
    color_space: str
    is_valid: bool
    validation_flag: Optional[str]  # "hdr_metadata_missing" | "hdr_low_punch" | "color_mismatch_sdr_bt2020"
    quality_score: int             # 0-100, voir HDR_QUALITY_SCORE dans constants
    has_hdr10_plus_metadata: bool  # détection multi-frames (§5 pass 2)


def parse_ratio(value: Any) -> float:
    """Parse un ratio ffprobe type '10000000/10000' en float.

    Exemples :
        parse_ratio("10000000/10000") → 1000.0
        parse_ratio("34000/50000") → 0.68
        parse_ratio(None) → 0.0
        parse_ratio("invalid") → 0.0
    """


def detect_hdr_type(
    color_primaries: str,
    color_transfer: str,
    side_data_list: list[dict],
) -> str:
    """Classifie le type HDR via ordre de priorité.

    Returns:
        "hlg" (arib-std-b67 transfer) >
        "dolby_vision" (DOVI config record in side_data) >
        "hdr10_plus" (SMPTE ST 2094-40 in side_data) >
        "hdr10" (smpte2084 + bt2020) >
        "sdr" (par défaut).
    """


def extract_hdr_metadata_pass1(
    ffprobe_path: str,
    media_path: str,
    timeout_s: float = 10.0,
) -> HdrInfo:
    """Extraction rapide HDR (1 frame, ~1-2 s).

    Commande ffprobe :
      -select_streams v -print_format json \
      -show_frames -read_intervals "%+#1" \
      -show_entries "frame=color_space,color_primaries,color_transfer,side_data_list,pix_fmt"

    Détecte : type HDR, MaxCLL, MaxFALL, luminance mastering display.
    Returns: HdrInfo avec has_hdr10_plus_metadata=False (pass 2 requis).
    """


def detect_hdr10_plus_pass2(
    ffprobe_path: str,
    media_path: str,
    timeout_s: float = 15.0,
) -> bool:
    """Vérifie présence HDR10+ via scan de 5 frames (uniquement si HDR10 détecté en pass 1).

    Commande ffprobe :
      -select_streams v -print_format json \
      -show_frames -read_intervals "%+#5" \
      -show_entries "frame=side_data_list"

    Returns:
        True si au moins 1 frame contient side_data_type "HDR10+" ou "SMPTE ST 2094-40".
    """


def validate_hdr(hdr_type: str, max_cll: float, max_fall: float,
                 color_primaries: str) -> tuple[bool, Optional[str]]:
    """Valide la cohérence HDR.

    Flags possibles :
        "hdr_metadata_missing" : HDR10 mais MaxCLL manquant/nul
        "hdr_low_punch"        : HDR10 valide mais MaxCLL < 500 nits
        "color_mismatch_sdr_bt2020" : SDR taggé mais bt2020 (erreur encode)
        None : HDR valide
    """


def compute_hdr_quality_score(hdr_info: HdrInfo) -> int:
    """Score qualité HDR 0-100 pour la comparaison de doublons.

    Hiérarchie :
        Dolby Vision 8.1 : 100  (meilleur, voir §6 pour le profile exact)
        HDR10+           : 90
        HDR10 valid      : 85
        HLG              : 75
        HDR10 low punch  : 65
        HDR10 invalid    : 50
        SDR              : 40
    """


def analyze_hdr(
    ffprobe_path: str,
    media_path: str,
    enable_hdr10_plus_detection: bool = True,
) -> HdrInfo:
    """Orchestrateur complet : pass 1 + pass 2 conditionnel + validation.

    Appelé depuis cinesort/infra/probe/normalize.py (ou hdr_analysis standalone).
    """
```

```python
# cinesort/domain/probe_models.py — ajouts dans NormalizedProbe

@dataclass
class NormalizedProbe:
    # ... champs existants ...

    # §5 HDR
    hdr_type: str = "sdr"
    max_cll: float = 0.0
    max_fall: float = 0.0
    min_luminance: float = 0.0
    max_luminance: float = 0.0
    hdr_is_valid: bool = True
    hdr_validation_flag: Optional[str] = None
    hdr_quality_score: int = 40
    has_hdr10_plus: bool = False
```

```python
# cinesort/infra/probe/ffprobe_backend.py — MODIFICATION commande existante

# AJOUTER à la commande ffprobe actuelle :
#   -show_frames -read_intervals "%+#1"
#   -show_entries "frame=color_space,color_primaries,color_transfer,side_data_list,pix_fmt"
#
# Le JSON retourné aura alors un champ "frames" en plus de "streams" et "format".
# Parser dans normalize.py utilise frames[0].side_data_list pour enrichir NormalizedProbe.
```

**Seuils et constantes :**

| Constante | Valeur | Rôle |
|---|---|---|
| `HDR_MAX_CLL_WARNING_THRESHOLD` | 500 nits | En dessous : HDR low punch |
| `HDR_MAX_CLL_TYPICAL_MIN` | 1000 nits | Cible normale films HDR |
| `HDR_MAX_FALL_TYPICAL` | 100 nits | Cible normale |
| `HDR_QUALITY_SCORE` (dict) | voir hiérarchie | Scores pour comparaison §16 |

**Ordre d'implémentation :**

1. **Étape 1 — Constantes** (5 min).
2. **Étape 2 — Modèles** : ajouter champs dans `NormalizedProbe` (15 min).
3. **Étape 3 — Module hdr_analysis.py** : les 6 fonctions publiques (2 h).
4. **Étape 4 — Tests module** : 12 tests unitaires sur fixtures JSON (1 h).
5. **Étape 5 — Modif ffprobe_backend** : ajouter `-show_frames -read_intervals` + `side_data_list` dans la commande standard (30 min).
6. **Étape 6 — Intégration normalize.py** : appel `analyze_hdr()` après extraction probe standard (30 min).
7. **Étape 7 — Tests corpus** : 8 fichiers étiquetés (SDR, HDR10 valid, HDR10 low-punch, HDR10 missing metadata, HDR10+, HLG, DV, color_mismatch) (1 h 30).

**Tests à écrire :**

```python
# tests/test_hdr_analysis.py

class TestParseRatio(unittest.TestCase):
    def test_valid_ratio(self): ...                   # "10000000/10000" → 1000.0
    def test_none_returns_0(self): ...
    def test_zero_denominator(self): ...
    def test_malformed_string(self): ...

class TestDetectHdrType(unittest.TestCase):
    def test_hlg_via_transfer(self): ...               # arib-std-b67
    def test_dv_via_side_data(self): ...
    def test_hdr10_plus_via_side_data(self): ...
    def test_hdr10_standard(self): ...
    def test_sdr_default(self): ...
    def test_priority_hlg_over_hdr10(self): ...        # HLG même si bt2020

class TestValidateHdr(unittest.TestCase):
    def test_hdr10_no_maxcll_flag_missing(self): ...
    def test_hdr10_maxcll_400_flag_low_punch(self): ...
    def test_hdr10_maxcll_1000_valid(self): ...
    def test_sdr_bt2020_flag_color_mismatch(self): ...

class TestComputeHdrQualityScore(unittest.TestCase):
    def test_hdr10_plus_90(self): ...
    def test_hdr10_valid_85(self): ...
    def test_hlg_75(self): ...
    def test_hdr10_low_punch_65(self): ...
    def test_sdr_40(self): ...

class TestHdr10PlusPass2(unittest.TestCase):
    def test_finds_smpte2094_40_in_frames(self): ...
    def test_no_hdr10_plus_in_hdr10_file(self): ...
    def test_timeout_returns_false(self): ...

class TestCorpus(unittest.TestCase):
    def test_fixture_hdr10_standard(self): ...
    def test_fixture_hdr10_plus_samsung(self): ...
    def test_fixture_hlg_broadcast(self): ...
    def test_fixture_sdr_bt2020_encode_error(self): ...
```

**Cas limites à tester explicitement :**

- ffprobe sans `-show_frames` → pas de side_data_list → fallback via streams metadata.
- Fichier SDR normal → `hdr_type="sdr"`, `quality_score=40`.
- Fichier HDR10 avec `MaxCLL=0` explicitement → `validation_flag="hdr_metadata_missing"`.
- HLG sans MaxCLL attendu (broadcast) → pas de flag warning.
- DV profile 5 détecté via side_data → `hdr_type="dolby_vision"`, quality_score réduit par §6.
- HDR10 + HDR10+ coexistants (Samsung stream) → priorité HDR10+.
- Pass 2 timeout → `has_hdr10_plus=False`, pas bloquant.

**Effort réévalué :** **6h** (2h module + 1h tests + 1h30 corpus + 30 min integration + 1h modif backend probe).

**Note packaging :** aucune dépendance nouvelle, mais la commande ffprobe devient plus lourde (`-show_frames`) → impact ~500 ms supplémentaire par fichier au scan initial. Acceptable.

---

### §6 — Dolby Vision ✅

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §6](NOTES_RECHERCHE_v7_5_0.md#§6--dolby-vision-)

**Prérequis :** §5 HDR (mutualise le call ffprobe `show_frames` avec `side_data_list`).

**Fichiers touchés :**
- [cinesort/domain/perceptual/hdr_analysis.py](../../../cinesort/domain/perceptual/hdr_analysis.py) : enrichir pour extraire les infos DV (même module §5).
- [cinesort/domain/probe_models.py](../../../cinesort/domain/probe_models.py) : ajouter 5 champs DV à `NormalizedProbe`.
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : `DV_PROFILE_LABELS`, `DV_COMPAT_RANKING`.

**Signatures exactes :**

```python
# hdr_analysis.py — fonctions ajoutées

@dataclass(frozen=True)
class DolbyVisionInfo:
    present: bool
    profile: str              # "5" | "7" | "8.1" | "8.2" | "8.4" | "unknown"
    compatibility: str        # "none" | "hdr10_full" | "hdr10_partial" | "sdr" | "hlg"
    el_present: bool          # Enhancement Layer (Profile 7)
    rpu_present: bool
    warning: Optional[str]    # message FR pour l'UI, ex: "Player Dolby Vision requis"
    quality_score: int         # 0-100 pour comparaison §16


def extract_dv_configuration(side_data_list: list[dict]) -> Optional[dict]:
    """Cherche l'entrée 'DOVI configuration record' dans side_data_list.

    Returns:
        Dict avec les champs DV, ou None si DV absent.
    """


def classify_dv_profile(
    dv_profile: int,
    compat_id: int,
    el_present: bool,
    rpu_present: bool,
) -> DolbyVisionInfo:
    """Classifie le profile DV selon les flags et compatibility_id.

    Règles :
        profile=5 → "5", compat="none", warning="Player DV requis"
        el_present=1 ou profile=7 → "7", compat="hdr10_partial"
        profile=8, compat_id=1 → "8.1", compat="hdr10_full"
        profile=8, compat_id=2 → "8.2", compat="sdr"
        profile=8, compat_id=4 → "8.4", compat="hlg"
        autre → "unknown"
    """


def compute_dv_quality_score(dv_info: DolbyVisionInfo) -> int:
    """Score qualité pour comparaison.

    Profile 8.1 : 100
    Profile 7   : 95
    Profile 8.4 : 88
    Profile 8.2 : 82
    Profile 5   : 80 (pénalisé incompatibilité)
    None        : N/A (score HDR §5 utilisé à la place)
    """


def detect_invalid_dv(dv_info: DolbyVisionInfo) -> Optional[str]:
    """Détecte les DV pathologiques (pas de RPU, etc.).

    Returns:
        Flag warning ou None.
        "dv_invalid_no_rpu" : tagué DV mais rpu_present=False
        "dv_el_expected_missing" : profile 7 mais el_present=False
    """
```

```python
# probe_models.py — ajouts dans NormalizedProbe

@dataclass
class NormalizedProbe:
    # ... champs existants + ceux du §5 ...

    # §6 Dolby Vision
    dv_present: bool = False
    dv_profile: str = "none"
    dv_compatibility: str = "none"
    dv_el_present: bool = False
    dv_warning: Optional[str] = None
    dv_quality_score: int = 0
```

**Seuils et constantes :**

```python
# constants.py ajouts

DV_PROFILE_LABELS = {
    "5": "Dolby Vision Profile 5 (IPTPQc2 proprietary)",
    "7": "Dolby Vision Profile 7 (BL+EL+RPU)",
    "8.1": "Dolby Vision Profile 8.1 (HDR10 compatible)",
    "8.2": "Dolby Vision Profile 8.2 (SDR compatible)",
    "8.4": "Dolby Vision Profile 8.4 (HLG compatible)",
    "unknown": "Dolby Vision (profil non identifié)",
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
    "7": "Profile 7 : fallback HDR10 possible mais Enhancement Layer ignoré sur players HDR10.",
    "unknown": "Profil Dolby Vision non reconnu, comportement player imprévisible.",
}
```

**Ordre d'implémentation :**

1. **Étape 1 — Constantes** : `DV_PROFILE_LABELS`, `DV_COMPAT_RANKING`, `DV_PROFILE_WARNINGS_FR` (10 min).
2. **Étape 2 — Modèles** : +5 champs DV dans `NormalizedProbe` (10 min).
3. **Étape 3 — Fonctions classification** : `extract_dv_configuration`, `classify_dv_profile`, `compute_dv_quality_score`, `detect_invalid_dv` (1 h).
4. **Étape 4 — Intégration dans `analyze_hdr()`** : après la détection HDR type, si DV → appel des fonctions DV → enrichit HdrInfo (20 min).
5. **Étape 5 — Tests** : 10 tests sur fixtures JSON de side_data_list (1 h).
6. **Étape 6 — Corpus validation** : 5 fichiers DV réels (Profile 5, 7, 8.1, 8.4, sans RPU) (1 h).

**Tests à écrire :**

```python
# tests/test_dolby_vision.py

class TestExtractDvConfiguration(unittest.TestCase):
    def test_finds_dovi_in_side_data(self): ...
    def test_no_dovi_returns_none(self): ...
    def test_malformed_side_data(self): ...

class TestClassifyDvProfile(unittest.TestCase):
    def test_profile_5(self): ...                     # dv_profile=5, compat=0
    def test_profile_7_el_present(self): ...          # dv_profile=7, el_present=1
    def test_profile_8_1_hdr10_compat(self): ...      # profile=8, compat=1
    def test_profile_8_4_hlg_compat(self): ...        # profile=8, compat=4
    def test_unknown_profile(self): ...

class TestComputeDvQualityScore(unittest.TestCase):
    def test_profile_8_1_top_score(self): ...
    def test_profile_5_penalized(self): ...

class TestDetectInvalidDv(unittest.TestCase):
    def test_no_rpu_invalid(self): ...
    def test_profile_7_el_missing_warning(self): ...

class TestCorpus(unittest.TestCase):
    def test_netflix_profile_5_rip(self): ...
    def test_uhd_bluray_profile_7(self): ...
    def test_x265_hybrid_profile_8_1(self): ...
```

**Cas limites à tester explicitement :**

- Fichier DV valide mais ffprobe trop vieux (< 4.3) ne parse pas DOVI → fallback HDR10 via §5.
- DV Profile 5 : verdict avec warning affiché dans UI.
- Profile 7 sans EL (rip incomplet) : flag `dv_el_expected_missing`.
- Profile 8 avec compat_id inconnu (nouveau sub-profile futur) : verdict `"8.x"`, confidence réduite.

**Effort réévalué :** **3h30** (dev + tests + corpus).

**Note packaging :** aucune dépendance nouvelle. **dovi_tool n'est PAS embarqué** en v7.5.0 (ffprobe suffit pour détection). Report à v7.6.0+ si conversion de profils devient nécessaire (voir backlog).

---

### §7 — Fake 4K / upscale detection ✅

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §7](NOTES_RECHERCHE_v7_5_0.md#§7--fake-4k--upscale-detection-)

**Prérequis :** §13 SSIM self-ref (pour la combinaison des 2 verdicts), §4 Scene detection (frames extraites utilisées).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : +6 constantes.
- [cinesort/domain/perceptual/upscale_detection.py](../../../cinesort/domain/perceptual/upscale_detection.py) : **nouveau module** (regroupe FFT 2D + combinaison avec SSIM §13).
- [cinesort/domain/perceptual/models.py](../../../cinesort/domain/perceptual/models.py) : +3 champs dans `VideoPerceptual`.
- [cinesort/domain/perceptual/video_analysis.py](../../../cinesort/domain/perceptual/video_analysis.py) : appel `compute_fft_hf_ratio()` après extraction frames.
- [CineSort.spec](../../../CineSort.spec) : +`cinesort.domain.perceptual.upscale_detection` aux `hiddenimports`.

**Signatures exactes :**

```python
# cinesort/domain/perceptual/upscale_detection.py

from __future__ import annotations
import logging
from statistics import median
from typing import Any, Optional

import numpy as np

from .constants import (
    FAKE_4K_FFT_HF_CUTOFF_RATIO,
    FAKE_4K_FFT_THRESHOLD_NATIVE,
    FAKE_4K_FFT_THRESHOLD_AMBIGUOUS,
    FAKE_4K_FFT_MIN_Y_AVG,
    FAKE_4K_FFT_MIN_VARIANCE,
    FAKE_4K_MIN_HEIGHT,
    SSIM_SELF_REF_FAKE_THRESHOLD,  # importé de §13
)

logger = logging.getLogger(__name__)


def compute_fft_hf_ratio(
    pixels: list[int],
    width: int,
    height: int,
    hf_cutoff_ratio: float = FAKE_4K_FFT_HF_CUTOFF_RATIO,
) -> float:
    """Calcule le ratio énergie haute fréquence / totale via FFT 2D.

    Algorithme :
        1. Reshape pixels en (height, width) float64.
        2. FFT 2D + shift (zero frequency au centre).
        3. Magnitude.
        4. Mask anneau extérieur (distance > hf_cutoff * min(h,w)/2).
        5. Ratio sum(|HF|²) / sum(|total|²).

    Returns: 0.0-1.0. 0.0 si erreur.
    """


def is_frame_usable_for_fft(
    pixels: list[int],
    width: int,
    height: int,
    y_avg: float,
    variance: Optional[float] = None,
) -> bool:
    """Filtre les frames non utilisables pour l'analyse FFT.

    Exclut :
        - frames trop sombres (y_avg < FAKE_4K_FFT_MIN_Y_AVG)
        - frames uniformes (variance < FAKE_4K_FFT_MIN_VARIANCE)
        - pixels tronqués (len < width * height * 0.9)

    Returns: True si utilisable.
    """


def compute_fft_hf_ratio_median(
    frames_data: list[dict[str, Any]],
    video_width: int,
    video_height: int,
) -> Optional[float]:
    """Calcule le ratio HF/Total médian sur les frames utilisables.

    Args:
        frames_data: frames extraites par extract_representative_frames (§4).
        video_width/height: résolution native pour cohérence calculs.

    Returns:
        float 0.0-1.0 médian des ratios, ou None si < 2 frames utilisables.
    """


def classify_fake_4k_fft(
    fft_hf_ratio: Optional[float],
    video_height: int,
    is_animation: bool,
) -> tuple[str, float]:
    """Classifie le ratio FFT en verdict.

    Verdicts (§7 seul) :
        "not_applicable_resolution" : height < FAKE_4K_MIN_HEIGHT
        "not_applicable_animation"  : is_animation
        "insufficient_frames"       : ratio is None
        "4k_native"                 : ratio ≥ FAKE_4K_FFT_THRESHOLD_NATIVE
        "ambiguous_2k_di"           : ratio 0.08-0.18, bitrate correct
        "fake_4k_bicubic"           : ratio < FAKE_4K_FFT_THRESHOLD_AMBIGUOUS

    Returns: (verdict, confidence).
    """


def combine_fake_4k_verdicts(
    fft_ratio: Optional[float],
    ssim_self_ref: Optional[float],
) -> tuple[str, float]:
    """Combine les verdicts FFT (§7) + SSIM self-ref (§13).

    Returns:
        "fake_4k_confirmed"      : les 2 concluent fake (confidence 0.95)
        "fake_4k_probable"       : un seul conclut fake (confidence 0.70)
        "4k_native"              : aucun ne conclut fake (confidence 0.90)
        "ambiguous"              : données partielles, verdict incertain
    """
```

```python
# models.py — ajouts dans VideoPerceptual

@dataclass
class VideoPerceptual:
    # ... champs existants + ceux du §13 SSIM ...

    # §7 Fake 4K FFT
    fft_hf_ratio_median: Optional[float] = None
    fake_4k_verdict_fft: str = "unknown"
    fake_4k_verdict_combined: str = "unknown"       # combinaison §7 + §13
    fake_4k_combined_confidence: float = 0.0
```

```python
# video_analysis.py — ajout après l'analyse existante

# --- §7 FFT HF ratio (si 4K et pas animation) ---
if video_height >= FAKE_4K_MIN_HEIGHT and not is_animation:
    fft_ratio = compute_fft_hf_ratio_median(frames_data, video_width, video_height)
    result.fft_hf_ratio_median = fft_ratio
    verdict_fft, _ = classify_fake_4k_fft(fft_ratio, video_height, is_animation)
    result.fake_4k_verdict_fft = verdict_fft

# --- Combinaison §7 + §13 SSIM self-ref ---
combined, conf = combine_fake_4k_verdicts(result.fft_hf_ratio_median, result.ssim_self_ref)
result.fake_4k_verdict_combined = combined
result.fake_4k_combined_confidence = conf
```

**Seuils et constantes :**

| Constante | Valeur | Rôle |
|---|---|---|
| `FAKE_4K_FFT_HF_CUTOFF_RATIO` | 0.25 | Dernier quart Nyquist spatial |
| `FAKE_4K_FFT_THRESHOLD_NATIVE` | 0.18 | ≥ : 4K native |
| `FAKE_4K_FFT_THRESHOLD_AMBIGUOUS` | 0.08 | < : upscale bicubique |
| `FAKE_4K_FFT_MIN_Y_AVG` | 20 | Skip frames trop sombres |
| `FAKE_4K_FFT_MIN_VARIANCE` | 200 | Skip frames uniformes |
| `FAKE_4K_MIN_HEIGHT` | 1800 | Skip si pas 4K |

**Ordre d'implémentation :**

1. **Étape 1 — Constantes** (5 min).
2. **Étape 2 — Modèles** : +3 champs dans `VideoPerceptual` (10 min).
3. **Étape 3 — Fonctions FFT pures** : `compute_fft_hf_ratio`, `is_frame_usable_for_fft` (1 h).
4. **Étape 4 — Tests FFT unitaires** : 8 tests (sinusoïde, bruit blanc, upscale bicubic simulé, frames sombres) (1 h).
5. **Étape 5 — Orchestration** : `compute_fft_hf_ratio_median`, `classify_fake_4k_fft`, `combine_fake_4k_verdicts` (45 min).
6. **Étape 6 — Tests orchestration** : 6 tests (30 min).
7. **Étape 7 — Intégration video_analysis** : après extraction frames, avant score composite (20 min).
8. **Étape 8 — Corpus validation** : 6 fichiers étiquetés (native UHD, remaster 2K DI, fake bicubic, fake Topaz AI, animation, 1080p) (1 h).

**Tests à écrire :**

```python
# tests/test_fake_4k_detection.py

class TestComputeFftHfRatio(unittest.TestCase):
    def test_pure_sine_high_frequency(self): ...       # HF ratio élevé
    def test_uniform_frame_ratio_zero(self): ...
    def test_white_noise_ratio_balanced(self): ...
    def test_upscale_bicubic_low_hf(self): ...         # simulé

class TestIsFrameUsable(unittest.TestCase):
    def test_dark_frame_rejected(self): ...
    def test_uniform_frame_rejected(self): ...
    def test_normal_frame_accepted(self): ...

class TestComputeFftHfRatioMedian(unittest.TestCase):
    def test_returns_median_of_multiple_frames(self): ...
    def test_filters_unusable_frames(self): ...
    def test_insufficient_frames_returns_none(self): ...

class TestClassifyFake4kFft(unittest.TestCase):
    def test_not_applicable_if_not_4k(self): ...
    def test_not_applicable_if_animation(self): ...
    def test_ratio_020_native(self): ...
    def test_ratio_010_ambiguous(self): ...
    def test_ratio_005_fake_bicubic(self): ...

class TestCombineVerdicts(unittest.TestCase):
    def test_both_fake_confirmed(self): ...
    def test_only_fft_fake_probable(self): ...
    def test_only_ssim_fake_probable(self): ...
    def test_none_fake_native(self): ...
    def test_both_none_ambiguous(self): ...

class TestCorpus(unittest.TestCase):
    def test_fixture_native_uhd_bluray(self): ...
    def test_fixture_fake_bicubic_upscale(self): ...
    def test_fixture_remaster_2k_di(self): ...         # attendu ambiguous
    def test_fixture_topaz_ai_upscale(self): ...       # attendu fake_4k_probable
    def test_fixture_animation_skip(self): ...
```

**Cas limites à tester explicitement :**

- Film 4K avec scènes très sombres (horror films) → peu de frames utilisables, verdict `insufficient_frames`.
- Film avec plan-séquence statique (Koyaanisqatsi) → frames uniformes, filtrées → `insufficient_frames` possible.
- Upscale IA très bon (Topaz v4.x) → FFT peut être trompé, mais SSIM reste bas → combiné `fake_4k_probable`.
- Film avec scanner 6K→4K : HF riches → `4k_native` correct.

**Effort réévalué :** **4h30** (FFT + orchestration + tests + corpus).

**Note packaging :** numpy déjà requis (§9 le nécessite). Module ajouté aux `hiddenimports` dans [CineSort.spec](../../../CineSort.spec).

---

### §8 — Interlacing, crop, judder, IMAX ✅

**Date du plan :** 2026-04-22
**Recherche :** [NOTES_RECHERCHE §8](NOTES_RECHERCHE_v7_5_0.md#§8--interlacing-crop-judder-)

**Prérequis :** §1 Parallélisme (pour lancer les 3-4 filtres FFmpeg en parallèle).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : +15 constantes.
- [cinesort/domain/perceptual/metadata_analysis.py](../../../cinesort/domain/perceptual/metadata_analysis.py) : **nouveau module** (idet + cropdetect + mpdecimate + IMAX).
- [cinesort/domain/perceptual/models.py](../../../cinesort/domain/perceptual/models.py) : +10 champs dans `VideoPerceptual`.
- [cinesort/ui/api/settings_support.py](../../../cinesort/ui/api/settings_support.py) : 3 nouveaux settings.
- [CineSort.spec](../../../CineSort.spec) : +module aux `hiddenimports`.

**Signatures exactes :**

```python
# cinesort/domain/perceptual/metadata_analysis.py

from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Optional

from .constants import (
    IDET_SEGMENT_DURATION_S, IDET_INTERLACE_RATIO_THRESHOLD,
    CROPDETECT_SEGMENT_DURATION_S, CROPDETECT_LIMIT, CROPDETECT_ROUND,
    MPDECIMATE_SEGMENT_DURATION_S,
    MPDECIMATE_JUDDER_LIGHT, MPDECIMATE_JUDDER_PULLDOWN, MPDECIMATE_JUDDER_HEAVY,
    IMAX_AR_FULL_FRAME_MIN, IMAX_AR_FULL_FRAME_MAX,
    IMAX_AR_DIGITAL_MIN, IMAX_AR_DIGITAL_MAX,
    IMAX_EXPANSION_AR_DELTA, IMAX_NATIVE_RESOLUTION_MIN_HEIGHT,
    IMAX_EXPANSION_SEGMENTS_COUNT,
)
from .ffmpeg_runner import run_ffmpeg_text

logger = logging.getLogger(__name__)

_RE_IDET_MULTI = re.compile(
    r"Multi frame detection:\s*TFF:\s*(\d+)\s*BFF:\s*(\d+)\s*Progressive:\s*(\d+)\s*Undetermined:\s*(\d+)"
)
_RE_CROP = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")
_RE_MPDECIMATE = re.compile(r"drop\s+pts:|keep\s+pts:")


@dataclass(frozen=True)
class InterlaceInfo:
    detected: bool
    interlace_type: str       # "progressive" | "tff" | "bff" | "mixed" | "unknown"
    tff_count: int
    bff_count: int
    progressive_count: int


@dataclass(frozen=True)
class CropSegment:
    start_s: float
    crop_w: int
    crop_h: int
    crop_x: int
    crop_y: int
    aspect_ratio: float


@dataclass(frozen=True)
class CropInfo:
    has_bars: bool
    verdict: str              # "full_frame" | "letterbox_2_35" | "letterbox_2_39" |
                              # "pillarbox" | "windowbox" | "letterbox_other"
    detected_w: int
    detected_h: int
    aspect_ratio: float
    segments: list[CropSegment]  # pour détection IMAX Expansion


@dataclass(frozen=True)
class JudderInfo:
    drop_count: int
    keep_count: int
    drop_ratio: float
    verdict: str              # "judder_none" | "judder_light" | "pulldown_3_2_suspect" | "judder_heavy"


@dataclass(frozen=True)
class ImaxInfo:
    is_imax: bool
    imax_type: str            # "none" | "full_frame_143" | "digital_190" |
                              # "expansion" | "native_high_resolution" | "tmdb_keyword"
    confidence: float
    aspect_ratios_observed: list[float]  # de cropdetect multi-segments


# --- Fonctions d'analyse ---

def detect_interlacing(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    timeout_s: float = 30.0,
) -> InterlaceInfo:
    """Lance `ffmpeg -vf idet` sur 30 s, parse 'Multi frame detection'."""


def detect_crop_single_segment(
    ffmpeg_path: str,
    media_path: str,
    start_s: float,
    duration_s: float = CROPDETECT_SEGMENT_DURATION_S,
    timeout_s: float = 30.0,
) -> Optional[CropSegment]:
    """Lance `ffmpeg -vf cropdetect` sur UN segment.

    Parse la dernière ligne 'crop=W:H:X:Y'.
    """


def detect_crop_multi_segments(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    n_segments: int = IMAX_EXPANSION_SEGMENTS_COUNT,
) -> list[CropSegment]:
    """Lance cropdetect sur N segments répartis (début, milieu, fin).

    Utilisé pour détecter IMAX Expansion (variations d'aspect ratio).
    """


def classify_crop(
    segments: list[CropSegment],
    orig_w: int,
    orig_h: int,
) -> CropInfo:
    """Classifie le crop final à partir des segments analysés.

    Si plusieurs segments avec aspect ratio variable → garde le premier et flag
    dans ImaxInfo (expansion détectée).
    """


def detect_judder(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    timeout_s: float = 30.0,
) -> JudderInfo:
    """Lance `ffmpeg -vf mpdecimate`, compte drop/keep."""


def classify_imax(
    probe_width: int,
    probe_height: int,
    crop_segments: list[CropSegment],
    tmdb_keywords: list[str],
) -> ImaxInfo:
    """Classifie le format IMAX via 4 méthodes (voir NOTES §8.4).

    Priorité :
        1. Expansion via variabilité aspect ratio segments
        2. Aspect ratio container (1.43 ou 1.90)
        3. Résolution native > 2600p
        4. Cross-check tmdb.keywords
    """


def analyze_metadata_filters(
    ffmpeg_path: str,
    media_path: str,
    duration_s: float,
    probe_width: int,
    probe_height: int,
    tmdb_keywords: list[str],
    enable_interlacing: bool = True,
    enable_crop: bool = True,
    enable_judder: bool = False,
) -> dict:
    """Orchestrateur : lance les 3 filtres (selon settings) + classification IMAX.

    Peut être appelé depuis un ThreadPool §1 pour parallélisation.

    Returns:
        {
            "interlace": InterlaceInfo,
            "crop": CropInfo,
            "judder": JudderInfo or None if disabled,
            "imax": ImaxInfo,
        }
    """
```

```python
# models.py — ajouts dans VideoPerceptual

@dataclass
class VideoPerceptual:
    # ... champs existants ...

    # §8.1 Interlacing
    interlaced_detected: bool = False
    interlace_type: str = "progressive"

    # §8.2 Crop
    crop_has_bars: bool = False
    crop_verdict: str = "full_frame"
    detected_aspect_ratio: float = 0.0
    detected_crop_w: int = 0
    detected_crop_h: int = 0

    # §8.3 Judder
    judder_ratio: float = 0.0
    judder_verdict: str = "judder_none"

    # §8.4 IMAX
    is_imax: bool = False
    imax_type: str = "none"
    imax_confidence: float = 0.0
```

**Seuils et constantes :**

```python
# constants.py ajouts

# Interlacing
IDET_SEGMENT_DURATION_S = 30
IDET_INTERLACE_RATIO_THRESHOLD = 0.3

# Crop
CROPDETECT_SEGMENT_DURATION_S = 60
CROPDETECT_LIMIT = 24
CROPDETECT_ROUND = 16

# Judder
MPDECIMATE_SEGMENT_DURATION_S = 30
MPDECIMATE_JUDDER_LIGHT = 0.05
MPDECIMATE_JUDDER_PULLDOWN = 0.15
MPDECIMATE_JUDDER_HEAVY = 0.25

# IMAX
IMAX_AR_FULL_FRAME_MIN = 1.40
IMAX_AR_FULL_FRAME_MAX = 1.46
IMAX_AR_DIGITAL_MIN = 1.88
IMAX_AR_DIGITAL_MAX = 1.92
IMAX_EXPANSION_AR_DELTA = 0.3
IMAX_NATIVE_RESOLUTION_MIN_HEIGHT = 2600
IMAX_EXPANSION_SEGMENTS_COUNT = 3
```

**Settings ajoutés :**

```python
# settings_support.py ajouts
"perceptual_interlacing_detection_enabled": True,
"perceptual_crop_detection_enabled": True,
"perceptual_judder_detection_enabled": False,       # opt-in car rare
# IMAX est automatique (dérive de crop + résolution, pas de setting)
```

**Ordre d'implémentation :**

1. **Étape 1 — Constantes** : 15 constantes (10 min).
2. **Étape 2 — Modèles** : +10 champs dans `VideoPerceptual` (20 min).
3. **Étape 3 — Dataclasses internes** : InterlaceInfo, CropSegment, CropInfo, JudderInfo, ImaxInfo (15 min).
4. **Étape 4 — Fonctions idet** : `detect_interlacing` + regex parse + classify (45 min).
5. **Étape 5 — Fonctions cropdetect** : `detect_crop_single_segment` + `detect_crop_multi_segments` + `classify_crop` (1 h).
6. **Étape 6 — Fonctions mpdecimate** : `detect_judder` (30 min).
7. **Étape 7 — Fonctions IMAX** : `classify_imax` avec 4 méthodes priorisées (45 min).
8. **Étape 8 — Orchestrateur parallèle** : `analyze_metadata_filters` lance les 3-4 filtres via ThreadPoolExecutor (§1) (30 min).
9. **Étape 9 — Tests unitaires** : 18 tests (parsing idet/crop/mpdecimate, classify IMAX) (2 h).
10. **Étape 10 — Settings** : 3 settings + validation (15 min).
11. **Étape 11 — Intégration video_analysis** : appel `analyze_metadata_filters` dans le pipeline (30 min).
12. **Étape 12 — Corpus validation** : 8 fichiers étiquetés (progressive/interlaced DVD rip, letterbox 2.35, full frame, pulldown 3:2, IMAX Full Frame 1.43, IMAX Digital 1.90, IMAX Expansion Dune, IMAX natif 6K) (1 h 30).

**Tests à écrire :**

```python
# tests/test_metadata_filters.py

class TestDetectInterlacing(unittest.TestCase):
    def test_parse_multi_frame_output(self): ...
    def test_tff_dominant_flagged(self): ...
    def test_progressive_normal(self): ...

class TestDetectCrop(unittest.TestCase):
    def test_parse_crop_line(self): ...
    def test_letterbox_2_35_verdict(self): ...
    def test_full_frame_no_bars(self): ...
    def test_pillarbox_vertical_bars(self): ...
    def test_cropdetect_fluctuating_segments(self): ...     # IMAX Expansion

class TestDetectJudder(unittest.TestCase):
    def test_count_drops_and_keeps(self): ...
    def test_ratio_005_none(self): ...
    def test_ratio_020_pulldown_3_2(self): ...

class TestClassifyImax(unittest.TestCase):
    def test_ar_143_full_frame(self): ...
    def test_ar_190_digital(self): ...
    def test_expansion_variable_ar(self): ...
    def test_native_high_resolution_above_2600p(self): ...
    def test_tmdb_keyword_low_confidence(self): ...
    def test_no_imax_standard_film(self): ...

class TestAnalyzeMetadataFilters(unittest.TestCase):
    def test_all_filters_run_in_parallel(self): ...       # mock timing
    def test_disabled_judder_not_called(self): ...
    def test_ffmpeg_error_on_one_filter_continues_others(self): ...

class TestCorpus(unittest.TestCase):
    def test_dvd_rip_interlaced(self): ...
    def test_bluray_letterbox_2_39(self): ...
    def test_dune_2021_imax_expansion(self): ...
    def test_dark_knight_imax_expansion(self): ...
    def test_standard_16_9_no_imax(self): ...
```

**Cas limites à tester explicitement :**

- Film 1080p 16:9 standard : tous les verdicts `none` / `progressive` / `full_frame`.
- Rip DVD NTSC interlaced + pulldown : interlace=true + judder=pulldown.
- Fichier avec container 1920×1080 mais contenu cropped 1920×816 → letterbox 2.35.
- IMAX Expansion (Dune) : 3 segments, aspect 2.39/1.78/2.39 → `imax_type="expansion"`.
- IMAX pure 1.43:1 (rare) : aspect container 1.43 → `imax_type="full_frame_143"`.
- Vidéo 6K (8192×4320) : height > 2600 → `imax_type="native_high_resolution"`.
- ffmpeg filter échoue (codec exotique) : try/except, skip ce filtre, continue les autres.

**Effort réévalué :** **9h** (4h dev + 2h tests + 1h30 corpus + 30 min settings + 30 min integration + 30 min IMAX tests edge).

**Note packaging :** aucune dépendance nouvelle. Parallélisation via §1 indispensable pour éviter un pipeline de 30-40 s séquentiel.

**Récapitulatif Vague 3 :**

| § | Effort |
|---|---|
| §5 HDR metadata (+HDR10+) | 6h |
| §6 Dolby Vision | 3h30 |
| §7 Fake 4K FFT | 4h30 |
| §8 Interlacing/crop/judder/IMAX | 9h |
| **Total Vague 3** | **~23h** |

---

## Vague 4 — Cœur expert

### §15 — Grain intelligence avancée ✅ (section phare)

**Date du plan :** 2026-04-23
**Recherche :** [NOTES_RECHERCHE §15](NOTES_RECHERCHE_v7_5_0.md#§15--grain-intelligence-avancée--section-phare-v750)

**Prérequis :**
- §1 Parallélisme (le grain sain vs encode nécessite FFT temporelle sur plusieurs frames, parallélisable).
- §4 Scene detection (frames extraites utilisées pour l'analyse temporelle).
- §7 Fake 4K FFT (réutilise le FFT 2D helper pour l'autocorrélation spatiale).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : +25 constantes grain v2.
- [cinesort/domain/perceptual/grain_signatures.py](../../../cinesort/domain/perceptual/grain_signatures.py) : **nouveau module** (base de connaissances signatures).
- [cinesort/domain/perceptual/grain_classifier.py](../../../cinesort/domain/perceptual/grain_classifier.py) : **nouveau module** (grain sain vs encode, DNR partiel).
- [cinesort/domain/perceptual/av1_grain_metadata.py](../../../cinesort/domain/perceptual/av1_grain_metadata.py) : **nouveau module** (extraction AFGS1).
- [cinesort/domain/perceptual/grain_analysis.py](../../../cinesort/domain/perceptual/grain_analysis.py) : **refactor** — intègre classification v2, appelle les 3 nouveaux modules.
- [cinesort/domain/perceptual/models.py](../../../cinesort/domain/perceptual/models.py) : +14 champs dans `GrainAnalysis`.
- [cinesort/ui/api/settings_support.py](../../../cinesort/ui/api/settings_support.py) : setting `perceptual_grain_intelligence_enabled` (défaut `True`).
- [CineSort.spec](../../../CineSort.spec) : +3 modules aux `hiddenimports`.

**Signatures exactes :**

##### Module 1 : `grain_signatures.py`

```python
# cinesort/domain/perceptual/grain_signatures.py

from __future__ import annotations
from typing import Any, Optional
from .constants import GRAIN_PROFILE_BY_ERA_V2, GRAIN_SIGNATURES_EXCEPTIONS


def classify_film_era_v2(year: int, film_format: Optional[str] = None) -> str:
    """Classifie l'ère en 6 bandes (v2) + exception 70mm large format.

    Args:
        year: année de production TMDb.
        film_format: optionnel, "70mm" force la bande "large_format_classic".

    Returns: une des valeurs de GRAIN_ERA_V2 keys ou "large_format_classic" | "unknown".
    """


def detect_film_format_hint(
    video_height: int,
    tmdb_runtime_min: int,
    tmdb_keywords: list[str],
    year: int,
) -> Optional[str]:
    """Heuristique pour détecter format 70mm / IMAX Film.

    Indices :
        - tmdb keywords contient "70mm" ou "imax film"
        - résolution native > 4320p + année < 2000 (scan cinéma archive)
        - runtime > 150 min ET année < 1990 (épopée 70mm probable)

    Returns: "70mm" | None.
    """


def get_expected_grain_signature(
    era: str,
    genres: list[str],
    budget: int,
    companies: list[str],
    country: Optional[str] = None,
) -> dict[str, Any]:
    """Retourne la signature grain attendue.

    Priorité : GRAIN_SIGNATURES_EXCEPTIONS (ordonné) > GRAIN_PROFILE_BY_ERA_V2[era].

    Returns: dict avec clés level_mean, level_tolerance, uniformity_max,
             texture_variance_baseline, confidence, label.
    """


def _rule_matches(rule: dict, era: str, genres: list[str],
                  budget: int, companies: list[str], country: Optional[str]) -> bool:
    """Teste si une règle d'exception matche le contexte."""


# Table de connaissances (éditée à la main, pas calibrée ML)
# À enrichir via tests/fixtures/grain_intelligence au fil du temps.
```

##### Module 2 : `av1_grain_metadata.py`

```python
# cinesort/domain/perceptual/av1_grain_metadata.py

from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from .ffmpeg_runner import run_ffmpeg_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Av1FilmGrainInfo:
    present: bool
    apply_grain: bool                 # flag AV1 apply_grain (frame header)
    grain_seed: Optional[int]         # reproducible seed
    ar_coeff_lag: Optional[int]       # 0-3, autoregressive lag
    num_y_points: Optional[int]       # nombre de scaling points
    has_afgs1_t35: bool               # ITU-T T.35 AOMedia metadata détectée
    raw_params: Optional[dict]        # payload brut pour debug


def extract_av1_film_grain_params(
    ffprobe_path: str,
    media_path: str,
    timeout_s: float = 10.0,
) -> Optional[Av1FilmGrainInfo]:
    """Extrait les paramètres film grain AV1 via ffprobe.

    Commande :
      ffprobe -select_streams v -show_entries
        "stream=codec_name,profile,side_data_list"
        -print_format json <file>

    Returns:
        Av1FilmGrainInfo si codec=av1 avec grain metadata, None sinon.
    """


def has_afgs1_in_side_data(side_data_list: list[dict]) -> bool:
    """Cherche ITU-T T.35 AFGS1 payload dans side_data_list.

    Pattern : country_code=0xB5 (USA) + provider_code=0x5890 (AOMedia).
    """
```

##### Module 3 : `grain_classifier.py` (cœur technique)

```python
# cinesort/domain/perceptual/grain_classifier.py

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .constants import (
    GRAIN_TEMPORAL_CORR_AUTHENTIC, GRAIN_TEMPORAL_CORR_ENCODE,
    GRAIN_SPATIAL_LAG_PEAK_RATIO, GRAIN_CROSS_COLOR_CORR_AUTHENTIC,
    DNR_PARTIAL_TEXTURE_RATIO,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GrainNatureVerdict:
    nature: str                       # "film_grain" | "encode_noise" | "post_added" | "ambiguous"
    confidence: float                 # 0.0-1.0
    temporal_corr: float              # mesure temporelle
    spatial_lag8_ratio: float         # pic lag8 / lag1
    spatial_lag16_ratio: float        # pic lag16 / lag1
    cross_color_corr: Optional[float] # None si N&B ou Y seul


@dataclass(frozen=True)
class DnrPartialVerdict:
    is_partial_dnr: bool
    texture_loss_ratio: float         # 0.0-1.0
    texture_actual: float
    texture_baseline: float
    detail_fr: str                    # texte FR pour UI


# --- Détection zones plates ---

def find_flat_zones(
    frame_y: np.ndarray,
    block_size: int = 16,
    flat_threshold: float = 100.0,
    max_zones: int = 20,
) -> list[tuple[int, int, int, int]]:
    """Trouve les zones plates (low variance) d'une frame luminance.

    Returns:
        Liste de (y, x, h, w) des blocs plats, limitée à max_zones.
    """


# --- Corrélation temporelle ---

def compute_temporal_correlation(
    frames_y: list[np.ndarray],
    flat_zones_per_frame: list[list[tuple]],
) -> float:
    """Corrélation Pearson du bruit entre frames consécutives.

    Compare block(frame_i) vs block(frame_{i+1}) sur zones plates alignées.

    Returns: corrélation moyenne 0.0-1.0. 0.0 si impossible.
    """


# --- Autocorrélation spatiale 8 directions ---

def compute_spatial_autocorr_8dir(
    frame_y: np.ndarray,
    flat_zones: list[tuple],
    lags: list[int] = [1, 8, 16],
) -> dict[int, float]:
    """Autocorrélation à 8 directions, pour chaque lag donné.

    Algorithme :
        Pour chaque direction (dy, dx) ∈ 8 voisins :
          corr = mean( block * shift(block, dy, dx) )
        Retour : moyenne des 8 directions pour chaque lag.

    Returns:
        {1: mean_corr_lag1, 8: mean_corr_lag8, 16: mean_corr_lag16}
    """


# --- Cross-color correlation ---

def compute_cross_color_correlation(
    frames_rgb: Optional[list[np.ndarray]],
    flat_zones_per_frame: list[list[tuple]],
) -> Optional[float]:
    """Corrélation moyenne (R-G) + (G-B) + (R-B) sur zones plates.

    Returns: float 0.0-1.0 ou None si RGB indisponible (frames Y seulement).
    """


# --- Verdict grain nature ---

def classify_grain_nature(
    frames_y: list[np.ndarray],
    frames_rgb: Optional[list[np.ndarray]],
) -> GrainNatureVerdict:
    """Classifie la nature du grain/bruit détecté.

    Combine 3 métriques (poids 50/30/20) :
        - temporal_corr (temporal low = film_grain, high = encode_noise)
        - spatial autocorr lag8/lag16 vs lag1 (pics = encode DCT)
        - cross_color_corr (high = film, low = encode séparé)

    Returns: GrainNatureVerdict.
    """


# --- DNR partiel ---

def detect_partial_dnr(
    frames_y: list[np.ndarray],
    grain_level: float,
    texture_variance_baseline: float,
) -> DnrPartialVerdict:
    """Détecte le DNR partiel via ratio texture_actual / baseline.

    Zones textures = variance entre 10 et 500 (ni plat, ni détail fort).
    Si ratio < 0.7 ET grain_level < 1.5 → DNR partiel suspect.

    Returns: DnrPartialVerdict avec détail FR.
    """
```

##### Module 4 : `grain_analysis.py` (refactor)

```python
# cinesort/domain/perceptual/grain_analysis.py — modifications

# ANCIEN code : classify_film_era, analyze_grain (existant, ~350L)

# NOUVEAU : analyze_grain_v2 qui wrappe l'ancien + ajoute les nouvelles briques

def analyze_grain_v2(
    frames_data: list[dict[str, Any]],
    video_blur_mean: float,
    tmdb_metadata: Optional[dict[str, Any]],
    bit_depth: int,
    tmdb_year: int,
    av1_grain_info: Optional[Av1FilmGrainInfo] = None,
) -> GrainAnalysis:
    """Version 2 enrichie de analyze_grain.

    Ajoute :
        - Classification ère v2 (6 bandes + 70mm exception)
        - Signature attendue par contexte
        - Classification nature grain (film vs encode)
        - Détection DNR partiel
        - Bonus AV1 AFGS1 si metadata présente
        - Texte contexte historique FR

    Returns: GrainAnalysis enrichi (14 champs supplémentaires).
    """
    # 1. Analyse existante (conservée pour backward compat)
    result = analyze_grain(frames_data, video_blur_mean, tmdb_metadata, bit_depth, tmdb_year)

    # 2. Ère v2
    era_v2 = classify_film_era_v2(tmdb_year, film_format=_detect_format(tmdb_metadata))
    result.film_era_v2 = era_v2

    # 3. Signature attendue
    signature = get_expected_grain_signature(era_v2, genres=..., budget=..., companies=...)
    result.expected_grain_level = signature["level_mean"]
    result.expected_grain_uniformity_max = signature["uniformity_max"]

    # 4. Classification nature grain (si frames disponibles)
    if len(frames_data) >= 3:
        frames_y = [np.array(f["pixels"]).reshape(f["height"], f["width"]) for f in frames_data]
        nature_verdict = classify_grain_nature(frames_y, frames_rgb=None)
        result.grain_nature = nature_verdict.nature
        result.grain_nature_confidence = nature_verdict.confidence
        result.temporal_correlation = nature_verdict.temporal_corr
        result.spatial_lag8_ratio = nature_verdict.spatial_lag8_ratio

    # 5. DNR partiel
    dnr_verdict = detect_partial_dnr(frames_y, result.grain_level,
                                      signature.get("texture_variance_baseline", 150.0))
    result.is_partial_dnr = dnr_verdict.is_partial_dnr
    result.texture_loss_ratio = dnr_verdict.texture_loss_ratio

    # 6. Bonus AV1
    if av1_grain_info and av1_grain_info.present and av1_grain_info.apply_grain:
        result.av1_afgs1_present = True
        result.score += GRAIN_AV1_AFGS1_BONUS
        result.score = min(100, result.score)

    # 7. Contexte historique FR
    result.historical_context_fr = build_grain_historical_context(
        result, era_v2, signature, tmdb_metadata
    )

    return result


def build_grain_historical_context(
    grain: GrainAnalysis,
    era: str,
    signature: dict,
    tmdb_metadata: Optional[dict],
) -> str:
    """Construit le bloc texte FR pour la modale UI.

    Format : 8 lignes avec mesures + interprétation humaine.
    """
```

##### Modèles (`models.py`)

```python
# models.py — ajouts dans GrainAnalysis

@dataclass
class GrainAnalysis:
    # ... champs existants ...

    # §15 — Grain Intelligence v2
    film_era_v2: str = "unknown"                    # 6 bandes + large_format
    film_format_detected: Optional[str] = None       # "70mm" si IMAX Film

    # Signature attendue
    expected_grain_level: float = 0.0
    expected_grain_tolerance: float = 0.0
    expected_grain_uniformity_max: float = 0.0
    signature_label: str = "default_era_profile"

    # Nature grain
    grain_nature: str = "unknown"                    # "film_grain" | "encode_noise" | "post_added" | "ambiguous"
    grain_nature_confidence: float = 0.0
    temporal_correlation: float = 0.0
    spatial_lag8_ratio: float = 0.0
    spatial_lag16_ratio: float = 0.0
    cross_color_correlation: Optional[float] = None

    # DNR partiel
    is_partial_dnr: bool = False
    texture_loss_ratio: float = 0.0
    texture_variance_actual: float = 0.0
    texture_variance_baseline: float = 0.0

    # AV1 AFGS1
    av1_afgs1_present: bool = False

    # Contexte historique (texte FR pour UI)
    historical_context_fr: str = ""
```

**Constantes (`constants.py`)**

```python
# constants.py ajouts

# --- Ères v2 (6 bandes + large format) ---
GRAIN_ERA_V2 = {
    "16mm_era": 1980,
    "35mm_classic": 1999,
    "late_film": 2006,
    "transition": 2013,
    "digital_modern": 2021,
    "digital_hdr_era": 9999,
}

# --- Profils attendus par ère ---
GRAIN_PROFILE_BY_ERA_V2 = {
    "16mm_era":      {"level_mean": 4.5, "level_tolerance": 1.5, "uniformity_max": 0.75, "texture_variance_baseline": 250.0},
    "35mm_classic":  {"level_mean": 3.0, "level_tolerance": 1.0, "uniformity_max": 0.80, "texture_variance_baseline": 180.0},
    "late_film":     {"level_mean": 2.0, "level_tolerance": 0.8, "uniformity_max": 0.82, "texture_variance_baseline": 150.0},
    "transition":    {"level_mean": 1.5, "level_tolerance": 1.0, "uniformity_max": 0.85, "texture_variance_baseline": 130.0},
    "digital_modern":{"level_mean": 0.5, "level_tolerance": 0.5, "uniformity_max": 0.90, "texture_variance_baseline": 120.0},
    "digital_hdr_era":{"level_mean": 0.3, "level_tolerance": 0.3, "uniformity_max": 0.92, "texture_variance_baseline": 140.0},
    "large_format_classic": {"level_mean": 1.8, "level_tolerance": 0.8, "uniformity_max": 0.85, "texture_variance_baseline": 140.0},
}

# --- Règles d'exception (matchées en ordre, spécifique d'abord) ---
GRAIN_SIGNATURES_EXCEPTIONS = [
    # Animation : jamais de grain
    {"era": "*", "genres_any": ["Animation", "animation"], "level_mean": 0.0,
     "level_tolerance": 0.3, "uniformity_max": 0.95, "texture_variance_baseline": 80.0,
     "label": "animation_aplats"},

    # Horror 16mm : grain élevé
    {"era": "16mm_era", "genres_any": ["Horror", "horror"], "level_mean": 4.8,
     "level_tolerance": 1.2, "uniformity_max": 0.70, "texture_variance_baseline": 280.0,
     "label": "16mm_horror_grain"},

    # A24 / Focus : esthétique grain intentionnel même en digital
    {"era": "digital_modern", "companies_any": ["A24", "Focus Features"],
     "level_mean": 1.8, "level_tolerance": 1.0, "uniformity_max": 0.82,
     "texture_variance_baseline": 160.0, "label": "a24_filmic_aesthetic"},

    # Nolan digital era : grain intentionnel IMAX/70mm
    {"era_any": ["digital_modern", "digital_hdr_era"],
     "companies_any": ["Syncopy"], "level_mean": 1.5, "level_tolerance": 0.8,
     "uniformity_max": 0.82, "texture_variance_baseline": 150.0,
     "label": "nolan_intentional_grain"},

    # Pixar/Dreamworks/Disney animation haute-def : aplats parfaits
    {"era": "*", "companies_any": ["Pixar", "DreamWorks Animation", "Walt Disney Animation Studios"],
     "level_mean": 0.0, "level_tolerance": 0.2, "uniformity_max": 0.95,
     "texture_variance_baseline": 70.0, "label": "major_animation_studio"},

    # (À enrichir progressivement avec les retours utilisateurs)
]

# --- Grain Classifier thresholds ---
GRAIN_TEMPORAL_CORR_AUTHENTIC = 0.2       # < 0.2 : grain argentique
GRAIN_TEMPORAL_CORR_ENCODE = 0.7          # > 0.7 : encode noise
GRAIN_SPATIAL_LAG_PEAK_RATIO = 1.3        # pics lag8/16 vs lag1
GRAIN_CROSS_COLOR_CORR_AUTHENTIC = 0.6    # high = film grain
GRAIN_NATURE_WEIGHT_TEMPORAL = 0.5
GRAIN_NATURE_WEIGHT_SPATIAL = 0.3
GRAIN_NATURE_WEIGHT_CROSS_COLOR = 0.2

# --- DNR partiel ---
DNR_PARTIAL_TEXTURE_RATIO = 0.7
DNR_PARTIAL_GRAIN_LEVEL_MAX = 1.5         # DNR partiel possible seulement si grain faible

# --- AV1 AFGS1 bonus ---
GRAIN_AV1_AFGS1_BONUS = 15                # points visuel

# --- Flat zones detection ---
FLAT_ZONE_VARIANCE_THRESHOLD = 100.0
FLAT_ZONE_BLOCK_SIZE = 16
FLAT_ZONE_MAX_COUNT = 20

# --- Texture zones (pour DNR partiel) ---
TEXTURE_ZONE_VARIANCE_MIN = 10.0
TEXTURE_ZONE_VARIANCE_MAX = 500.0
```

**Ordre d'implémentation :**

1. **Étape 1 — Constantes v2** : 25 constantes + table GRAIN_SIGNATURES_EXCEPTIONS (20 min).
2. **Étape 2 — Modèles** : +14 champs dans `GrainAnalysis` (20 min).
3. **Étape 3 — Module `grain_signatures.py`** : classification v2, détection format, règles exceptions (1 h 30).
4. **Étape 4 — Tests signatures** : 15 tests (classification ère, matching règles, priorité spécificité) (1 h).
5. **Étape 5 — Module `av1_grain_metadata.py`** : extraction AFGS1 via ffprobe (1 h).
6. **Étape 6 — Tests AV1** : 6 tests (fichier AV1 avec/sans AFGS1, codec non-AV1, ffprobe error) (30 min).
7. **Étape 7 — Module `grain_classifier.py` — partie plate + temporel** : `find_flat_zones`, `compute_temporal_correlation` (1 h 30).
8. **Étape 8 — Module `grain_classifier.py` — partie spatial + cross-color** : autocorr 8-dir, cross-color correlation (2 h).
9. **Étape 9 — Verdict nature grain** : `classify_grain_nature` avec pondérations (1 h).
10. **Étape 10 — DNR partiel** : `detect_partial_dnr` + texte FR (45 min).
11. **Étape 11 — Tests classifier** : 20 tests (temporal, spatial, cross, verdicts, DNR) (2 h).
12. **Étape 12 — Refactor `grain_analysis.py` → `analyze_grain_v2`** : intégration des 3 nouveaux modules (1 h 30).
13. **Étape 13 — Fonction `build_grain_historical_context`** : génération texte FR (1 h).
14. **Étape 14 — Setting + intégration pipeline** : `perceptual_grain_intelligence_enabled` + appel depuis `perceptual_support.py` (30 min).
15. **Étape 15 — CineSort.spec hiddenimports** : 3 nouveaux modules (5 min).
16. **Étape 16 — Corpus fixtures** : 30 films étiquetés dans `tests/fixtures/grain_intelligence/` avec structure (path, metadata_tmdb, expected_verdict) (2 h 30).
17. **Étape 17 — Tests intégration + corpus validation** : 12 tests corpus (2 h).

**Tests à écrire :**

```python
# tests/test_grain_intelligence.py  (~70 tests au total)

class TestClassifyFilmEraV2(unittest.TestCase):
    def test_1975_returns_16mm_era(self): ...
    def test_1985_returns_35mm_classic(self): ...
    def test_2003_returns_late_film(self): ...
    def test_2010_returns_transition(self): ...
    def test_2018_returns_digital_modern(self): ...
    def test_2023_returns_digital_hdr_era(self): ...
    def test_unknown_year_returns_unknown(self): ...
    def test_70mm_override_returns_large_format(self): ...

class TestGetExpectedGrainSignature(unittest.TestCase):
    def test_animation_returns_aplats(self): ...
    def test_16mm_horror_specific_rule(self): ...
    def test_a24_digital_filmic_rule(self): ...
    def test_nolan_syncopy_rule(self): ...
    def test_pixar_animation_rule(self): ...
    def test_no_match_fallback_to_era_profile(self): ...
    def test_rule_priority_specificity_order(self): ...

class TestDetectFilmFormatHint(unittest.TestCase):
    def test_70mm_keyword_returns_70mm(self): ...
    def test_resolution_8k_pre_2000_returns_70mm(self): ...
    def test_runtime_180_pre_1990_returns_70mm(self): ...
    def test_modern_high_res_returns_none(self): ...

class TestExtractAv1FilmGrainParams(unittest.TestCase):
    def test_av1_with_afgs1_detected(self): ...
    def test_av1_without_afgs1(self): ...
    def test_hevc_codec_returns_none(self): ...
    def test_ffprobe_error_returns_none(self): ...

class TestFindFlatZones(unittest.TestCase):
    def test_returns_low_variance_blocks(self): ...
    def test_respects_max_zones(self): ...
    def test_empty_frame_returns_empty(self): ...

class TestComputeTemporalCorrelation(unittest.TestCase):
    def test_identical_frames_returns_1(self): ...    # même bruit = corrélation 1
    def test_random_frames_returns_near_0(self): ...  # grain différent = ~0
    def test_block_noise_returns_high(self): ...      # encode noise = > 0.7

class TestComputeSpatialAutocorr8dir(unittest.TestCase):
    def test_white_noise_no_peaks(self): ...
    def test_block_aligned_pattern_peaks_at_lag8(self): ...
    def test_isotropic_grain_uniform_decay(self): ...

class TestCrossColorCorrelation(unittest.TestCase):
    def test_film_grain_high_corr(self): ...
    def test_encode_noise_low_corr(self): ...
    def test_grayscale_returns_none(self): ...

class TestClassifyGrainNature(unittest.TestCase):
    def test_film_grain_verdict(self): ...
    def test_encode_noise_verdict(self): ...
    def test_post_added_verdict(self): ...             # pattern synthétique spécifique
    def test_ambiguous_verdict(self): ...
    def test_confidence_computed_correctly(self): ...

class TestDetectPartialDnr(unittest.TestCase):
    def test_normal_texture_not_dnr(self): ...
    def test_low_texture_grain_low_is_dnr(self): ...
    def test_low_texture_grain_high_not_dnr(self): ... # grain présent = pas DNR
    def test_fr_detail_text_generated(self): ...

class TestBuildHistoricalContextFr(unittest.TestCase):
    def test_contains_era_label(self): ...
    def test_contains_expected_values(self): ...
    def test_contains_measured_values(self): ...
    def test_fr_wording_correct(self): ...

class TestCorpus(unittest.TestCase):
    """Validation empirique sur fixtures."""
    def test_blade_runner_1982_uhd_grain_authentic(self): ...
    def test_blade_runner_1982_blu_2007_dnr_aggressive(self): ...
    def test_oppenheimer_2023_imax_grain_added(self): ...
    def test_soul_pixar_2020_animation_skip(self): ...
    def test_mad_max_fury_road_2015_clean_digital(self): ...
    def test_av1_afgs1_bonus_applied(self): ...
    def test_16mm_horror_hammer_70s_high_grain(self): ...
```

**Cas limites à tester explicitement :**

- Film < 90 s (bonus, trailer) : skip analyse temporelle (pas assez de frames), fallback sur grain_level seul.
- Tous les pixels N&B : cross_color_correlation retourne None, pondération redistribuée (50% temporal + 50% spatial, 0% cross).
- Moins de 3 frames valides extraites : verdict `insufficient_frames`, grain_nature = "unknown".
- AV1 avec AFGS1 mais bitrate très bas (grain re-synthétisé mal) : fallback analyse pixel.
- Film post-2020 à grain intentionnel (Nolan) : signature spécifique via règle companies_any Syncopy.
- Animation avec grain mesuré > 0.5 : faux positif possible. Règle "animation_aplats" prime → verdict forcé `not_applicable_animation`.
- Film 70mm Imax mal taggé TMDb : fallback sur ère basique, pas de bonus large_format.
- Thread safety : les fonctions `compute_*_correlation` doivent être **pures** (pas de state partagé).

**Effort réévalué :** **22h** (cœur différenciateur, justifie effort fort).
- 4h : modules signatures + av1_metadata + tests
- 8h : grain_classifier (temporal + spatial + cross-color + verdicts)
- 3h : DNR partiel + context FR
- 1h : refactor grain_analysis + intégration
- 3h : corpus fixtures 30 films
- 3h : tests + validation

**Note packaging :**
- Aucune dépendance externe nouvelle (numpy déjà là).
- 3 modules à ajouter aux `hiddenimports` :
  ```python
  "cinesort.domain.perceptual.grain_signatures",
  "cinesort.domain.perceptual.av1_grain_metadata",
  "cinesort.domain.perceptual.grain_classifier",
  ```
- Aucune migration SQL (champs stockés dans blob JSON `perceptual_metrics.grain`).

**Impact comparaison doublons (pour §16 Score composite) :**
- `grain_nature == "film_grain"` + `is_partial_dnr == False` → **+10 pts** (grain préservé)
- `is_partial_dnr == True` → **-15 pts** (perte qualité masquée)
- `grain_nature == "encode_noise"` → **-8 pts** (compression destructive)
- `av1_afgs1_present == True` → **+15 pts** (encodage grain-respectueux)
- Score attendu = 0 si conforme ère, -5 à +10 si écart → pondéré dans score visuel final

---

### §12 — Mel spectrogram ✅

**Date du plan :** 2026-04-23
**Recherche :** [NOTES_RECHERCHE §12](NOTES_RECHERCHE_v7_5_0.md#§12--mel-spectrogram-)

**Prérequis :**
- §9 Spectral cutoff (réutilise extraction audio et FFT).
- §1 Parallélisme (Mel peut tourner en parallèle des autres analyses audio).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : +14 constantes Mel.
- [cinesort/domain/perceptual/mel_analysis.py](../../../cinesort/domain/perceptual/mel_analysis.py) : **nouveau module**.
- [cinesort/domain/perceptual/audio_perceptual.py](../../../cinesort/domain/perceptual/audio_perceptual.py) : intégration + modification `_compute_audio_score` (ajout poids Mel 15%).
- [cinesort/domain/perceptual/models.py](../../../cinesort/domain/perceptual/models.py) : +6 champs dans `AudioPerceptual`.
- [cinesort/ui/api/settings_support.py](../../../cinesort/ui/api/settings_support.py) : setting `perceptual_audio_mel_enabled`.
- [CineSort.spec](../../../CineSort.spec) : +`cinesort.domain.perceptual.mel_analysis` aux `hiddenimports`.

**Signatures exactes :**

```python
# cinesort/domain/perceptual/mel_analysis.py

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .constants import (
    MEL_N_FILTERS, MEL_FMIN, MEL_FMAX,
    MEL_SOFT_CLIP_HARMONICS_MIN_PCT,
    MEL_SOFT_CLIP_HARMONICS_WARN_PCT,
    MEL_SOFT_CLIP_HARMONICS_SEVERE_PCT,
    MEL_MP3_SHELF_DROP_DB, MEL_MP3_SHELF_MIN_FRAMES_PCT,
    MEL_AAC_HOLE_THRESHOLD_DB, MEL_AAC_HOLE_RATIO_WARN,
    MEL_AAC_HOLE_RATIO_SEVERE, MEL_AAC_SYNTHETIC_VARIANCE_THRESHOLD,
    MEL_WEIGHT_SOFT_CLIP, MEL_WEIGHT_MP3_SHELF,
    MEL_WEIGHT_AAC_HOLES, MEL_WEIGHT_FLATNESS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MelAnalysisResult:
    mel_soft_clipping_pct: float       # % frames avec harmoniques clipping
    mel_mp3_shelf_detected: bool
    mel_mp3_shelf_drop_db: float
    mel_aac_holes_ratio: float          # fraction bandes avec trous
    mel_aac_synthetic_variance_ratio: float
    mel_spectral_flatness_mean: float   # 0.0-1.0
    mel_score: int                      # 0-100 composite
    mel_verdict: str                    # "clean" | "soft_clipped" | "mp3_encoded" |
                                        # "aac_low_bitrate" | "insufficient_data"


def hz_to_mel(hz: float) -> float:
    """Slaney 1998 : 2595 * log10(1 + hz/700)."""


def mel_to_hz(mel: float) -> float:
    """Inverse : 700 * (10**(mel/2595) - 1)."""


def build_mel_filter_bank(
    n_filters: int = MEL_N_FILTERS,
    sample_rate: int = 48000,
    n_fft: int = 4096,
    fmin: float = MEL_FMIN,
    fmax: float = MEL_FMAX,
) -> np.ndarray:
    """Construit le filter bank triangulaire Mel.

    Returns:
        np.ndarray shape (n_filters, n_fft//2+1).
    """


def apply_mel_filters(
    spectrogram: np.ndarray,
    mel_filters: np.ndarray,
) -> np.ndarray:
    """Applique le filter bank au spectrogramme STFT.

    Args:
        spectrogram: magnitude linéaire shape (n_frames, n_freqs).
        mel_filters: filter bank shape (n_filters, n_freqs).

    Returns:
        Mel spectrogram shape (n_frames, n_filters).
    """


def mel_to_db(mel_spec: np.ndarray, top_db: float = 80.0, eps: float = 1e-10) -> np.ndarray:
    """Convertit en dB, clipé à [-top_db, 0]."""


def detect_soft_clipping(mel_spec_db: np.ndarray, mel_freqs_hz: np.ndarray) -> dict:
    """Détection soft clipping via harmoniques régulières.

    Pour chaque frame :
        1. Trouver pics locaux < 6000 Hz.
        2. Pour chaque pic, vérifier harmoniques à 2f, 3f, 4f.
        3. Compter les frames avec harmoniques (>= 2 harmoniques détectées).

    Returns:
        {"pct_frames_with_harmonics": float, "verdict": "normal" | "warn" | "severe"}
    """


def detect_mp3_shelf(mel_spec_db: np.ndarray, mel_freqs_hz: np.ndarray) -> dict:
    """Détecte la signature shelf MP3 à 16 kHz.

    Mesure :
        - P_avant = puissance moy bandes Mel dans [14000, 16000] Hz
        - P_apres = puissance moy bandes Mel dans [16000, 18000] Hz
        - drop = P_avant - P_apres (dB)

    Shelf détecté si drop > MEL_MP3_SHELF_DROP_DB (20 dB) sur >= 70% frames.

    Returns: {"shelf_detected": bool, "shelf_drop_db": float, "frames_pct": float}
    """


def detect_aac_holes(mel_spec_db: np.ndarray, mel_freqs_hz: np.ndarray) -> dict:
    """Détecte trous spectraux AAC bas bitrate.

    Mesure :
        - hole_ratio : fraction bandes avec puissance moy < -80 dB
        - synthetic_ratio : fraction bandes avec variance temporelle < 0.05

    Returns:
        {"hole_ratio": float, "synthetic_ratio": float, "verdict": str}
    """


def compute_spectral_flatness(mel_spec_linear: np.ndarray) -> float:
    """Spectral flatness moyenne sur toutes les frames.

    Formule : geometric_mean / arithmetic_mean (par frame, puis moyenne temporelle).

    Returns: float 0.0-1.0.
    """


def compute_mel_score(
    soft_clip: dict,
    mp3_shelf: dict,
    aac_holes: dict,
    flatness: float,
) -> tuple[int, str]:
    """Calcule le score Mel composite 0-100 et le verdict.

    Pondérations (constants.py MEL_WEIGHT_*) :
        - soft_clip : 40%
        - mp3_shelf : 20%
        - aac_holes : 30%
        - flatness : 10%

    Chaque sous-score 0-100, combinaison pondérée.

    Verdict :
        - score >= 80 : "clean"
        - soft_clip dominant : "soft_clipped"
        - mp3_shelf : "mp3_encoded"
        - aac_holes : "aac_low_bitrate"
    """


def analyze_mel(
    spectrogram: np.ndarray,         # STFT magnitude (shape n_frames × n_freqs)
    sample_rate: int,
    n_fft: int,
) -> MelAnalysisResult:
    """Orchestrateur : applique filter bank + 4 analyses + score.

    Réutilise la STFT calculée par §9 Spectral cutoff.

    Returns: MelAnalysisResult.
    """
```

```python
# models.py — ajouts dans AudioPerceptual

@dataclass
class AudioPerceptual:
    # ... champs existants + §9 + §14 ...

    # §12 Mel spectrogram
    mel_soft_clipping_pct: float = 0.0
    mel_mp3_shelf_detected: bool = False
    mel_aac_holes_ratio: float = 0.0
    mel_spectral_flatness: float = 0.0
    mel_score: int = 0
    mel_verdict: str = "unknown"
```

```python
# audio_perceptual.py — intégration après §9 spectral

# --- Mel analysis (si activé) ---
if settings.get("perceptual_audio_mel_enabled", True):
    # Réutiliser la STFT calculée par §9 spectral_analysis
    spectrogram = ... # from §9 spectral_result.spectrogram (à exposer)
    if spectrogram is not None and len(spectrogram) > 0:
        mel_result = analyze_mel(spectrogram, sample_rate=48000, n_fft=4096)
        result.mel_soft_clipping_pct = mel_result.mel_soft_clipping_pct
        result.mel_mp3_shelf_detected = mel_result.mel_mp3_shelf_detected
        result.mel_aac_holes_ratio = mel_result.mel_aac_holes_ratio
        result.mel_spectral_flatness = mel_result.mel_spectral_flatness
        result.mel_score = mel_result.mel_score
        result.mel_verdict = mel_result.mel_verdict
```

**Modification du scoring audio :**

```python
# audio_perceptual.py — _compute_audio_score modifié

def _compute_audio_score(
    loud: Optional[dict],
    astats: Optional[dict],
    clip: Optional[dict],
    mel: Optional[MelAnalysisResult] = None,  # NOUVEAU
) -> int:
    # ... calcul actuel des sous-scores ...

    # NOUVEAU : s_mel
    s_mel = mel.mel_score if mel else 50

    total = (
        s_lra * AUDIO_WEIGHT_LRA
        + s_noise * AUDIO_WEIGHT_NOISE_FLOOR
        + s_clip * AUDIO_WEIGHT_CLIPPING
        + s_dyn * AUDIO_WEIGHT_DYNAMIC_RANGE
        + s_crest * AUDIO_WEIGHT_CREST
        + s_mel * AUDIO_WEIGHT_MEL  # NOUVEAU
    ) / 100
    return max(0, min(100, int(round(total))))
```

**Mise à jour pondérations `constants.py`** :

```python
# Avant
AUDIO_WEIGHT_LRA = 30
AUDIO_WEIGHT_NOISE_FLOOR = 25
AUDIO_WEIGHT_CLIPPING = 20
AUDIO_WEIGHT_DYNAMIC_RANGE = 15
AUDIO_WEIGHT_CREST = 10
# Total = 100

# Après (redistribution)
AUDIO_WEIGHT_LRA = 25
AUDIO_WEIGHT_NOISE_FLOOR = 20
AUDIO_WEIGHT_CLIPPING = 15
AUDIO_WEIGHT_DYNAMIC_RANGE = 15
AUDIO_WEIGHT_CREST = 10
AUDIO_WEIGHT_MEL = 15  # NOUVEAU
# Total = 100
```

**Seuils et constantes :**

| Constante | Valeur | Rôle |
|---|---|---|
| `MEL_N_FILTERS` | 64 | Standard audio analysis |
| `MEL_FMIN` | 0 Hz | |
| `MEL_FMAX` | 24000 Hz | Nyquist à 48 kHz SR |
| `MEL_SOFT_CLIP_HARMONICS_MIN_PCT` | 5 | % frames normale |
| `MEL_SOFT_CLIP_HARMONICS_WARN_PCT` | 15 | % frames suspect |
| `MEL_SOFT_CLIP_HARMONICS_SEVERE_PCT` | 30 | % frames sévère |
| `MEL_MP3_SHELF_DROP_DB` | 20 | dB drop seuil |
| `MEL_MP3_SHELF_MIN_FRAMES_PCT` | 70 | % frames avec drop |
| `MEL_AAC_HOLE_THRESHOLD_DB` | -80 | Seuil "trou spectral" |
| `MEL_AAC_HOLE_RATIO_WARN` | 0.05 | 5% bandes avec trous |
| `MEL_AAC_HOLE_RATIO_SEVERE` | 0.10 | 10% bandes |
| `MEL_AAC_SYNTHETIC_VARIANCE_THRESHOLD` | 0.05 | Variance bandes synthétiques |
| `MEL_WEIGHT_SOFT_CLIP` | 40 | Poids score composite |
| `MEL_WEIGHT_MP3_SHELF` | 20 | |
| `MEL_WEIGHT_AAC_HOLES` | 30 | |
| `MEL_WEIGHT_FLATNESS` | 10 | |

**Ordre d'implémentation :**

1. **Étape 1 — Constantes** : 14 constantes + mise à jour AUDIO_WEIGHT_* (15 min).
2. **Étape 2 — Modèles** : +6 champs dans `AudioPerceptual` (10 min).
3. **Étape 3 — Fonctions primitives** : `hz_to_mel`, `mel_to_hz`, `build_mel_filter_bank`, `apply_mel_filters`, `mel_to_db` (1 h).
4. **Étape 4 — Tests primitives** : 8 tests (filter bank sanity, conversions Hz/Mel) (45 min).
5. **Étape 5 — Détections** : `detect_soft_clipping`, `detect_mp3_shelf`, `detect_aac_holes`, `compute_spectral_flatness` (2 h).
6. **Étape 6 — Tests détections** : 12 tests (signaux synthétiques : ton pur, MP3 shelf simulé, trous AAC) (1 h).
7. **Étape 7 — Orchestrateur `analyze_mel`** + score composite (30 min).
8. **Étape 8 — Intégration `analyze_audio_perceptual`** + partage STFT §9 (45 min).
9. **Étape 9 — Modification `_compute_audio_score`** + redistribution poids (15 min).
10. **Étape 10 — Tests intégration** : 4 tests bout-en-bout (30 min).
11. **Étape 11 — Corpus validation** : 5 fichiers audio étiquetés (FLAC clean, MP3 320, MP3 128, AAC 128, AAC 64 SBR) (1 h).

**Tests à écrire :**

```python
# tests/test_mel_analysis.py  (~30 tests)

class TestMelConversions(unittest.TestCase):
    def test_hz_to_mel_1000hz_returns_1000(self): ...
    def test_mel_to_hz_roundtrip(self): ...

class TestBuildMelFilterBank(unittest.TestCase):
    def test_shape_correct(self): ...                  # (64, n_fft//2 + 1)
    def test_filters_sum_to_expected_range(self): ...  # triangulaires
    def test_filter_centers_log_spaced_in_mel(self): ...

class TestApplyMelFilters(unittest.TestCase):
    def test_output_shape(self): ...                   # (n_frames, 64)
    def test_non_negative_values(self): ...

class TestDetectSoftClipping(unittest.TestCase):
    def test_pure_tone_no_harmonics(self): ...
    def test_clipped_tone_has_harmonics(self): ...
    def test_normal_voice_below_warn(self): ...

class TestDetectMp3Shelf(unittest.TestCase):
    def test_flat_spectrum_no_shelf(self): ...
    def test_mp3_simulated_shelf_detected(self): ...   # signal avec drop à 16kHz
    def test_lossless_flat_above_16khz_no_shelf(self): ...

class TestDetectAacHoles(unittest.TestCase):
    def test_flac_no_holes(self): ...
    def test_aac_64kbps_many_holes(self): ...
    def test_opus_low_br_synthetic_bands(self): ...

class TestSpectralFlatness(unittest.TestCase):
    def test_white_noise_flatness_near_1(self): ...
    def test_pure_tone_flatness_near_0(self): ...

class TestComputeMelScore(unittest.TestCase):
    def test_clean_audio_high_score(self): ...
    def test_severe_soft_clip_low_score(self): ...
    def test_mp3_shelf_verdict(self): ...

class TestAnalyzeMelIntegration(unittest.TestCase):
    def test_flac_fixture_clean_verdict(self): ...
    def test_mp3_320_fixture_verdict(self): ...
    def test_aac_64_fixture_verdict(self): ...
    def test_silent_audio_insufficient_data(self): ...
```

**Cas limites à tester explicitement :**

- Audio silencieux : mel_spec = -inf partout → verdict `insufficient_data`, score 50.
- Audio très court (< 1s) : pas assez de frames STFT → skip, verdict `insufficient_data`.
- Sample rate 22 kHz : Nyquist 11 kHz, bandes Mel au-dessus ignorées (pas d'erreur).
- Film musette/musique seule : flatness haute partout, MP3 shelf peut être faux positif si piste ancienne (20 kHz naturel). Cross-check avec codec (si FLAC → flag `vintage_master_low_hf_natural`).
- Audio 24-bit dynamic extrême : peut déclencher soft_clipping si voix percutantes → seuils validés dans corpus pour éviter.

**Effort réévalué :** **6h30** (1h primitives + 2h détections + 1h tests + 1h intégration + 1h corpus + 30 min doc).

**Note packaging :**
- Aucune dépendance nouvelle (numpy déjà là).
- Ajouter `cinesort.domain.perceptual.mel_analysis` aux `hiddenimports` dans [CineSort.spec](../../../CineSort.spec).
- Migration SQL : **aucune** (champs dans blob JSON `perceptual_metrics.audio`).

**Impact comparaison doublons :**
- Deux fichiers avec même LRA/noise mais un avec `mel_verdict="mp3_encoded"` et l'autre `"clean"` → le second gagne +12 pts sur score audio (différenciateur clair).
- Combinaison avec §9 spectral cutoff : les deux doivent converger. Si §9 dit lossy et §12 dit clean → flag anomalie, confidence réduite.

---

## Récapitulatif Vague 4

| § | Effort |
|---|---|
| §15 Grain intelligence avancée | 22h |
| §12 Mel spectrogram | 6h30 |
| **Total Vague 4** | **~28h30** |

---

## Vague 5 — ML

### §10 — VMAF no-reference 📦 REPORTÉ v7.6.0+

**Statut :** reporté après découverte critique (pas de modèle NR-VMAF public disponible). Voir [NOTES_RECHERCHE §10](NOTES_RECHERCHE_v7_5_0.md#§10--vmaf-no-reference-📦-reporté-v760-pas-de-modèle-public) pour les détails + [BACKLOG](BACKLOG_v7_5_0.md) pour la reprise.

**Pas de plan de code** pour v7.5.0 — aucune implémentation prévue.

**Option alternative si l'utilisateur veut quand même un "score NR" visible** :
- Exposer le SSIM self-ref (§13) sur échelle 0-100 (conversion linéaire depuis 0.85-0.99).
- Label UI : "Score qualité auto-référentiel".
- Effort minimal : 30 min.
- À discuter avec user si besoin avant build v7.5.0.

**Redistribution des pondérations score composite (§16)** :
- VMAF NR supprimé (0% au lieu de 25%)
- Score perceptuel classique : 50% (+10%)
- Métadonnées HDR : 15% (+5%)
- Résolution effective : 20% (+10%)
- LPIPS : 15% (inchangé)
- Total : 100%

---

### §11 — LPIPS 🔜

**Date du plan :** 2026-04-23
**Recherche :** [NOTES_RECHERCHE §11](NOTES_RECHERCHE_v7_5_0.md#§11--lpips-)

**Prérequis :**
- §1 Parallélisme (inférence ONNX peut tourner en parallèle des autres analyses).
- §7 / §13 (extract_aligned_frames déjà disponible dans [comparison.py](../../../cinesort/domain/perceptual/comparison.py)).

**Fichiers touchés :**
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : +7 constantes LPIPS.
- [cinesort/domain/perceptual/lpips_compare.py](../../../cinesort/domain/perceptual/lpips_compare.py) : **nouveau module**.
- [cinesort/domain/perceptual/comparison.py](../../../cinesort/domain/perceptual/comparison.py) : intégration LPIPS dans `build_comparison_report`.
- [cinesort/ui/api/settings_support.py](../../../cinesort/ui/api/settings_support.py) : setting `perceptual_lpips_enabled`.
- [requirements.txt](../../../requirements.txt) : +`onnxruntime>=1.24,<2.0`.
- [CineSort.spec](../../../CineSort.spec) :
  - Ajouter `assets/models/lpips_alexnet.onnx` aux `datas`
  - Ajouter `onnxruntime` + `cinesort.domain.perceptual.lpips_compare` aux `hiddenimports`.
- `assets/models/lpips_alexnet.onnx` : **nouveau binaire** (~55 MB).
- `scripts/convert_lpips_to_onnx.py` : **nouveau script** (one-shot pour générer le modèle, pas nécessaire au runtime).

**Signatures exactes :**

```python
# cinesort/domain/perceptual/lpips_compare.py

from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Optional

import numpy as np

from .constants import (
    LPIPS_MODEL_PATH, LPIPS_INPUT_SIZE, LPIPS_N_FRAMES_PAIRS,
    LPIPS_DISTANCE_IDENTICAL, LPIPS_DISTANCE_VERY_SIMILAR,
    LPIPS_DISTANCE_SIMILAR, LPIPS_DISTANCE_DIFFERENT,
    LPIPS_INFERENCE_TIMEOUT_S,
)

logger = logging.getLogger(__name__)

# Lazy import pour éviter ImportError au module load si ONNX Runtime absent
_ort_session = None
_ort_available: Optional[bool] = None


def _is_ort_available() -> bool:
    """Vérifie disponibilité ONNX Runtime (lazy, cache)."""
    global _ort_available
    if _ort_available is None:
        try:
            import onnxruntime  # noqa: F401
            _ort_available = True
        except ImportError:
            _ort_available = False
            logger.warning("onnxruntime non installé — LPIPS désactivé")
    return _ort_available


def _get_session(model_path: str):
    """Charge paresseusement la session ONNX (1 fois par process)."""
    global _ort_session
    if _ort_session is None:
        import onnxruntime as ort
        if not Path(model_path).exists():
            raise FileNotFoundError(f"LPIPS model absent : {model_path}")
        _ort_session = ort.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
        )
    return _ort_session


@dataclass(frozen=True)
class LpipsResult:
    distance_median: Optional[float]       # médiane des distances par paire
    distances_per_pair: list[float]        # détail par paire (debug)
    verdict: str                           # "identical" | "very_similar" | "similar" |
                                           # "different" | "very_different" | "insufficient_data"
    n_pairs_evaluated: int


def preprocess_frame_for_lpips(
    pixels_y: list[int],
    width: int,
    height: int,
    target_size: int = LPIPS_INPUT_SIZE,
) -> np.ndarray:
    """Prépare une frame pour l'inférence LPIPS.

    Étapes :
        1. Reshape (height, width) depuis pixels_y Y (grayscale).
        2. Convertir Y → RGB via 3 canaux identiques.
        3. Resize bicubique à target_size × target_size.
        4. Normaliser [-1, 1] (LPIPS attend float dans cette plage).
        5. Transposer (H, W, C) → (C, H, W) + ajouter batch dim → (1, 3, H, W).

    Returns: np.ndarray dtype float32, shape (1, 3, target_size, target_size).
    """


def compute_lpips_distance_pair(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    model_path: str = LPIPS_MODEL_PATH,
) -> Optional[float]:
    """Calcule la distance LPIPS entre 2 frames pré-traitées.

    Args:
        frame_a, frame_b: np.ndarray float32 shape (1, 3, H, W), valeurs [-1, 1].

    Returns:
        float distance 0.0-1.0 (plus petit = plus similaire), ou None si erreur.
    """


def compute_lpips_comparison(
    aligned_frames: list[dict],
    max_pairs: int = LPIPS_N_FRAMES_PAIRS,
) -> LpipsResult:
    """Compare 2 fichiers via LPIPS sur N paires de frames alignées.

    Args:
        aligned_frames: sortie de `extract_aligned_frames()` (comparison.py).
                        Chaque élément = {"timestamp", "pixels_a", "pixels_b", ...}.
        max_pairs: limite le nombre de paires analysées.

    Returns: LpipsResult.
    """


def classify_lpips_verdict(distance: Optional[float]) -> str:
    """Classifie une distance en verdict textuel.

    < 0.05 : "identical"
    < 0.15 : "very_similar"
    < 0.30 : "similar"
    < 0.50 : "different"
    >= 0.50 : "very_different"
    None : "insufficient_data"
    """
```

```python
# cinesort/domain/perceptual/comparison.py — intégration

def build_comparison_report(
    perc_a: dict,
    perc_b: dict,
    per_frame: list,
    media_a: str,
    media_b: str,
    lpips_result: Optional[LpipsResult] = None,     # NOUVEAU
) -> dict:
    """Construit le rapport de comparaison (étend l'existant avec LPIPS)."""
    report = _build_existing_report(perc_a, perc_b, per_frame, media_a, media_b)

    # NOUVEAU : ajouter critère LPIPS si disponible
    if lpips_result and lpips_result.distance_median is not None:
        report["criteria"].append({
            "name": "Distance perceptuelle LPIPS",
            "value_a": "référence (A)",
            "value_b": f"{lpips_result.distance_median:.3f} ({lpips_result.verdict})",
            "winner": None,  # LPIPS mesure similarité, pas qualité
            "weight": 15,
            "detail_fr": _build_lpips_detail_fr(lpips_result),
        })

    return report


def _build_lpips_detail_fr(result: LpipsResult) -> str:
    """Construit le texte FR pour l'UI."""
    verdicts_fr = {
        "identical": "Les 2 fichiers sont visuellement quasi-identiques.",
        "very_similar": "Très similaires — probablement même source, encodes différents.",
        "similar": "Similaires — même film, possiblement versions/masters différents.",
        "different": "Différents — versions distinctes (theatrical vs extended ?) ou remaster couleur.",
        "very_different": "Très différents — attention, possible erreur de comparaison.",
        "insufficient_data": "Données insuffisantes pour évaluation perceptuelle.",
    }
    return verdicts_fr.get(result.verdict, "")
```

```python
# perceptual_support.py — modification de compare_perceptual()

# APRÈS les calls existants (extract_aligned_frames, compare_per_frame)
# AJOUTER :

from cinesort.domain.perceptual.lpips_compare import compute_lpips_comparison, _is_ort_available

lpips_result = None
if settings.get("perceptual_lpips_enabled", True) and _is_ort_available():
    lpips_result = compute_lpips_comparison(aligned)

report = build_comparison_report(
    perc_a, perc_b, per_frame,
    str(media_a), str(media_b),
    lpips_result=lpips_result,  # NOUVEAU
)
```

**Constantes :**

```python
# constants.py ajouts
LPIPS_MODEL_PATH = "assets/models/lpips_alexnet.onnx"   # relatif au bundle
LPIPS_INPUT_SIZE = 256                                   # modèle entraîné sur 256×256
LPIPS_N_FRAMES_PAIRS = 5                                 # 5 paires médiane
LPIPS_DISTANCE_IDENTICAL = 0.05
LPIPS_DISTANCE_VERY_SIMILAR = 0.15
LPIPS_DISTANCE_SIMILAR = 0.30
LPIPS_DISTANCE_DIFFERENT = 0.50
LPIPS_INFERENCE_TIMEOUT_S = 30
```

**Setting ajouté :**

```python
# settings_support.py
"perceptual_lpips_enabled": True,      # toggle UI simple
```

**Ordre d'implémentation :**

1. **Étape 1 — Script de conversion ONNX one-shot** : `scripts/convert_lpips_to_onnx.py` utilisant `lpips-tensorflow` (1 h).
   - Générer `lpips_alexnet.onnx` à partir du dépôt officiel.
   - Vérifier taille finale (~55 MB).
   - Valider inférence avec 2 images test.
2. **Étape 2 — Placer le modèle dans `assets/models/`** + vérifier inclusion Git LFS ou exclusion `.gitignore` (décision packaging) (15 min).
3. **Étape 3 — Dépendance onnxruntime** : ajouter dans `requirements.txt`, tester install local (15 min).
4. **Étape 4 — Constantes** : 8 constantes dans `perceptual/constants.py` (10 min).
5. **Étape 5 — Module `lpips_compare.py`** : signatures + lazy ONNX loading + preprocess + distance (2 h).
6. **Étape 6 — Tests unitaires** : 10 tests (preprocess, classify verdict, cas erreur) (1 h).
7. **Étape 7 — Intégration `comparison.py`** : nouveau critère + texte FR (30 min).
8. **Étape 8 — Intégration `perceptual_support.compare_perceptual()`** : appel LPIPS conditionnel (30 min).
9. **Étape 9 — Setting + validation UI** : ajouter toggle dans les réglages desktop + dashboard (45 min).
10. **Étape 10 — `CineSort.spec`** : datas + hiddenimports (15 min).
11. **Étape 11 — Tests intégration** : 4 tests bout-en-bout avec modèle réel (45 min).
12. **Étape 12 — Corpus validation** : 8 paires étiquetées (identical encode, remaster, theatrical/extended, colorisation, films différents) (1 h 30).

**Tests à écrire :**

```python
# tests/test_lpips_compare.py (~30 tests)

class TestOrtAvailable(unittest.TestCase):
    def test_available_when_installed(self): ...
    def test_graceful_fallback_when_missing(self): ...

class TestPreprocessFrame(unittest.TestCase):
    def test_shape_correct(self): ...              # (1, 3, 256, 256)
    def test_normalization_range(self): ...        # [-1, 1]
    def test_resize_bicubic(self): ...
    def test_grayscale_to_rgb(self): ...           # Y → 3 canaux identiques

class TestClassifyLpipsVerdict(unittest.TestCase):
    def test_0_02_identical(self): ...
    def test_0_10_very_similar(self): ...
    def test_0_20_similar(self): ...
    def test_0_40_different(self): ...
    def test_0_80_very_different(self): ...
    def test_none_insufficient_data(self): ...

class TestComputeLpipsDistancePair(unittest.TestCase):
    def test_identical_frames_distance_near_0(self): ...
    def test_random_frames_distance_high(self): ...
    def test_ort_session_cached(self): ...
    def test_model_absent_returns_none(self): ...

class TestComputeLpipsComparison(unittest.TestCase):
    def test_returns_median_of_distances(self): ...
    def test_respects_max_pairs(self): ...
    def test_empty_frames_returns_insufficient(self): ...
    def test_3_pairs_minimum(self): ...             # verdict si < 3

class TestIntegration(unittest.TestCase):
    def test_comparison_report_includes_lpips(self): ...
    def test_setting_disabled_skips_lpips(self): ...
    def test_onnx_missing_fallback_gracefully(self): ...
    def test_fr_detail_text_generated(self): ...

class TestCorpus(unittest.TestCase):
    """Validation empirique sur 8 paires étiquetées."""
    def test_identical_encodes_distance_lt_005(self): ...
    def test_remaster_distance_015_to_030(self): ...
    def test_theatrical_extended_distance_gt_030(self): ...
    def test_different_films_distance_gt_050(self): ...
```

**Cas limites à tester explicitement :**

- `onnxruntime` non installé : `_is_ort_available()` retourne False, feature désactivée silencieusement.
- Modèle ONNX absent (`lpips_alexnet.onnx` manquant dans bundle) : log error au premier usage, `LpipsResult.distance_median = None`.
- Frames noires (scène générique) : LPIPS distance très basse artificiellement. Filtrage pré-inférence (comme §7) : exclure frames avec `y_avg < 20`.
- Frames de résolutions différentes (A 1080p, B 4K) : resize bicubique uniforme à 256×256 → OK.
- Moins de 3 paires valides après filtrage : verdict `insufficient_data`, distance `None`.
- Timeout ONNX Runtime : retour `None`, log warning.
- Thread-safety : `onnxruntime.InferenceSession` est thread-safe pour `run()` après init. Notre lazy singleton compatible avec ThreadPool §1.

**Effort réévalué :** **10h** (2h conversion ONNX + 2h module + 1h tests unit + 1h intégration + 1h settings UI + 1h30 tests intégration + 1h30 corpus).

**Note packaging :**
- Dépendance nouvelle : `onnxruntime>=1.24,<2.0` (~30-50 MB wheel Windows).
- Binaire embarqué : `lpips_alexnet.onnx` (~55 MB).
- **Impact bundle EXE total : +100 MB environ.**
- Bundle actuel : 16 MB → avec LPIPS : **~116 MB**.
- Décision : acceptable pour "app pro" communautaire (Adobe Lightroom fait 2 GB). User averti via README et CHANGELOG.

**Script de conversion ONNX** (`scripts/convert_lpips_to_onnx.py`) :

```python
"""Script one-shot pour générer le modèle LPIPS AlexNet ONNX.
Exécuté 1 fois en développement, le .onnx est ensuite embarqué dans le bundle.

Usage :
    pip install lpips torch
    python scripts/convert_lpips_to_onnx.py
    # Génère : assets/models/lpips_alexnet.onnx
"""
import torch
import lpips

model = lpips.LPIPS(net='alex')
model.eval()

# Dummy inputs pour le tracing
dummy_a = torch.randn(1, 3, 256, 256)
dummy_b = torch.randn(1, 3, 256, 256)

torch.onnx.export(
    model,
    (dummy_a, dummy_b),
    "assets/models/lpips_alexnet.onnx",
    input_names=["input_a", "input_b"],
    output_names=["distance"],
    dynamic_axes={
        "input_a": {0: "batch"},
        "input_b": {0: "batch"},
    },
    opset_version=17,
)
print("LPIPS AlexNet ONNX exporté avec succès.")
```

**Git LFS ou commit binaire ?** : le modèle de 55 MB peut être commité directement (limite GitHub 100 MB par fichier). **Décision : commit direct** dans `assets/models/` pour simplicité, pas de Git LFS.

---

## Récapitulatif Vague 5

| § | Statut | Effort |
|---|---|---|
| §10 VMAF NR | 📦 Reporté v7.6.0+ (pas de modèle public) | 0h v7.5.0 |
| §11 LPIPS | ✅ À implémenter | 10h |
| **Total Vague 5** | | **~10h** |

**Gain pour v7.5.0** : 10h économisées (vs 14h initial estimé pour §10+§11) réinvestissables ailleurs.

---

## Vague 6 — Synthèse

### §16 — Score composite et visualisation 🔜 (section de synthèse, bloquée par toutes les autres)

**Date du plan :** 2026-04-23
**Recherche :** [NOTES_RECHERCHE §16](NOTES_RECHERCHE_v7_5_0.md#§16--score-composite-et-visualisation--section-de-synthèse)

**Prérequis :** **toutes les sections précédentes** doivent être implémentées et stables. §16 agrège et visualise leurs résultats.

**Fichiers touchés :**
- [cinesort/domain/perceptual/composite_score_v2.py](../../../cinesort/domain/perceptual/composite_score_v2.py) : **nouveau module** (remplace le `composite_score.py` existant ? ou coexiste et on migre).
- [cinesort/domain/perceptual/constants.py](../../../cinesort/domain/perceptual/constants.py) : +20 constantes poids/tiers/ajustements.
- [cinesort/domain/perceptual/models.py](../../../cinesort/domain/perceptual/models.py) : ajout `GlobalScoreResult` dataclass.
- [cinesort/domain/perceptual/composite_score.py](../../../cinesort/domain/perceptual/composite_score.py) : refactor pour appeler `composite_score_v2.py`.
- [cinesort/ui/api/perceptual_support.py](../../../cinesort/ui/api/perceptual_support.py) : intégration global score dans `compare_perceptual()`.
- [web/views/validation.js](../../../web/views/validation.js) : composant UI score global (cercle + 3 jauges).
- [web/views/execution.js](../../../web/views/execution.js) : modale deep-compare avec accordéon détaillé.
- [web/components/score-circle.js](../../../web/components/score-circle.js) : **nouveau composant** cercle SVG animé.
- [web/components/score-gauge.js](../../../web/components/score-gauge.js) : **nouveau composant** jauge horizontale.
- [web/components/score-accordion.js](../../../web/components/score-accordion.js) : **nouveau composant** accordéon détaillé.
- [web/styles.css](../../../web/styles.css) : +150L styles score composite.
- [web/dashboard/views/execution.js](../../../web/dashboard/views/execution.js) : parité dashboard.
- [web/dashboard/styles.css](../../../web/dashboard/styles.css) : parité styles.

**Signatures exactes :**

##### Module `composite_score_v2.py`

```python
# cinesort/domain/perceptual/composite_score_v2.py

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from .constants import (
    GLOBAL_WEIGHT_VIDEO_V2, GLOBAL_WEIGHT_AUDIO_V2, GLOBAL_WEIGHT_COHERENCE_V2,
    VIDEO_WEIGHT_PERCEPTUAL, VIDEO_WEIGHT_RESOLUTION, VIDEO_WEIGHT_HDR, VIDEO_WEIGHT_LPIPS,
    AUDIO_WEIGHT_PERCEPTUAL_V2, AUDIO_WEIGHT_SPECTRAL, AUDIO_WEIGHT_DRC,
    AUDIO_WEIGHT_CHROMAPRINT, AUDIO_WEIGHT_RESERVE,
    COHERENCE_WEIGHT_RUNTIME, COHERENCE_WEIGHT_NFO,
    TIER_PLATINUM_THRESHOLD, TIER_GOOD_THRESHOLD, TIER_SILVER_THRESHOLD,
    TIER_BRONZE_THRESHOLD,
    ADJUSTMENT_GRAIN_FILM_BONUS, ADJUSTMENT_GRAIN_PARTIAL_DNR_MALUS,
    ADJUSTMENT_GRAIN_ENCODE_NOISE_MALUS, ADJUSTMENT_AV1_AFGS1_BONUS,
    ADJUSTMENT_DV_PROFILE_5_MALUS, ADJUSTMENT_HDR_METADATA_MISSING_MALUS,
    ADJUSTMENT_IMAX_EXPANSION_BONUS, ADJUSTMENT_IMAX_TYPED_BONUS,
    ADJUSTMENT_FAKE_LOSSLESS_MALUS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubScore:
    """Un sous-score avec sa confidence."""
    name: str                  # "blockiness", "hdr_validation", etc.
    value: float               # 0-100
    weight: float              # poids relatif au parent
    confidence: float          # 0.0-1.0
    label_fr: str              # pour UI tooltip
    tier: Optional[str] = None # "platinum" | "gold" | ... pour ce sous-score
    detail_fr: Optional[str] = None  # phrase explicative pour accordéon


@dataclass(frozen=True)
class CategoryScore:
    """Score d'une catégorie (vidéo / audio / cohérence)."""
    name: str                  # "video" | "audio" | "coherence"
    value: float               # 0-100 pondéré des sub_scores
    weight: float              # poids dans le global
    confidence: float          # moyenne pondérée des sub_confidences
    tier: str                  # tier de la catégorie
    sub_scores: list[SubScore]


@dataclass(frozen=True)
class GlobalScoreResult:
    """Résultat score composite complet."""
    global_score: float        # 0-100
    global_tier: str           # "platinum" | "gold" | "silver" | "bronze" | "reject"
    global_confidence: float   # 0.0-1.0
    category_scores: list[CategoryScore]
    warnings: list[str]        # encarts jaunes UI
    adjustments_applied: list[str]  # trace debugging des ajustements


def compute_global_score_v2(
    video_perceptual: Any,          # VideoPerceptual
    audio_perceptual: Any,          # AudioPerceptual
    grain_analysis: Any,             # GrainAnalysis (avec champs v2)
    normalized_probe: Any,           # NormalizedProbe (avec HDR §5 + DV §6)
    tmdb_metadata: Optional[dict],
    nfo_consistency: Optional[dict],
    runtime_vs_tmdb_flag: Optional[str],
    av1_grain_info: Optional[Any] = None,
    lpips_result: Optional[Any] = None,
    imax_info: Optional[Any] = None,
) -> GlobalScoreResult:
    """Calcule le score global composite avec tous les ajustements contextuels.

    Étapes :
        1. Construire les SubScores par catégorie.
        2. Appliquer les ajustements contextuels (9 règles).
        3. Calculer les CategoryScores pondérés par confidence.
        4. Calculer le global via pondération catégories × confidences.
        5. Déterminer le tier.
        6. Collecter les warnings.

    Returns: GlobalScoreResult complet prêt pour sérialisation JSON UI.
    """


def build_video_subscores(
    video_perceptual: Any,
    grain_analysis: Any,
    normalized_probe: Any,
    imax_info: Optional[Any],
    lpips_result: Optional[Any],
) -> list[SubScore]:
    """Construit les ~10 sous-scores vidéo avec labels FR."""


def build_audio_subscores(
    audio_perceptual: Any,
) -> list[SubScore]:
    """Construit les ~6 sous-scores audio avec labels FR."""


def build_coherence_subscores(
    normalized_probe: Any,
    tmdb_metadata: Optional[dict],
    nfo_consistency: Optional[dict],
    runtime_vs_tmdb_flag: Optional[str],
) -> list[SubScore]:
    """Construit les ~2 sous-scores cohérence."""


def apply_contextual_adjustments(
    sub_scores: list[SubScore],
    grain_analysis: Any,
    normalized_probe: Any,
    av1_grain_info: Optional[Any],
    imax_info: Optional[Any],
    is_animation: bool,
    film_era: str,
) -> tuple[list[SubScore], list[str]]:
    """Applique les 9 règles d'ajustement contextuel.

    Règle 1 : grain v2 bonus/malus
    Règle 2 : AV1 AFGS1 bonus
    Règle 3 : DV Profile 5 malus
    Règle 4 : HDR metadata missing malus
    Règle 5 : IMAX bonus
    Règle 6 : Spectral cutoff cross-validation (fake lossless)
    Règle 7 : Version hint warning
    Règle 8 : Animation skip pénalités
    Règle 9 : Vintage master tolérance

    Returns: (sub_scores_ajustés, liste_ajustements_appliqués_pour_debug).
    """


def weighted_score_with_confidence(
    scores: list[tuple[float, float, float]]  # (value, weight, confidence)
) -> tuple[float, float]:
    """Calcule score pondéré + confidence effective.

    Returns: (score_final, confidence_moyenne_effective).
    """


def determine_tier_v2(score: float) -> str:
    """Convertit score 0-100 en tier.

    ≥ 90 : platinum
    ≥ 80 : gold
    ≥ 65 : silver
    ≥ 50 : bronze
    else : reject
    """


def collect_warnings(
    sub_scores: list[SubScore],
    normalized_probe: Any,
    grain_analysis: Any,
    runtime_vs_tmdb_flag: Optional[str],
    category_scores: list[CategoryScore],
) -> list[str]:
    """Collecte les warnings top-level à afficher en encart jaune UI.

    Exemples :
        - "Runtime 145 min vs TMDb 162 min — possible Theatrical Cut"
        - "Dolby Vision Profile 5 — couleurs nécessitent player DV licensé"
        - "Analyse partielle — confidence limitée (%)"
        - "Déséquilibre vidéo/audio marqué (delta 45 pts)"
    """
```

**Constantes (20 nouvelles)** :

```python
# constants.py ajouts

# ========== Pondérations composite V2 ==========
# Global
GLOBAL_WEIGHT_VIDEO_V2 = 60
GLOBAL_WEIGHT_AUDIO_V2 = 35
GLOBAL_WEIGHT_COHERENCE_V2 = 5

# Vidéo (total = 100)
VIDEO_WEIGHT_PERCEPTUAL = 50
VIDEO_WEIGHT_RESOLUTION = 20
VIDEO_WEIGHT_HDR = 15
VIDEO_WEIGHT_LPIPS = 15

# Audio (total = 100)
AUDIO_WEIGHT_PERCEPTUAL_V2 = 50
AUDIO_WEIGHT_SPECTRAL = 20
AUDIO_WEIGHT_DRC = 15
AUDIO_WEIGHT_CHROMAPRINT = 5
AUDIO_WEIGHT_RESERVE = 10       # pour extensions futures (NR-VMAF custom quand dispo)

# Cohérence (total = 100)
COHERENCE_WEIGHT_RUNTIME = 60
COHERENCE_WEIGHT_NFO = 40

# ========== Tiers (cohérent avec la maquette) ==========
TIER_PLATINUM_THRESHOLD = 90
TIER_GOOD_THRESHOLD = 80         # = "Gold"
TIER_SILVER_THRESHOLD = 65
TIER_BRONZE_THRESHOLD = 50
# < 50 = Reject

TIER_V2_LABELS = {
    "platinum": "Platinum",
    "gold": "Gold",
    "silver": "Silver",
    "bronze": "Bronze",
    "reject": "Reject",
}
TIER_V2_COLORS = {
    "platinum": "#FFD700",   # or
    "gold":     "#22C55E",   # vert
    "silver":   "#3B82F6",   # bleu
    "bronze":   "#F59E0B",   # orange
    "reject":   "#EF4444",   # rouge
}

# ========== Ajustements contextuels (pts +/-) ==========
ADJUSTMENT_GRAIN_FILM_BONUS = 10              # grain authentique préservé
ADJUSTMENT_GRAIN_PARTIAL_DNR_MALUS = -15       # DNR partiel détecté
ADJUSTMENT_GRAIN_ENCODE_NOISE_MALUS = -8       # bruit compression
ADJUSTMENT_AV1_AFGS1_BONUS = 15                # grain synthesis metadata
ADJUSTMENT_DV_PROFILE_5_MALUS = -8             # incompatibilité players
ADJUSTMENT_HDR_METADATA_MISSING_MALUS = -10    # HDR10 sans MaxCLL
ADJUSTMENT_IMAX_EXPANSION_BONUS = 15           # master IMAX Enhanced
ADJUSTMENT_IMAX_TYPED_BONUS = 10               # full_frame_143 ou digital_190
ADJUSTMENT_FAKE_LOSSLESS_MALUS = -10           # codec FLAC mais cutoff lossy

# ========== Seuils warning déséquilibre ==========
CATEGORY_IMBALANCE_WARN_DELTA = 40   # si vidéo-audio delta > 40, flag warning
CONFIDENCE_LOW_WARN_THRESHOLD = 0.60  # si < 0.60, flag "analyse partielle"
```

**Ordre d'implémentation :**

### Backend (14h)

1. **Étape 1 — Constantes v2** : 20 constantes dans `perceptual/constants.py` (30 min).
2. **Étape 2 — Dataclasses** : `SubScore`, `CategoryScore`, `GlobalScoreResult` (20 min).
3. **Étape 3 — Module `composite_score_v2.py` skeleton** : signatures toutes les fonctions (30 min).
4. **Étape 4 — `build_video_subscores()`** : construction des ~10 sous-scores vidéo avec labels FR + tier (1 h 30).
5. **Étape 5 — `build_audio_subscores()`** : ~6 sous-scores audio (45 min).
6. **Étape 6 — `build_coherence_subscores()`** : runtime + NFO (30 min).
7. **Étape 7 — `apply_contextual_adjustments()`** : implémenter les 9 règles (1 h 30).
8. **Étape 8 — `weighted_score_with_confidence()` + helpers** (30 min).
9. **Étape 9 — `collect_warnings()`** : 5 warnings types (1 h).
10. **Étape 10 — `compute_global_score_v2()` orchestrateur** (45 min).
11. **Étape 11 — Tests unitaires backend** : 35 tests (pondération, ajustements, tiers, warnings) (3 h).
12. **Étape 12 — Intégration dans `perceptual_support.compare_perceptual`** (30 min).
13. **Étape 13 — Refactor migration `composite_score.py` → délègue à `composite_score_v2.py`** (30 min).
14. **Étape 14 — Tests intégration** : 10 tests avec fixtures complètes perceptual (1 h 30).

### Frontend (12h)

15. **Étape 15 — Composant `score-circle.js`** : cercle SVG animé avec comptage et color ramp (1 h 30).
16. **Étape 16 — Composant `score-gauge.js`** : jauge horizontale avec tier colors et animation (1 h).
17. **Étape 17 — Composant `score-accordion.js`** : accordéon détaillé avec sous-scores (2 h).
18. **Étape 18 — Styles CSS CinemaLux** : variables tier colors, animations, tooltips FR (1 h 30).
19. **Étape 19 — Intégration dans modale deep-compare** : layout complet (2 h).
20. **Étape 20 — Tooltip FR éducatif par score** : 14 textes FR (1 h).
21. **Étape 21 — Warnings encarts jaunes** : composant réutilisable (30 min).
22. **Étape 22 — Radar chart optionnel** (toggle power user) (1 h 30).
23. **Étape 23 — Parité dashboard** : même composants dans `web/dashboard/` (1 h).

### Tests (4h)

24. **Étape 24 — Tests frontend** : 20 tests Playwright e2e (composants, animations, accordéon, tooltips, warnings) (2 h 30).
25. **Étape 25 — Corpus validation global score** : 8 fichiers avec scores attendus (native UHD HDR10, DV 8.1, fake 4K, DNR Blu-ray 2008, etc.) (1 h 30).

**Tests à écrire :**

```python
# tests/test_composite_score_v2.py (~50 tests backend)

class TestWeightedScoreWithConfidence(unittest.TestCase):
    def test_all_confidence_1_returns_weighted_mean(self): ...
    def test_low_confidence_reduces_weight(self): ...
    def test_all_confidence_0_returns_neutral_50(self): ...
    def test_empty_scores_returns_50(self): ...

class TestBuildVideoSubscores(unittest.TestCase):
    def test_contains_10_subscores(self): ...
    def test_labels_fr_present(self): ...
    def test_weights_sum_to_100(self): ...
    def test_lpips_excluded_if_none(self): ...    # single film, pas deep-compare

class TestBuildAudioSubscores(unittest.TestCase):
    def test_contains_mel_if_enabled(self): ...
    def test_contains_drc_category(self): ...
    def test_contains_spectral_verdict(self): ...

class TestBuildCoherenceSubscores(unittest.TestCase):
    def test_runtime_vs_tmdb_mapped(self): ...
    def test_nfo_consistency_mapped(self): ...

class TestApplyContextualAdjustments(unittest.TestCase):
    def test_rule1_film_grain_bonus(self): ...
    def test_rule1_partial_dnr_malus(self): ...
    def test_rule2_av1_afgs1_bonus(self): ...
    def test_rule3_dv_profile_5_malus(self): ...
    def test_rule4_hdr_metadata_missing_malus(self): ...
    def test_rule5_imax_expansion_bonus(self): ...
    def test_rule6_fake_lossless_malus(self): ...
    def test_rule7_version_hint_no_malus_but_warning(self): ...
    def test_rule8_animation_skips_grain_penalties(self): ...
    def test_rule9_vintage_master_tolerance(self): ...
    def test_multiple_rules_compound(self): ...     # plusieurs règles simultanées

class TestDetermineTierV2(unittest.TestCase):
    def test_95_returns_platinum(self): ...
    def test_85_returns_gold(self): ...
    def test_70_returns_silver(self): ...
    def test_55_returns_bronze(self): ...
    def test_45_returns_reject(self): ...

class TestCollectWarnings(unittest.TestCase):
    def test_runtime_mismatch_warning(self): ...
    def test_dv_profile_5_warning(self): ...
    def test_low_confidence_warning(self): ...
    def test_imbalance_warning(self): ...
    def test_no_warnings_perfect_file(self): ...

class TestComputeGlobalScoreV2(unittest.TestCase):
    def test_perfect_uhd_hdr_platinum(self): ...
    def test_dnr_aggressive_bluray_bronze(self): ...
    def test_fake_4k_reject(self): ...
    def test_animation_skips_grain(self): ...
    def test_imax_expansion_platinum(self): ...
    def test_av1_afgs1_boost(self): ...
    def test_confidence_low_adjusts_score(self): ...
    def test_missing_hdr_metadata_malus(self): ...
    def test_version_hint_warning_visible(self): ...

class TestCorpus(unittest.TestCase):
    """8 fichiers réels validation score final."""
    def test_dune_2021_uhd_dv_platinum(self): ...
    def test_blade_runner_uhd_authentic_gold(self): ...
    def test_blade_runner_bluray_2008_dnr_bronze(self): ...
    def test_fake_4k_upscale_reject(self): ...
    def test_oppenheimer_imax_expansion_platinum(self): ...
```

```javascript
// tests/e2e/test_score_composite_v7_5_0.py (~20 tests Playwright)

class TestScoreCircle(unittest.TestCase):
    def test_animation_plays_on_load(self): ...
    def test_color_matches_tier(self): ...
    def test_value_rendered_correctly(self): ...

class TestScoreGauges(unittest.TestCase):
    def test_three_gauges_rendered(self): ...
    def test_widths_proportional_to_weights(self): ...
    def test_colors_match_category_tiers(self): ...

class TestScoreAccordion(unittest.TestCase):
    def test_click_expands_category(self): ...
    def test_subscores_visible_after_expand(self): ...
    def test_tooltip_fr_shows_on_hover(self): ...
    def test_low_confidence_subscores_transparent(self): ...

class TestWarnings(unittest.TestCase):
    def test_yellow_encart_visible_when_flags(self): ...
    def test_runtime_mismatch_warning_text_fr(self): ...
    def test_dv_profile_5_warning_text_fr(self): ...

class TestRadarToggle(unittest.TestCase):
    def test_radar_hidden_by_default(self): ...
    def test_toggle_shows_radar_chart(self): ...
```

**Cas limites à tester explicitement :**

- Toutes les features optionnelles désactivées (pas de Mel, pas de LPIPS, pas de spectral) → score composite dégradé, pondérations renormalisées.
- ffmpeg indisponible → pas d'analyse possible, score null, UI affiche "Analyse impossible".
- Fichier trop court (< 90s) : confidence réduite partout, score quand même calculable, warning `short_file_limited_analysis`.
- Toutes confidence = 0 (cas pathologique) : fallback score = 50, tier "silver", warning clair.
- Film archive années 40-50 : ère `16mm_era`, tolérance grain/spectral appliquée, score correct.
- Fichier 8K : scaled treatments adaptés, pas de faux positif upscale.

**Effort réévalué :** **30h** (14h backend + 12h frontend + 4h tests) — dépend de la qualité des composants UI CinemaLux existants (certains sont déjà disponibles).

**Note packaging :**
- Aucune dépendance nouvelle (tout est Python stdlib + numpy).
- Nouveaux modules aux `hiddenimports` CineSort.spec :
  ```python
  "cinesort.domain.perceptual.composite_score_v2",
  ```

**Impact sur l'existant :**
- `composite_score.py` existant **refactoré** pour déléguer à v2. Pas de rupture backward compat.
- Le score existant (`global_score`, `global_tier`) reste exposé avec les anciennes valeurs pour les rows v7.4 (migration progressive lors du re-scan).

---

## Récapitulatif Vague 6

| § | Effort |
|---|---|
| §16 Score composite et visualisation | 30h |
| **Total Vague 6** | **30h** |

---

## Fin du plan de code
