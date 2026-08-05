"""Issue #612 — le .nfo exporte porte l'identifiant TMDb du film.

Sans `<uniqueid>`, Jellyfin et Kodi ne relient pas le fichier a TMDb : ils
re-scrapent tout (poster, synopsis, casting) et l'utilisateur croit avoir
exporte des metadonnees completes alors qu'il a un squelette.

Ce qui manquait vraiment : `export_nfo_for_run` savait deja ecrire
`<uniqueid>` a partir de `row["tmdb_id"]`, mais AUCUN producteur ne posait
cette clef. Les rows de l'export viennent de
`dashboard_support.build_run_report_payload`, dont le payload par row ne
contenait pas de `tmdb_id` : la lecture rendait toujours `None`. Les tests
existants (`tests/test_export_support.py`) fabriquent la row a la main avec un
`tmdb_id` deja pose — ils exercent le constructeur XML, jamais la chaine.

Ce fichier part donc du VRAI point d'entree, `_export_run_nfo_impl(run_id)`,
et lit le fichier .nfo ecrit sur disque.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from cinesort.ui.api import dashboard_support, film_support
from cinesort.ui.api.cinesort_api import CineSortApi

_TITLE = "Avatar"
_YEAR = 2009
_AUTO_TMDB_ID = 19995
_OTHER_TMDB_ID = 76600  # Avatar : la voie de l'eau — un AUTRE film


def _plan_line(folder: str, video: str, *, candidates: List[Dict[str, Any]]) -> str:
    return json.dumps(
        {
            "row_id": "row-1",
            "kind": "single",
            "folder": folder,
            "video": video,
            "proposed_title": _TITLE,
            "proposed_year": _YEAR,
            "proposed_source": "tmdb",
            "confidence": 95,
            "confidence_label": "high",
            "candidates": candidates,
            "warning_flags": [],
        },
        ensure_ascii=False,
    )


class ExportNfoUniqueIdRealPathTests(unittest.TestCase):
    """Chaine complete : run en base + plan.jsonl -> _export_run_nfo_impl -> .nfo."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_nfo612_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.movie_dir = Path(self._tmp) / "root" / f"{_TITLE} ({_YEAR})"
        self.movie_dir.mkdir(parents=True, exist_ok=True)
        self.video = f"{_TITLE}.{_YEAR}.1080p.mkv"
        (self.movie_dir / self.video).write_bytes(b"x" * 16)

        self.api = CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]
        self.store, _runner = self.api._get_or_create_infra(self.state_dir)
        self.run_id = "run_nfo612"

        now = time.time()
        self.store.run.insert_run_pending(
            run_id=self.run_id,
            root=str(self.movie_dir.parent),
            state_dir=str(self.state_dir),
            config={"root": str(self.movie_dir.parent), "state_dir": str(self.state_dir)},
            created_ts=now,
        )
        self.store.run.mark_run_running(self.run_id, started_ts=now)
        self.store.run.mark_run_done(self.run_id, stats={"planned_rows": 1}, ended_ts=now + 1)

        self.run_paths = self.api._run_paths_for(self.state_dir, self.run_id, ensure_exists=True)
        self.nfo_path = (self.movie_dir / self.video).with_suffix(".nfo")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_plan(self, candidates: List[Dict[str, Any]]) -> None:
        self.run_paths.plan_jsonl.write_text(
            _plan_line(str(self.movie_dir), self.video, candidates=candidates) + "\n",
            encoding="utf-8",
        )

    def _export(self) -> Dict[str, Any]:
        return self.api._export_run_nfo_impl(self.run_id, overwrite=True, dry_run=False)

    # -- le defaut de #612 ------------------------------------------------

    def test_le_nfo_exporte_porte_l_uniqueid_du_candidat_retenu(self) -> None:
        self._write_plan([{"title": _TITLE, "year": _YEAR, "source": "tmdb", "tmdb_id": _AUTO_TMDB_ID, "score": 0.95}])
        result = self._export()
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(int(result.get("written") or 0), 1, result)
        content = self.nfo_path.read_text(encoding="utf-8")
        self.assertIn(
            f'<uniqueid type="tmdb" default="true">{_AUTO_TMDB_ID}</uniqueid>',
            content,
            f".nfo sans identifiant TMDb -> Jellyfin/Kodi re-scrapent tout :\n{content}",
        )

    def test_un_candidat_d_un_autre_film_ne_devient_pas_l_uniqueid(self) -> None:
        """`PlanRow.candidates` n'est pas triee : `candidates[0]` mentirait (#714)."""
        self._write_plan(
            [
                # En TETE de liste, mais ce n'est PAS le film propose.
                {"title": "Avatar : la voie de l'eau", "year": 2022, "source": "tmdb", "tmdb_id": _OTHER_TMDB_ID},
                {"title": _TITLE, "year": _YEAR, "source": "tmdb", "tmdb_id": _AUTO_TMDB_ID, "score": 0.9},
            ]
        )
        self.assertTrue(self._export().get("ok"))
        content = self.nfo_path.read_text(encoding="utf-8")
        self.assertIn(f'<uniqueid type="tmdb" default="true">{_AUTO_TMDB_ID}</uniqueid>', content)
        self.assertNotIn(str(_OTHER_TMDB_ID), content)

    def test_le_choix_tmdb_manuel_de_l_utilisateur_prime_sur_le_match_auto(self) -> None:
        self._write_plan([{"title": _TITLE, "year": _YEAR, "source": "tmdb", "tmdb_id": _AUTO_TMDB_ID, "score": 0.95}])
        self.store.film_modal.upsert_tmdb_override(
            run_id=self.run_id,
            row_id="row-1",
            tmdb_id=_OTHER_TMDB_ID,
            new_confidence=100,
            proposed_title=_TITLE,
            proposed_year=_YEAR,
        )
        self.assertTrue(self._export().get("ok"))
        content = self.nfo_path.read_text(encoding="utf-8")
        self.assertIn(f'<uniqueid type="tmdb" default="true">{_OTHER_TMDB_ID}</uniqueid>', content)
        self.assertNotIn(str(_AUTO_TMDB_ID), content)

    def test_overrides_illisibles_donne_un_nfo_sans_identifiant_plutot_qu_un_faux(self) -> None:
        """Le doute va dans le sens restrictif.

        Si la table des choix manuels est illisible, on ne sait pas si le match
        automatique est encore celui que l'utilisateur veut. Un .nfo sans
        identifiant se re-scrape ; un .nfo qui affirme le mauvais identifiant
        est cru sur parole par Jellyfin.
        """
        self._write_plan([{"title": _TITLE, "year": _YEAR, "source": "tmdb", "tmdb_id": _AUTO_TMDB_ID, "score": 0.95}])
        with mock.patch.object(film_support, "list_tmdb_overrides_bulk", return_value=None):
            self.assertTrue(self._export().get("ok"))
        content = self.nfo_path.read_text(encoding="utf-8")
        self.assertNotIn("uniqueid", content)

    def test_sans_candidat_tmdb_le_nfo_reste_sans_identifiant(self) -> None:
        self._write_plan([{"title": _TITLE, "year": _YEAR, "source": "name"}])
        self.assertTrue(self._export().get("ok"))
        content = self.nfo_path.read_text(encoding="utf-8")
        self.assertNotIn("uniqueid", content)
        self.assertIn(f"<title>{_TITLE}</title>", content)

    # -- non-regression des autres consommateurs du meme payload -----------

    def test_le_csv_du_rapport_garde_exactement_ses_colonnes(self) -> None:
        """Le payload de row sert aussi aux exports JSON/CSV/HTML."""
        self._write_plan([{"title": _TITLE, "year": _YEAR, "source": "tmdb", "tmdb_id": _AUTO_TMDB_ID, "score": 0.95}])
        built, _paths = dashboard_support.build_run_report_payload(self.api, self.run_id)
        self.assertTrue(built.get("ok"), built)
        header = dashboard_support.report_to_csv_text(built["report"]).splitlines()[0]
        self.assertNotIn("tmdb_id", header, "la colonne CSV ne doit pas bouger sous les yeux de l'utilisateur")


if __name__ == "__main__":
    unittest.main()
