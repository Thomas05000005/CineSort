"""Securite de l'auto-installation des outils probe, exercee par la FACADE DE PRODUCTION.

Issues #466 (CWE-494 : binaire telecharge puis EXECUTE sans verification
effective) et #734 (CWE-409 : decompression non bornee, zip bomb).

Tous les tests de ce fichier passent par
`CineSortApi().runtime.auto_install_probe_tools()`, c'est-a-dire le point
d'entree reellement appele par le bouton « Installer automatiquement » du
dashboard (`web/dashboard/views/parametres.js` -> POST
`runtime/auto_install_probe_tools`). Aucune fonction interne n'est appelee
directement : le trou de la derniere campagne etait precisement une batterie qui
prouvait un comportement sur un chemin que la production n'empruntait pas.

Seul le transport reseau est simule (`urlretrieve`), comme le ferait un
attaquant en MITM ou un miroir compromis : tout le reste — resolution de
l'empreinte, verification, bornes, ecriture disque, remontee d'erreur a
l'UI — est le code de production.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional
from unittest import mock

import cinesort.infra.probe.auto_install as auto_install
import cinesort.ui.api.cinesort_api as backend

# Charge utile d'un attaquant : ce que CineSort ecrirait dans tools/ffprobe.exe
# puis LANCERAIT via subprocess (cf. cinesort/infra/probe/tools_manager.py).
_PAYLOAD = b"MZ\x90\x00PWNED-BY-MITM"


def _zip_bytes(entries: Dict[str, bytes]) -> bytes:
    """Construit une archive ZIP en memoire et retourne ses octets exacts."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def _fake_transport(payload: bytes) -> Callable[..., None]:
    """Remplace urlretrieve : sert `payload` quelle que soit l'URL demandee.

    Respecte le contrat d'urllib (appel du reporthook), pour que le bornage du
    telechargement soit exerce comme en production et pas court-circuite.
    """

    def _download(url: str, dest: str, reporthook: Optional[Callable[[int, int, int], None]] = None) -> None:
        block = 8192
        if reporthook is not None:
            reporthook(0, block, len(payload))
        with open(dest, "wb") as out:
            written = 0
            blocknum = 0
            while written < len(payload):
                chunk = payload[written : written + block]
                out.write(chunk)
                written += len(chunk)
                blocknum += 1
                if reporthook is not None:
                    reporthook(blocknum, block, len(payload))

    return _download


def _write_bomb_zip(path: Path, entry: str, uncompressed_bytes: int) -> str:
    """Ecrit sur disque un ZIP dont `entry` decompresse `uncompressed_bytes`, et retourne son SHA256.

    Ecrit et relit en streaming : le test ne doit pas lui-meme tenir des
    centaines de Mio en memoire, sinon il fragilise les tests voisins du meme
    processus pytest.
    """
    chunk = b"\0" * (1024 * 1024)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        with zf.open(entry, "w") as member:
            remaining = uncompressed_bytes
            while remaining > 0:
                take = min(len(chunk), remaining)
                member.write(chunk[:take])
                remaining -= take
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_transport(source: Path) -> Callable[..., None]:
    """Remplace urlretrieve : recopie `source` par blocs, sans charger le fichier en memoire."""

    def _download(url: str, dest: str, reporthook: Optional[Callable[[int, int, int], None]] = None) -> None:
        block = 65536
        total = source.stat().st_size
        if reporthook is not None:
            reporthook(0, block, total)
        with open(source, "rb") as src, open(dest, "wb") as out:
            blocknum = 0
            while True:
                data = src.read(block)
                if not data:
                    break
                out.write(data)
                blocknum += 1
                if reporthook is not None:
                    reporthook(blocknum, block, total)

    return _download


