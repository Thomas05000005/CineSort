"""F09 — le cache row v2 ne doit pas figer les infos SOUS-TITRES.

La cle de validite du cache row (taille/mtime/hash video + nfo_sig + kind +
cfg_sig) ne reflete AUCUN fichier .srt voisin : `_plan_item` faisait
`return [cached_row]` AVANT `_apply_subtitle_detection`. Ajouter un
sous-titre externe apres coup laissait donc le faux flag `subtitle_missing_fr`,
que `persist_folder_cache` refigeait ensuite sous la nouvelle folder_sig
(staleness permanente).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir


class RowCacheSubtitleStalenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_subs_f09_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.store = SQLiteStore(db_path_for_state_dir(self.state_dir))
        self.store.initialize()

        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

        self.folder = self.root / "Inception (2010)"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.video = self.folder / "Inception (2010).mkv"
        self.video.write_bytes(b"a" * 4096)
        self.srt = self.folder / "Inception (2010).fr.srt"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scan(self, run_id: str, *, expected_langs):
        cfg = core.Config(root=self.root, enable_tmdb=False, incremental_scan_enabled=True)
        return plan_support.plan_library(
            cfg,
            tmdb=None,
            log=lambda _lvl, _msg: None,
            progress=lambda _i, _t, _c: None,
            scan_index=self.store.scan,
            run_id=run_id,
            subtitle_expected_languages=expected_langs,
        )

    def _cold_scan(self, run_id: str, *, expected_langs):
        """Meme etat disque, cache VIERGE : la reference d'ordre canonique."""
        cold_state = Path(self._tmp) / f"cold_{run_id}"
        cold_state.mkdir(parents=True, exist_ok=True)
        store = SQLiteStore(db_path_for_state_dir(cold_state))
        store.initialize()
        self.addCleanup(lambda: self._close_quietly(store))
        cfg = core.Config(root=self.root, enable_tmdb=False, incremental_scan_enabled=True)
        rows, stats = plan_support.plan_library(
            cfg,
            tmdb=None,
            log=lambda _lvl, _msg: None,
            progress=lambda _i, _t, _c: None,
            scan_index=store.scan,
            run_id=run_id,
            subtitle_expected_languages=expected_langs,
        )
        self.assertEqual(
            int(getattr(stats, "incremental_cache_row_hits", 0) or 0),
            0,
            "la reference doit etre un VRAI scan a froid",
        )
        return rows, stats

    @staticmethod
    def _close_quietly(store) -> None:
        try:
            store.close()
        except Exception:  # noqa: BLE001 - teardown best-effort
            pass

    def test_srt_ajoute_apres_scan1_retire_le_flag_sur_row_hit(self) -> None:
        rows1, _stats1 = self._scan("scan1", expected_langs=["fr"])
        self.assertEqual(len(rows1), 1)
        self.assertIn("subtitle_missing_fr", rows1[0].warning_flags)

        self.srt.write_text("", encoding="utf-8")

        rows2, stats2 = self._scan("scan2", expected_langs=["fr"])
        self.assertEqual(
            int(getattr(stats2, "incremental_cache_row_hits", 0) or 0),
            1,
            "le test doit passer par un HIT row sinon il ne prouve rien",
        )
        self.assertEqual(len(rows2), 1)
        self.assertNotIn("subtitle_missing_fr", rows2[0].warning_flags)
        self.assertEqual(rows2[0].subtitle_languages, ["fr"])
        self.assertEqual(rows2[0].subtitle_count, 1)
        self.assertEqual(rows2[0].subtitle_missing_langs, [])

    def test_flag_revient_si_le_srt_est_supprime(self) -> None:
        """Garde anti-implementation « on ne fait qu'enlever des flags »."""
        self._scan("scan1", expected_langs=["fr"])
        self.srt.write_text("", encoding="utf-8")
        rows2, _ = self._scan("scan2", expected_langs=["fr"])
        self.assertNotIn("subtitle_missing_fr", rows2[0].warning_flags)

        self.srt.unlink()
        rows3, stats3 = self._scan("scan3", expected_langs=["fr"])
        self.assertEqual(
            int(getattr(stats3, "incremental_cache_row_hits", 0) or 0),
            1,
            "le test doit passer par un HIT row sinon il ne prouve rien",
        )
        self.assertIn("subtitle_missing_fr", rows3[0].warning_flags)
        self.assertEqual(rows3[0].subtitle_count, 0)
        self.assertEqual(rows3[0].subtitle_languages, [])

    def test_ordre_des_flags_identique_au_scan_a_froid_flag_qui_apparait(self) -> None:
        """Revue adverse : plan.jsonl doit etre idempotent (cache vs scan a froid).

        Le scan a froid pose les flags sous-titres AVANT not_a_movie/integrity ;
        re-APPEND en fin de liste apres purge donnait a la meme row deux
        serialisations differentes (les chips d'alerte sont jointes sans tri).
        """
        self.srt.write_text("", encoding="utf-8")
        self._scan("scan1", expected_langs=["fr"])  # cache : aucun flag sous-titre

        self.srt.unlink()  # le flag subtitle_missing_fr doit APPARAITRE au refresh
        rows2, stats2 = self._scan("scan2", expected_langs=["fr"])
        self.assertEqual(
            int(getattr(stats2, "incremental_cache_row_hits", 0) or 0),
            1,
            "le test doit passer par un HIT row sinon il ne prouve rien",
        )
        self.assertIn("subtitle_missing_fr", rows2[0].warning_flags)

        rows_cold, _ = self._cold_scan("froid1", expected_langs=["fr"])
        self.assertEqual(
            rows2[0].warning_flags,
            rows_cold[0].warning_flags,
            "ordre des warning_flags divergent entre cache row et scan a froid",
        )

    def test_ordre_des_flags_identique_au_scan_a_froid_flag_deja_present(self) -> None:
        """Meme garde quand le flag EXISTAIT deja : il doit rester a sa place."""
        rows1, _ = self._scan("scan1", expected_langs=["fr"])
        self.assertIn("subtitle_missing_fr", rows1[0].warning_flags)

        # Sidecar non-video : change la folder_signature (donc MISS dossier) sans
        # toucher a la cle du cache row -> on passe bien par le refresh.
        (self.folder / "poster.jpg").write_bytes(b"\x00")

        rows2, stats2 = self._scan("scan2", expected_langs=["fr"])
        self.assertEqual(
            int(getattr(stats2, "incremental_cache_row_hits", 0) or 0),
            1,
            "le test doit passer par un HIT row sinon il ne prouve rien",
        )
        rows_cold, _ = self._cold_scan("froid2", expected_langs=["fr"])
        self.assertEqual(
            rows2[0].warning_flags,
            rows_cold[0].warning_flags,
            "ordre des warning_flags divergent entre cache row et scan a froid",
        )

    # --- NON-REGRESSION : doit rester VERT des deux cotes de la mutation -----

    def test_row_hit_sans_langues_attendues_ne_touche_pas_la_row(self) -> None:
        rows1, _ = self._scan("scan1", expected_langs=None)
        self.srt.write_text("", encoding="utf-8")
        rows2, stats2 = self._scan("scan2", expected_langs=None)

        self.assertEqual(
            int(getattr(stats2, "incremental_cache_row_hits", 0) or 0),
            1,
            "le test doit passer par un HIT row sinon il ne prouve rien",
        )
        self.assertEqual(rows2[0].subtitle_count, rows1[0].subtitle_count)
        self.assertEqual(rows2[0].subtitle_languages, rows1[0].subtitle_languages)
        self.assertEqual(rows2[0].warning_flags, rows1[0].warning_flags)

    def test_row_hit_preserve_lidentite_et_les_autres_flags(self) -> None:
        rows1, _ = self._scan("scan1", expected_langs=["fr"])
        self.srt.write_text("", encoding="utf-8")
        rows2, _ = self._scan("scan2", expected_langs=["fr"])

        self.assertEqual(rows2[0].row_id, rows1[0].row_id)
        self.assertEqual(rows2[0].kind, rows1[0].kind)
        self.assertEqual(rows2[0].proposed_title, rows1[0].proposed_title)
        self.assertEqual(rows2[0].proposed_year, rows1[0].proposed_year)
        self.assertEqual(rows2[0].confidence, rows1[0].confidence)
        others1 = {f for f in rows1[0].warning_flags if not str(f).startswith("subtitle_")}
        others2 = {f for f in rows2[0].warning_flags if not str(f).startswith("subtitle_")}
        self.assertEqual(
            others2,
            others1,
            "le refresh sous-titres ne doit toucher qu'aux flags subtitle_*",
        )


if __name__ == "__main__":
    unittest.main()
