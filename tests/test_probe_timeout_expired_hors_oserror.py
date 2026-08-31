"""`subprocess.TimeoutExpired` n'herite PAS d'`OSError` — la sonde de VERSION l'ignorait.

Meme piege que la regle 4 du `CLAUDE.md` (`sqlite3.Error` n'herite pas d'`OSError`),
sur une autre hierarchie : `TimeoutExpired` derive de `SubprocessError`, donc
d'`Exception`. Un `except OSError` ne l'attrape pas.

ITER13 avait ferme cette famille sur la sonde de FICHIER — `ffprobe_backend.py:40`,
`mediainfo_backend.py:23` et la branche PARALLELE de `service.probe_files` nomment
tous les trois `subprocess.TimeoutExpired` a cote d'`OSError`, ce qui est en soi la
preuve, dans ce depot, que les deux classes sont disjointes. La sonde de VERSION
(`ffprobe -version` / `mediainfo --Version`) etait restee dehors :

    tooling._probe_version                 except OSError
    tools_manager._probe_version_line      except (OSError, TypeError, ValueError)
    tools_manager._run_winget_for_tool     except (KeyError, OSError, TypeError, ValueError)

Or c'est bien `default_runner` qui les sert, et il RE-LEVE `TimeoutExpired` apres
epuisement des tentatives (`_retry_backoff.retry_with_backoff` le classe transitoire,
le rejoue, puis `raise`). L'exception traversait ensuite `get_tools_status`,
`ProbeService._get_tools_cached` et `probe_file`, et ses appelants ne la retenaient
pas non plus : `probe_support.recheck_probe_for_row` et `app/runtime_probe_check`
attrapent `(OSError, KeyError, TypeError, ValueError)`, tuple qui ne la contient pas
davantage.

POURQUOI LA BATTERIE EXISTANTE NE POUVAIT PAS LE VOIR
-----------------------------------------------------
Deux tests de `test_probe_tools_manager.py` portent « timeout » dans leur nom
(`test_detect_probe_tools_invalid_executable_when_runner_raises`,
`test_validate_tool_path_rejects_timeout_or_non_executable`) et injectent
`TimeoutError` — le builtin, qui EST une sous-classe d'`OSError` depuis la PEP 3151.
Ils etaient donc verts pendant tout le defaut : ils eprouvaient la garde contre une
classe que la production ne leve jamais a cet endroit. Ce fichier rejoue les memes
scenarios avec la classe REELLE.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.infra.probe.service import ProbeService, reset_tools_status_cache
from cinesort.infra.probe.tooling import get_tools_status
from cinesort.infra.probe.tools_manager import _run_winget_for_tool, detect_probe_tools, validate_tool_path


def _timeout_runner(cmd: List[str], timeout_s: float) -> Tuple[int, str, str]:
    """Le runner que `default_runner` finit par imiter : retries epuises -> re-leve."""
    raise subprocess.TimeoutExpired(cmd=list(cmd), timeout=float(timeout_s))


class HierarchieDesExceptionsTests(unittest.TestCase):
    """Le fait de langage qui rend les mentions explicites OBLIGATOIRES.

    Sans cette garde, un futur passage « simplifie » les tuples en retirant
    `subprocess.TimeoutExpired`, en croyant `OSError` suffisant — et rien ne
    rougirait avant la prochaine panne de NAS chez un utilisateur.
    """

    def test_timeout_expired_n_est_pas_un_oserror(self) -> None:
        self.assertFalse(issubclass(subprocess.TimeoutExpired, OSError))

    def test_le_builtin_timeout_error_lui_en_est_un(self) -> None:
        # C'est cette confusion exacte qui rendait verts les deux tests
        # « timeout » de test_probe_tools_manager.py.
        self.assertTrue(issubclass(TimeoutError, OSError))


class SondeDeVersionTests(unittest.TestCase):
    """`tooling.get_tools_status` : un timeout degrade la VERSION, il n'explose pas."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="probe_timeout_version_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.ffprobe = self.root / "ffprobe.exe"
        self.mediainfo = self.root / "MediaInfo.exe"
        self.ffprobe.write_bytes(b"x")
        self.mediainfo.write_bytes(b"x")

    def test_get_tools_status_rend_un_statut_au_lieu_de_lever(self) -> None:
        tools = get_tools_status(
            mediainfo_path=str(self.mediainfo),
            ffprobe_path=str(self.ffprobe),
            runner=_timeout_runner,
            which_fn=lambda _name: None,
        )
        # Le binaire est bien la (chemin resolu) : c'est sa VERSION qui n'a pas
        # pu etre lue. On ne pretend pas qu'il est absent.
        for name in ("ffprobe", "mediainfo"):
            self.assertTrue(tools[name].available, name)
            self.assertEqual(tools[name].version, "", name)
            self.assertIn("version non lue", tools[name].message, name)


