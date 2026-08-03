"""Issue #423 — la lecture d'un fichier statique est plafonnee.

Defaut d'origine : `_read_static_bytes` faisait `resolved.read_bytes()`, donc
chargeait le fichier entier en memoire avant d'ecrire la reponse. Aucune borne.

Portee reelle, non survendue : declencher ce cas suppose de pouvoir ecrire dans
`web/` sous le repertoire d'installation. Qui en est capable peut deja remplacer
un `.js` servi au navigateur, ce qui est strictement pire qu'un pic de memoire.
C'est de la defense en profondeur.

Les tests passent par un VRAI serveur REST et de VRAIES requetes HTTP : c'est le
chemin `_serve_dashboard_file` -> `_read_static_bytes` de production qui tourne,
pas un appel direct au helper.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest import mock

import cinesort.ui.api.cinesort_api as backend
from cinesort.infra import rest_server
from cinesort.infra.rest_server import RestApiServer
from tests._helpers import find_free_port as _find_free_port

# Plafond reduit pour le test : ecrire 32 Mio sur disque a chaque execution
# serait du gaspillage pur. La CONSTANTE est un reglage, pas le garde — le
# garde reste le code teste, et le muter fait bien rougir ces tests.
_TEST_CAP = 4096


class StaticReadCapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="cinesort_static_cap_")
        # `.resolve()` obligatoire, pas cosmetique : `_resolve_static_path`
        # compare `(root / relative).resolve()` a `root` via `relative_to()`, et
        # les DEUX productions de `_resolve_dashboard_root` renvoient un chemin
        # deja resolu. Un fixture qui fournirait un chemin non canonique ferait
        # echouer cette comparaison et rendrait TOUT en 403 — c'est ce qui est
        # arrive sur le runner Windows de la CI, ou `tempfile` rend un nom court
        # 8.3 (`C:\Users\RUNNER~1\...`) que `resolve()` reecrit en nom long.
        cls.web_root = Path(cls._tmp).resolve() / "dashboard"
        cls.web_root.mkdir(parents=True)
        assert cls.web_root == cls.web_root.resolve(), (
            "la racine servie doit etre canonique, comme celle que produit "
            "_resolve_dashboard_root — sinon les 403 masqueraient le plafond teste"
        )
        cls.small = cls.web_root / "petit.js"
        cls.small.write_bytes(b"// contenu normal\n" * 8)
        cls.big = cls.web_root / "enorme.js"
        cls.big.write_bytes(b"A" * (_TEST_CAP + 1))
        cls.pile = cls.web_root / "pile.js"
        cls.pile.write_bytes(b"B" * _TEST_CAP)

        cls._patch_root = mock.patch.object(rest_server, "_resolve_dashboard_root", return_value=cls.web_root)
        cls._patch_root.start()
        cls._patch_cap = mock.patch.object(rest_server, "_STATIC_MAX_BYTES", _TEST_CAP)
        cls._patch_cap.start()

        cls.state_dir = Path(cls._tmp) / "state"
        cls.state_dir.mkdir()
        cls.api = backend.CineSortApi()
        cls.api.settings.save_settings({"state_dir": str(cls.state_dir), "tmdb_enabled": False})
        cls.port = _find_free_port()
        cls.server = RestApiServer(cls.api, port=cls.port, token="token-de-test-statiques")
        cls.server.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls._patch_cap.stop()
        cls._patch_root.stop()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _get(self, path: str) -> tuple:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            return resp.status, resp.read()
        finally:
            with contextlib.suppress(OSError):
                conn.close()

    def test_fichier_normal_toujours_servi(self) -> None:
        """Controle positif : sans lui, un serveur casse rendrait les refus
        ci-dessous verts sans rien prouver."""
        status, body = self._get("/dashboard/petit.js")
        self.assertEqual(status, 200)
        self.assertIn(b"contenu normal", body)

    def test_fichier_au_dela_du_plafond_refuse(self) -> None:
        """ROUGE sans le correctif : le fichier etait charge puis servi en 200."""
        status, body = self._get("/dashboard/enorme.js")
        self.assertEqual(status, 500, "un statique hors plafond ne doit pas etre servi")
        self.assertNotIn(b"AAAA", body, "aucun octet du fichier refuse ne doit atteindre le client")

    def test_fichier_exactement_au_plafond_servi(self) -> None:
        """Verrouille le sens de l'inegalite : le plafond est inclusif."""
        status, body = self._get("/dashboard/pile.js")
        self.assertEqual(status, 200, "un fichier pile au plafond doit rester servi")
        self.assertEqual(len(body), _TEST_CAP)


