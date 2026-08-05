"""#469 — la conformance de dossier doit etre calculee avec le MEME contexte
de nommage que les ecrivains.

Contexte mesure sur le code (et non sur l'enonce de l'issue) :

`build_naming_context` accepte `probe_data` / `quality_data` / `tmdb_id`, mais
sur le chemin de RENOMMAGE personne ne les alimente. Les cinq rendus reels du
template film sont :

  - `apply_core.apply_single`            (title, year, edition, separator)
  - `apply_core.apply_collection_item`   (title, year, edition, separator)
  - `duplicate_support.planned_target_folder` (miroir du precedent)
  - `duplicate_support.template_uses_edition` (sonde, title/year neutres)
  - `library_support._planned_folder_label`   (libelle, contexte litteral)

Seul l'apercu des reglages (`cinesort_api`) passe un probe. `{resolution}`,
`{video_codec}`, `{tmdb_tag}`, `{quality}`, `{score}` sont donc TOUJOURS vides
a l'ecriture : un dossier « Titre (Annee) [1080p] » n'est PAS deja conforme,
l'apply lui retirerait le segment. Elargir `folder_matches_template` pour
l'accepter (regex `.*` sur les placeholders variables, correctif propose par
l'issue) rendrait la conformance plus permissive que l'ecrivain et casserait
l'invariant « planned == apply par construction ».

Le defaut REEL et adjacent : `edition` et `separator` SONT alimentes par les
ecrivains et n'etaient pas transmis a la conformance. Un dossier que l'apply
venait lui-meme d'ecrire sous un template a edition/separateur etait juge non
conforme a son propre template.

Les deux tests de CHAINE (`_build_resolved_row`, `apply_single`) existent parce
qu'un test du seul helper reste vert si l'on remet l'ancien appel au site
d'appel.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.domain.core as core
from cinesort.app.apply_core import apply_single
from cinesort.app.plan_support_replan import _build_resolved_row
from cinesort.domain.naming import build_naming_context, folder_matches_template, format_movie_folder

_EDITION_TEMPLATE = "{title} ({year}) {edition-tag}"
_SEP_TEMPLATE = "{title}{sep}({year})"


class FolderMatchesTemplateEditionSeparatorTests(unittest.TestCase):
    """Niveau helper : le rendu de reference doit inclure edition + separateur."""

    def test_edition_folder_written_by_apply_is_recognised_as_conform(self) -> None:
        # Nom EXACTEMENT tel que apply_single l'ecrit (meme chaine de rendu).
        written = format_movie_folder(
            _EDITION_TEMPLATE,
            build_naming_context(title="Inception", year=2010, edition="Director's Cut", separator=" "),
        )
        self.assertEqual(written, "Inception (2010) {edition-Director's Cut}")
        self.assertTrue(
            folder_matches_template(written, _EDITION_TEMPLATE, "Inception", 2010, edition="Director's Cut"),
            "le dossier ecrit par l'apply doit etre conforme a son propre template",
        )

    def test_edition_omitted_keeps_the_folder_non_conform(self) -> None:
        # Sans l'edition, le rendu de reference est ampute -> non conforme.
        # C'est le comportement d'avant #469, conserve ici comme borne : le fix
        # ne rend PAS tout conforme, il transmet une entree manquante.
        self.assertFalse(
            folder_matches_template(
                "Inception (2010) {edition-Director's Cut}",
                _EDITION_TEMPLATE,
                "Inception",
                2010,
            )
        )

    def test_separator_folder_written_by_apply_is_recognised_as_conform(self) -> None:
        written = format_movie_folder(
            _SEP_TEMPLATE,
            build_naming_context(title="Inception", year=2010, separator="."),
        )
        self.assertEqual(written, "Inception.(2010)")
        self.assertTrue(folder_matches_template(written, _SEP_TEMPLATE, "Inception", 2010, separator="."))
        # Separateur different -> le dossier n'est pas celui que l'apply ecrirait.
        self.assertFalse(folder_matches_template(written, _SEP_TEMPLATE, "Inception", 2010, separator="_"))

    def test_variable_placeholders_stay_non_conform(self) -> None:
        """Garde anti-elargissement : le correctif propose par #469 est refuse.

        `{resolution}` n'est jamais alimente a l'ecriture ; « Inception (2010)
        [1080p] » n'est donc pas conforme. Si un jour on wildcarde les
        placeholders variables, ce test tombe et force a re-arbitrer.
        """
        tpl = "{title} ({year}) [{resolution}]"
        self.assertEqual(
            format_movie_folder(tpl, build_naming_context(title="Inception", year=2010)),
            "Inception (2010)",
        )
        self.assertFalse(folder_matches_template("Inception (2010) [1080p]", tpl, "Inception", 2010))
        self.assertTrue(folder_matches_template("Inception (2010)", tpl, "Inception", 2010))


_NFO_STATE = {
    "nfo_ok": True,
    "nfo_cov": 1.0,
    "nfo_seq": 1.0,
    "nfo_reject_reason": "",
    "year_delta_reject": False,
    "nfo_partial_match": False,
}


def _noop_log(_level: str, _msg: str) -> None:
    return None


class _StubTmdb:
    def get_movie_runtime(self, _tmdb_id):
        return None

    def get_movie_collection(self, _tmdb_id):
        return None, None


class ReplanCallSiteEditionTests(unittest.TestCase):
    """Site d'appel 1/2 : `plan_support_replan._build_resolved_row`.

    `is_already_conform` rehausse la confiance a 90/'high'. Un candidat faible
    (59/'low') rend le rehaussement observable.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="conform_edition_replan_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _row(self, *, folder_name: str, detected_edition, template: str):
        cfg = core.Config(root=self.root, naming_movie_template=template).normalized()
        # base = 59 / 'low' (cap similarite < 0.60 de compute_confidence)
        cand = core.Candidate(title="Film Y", year=2010, source="tmdb", tmdb_id=7, score=0.10, note="dY=0, sim=0.50")
        # runtime=0 -> le cross-check runtime (Phase 6.1) ne se declenche pas :
        # la confiance observee ne depend que de `is_already_conform`.
        nfo = core.NfoInfo(title="Film Y", originaltitle=None, year=2010, tmdbid="7", imdbid=None, runtime=0)
        folder = self.root / folder_name
        return _build_resolved_row(
            cfg,
            folder,
            Path("movie.mkv"),
            cand,
            row_id="r1",
            kind="single",
            is_collection=False,
            folder_name=folder_name,
            cands=[cand],
            nfo=nfo,
            nfo_path=folder / "movie.nfo",
            nfo_state=dict(_NFO_STATE),
            name_year=2010,
            name_year_reason="folder",
            remaster_hint=False,
            tmdb_used=True,
            title_ambiguous=False,
            detected_edition=detected_edition,
            tmdb=_StubTmdb(),
            log=_noop_log,
        )

    def test_edition_folder_gets_the_conformity_confidence_boost(self) -> None:
        row = self._row(
            folder_name="Film Y (2010) {edition-Director's Cut}",
            detected_edition="Director's Cut",
            template=_EDITION_TEMPLATE,
        )
        self.assertEqual(row.confidence, 90, "dossier deja conforme -> rehaussement 90/'high'")
        self.assertEqual(row.confidence_label, "high")

    def test_non_conform_folder_keeps_its_low_confidence(self) -> None:
        """Borne : le rehaussement reste conditionnel, il ne devient pas systematique."""
        row = self._row(
            folder_name="film.y.2010.bluray.x264",
            detected_edition="Director's Cut",
            template=_EDITION_TEMPLATE,
        )
        self.assertEqual(row.confidence, 59)
        self.assertEqual(row.confidence_label, "low")


