"""GATE AUDIT 2026-06-11 (R3e, gap[4]) — le breaker est alimente en backend auto.

Avant : en backend 'auto', une source reseau injoignable rend ffprobe ET
mediainfo None (timeout/IO) alors que les binaires restent available=True.
`_is_tool_unavailable_failure` L189 retournait True (classait a tort "tool
indisponible"), ce qui SAUTAIT le feed `_source_breaker.record_failure`
(service.py:542). Le compteur n'incrementait jamais -> la source ne passait
jamais DEGRADED -> check_or_raise ne court-circuitait jamais -> chaque fichier
du NAS en panne payait le timeout adaptatif complet (~41h de hang).

Apres : le feed du breaker utilise `_is_tool_definitely_unavailable` (STRICTE),
qui ne classe "indisponible" que si les binaires sont reellement absents. Le cas
auto + binaires available + 2 runs None alimente desormais le breaker. Le cache
(`_is_tool_unavailable_failure`, inchange) reste protege de la pollution.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.probe._source_circuit_breaker import SourceCircuitBreaker
from cinesort.infra.probe.service import ProbeService
from cinesort.infra.probe.tooling import ToolStatus


def _tool(name: str, available: bool) -> ToolStatus:
    return ToolStatus(
        name=name,
        available=available,
        path=(f"/fake/{name}" if available else ""),
        version="1.0" if available else "",
        message="",
    )


class IsToolDefinitelyUnavailableTests(unittest.TestCase):
    """Logique STRICTE : seuls les cas binaire-vraiment-absent comptent."""

    def setUp(self) -> None:
        self.svc = ProbeService(mock.Mock(), source_breaker=mock.Mock(spec=SourceCircuitBreaker))

    def test_auto_both_available_is_not_unavailable(self) -> None:
        # Coeur du gap : auto + 2 binaires dispos -> PAS "tool unavailable"
        # (une panne reseau ici doit alimenter le breaker).
        self.assertFalse(
            self.svc._is_tool_definitely_unavailable(
                backend="auto",
                mediainfo_tool=_tool("mediainfo", True),
                ffprobe_tool=_tool("ffprobe", True),
            )
        )

    def test_auto_both_missing_is_unavailable(self) -> None:
        self.assertTrue(
            self.svc._is_tool_definitely_unavailable(
                backend="auto",
                mediainfo_tool=_tool("mediainfo", False),
                ffprobe_tool=_tool("ffprobe", False),
            )
        )

    def test_auto_one_available_is_not_unavailable(self) -> None:
        self.assertFalse(
            self.svc._is_tool_definitely_unavailable(
                backend="auto",
                mediainfo_tool=_tool("mediainfo", True),
                ffprobe_tool=_tool("ffprobe", False),
            )
        )

    def test_ffprobe_backend_missing_is_unavailable(self) -> None:
        self.assertTrue(
            self.svc._is_tool_definitely_unavailable(
                backend="ffprobe",
                mediainfo_tool=_tool("mediainfo", True),
                ffprobe_tool=_tool("ffprobe", False),
            )
        )

    def test_none_backend_is_not_unavailable(self) -> None:
        self.assertFalse(
            self.svc._is_tool_definitely_unavailable(
                backend="none",
                mediainfo_tool=_tool("mediainfo", False),
                ffprobe_tool=_tool("ffprobe", False),
            )
        )


class ProbeBreakerAutoWiringTests(unittest.TestCase):
    """Wiring reel : probe_file en auto + binaires dispos + probes en echec
    DOIT appeler record_failure (skip sur HEAD)."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_probe_wire_")
        # Fichier local reel : compute_adaptive_timeout / stat fonctionnent.
        self.media = Path(self._tmp) / "film.mkv"
        self.media.write_bytes(b"x" * 8192)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _failing_runner(self, cmd, timeout_s):
        # Tout echoue (rc=1) : version non lue (tool reste available via path) ET
        # probe sans sortie -> raw_mediainfo/raw_ffprobe = None. Simule un NAS
        # injoignable : le binaire se lance mais ne lit rien.
        return (1, "", "Input/output error (source NAS injoignable)")

    def _make_service(self):
        breaker = mock.Mock(spec=SourceCircuitBreaker)
        breaker.check_or_raise.return_value = None  # source pas (encore) degradee
        breaker.record_failure.return_value = False
        svc = ProbeService(
            mock.Mock(),  # store jamais touche (cache_key patche a None)
            runner=self._failing_runner,
            which_fn=lambda name: f"/fake/{name}",  # 2 binaires "available"
            source_breaker=breaker,
        )
        return svc, breaker

    def test_record_failure_called_on_auto_probe_failure(self) -> None:
        svc, breaker = self._make_service()
        with mock.patch.object(svc, "_cache_key", return_value=None):
            result = svc.probe_file(media_path=self.media, settings={"probe_backend": "auto"})
        self.assertTrue(result.get("ok"))
        breaker.record_failure.assert_called_once()
        breaker.record_success.assert_not_called()


if __name__ == "__main__":
    unittest.main()
