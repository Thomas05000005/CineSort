"""Issue #560 — vectorisation numpy de `_texture_zone_variance` et `detect_mp3_shelf`.

Une optimisation qui change un RESULTAT est un bug, pas un gain. Ces tests
verrouillent donc deux choses distinctes.

1. EQUIVALENCE NUMERIQUE contre une reference naive qui reproduit exactement la
   boucle Python remplacee. La vectorisation change l'ordre des sommations
   flottantes ; les tolerances ci-dessous sont mesurees, pas devinees
   (cf. `_TEXTURE_RTOL` et `_SHELF_ATOL_DB`).

2. BUDGET DE TRAVAIL, compte par un espion — jamais par un chronometre. Ce depot
   a deja produit un test de perf flaky qui mesurait un rapport de durees sur un
   runner partage. Ici on compte le nombre de reductions numpy declenchees :
   c'est deterministe et ca ne depend d'aucune charge machine.

   Mesure sur `main` avant correctif, 2 frames 1080p en blocs 16x16 :
   **16 080 appels a `.var()`** (8040 blocs par frame). Apres : **2**.
   `detect_mp3_shelf` sur 700 frames : **1400 appels a `.mean()`**. Apres : **2**.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest import mock

import numpy as np

import cinesort.domain.perceptual.grain_classifier as grain_classifier
from cinesort.domain.perceptual.constants import (
    MEL_MP3_SHELF_DROP_DB,
    TEXTURE_ZONE_VARIANCE_MAX,
    TEXTURE_ZONE_VARIANCE_MIN,
)
from cinesort.domain.perceptual.grain_classifier import _texture_zone_variance
from cinesort.domain.perceptual.mel_analysis import detect_mp3_shelf

# ---------------------------------------------------------------------------
# Tolerances : mesurees sur les profils ci-dessous, puis justifiees
# ---------------------------------------------------------------------------

# Ecart relatif observe sur la valeur RENDUE par `_texture_zone_variance`, sur
# 6 profils de frames 1080p (~8000 blocs chacun) : 0 a 1.5e-16, soit au plus
# 1 ulp de float64 (eps = 2.2e-16). Le pire ecart bloc a bloc etait 6.5e-16
# (~3 ulp). 1e-12 laisse quatre ordres de grandeur de marge pour une variation
# d'implementation numpy (pairwise summation, SIMD), tout en restant onze ordres
# sous ce qui pourrait deplacer la decision metier : le verdict DNR compare
# `texture_actual / baseline` a DNR_PARTIAL_TEXTURE_RATIO = 0.7.
_TEXTURE_RTOL = 1e-12

# Pour le shelf MP3, la grandeur qui decide est ABSOLUE : une frame compte des
# lors que son drop depasse MEL_MP3_SHELF_DROP_DB = 20 dB. C'est donc l'ecart
# absolu en dB qu'il faut borner, pas un ecart relatif (lequel explose sans
# signification sur les drops proches de zero). Ecart mesure en float64 — le
# dtype que produit reellement `analyze_mel` : <= 2.2e-14 dB sur les drops,
# <= 3.4e-16 dB sur la moyenne rendue. 1e-9 dB reste sept ordres de grandeur
# sous 0.01 dB, deja inaudible et bien en deca de la resolution de la mesure.
_SHELF_ATOL_DB = 1e-9

_BLOCK = 16


# ---------------------------------------------------------------------------
# References naives : la boucle Python telle qu'elle etait avant #560
# ---------------------------------------------------------------------------


def _ref_texture_zone_variance(frames_y: List[np.ndarray], block_size: int = _BLOCK) -> float:
    if not frames_y:
        return 0.0
    variances: List[float] = []
    for frame in frames_y:
        if frame is None or frame.ndim != 2:
            continue
        h, w = frame.shape
        if h < block_size or w < block_size:
            continue
        arr = frame.astype(np.float64, copy=False)
        for y in range(0, h - block_size + 1, block_size):
            for x in range(0, w - block_size + 1, block_size):
                var = float(np.var(arr[y : y + block_size, x : x + block_size]))
                if TEXTURE_ZONE_VARIANCE_MIN < var < TEXTURE_ZONE_VARIANCE_MAX:
                    variances.append(var)
    if not variances:
        return 0.0
    return float(np.mean(variances))


def _ref_mp3_shelf(mel_spec_db: np.ndarray, mel_freqs_hz: np.ndarray) -> Dict[str, Any]:
    before_idx = np.where((mel_freqs_hz >= 14000.0) & (mel_freqs_hz < 16000.0))[0]
    after_idx = np.where((mel_freqs_hz >= 16000.0) & (mel_freqs_hz < 18000.0))[0]
    if before_idx.size == 0 or after_idx.size == 0:
        return {"shelf_detected": False, "shelf_drop_db": 0.0, "frames_pct": 0.0}
    drops = []
    for i in range(mel_spec_db.shape[0]):
        before_pow = float(np.mean(mel_spec_db[i, before_idx]))
        after_pow = float(np.mean(mel_spec_db[i, after_idx]))
        drops.append(before_pow - after_pow)
    arr = np.asarray(drops, dtype=np.float64)
    frames_with_shelf = int(np.sum(arr > MEL_MP3_SHELF_DROP_DB))
    frames_pct = 100.0 * frames_with_shelf / max(1, arr.size)
    return {
        "shelf_detected": frames_pct >= 70.0,
        "shelf_drop_db": float(arr.mean()) if arr.size else 0.0,
        "frames_pct": frames_pct,
    }


# ---------------------------------------------------------------------------
# L'espion qui COMPTE (pas un chronometre)
# ---------------------------------------------------------------------------


class _CountingArray(np.ndarray):
    """Vrai `ndarray` qui compte ses propres reductions.

    Sous-classe et non `MagicMock` : le calcul a lieu pour de bon et le resultat
    est celui de numpy. Un faux tableau fabriquerait la condition mesuree.
    `numpy.var`/`numpy.mean` delegant aux methodes pour les sous-classes, les
    deux formes d'appel (fonction et methode) sont comptees.
    """

    def __array_finalize__(self, obj: Any) -> None:
        if obj is not None:
            self.tally = getattr(obj, "tally", None)

    def var(self, *args: Any, **kwargs: Any) -> Any:
        if getattr(self, "tally", None) is not None:
            self.tally["var"] += 1
        return np.ndarray.var(self, *args, **kwargs)

    def mean(self, *args: Any, **kwargs: Any) -> Any:
        if getattr(self, "tally", None) is not None:
            self.tally["mean"] += 1
        return np.ndarray.mean(self, *args, **kwargs)


def _counted(arr: np.ndarray, tally: Dict[str, int]) -> np.ndarray:
    out = np.asarray(arr).view(_CountingArray)
    out.tally = tally
    return out


# ---------------------------------------------------------------------------
# Jeux de frames : profils qui ressemblent a une image de film
# ---------------------------------------------------------------------------


def _frame_profiles() -> Dict[str, List[np.ndarray]]:
    rng = np.random.default_rng(20260805)
    h, w = 540, 960
    yy, xx = np.mgrid[0:h, 0:w]
    base = 16.0 + 200.0 * (yy / h) * (0.5 + 0.5 * np.sin(xx / 137.0))

    # Bandes de grain croissant : balaie tout le spectre de variance et pose donc
    # des blocs des DEUX cotes des seuils 10 / 500 — c'est la que la selection
    # est la plus sensible a un ecart d'arrondi.
    swept = np.full((h, w), 64.0)
    for i, sigma in enumerate(np.linspace(0.0, 40.0, h // _BLOCK)):
        swept[i * _BLOCK : (i + 1) * _BLOCK, :] += rng.normal(0, sigma, (_BLOCK, w))

    return {
        "grain_fin": [np.clip(base + rng.normal(0, 3.0, (h, w)), 0, 255) for _ in range(3)],
        "grain_marque": [np.clip(base + rng.normal(0, 12.0, (h, w)), 0, 255) for _ in range(3)],
        "uint8_quantifie": [np.clip(base + rng.normal(0, 8.0, (h, w)), 0, 255).astype(np.uint8) for _ in range(3)],
        "texture_fine": [np.clip(128 + 30 * np.sin(xx / 3.0) * np.cos(yy / 3.0), 0, 255)],
        "seuils_balayes": [np.clip(swept, 0, 255)],
        "dimensions_non_multiples": [
            np.clip(base + rng.normal(0, 6.0, (h, w)), 0, 255)[: h - 7, : w - 11] for _ in range(2)
        ],
        "melange_plat_et_texture": [
            np.clip(base + rng.normal(0, 2.0, (h, w)), 0, 255),
            np.full((h, w), 64.0),
            np.clip(128 + 30 * np.sin(xx / 3.0) * np.cos(yy / 3.0), 0, 255),
        ],
    }


class TextureZoneVarianceEquivalenceTests(unittest.TestCase):
    def test_matches_the_replaced_python_loop_on_every_profile(self) -> None:
        for name, frames in _frame_profiles().items():
            with self.subTest(profil=name):
                expected = _ref_texture_zone_variance(frames)
                got = _texture_zone_variance(frames)
                self.assertGreater(expected, 0.0, "profil sans bloc texture : ne prouverait rien")
                self.assertAlmostEqual(
                    got / expected,
                    1.0,
                    delta=_TEXTURE_RTOL,
                    msg=f"{name} : attendu {expected!r}, obtenu {got!r}",
                )

    def test_block_grid_matches_the_replaced_loop_on_odd_dimensions(self) -> None:
        """Le rognage `(h // bs) * bs` doit reproduire `range(0, h - bs + 1, bs)`.

        Une frame dont les cotes ne sont pas multiples de 16 est le cas ou une
        erreur de decoupage se voit : elle ferait entrer ou sortir une rangee
        entiere de blocs, donc deplacerait franchement la moyenne.
        """
        rng = np.random.default_rng(7)
        for h, w in ((100, 100), (101, 97), (16, 16), (31, 31), (255, 129)):
            with self.subTest(shape=(h, w)):
                frame = np.clip(128 + rng.normal(0, 9.0, (h, w)), 0, 255)
                expected = _ref_texture_zone_variance([frame])
                got = _texture_zone_variance([frame])
                if expected == 0.0:
                    self.assertEqual(got, 0.0)
                else:
                    self.assertAlmostEqual(got / expected, 1.0, delta=_TEXTURE_RTOL)

    def test_degenerate_inputs_behave_as_before(self) -> None:
        rng = np.random.default_rng(11)
        good = np.clip(128 + rng.normal(0, 9.0, (64, 64)), 0, 255)
        cases: List[List[Any]] = [
            [],
            [None],
            [np.zeros((3,))],
            [np.zeros((4, 4, 4))],
            [np.full((64, 64), 128.0)],  # variance nulle : sous le seuil bas
            [np.zeros((8, 8))],  # plus petit qu'un bloc
            [None, good, np.zeros((8, 8))],
        ]
        for i, frames in enumerate(cases):
            with self.subTest(cas=i):
                self.assertEqual(_texture_zone_variance(frames), _ref_texture_zone_variance(frames))

    def test_blocks_outside_the_texture_band_stay_excluded(self) -> None:
        flat = np.full((64, 64), 100.0)
        self.assertEqual(_texture_zone_variance([flat]), 0.0)
        self.assertEqual(_texture_zone_variance([flat]), _ref_texture_zone_variance([flat]))

        rng = np.random.default_rng(3)
        loud = np.clip(128 + rng.normal(0, 400.0, (64, 64)), -1e6, 1e6)
        self.assertEqual(_texture_zone_variance([loud]), _ref_texture_zone_variance([loud]))
        self.assertLess(_texture_zone_variance([loud]), TEXTURE_ZONE_VARIANCE_MAX)

    def test_bounds_stay_strict_on_a_block_sitting_exactly_on_them(self) -> None:
        """Bornes STRICTES : ]MIN, MAX[ et non [MIN, MAX].

        Sur des donnees quelconques la variance ne tombe jamais pile sur 10.0 ou
        500.0, si bien qu'un `>=` a la place de `>` restait invisible : la
        condition n'etait pas atteinte, ce n'est donc pas un mutant equivalent
        mais un test manquant. On la FORCE ici.

        Un bloc 16x16 dont la moitie des pixels vaut 0 et l'autre V a pour
        variance V^2/4, calculee exactement en float64 pour V entier petit
        (verifie : V=4 -> 4.0, V=8 -> 16.0, V=16 -> 64.0, egalite stricte). Les
        seuils sont deplaces sur 4.0 et 64.0 le temps du test : seul le bloc du
        milieu (16.0) doit etre retenu.
        """

        def block(v: float) -> np.ndarray:
            blk = np.zeros((_BLOCK, _BLOCK), dtype=np.float64)
            blk[: _BLOCK // 2, :] = v
            return blk

        on_min, inside, on_max = block(4.0), block(8.0), block(16.0)
        self.assertEqual(float(on_min.var()), 4.0)
        self.assertEqual(float(inside.var()), 16.0)
        self.assertEqual(float(on_max.var()), 64.0)

        frame = np.hstack([on_min, inside, on_max])
        with mock.patch.object(grain_classifier, "TEXTURE_ZONE_VARIANCE_MIN", 4.0):
            with mock.patch.object(grain_classifier, "TEXTURE_ZONE_VARIANCE_MAX", 64.0):
                got = _texture_zone_variance([frame])
        self.assertEqual(
            got,
            16.0,
            "les blocs PILE sur les bornes doivent rester exclus ; une moyenne "
            f"differente de 16.0 (obtenu {got!r}) signale un `>=` ou un `<=`",
        )


class TextureZoneVarianceWorkBudgetTests(unittest.TestCase):
    def test_one_reduction_per_frame_not_one_per_block(self) -> None:
        rng = np.random.default_rng(20260805)
        frames = [np.clip(128 + rng.normal(0, 6.0, (540, 960)), 0, 255) for _ in range(2)]
        blocks_per_frame = (540 // _BLOCK) * (960 // _BLOCK)
        self.assertGreater(blocks_per_frame, 1000, "frame trop petite pour que la mesure ait un sens")

        tally = {"var": 0, "mean": 0}
        counted = _texture_zone_variance([_counted(f, tally) for f in frames])

        self.assertLessEqual(
            tally["var"],
            len(frames),
            f"au plus une reduction de variance par frame attendue ; mesure {tally['var']} "
            f"pour {len(frames)} frames de {blocks_per_frame} blocs",
        )
        # Garde-fou sur l'instrument : l'espion ne doit pas changer le resultat.
        self.assertEqual(counted, _texture_zone_variance(frames))


# ---------------------------------------------------------------------------
# detect_mp3_shelf
# ---------------------------------------------------------------------------


def _mel_freqs(n: int = 128) -> np.ndarray:
    return np.linspace(0.0, 24000.0, n)


def _spectrogram_profiles() -> Dict[str, np.ndarray]:
    rng = np.random.default_rng(20260805)
    freqs = _mel_freqs()
    shelf = rng.uniform(-30.0, -10.0, (700, 128))
    shelf[:, freqs >= 16000.0] -= 45.0
    quasi = np.zeros((500, 128))
    quasi[:, (freqs >= 14000.0) & (freqs < 16000.0)] = MEL_MP3_SHELF_DROP_DB
    return {
        "bruit_uniforme": rng.uniform(-80.0, 0.0, (700, 128)),
        "shelf_franc_16k": shelf,
        "drops_pile_sur_le_seuil": quasi,
        "une_seule_frame": rng.uniform(-80.0, 0.0, (1, 128)),
        "spectro_court": rng.uniform(-80.0, 0.0, (3, 128)),
    }


class Mp3ShelfEquivalenceTests(unittest.TestCase):
    def test_matches_the_replaced_python_loop_on_every_profile(self) -> None:
        freqs = _mel_freqs()
        for name, spec in _spectrogram_profiles().items():
            with self.subTest(profil=name):
                expected = _ref_mp3_shelf(spec, freqs)
                got = detect_mp3_shelf(spec, freqs)
                self.assertAlmostEqual(
                    got["shelf_drop_db"],
                    expected["shelf_drop_db"],
                    delta=_SHELF_ATOL_DB,
                    msg=f"{name} : drop moyen",
                )
                self.assertEqual(got["frames_pct"], expected["frames_pct"], f"{name} : % de frames")
                self.assertEqual(got["shelf_detected"], expected["shelf_detected"], f"{name} : verdict")

    def test_guard_paths_are_unchanged(self) -> None:
        freqs = _mel_freqs()
        empty = detect_mp3_shelf(np.zeros((0, 0)), freqs)
        self.assertEqual(empty, {"shelf_detected": False, "shelf_drop_db": 0.0, "frames_pct": 0.0})

        # Nyquist a 12 kHz : aucune bande dans [14k, 18k[, rien de mesurable.
        low = detect_mp3_shelf(np.zeros((10, 32)), np.linspace(0.0, 12000.0, 32))
        self.assertEqual(low, {"shelf_detected": False, "shelf_drop_db": 0.0, "frames_pct": 0.0})

    def test_float32_input_gives_the_same_bits_as_the_widened_float64(self) -> None:
        """L'accumulation doit rester en float64 meme sur une entree float32.

        Le pipeline `analyze_mel` fournit du float64 (verifie sur des
        echantillons f64, f32 et int16), mais la fonction est publique. Sans
        `dtype=np.float64`, la reduction ET la soustraction se feraient en
        float32 — moins precis que la boucle remplacee, qui repassait par un
        `float()` Python a chaque frame.

        L'assertion est une egalite STRICTE, et pas une tolerance : un float32
        est exactement representable en float64, donc les deux appels ne peuvent
        differer que par la largeur de l'accumulateur. Une tolerance lache (1e-6)
        laissait passer le retrait du `dtype`, dont l'effet mesure n'etait que de
        1.7e-7 dB sur ce jeu.
        """
        rng = np.random.default_rng(5)
        spec32 = rng.uniform(-80.0, 0.0, (400, 128)).astype(np.float32)
        freqs = _mel_freqs()
        self.assertEqual(
            detect_mp3_shelf(spec32, freqs),
            detect_mp3_shelf(spec32.astype(np.float64), freqs),
        )


class Mp3ShelfWorkBudgetTests(unittest.TestCase):
    def test_two_reductions_whatever_the_number_of_frames(self) -> None:
        rng = np.random.default_rng(20260805)
        freqs = _mel_freqs()
        spec = rng.uniform(-80.0, 0.0, (700, 128))

        tally = {"var": 0, "mean": 0}
        counted = detect_mp3_shelf(_counted(spec, tally), freqs)

        self.assertLessEqual(
            tally["mean"],
            2,
            f"deux reductions attendues (avant / apres 16 kHz) ; mesure {tally['mean']} pour {spec.shape[0]} frames",
        )
        # Garde-fou sur l'instrument.
        self.assertEqual(counted, detect_mp3_shelf(spec, freqs))


if __name__ == "__main__":
    unittest.main()
