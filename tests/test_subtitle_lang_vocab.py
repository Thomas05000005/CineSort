"""Vocabulaire des langues de sous-titres : 3 sorties faussees du meme rapport.

Les trois defauts corriges ici alimentaient le MEME `SubtitleReport`
(`languages` / `missing_languages` / `duplicate_languages`), consomme par le
score qualite et par la Bibliotheque :

* #679 — `hi` etait declare tag « hearing impaired » dans la table de langues,
  donc le code ISO 639-1 du HINDI etait efface de toute piste embarquee (et
  `hin` etait absent) : langue disparue + faux `subtitle_missing_*`.
* #610 — `vo` (« version originale ») etait mappe vers l'ANGLAIS : un
  `Film.vo.srt` sur un film japonais faisait croire a un sous-titre EN present.
* #749 — une paire VobSub `Film.fr.idx` + `Film.fr.sub` (UN sous-titre, deux
  fichiers) etait comptee DEUX fois et levait un faux doublon de langue. Le
  correctif F12 des tags de variante ne couvre pas ce cas : la paire ne porte
  aucun tag.

Cause commune : une table `_LANG_MAP` unique servait deux vocabulaires
incompatibles (codes ISO ffprobe / tags de nom de fichier), et deux marches
arriere ecrites separement pouvaient donner deux roles differents au meme
token. Le correctif separe les tables et fait passer les deux lectures par
`_classify_subtitle_suffix`.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cinesort.domain.librarian import generate_suggestions
from cinesort.domain.subtitle_helpers import (
    _normalize_expected_language,
    _normalize_iso639,
    build_subtitle_report,
    detect_language_from_suffix,
)


def _report(video_name, sub_names, expected=None, embedded=None):
    """Chemin de PRODUCTION complet : dossier reel + build_subtitle_report."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        video = folder / video_name
        video.write_bytes(b"\x00")
        for name in sub_names:
            (folder / name).write_text("", encoding="utf-8")
        return build_subtitle_report(folder, video, expected, embedded_subtitles=embedded)


def _plan_row(row_id, subtitle_languages):
    """PlanRow-like tel que `generate_suggestions` le lit (via getattr)."""
    return SimpleNamespace(
        row_id=row_id,
        proposed_title=f"Film {row_id}",
        warning_flags=[],
        subtitle_languages=list(subtitle_languages),
        subtitle_missing_langs=[],
    )


def _films_flagges_sans_sous_titres(expected, rows):
    """Nombre de films que l'ecran Bibliothecaire annonce « sous-titres manquants »."""
    out = generate_suggestions(rows, [], {"subtitle_expected_languages": list(expected)})
    for suggestion in out["suggestions"]:
        if suggestion["id"] == "missing_subtitles":
            return int(suggestion["count"])
    return 0