class AutoInstallSupplyChainFacadeTests(unittest.TestCase):
    """Le binaire non verifiable ne doit JAMAIS atterrir dans tools/."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_autoinstall_sec_")
        self.local_appdata = Path(self._tmp) / "appdata"
        self.tools = Path(self._tmp) / "tools"
        self.local_appdata.mkdir(parents=True, exist_ok=True)
        self.tools.mkdir(parents=True, exist_ok=True)
        # Isole l'etat de l'application (settings.json, runs) : state.default_state_dir()
        # derive de LOCALAPPDATA.
        self._env = mock.patch.dict(
            os.environ,
            {"LOCALAPPDATA": str(self.local_appdata)},
        )
        self._env.start()
        os.environ.pop(auto_install._ENV_SHA256_FFMPEG, None)
        os.environ.pop(auto_install._ENV_SHA256_MEDIAINFO, None)
        self._tools_patch = mock.patch.object(auto_install, "get_tools_dir", return_value=self.tools)
        self._tools_patch.start()
        self.api = backend.CineSortApi()

    def tearDown(self) -> None:
        self._tools_patch.stop()
        self._env.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _installed_files(self) -> list[str]:
        return sorted(p.name for p in self.tools.iterdir())

    def _assert_rien_installe(self, payload: dict) -> None:
        self.assertFalse(payload.get("ok"), payload)
        self.assertEqual(self._installed_files(), [], "aucun fichier ne doit rester dans tools/")
        self.assertEqual(payload.get("installed") or {}, {}, payload)
        self.assertTrue(payload.get("errors"), payload)

    def test_archive_substituee_par_un_mitm_est_refusee(self) -> None:
        """#466 — l'archive servie ne correspond pas a l'empreinte epinglee : refus.

        Sur main, EXPECTED_SHA256_* valant None, `_verify_archive` se contentait
        d'un warning : le faux ffprobe.exe etait ecrit dans tools/ puis execute.
        """
        tampered = _zip_bytes(
            {
                "ffmpeg-8.1.2-essentials_build/bin/ffprobe.exe": _PAYLOAD,
                "ffmpeg-8.1.2-essentials_build/bin/ffmpeg.exe": _PAYLOAD,
                "MediaInfo.exe": _PAYLOAD,
            }
        )
        with mock.patch.object(auto_install, "urlretrieve", side_effect=_fake_transport(tampered)):
            payload = self.api.runtime.auto_install_probe_tools()

        self._assert_rien_installe(payload)
        joined = " ".join(str(e) for e in payload["errors"])
        self.assertIn("SHA256 mismatch", joined, joined)

    def test_sans_empreinte_epinglee_l_installation_est_refusee_avec_un_message_actionnable(self) -> None:
        """#466 — empreinte inconnue => FAIL-CLOSED, et le message explique la degradation.

        L'application doit rester utilisable sans ces binaires : le message doit
        dire ce qui se degrade (analyse technique seule) et donner les chemins
        alternatifs (winget, chemin manuel).
        """
        archive = _zip_bytes({"bin/ffprobe.exe": _PAYLOAD, "MediaInfo.exe": _PAYLOAD})
        with (
            mock.patch.object(auto_install, "EXPECTED_SHA256_FFMPEG", None),
            mock.patch.object(auto_install, "EXPECTED_SHA256_MEDIAINFO", None),
            mock.patch.object(auto_install, "urlretrieve", side_effect=_fake_transport(archive)) as transport,
        ):
            payload = self.api.runtime.auto_install_probe_tools()

        self._assert_rien_installe(payload)
        joined = " ".join(str(e) for e in payload["errors"])
        self.assertIn("refusee", joined.lower(), joined)
        # Le refus doit tomber AVANT le telechargement : inutile de tirer 100 Mo.
        self.assertEqual(transport.call_count, 0, "aucun telechargement ne doit etre lance sans empreinte")
        # Ce qui se degrade, et ce que l'utilisateur peut faire a la place.
        for attendu in ("winget", "Parametres > Outils externes", "score qualite"):
            self.assertIn(attendu, joined, f"message d'echec non actionnable, '{attendu}' absent : {joined}")

    def test_zip_bombe_abandonnee_avant_toute_ecriture(self) -> None:
        """#734 — archive dont l'empreinte est valide mais le contenu decompresse enorme.

        L'empreinte attendue est fournie via la variable d'environnement
        documentee : la bombe franchit donc la verification d'integrite, ce qui
        est exactement le point de l'issue (la borne doit proteger AUSSI hors du
        modele checksum, ex. un amont compromis ou un pin errone).
        """
        oversize = 260 * 1024 * 1024  # > _MAX_MEMBER_UNCOMPRESSED_BYTES (256 Mio)
        bomb_path = Path(self._tmp) / "bomb.zip"
        digest = _write_bomb_zip(bomb_path, "bin/ffprobe.exe", oversize)

        with (
            mock.patch.dict(os.environ, {auto_install._ENV_SHA256_FFMPEG: digest}),
            mock.patch.object(auto_install, "urlretrieve", side_effect=_file_transport(bomb_path)),
        ):
            payload = self.api.runtime.auto_install_probe_tools()

        self.assertFalse(payload.get("ok"), payload)
        self.assertNotIn("ffprobe", payload.get("installed") or {}, payload)
        self.assertEqual(
            self._installed_files(),
            [],
            "ni binaire tronque ni fichier .part ne doit survivre a l'abandon",
        )
        joined = " ".join(str(e) for e in payload["errors"])
        self.assertIn("fail-closed", joined, joined)

    def test_installation_nominale_toujours_fonctionnelle(self) -> None:
        """Garde-fou : le durcissement ne doit pas casser le cas legitime.

        Une archive dont l'empreinte correspond a celle attendue s'installe
        normalement, avec le contenu exact.
        """
        ff_archive = _zip_bytes(
            {
                "ffmpeg-8.1.2-essentials_build/bin/ffprobe.exe": b"real-ffprobe",
                "ffmpeg-8.1.2-essentials_build/bin/ffmpeg.exe": b"real-ffmpeg",
            }
        )
        mi_archive = _zip_bytes({"MediaInfo.exe": b"real-mediainfo"})

        def _dispatch(url: str, dest: str, reporthook=None) -> None:
            payload = ff_archive if "ffmpeg" in url.lower() else mi_archive
            _fake_transport(payload)(url, dest, reporthook)

        with (
            mock.patch.dict(
                os.environ,
                {
                    auto_install._ENV_SHA256_FFMPEG: hashlib.sha256(ff_archive).hexdigest(),
                    auto_install._ENV_SHA256_MEDIAINFO: hashlib.sha256(mi_archive).hexdigest(),
                },
            ),
            mock.patch.object(auto_install, "urlretrieve", side_effect=_dispatch),
        ):
            payload = self.api.runtime.auto_install_probe_tools()

        self.assertEqual(payload.get("errors"), [], payload)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual((self.tools / "ffprobe.exe").read_bytes(), b"real-ffprobe")
        self.assertEqual((self.tools / "ffmpeg.exe").read_bytes(), b"real-ffmpeg")
        self.assertEqual((self.tools / "MediaInfo.exe").read_bytes(), b"real-mediainfo")


if __name__ == "__main__":
    unittest.main()
