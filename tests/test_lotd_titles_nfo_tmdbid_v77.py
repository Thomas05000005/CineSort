# -*- coding: utf-8 -*-
"""GATES dedies Lot D (verif totale 2026-07) — fixes titres + NFO tmdbid.

Couvre les 3 findings corriges :

[LOTD-DUP-TITLE-YEAR] Path.stem mangeait ".2005" comme une extension sur un
    nom SANS vraie extension -> "Titre.2005" et "Titre.2005.720p" produisaient
    2 identites titre+annee differentes pour le MEME film (vrai doublon rate,
    dossier redondant "Titre 2005 (2005)"). Fix en 2 volets :
    - scene_parser : suffixe strippe seulement si vraie extension ;
    - build_candidates_from_name : annee de QUEUE == annee detectee strippee
      du titre (identite coherente, dossier "Titre (2005)").

[BUG-TITLE-CHANNEL-RESIDUE] meme cause : ".1-GRP" (canal 7.1 colle au release
    group) mange comme extension -> residu "7" orphelin ("Interstellar 2014 7").
    + variante codec "H.265-EVO" (le `\\.?` de _NOISE_RE etait mort car les
    points sont deja remplaces par des espaces).

[GAP-NFO-TMDBID] build_candidates_from_nfo ne copiait pas NfoInfo.tmdbid sur
    le Candidate -> identite TMDb gratuite perdue quand le NFO matche. Le
    cross-check anti-NFO-pollue (plan_support_dedup) retire l'id si TMDb le
    refute, et ajoute toujours le candidat verifie nfo_tmdb.

Zone sensible (memoire R4-P2/P3) : differentiel corpus AVANT/APRES joue le
2026-07-08 sur 162 noms (tests figes + seed torrents synthetique) : 0
divergence non voulue hors les familles ciblees.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from cinesort.app.plan_support_dedup import _augment_candidates_from_nfo_tmdb_id
from cinesort.domain.core import (
    NfoInfo,
    build_candidates_from_name,
    build_candidates_from_nfo,
)
from cinesort.domain.duplicate_support import movie_key
from cinesort.domain.scene_parser import parse_scene_title
from cinesort.domain.title_helpers import strip_trailing_year_if_equal

_NORM = str.lower


class SceneParserExtensionGuardTests(unittest.TestCase):
    """Le suffixe n'est strippe que s'il ressemble a une vraie extension."""

    def test_year_suffix_kept_on_bare_name(self) -> None:
        # [LOTD-DUP-TITLE-YEAR] ".2005" n'est PAS une extension : l'annee reste
        # dans le titre, coherent avec la variante taggee "….2005.720p".
        self.assertEqual(parse_scene_title("Le.Grand.Voyage.2005"), "Le Grand Voyage 2005")
        self.assertEqual(parse_scene_title("Le.Grand.Voyage.2005.720p"), "Le Grand Voyage 2005")
        self.assertEqual(parse_scene_title("Le.Grand.Voyage.2005.mkv"), "Le Grand Voyage 2005")

    def test_channel_glued_to_group_cleaned(self) -> None:
        # [BUG-TITLE-CHANNEL-RESIDUE] ".1-GRP" n'est plus mange comme extension
        # -> "7 1-GRP" complet, nettoye par audio-residue + release-group.
        self.assertEqual(
            parse_scene_title("Interstellar.2014.2160p.UHD.BluRay.REMUX.HDR10.x265.TrueHD.Atmos.7.1-LOTD"),
            "Interstellar 2014",
        )
        self.assertEqual(
            parse_scene_title("The.Matrix.1999.1080p.BluRay.x264.DTS.5.1-LOTD"),
            "The Matrix 1999",
        )
        self.assertEqual(
            parse_scene_title("Old.Boy.2003.720p.HDTV.XviD.AC3.2.0-LOTD"),
            "Old Boy 2003",
        )

    def test_codec_h26x_space_separated_cleaned(self) -> None:
        # Variante codec de la meme famille : "H.265-EVO" -> "H 265-EVO" apres
        # le replace point->espace ; `h[\s.]?26[45]` le couvre desormais.
        self.assertEqual(
            parse_scene_title("The.Batman.2022.2160p.WEB-DL.DDP5.1.Atmos.DV.HDR.H.265-EVO"),
            "The Batman 2022",
        )
        self.assertEqual(
            parse_scene_title("Avatar.The.Way.of.Water.2022.1080p.MA.WEB-DL.DDP5.1.Atmos.H.264-FLUX"),
            "Avatar The Way of Water 2022",
        )

    def test_real_extensions_still_stripped(self) -> None:
        self.assertEqual(parse_scene_title("Inception.2010.1080p.BluRay.x264-RARBG.mkv"), "Inception 2010")
        self.assertEqual(parse_scene_title("Inception.mkv"), "Inception")
        self.assertEqual(parse_scene_title(".mkv"), "")
        self.assertEqual(parse_scene_title("2010.mkv"), "2010")

    def test_title_mutilation_corpus_unchanged(self) -> None:
        # Sentinelles du corpus R4-P2/P3 (seed torrents) : zero regression.
        self.assertEqual(parse_scene_title("Thor - Ragnarok (2017)"), "Thor - Ragnarok")
        self.assertEqual(parse_scene_title("21 Jump Street (2012)"), "21 Jump Street")
        self.assertEqual(parse_scene_title("Ma Vie de Courgette"), "Ma Vie de Courgette")
        self.assertEqual(
            parse_scene_title("1917.2019.1080p.BluRay.x264.mkv"),
            "1917 2019",
        )


class IdentityTrailingYearTests(unittest.TestCase):
    """[LOTD-DUP-TITLE-YEAR] revue round 1 : titre proposé INTACT, tolérance
    portée UNIQUEMENT par la clé de dédoublonnage (movie_key)."""

    def test_helper_strips_only_when_equal(self) -> None:
        self.assertEqual(strip_trailing_year_if_equal("Le Grand Voyage 2005", 2005), "Le Grand Voyage")
        # Année de queue != année du couple : film-année, préservé.
        self.assertEqual(strip_trailing_year_if_equal("Blade Runner 2049", 2017), "Blade Runner 2049")
        self.assertEqual(strip_trailing_year_if_equal("Le Grand Voyage 2005", None), "Le Grand Voyage 2005")
        self.assertEqual(strip_trailing_year_if_equal("2005", 2005), "2005")  # pas de tête
        self.assertEqual(strip_trailing_year_if_equal("", 2005), "")

    def test_proposed_title_stays_intact_no_release_year(self) -> None:
        # RÉGRESSION à ne jamais réintroduire : "Blade Runner 2049" est le titre
        # (2049 en fait partie), sorti en 2017. Sans année de sortie dans le nom,
        # l'ancien strip le mutilait en "Blade Runner". Le renommage disque suit
        # le titre -> il DOIT rester intact (seed torrents).
        for folder in ("Blade.Runner.2049.2160p.BluRay.x265-GRP", "Wonder.Woman.1984.1080p.WEBRip"):
            cands = [c for c in build_candidates_from_name(folder, folder + ".mkv") if c.source == "name"]
            self.assertEqual(len(cands), 1, folder)
            self.assertIn(str(cands[0].year), cands[0].title, (folder, cands[0].title))  # année conservée

    def test_dedup_key_collapses_year_in_title_variants(self) -> None:
        # Cœur du finding : "Titre 2005" (nom "Titre.2005[.720p]") et "Titre"
        # (dossier "Titre (2005)") sont le MÊME film -> même clé movie_key.
        keys = {
            movie_key("Le Grand Voyage 2005", 2005, norm_for_tokens=_NORM),
            movie_key("Le Grand Voyage", 2005, norm_for_tokens=_NORM),
        }
        self.assertEqual(len(keys), 1, keys)
        # Film-année : clé distincte quand l'année du titre != année de sortie.
        self.assertNotEqual(
            movie_key("Blade Runner 2049", 2017, norm_for_tokens=_NORM),
            movie_key("Blade Runner", 2017, norm_for_tokens=_NORM),
        )

    def test_same_identity_with_and_without_quality_tag(self) -> None:
        # 2 copies du MÊME film, une seule avec tag qualité après l'année :
        # titre proposé identique (fix a du parser) ET clé dédup identique.
        variants = [
            ("Le.Grand.Voyage.2005", "Le.Grand.Voyage.2005.mkv"),
            ("Le.Grand.Voyage.2005.720p", "Le.Grand.Voyage.2005.720p.mkv"),
            ("Le.Grand.Voyage.2005.1080p", "Le.Grand.Voyage.2005.1080p.mkv"),
        ]
        keys = set()
        for folder, video in variants:
            cands = [c for c in build_candidates_from_name(folder, video) if c.source == "name"]
            self.assertEqual(len(cands), 1, (folder, cands))
            keys.add(movie_key(cands[0].title, cands[0].year or 0, norm_for_tokens=_NORM))
        self.assertEqual(len(keys), 1, keys)


class NfoTmdbIdPropagationTests(unittest.TestCase):
    """[GAP-NFO-TMDBID] le <tmdbid> du NFO est copie sur le Candidate (0 reseau)."""

    def _nfo(self, tmdbid) -> NfoInfo:
        return NfoInfo(
            title="Inception",
            originaltitle="Inception",
            year=2010,
            tmdbid=tmdbid,
            imdbid=None,
        )

    def test_tmdbid_copied_as_int(self) -> None:
        cands = build_candidates_from_nfo(self._nfo("27205"))
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].tmdb_id, 27205)
        self.assertEqual(cands[0].source, "nfo")
        self.assertEqual((cands[0].title, cands[0].year), ("Inception", 2010))

    def test_tmdbid_absent_or_garbage_gives_none(self) -> None:
        for raw in (None, "", "   ", "tt0137523", "abc", "0", "-5"):
            cands = build_candidates_from_nfo(self._nfo(raw))
            self.assertEqual(len(cands), 1, raw)
            self.assertIsNone(cands[0].tmdb_id, raw)


class _StubTmdb:
    """Client TMDb stub : find_by_tmdb_id renvoie un resultat fige, 0 reseau."""

    def __init__(self, result) -> None:
        self._result = result
        self.calls = 0

    def find_by_tmdb_id(self, tmdbid):
        self.calls += 1
        return self._result


class NfoTmdbIdCrossCheckTests(unittest.TestCase):
    """Le cross-check app conserve son role anti-NFO-pollue apres propagation."""

    def _run_augment(self, tmdb_result):
        nfo = NfoInfo(title="Inception", originaltitle="Inception", year=2010, tmdbid="27205", imdbid=None)
        nfo_cands = build_candidates_from_nfo(nfo)
        self.assertEqual(nfo_cands[0].tmdb_id, 27205)  # premisse : id propage
        logs: list = []
        _augment_candidates_from_nfo_tmdb_id(
            SimpleNamespace(enable_tmdb=True),
            nfo,
            nfo_cands,
            "Inception.2010.1080p.BluRay.x264-RARBG",
            "Inception.2010.1080p.BluRay.x264-RARBG.mkv",
            name_year=2010,
            nfo_ok=True,
            tmdb=_StubTmdb(tmdb_result),
            log=lambda lvl, msg: logs.append((lvl, msg)),
            log_ctx="[test]",
        )
        return nfo_cands, logs

    def test_verified_candidate_still_added_despite_propagated_id(self) -> None:
        # Le candidat 'nfo' de base porte deja l'id 27205 : le candidat VERIFIE
        # nfo_tmdb (score 0.93 + poster) doit quand meme etre ajoute.
        result = SimpleNamespace(
            id=27205, title="Inception", original_title="Inception", year=2010, poster_path="/x.jpg"
        )
        cands, _logs = self._run_augment(result)
        self.assertEqual({c.source for c in cands}, {"nfo", "nfo_tmdb"}, cands)
        verified = next(c for c in cands if c.source == "nfo_tmdb")
        self.assertEqual(verified.tmdb_id, 27205)

    def test_rejected_id_removed_from_base_candidate(self) -> None:
        # NFO pollue : le cross-check refute l'id -> il est RETIRE du candidat
        # 'nfo' de base (pas d'identite TMDb fausse propagee au plan).
        result = SimpleNamespace(
            id=27205, title="Totally Different Zzz Film", original_title="", year=1971, poster_path=None
        )
        cands, logs = self._run_augment(result)
        self.assertEqual([c.source for c in cands], ["nfo"], cands)
        self.assertIsNone(cands[0].tmdb_id, cands)
        self.assertTrue(any("rejete" in msg for _lvl, msg in logs), logs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
