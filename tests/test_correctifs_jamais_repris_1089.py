"""Issue #1089 — trois correctifs qui n'avaient jamais ete repris dans `main`.

Le rangement du 2026-08-15 a montre que ce depot fusionne en SQUASH : le SHA
d'une branche n'entre jamais dans `main`, donc `git branch --merged` et
`git cherry` la declarent non fusionnee meme quand son travail est livre. Sur
105 branches, 104 presentaient cette signature. Le controle qui tranche est le
CONTENU — et pour un correctif, sa capacite a s'ANNULER sur `main`
(`git apply --check -R`).

Quatre branches portaient un correctif encore absent. Trois sont reprises ici,
chacune avec le test qui manquait ; la quatrieme (`radarr-sync-tmdb-defensif`)
elargit ce qui est ACCEPTE en entree et demande un arbitrage produit, donc elle
reste documentee dans #1089 plutot que reprise a l'aveugle.

Tous les tests ci-dessous eprouvent un COMPORTEMENT : ils appellent la fonction
de production et lisent ce qu'elle fait. `CLAUDE.md` proscrit les tests qui
comparent une chaine de code source — ils tombent quand le code s'ameliore et
ne detectent rien quand il casse.
"""

from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest import mock

from cinesort.app import plugin_hooks
from cinesort.domain.core import find_best_nfo_for_video


class PluginEnvNeFuitePasLesCheminsPythonTests(unittest.TestCase):
    """`sec/audit-plugin-env-pythonpath-2026-05-25`.

    Les plugins sont des scripts TIERS de l'utilisateur, lances en processus
    separe. Leur transmettre `PYTHONPATH` / `PYTHONHOME` leur livrait le chemin
    d'installation — de quoi deduire l'architecture et cibler des bibliotheques
    locales. Ce n'etait pas necessaire : la commande est
    `[sys.executable, plugin]`, et un interpreteur se localise seul. Pire,
    `PYTHONHOME` herite d'un parent mal configure peut CASSER un venv.

    On lit l'environnement REELLEMENT transmis au sous-processus, capture au
    site d'appel de `tracked_run`.
    """

    def _env_transmis(self, tmp: Path) -> dict:
        script = tmp / "on_scan_done.py"
        script.write_text("pass\n", encoding="utf-8")
        capture: dict = {}

        def _faux_run(cmd, **kwargs):  # noqa: ANN001, ARG001
            capture.update(kwargs.get("env") or {})
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(plugin_hooks, "tracked_run", _faux_run):
            plugin_hooks._run_plugin(script, "scan_done", {"run_id": "r1"}, timeout_s=5)
        return capture

    def test_ni_pythonpath_ni_pythonhome_ne_sont_transmis(self):
        """ROUGE avant le correctif : les deux figuraient dans le whitelist,
        donc dans l'environnement du script tiers."""
        import tempfile

        with tempfile.TemporaryDirectory(prefix="cinesort_plug_") as td:
            with mock.patch.dict(
                "os.environ",
                {"PYTHONPATH": "C:/secret/lib", "PYTHONHOME": "C:/secret/py"},
                clear=False,
            ):
                env = self._env_transmis(Path(td))
        self.assertNotIn("PYTHONPATH", env, "revele le chemin d'installation au plugin")
        self.assertNotIn("PYTHONHOME", env, "revele le chemin d'installation au plugin")

    def test_ce_qui_est_necessaire_reste_transmis(self):
        """Contre-test : retirer trop remplacerait un defaut par un autre.

        Les plugins recoivent du JSON UTF-8 sur stdin — sans `PYTHONIOENCODING`
        ils le decodent en cp1252 sur un poste Windows francais.
        """
        import tempfile

        with tempfile.TemporaryDirectory(prefix="cinesort_plug_") as td:
            env = self._env_transmis(Path(td))
        self.assertEqual(env.get("PYTHONIOENCODING"), "utf-8")
        self.assertIn("PATH", env, "sans PATH, aucun interpreteur ni outil n'est trouvable")
        self.assertEqual(env.get("CINESORT_RUN_ID"), "r1", "le contexte metier doit passer")


