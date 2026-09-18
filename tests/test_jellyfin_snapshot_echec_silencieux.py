"""L'echec du snapshot Jellyfin ne doit plus se confondre avec « rien a sauvegarder ».

`snapshot_watched` attrape TOUTE exception du client et rendait `{}`. Or `{}`
est aussi ce que rend une bibliotheque ou aucun film n'est marque comme vu. Les
deux cas partaient ensuite dans le meme silence :

    _snapshot_jellyfin_watched : `if snapshot:` -> aucun log
    _restore_jellyfin_watched  : `if not snapshot: return`

Pendant ce temps l'apply, lui, deplacait bien les fichiers. Jellyfin cle ses
items par chemin : il re-indexe alors des items NEUFS et les statuts « vu » sont
perdus, definitivement, sans que rien ne les restaure. Le journal d'apply
n'affichait pas une ligne a ce sujet.

Le remede ne rend pas l'apply bloquant — ce serait un arbitrage produit. Il rend
ATTEIGNABLE la garde qui existait deja juste a cote (`log_fn("WARN", "Jellyfin
sync : échec snapshot — ...")`, apply_support.py) et que `snapshot_watched`
privait de sa matiere en avalant l'echec avant elle.

PIEGE EVITE — LE MOCK QUI FABRIQUE LA CONDITION TESTEE
------------------------------------------------------
Les clients sont de VRAIES classes (meme parti que
`test_jellyfin_watched_counters_535.py`). Un `MagicMock` rendrait un objet
truthy pour `get_all_movies_from_all_libraries`, la boucle de `snapshot_watched`
itererait sur un Mock et le test ne prouverait rien du cas reel.

PIEGE EVITE — TESTER LA DECISION SANS SON SITE D'APPEL
-------------------------------------------------------
Les tests de journalisation ne patchent PAS `snapshot_watched` : ils patchent le
CLIENT et laissent la vraie fonction s'executer. Un mutant qui supprimerait
l'appel, ou qui passerait la mauvaise valeur, doit mourir — eprouver la seule
decision laisserait ces deux-la vivants.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from cinesort.app.jellyfin_sync import WatchedInfo, _normalize_path, snapshot_watched
from cinesort.infra.jellyfin_client import JellyfinError
from cinesort.ui.api import apply_support

_PATH_VU = r"C:\Films\Inception (2010)\Inception.2010.1080p.BluRay.mkv"
_PATH_NON_VU = r"C:\Films\Matrix (1999)\Matrix.1999.1080p.BluRay.mkv"
_DATE = "2026-01-15T20:11:37.0000000Z"

_SETTINGS: Dict[str, Any] = {
    "jellyfin_enabled": True,
    "jellyfin_url": "http://nas:8096",
    "jellyfin_api_key": "cle-de-test",
    "jellyfin_user_id": "uid",
}


class _ClientEnPanne:
    """Serveur eteint / 401 : la lecture de la bibliotheque leve."""

    def get_all_movies_from_all_libraries(self, user_id: str) -> List[Dict[str, Any]]:
        raise JellyfinError("Connexion impossible à http://nas:8096 : [Errno 111] Connection refused")


class _ClientQuiRepond:
    """Serveur joignable : il rend la liste qu'on lui donne, meme vide."""

    def __init__(self, movies: List[Dict[str, Any]]) -> None:
        self._movies = movies

    def get_all_movies_from_all_libraries(self, user_id: str) -> List[Dict[str, Any]]:
        return list(self._movies)


def _film(path: str, *, played: bool) -> Dict[str, Any]:
    return {
        "path": path,
        "played": played,
        "play_count": 17 if played else 0,
        "last_played_date": _DATE if played else "",
    }


def _capture_snapshot(client: Any) -> Tuple[Any, List[Tuple[str, str]]]:
    """Joue `_snapshot_jellyfin_watched` de bout en bout sur `client`.

    Seuls les settings et la FABRIQUE de client sont remplaces : le vrai
    `snapshot_watched` s'execute, donc le site d'appel est exerce.
    """
    logs: List[Tuple[str, str]] = []
    with (
        patch.object(apply_support, "_read_jellyfin_settings", return_value=dict(_SETTINGS)),
        patch.object(apply_support, "_make_jellyfin_client", return_value=client),
    ):
        ctx = apply_support._snapshot_jellyfin_watched(None, lambda level, msg: logs.append((level, msg)))
    return ctx, logs


