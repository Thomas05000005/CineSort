"""Zones domaine — une notion encodee DEUX fois, et les deux ont diverge.

Lot « domaine » de l'ultra-audit 2026-08-31. Chaque classe couvre UN constat
confirme par deux jurys independants ; chaque test a ete VU ROUGE avant le
correctif, et le commentaire de classe porte la mesure du rouge.

Constats couverts :
  #5  CRITIQUE duplicate_compare — classe de resolution encodee deux fois
  #6  MAJEUR   audio_perceptual  — « meilleure piste » aveugle au `profile`
  #8  MAJEUR   release_name_parser — DTS:X booleen d'un cote, codec de l'autre
  #20 MAJEUR   duplicate_compare — abstention « canaux audio » inatteignable
  #9  MINEUR   naming/scene_parser/title_helpers — 3 regex de tags providers
  #15 MINEUR   naming — garde preventif MAX_PATH aveugle au nom interne
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.domain import naming, scene_parser, title_helpers
from cinesort.domain.duplicate_compare import compare_by_criteria
from cinesort.domain.naming import check_path_length, check_path_length_killswitch
from cinesort.domain.perceptual.audio_perceptual import select_best_audio_track
from cinesort.domain.release_name_parser import parse_release_name
from cinesort.domain.resolution_class import classify_resolution


def _probe(width: int, height: int, *, audio: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Pseudo-probe minimal, forme de `_build_pseudo_probe` (duplicate_support)."""
    return {
        "video": {"width": width, "height": height, "codec": "hevc", "bitrate": 8_000_000},
        "audio_tracks": [{"codec": "ac3", "channels": 6}] if audio is None else audio,
    }


def _criterion(probe_a: Dict[str, Any], probe_b: Dict[str, Any], name: str) -> Any:
    for crit in compare_by_criteria(probe_a, probe_b):
        if crit.name == name:
            return crit
    raise AssertionError(f"critere {name!r} absent de compare_by_criteria")


class ResolutionAnnonceEgaleDeltaTests(unittest.TestCase):
    """Constat #5 — `_resolution_height` et `_resolution_label` divergeaient.

    `_resolution_height` rend la CLASSE (2160/1080/720) au-dessus de 720p mais
    la HAUTEUR BRUTE en dessous ; `_resolution_label` re-classait cette valeur
    avec des seuils HAUTEUR (`h >= 480 -> "480p"`). Toute la plage SD
    [480..679] s'affichait donc « 480p » alors que la valeur comparee etait la
    hauteur brute.

    ROUGE MESURE avant correctif, 720x576 (PAL) contre 720x480 (NTSC) :
        value_a='480p'  value_b='480p'  winner='a'  points_delta=+30
    soit le POIDS PLEIN du critere resolution en faveur d'un fichier que la
    table de criteres declare identique. Le verdict n'est pas que affiche :
    « Auto-decider tous » envoie le perdant en _duplicates_user_decided/.
    """

    def test_meme_etiquette_implique_delta_nul(self) -> None:
        crit = _criterion(_probe(720, 576), _probe(720, 480), "resolution")
        if crit.value_a == crit.value_b:
            self.assertEqual(
                crit.points_delta,
                0,
                f"annonce '{crit.value_a}' vs '{crit.value_b}' (identiques) mais delta={crit.points_delta}",
            )
            self.assertEqual(crit.winner, "tie")

    def test_delta_non_nul_implique_etiquettes_distinctes(self) -> None:
        """Contrapposee : tout delta doit etre justifie par l'affichage."""
        cas = [
            ((720, 576), (720, 480)),
            ((720, 480), (640, 360)),
            ((1920, 800), (1280, 536)),
            ((3840, 1600), (1920, 1080)),
            ((1920, 1080), (1920, 1088)),
            ((1920, 800), (1920, 816)),
        ]
        for (wa, ha), (wb, hb) in cas:
            with self.subTest(a=(wa, ha), b=(wb, hb)):
                crit = _criterion(_probe(wa, ha), _probe(wb, hb), "resolution")
                self.assertEqual(
                    crit.points_delta == 0,
                    crit.value_a == crit.value_b,
                    f"'{crit.value_a}' vs '{crit.value_b}' -> delta={crit.points_delta}",
                )

    def test_echelle_deleguee_a_resolution_class(self) -> None:
        """L'echelle largeur-primaire n'est plus recopiee dans ce module.

        Garde de NON-DIVERGENCE : le comparateur doit rendre exactement la
        bande de `resolution_class.classify_resolution`, source unique du depot.

        Ce garde est vert des l'origine — il ne peut pas rougir en mutant
        `resolution_class`, ou les deux cotes liraient la meme valeur mutee
        (mutant EQUIVALENT par construction). Ce qu'il garde est la DELEGATION.
        Mutation runtime faite pour le prouver : re-injecter dans l'espace de
        noms de `duplicate_compare` une echelle HAUTEUR-primaire — la recopie
        pre-bug-178 que ce correctif a supprimee — le fait rougir sur 3 cas :
            1920x800  -> '720p'  au lieu de '1080p'  (scope 2.35:1)
            1280x536  -> '536p'  au lieu de '720p'
            3840x1600 -> '1600p' au lieu de '2160p'
        """
        for w, h in [(3840, 2160), (3840, 1600), (1920, 1080), (1920, 800), (1280, 720), (1280, 536), (720, 576)]:
            with self.subTest(w=w, h=h):
                bande = classify_resolution(w, h)
                if bande == "SD":
                    continue
                crit = _criterion(_probe(w, h), _probe(w, h), "resolution")
                self.assertEqual(crit.value_a, bande)