class CorsWildcardSurLanAvertitTests(unittest.TestCase):
    """`sec/audit-cors-warning-2026-05-26`.

    `CORS='*'` combine a `host=0.0.0.0` laisse toute origine emettre des
    requetes. L'authentification Bearer reste la barriere — ce n'est donc pas
    une faille, mais une combinaison que l'administrateur doit CHOISIR en
    connaissance de cause. Elle etait jusqu'ici silencieuse.

    On appelle `RestApiServer.start()` en neutralisant TOUT ce qui ouvre une
    socket ou demarre un thread : demarrer un vrai serveur lancerait le cron de
    purge TTL, qui agit sur la bibliotheque REELLE (cf. CLAUDE.md).
    """

    def _avertissements(self, cors_origin: str, host: str) -> list[str]:
        from cinesort.infra import rest_server

        vus: list[str] = []

        def _capturer(msg, *args, **kwargs):  # noqa: ANN001, ARG001
            try:
                vus.append(str(msg) % args if args else str(msg))
            except TypeError:
                vus.append(str(msg))

        srv = object.__new__(rest_server.RestApiServer)
        srv._cors_origin = cors_origin
        srv._port = 8642
        srv._host = host
        srv._api = mock.Mock()
        srv._server = None
        srv._thread = None  # -> is_running False, on entre bien dans start()
        srv._token = "jeton-de-test"  # sinon un AUTRE avertissement part
        # `_lan_demoted` court-circuite TOUTE la branche LAN : si la retrogradation
        # a eu lieu, l'avertissement CORS ne doit pas partir non plus.
        srv._lan_demoted = False
        srv._lan_demotion_reason = ""

        # Le corps de `start()` au-dela de l'avertissement monte un serveur HTTP
        # et un thread : on le laisse echouer et on ne garde que le journal.
        with (
            mock.patch.object(rest_server.logger, "warning", _capturer),
            mock.patch.object(rest_server, "_get_api_methods", side_effect=RuntimeError("stop")),
        ):
            with self.assertRaises(RuntimeError):
                rest_server.RestApiServer.start(srv)
        return [m for m in vus if "CORS" in m]

    def test_le_wildcard_sur_le_lan_declenche_l_avertissement(self):
        """ROUGE avant le correctif : la combinaison etait silencieuse."""
        vus = self._avertissements("*", "0.0.0.0")  # noqa: S104 - c'est le cas teste
        self.assertEqual(len(vus), 1, f"un avertissement CORS attendu, vu : {vus}")
        self.assertIn(
            "rest_api_cors_origin",
            vus[0],
            "le message doit nommer le REGLAGE qui permet de restreindre, sinon "
            "l'admin sait qu'il y a un risque mais pas quoi faire",
        )
        self.assertIn("8642", vus[0], "le message doit porter le port reel")

    def test_pas_d_avertissement_quand_l_origine_est_restreinte(self):
        """Contre-test : un CORS explicite ne doit rien declencher, sinon
        l'avertissement devient du bruit que l'admin apprend a ignorer."""
        self.assertEqual(self._avertissements("http://192.168.1.50:8642", "0.0.0.0"), [])  # noqa: S104

    def test_pas_d_avertissement_en_localhost(self):
        """Le wildcard sur la boucle locale n'expose rien au LAN."""
        self.assertEqual(self._avertissements("*", "127.0.0.1"), [])


class FindBestNfoRendLeMemeResultatTests(unittest.TestCase):
    """`fix/audit-2026-05-30-core-min-vs-sorted`.

    `sorted(xs, key=k)[0]` trie N elements pour n'en garder qu'un ; `min(xs,
    key=k)` fait le meme choix en un seul passage. Le correctif est une
    optimisation — donc ce qu'il faut prouver n'est PAS un gain, c'est que le
    RESULTAT est IDENTIQUE, y compris sur les egalites, ou `min` et `sorted`
    rendent tous deux le PREMIER element de valeur minimale.
    """

    def setUp(self) -> None:
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        import tempfile

        self._td = tempfile.mkdtemp(prefix="cinesort_nfo_")
        self.dossier = Path(self._td)
        self.addCleanup(lambda: __import__("shutil").rmtree(self._td, ignore_errors=True))

    def _creer(self, *noms: str) -> None:
        for n in noms:
            (self.dossier / n).write_text("<movie/>", encoding="utf-8")

    def test_le_nfo_du_film_gagne_sur_les_autres(self):
        video = self.dossier / "Interstellar.2014.mkv"
        video.write_bytes(b"x" * 32)
        self._creer("Interstellar.2014.nfo", "aaa.nfo")
        self.assertEqual(
            find_best_nfo_for_video(self.dossier, video),
            self.dossier / "Interstellar.2014.nfo",
            "le nfo homonyme de la video prime sur l'ordre alphabetique",
        )

    def test_a_defaut_le_premier_minimum_alphabetique_gagne(self):
        """C'est le comportement de `sorted(...)[0]` que `min(...)` doit
        reproduire : minuscules, et premier en cas d'egalite."""
        video = self.dossier / "Film.mkv"
        video.write_bytes(b"x" * 32)
        self._creer("Zeta.nfo", "alpha.nfo", "Beta.nfo")
        self.assertEqual(
            find_best_nfo_for_video(self.dossier, video),
            self.dossier / "alpha.nfo",
            "la comparaison doit rester insensible a la casse",
        )

    def test_aucun_nfo_rend_none(self):
        video = self.dossier / "Film.mkv"
        video.write_bytes(b"x" * 32)
        self.assertIsNone(find_best_nfo_for_video(self.dossier, video))


if __name__ == "__main__":
    unittest.main()
