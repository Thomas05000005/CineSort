# -*- coding: utf-8 -*-
"""Symboles morts CABLES plutot que supprimes (issues #490, #781, #483, #702, #715).

Trois symboles etaient declares et jamais lus. Ce n'etaient pas des dechets :
chacun decrivait une intention que le code appliquait mal, ou pas du tout, juste
a cote. Ce fichier verrouille le cablage.

1. `radarr_sync._UPGRADE_ENCODE_FLAGS` : la constante nommait les deux flags
   d'encode qui justifient un upgrade Radarr, pendant que la detection reelle
   cherchait les sous-chaines "upscale"/"reencode" dans les LIBELLES humains du
   rapport. Or le libelle est "Re-encode degrade" (trait d'union) : il ne
   contient pas "reencode". Le flag `reencode_degraded` ne declenchait donc
   jamais d'upgrade quand il etait seul — le cas SD sous 300 kbps.
2. `_fuzzy_utils.find_best_fuzzy_match` : helper vectorise de l'issue #29, jamais
   appele, parce que son contrat perdait l'index (il filtrait les choix vides
   sans memoriser leur position d'origine) alors que ses 3 call sites prevus ont
   precisement besoin de l'index pour remonter a l'objet metier.
3. `library_actions_support._EXPORT_FIELDS` : la liste des colonnes d'export
   etait re-ecrite a la main a 3 endroits, et la 4e copie — la constante morte —
   avait deja derive (tier_v2 / audio_languages / subtitle_languages).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any, Dict, List

from cinesort.app._fuzzy_utils import find_best_fuzzy_match
from cinesort.app.radarr_sync import _OBSOLETE_CODECS, _UPGRADE_ENCODE_FLAGS, should_propose_upgrade
from cinesort.domain.encode_analysis import analyze_encode_quality
from cinesort.domain.quality_score import _apply_encode_warnings_helper

REPO_ROOT = Path(__file__).resolve().parent.parent


def _reasons_for(detected: Dict[str, Any]) -> List[str]:
    """Les libelles humains EXACTEMENT tels que le scoring les persiste.

    Le fixture ne doit surtout pas figer `reasons=[]` : ce sont ces libelles
    que l'ANCIENNE detection par sous-chaine lisait. Avec une liste vide,
    aucun test ne reproduirait le bug corrige ("Re-encode degrade" ne contient
    pas la sous-chaine "reencode"), et le test estampille "non-regression"
    serait rouge sous l'ancienne implementation — donc il ne prouverait rien
    d'autre que le correctif lui-meme.

    Les libelles viennent du producteur reel (`_apply_encode_warnings_helper`,
    quality_score.py) : ni copie, ni paraphrase, donc pas de derive possible.
    """
    reasons: List[str] = []
    _apply_encode_warnings_helper(
        encode_warnings=analyze_encode_quality(detected),
        video_sub=0.0,
        factors=[],
        reasons=reasons,
    )
    return reasons


def _report(**detected: Any) -> Dict[str, Any]:
    """Rapport qualite realiste : `metrics.detected` ET les `reasons` associees."""
    base: Dict[str, Any] = {"height": 1080, "bitrate_kbps": 12000, "video_codec": "hevc"}
    base.update(detected)
    return {"score": 70, "tier": "Silver", "reasons": _reasons_for(base), "metrics": {"detected": base}}


def _legacy_report(**detected: Any) -> Dict[str, Any]:
    """Rapport persiste par une ANCIENNE version : codec sous la cle `codec`.

    Les `reasons` restent celles calculees a l'epoque par le scoring, qui
    disposait du vrai codec — seule la cle de persistance differe.
    """
    rep = _report(**detected)
    det = rep["metrics"]["detected"]
    det["codec"] = det.pop("video_codec")
    return rep


MONITORED = {"monitored": True, "row_id": "r1"}


class UpgradeEncodeFlagsTests(unittest.TestCase):
    """`_UPGRADE_ENCODE_FLAGS` pilote enfin la detection d'upgrade."""

    def test_constant_matches_the_canonical_flag_names(self) -> None:
        """La constante doit nommer des flags que `analyze_encode_quality` emet."""
        emitted = set(analyze_encode_quality({"height": 1080, "bitrate_kbps": 400, "video_codec": "hevc"}))
        self.assertTrue(_UPGRADE_ENCODE_FLAGS.issubset(emitted))

    def test_sd_reencode_degrade_seul_propose_un_upgrade(self) -> None:
        """LE cas qui echouait : SD 250 kbps -> `reencode_degraded` SANS upscale.

        En SD (height < 680) `analyze_encode_quality` n'ajoute pas
        `upscale_suspect` : `reencode_degraded` est seul, et son libelle
        "Re-encode degrade" ne contenait pas la sous-chaine "reencode" cherchee.
        Le rapport porte ici le VRAI libelle, donc ce test est rouge sous
        l'ancienne detection a cause du trait d'union — pas d'un fixture vide.
        """
        detected = {"height": 480, "bitrate_kbps": 250, "video_codec": "h264"}
        self.assertEqual(analyze_encode_quality(detected), ["reencode_degraded"])
        rep = _report(**detected)
        # La racine du bug, rendue explicite : le libelle persiste ne contient
        # aucune des deux sous-chaines que l'ancienne detection cherchait.
        self.assertTrue(rep["reasons"])
        self.assertFalse(any("upscale" in r.lower() or "reencode" in r.lower() for r in rep["reasons"]))
        self.assertTrue(should_propose_upgrade(MONITORED, rep))

    def test_upscale_1080p_propose_toujours_un_upgrade(self) -> None:
        """Non-regression : le cas qui marchait AVANT marche toujours.

        Verte des DEUX cotes : le rapport porte "Upscale suspect", que
        l'ancienne detection par sous-chaine attrapait deja.
        """
        detected = {"height": 1080, "bitrate_kbps": 900, "video_codec": "hevc"}
        self.assertIn("upscale_suspect", analyze_encode_quality(detected))
        rep = _report(**detected)
        self.assertTrue(any("upscale" in r.lower() for r in rep["reasons"]))
        self.assertTrue(should_propose_upgrade(MONITORED, rep))

    def test_fichier_sain_ne_propose_pas_d_upgrade(self) -> None:
        """Non-regression : pas de faux positif sur un fichier propre."""
        self.assertEqual(analyze_encode_quality({"height": 1080, "bitrate_kbps": 12000, "video_codec": "hevc"}), [])
        self.assertFalse(should_propose_upgrade(MONITORED, _report()))

    def test_4k_light_seul_ne_propose_pas_d_upgrade(self) -> None:
        """`4k_light` est informatif : volontairement hors _UPGRADE_ENCODE_FLAGS."""
        detected = {"height": 2160, "bitrate_kbps": 12000, "video_codec": "hevc"}
        self.assertEqual(analyze_encode_quality(detected), ["4k_light"])
        self.assertFalse(should_propose_upgrade(MONITORED, _report(**detected)))

    def test_codec_obsolete_lu_sur_la_bonne_cle(self) -> None:
        """`metrics.detected` expose `video_codec`, pas `codec` : la branche
        codec obsolete lisait une cle inexistante et etait inatteignable."""
        self.assertTrue(should_propose_upgrade(MONITORED, _report(video_codec="xvid", bitrate_kbps=12000)))

    def test_codec_obsolete_cle_legacy_toujours_acceptee(self) -> None:
        """Rapports persistes par d'anciennes versions : fallback sur `codec`."""
        rep = _legacy_report(video_codec="divx", bitrate_kbps=12000)
        self.assertNotIn("video_codec", rep["metrics"]["detected"])
        self.assertTrue(should_propose_upgrade(MONITORED, rep))

    def test_flags_d_encode_lus_aussi_sur_la_cle_legacy(self) -> None:
        """Le fallback legacy doit couvrir les DEUX branches, pas seulement le codec.

        `analyze_encode_quality` ne lit que `video_codec` : sans reinjection du
        codec normalise, le meme rapport ancien serait honore pour "codec
        obsolete" et ignore pour les flags d'encode. Ce cas (1080p h264 a
        900 kbps) proposait un upgrade avant le PR ET doit le proposer apres.
        """
        rep = _legacy_report(video_codec="h264", height=1080, bitrate_kbps=900)
        det = rep["metrics"]["detected"]
        self.assertEqual(det["codec"], "h264")
        self.assertNotIn("video_codec", det)
        # Le codec n'est pas obsolete : seule la branche flags d'encode peut repondre.
        self.assertNotIn(det["codec"], _OBSOLETE_CODECS)
        self.assertEqual(analyze_encode_quality(det), [])
        self.assertTrue(should_propose_upgrade(MONITORED, rep))

    def test_film_non_monitored_jamais_propose(self) -> None:
        """Non-regression : le garde `monitored` prime sur tout le reste."""
        detected = {"height": 480, "bitrate_kbps": 250, "video_codec": "h264"}
        self.assertFalse(should_propose_upgrade({"monitored": False}, _report(**detected)))