class HindiNestPasUnTagMalentendant(unittest.TestCase):
    """#679 — `hi`/`hin` designent le HINDI, pas « hearing impaired »."""

    def test_piste_embarquee_hindi_est_conservee(self) -> None:
        """Le defaut le plus couteux : la piste hindi disparait ET declenche un
        faux « manquant ». `_normalize_iso639` est la table lue pour toutes les
        pistes venant de ffprobe/MediaInfo, ou `hi` ne peut signifier que hindi.
        """
        self.assertEqual(_normalize_iso639("hi"), "hi")
        self.assertEqual(_normalize_iso639("hin"), "hi")
        self.assertEqual(_normalize_iso639("hindi"), "hi")

        report = _report(
            "Bollywood.Film.mkv",
            [],
            ["hi"],
            embedded=[{"index": 0, "language": "hi", "forced": False}],
        )
        self.assertEqual(report.languages, ["hi"])
        self.assertEqual(report.missing_languages, [])

    def test_hi_seul_est_hindi_hi_apres_une_langue_est_une_variante(self) -> None:
        """L'arbitrage de l'ambiguite Jellyfin, dans les deux sens.

        La convention du projet est `sdh` pour le malentendant : un `hi` SEUL
        vaut donc hindi. Mais `Film.en.hi.srt` (convention Jellyfin) doit rester
        de l'ANGLAIS malentendant, pas devenir du hindi.
        """
        self.assertEqual(detect_language_from_suffix("Film.hi.srt", video_stem="Film"), "hi")
        self.assertEqual(detect_language_from_suffix("Film.en.hi.srt", video_stem="Film"), "en")
        self.assertEqual(detect_language_from_suffix("Film.fr.hi.forced.srt", video_stem="Film"), "fr")

    def test_sous_titre_hindi_externe_remonte_dans_le_rapport(self) -> None:
        report = _report("Film.mkv", ["Film.hi.srt"], ["hi"])
        self.assertEqual(report.languages, ["hi"])
        self.assertEqual(report.missing_languages, [])

    def test_hindi_seul_reste_comptable_comme_doublon(self) -> None:
        """Corollaire : le token qui PORTE la langue n'est pas un tag de
        variante. Sinon `Film.hi.srt` serait exclu du comptage des doublons
        comme s'il etait une piste malentendant, et un vrai doublon hindi
        passerait inapercu.
        """
        report = _report("Film.mkv", ["Film.hi.srt", "Film.hindi.srt"], [])
        self.assertEqual(report.duplicate_languages, ["hi"])
        # ... alors qu'une VRAIE variante malentendant n'est pas un doublon.
        report = _report("Film.mkv", ["Film.en.srt", "Film.en.hi.srt"], [])
        self.assertEqual(report.languages, ["en"])
        self.assertEqual(report.duplicate_languages, [])

    # --- NON-REGRESSION (doit rester VERT des deux cotes de la mutation) -----

    def test_les_autres_tags_ne_sont_toujours_pas_des_langues(self) -> None:
        for name in ("Film.forced.srt", "Film.sdh.srt", "Film.cc.srt"):
            with self.subTest(name=name):
                self.assertEqual(detect_language_from_suffix(name, video_stem="Film"), "")
        self.assertEqual(_normalize_iso639("sdh"), "")
        self.assertEqual(_normalize_iso639("und"), "")


class VoNestPasLAnglais(unittest.TestCase):
    """#610 — « version originale » ne dit rien de la langue."""

    def test_vo_ne_fabrique_plus_un_sous_titre_anglais(self) -> None:
        """Un film japonais avec `Film.vo.srt` : la VO est japonaise, pas
        anglaise. En mappant `vo` -> 'en', le rapport annoncait un sous-titre EN
        present et eteignait le signal « sous-titre EN manquant ».
        """
        self.assertEqual(detect_language_from_suffix("Film.vo.srt"), "")
        self.assertEqual(detect_language_from_suffix("Film.vo.srt", video_stem="Film"), "")
        self.assertEqual(_normalize_iso639("vo"), "")

        report = _report("Seven.Samurai.mkv", ["Seven.Samurai.vo.srt"], ["en"])
        self.assertEqual(report.languages, [])
        self.assertEqual(report.missing_languages, ["en"])

    # --- NON-REGRESSION -----------------------------------------------------

    def test_vostfr_et_vf_restent_du_francais(self) -> None:
        """`vostfr`/`vf`, eux, designent bien une langue : le sous-titre d'une
        VOSTFR EST francais. Seul `vo` etait une invention.
        """
        self.assertEqual(detect_language_from_suffix("Film.vostfr.srt"), "fr")
        self.assertEqual(detect_language_from_suffix("Film.vf.srt"), "fr")
        report = _report("Film.mkv", ["Film.vostfr.srt"], ["fr"])
        self.assertEqual(report.languages, ["fr"])
        self.assertEqual(report.missing_languages, [])

    def test_vo_ne_bloque_plus_la_lecture_du_code_langue_qui_le_precede(self) -> None:
        """`vo` n'est pas une langue, mais il n'est pas non plus un mot de titre.

        Il n'etait ni dans `_SUBTITLE_FLAG_TOKENS` (traversables) ni porteur de
        langue : la marche arriere s'arretait dessus et perdait le code juste
        avant. `Film.fr.vo.srt` rendait donc '' alors que le nom dit
        explicitement 'fr'. Idem pour `multi` et `und`.

        La borne F12 n'est pas relachee : on ne traverse que dans le mode
        BORNE (stem de la video connu), ou aucun token ne peut etre un mot du
        titre. Sans stem, rien ne change.
        """
        self.assertEqual(detect_language_from_suffix("Film.fr.vo.srt", video_stem="Film"), "fr")
        self.assertEqual(detect_language_from_suffix("Film.fr.multi.srt", video_stem="Film"), "fr")
        self.assertEqual(detect_language_from_suffix("Film.fr.und.srt", video_stem="Film"), "fr")
        # ... sans jamais inventer de langue quand `vo` est seul (#610).
        self.assertEqual(detect_language_from_suffix("Film.vo.srt", video_stem="Film"), "")
        # ... et la borne du mode NON borne reste intacte (mot de titre).
        self.assertEqual(detect_language_from_suffix("Dr.No.forced.srt"), "")