class CanauxAudioAbstentionTests(unittest.TestCase):
    """Constat #20 — le garde d'abstention etait INATTEIGNABLE pour les canaux.

    `_compare_criterion` s'abstient (`winner='unknown'`, delta 0) des qu'une
    valeur vaut None. Or l'appelant coercait `int(aa.get('channels') or 0)`
    AVANT l'appel : un probe audio absent devenait 0, jamais None.

    ROUGE MESURE, A=AC3 5.1 contre B sans aucune piste audio :
        value_a='5.1'  value_b='?'  winner='a'  points_delta=+10
    L'etiquette dit « inconnu » et le delta applique le poids PLEIN.
    """

    def test_probe_audio_absent_ne_fait_pas_perdre(self) -> None:
        crit = _criterion(
            _probe(1920, 1080, audio=[{"codec": "ac3", "channels": 6}]),
            _probe(1920, 1080, audio=[]),
            "audio_channels",
        )
        self.assertEqual(crit.value_b, "?")
        self.assertEqual(crit.winner, "unknown")
        self.assertEqual(crit.points_delta, 0)

    def test_canaux_manquants_des_deux_cotes(self) -> None:
        crit = _criterion(
            _probe(1920, 1080, audio=[{"codec": "ac3"}]),
            _probe(1920, 1080, audio=[{"codec": "dts"}]),
            "audio_channels",
        )
        self.assertEqual((crit.value_a, crit.value_b), ("?", "?"))
        self.assertEqual(crit.winner, "unknown")
        self.assertEqual(crit.points_delta, 0)

    def test_canaux_connus_tranchent_toujours(self) -> None:
        crit = _criterion(
            _probe(1920, 1080, audio=[{"codec": "ac3", "channels": 8}]),
            _probe(1920, 1080, audio=[{"codec": "ac3", "channels": 2}]),
            "audio_channels",
        )
        self.assertEqual(crit.winner, "a")
        self.assertEqual(crit.points_delta, 10)