class FindBestFuzzyMatchTests(unittest.TestCase):
    """Le helper rend un index EXPLOITABLE par le caller."""

    def test_index_pointe_dans_la_liste_d_origine(self) -> None:
        """Un choix vide en tete decalait l'index et rendait le helper inutilisable."""
        choices = ["", "avatar", "inception"]
        best = find_best_fuzzy_match("Inception", choices)
        self.assertIsNotNone(best)
        assert best is not None
        match_str, score, idx = best
        self.assertEqual(match_str, "inception")
        self.assertGreaterEqual(score, 85)
        self.assertEqual(idx, 2)
        self.assertEqual(choices[idx], "inception")

    def test_sans_choix_vide_l_index_reste_juste(self) -> None:
        choices = ["avatar", "inception", "arrival"]
        best = find_best_fuzzy_match("Arrival", choices)
        assert best is not None
        self.assertEqual(choices[best[2]], "arrival")

    def test_accents_normalises_des_deux_cotes(self) -> None:
        best = find_best_fuzzy_match("Café Society", ["cafe society"])
        assert best is not None
        self.assertEqual(best[2], 0)

    def test_sous_le_seuil_renvoie_none(self) -> None:
        self.assertIsNone(find_best_fuzzy_match("Inception", ["avatar"]))

    def test_query_vide_renvoie_none(self) -> None:
        self.assertIsNone(find_best_fuzzy_match("", ["inception"]))

    def test_choix_tous_vides_renvoie_none(self) -> None:
        self.assertIsNone(find_best_fuzzy_match("Inception", ["", "   "]))

    def test_choices_are_normalized_evite_la_re_normalisation(self) -> None:
        """Les index pre-normalises (radarr_by_year_normalized) sont passes tels quels."""
        best = find_best_fuzzy_match("Inception", ["inception"], choices_are_normalized=True)
        assert best is not None
        self.assertEqual(best[2], 0)

    def test_token_sort_insensible_a_l_ordre_des_mots(self) -> None:
        best = find_best_fuzzy_match("Society Cafe", ["cafe society"], use_token_sort=True)
        assert best is not None
        self.assertEqual(best[2], 0)