class InventaireDesOutilsTests(unittest.TestCase):
    """`tools_manager` : meme exigence sur les deux routes de l'ecran Parametres."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="probe_timeout_tools_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.ffprobe = self.root / "ffprobe.exe"
        self.ffprobe.write_bytes(b"x")

    def test_detect_probe_tools_classe_invalid_executable(self) -> None:
        payload = detect_probe_tools(
            settings={"probe_backend": "auto", "ffprobe_path": str(self.ffprobe), "mediainfo_path": ""},
            state_dir=self.root,
            runner=_timeout_runner,
            which_fn=lambda _name: None,
            check_versions=True,
            scan_winget_packages=False,
        )
        self.assertEqual(str(payload.get("tools", {}).get("ffprobe", {}).get("status")), "invalid_executable", payload)

    def test_validate_tool_path_refuse_sans_lever(self) -> None:
        result = validate_tool_path(
            tool_name="ffprobe",
            tool_path=str(self.ffprobe),
            state_dir=self.root,
            runner=_timeout_runner,
        )
        self.assertFalse(result.get("ok"), result)
        self.assertIn("Executable invalide", str(result.get("message") or ""))

    def test_winget_essaie_le_paquet_suivant_au_lieu_d_abandonner(self) -> None:
        """`WINGET_INSTALL_TIMEOUT_S` vaut 1800 s : le timeout EST le mode d'echec
        attendu d'une installation qui s'enlise. Il ne doit pas sortir de la boucle
        des le premier identifiant de paquet."""
        vus: List[List[str]] = []

        def runner(cmd: List[str], timeout_s: float) -> Tuple[int, str, str]:
            vus.append([str(x) for x in cmd])
            raise subprocess.TimeoutExpired(cmd=list(cmd), timeout=float(timeout_s))

        result = _run_winget_for_tool(
            tool_name="ffprobe",
            action="install",
            scope="user",
            runner=runner,
            winget_path="winget.exe",
        )
        self.assertFalse(result.get("ok"), result)
        self.assertIn("Echec install ffprobe", str(result.get("message") or ""))
        # DEUX identifiants sont declares pour ffprobe (`Gyan.FFmpeg`, `BtbN.FFmpeg`).
        # Le `continue` du except doit les avoir essayes tous les deux : avant le
        # correctif, le premier timeout sortait de la boucle et le second paquet
        # n'etait jamais tente.
        self.assertEqual(len(vus), 2, vus)


class ChaineProbeFileTests(unittest.TestCase):
    """La consequence reelle : `probe_file` ne remonte plus l'exception a ses appelants.

    Cinq modules de production construisent un `ProbeService` (`probe_support`,
    `quality_report_support`, `perceptual_support`, `quality_support`,
    `runtime_probe_check`). Aucun ne nomme `subprocess.TimeoutExpired` autour de
    l'appel ; les deux verifies un par un — `probe_support.recheck_probe_for_row`
    et `runtime_probe_check` — attrapent `(OSError, KeyError, TypeError,
    ValueError)`.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="probe_timeout_chain_")
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        state_dir = root / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(db_path_for_state_dir(state_dir), busy_timeout_ms=8000)
        self.store.initialize()
        self.media = root / "film.mkv"
        self.media.write_bytes(b"\x00" * 2048)
        self.ffprobe = root / "ffprobe.exe"
        self.mediainfo = root / "MediaInfo.exe"
        self.ffprobe.write_bytes(b"x")
        self.mediainfo.write_bytes(b"x")
        reset_tools_status_cache()
        self.addCleanup(reset_tools_status_cache)

    def _settings(self) -> Dict[str, Any]:
        return {
            "probe_backend": "auto",
            "ffprobe_path": str(self.ffprobe),
            "mediainfo_path": str(self.mediainfo),
        }

    def test_probe_file_rend_un_payload_avec_le_timeout_dit(self) -> None:
        service = ProbeService(self.store, runner=_timeout_runner, which_fn=lambda _name: None)
        result = service.probe_file(media_path=self.media, settings=self._settings())

        self.assertTrue(result.get("ok"), result)
        normalized = result.get("normalized") or {}
        messages = " ".join(str(m) for m in (normalized.get("messages") or []))
        # La degradation est DITE, pas silencieuse : les deux backends nomment
        # leur timeout dans les messages du probe.
        self.assertIn("timeout", messages.lower(), messages)
        # Et la version reste vide plutot que la sonde entiere en erreur.
        tools = (result.get("sources") or {}).get("tools") or {}
        self.assertEqual(str(tools.get("ffprobe", {}).get("version") or ""), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