class MeilleurePisteAudioTests(unittest.TestCase):
    """Constat #6 — `select_best_audio_track` ignorait `profile`/`is_atmos`.

    ffprobe range le codec de BASE dans `codec` ('dts') et la variante dans
    `profile` ('DTS-HD MA') / `is_atmos`. Les trois autres implementations de
    « la meilleure piste » passent par `_canonical_audio_codec` ; celle-ci
    faisait un substring sur `codec`/`title` seuls.

    ROUGE MESURE, remux BluRay DTS-HD MA 7.1 + piste EAC3 2.0 de commentaires :
        select_best_audio_track(...) -> {'codec': 'eac3', ...}
    soit exactement le defaut R8-039 deja corrige dans `quality_score`.
    """

    def test_dts_hd_ma_bat_une_piste_eac3(self) -> None:
        pistes = [
            {"codec": "dts", "profile": "DTS-HD MA", "channels": 8},
            {"codec": "eac3", "channels": 2, "title": "Commentaire"},
        ]
        self.assertIs(select_best_audio_track(pistes), pistes[0])

    def test_dts_hd_ma_gagne_meme_en_seconde_position(self) -> None:
        pistes = [
            {"codec": "flac", "channels": 2},
            {"codec": "dts", "profile": "DTS-HD MA", "channels": 8},
        ]
        self.assertIs(select_best_audio_track(pistes), pistes[1])

    def test_drapeau_is_atmos_equivaut_au_titre_atmos(self) -> None:
        """`is_atmos=True` et `title='Atmos'` doivent classer pareil."""
        par_titre = [{"codec": "flac", "channels": 2}, {"codec": "eac3", "channels": 6, "title": "Atmos"}]
        par_drapeau = [{"codec": "flac", "channels": 2}, {"codec": "eac3", "channels": 6, "is_atmos": True}]
        self.assertIs(select_best_audio_track(par_titre), par_titre[1])
        self.assertIs(select_best_audio_track(par_drapeau), par_drapeau[1])

    def test_dts_hd_hra_reste_lossy(self) -> None:
        """Non-regression #807 : HRA ne doit pas heriter du rang DTS-HD MA."""
        pistes = [
            {"codec": "dts", "profile": "DTS-HD HRA", "channels": 8},
            {"codec": "flac", "channels": 2},
        ]
        self.assertIs(select_best_audio_track(pistes), pistes[1])


class DtsXNomDeReleaseTests(unittest.TestCase):
    """Constat #8 — DTS:X : booleen cote parser, chaine de codec cote scorer.

    `_PATTERNS_AUDIO` declare la ligne `dts_x` avec `lossless=True`, valeur
    JETEE par le `continue` de la boucle. L'Atmos a un repli qui rattrape le
    porteur (`truehd`) ; DTS:X n'en avait aucun.

    ROUGE MESURE sur 'Dune.2021.2160p.UHD.BluRay.DTS-X.7.1-GRP.mkv' :
        audio_codec_hint='dts'   audio_is_lossless=False
    -- le token 'DTS-X' matche AUSSI le motif generique `\\bDTS\\b`, donc le
    porteur retenu etait un DTS LOSSY. Et sur la variante collee 'DTSX' :
        audio_codec_hint=''      audio_is_lossless=False
    -- aucun porteur du tout, donc AUCUNE piste synthetisee par
    `_merge_probe_with_name_hints` et zero point audio.
    """

    def test_dts_x_separe_donne_un_porteur_lossless(self) -> None:
        info = parse_release_name("Dune.2021.2160p.UHD.BluRay.DTS-X.7.1-GRP.mkv")
        self.assertTrue(info.audio_is_dts_x)
        self.assertEqual(info.audio_codec_hint, "dts_hd_ma")
        self.assertTrue(info.audio_is_lossless)

    def test_dts_x_deux_points_donne_un_porteur_lossless(self) -> None:
        info = parse_release_name("Blade.Runner.2049.2160p.BluRay.DTS:X.7.1-GRP.mkv")
        self.assertTrue(info.audio_is_dts_x)
        self.assertEqual(info.audio_codec_hint, "dts_hd_ma")
        self.assertTrue(info.audio_is_lossless)

    def test_dtsx_colle_donne_un_porteur_lossless(self) -> None:
        info = parse_release_name("Sicario.2015.2160p.UHD.BluRay.DTSX.7.1-GRP.mkv")
        self.assertTrue(info.audio_is_dts_x)
        self.assertEqual(info.audio_codec_hint, "dts_hd_ma")
        self.assertTrue(info.audio_is_lossless)

    def test_porteur_explicite_non_ecrase(self) -> None:
        """Un DTS-HD MA annonce reste DTS-HD MA, un TrueHD reste TrueHD."""
        info = parse_release_name("Film.2020.2160p.BluRay.TrueHD.7.1.DTS-X-GRP.mkv")
        self.assertTrue(info.audio_is_dts_x)
        self.assertEqual(info.audio_codec_hint, "truehd")
        self.assertTrue(info.audio_is_lossless)

    def test_dts_simple_reste_lossy(self) -> None:
        """Non-regression : un DTS nu ne devient pas lossless."""
        info = parse_release_name("Film.2020.1080p.BluRay.DTS.5.1-GRP.mkv")
        self.assertFalse(info.audio_is_dts_x)
        self.assertEqual(info.audio_codec_hint, "dts")
        self.assertFalse(info.audio_is_lossless)


