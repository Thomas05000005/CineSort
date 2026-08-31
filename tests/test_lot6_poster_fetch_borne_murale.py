"""LOT 6 (A) — `FETCH_TIMEOUT_S` ne borne PAS la duree de `fetch_and_cache`.

`GET /api/poster` s'execute dans un thread du serveur REST
(`rest_server.py`, handler `/api/poster`). La constante `FETCH_TIMEOUT_S = 10.0`
laisse croire que l'aller-retour TMDb y est borne a dix secondes. Elle ne borne
en realite qu'UNE LECTURE DE SOCKET :

  - `requests` applique ce timeout par tentative, et la session du proxy est
    construite avec `max_attempts=2` — le backoff s'y ajoute encore ;
  - surtout, la boucle `iter_content` n'a AUCUNE borne murale. Un pair qui
    envoie un chunk toutes les 9 s ne declenche jamais le timeout de lecture :
    chaque lecture individuelle reste sous les 10 s, et la boucle ne s'arrete
    qu'au plafond de TAILLE (`MAX_POSTER_BYTES`, 5 Mio). A 8 Kio par chunk cela
    fait 640 lectures, soit plus d'une heure et demie de thread retenu pour une
    seule jaquette — sans qu'aucun timeout n'ait expire.

Le test simule cette horloge : le pair repond, sans jamais etre en retard au
sens du timeout par lecture. On mesure la duree MURALE consommee par
`fetch_and_cache`, pas le nombre d'octets.

Le correctif ajoute `STREAM_BUDGET_S`, une echeance murale sur la lecture du
corps, et documente la borne reelle de l'appel complet.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

from cinesort.infra.integrations import poster_proxy


class _HorlogeSimulee:
    """Horloge monotone pilotee par le test (aucune attente reelle)."""

    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def avancer(self, secondes: float) -> None:
        self.t += secondes


class _ReponseGoutteAGoutte:
    """Pair qui repond regulierement, mais lentement — jamais en timeout.

    Chaque chunk arrive apres `pas` secondes simulees : sous `FETCH_TIMEOUT_S`,
    donc aucune lecture n'expire jamais.
    """

    def __init__(self, horloge: _HorlogeSimulee, pas: float = 9.0) -> None:
        self.status_code = 200
        self.headers = {"Content-Type": "image/jpeg"}
        self._horloge = horloge
        self._pas = pas
        self.chunks_livres = 0
        self.ferme = False

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        while True:
            self._horloge.avancer(self._pas)
            self.chunks_livres += 1
            yield b"\xff\xd8\xff\xe0" + b"x" * (chunk_size - 4)

    def close(self) -> None:
        self.ferme = True


class _ReponseImmediate:
    def __init__(self, corps: bytes) -> None:
        self.status_code = 200
        self.headers = {"Content-Type": "image/jpeg"}
        self._corps = corps

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        yield self._corps

    def close(self) -> None:
        return None


class _FakeTmdbClient:
    def get_movie_poster_path(self, movie_id: int, force_refresh: bool = False) -> str:  # noqa: ARG002
        return "/abc123.jpg"


class _BaseFetch(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="lot6_borne_")
        self.cache_root = Path(self._tmp.name) / "posters"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.horloge = _HorlogeSimulee()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _fetch(self, reponse: Any) -> tuple:
        session = mock.MagicMock()
        session.get.return_value = reponse
        with (
            mock.patch.object(poster_proxy, "time", self.horloge),
            mock.patch.object(poster_proxy, "_get_session", return_value=session),
        ):
            return poster_proxy.fetch_and_cache(_FakeTmdbClient(), self.cache_root, 550, "w342")


class LaLectureDuCorpsEstBorneeDansLeTempsTests(_BaseFetch):
    #: Plafond du test : large devant la borne visee, minuscule devant l'heure
    #: et demie que consomme la version non bornee.
    PLAFOND_MURAL_S = 120.0

    def test_un_pair_lent_ne_retient_pas_le_thread_du_serveur(self) -> None:
        reponse = _ReponseGoutteAGoutte(self.horloge, pas=9.0)

        cache_file, _content_type, error_code = self._fetch(reponse)

        self.assertLessEqual(
            self.horloge.t,
            self.PLAFOND_MURAL_S,
            f"fetch_and_cache a retenu le thread {self.horloge.t:.0f} s "
            f"({reponse.chunks_livres} lectures) alors que FETCH_TIMEOUT_S vaut "
            f"{poster_proxy.FETCH_TIMEOUT_S} s",
        )
        self.assertIsNone(cache_file, "un fetch abandonne ne doit rien laisser en cache")
        self.assertEqual(error_code, poster_proxy.ERR_OFFLINE)
        self.assertTrue(reponse.ferme, "la connexion abandonnee n'a pas ete fermee")

    def test_temoin_une_reponse_normale_reste_servie(self) -> None:
        """Sans lui, « abandonner tout de suite » passerait aussi."""
        cache_file, content_type, error_code = self._fetch(_ReponseImmediate(b"\xff\xd8\xff\xe0JAQUETTE"))

        self.assertIsNone(error_code)
        self.assertEqual(content_type, "image/jpeg")
        assert cache_file is not None
        self.assertEqual(cache_file.read_bytes(), b"\xff\xd8\xff\xe0JAQUETTE")


class LaConstanteDeBudgetEstCoherenteTests(unittest.TestCase):
    """La borne annoncee doit rester atteignable : plusieurs chunks avant l'abandon.

    Un budget inferieur au timeout d'une seule lecture rendrait la borne
    inoperante (on abandonnerait avant le premier octet).
    """

    def test_le_budget_de_lecture_depasse_le_timeout_d_une_lecture(self) -> None:
        self.assertGreater(poster_proxy.STREAM_BUDGET_S, poster_proxy.FETCH_TIMEOUT_S)


if __name__ == "__main__":
    unittest.main()
