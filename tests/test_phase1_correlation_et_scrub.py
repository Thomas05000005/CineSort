"""Phase 1 de la boite noire — corréler, et ne pas fuiter en corrélant.

Deux défauts trouvés par la cartographie de l'instrumentation, tous deux sur des
chemins qui existent depuis longtemps et que personne ne regardait.

**1. L'apply n'estampillait pas son `run_id`.** `apply_changes` s'exécute
SYNCHRONIQUEMENT dans le thread de la requête REST : il ne passe donc pas par
`job_runner._run_worker`, l'un des quatre seuls sites du dépôt à poser la
ContextVar. Toutes les lignes de `cinesort.log` émises par l'opération la plus
destructive du produit sortaient en `[run=- req=...]` — rattachables à la
requête, pas au run. Le `run_id` était pourtant disponible en paramètre.

**2. `debug_tmdb.log` n'était pas scrubbé.** Ses 16 sites d'appel sont TOUS des
chemins d'échec du type `... error={exc}`, et `exc` est une exception de client
HTTP dont la représentation porte l'URL complète — `?api_key=` compris. Le
fichier ne passe par aucun filtre stdlib : la clé TMDb de l'utilisateur était
écrite en clair sur son disque (CWE-532).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

from cinesort.infra import log_context
from cinesort.infra.tmdb_client import TmdbClient


class L_APPLY_ESTAMPILLE_SON_RUN_ID_Tests(unittest.TestCase):
    """Le `run_id` doit être posé PENDANT l'apply, et RESTAURÉ après."""

    def _apply(self, run_id: str, observateur) -> Any:
        from cinesort.ui.api import apply_support

        # On coupe juste après la pose : ce test porte sur la ContextVar, pas
        # sur l'apply. `_apply_slot_guard` est le premier appel du corps.
        api = mock.Mock()
        api._apply_slot_guard.side_effect = lambda _rid: observateur()
        return apply_support.apply_changes(
            api,
            run_id,
            {},
            dry_run=True,
            quarantine_unapproved=False,
            cleanup_scope_label=lambda s: s,
            cleanup_status_label=lambda *a, **k: "",
            cleanup_reason_label=lambda s: s,
        )

    def test_le_run_id_est_pose_pendant_l_apply(self):
        """ROUGE avant le correctif : la ContextVar valait None, donc chaque
        ligne de log de l'apply sortait en `[run=-]`."""
        vu: Dict[str, Any] = {}

        class _Sonde:
            def __enter__(_s):
                vu["pendant"] = log_context.get_run_id()
                raise RuntimeError("stop")

            def __exit__(_s, *a):
                return False

        with self.assertRaises(RuntimeError):
            self._apply("20260819_120000_000_abc", lambda: _Sonde())
        self.assertEqual(
            vu.get("pendant"),
            "20260819_120000_000_abc",
            "le run_id doit etre lisible depuis le contexte PENDANT l'apply",
        )

    def test_le_run_id_est_RESTAURE_apres_l_apply(self):
        """Contre-test : le thread REST sert d'autres requêtes ensuite.

        Laisser la ContextVar posée estampillerait les requêtes suivantes avec
        un run qui n'est plus le leur — un correctif qui en créerait un autre.
        """

        class _Sonde:
            def __enter__(_s):
                raise RuntimeError("stop")

            def __exit__(_s, *a):
                return False

        avant = log_context.get_run_id()
        with self.assertRaises(RuntimeError):
            self._apply("20260819_120000_000_abc", lambda: _Sonde())
        self.assertEqual(
            log_context.get_run_id(),
            avant,
            "la ContextVar doit revenir a son etat d'avant, meme sur exception",
        )


class DEBUG_TMDB_NE_FUITE_PAS_LA_CLE_Tests(unittest.TestCase):
    """Le journal TMDb ne doit jamais porter une clé d'API en clair."""

    def _ecrire(self, message: str, tmp: Path) -> str:
        # Construction MINIMALE volontaire : `_debug` n'a besoin que de
        # `cache_path`, et un `TmdbClient` complet exigerait une configuration,
        # un cache et un disjoncteur qui n'ont rien a voir avec ce qu'on mesure.
        #
        # Sourcery signale le couplage a la structure interne. Il est reel, mais
        # il echoue BRUYAMMENT : si `_debug` se met a lire un autre attribut,
        # `object.__new__` le laisse absent et le test leve `AttributeError`. Un
        # client complet, lui, fournirait silencieusement toutes les valeurs par
        # defaut et masquerait le changement. Ici, la fragilite est le signal.
        client = object.__new__(TmdbClient)
        client.cache_path = tmp / "tmdb_cache.json"
        with mock.patch.dict("os.environ", {"CINESORT_DEBUG": "1"}, clear=False):
            client._debug(message)
        journal = tmp / "debug_tmdb.log"
        return journal.read_text(encoding="utf-8") if journal.exists() else ""

    def test_une_url_avec_api_key_est_redigee(self):
        """ROUGE avant le correctif : la clé partait en clair sur le disque.

        Le message reproduit la forme RÉELLE des 16 sites d'appel — une
        exception de `requests` dont le `str()` porte l'URL complète.
        """
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="cinesort_tmdbdbg_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        contenu = self._ecrire(
            "search_movie warning query=inception "
            "error=HTTPError('401 for url: https://api.themoviedb.org/3/search/movie"
            "?api_key=CLE_SECRETE_DE_L_UTILISATEUR&query=inception')",
            tmp,
        )
        self.assertNotIn("CLE_SECRETE_DE_L_UTILISATEUR", contenu, "la cle TMDb a fuite en clair")
        self.assertIn("REDACTED", contenu, "le scrubber doit avoir laisse sa marque")

    def test_le_reste_du_message_est_PRESERVE(self):
        """Contre-test : scrubber trop large = journal inutilisable.

        Ce qui fait la valeur de ce fichier, c'est de dire QUELLE requete a
        echoue. Si le scrub emporte la query et le code d'erreur, on remplace
        une fuite par une cecite.
        """
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="cinesort_tmdbdbg_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        contenu = self._ecrire(
            "search_movie warning query=inception "
            "error=HTTPError('401 for url: https://api.themoviedb.org/3/search/movie"
            "?api_key=CLE_SECRETE_DE_L_UTILISATEUR&query=inception')",
            tmp,
        )
        self.assertIn("search_movie", contenu)
        self.assertIn("query=inception", contenu)
        self.assertIn("401", contenu)


if __name__ == "__main__":
    unittest.main()