class TagsProvidersRegexUniqueTests(unittest.TestCase):
    """Constat #9 — la meme regex de tag provider existait en TROIS exemplaires.

    Seul l'exemplaire de `naming.py` portait le `\\s*` avant le separateur, que
    les commentaires des TROIS annoncent (« tolere espaces internes »).

    ROUGE MESURE sur 'Inception (2010) {tmdb - 27205}' :
        naming.extract_provider_tags       -> tmdb_id=27205
        title_helpers.extract_provider_tags-> tmdb_id=None
        scene_parser.extract_provider_tags -> (None, None)
        scene_parser.strip_provider_tags   -> 'Inception (2010) {tmdb - 27205}'
    Consequence : le tag n'est ni retire du titre (les chiffres polluent la
    query fuzzy TMDb) ni exploite pour l'auto-link deterministe.
    """

    NOM = "Inception (2010) {tmdb - 27205} [imdbid - tt1375666]"

    def test_les_trois_extracteurs_lisent_le_meme_tag(self) -> None:
        self.assertEqual(naming.extract_provider_tags(self.NOM).tmdb_id, 27205)
        self.assertEqual(title_helpers.extract_provider_tags(self.NOM).tmdb_id, 27205)
        self.assertEqual(scene_parser.extract_provider_tags(self.NOM)[0], 27205)

    def test_les_trois_extracteurs_lisent_le_meme_imdb(self) -> None:
        self.assertEqual(naming.extract_provider_tags(self.NOM).imdb_id, "tt1375666")
        self.assertEqual(title_helpers.extract_provider_tags(self.NOM).imdb_id, "tt1375666")
        self.assertEqual(scene_parser.extract_provider_tags(self.NOM)[1], "tt1375666")

    def test_les_trois_strippers_nettoient_pareil(self) -> None:
        attendu = "Inception (2010)"
        self.assertEqual(naming.strip_provider_tags(self.NOM), attendu)
        self.assertEqual(title_helpers.strip_provider_tags(self.NOM), attendu)
        self.assertEqual(scene_parser.strip_provider_tags(self.NOM), attendu)

    def test_objet_regex_partage(self) -> None:
        """Une seule definition compilee : plus aucune copie a faire diverger."""
        self.assertIs(naming._PROVIDER_TMDB_TAG_RE, scene_parser._PROVIDER_TMDB_TAG_RE)
        self.assertIs(title_helpers._TMDB_TAG_RE, scene_parser._PROVIDER_TMDB_TAG_RE)
        self.assertIs(naming._PROVIDER_IMDB_TAG_RE, scene_parser._PROVIDER_IMDB_TAG_RE)
        self.assertIs(title_helpers._IMDB_TAG_RE, scene_parser._PROVIDER_IMDB_TAG_RE)

    def test_forme_compacte_toujours_reconnue(self) -> None:
        """Non-regression : la forme sans espace reste la forme dominante."""
        compact = "Fight Club [tmdb-550] [imdbid-tt0137523]"
        self.assertEqual(scene_parser.extract_provider_tags(compact), (550, "tt0137523"))
        self.assertEqual(naming.extract_provider_tags(compact).tmdb_id, 550)
        self.assertEqual(title_helpers.extract_provider_tags(compact).tmdb_id, 550)
        self.assertEqual(scene_parser.strip_provider_tags(compact), "Fight Club")