class SnapshotDistingueEchecEtBibliothequeVideTests(unittest.TestCase):
    """`None` (on ne sait pas) et `{}` (rien a sauvegarder) sont deux reponses."""

    def test_un_echec_de_lecture_rend_none(self) -> None:
        """ROUGE sans le correctif : la fonction rendait `{}`."""
        self.assertIsNone(snapshot_watched(_ClientEnPanne(), "uid"))

    def test_une_bibliotheque_vide_rend_un_dict_vide(self) -> None:
        """CONTRE-TEST : le correctif ne doit pas transformer « vide » en « echec »."""
        snapshot = snapshot_watched(_ClientQuiRepond([]), "uid")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot, {})

    def test_une_bibliotheque_sans_aucun_film_vu_rend_un_dict_vide(self) -> None:
        """CONTRE-TEST : des films presents mais non vus, ce n'est pas un echec."""
        snapshot = snapshot_watched(_ClientQuiRepond([_film(_PATH_NON_VU, played=False)]), "uid")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot, {})

    def test_le_cas_nominal_rend_les_films_vus(self) -> None:
        """NON-REGRESSION : la capture elle-meme est inchangee."""
        snapshot = snapshot_watched(
            _ClientQuiRepond([_film(_PATH_VU, played=True), _film(_PATH_NON_VU, played=False)]),
            "uid",
        )

        self.assertEqual(snapshot, {_normalize_path(_PATH_VU): WatchedInfo(True, 17, _DATE)})


class LEchecDuSnapshotAtteintLeJournalDApplyTests(unittest.TestCase):
    """Ce que l'utilisateur lit dans le journal de l'apply, pas ce que le code sait."""

    def test_un_echec_est_annonce_avant_que_les_fichiers_ne_bougent(self) -> None:
        """ROUGE sans le correctif : le journal ne portait AUCUNE ligne.

        L'assertion ne se contente pas d'un WARN : elle exige que le message
        nomme la consequence (la restauration impossible). « Seul le correctif
        produit ca » — un WARN generique d'une autre source ne la satisferait
        pas.
        """
        ctx, logs = _capture_snapshot(_ClientEnPanne())

        warns = [msg for level, msg in logs if level == "WARN"]
        self.assertTrue(
            any("restaur" in msg.lower() for msg in warns),
            f"l'echec du snapshot doit etre annonce a l'utilisateur, logs={logs}",
        )
        # Aucun contexte rendu : `_restore_jellyfin_watched` ne doit pas croire
        # qu'il a un snapshot (vide) a restaurer.
        self.assertIsNone(ctx)

    def test_une_bibliotheque_sans_film_vu_ne_declenche_aucune_alerte(self) -> None:
        """CONTRE-TEST : ne pas crier au loup quand il n'y a rien a sauvegarder.

        VERT des deux cotes du correctif — c'est justement ce qui prouve que
        l'alerte ajoutee vise l'IGNORANCE et non l'absence.
        """
        ctx, logs = _capture_snapshot(_ClientQuiRepond([_film(_PATH_NON_VU, played=False)]))

        self.assertEqual([msg for level, msg in logs if level == "WARN"], [])
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["snapshot"], {})

    def test_le_cas_nominal_reste_annonce_en_info(self) -> None:
        """NON-REGRESSION : la ligne « N film(s) vu(s) sauvegardé(s) » subsiste."""
        ctx, logs = _capture_snapshot(_ClientQuiRepond([_film(_PATH_VU, played=True)]))

        self.assertEqual([msg for level, msg in logs if level == "WARN"], [])
        self.assertTrue(
            any(level == "INFO" and "1" in msg for level, msg in logs),
            f"le cas nominal doit rester annonce, logs={logs}",
        )
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx["user_id"], "uid")
        self.assertEqual(ctx["snapshot"], {_normalize_path(_PATH_VU): WatchedInfo(True, 17, _DATE)})


if __name__ == "__main__":
    unittest.main()
