"""Lot « compteurs et valeurs qui mentent a l'utilisateur » — #686, #472, #381.

Trois grandeurs affichees etaient nommees autrement que ce qu'elles mesuraient.

#686 — `_detect_cross_root_duplicates` renvoyait le nombre de RANGEES qu'elle
venait de flaguer ; le seul appelant l'annonce sous le libelle « N film(s) ».
Un film present dans deux racines faisait donc annoncer « 2 film(s) », dans
trois racines « 3 film(s) ». En prime, l'ordre des racines citees dans les
notes venait d'un `set` : le meme disque produisait deux plans differents d'une
execution a l'autre (hachage des chaines randomise par processus).

#472 — `get_quality_counts_for_runs` re-seuillait le `score` brut a 85 et 55
alors que le tier de chaque film est DEJA persiste, decide par les seuils du
profil qualite actif. Le 85 etait l'ancien seuil Platinum d'avant la
recalibration v1.5.7 (70/66/55/40) : un film Platinum a 78/100 etait affiche
Platinum par la page Qualite mais absent du compte « premium » du meme payload.

#381 — le seul champ lisible de l'analyse mel, `mel_verdict`, disait
« insufficient_data » (« je n'ai pas pu mesurer ») pour une mesure aboutie dont
le score etait simplement bas. La meme valeur servait aux deux sens opposes.
Ce fichier contient aussi la preuve executable que les sous-mesures mel ne sont
PAS orphelines — la premisse de l'issue —, puisqu'elles decident du score audio.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

import cinesort.domain.core as core
from cinesort.app.plan_support_dedup import _detect_cross_root_duplicates, plan_multi_roots
from cinesort.domain.core import PlanRow
from cinesort.domain.perceptual.audio_perceptual import _compute_audio_score
from cinesort.domain.perceptual.mel_analysis import analyze_mel, compute_mel_score

# ---------------------------------------------------------------------------
# #686 — le compteur de doublons cross-root
# ---------------------------------------------------------------------------


def _row(title: str, year: int, source_root: str) -> PlanRow:
    row = PlanRow(
        row_id=f"{title}_{year}_{source_root}",
        kind="single",
        folder="f",
        video="v.mkv",
        proposed_title=title,
        proposed_year=year,
        proposed_source="name",
        confidence=80,
        confidence_label="high",
        candidates=[],
    )
    row.source_root = source_root
    return row


class CrossRootCounterCountsFilmsTests(unittest.TestCase):
    """#686 — la valeur retournee compte des FILMS, comme le libelle l'annonce."""

    def test_un_film_dans_deux_racines_compte_un_seul_film(self) -> None:
        rows = [_row("Inception", 2010, r"C:\Films"), _row("Inception", 2010, r"D:\Films")]

        self.assertEqual(_detect_cross_root_duplicates(rows), 1)
        # Les DEUX rangees restent flaguees : c'est bien la grandeur qui change,
        # pas le marquage. Un correctif qui n'aurait flague qu'une rangee
        # (« deduplication ») ferait disparaitre l'alerte d'un cote.
        self.assertEqual(sum(1 for r in rows if "duplicate_cross_root" in (r.warning_flags or [])), 2)

    def test_un_film_dans_trois_racines_compte_toujours_un_seul_film(self) -> None:
        """Le facteur d'erreur suivait le nombre de racines : 3 racines -> « 3 film(s) »."""
        rows = [
            _row("Dune", 2021, r"C:\Films"),
            _row("Dune", 2021, r"D:\Films"),
            _row("Dune", 2021, r"E:\Films"),
        ]

        self.assertEqual(_detect_cross_root_duplicates(rows), 1)
        self.assertEqual(sum(1 for r in rows if "duplicate_cross_root" in (r.warning_flags or [])), 3)

    def test_deux_films_distincts_comptent_deux(self) -> None:
        """Garde-fou : un correctif qui retournerait « 1 » en dur passerait les
        deux tests precedents. Deux films distincts doivent bien compter 2."""
        rows = [
            _row("Inception", 2010, r"C:\Films"),
            _row("Inception", 2010, r"D:\Films"),
            _row("Dune", 2021, r"C:\Films"),
            _row("Dune", 2021, r"D:\Films"),
        ]

        self.assertEqual(_detect_cross_root_duplicates(rows), 2)

    def test_un_film_dans_une_seule_racine_ne_compte_pas(self) -> None:
        rows = [_row("Matrix", 1999, r"C:\Films"), _row("Matrix", 1999, r"C:\Films")]

        self.assertEqual(_detect_cross_root_duplicates(rows), 0)
        self.assertEqual([r.warning_flags or [] for r in rows], [[], []])

    def test_rangees_deja_flaguees_ne_changent_pas_le_compte(self) -> None:
        """Le `+= 1` etait DANS le `if flag pas deja pose`.

        Sur un re-plan qui repart de rangees deja flaguees (resync), le meme
        etat de disque annoncait donc 2, 1 ou 0 selon ce qui restait a poser.
        Le nombre de films en double, lui, ne depend pas de l'ordre des passes.
        """
        rows = [_row("Alien", 1979, r"C:\Films"), _row("Alien", 1979, r"D:\Films")]
        rows[0].warning_flags = ["duplicate_cross_root"]

        self.assertEqual(_detect_cross_root_duplicates(rows), 1)

    def test_ordre_des_racines_citees_est_trie(self) -> None:
        """L'ordre venait d'un `set` : non reproductible entre deux processus.

        Six racines fournies a l'envers de leur ordre alphabetique : la note
        doit les citer triees, donc dans un ordre qui ne depend ni de l'ordre
        d'insertion ni du hachage.
        """
        roots = [r"F:\Films", r"E:\Films", r"D:\Films", r"C:\Films", r"B:\Films", r"A:\Films"]
        rows = [_row("Solaris", 1972, rt) for rt in roots]

        _detect_cross_root_duplicates(rows)

        # La rangee de A: cite les cinq autres, dans l'ordre trie.
        note_a = next(r.notes for r in rows if r.source_root == r"A:\Films")
        self.assertEqual(
            note_a,
            r" | Aussi dans: B:\Films, C:\Films, D:\Films, E:\Films, F:\Films",
        )
        # Et la rangee de F: cite les cinq autres, dans le meme ordre trie.
        note_f = next(r.notes for r in rows if r.source_root == r"F:\Films")
        self.assertEqual(
            note_f,
            r" | Aussi dans: A:\Films, B:\Films, C:\Films, D:\Films, E:\Films",
        )