class GardePreventifMaxPathTests(unittest.TestCase):
    """Constat #15 — le garde PREVENTIF ne voit pas ce que le kill-switch tue.

    `check_path_length` mesure `root\\dossier` a 240 ; le kill-switch mesure le
    chemin cible COMPLET a 259. `windows_safe` tronque deja le dossier a 180 :
    la longueur qui tue vient du nom de fichier INTERNE, que le garde preventif
    ne recevait pas. Un seuil plus BAS qui ne peut pas se declencher avant le
    seuil plus HAUT n'est pas un garde, c'est un decor.

    ROUGE MESURE, root='D:\\Films', dossier de 180 chars, fichier interne de
    70 chars :
        check_path_length_killswitch(cible) -> 'PATH_TOO_LONG : ... 260 chars'
        check_path_length(root, dossier)    -> None
    """

    ROOT = "D:\\Films"

    def test_le_preventif_precede_le_killswitch(self) -> None:
        dossier = "D" * 180
        interne = "i" * 70 + ".mkv"
        cible = f"{self.ROOT}\\{dossier}\\{interne}"
        self.assertIsNotNone(check_path_length_killswitch(cible))
        self.assertIsNotNone(check_path_length(self.ROOT, dossier, inner_name=interne))

    def test_chemin_court_reste_muet(self) -> None:
        self.assertIsNone(check_path_length(self.ROOT, "Inception (2010)"))
        self.assertIsNone(check_path_length(self.ROOT, "Inception (2010)", inner_name="movie.mkv"))

    def test_le_garde_a_un_appelant_de_production(self) -> None:
        """ROUGE MESURE : ZERO appelant hors tests (sa def + test_naming.py +
        test_unicode_filenames.py). Un garde que personne n'appelle ne garde
        rien. Releve par AST, pas par comparaison de chaine : un appel reste un
        appel meme si la ligne est reecrite.
        """
        racine = Path(__file__).resolve().parent.parent / "cinesort"
        appelants: List[str] = []
        for chemin in racine.rglob("*.py"):
            if chemin.name == "naming.py":
                continue  # le module de definition ne compte pas
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.Call):
                    continue
                cible = noeud.func
                nom = cible.attr if isinstance(cible, ast.Attribute) else getattr(cible, "id", "")
                if nom == "check_path_length":
                    appelants.append(f"{chemin.relative_to(racine).as_posix()}:{noeud.lineno}")
        self.assertTrue(appelants, "check_path_length n'a aucun appelant de production")

    def test_zone_preventive_sans_killswitch(self) -> None:
        """Entre 240 et 259 : on avertit, on ne tue pas. C'est la marge."""
        dossier = "D" * 180
        interne = "i" * 55 + ".mkv"
        cible = f"{self.ROOT}\\{dossier}\\{interne}"
        self.assertGreater(len(cible), 240)
        self.assertLessEqual(len(cible), 259)
        self.assertIsNone(check_path_length_killswitch(cible))
        self.assertIsNotNone(check_path_length(self.ROOT, dossier, inner_name=interne))


if __name__ == "__main__":
    unittest.main()
