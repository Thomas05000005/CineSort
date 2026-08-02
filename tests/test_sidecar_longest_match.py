"""F03 — un sidecar ambigu doit revenir a la video au stem le plus specifique.

Contexte du finding (revue post-merge 2026-07-18) : `is_sidecar_for_video` matche
par PREFIXE (`ss.startswith(vs + delim)`). Dans un dossier partage contenant
`Alien.mkv` et `Alien 2.mkv`, le fichier `Alien 2.srt` matche les DEUX films, et
aucun arbitrage n'existait nulle part.

Consequence a l'apply : le sous-titre d'un film pouvait partir avec un autre —
notamment vers `_review/_duplicates_user_decided/` (loser d'un doublon) ou vers
le bucket de suppression, ou l'utilisateur vide manuellement = perte definitive.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from cinesort.domain import core


def _cfg(root: Path) -> core.Config:
    return core.Config(root=root).normalized()


class SidecarLongestMatchTests(unittest.TestCase):
    def test_sidecar_ambigu_va_au_stem_le_plus_long(self) -> None:
        with TemporaryDirectory() as tmp_name:
            folder = Path(tmp_name)
            (folder / "Alien.mkv").write_bytes(b"a")
            (folder / "Alien 2.mkv").write_bytes(b"b")
            (folder / "Alien.srt").write_text("x", encoding="utf-8")
            (folder / "Alien 2.srt").write_text("y", encoding="utf-8")
            cfg = _cfg(folder)

            pour_alien = sorted(
                p.name for p in core.classify_sidecars(cfg, folder, folder / "Alien.mkv", is_collection=True)
            )
            pour_alien2 = sorted(
                p.name for p in core.classify_sidecars(cfg, folder, folder / "Alien 2.mkv", is_collection=True)
            )

            self.assertEqual(
                pour_alien,
                ["Alien.srt"],
                "Alien.mkv ne doit pas revendiquer le sous-titre de Alien 2 (il l'emporterait a l'apply)",
            )
            self.assertEqual(pour_alien2, ["Alien 2.srt"])

    def test_sidecar_multi_tokens_suit_la_meme_regle(self) -> None:
        """Convention Plex/Jellyfin : langue et flags s'ajoutent apres le nom de base."""
        with TemporaryDirectory() as tmp_name:
            folder = Path(tmp_name)
            (folder / "Alien.mkv").write_bytes(b"a")
            (folder / "Alien 2.mkv").write_bytes(b"b")
            (folder / "Alien 2.fr.forced.srt").write_text("y", encoding="utf-8")
            cfg = _cfg(folder)

            pour_alien = [p.name for p in core.classify_sidecars(cfg, folder, folder / "Alien.mkv", is_collection=True)]
            pour_alien2 = [
                p.name for p in core.classify_sidecars(cfg, folder, folder / "Alien 2.mkv", is_collection=True)
            ]

            self.assertEqual(pour_alien, [])
            self.assertEqual(pour_alien2, ["Alien 2.fr.forced.srt"])

    def test_aucun_sidecar_ne_devient_orphelin(self) -> None:
        """Garde : chaque sidecar reste attribue a exactement une video."""
        with TemporaryDirectory() as tmp_name:
            folder = Path(tmp_name)
            (folder / "Alien.mkv").write_bytes(b"a")
            (folder / "Alien 2.mkv").write_bytes(b"b")
            noms = ["Alien.srt", "Alien.fr.srt", "Alien 2.srt", "Alien 2.fr.srt"]
            for nom in noms:
                (folder / nom).write_text("x", encoding="utf-8")
            cfg = _cfg(folder)

            attribues = []
            for video in ("Alien.mkv", "Alien 2.mkv"):
                attribues.extend(p.name for p in core.classify_sidecars(cfg, folder, folder / video, is_collection=True))

            self.assertEqual(sorted(attribues), sorted(noms), "aucun sidecar perdu")
            self.assertEqual(len(attribues), len(set(attribues)), "aucun sidecar attribue deux fois")

    def test_video_ignoree_au_scan_ne_capture_pas_de_sidecar(self) -> None:
        """Un sample/trailer ne produit aucune row : il ne doit rien revendiquer.

        Defaut trouve en revue adversaire : l'arbitrage comparait le sidecar a
        TOUTES les videos du dossier, y compris celles que le scan rejette. Le
        sous-titre etait attribue a une video jamais appliquee et restait
        orphelin dans le dossier source au lieu de suivre le film.
        """
        with TemporaryDirectory() as tmp_name:
            folder = Path(tmp_name)
            (folder / "Alien.mkv").write_bytes(b"a")
            (folder / "Alien.sample.mkv").write_bytes(b"s")
            (folder / "Alien.sample.fr.srt").write_text("s", encoding="utf-8")
            (folder / "Alien.fr.srt").write_text("x", encoding="utf-8")
            cfg = _cfg(folder)

            noms = sorted(
                p.name for p in core.classify_sidecars(cfg, folder, folder / "Alien.mkv", is_collection=True)
            )
            self.assertEqual(
                noms,
                ["Alien.fr.srt", "Alien.sample.fr.srt"],
                "le sample n'etant jamais applique, son sous-titre doit suivre le film reel",
            )

    def test_sans_video_concurrente_comportement_inchange(self) -> None:
        """NON-REGRESSION : hors ambiguite reelle, le correctif est un no-op strict."""
        with TemporaryDirectory() as tmp_name:
            folder = Path(tmp_name)
            (folder / "Alien.mkv").write_bytes(b"a")
            (folder / "Alien 2.srt").write_text("y", encoding="utf-8")
            (folder / "Alien.fr.srt").write_text("x", encoding="utf-8")
            cfg = _cfg(folder)

            noms = sorted(
                p.name for p in core.classify_sidecars(cfg, folder, folder / "Alien.mkv", is_collection=False)
            )
            self.assertEqual(
                noms,
                ["Alien 2.srt", "Alien.fr.srt"],
                "sans seconde video, Alien.mkv garde tous les sidecars qui le prefixent",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