class CrossRootMessageTests(unittest.TestCase):
    """#686 — le SITE D'APPEL : ce que l'utilisateur lit reellement.

    Corriger la fonction sans corriger son unique appelant n'aurait rien change
    au message affiche pendant le scan.
    """

    @staticmethod
    def _make_movie_folder(root: Path, title: str, year: int) -> Path:
        folder = root / f"{title} ({year})"
        folder.mkdir(parents=True, exist_ok=True)
        # 11 Mo : au-dessus de MIN_VIDEO_BYTES (10 Mo), sinon la video est ignoree.
        (folder / f"{title} ({year}).mkv").write_bytes(b"\x00" * (11 * 1024 * 1024))
        return folder

    def test_le_scan_annonce_un_film_et_deux_dossiers(self) -> None:
        with (
            tempfile.TemporaryDirectory(prefix="cnt686_a_") as tmp_a,
            tempfile.TemporaryDirectory(prefix="cnt686_b_") as tmp_b,
        ):
            root_a, root_b = Path(tmp_a), Path(tmp_b)
            self._make_movie_folder(root_a, "Inception", 2010)
            self._make_movie_folder(root_b, "Inception", 2010)

            logs: list[tuple[str, str]] = []
            rows, _stats = plan_multi_roots(
                [root_a, root_b],
                build_cfg=lambda r: core.Config(root=r, enable_tmdb=False),
                tmdb=None,
                log=lambda level, msg: logs.append((level, msg)),
                progress=lambda *_a, **_kw: None,
            )

            self.assertEqual(len(rows), 2, "setup : deux rangees, une par racine")
            dup_msgs = [msg for _lvl, msg in logs if "cross-root" in msg]
            self.assertEqual(len(dup_msgs), 1, f"un seul message attendu, obtenu : {dup_msgs}")
            message = dup_msgs[0]

            # Assertions bornees sur le TEXTE complet : `assertIn("1 film")`
            # passerait aussi sur « 11 film(s) ».
            self.assertIn("1 film(s) present(s) dans plusieurs racines", message)
            self.assertIn("(2 dossier(s) concerne(s))", message)
            # Et surtout : le vieux message exact ne doit plus etre produisible.
            self.assertNotIn("2 film(s)", message)


# ---------------------------------------------------------------------------
# #472 — premium_count / low_count suivent le tier persiste, pas un seuil fige
# ---------------------------------------------------------------------------


