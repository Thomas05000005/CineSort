"""F30 — le compteur `mkdirs` du dry-run doit egaler celui de l'apply reel.

Contexte du finding (revue post-merge 2026-07-18) : `mkdir_counted` ne se
dedoublonne que par `path.exists()`. En apply reel, le dossier existe des le 2e
appel, donc il n'est compte qu'une fois. En dry-run rien n'est cree : le meme
dossier etait recompte a chaque fichier deplace (video + chaque sous-titre) et
re-logue « MKDIR: <meme chemin> ».

Consequences visibles pour l'utilisateur : le bandeau « === APPLY done ...
mkdirs=N » de la preview annonce un nombre faux, et le log de preview contient
des lignes MKDIR dupliquees. La duplication est aussi INTER-ROWS : deux films
d'une meme saga recomptaient chacun le dossier de saga partage.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.domain.core as core
from cinesort.app import apply_core
from cinesort.app.apply_core import apply_rows


class _LogCollector:
    def __init__(self) -> None:
        self.entries: list = []

    def __call__(self, level: str, msg: str) -> None:
        self.entries.append((level, msg))

    def mkdir_lines(self) -> list:
        return [msg for _level, msg in self.entries if msg.startswith("MKDIR:")]


def _collection_row(row_id: str, folder: str, video: str, title: str) -> core.PlanRow:
    return core.PlanRow(
        row_id=row_id,
        kind="collection",
        folder=folder,
        video=video,
        proposed_title=title,
        proposed_year=1979,
        proposed_source="name",
        confidence=90,
        confidence_label="high",
        candidates=[],
    )


class ApplyMkdirsDryRunParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_f30_")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _build_root(self, name: str) -> tuple:
        """Un film de collection + 2 sous-titres : 1 seul sous-dossier a creer."""
        root = Path(self._tmp) / name
        folder = root / "Saga.Film.1979"
        folder.mkdir(parents=True)
        (folder / "saga.mkv").write_bytes(b"\x00" * 64)
        (folder / "saga.fr.srt").write_text("fr", encoding="utf-8")
        (folder / "saga.en.srt").write_text("en", encoding="utf-8")

        cfg = core.Config(root=root, enable_collection_folder=True).normalized()
        rows = [_collection_row("c1", str(folder), "saga.mkv", "Saga Film")]
        decisions = {"c1": {"ok": True, "title": "Saga Film", "year": 1979}}
        return cfg, rows, decisions

    def test_mkdirs_parite_dry_run_vs_reel(self) -> None:
        cfg_dry, rows_dry, dec_dry = self._build_root("dry")
        log_dry = _LogCollector()
        res_dry = apply_rows(
            cfg_dry,
            rows_dry,
            dec_dry,
            dry_run=True,
            quarantine_unapproved=False,
            log=log_dry,
            decision_presence={"c1"},
        )

        cfg_real, rows_real, dec_real = self._build_root("reel")
        log_real = _LogCollector()
        res_real = apply_rows(
            cfg_real,
            rows_real,
            dec_real,
            dry_run=False,
            quarantine_unapproved=False,
            log=log_real,
            decision_presence={"c1"},
        )

        self.assertEqual(
            res_dry.mkdirs,
            res_real.mkdirs,
            f"la preview annonce {res_dry.mkdirs} creation(s) de dossier pour {res_real.mkdirs} reelle(s)",
        )
        self.assertEqual(
            len(log_dry.mkdir_lines()),
            len(log_real.mkdir_lines()),
            f"lignes MKDIR dupliquees en preview : {log_dry.mkdir_lines()}",
        )
        # Garde-fou : seule la comptabilite mkdir devait bouger.
        self.assertEqual(res_dry.moves, res_real.moves, "le nombre de deplacements doit rester identique")

    def _build_saga_partagee(self, name: str) -> tuple:
        """Deux films DISTINCTS appartenant a la MEME saga.

        C'est le vrai cas inter-rows : les deux rows visent le meme dossier de
        saga `_Collection/Alien Collection`, qui ne doit etre compte qu'une fois.
        """
        root = Path(self._tmp) / name
        rows = []
        for index, (titre, annee) in enumerate((("Alien", 1979), ("Aliens", 1986)), start=1):
            folder = root / f"Film{index}"
            folder.mkdir(parents=True)
            (folder / f"film{index}.mkv").write_bytes(b"\x00" * 64)
            row = core.PlanRow(
                row_id=f"s{index}",
                kind="single",
                folder=str(folder),
                video=f"film{index}.mkv",
                proposed_title=titre,
                proposed_year=annee,
                proposed_source="name",
                confidence=90,
                confidence_label="high",
                candidates=[],
            )
            row.tmdb_collection_name = "Alien Collection"
            rows.append(row)
        cfg = core.Config(root=root, enable_collection_folder=True).normalized()
        decisions = {r.row_id: {"ok": True, "title": r.proposed_title, "year": r.proposed_year} for r in rows}
        return cfg, rows, decisions

    def test_saga_partagee_par_deux_films_comptee_une_fois(self) -> None:
        cfg_dry, rows_dry, dec_dry = self._build_saga_partagee("saga_dry")
        log_dry = _LogCollector()
        res_dry = apply_rows(
            cfg_dry,
            rows_dry,
            dec_dry,
            dry_run=True,
            quarantine_unapproved=False,
            log=log_dry,
            decision_presence=set(dec_dry),
        )

        cfg_real, rows_real, dec_real = self._build_saga_partagee("saga_reel")
        log_real = _LogCollector()
        res_real = apply_rows(
            cfg_real,
            rows_real,
            dec_real,
            dry_run=False,
            quarantine_unapproved=False,
            log=log_real,
            decision_presence=set(dec_real),
        )

        self.assertEqual(
            res_dry.mkdirs,
            res_real.mkdirs,
            f"parite inter-rows rompue : preview={res_dry.mkdirs} vs reel={res_real.mkdirs}",
        )
        self.assertEqual(
            len(log_dry.mkdir_lines()),
            len(log_real.mkdir_lines()),
            f"lignes MKDIR dupliquees en preview : {log_dry.mkdir_lines()}",
        )
        self.assertEqual(
            len(log_dry.mkdir_lines()),
            len(set(log_dry.mkdir_lines())),
            "un meme dossier de saga ne doit pas etre logue deux fois",
        )

    def test_etat_de_dedup_ne_fuit_pas_apres_l_apply(self) -> None:
        """Un appel direct a mkdir_counted apres un apply ne doit pas etre bride.

        Defaut trouve en revue adversaire : l'etat de deduplication survivait a
        l'apply dans le contexte du thread. Un futur appelant en dry-run aurait
        silencieusement herite d'un compteur faux.
        """
        cfg, rows, decisions = self._build_saga_partagee("fuite")
        log = _LogCollector()
        res = apply_rows(
            cfg, rows, decisions, dry_run=True, quarantine_unapproved=False, log=log, decision_presence=set(decisions)
        )
        self.assertGreaterEqual(res.mkdirs, 1)

        deja_compte = next(m.split("MKDIR: ", 1)[1] for m in log.mkdir_lines())
        res2 = core.ApplyResult()
        apply_core.mkdir_counted(
            Path(deja_compte),
            dry_run=True,
            log=_LogCollector(),
            res=res2,
            record_op_fn=None,
        )
        self.assertEqual(
            res2.mkdirs,
            1,
            "un nouvel ApplyResult doit repartir de zero : l'etat de l'apply precedent ne doit pas s'appliquer",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
