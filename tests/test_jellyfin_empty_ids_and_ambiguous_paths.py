"""Appariement Jellyfin : identifiants vides et chemins ambigus (issues #452, #544, #566).

Trois defauts de la meme famille — une cle qui n'identifie pas ce qu'on croit :

- #452 : `build_sync_report` marquait les films apparies par leur id Jellyfin.
         Un id vide entrait dans le set et excluait ensuite TOUS les films sans
         id de la detection des fantomes.
- #544 : le repli « media indexe sous le dossier local » retenait le PREMIER
         candidat rencontre. Un film pose a la racine de la bibliotheque
         capturait ainsi un film sans rapport, avec ses metadonnees.
- #566 : `restore_watched` indexait Jellyfin par chemin dans un dict simple.
         Deux items sur le meme chemin (doublon d'indexation) et le premier id
         disparaissait : `mark_played` repartait sur un seul item.

Execution :
  ./.venv/Scripts/python.exe -m pytest tests/test_jellyfin_empty_ids_and_ambiguous_paths.py -q
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cinesort.app._path_utils import normalize_path
from cinesort.app.jellyfin_sync import WatchedInfo, restore_watched
from cinesort.app.jellyfin_validation import build_sync_report

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(title, year, folder, video="", tmdb_id=None):
    cands = [SimpleNamespace(tmdb_id=tmdb_id)] if tmdb_id else []
    return SimpleNamespace(
        proposed_title=title,
        proposed_year=year,
        folder=folder,
        video=video,
        candidates=cands,
    )


def _jf(name, year, path, jf_id="jf1", tmdb_id=None):
    return {"id": jf_id, "name": name, "year": year, "path": path, "tmdb_id": tmdb_id}


def _titles(entries):
    return sorted(e["title"] for e in entries)


# ---------------------------------------------------------------------------
# Issue #452 — id Jellyfin vide
# ---------------------------------------------------------------------------


class EmptyJellyfinIdTests(unittest.TestCase):
    """L'appariement ne doit pas dependre d'un id qui peut etre vide.

    Un id vide est reellement produit en amont : `PlexClient.get_movies` pose
    `str(item.get("ratingKey") or "")`, et `JellyfinClient.get_all_movies` pose
    `item.get("Id", "")` (chemin de repli utilise quand `get_libraries` echoue,
    car seul `get_all_movies_from_all_libraries` filtre les items sans id).
    """

    def test_movie_without_id_is_still_detected_as_ghost(self) -> None:
        """Un film Jellyfin sans id, absent du disque, reste un fantome.

        Avant : le film apparie sans id injectait "" dans `matched_jf_ids`, et
        le fantome — lui aussi sans id — se retrouvait « deja apparie ».
        """
        local = [_row("Present", 2020, "/films/present", video="present.mkv")]
        jf = [
            _jf("Present", 2020, "/films/present/present.mkv", jf_id=""),
            _jf("Disparu", 1999, "/films/disparu/disparu.mkv", jf_id=""),
        ]
        report = build_sync_report(local, jf)

        self.assertEqual(report["matched"], 1)
        self.assertEqual(_titles(report["ghost_in_jellyfin"]), ["Disparu"])

    def test_matched_movie_without_id_is_not_a_ghost(self) -> None:
        """Garde anti-sur-correction : ignorer les id vides ne doit pas
        transformer un film APPARIE sans id en faux fantome."""
        local = [_row("Present", 2020, "/films/present", video="present.mkv")]
        jf = [_jf("Present", 2020, "/films/present/present.mkv", jf_id="")]
        report = build_sync_report(local, jf)

        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["ghost_in_jellyfin"], [])


# ---------------------------------------------------------------------------
# Issue #544 — appariement par chemin ambigu
# ---------------------------------------------------------------------------


class AmbiguousPathMatchTests(unittest.TestCase):
    """Le repli « sous le dossier local » ne doit jamais deviner."""

    def test_film_a_la_racine_ne_capture_pas_un_film_voisin(self) -> None:
        """Le cas le plus couteux : un film pose a la RACINE de la bibliotheque.

        Son « dossier » est la racine elle-meme, donc TOUS les films Jellyfin
        sont sous ce prefixe. Le premier itere gagnait : le film absent de
        Jellyfin etait declare apparie, avec le titre et l'id d'un autre film,
        lequel disparaissait au passage de la liste des fantomes.
        """
        local = [_row("Dune", 2021, "D:/Films", video="Dune.2021.mkv")]
        jf = [
            _jf("Avatar", 2009, "D:/Films/Avatar (2009)/avatar.mkv", jf_id="jf-avatar"),
            _jf("Blade Runner", 1982, "D:/Films/Blade Runner (1982)/br.mkv", jf_id="jf-br"),
        ]
        report = build_sync_report(local, jf)

        self.assertEqual(report["matched"], 0)
        self.assertEqual(_titles(report["missing_in_jellyfin"]), ["Dune"])
        self.assertEqual(_titles(report["ghost_in_jellyfin"]), ["Avatar", "Blade Runner"])
        self.assertEqual(report["metadata_mismatch"], [])

    def test_dossier_frere_avec_le_meme_prefixe_n_est_pas_capture(self) -> None:
        """« …/Dune » ne doit pas capturer « …/Dune 2 » : la comparaison porte
        sur une frontiere de segment, pas sur un prefixe de chaine."""
        local = [_row("Dune", 2021, "D:/Films/Dune", video="dune.mkv")]
        jf = [_jf("Dune : Deuxieme partie", 2024, "D:/Films/Dune 2/dune2.mkv", jf_id="jf-dune2")]
        report = build_sync_report(local, jf)

        self.assertEqual(report["matched"], 0)
        self.assertEqual(_titles(report["missing_in_jellyfin"]), ["Dune"])
        self.assertEqual(_titles(report["ghost_in_jellyfin"]), ["Dune : Deuxieme partie"])

    def test_nom_du_fichier_video_departage_plusieurs_candidats(self) -> None:
        """Quand le dossier contient plusieurs medias Jellyfin, c'est le nom du
        fichier video qui tranche — pas l'ordre d'iteration."""
        local = [_row("Coffret second film", 1974, "D:/Films/Coffret", video="film2.mkv")]
        jf = [
            _jf("Premier film", 1900, "D:/Films/Coffret/disque1/film1.mkv", jf_id="jf-1"),
            _jf("Second film", 1901, "D:/Films/Coffret/disque2/film2.mkv", jf_id="jf-2"),
        ]
        report = build_sync_report(local, jf)

        self.assertEqual(report["matched"], 1)
        self.assertEqual(_titles(report["ghost_in_jellyfin"]), ["Premier film"])

    def test_candidat_unique_sous_le_dossier_matche_toujours(self) -> None:
        """Non-regression : le repli reste utile quand Jellyfin n'indexe pas le
        fichier video tel quel (rip BDMV indexe par un fichier interne).

        L'item Jellyfin est prive d'annee (`ProductionYear` absent) : ni le
        niveau tmdb_id ni le niveau titre+annee ne peuvent le rattraper, donc
        seul le repli « sous le dossier » peut produire l'appariement. Sans
        cette privation, le test resterait vert meme si le repli ne rendait
        plus rien.
        """
        local = [_row("Film BD", 2005, "D:/Films/Film BD (2005)", video="Film BD.iso")]
        jf = [_jf("Film BD", 0, "D:/Films/Film BD (2005)/BDMV/index.bdmv", jf_id="jf-bd")]
        report = build_sync_report(local, jf)

        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["missing_in_jellyfin"], [])
        self.assertEqual(report["ghost_in_jellyfin"], [])

    def test_chemin_exact_partage_par_deux_items_ne_designe_personne(self) -> None:
        """Deux items Jellyfin sur le MEME chemin : le dernier indexe gagnait.

        Ici le doublon porte un titre et une annee faux ; le dernier-gagne
        attribuait donc au film local le mauvais item et fabriquait une
        divergence de metadonnees. On refuse l'appariement par chemin et on
        laisse le niveau titre+annee, plus sur, faire le travail.
        """
        path = "D:/Films/Inception (2010)/inception.mkv"
        local = [_row("Inception", 2010, "D:/Films/Inception (2010)", video="inception.mkv")]
        jf = [
            _jf("Inception", 2010, path, jf_id="jf-bon"),
            _jf("Doublon fantome", 1901, path, jf_id="jf-doublon"),
        ]
        report = build_sync_report(local, jf)

        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["metadata_mismatch"], [])
        self.assertEqual(_titles(report["ghost_in_jellyfin"]), ["Doublon fantome"])


# ---------------------------------------------------------------------------
# Issue #566 — doublon de chemin dans restore_watched
# ---------------------------------------------------------------------------


def _restore(client, snapshot, operations):
    return restore_watched(
        client,
        "uid",
        snapshot,
        operations,
        initial_delay_s=0,
        retry_delay_s=0,
        max_retries=1,
    )


class DuplicatePathRestoreTests(unittest.TestCase):
    """`restore_watched` doit fusionner par chemin, pas ecraser."""

    OLD = r"C:\Films\ancien\film.mkv"
    NEW = r"C:\Films\Film (2010)\film.mkv"

    def _snapshot_and_ops(self):
        snapshot = {normalize_path(self.OLD): WatchedInfo(True, 2, "2026-01-01")}
        operations = [
            {"op_type": "MOVE", "src_path": self.OLD, "dst_path": self.NEW, "undo_status": "PENDING"},
        ]
        return snapshot, operations

    @patch("cinesort.app.jellyfin_sync.time.sleep")
    def test_tous_les_items_du_chemin_sont_marques(self, _sleep) -> None:
        """Deux items Jellyfin sur le nouveau chemin : les deux sont re-affirmes."""
        snapshot, operations = self._snapshot_and_ops()
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"id": "dup-a", "path": self.NEW},
            {"id": "dup-b", "path": self.NEW},
        ]
        client.mark_played.return_value = True

        result = _restore(client, snapshot, operations)

        marked = {call.args[1] for call in client.mark_played.call_args_list}
        self.assertEqual(marked, {"dup-a", "dup-b"})
        self.assertEqual(result.restored, 1)
        self.assertEqual(result.errors, 0)
        self.assertEqual(result.not_found, 0)

    @patch("cinesort.app.jellyfin_sync.time.sleep")
    def test_echec_partiel_sur_un_doublon_n_est_pas_un_succes(self, _sleep) -> None:
        """Un seul des deux items marque = echec, jamais un succes silencieux."""
        snapshot, operations = self._snapshot_and_ops()
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"id": "dup-ok", "path": self.NEW},
            {"id": "dup-ko", "path": self.NEW},
        ]
        client.mark_played.side_effect = lambda _uid, item_id: item_id != "dup-ko"

        result = _restore(client, snapshot, operations)

        self.assertEqual(result.restored, 0)
        self.assertEqual(result.errors, 1)
        errors = [d for d in result.details if d.get("action") == "error"]
        self.assertEqual(errors[0]["item_id"], "dup-ko")

    @patch("cinesort.app.jellyfin_sync.time.sleep")
    def test_id_vide_n_efface_pas_l_item_valide_du_meme_chemin(self, _sleep) -> None:
        """Un item sans id sur le meme chemin ne doit ni ecraser l'item valide,
        ni provoquer un appel `mark_played` sur une chaine vide."""
        snapshot, operations = self._snapshot_and_ops()
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"id": "reel", "path": self.NEW},
            {"id": "", "path": self.NEW},
        ]
        client.mark_played.return_value = True

        result = _restore(client, snapshot, operations)

        marked = [call.args[1] for call in client.mark_played.call_args_list]
        self.assertEqual(marked, ["reel"])
        self.assertEqual(result.restored, 1)
        self.assertEqual(result.not_found, 0)

    @patch("cinesort.app.jellyfin_sync.time.sleep")
    def test_meme_item_liste_deux_fois_n_est_marque_qu_une_fois(self, _sleep) -> None:
        """`get_all_movies_from_all_libraries` fusionne deja par id ; on ne
        multiplie pas les POST si un item revient deux fois."""
        snapshot, operations = self._snapshot_and_ops()
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"id": "meme", "path": self.NEW},
            {"id": "meme", "path": self.NEW},
        ]
        client.mark_played.return_value = True

        result = _restore(client, snapshot, operations)

        client.mark_played.assert_called_once_with("uid", "meme")
        self.assertEqual(result.restored, 1)


if __name__ == "__main__":
    unittest.main()
