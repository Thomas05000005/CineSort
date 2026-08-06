"""Deux tables de constantes qui se declarent alignees sur une source unique... et ne le sont pas.

Ce dépôt a centralisé ses échelles pour empêcher les copies de diverger. Deux
copies avaient quand même dérivé, chacune SILENCIEUSEMENT — aucun test ne les
croisait avec leur source.

1. `library_support._classify_resolution` portait `h >= 1060` là où
   `domain.resolution_class.classify_resolution` (source de vérité) et les trois
   autres copies (`naming`, `duplicate_compare`, `perceptual/composite_score_v2`)
   portent toutes `h >= 1000`. `quality_score._resolution_label` se déclare
   pourtant explicitement « cohérent avec library_support._classify_resolution ».

2. `apply_support._resolve_hashed_target` lisait `VIDEO_EXTS_ALL` SEULE. Malgré
   son nom, cette table n'est pas l'union maximale des extensions vidéo : elle
   omet six des quatorze de `VIDEO_EXTS_DEFAULT`. Un film `.vob` ou `.m4v` — que
   le scan accepte et que l'apply a donc déplacé — n'y était pas trouvé, l'op
   était classée « destination absente », et la vérification d'identité sha1 de
   l'undo devenait inopérante sans le dire.

Ces tests croisent chaque copie avec sa source, pour que la prochaine dérive
soit rouge au lieu d'être invisible.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cinesort.domain.core as core
from cinesort.domain.resolution_class import (
    RES_720P,
    RES_1080P,
    RES_2160P,
    RES_SD,
    classify_resolution,
)
from cinesort.ui.api.apply_support import _resolve_hashed_target
from cinesort.ui.api.library_support import _classify_resolution

#: Vocabulaire du drawer bibliothèque -> vocabulaire canonique. Seule la QUEUE
#: (`unknown` vs `""`/`SD` quand aucune dimension n'est exploitable) diverge
#: légitimement : c'est documenté dans la note de dette de `resolution_class`.
_VERS_CANONIQUE = {"4k": RES_2160P, "1080p": RES_1080P, "720p": RES_720P, "sd": RES_SD}


class SeuilsResolutionTests(unittest.TestCase):
    def test_les_seuils_suivent_la_source_de_verite(self) -> None:
        """Toute dimension mesurable doit tomber dans la MEME bande des deux cotes."""
        dimensions = [
            (3840, 2160),  # 4K plein cadre
            (3840, 1600),  # 4K scope 2.39:1
            (1920, 1080),  # 1080p plein cadre
            (1920, 800),  # 1080p scope — le bug 178 historique
            (1280, 1024),  # largeur < 1900, hauteur dans [1000, 1060) : la derive
            (1680, 1050),  # idem (WSXGA+)
            (1280, 720),
            (1280, 536),  # 720p scope
            (720, 576),  # PAL
            (640, 480),
        ]
        for width, height in dimensions:
            with self.subTest(width=width, height=height):
                attendu = classify_resolution(width, height)
                obtenu = _VERS_CANONIQUE.get(_classify_resolution(width, height))
                self.assertEqual(
                    obtenu,
                    attendu,
                    f"{width}x{height} : la bibliotheque classe autrement que la source de verite",
                )

    def test_la_hauteur_sert_de_filet_quand_la_largeur_manque(self) -> None:
        """Cas explicitement prevu par `resolution_class` : probe partiel, largeur absente."""
        self.assertEqual(_classify_resolution(0, 1024), "1080p")
        self.assertEqual(_classify_resolution(0, 1050), "1080p")


class ExtensionsVideoUndoTests(unittest.TestCase):
    def test_VIDEO_EXTS_ALL_n_est_pas_l_union_maximale(self) -> None:
        """Le fait qui a induit le defaut. Verrouille pour qu'il reste ecrit noir sur blanc."""
        manquantes = set(core.VIDEO_EXTS_DEFAULT) - set(core.VIDEO_EXTS_ALL)
        self.assertEqual(
            manquantes,
            {".m4v", ".flv", ".mpg", ".mpeg", ".ogv", ".vob"},
            "si cette table bouge, relire les sites qui la lisent SEULE",
        )

    def test_la_video_principale_est_trouvee_pour_toute_extension_scannee(self) -> None:
        """Sans l'union, un film .vob rendait None -> op classee « destination absente »."""
        for ext in sorted(core.VIDEO_EXTS_DEFAULT):
            with self.subTest(ext=ext), tempfile.TemporaryDirectory() as tmp:
                dossier = Path(tmp) / "Film (2010)"
                dossier.mkdir()
                (dossier / "movie.nfo").write_bytes(b"x" * 4096)
                video = dossier / f"film{ext}"
                video.write_bytes(b"x" * 8192)

                self.assertEqual(
                    _resolve_hashed_target(dossier, "MOVE_DIR"),
                    video,
                    f"{ext} : la video principale n'est pas localisee, la verification sha1 est perdue",
                )


if __name__ == "__main__":
    unittest.main()