class _RecordingStream:
    """Flux binaire reel, qui note simplement combien d'octets on lui demande."""

    def __init__(self, inner, journal: list) -> None:
        self._inner = inner
        self._journal = journal

    def read(self, amt: int | None = None) -> bytes:
        self._journal.append(amt)
        return self._inner.read() if amt is None else self._inner.read(amt)

    def __enter__(self) -> "_RecordingStream":
        return self

    def __exit__(self, *_args: object) -> None:
        self._inner.close()


class _RecordingPath:
    """Adaptateur autour d'un VRAI Path : le fichier, les octets et la lecture
    sont reels ; seule la taille demandee a chaque `read()` est observee."""

    def __init__(self, real: Path) -> None:
        self._real = real
        self.name = real.name
        self.amounts: list = []

    def open(self, mode: str = "rb"):
        return _RecordingStream(self._real.open(mode), self.amounts)


class _HandlerProbe(rest_server._CineSortHandler):
    """Instance de handler sans socket : seul `_read_static_bytes` est exerce,
    et c'est bien le code de production du handler qui tourne."""

    def __init__(self) -> None:  # noqa: D107 - on court-circuite le cycle HTTP
        self.responded: tuple | None = None

    def _respond_json(self, status: int, payload: dict) -> None:  # type: ignore[override]
        self.responded = (status, payload)


class AllocationIsBoundedTests(unittest.TestCase):
    """Mesure ce qui est REELLEMENT demande au disque, pas seulement le statut.

    Sans ce test, remplacer `read(_STATIC_MAX_BYTES + 1)` par `read()` laisse
    toute la batterie verte : le controle de longueur qui suit refuse encore le
    fichier, mais apres l'avoir entierement charge en memoire. C'est exactement
    le faux garde que ce correctif evite.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_static_alloc_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.big = Path(self._tmp) / "enorme.js"
        self.big.write_bytes(b"C" * (_TEST_CAP * 64))
        self._patch_cap = mock.patch.object(rest_server, "_STATIC_MAX_BYTES", _TEST_CAP)
        self._patch_cap.start()
        self.addCleanup(self._patch_cap.stop)

    def test_la_lecture_ne_demande_jamais_plus_que_le_plafond(self) -> None:
        probe = _HandlerProbe()
        spy = _RecordingPath(self.big)

        result = probe._read_static_bytes(spy, "Test")

        self.assertIsNone(result, "un fichier hors plafond ne doit rien rendre a l'appelant")
        self.assertEqual(probe.responded[0], 500)  # type: ignore[index]
        self.assertTrue(spy.amounts, "aucune lecture n'a eu lieu : le test ne prouverait rien")
        self.assertNotIn(
            None,
            spy.amounts,
            "un read() sans argument lit jusqu'a EOF : la borne n'est pas portee par la lecture",
        )
        self.assertLessEqual(
            max(spy.amounts),
            _TEST_CAP + 1,
            f"lecture de {max(spy.amounts)} octets demandee alors que le plafond est {_TEST_CAP}",
        )

    def test_un_fichier_normal_est_lu_en_entier(self) -> None:
        petit = Path(self._tmp) / "petit.js"
        petit.write_bytes(b"D" * 128)
        probe = _HandlerProbe()
        spy = _RecordingPath(petit)

        result = probe._read_static_bytes(spy, "Test")

        self.assertEqual(result, b"D" * 128, "la borne ne doit pas tronquer un fichier legitime")
        self.assertIsNone(probe.responded, "aucune reponse d'erreur ne doit etre emise")


class StaticCapValueTests(unittest.TestCase):
    """Le plafond par defaut ne doit pas devenir une limite fonctionnelle."""

    def test_plafond_par_defaut_couvre_tous_les_statiques_livres(self) -> None:
        web = Path(__file__).resolve().parents[1] / "web"
        tailles = [(p.stat().st_size, p) for p in web.rglob("*") if p.is_file()]
        self.assertTrue(tailles, "arborescence web/ introuvable : le test ne prouverait rien")
        plus_gros, chemin = max(tailles)
        self.assertLess(
            plus_gros,
            rest_server._STATIC_MAX_BYTES,
            f"{chemin.name} ({plus_gros} octets) depasse le plafond "
            f"{rest_server._STATIC_MAX_BYTES} : le dashboard serait casse",
        )
        self.assertGreater(
            rest_server._STATIC_MAX_BYTES,
            plus_gros * 10,
            "garder au moins un ordre de grandeur de marge au-dessus du plus gros asset livre",
        )


if __name__ == "__main__":
    unittest.main()