class LanguesAttenduesSaisiesParLUtilisateur(unittest.TestCase):
    """Regression de la revue adverse : `vf`/`vostfr` cotes ATTENDUES.

    Separer les tables (#679/#610) a retire `vostfr`/`vf` de `_ISO639_MAP`, la
    seule table que lit `_normalize_iso639`. Or `_normalize_iso639` ne servait
    pas qu'aux pistes ffprobe : il normalisait aussi les langues ATTENDUES
    SAISIES PAR L'UTILISATEUR. Le champ « Langues attendues » est du texte
    libre sans liste blanche, sur une application francophone dont la table
    d'alias code `vostfr`/`vf` en dur precisement parce que ce sont les
    conventions FR courantes.

    Sans normaliseur dedie, un utilisateur ayant saisi `vf` passait de 0 % a
    100 % de sa bibliotheque en « sous-titres manquants » — a la LECTURE, donc
    sans re-scan : il rouvrait l'ecran et tout etait rouge.
    """

    def test_vf_et_vostfr_attendus_matchent_le_fr_detecte(self) -> None:
        """Chemin SCAN (`build_subtitle_report`) — un vrai dossier avec un
        vrai `Film.fr.srt` a cote.
        """
        for saisie in ("vf", "vostfr", "VOSTFR", "  Vf  "):
            with self.subTest(saisie=saisie):
                report = _report("Film.mkv", ["Film.fr.srt"], [saisie])
                self.assertEqual(report.languages, ["fr"])
                self.assertEqual(
                    report.missing_languages,
                    [],
                    f"La saisie {saisie!r} doit matcher le 'fr' detecte, pas lever un faux manquant.",
                )

    def test_vf_attendu_ne_repeint_pas_la_bibliotheque_en_rouge(self) -> None:
        """Chemin LECTURE (`librarian.generate_suggestions`) — le plus expose :
        il normalise les attendues a CHAQUE appel, sur des donnees deja
        calculees. Une regression ici n'attend meme pas un re-scan.
        """
        rows = [_plan_row("a", ["fr"]), _plan_row("b", ["fr"])]
        for saisie in ("fr", "french", "fra", "vf", "vostfr"):
            with self.subTest(saisie=saisie):
                self.assertEqual(
                    _films_flagges_sans_sous_titres([saisie], rows),
                    0,
                    f"La saisie {saisie!r} doit reconnaitre les 2 films qui ONT leur sous-titre FR.",
                )

    # --- NON-REGRESSION -----------------------------------------------------

    def test_une_attente_reellement_absente_reste_signalee(self) -> None:
        """La garde ne doit pas devenir « tout matche ». Une langue vraiment
        absente, et une saisie non resolvable, restent signalees telles quelles.
        """
        self.assertEqual(_report("Film.mkv", ["Film.fr.srt"], ["en"]).missing_languages, ["en"])
        self.assertEqual(_report("Film.mkv", ["Film.fr.srt"], ["zzz"]).missing_languages, ["zzz"])
        rows = [_plan_row("a", ["fr"]), _plan_row("b", ["fr"])]
        self.assertEqual(_films_flagges_sans_sous_titres(["en"], rows), 2)

    def test_le_normaliseur_iso_reste_ferme_aux_tags_de_nom_de_fichier(self) -> None:
        """Le fond du correctif d'origine est preserve : la table ISO ignore
        toujours `vostfr`/`vf`/`vo`. Les deux besoins sont distincts, d'ou deux
        fonctions — pas une table reouverte.
        """
        for tag in ("vostfr", "vf", "vo"):
            with self.subTest(tag=tag):
                self.assertEqual(_normalize_iso639(tag), "")
        self.assertEqual(_normalize_expected_language("vostfr"), "fr")
        self.assertEqual(_normalize_expected_language("vf"), "fr")
        # `vo` n'est une langue pour PERSONNE (#610), pas meme cote saisie.
        self.assertEqual(_normalize_expected_language("vo"), "")