class QualityCountsFollowPersistedTierTests(unittest.TestCase):
    """#472 — les agregats et la distribution par tier doivent s'accorder."""

    def setUp(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        self._tmp = tempfile.mkdtemp(prefix="cnt472_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api.settings.save_settings(
            {"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False}
        )
        self.store, _ = self.api._get_or_create_infra(self.state_dir)
        self.run_id = "run_472"
        self.store.run.insert_run_pending(
            run_id=self.run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={},
            created_ts=1000.0,
        )
        self.store.run.mark_run_running(self.run_id, started_ts=1001.0)
        self.store.run.mark_run_done(self.run_id, stats={"planned_rows": 4}, ended_ts=1002.0)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _insert(self, row_id: str, score: int, tier: str) -> None:
        self.store.quality.upsert_quality_report(
            run_id=self.run_id,
            row_id=row_id,
            score=score,
            tier=tier,
            reasons=[],
            metrics={},
            profile_id="default",
            profile_version=1,
        )

    def test_platinum_sous_85_est_compte_premium(self) -> None:
        """Le cas decisif : profil par defaut (platinum=70), film a 78.

        La page Qualite l'affiche Platinum (elle agrege la colonne `tier`), le
        compte « premium » du MEME payload l'ignorait (il re-seuillait a 85).
        """
        self._insert("row_a", score=78, tier="Platinum")
        self._insert("row_b", score=92, tier="Platinum")

        counts = self.store.quality.get_quality_counts_for_runs([self.run_id])[self.run_id]

        self.assertEqual(counts["premium_count"], 2)
        self.assertEqual(counts["scored_movies"], 2)

    def test_score_eleve_mais_tier_plafonne_n_est_pas_premium(self) -> None:
        """Sens inverse, et c'est le cas qui interdit de garder le score.

        Le tier n'est pas une simple fonction du score : `cap_tier` le plafonne
        (probe FAILED, source CAM) et la hierarchie multi-axes le borne. Un
        film a 90 plafonne Silver etait compte « premium » alors qu'aucune
        surface ne l'affiche premium.
        """
        self._insert("row_c", score=90, tier="Silver")

        counts = self.store.quality.get_quality_counts_for_runs([self.run_id])[self.run_id]

        self.assertEqual(counts["premium_count"], 0)

    def test_low_count_suit_le_tier_et_pas_le_seuil_55(self) -> None:
        """Bronze/Reject = « sous Silver ». Un Silver a 52 (profil permissif)
        n'est pas un film de basse qualite, il etait compte comme tel."""
        self._insert("row_d", score=52, tier="Silver")
        self._insert("row_e", score=45, tier="Bronze")
        self._insert("row_f", score=20, tier="Reject")

        counts = self.store.quality.get_quality_counts_for_runs([self.run_id])[self.run_id]

        self.assertEqual(counts["low_count"], 2)

    def test_alias_legacy_premium_reste_compte(self) -> None:
        """Les bases anterieures a la migration 011 ecrivaient « Premium »."""
        self._insert("row_g", score=61, tier="Premium")

        counts = self.store.quality.get_quality_counts_for_runs([self.run_id])[self.run_id]

        self.assertEqual(counts["premium_count"], 1)

    def test_le_dashboard_expose_le_meme_decoupage_que_la_distribution(self) -> None:
        """SITE D'APPEL : `summary.premium_pct` et `tier_distribution` sortent
        du MEME payload `get_global_stats` et se contredisaient."""
        for i in range(4):
            self._insert(f"row_dash_{i}", score=78, tier="Platinum")

        result = self.api._get_global_stats_impl(20)

        self.assertTrue(result["ok"])
        self.assertEqual(int(result["tier_distribution"].get("platinum", 0) or 0), 4)
        self.assertEqual(result["summary"]["premium_pct"], 100.0)


# ---------------------------------------------------------------------------
# #381 — mel : un verdict qui ne ment plus, et des sous-scores bien consommes
# ---------------------------------------------------------------------------


class MelVerdictDistinguishesLowScoreFromNoMeasureTests(unittest.TestCase):
    """#381 — « pas de donnees » et « donnees mediocres » ne sont plus le meme mot."""

    # Detections MESUREES et degradees, sans motif dominant : soft clipping en
    # « warn » (pas severe), trous AAC en « warn » (pas severe), pas de shelf
    # MP3, flatness tres loin du sweet spot. Score compose attendu ~52.
    _SOFT_WARN = {"pct_frames_with_harmonics": 28.0, "verdict": "warn"}
    _MP3_ABSENT = {"shelf_detected": False, "shelf_drop_db": 20.0, "frames_pct": 10.0}
    _AAC_WARN = {"hole_ratio": 0.09, "synthetic_ratio": 0.02, "verdict": "warn"}

    def test_mesure_aboutie_mais_basse_rend_degraded(self) -> None:
        score, verdict = compute_mel_score(self._SOFT_WARN, self._MP3_ABSENT, self._AAC_WARN, flatness=0.95)

        self.assertLess(score, 70, "setup : ce jeu doit bien tomber sous le seuil 'clean'")
        self.assertEqual(verdict, "degraded")

    def test_le_verdict_insufficient_data_n_est_plus_produit_par_le_score(self) -> None:
        """Il ne doit plus sortir d'AUCUNE combinaison de detections abouties.

        Balayage du plan (soft clipping x trous AAC x flatness) : toutes ces
        entrees viennent de detecteurs qui ont abouti, donc aucune ne peut
        legitimement rendre « donnees insuffisantes ».
        """
        for pct in (0.0, 10.0, 28.0, 50.0, 100.0):
            for ratio in (0.0, 0.04, 0.09, 0.5):
                for flat in (0.0, 0.3, 0.7, 1.0):
                    soft_verdict = "severe" if pct >= 30.0 else ("warn" if pct >= 15.0 else "normal")
                    aac_verdict = "severe" if ratio >= 0.10 else ("warn" if ratio >= 0.05 else "normal")
                    _score, verdict = compute_mel_score(
                        {"pct_frames_with_harmonics": pct, "verdict": soft_verdict},
                        self._MP3_ABSENT,
                        {"hole_ratio": ratio, "verdict": aac_verdict},
                        flatness=flat,
                    )
                    self.assertNotEqual(
                        verdict,
                        "insufficient_data",
                        f"mesure aboutie (pct={pct}, ratio={ratio}, flat={flat}) etiquetee non mesuree",
                    )

    def test_signal_trop_court_reste_insufficient_data(self) -> None:
        """L'autre moitie du contrat : la ou il n'y a VRAIMENT pas de mesure,
        le mot ne change pas. Sans cette garde, « corriger » le verdict aurait
        pu effacer le seul signal d'une analyse impossible."""
        result = analyze_mel(np.zeros(100, dtype=np.float32))

        self.assertEqual(result.mel_verdict, "insufficient_data")
        self.assertEqual(result.mel_score, 0)

    def test_un_verdict_clean_reste_clean(self) -> None:
        soft = {"pct_frames_with_harmonics": 2.0, "verdict": "normal"}
        aac = {"hole_ratio": 0.01, "verdict": "normal"}
        score, verdict = compute_mel_score(soft, self._MP3_ABSENT, aac, flatness=0.3)

        self.assertGreaterEqual(score, 70)
        self.assertEqual(verdict, "clean")


class MelSubScoresAreConsumedTests(unittest.TestCase):
    """#381 — la premisse « calcules pour rien » est FAUSSE : preuve executable.

    L'issue conclut que le moteur perceptuel passe ~1,5 s par film a calculer
    ces metriques « pour rien » et propose de les afficher ou de les supprimer.
    Les supprimer aurait change le score audio de toute la bibliotheque : les
    quatre sous-mesures composent `mel_score` (poids 40/20/30/10), qui pese
    `AUDIO_WEIGHT_MEL` = 15 % dans `_compute_audio_score`, donc dans
    `audio_score` et `audio_tier` — que l'utilisateur, lui, voit.
    """

    @staticmethod
    def _white_noise(n: int, seed: int) -> np.ndarray:
        return np.asarray(np.random.default_rng(seed).standard_normal(n) * 0.1, dtype=np.float32)

    @staticmethod
    def _low_pass(samples: np.ndarray, sample_rate: int, cutoff: float) -> np.ndarray:
        spectrum = np.fft.rfft(samples)
        freqs = np.fft.rfftfreq(samples.size, d=1.0 / sample_rate)
        spectrum[freqs > cutoff] = 0.0
        return np.asarray(np.fft.irfft(spectrum, n=samples.size), dtype=np.float32)

    def test_une_sous_mesure_degradee_fait_baisser_le_score_audio(self) -> None:
        clean = self._white_noise(48000 * 2, seed=11)
        shelved = self._low_pass(clean, 48000, 16000.0)

        mel_clean = analyze_mel(clean)
        mel_shelved = analyze_mel(shelved)

        # La sous-mesure change (c'est bien elle que le low-pass 16 kHz touche)...
        self.assertFalse(mel_clean.mel_mp3_shelf_detected)
        self.assertTrue(mel_shelved.mel_mp3_shelf_detected)
        # ... le composite mel la repercute...
        self.assertLess(mel_shelved.mel_score, mel_clean.mel_score)
        # ... et le score audio final, lui aussi. Aucun mock : les deux appels
        # ne different que par le contenu du signal.
        score_clean = _compute_audio_score(None, None, None, mel=mel_clean)
        score_shelved = _compute_audio_score(None, None, None, mel=mel_shelved)
        self.assertLess(score_shelved, score_clean)


if __name__ == "__main__":
    unittest.main()