class _DummyConfig:
    """Config minimale acceptee par apply_single (cf. test_apply_skip_identical_rename)."""

    def __init__(self, root: Path, template: str, separator: str = " "):
        self.root = root
        self.naming_movie_template = template
        self.separator = separator
        self.enable_collection_folder = False
        self.collection_root_name = "_Collection"


class ApplySingleCallSiteEditionTests(unittest.TestCase):
    """Site d'appel 2/2 : garde NOOP de `apply_core.apply_single`.

    Le dossier porte un espace double : `_norm_compare` (conformance) l'ignore,
    `_fs_equivalent` (garde suivante, casefold+NFC seulement) non. Le compteur
    `renames` distingue donc la garde de conformance de son filet de securite —
    sans cela les deux gardes emettent le meme motif de skip et le test resterait
    vert avec l'ancien appel.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="conform_edition_apply_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)
        self.review = self.root / "_review"

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _apply(self, folder_name: str, *, edition, template: str):
        cfg = _DummyConfig(self.root, template)
        folder = self.root / folder_name
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)
        res = core.ApplyResult()
        logs: list = []
        apply_single(
            cfg,
            folder,
            title="Inception",
            year=2010,
            dry_run=True,
            log=lambda level, msg: logs.append((level, msg)),
            res=res,
            conflicts_root=self.review / "_conflicts",
            conflicts_sidecars_root=self.review / "_conflicts_sidecars",
            duplicates_identical_root=self.review / "_duplicates_identical",
            leftovers_root=self.review / "_leftovers",
            edition=edition,
        )
        return res, logs

    def test_edition_folder_with_redundant_space_is_not_renamed(self) -> None:
        res, logs = self._apply(
            "Inception  (2010) {edition-Director's Cut}",
            edition="Director's Cut",
            template=_EDITION_TEMPLATE,
        )
        self.assertEqual(res.renames, 0, f"renommage sans effet metier compte comme rename: {logs}")
        self.assertEqual(res.skip_reasons.get(core.SKIP_REASON_NOOP_DEJA_CONFORME), 1)

    def test_genuinely_different_folder_is_still_renamed(self) -> None:
        """Borne : la garde ne doit pas avaler un vrai renommage."""
        res, _logs = self._apply(
            "inception.2010.directors.cut.1080p",
            edition="Director's Cut",
            template=_EDITION_TEMPLATE,
        )
        self.assertEqual(res.renames, 1)


if __name__ == "__main__":
    unittest.main()