class PaireVobSubEstUnSeulSousTitre(unittest.TestCase):
    """#749 — `.idx` + `.sub` = UN sous-titre, pas un doublon de langue."""

    def test_paire_idx_sub_sans_tag_n_est_pas_un_doublon(self) -> None:
        """Le cas que le correctif F12 des tags de variante NE couvre PAS :
        `Film.fr.idx` / `Film.fr.sub` ne portent aucun tag, donc rien ne les
        excluait du comptage — toute bibliotheque de DVD remuxes etait flaggee
        `subtitle_duplicate_lang`.
        """
        report = _report("Film.mkv", ["Film.fr.idx", "Film.fr.sub"], [])
        self.assertEqual(report.duplicate_languages, [])
        # La langue reste bien detectee, et les deux FICHIERS restent comptes.
        self.assertEqual(report.languages, ["fr"])
        self.assertEqual(report.count, 2)
        self.assertEqual(report.formats, [".idx", ".sub"])

    def test_idx_orphelin_sans_sub_reste_compte(self) -> None:
        """On n'exclut l'index que quand son `.sub` frere existe : seul, le
        `.idx` est le seul fichier qui represente ce sous-titre.
        """
        report = _report("Film.mkv", ["Film.fr.idx", "Film.french.srt"], [])
        self.assertEqual(report.duplicate_languages, ["fr"])

    # --- NON-REGRESSION -----------------------------------------------------

    def test_vrai_doublon_avec_une_paire_vobsub_reste_detecte(self) -> None:
        """Paire VobSub FR + un .srt FR = DEUX sous-titres francais : le doublon
        est reel et doit rester signale. C'est l'assertion qui interdit de
        « corriger » #749 en ignorant purement et simplement les VobSub.
        """
        report = _report("Film.mkv", ["Film.fr.idx", "Film.fr.sub", "Film.french.srt"], [])
        self.assertEqual(report.duplicate_languages, ["fr"])

    def test_deux_paires_vobsub_de_langues_differentes(self) -> None:
        report = _report(
            "Film.mkv",
            ["Film.fr.idx", "Film.fr.sub", "Film.en.idx", "Film.en.sub"],
            ["fr", "en"],
        )
        self.assertEqual(report.languages, ["en", "fr"])
        self.assertEqual(report.duplicate_languages, [])
        self.assertEqual(report.missing_languages, [])

    def test_deux_paires_vobsub_de_meme_langue_restent_un_doublon(self) -> None:
        """Deux paires VobSub FR distinctes = deux sous-titres FR = doublon."""
        report = _report(
            "Film.mkv",
            ["Film.fr.idx", "Film.fr.sub", "Film.french.idx", "Film.french.sub"],
            [],
        )
        self.assertEqual(report.duplicate_languages, ["fr"])


if __name__ == "__main__":
    unittest.main()
