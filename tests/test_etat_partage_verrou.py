"""Etat partage mute sans protection — issues #620 (cache OMDb) et #514 (timeout socket).

Deux defauts de la meme famille : du code prend une decision sur un etat que
quelqu'un d'autre peut changer sous ses pieds.

#620 — `OmdbClient._save_cache_atomic` serialisait `self._cache` sans prendre
       `self._lock`, alors que `_cache_set` le mute SOUS ce verrou. Un
       `json.dumps` qui itere un dict en cours de mutation leve
       `RuntimeError: dictionary changed size during iteration` — une
       RuntimeError, donc PAS rattrapee par le `except (OSError,
       PermissionError, ValueError)` du bloc : elle remonte a l'appelant.

#514 — `auto_install._socket_timeout` appelait `socket.setdefaulttimeout(120)`,
       c'est-a-dire le DEFAUT GLOBAL du processus. Pendant les 120 s du
       telechargement, tout socket cree par un autre thread (serveur REST,
       clients TMDb/Jellyfin/Plex, watcher) heritait de ce timeout sans l'avoir
       demande — et `auto_install_probe_tools` est declenchable a distance par
       la facade REST runtime.
"""

from __future__ import annotations

import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Callable, List, Optional
from unittest import mock

import cinesort.infra.probe.auto_install as auto_install
from cinesort.infra.omdb_client import OmdbClient
from cinesort.infra.probe.auto_install import _download_bounded

# ---------------------------------------------------------------------------
# #620 — cache OMDb serialise sans verrou
# ---------------------------------------------------------------------------


class OmdbCacheSnapshotSousVerrouTests(unittest.TestCase):
    """`_save_cache_atomic` doit prendre `self._lock` pour lire `self._cache`."""

    def _client(self, tmp: str) -> OmdbClient:
        return OmdbClient(api_key="k", cache_path=Path(tmp) / "omdb_cache.json")

    def test_la_serialisation_du_cache_attend_le_verrou(self) -> None:
        """Tant qu'un ecrivain tient le verrou, la sauvegarde ne peut pas lire le dict.

        Sans le correctif, `json.dumps(self._cache, ...)` part immediatement :
        c'est exactement la fenetre pendant laquelle un `_cache_set` concurrent
        fait grossir le dict en cours d'iteration.
        """
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp)
            try:
                for i in range(50):
                    client._cache[f"seed{i}"] = {"_ts": time.time(), "data": {"i": i}}

                verrou_tenu = threading.Event()
                liberer = threading.Event()
                sauvegarde_finie = threading.Event()
                erreurs: List[BaseException] = []

                def _ecrivain() -> None:
                    try:
                        with client._lock:
                            verrou_tenu.set()
                            # Ce que fait `_cache_set` en concurrence : muter le
                            # dict, sous le verrou, pendant que la sauvegarde
                            # voudrait le lire.
                            for i in range(200):
                                client._cache[f"live{i}"] = {"_ts": time.time(), "data": {"i": i}}
                            liberer.wait(10)
                    except BaseException as exc:  # pragma: no cover - diagnostic
                        erreurs.append(exc)

                def _sauveur() -> None:
                    try:
                        client._save_cache_atomic()
                        sauvegarde_finie.set()
                    except BaseException as exc:  # pragma: no cover - diagnostic
                        erreurs.append(exc)

                ecrivain = threading.Thread(target=_ecrivain, daemon=True)
                ecrivain.start()
                self.assertTrue(verrou_tenu.wait(10), "l'ecrivain n'a pas pris le verrou")

                sauveur = threading.Thread(target=_sauveur, daemon=True)
                sauveur.start()
                self.assertFalse(
                    sauvegarde_finie.wait(1.0),
                    "_save_cache_atomic a serialise le cache SANS attendre self._lock",
                )

                liberer.set()
                ecrivain.join(10)
                sauveur.join(10)
                self.assertEqual(erreurs, [], f"exception dans un thread : {erreurs}")
                self.assertTrue(sauvegarde_finie.is_set(), "la sauvegarde n'a jamais abouti")

                ecrit = json.loads((Path(tmp) / "omdb_cache.json").read_text(encoding="utf-8"))
                self.assertEqual(len(ecrit), 250, "le snapshot doit contenir les 250 entrees")
            finally:
                client.close()

    def test_l_ecriture_disque_a_lieu_hors_du_verrou(self) -> None:
        """Le verrou ne couvre que le snapshot, jamais le write + fsync + replace.

        Le tenir pendant l'I/O transformerait la correction du #620 en point de
        contention : un fsync lent (disque reseau, antivirus) bloquerait tous
        les threads qui alimentent le cache.
        """
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client(tmp)
            try:
                client._cache["seed"] = {"_ts": time.time(), "data": {"x": 1}}
                verrou_libre_pendant_fsync: List[bool] = []
                vrai_fsync = os.fsync

                def _fsync_espion(fd: int) -> None:
                    libre = client._lock.acquire(blocking=False)
                    verrou_libre_pendant_fsync.append(libre)
                    if libre:
                        client._lock.release()
                    return vrai_fsync(fd)

                with mock.patch("cinesort.infra.omdb_client.os.fsync", _fsync_espion):
                    client._save_cache_atomic()

                self.assertTrue(verrou_libre_pendant_fsync, "fsync n'a pas ete appele")
                self.assertTrue(
                    all(verrou_libre_pendant_fsync),
                    "self._lock est tenu pendant le fsync : l'I/O disque doit rester hors du verrou",
                )
            finally:
                client.close()


