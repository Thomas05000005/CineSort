"""Un serveur INJOIGNABLE n'est pas un film NON RETROUVE.

`restore_watched` classe les films non restaures en trois causes. Deux d'entre
elles se confondaient : quand le serveur Jellyfin ne repond a AUCUNE des cinq
tentatives (NAS endormi, cable debranche, service arrete pendant l'apply), la
boucle `continue` sans jamais remplir `jellyfin_by_path`. `pending` reste donc
plein et `mark_failed` vide — exactement l'etat produit par un serveur qui
REPOND mais n'a pas encore re-indexe. Tout tombait dans la meme branche :

    result.not_found += 1
    "reason": "film non retrouve dans Jellyfin apres re-indexation"

L'utilisateur etait bien prevenu — c'est ce qui separe ce defaut d'un silence —
mais le message l'envoie chercher un « Force Refresh All Metadata » quand la
seule action utile est de rallumer une machine.

Ce que cette batterie verrouille, dans les deux sens :

- le cas du defaut : aucune reponse -> `unreachable`, et la raison nomme le
  reseau ;
- les CONTRE-TESTS, qui pesent autant : un serveur qui repond garde `not_found`
  (sinon on aurait remplace un diagnostic faux par un autre), une seule reponse
  suffit a refuser le verdict « injoignable », et un `mark_played` en echec
  persistant reste en `errors` ;
- le SITE D'APPEL : sortir ces films de `not_found` sans message dedie les
  ferait passer d'un diagnostic faux a un SILENCE. Tester la decision ne dit
  rien du site d'appel — lecon deja payee trois fois dans ce depot.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

from cinesort.app.jellyfin_sync import (
    RestoreResult,
    WatchedInfo,
    _normalize_path,
    restore_watched,
)
from cinesort.infra.jellyfin_client import JellyfinError

_OLD = r"C:\Films\movie.mkv"
_NEW = r"C:\Films\Movie (2020)\Movie (2020).mkv"


def _snapshot() -> Dict[str, WatchedInfo]:
    return {_normalize_path(_OLD): WatchedInfo(True, 3, "2026-01-15T20:00:00Z")}


def _operations() -> List[Dict[str, Any]]:
    return [{"op_type": "MOVE", "src_path": _OLD, "dst_path": _NEW, "undo_status": "PENDING"}]


def _restore(client: Any, *, max_retries: int = 3) -> RestoreResult:
    return restore_watched(
        client,
        "uid",
        _snapshot(),
        _operations(),
        initial_delay_s=0,
        retry_delay_s=0,
        max_retries=max_retries,
    )


@patch("cinesort.app.jellyfin_sync.time.sleep")
class ServeurInjoignableTests(unittest.TestCase):
    """Le cas du defaut : le serveur ne repond a aucune tentative."""

    def test_un_serveur_injoignable_n_est_pas_compte_en_non_retrouve(self, _sleep: Any) -> None:
        client = MagicMock()
        client.get_all_movies_from_all_libraries.side_effect = JellyfinError("Connexion refusee")

        result = _restore(client)

        self.assertEqual(result.unreachable, 1, "le film doit etre compte comme injoignable")
        self.assertEqual(result.not_found, 0, "il n'a PAS ete cherche : le serveur n'a jamais repondu")
        self.assertEqual(result.restored, 0)
        self.assertEqual(result.errors, 0, "aucun mark_played n'a echoue — il n'a pas ete tente")

    def test_la_raison_nomme_le_reseau_et_non_l_indexation(self, _sleep: Any) -> None:
        """Le detail est ce que lira un utilisateur qui cherche la cause."""
        client = MagicMock()
        client.get_all_movies_from_all_libraries.side_effect = OSError("timeout")

        result = _restore(client)

        details = [d for d in result.details if d.get("action") == "unreachable"]
        self.assertEqual(len(details), 1, f"details={result.details}")
        raison = str(details[0].get("reason", ""))
        self.assertIn("injoignable", raison)
        self.assertNotIn("re-indexation", raison, "la re-indexation n'est pas la cause ici")

    def test_les_trois_familles_d_exception_reseau_sont_traitees_pareil(self, _sleep: Any) -> None:
        """`OSError`, `ValueError` et `JellyfinError` sont les trois attrapees."""
        for exc in (OSError("reseau"), ValueError("json casse"), JellyfinError("503")):
            with self.subTest(exception=type(exc).__name__):
                client = MagicMock()
                client.get_all_movies_from_all_libraries.side_effect = exc
                self.assertEqual(_restore(client).unreachable, 1)


@patch("cinesort.app.jellyfin_sync.time.sleep")
class ContreTestsLeDiagnosticExistantEstPreserveTests(unittest.TestCase):
    """CONTRE-TESTS : ne pas remplacer un diagnostic faux par un autre."""

    def test_un_serveur_qui_repond_garde_le_verdict_non_retrouve(self, _sleep: Any) -> None:
        """Le cas legitime de `not_found` : le serveur repond, le film n'y est pas.

        C'est le scenario de `test_movie_not_found_after_retries` — il doit rester
        vert. Sans ce contre-test, un correctif qui basculerait TOUT en
        `unreachable` passerait.
        """
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = []

        result = _restore(client)

        self.assertEqual(result.not_found, 1)
        self.assertEqual(result.unreachable, 0, "le serveur a repondu : rien d'injoignable")

    def test_une_seule_reponse_suffit_a_refuser_le_verdict_injoignable(self, _sleep: Any) -> None:
        """Prudence deliberee : le OU porte sur TOUTES les tentatives.

        Un serveur qui repond puis se tait a bien ete joint. On ne le declare pas
        injoignable sur la foi des tentatives suivantes — sinon le verdict
        dependrait de l'instant ou le reseau a laché, pas de ce qu'on sait.
        """
        client = MagicMock()
        client.get_all_movies_from_all_libraries.side_effect = [
            [],  # tentative 1 : le serveur repond, bibliotheque sans le film
            JellyfinError("le serveur tombe"),
            JellyfinError("toujours absent"),
        ]

        result = _restore(client)

        self.assertEqual(result.not_found, 1, "le serveur a parle une fois : verdict inchange")
        self.assertEqual(result.unreachable, 0)

    def test_un_mark_played_en_echec_persistant_reste_une_erreur(self, _sleep: Any) -> None:
        """`errors` n'est pas absorbe : la branche `mark_failed` prime."""
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"id": "jf-1", "path": _NEW, "played": False, "play_count": 0, "last_played_date": ""},
        ]
        client.mark_played.return_value = False

        result = _restore(client)

        self.assertEqual(result.errors, 1)
        self.assertEqual(result.unreachable, 0)
        self.assertEqual(result.not_found, 0)

    def test_une_restauration_nominale_ne_compte_aucun_injoignable(self, _sleep: Any) -> None:
        client = MagicMock()
        client.get_all_movies_from_all_libraries.return_value = [
            {"id": "jf-1", "path": _NEW, "played": False, "play_count": 3, "last_played_date": ""},
        ]
        client.mark_played.return_value = True

        result = _restore(client)

        self.assertEqual(result.restored, 1)
        self.assertEqual(result.unreachable, 0)