class RadarrFuzzyStillMatchesTests(unittest.TestCase):
    """Non-regression : le fallback fuzzy de radarr_sync passe par le helper."""

    def test_match_par_accent_via_le_helper(self) -> None:
        import types

        from cinesort.app.radarr_sync import build_radarr_report

        rows = [
            types.SimpleNamespace(
                folder="/movies/x",
                video="x.mkv",
                proposed_title="Café Society",
                proposed_year=2016,
                row_id="r1",
                candidates=[],
            )
        ]
        # Un film de la meme annee AVANT la cible : si l'index rendu par le
        # helper etait faux, c'est ce film-la qui serait matche.
        radarr: List[Dict[str, Any]] = [
            {
                "id": 7,
                "title": "Arrival",
                "year": 2016,
                "tmdb_id": 0,
                "monitored": True,
                "has_file": True,
                "quality_profile_id": 1,
                "path": "/other/arrival",
                "quality_name": "HD",
            },
            {
                "id": 1,
                "title": "Cafe Society",
                "year": 2016,
                "tmdb_id": 0,
                "monitored": True,
                "has_file": True,
                "quality_profile_id": 1,
                "path": "/other/cafe",
                "quality_name": "HD",
            },
        ]
        report = build_radarr_report(rows, radarr, {}, [])
        self.assertEqual(report["matched_count"], 1)
        self.assertEqual(report["matched"][0]["radarr_id"], 1)