# ---------------------------------------------------------------------------
# #514 — timeout socket global pendant l'auto-install
# ---------------------------------------------------------------------------


class _FausseReponseHttp(io.BytesIO):
    """Reponse minimale facon `http.client.HTTPResponse` : lecture + `.headers`."""

    def __init__(self, payload: bytes, headers: Optional[dict] = None) -> None:
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))} if headers is None else headers


def _urlopen_espion(payload: bytes, journal: List[dict], headers: Optional[dict] = None) -> Callable[..., Any]:
    """Faux `urlopen` : enregistre le timeout recu ET le defaut socket global observe.

    L'observation se fait DANS l'appel, c'est-a-dire a l'instant precis ou la
    connexion serait ouverte : c'est la fenetre pendant laquelle le defaut
    global etait modifie.
    """

    def _open(request: Any, timeout: Any = None, **kwargs: Any) -> _FausseReponseHttp:
        journal.append(
            {
                "timeout": timeout,
                "defaut_socket": socket.getdefaulttimeout(),
                "url": getattr(request, "full_url", request),
            }
        )
        return _FausseReponseHttp(payload, headers)

    return _open


class TimeoutTelechargementLocalTests(unittest.TestCase):
    """Le timeout du telechargement doit etre porte par la connexion, pas par le processus."""

    def test_le_defaut_socket_global_n_est_pas_modifie_pendant_le_telechargement(self) -> None:
        """#514 — aucun autre thread ne doit heriter du timeout de l'auto-install."""
        journal: List[dict] = []
        avant = socket.getdefaulttimeout()
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "x.zip")
            with mock.patch.object(auto_install, "urlopen", _urlopen_espion(b"payload-zip", journal)):
                _download_bounded("https://example.com/x.zip", dest, label="x.zip")
            self.assertEqual(Path(dest).read_bytes(), b"payload-zip")
        apres = socket.getdefaulttimeout()

        self.assertEqual(len(journal), 1, journal)
        self.assertEqual(
            journal[0]["defaut_socket"],
            avant,
            "socket.setdefaulttimeout() a ete appele : le timeout fuit vers tous les autres threads",
        )
        self.assertEqual(apres, avant, "le defaut socket global a fuite hors du telechargement")

    def test_le_timeout_est_passe_a_la_connexion(self) -> None:
        """La borne existe toujours — elle est simplement locale a cette connexion."""
        journal: List[dict] = []
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "x.zip")
            with mock.patch.object(auto_install, "urlopen", _urlopen_espion(b"payload-zip", journal)):
                _download_bounded("https://example.com/x.zip", dest, label="x.zip")

        self.assertEqual(len(journal), 1, journal)
        self.assertEqual(
            journal[0]["timeout"],
            auto_install._DOWNLOAD_TIMEOUT_S,
            "le telechargement doit etre borne par urlopen(timeout=...), sinon un serveur muet fait hang l'install",
        )

    def test_le_plafond_de_taille_coupe_toujours_pendant_le_transfert(self) -> None:
        """Garde-fou : le changement de transport ne doit pas desarmer la borne #734."""
        journal: List[dict] = []
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "big.zip")
            gros = b"\0" * 20_000
            with (
                mock.patch.object(auto_install, "_MAX_ARCHIVE_BYTES", 4096),
                mock.patch.object(auto_install, "urlopen", _urlopen_espion(gros, journal)),
            ):
                with self.assertRaises(auto_install.IntegrityError) as ctx:
                    _download_bounded("https://example.com/big.zip", dest, label="big.zip")
            self.assertIn("taille annoncee", str(ctx.exception))
            self.assertFalse(os.path.exists(dest), "aucun fragment d'archive ne doit survivre a l'abandon")

    def test_sans_taille_annoncee_la_coupure_vient_du_volume_recu_et_ne_laisse_rien(self) -> None:
        """Serveur sans `Content-Length` : la borne tombe pendant le transfert.

        C'est le seul chemin ou un fragment d'archive existe deja sur disque au
        moment de l'abandon — il doit etre efface (fail-closed : rien de
        reutilisable ne survit a un refus).
        """
        journal: List[dict] = []
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "big.zip")
            gros = b"\0" * (auto_install._DOWNLOAD_BLOCK_BYTES * 3)
            with (
                mock.patch.object(auto_install, "_MAX_ARCHIVE_BYTES", 4096),
                mock.patch.object(auto_install, "urlopen", _urlopen_espion(gros, journal, headers={})),
            ):
                with self.assertRaises(auto_install.IntegrityError) as ctx:
                    _download_bounded("https://example.com/big.zip", dest, label="big.zip")
            self.assertIn("interrompu", str(ctx.exception))
            self.assertFalse(os.path.exists(dest), "le fragment deja ecrit doit etre efface")
            self.assertEqual(sorted(os.listdir(tmp)), [], "aucun residu dans le dossier de travail")


if __name__ == "__main__":
    unittest.main()