class PayloadTests(unittest.TestCase):
    """Le compteur doit SORTIR de la fonction, sinon il n'informe personne."""

    def test_to_dict_porte_le_compteur(self) -> None:
        self.assertEqual(RestoreResult(unreachable=4).to_dict()["unreachable"], 4)

    def test_le_defaut_reste_zero(self) -> None:
        self.assertEqual(RestoreResult().unreachable, 0)


class LeSiteDAppelPrevientLUtilisateurTests(unittest.TestCase):
    """Sortir de `not_found` SANS message dedie creerait un silence.

    Avant ce correctif, ces films declenchaient le WARN « non retrouve(s) apres
    re-indexation ». Le diagnostic etait faux, mais il existait. Un correctif qui
    se contenterait de les deplacer dans un nouveau compteur les rendrait
    INVISIBLES — un echec silencieux la ou il y avait un echec mal nomme.
    """

    def _logs_pour(self, result: RestoreResult) -> List[Tuple[str, str]]:
        from cinesort.ui.api import apply_support

        logs: List[Tuple[str, str]] = []
        store = MagicMock()
        store.apply.list_apply_operations.return_value = []

        with (
            patch.object(apply_support, "_make_jellyfin_client", return_value=object()),
            patch.object(apply_support, "restore_watched", return_value=result),
        ):
            apply_support._restore_jellyfin_watched(
                MagicMock(),
                lambda level, msg: logs.append((level, msg)),
                {
                    "snapshot": _snapshot(),
                    "user_id": "uid",
                    "settings": {"jellyfin_url": "http://host"},
                },
                store,
                "batch-1",
            )
        return logs

    def test_l_utilisateur_est_prevenu_et_la_cause_designe_le_serveur(self) -> None:
        logs = self._logs_pour(RestoreResult(unreachable=7))

        warns = [msg for level, msg in logs if level == "WARN"]
        self.assertTrue(
            any("7" in msg and "injoignable" in msg.lower() for msg in warns),
            f"un serveur injoignable doit etre signale, logs={logs}",
        )

    def test_le_message_ne_parle_pas_de_re_indexation(self) -> None:
        """Contre-test du defaut d'origine : c'est la mauvaise piste."""
        warns = [msg for level, msg in self._logs_pour(RestoreResult(unreachable=7)) if level == "WARN"]
        self.assertTrue(warns, "au moins un WARN attendu")
        self.assertFalse(
            any("re-indexation" in msg.lower() for msg in warns),
            f"la re-indexation n'est pas la cause d'un serveur injoignable, warns={warns}",
        )

    def test_le_message_rassure_sur_les_fichiers(self) -> None:
        """Seuls les statuts « vu » sont perdus : l'apply disque, lui, a reussi."""
        warns = [msg for level, msg in self._logs_pour(RestoreResult(unreachable=1)) if level == "WARN"]
        self.assertTrue(
            any("rangés" in msg or "ranges" in msg for msg in warns),
            f"le message doit distinguer les fichiers des statuts, warns={warns}",
        )

    def test_aucun_injoignable_aucun_message(self) -> None:
        """CONTRE-TEST : le WARN ne se declenche pas sur une restauration saine."""
        logs = self._logs_pour(RestoreResult(restored=5))

        self.assertFalse(
            [msg for level, msg in logs if level == "WARN" and "injoignable" in msg.lower()],
            f"aucune alerte attendue sur un restore nominal, logs={logs}",
        )


if __name__ == "__main__":
    unittest.main()