class ExportFieldsSingleSourceTests(unittest.TestCase):
    """`_EXPORT_FIELDS` est la source unique des colonnes d'export."""

    def test_export_fields_single_source(self) -> None:
        """Les cles produites par `_row_to_export_dict` == les colonnes declarees.

        C'est ce contrat qui manquait : la constante avait derive vers
        `tier_v2` / `audio_languages` / `subtitle_languages` sans que rien
        n'echoue, parce que personne ne la lisait.
        """
        from cinesort.ui.api.library_actions_support import _EXPORT_FIELDS, _row_to_export_dict

        produced = _row_to_export_dict(
            {
                "row_id": "r1",
                "title": "Inception",
                "year": 2010,
                "score_v2": 91,
                "tier_v2": "Gold",
                "path": "/movies/Inception (2010)",
                "size_bytes": 123,
                "duration_min": 148,
                "codec": "hevc",
                "resolution": "1080p",
                "audio_languages": ["fr", "en"],
                "subtitle_languages": ["fr"],
                "warnings": [],
            }
        )
        self.assertEqual(tuple(produced.keys()), _EXPORT_FIELDS)

    def test_export_fields_sans_doublon(self) -> None:
        from cinesort.ui.api.library_actions_support import _EXPORT_FIELDS

        self.assertEqual(len(set(_EXPORT_FIELDS)), len(_EXPORT_FIELDS))


class ScanHelpersSingleBonusRuleTests(unittest.TestCase):
    """`file_name_looks_bonus` est la seule implementation restante de la regle."""

    def test_une_seule_implementation_de_la_regle(self) -> None:
        """Exactement UNE fonction du module consulte GENERIC_EXTRA_VIDEO_NAMES.

        Le module en portait trois : la fonction publique, une closure, et une
        variante `Path` morte (celle-ci supprimee en amont par #705). On compte
        les implementations plutot que de nommer les clones supprimes : nommer
        un symbole absent, meme pour l'interdire, le ferait passer pour "lu"
        par test_contract_dead_symbols.
        """
        import ast
        from pathlib import Path as _Path

        src = (_Path(REPO_ROOT) / "cinesort" / "domain" / "scan_helpers.py").read_text(encoding="utf-8")
        holders = [
            node.name
            for node in ast.walk(ast.parse(src))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(sub, ast.Name) and sub.id == "GENERIC_EXTRA_VIDEO_NAMES" for sub in ast.walk(node))
        ]
        self.assertEqual(holders, ["file_name_looks_bonus"])

    def test_regle_bonus_inchangee(self) -> None:
        """Non-regression : memes verdicts qu'avant la fusion des 3 copies."""
        from cinesort.domain.scan_helpers import file_name_looks_bonus

        for name in ("Inception.sample.mkv", "trailer.mkv", "Bonus.mkv", "making of.mkv", "deleted-scenes.mkv"):
            self.assertTrue(file_name_looks_bonus(name), name)
        for name in ("Inception (2010).mkv", "Demo Day (2015).mkv", "Fahrenheit 451.mkv", ""):
            self.assertFalse(file_name_looks_bonus(name), name)


class RetentionDaysPhantomTests(unittest.TestCase):
    """Le reglage fantome `retention_days` a bien ete supprime (#781)."""

    def test_le_reglage_n_est_plus_persiste(self) -> None:
        """Envoyer la cle ne doit plus rien ecrire : elle n'avait aucun lecteur."""
        from cinesort.ui.api.settings_support import _save_section_advanced

        out = _save_section_advanced({"retention_days": 180, "history_retention_days": 42})
        self.assertNotIn("retention_days", out)
        self.assertEqual(out.get("history_retention_days"), 42)

    def test_le_reglage_reellement_branche_survit(self) -> None:
        """Non-regression : `history_retention_days` (lu par app.py) est intact."""
        from cinesort.ui.api.settings_support import _save_section_advanced

        self.assertEqual(_save_section_advanced({"history_retention_days": 9000}), {"history_retention_days": 3650})

    def test_le_champ_ui_a_disparu_de_parametres_js(self) -> None:
        """Le curseur "Retention scores et analyses" ne doit plus etre propose.

        `key: "history_retention_days"` contient la sous-chaine : on ancre donc
        sur la cle EXACTE, pas sur une recherche naive.
        """
        js = (REPO_ROOT / "web" / "dashboard" / "views" / "parametres.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r'key:\s*"retention_days"', js))
        self.assertIsNotNone(re.search(r'key:\s*"history_retention_days"', js))


if __name__ == "__main__":
    unittest.main()
