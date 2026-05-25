from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.infra.probe.tools_manager import detect_probe_tools, manage_probe_tools, validate_tool_path


def _isolate_tools_lookup(td: str):
    """
    Isole la detection d'outils dans un tempdir : force sys.frozen=True et
    sys.executable=td/app.exe pour que tools_roots pointe vers td/tools (vide),
    neutralisant ainsi la detection du dossier tools/ present dans le repo.
    """
    fake_exec = str(Path(td) / "app.exe")
    return mock.patch.multiple(sys, frozen=True, executable=fake_exec, create=True)


class ProbeToolsManagerTests(unittest.TestCase):
    def test_detect_probe_tools_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="probe_tools_missing_") as td, _isolate_tools_lookup(td):
            payload = detect_probe_tools(
                settings={"probe_backend": "auto", "ffprobe_path": "", "mediainfo_path": ""},
                state_dir=Path(td),
                which_fn=lambda _name: None,
                check_versions=True,
                scan_winget_packages=False,
            )
        self.assertFalse(payload.get("hybrid_ready"), payload)
        self.assertEqual(str(payload.get("degraded_mode")), "none", payload)
        tools = payload.get("tools", {})
        self.assertEqual(str(tools.get("ffprobe", {}).get("status")), "missing", payload)
        self.assertEqual(str(tools.get("mediainfo", {}).get("status")), "missing", payload)

    def test_detect_probe_tools_valid_versions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="probe_tools_ok_") as td:
            root = Path(td)
            ff = root / "ffprobe.exe"
            mi = root / "MediaInfo.exe"
            ff.write_bytes(b"x")
            mi.write_bytes(b"x")

            def runner(cmd, _timeout):
                txt = " ".join(str(x) for x in cmd).lower()
                if "-version" in txt and "ffprobe" in txt:
                    return 0, "ffprobe version 7.1.1", ""
                if "--version" in txt and ("mediainfo" in txt):
                    return 0, "MediaInfoLib - v24.12", ""
                return 1, "", "unexpected"

            payload = detect_probe_tools(
                settings={"probe_backend": "auto", "ffprobe_path": str(ff), "mediainfo_path": str(mi)},
                state_dir=root,
                runner=runner,
                which_fn=lambda _name: None,
                check_versions=True,
                scan_winget_packages=False,
            )
        self.assertTrue(payload.get("hybrid_ready"), payload)
        self.assertEqual(str(payload.get("degraded_mode")), "hybrid", payload)
        self.assertEqual(str(payload.get("tools", {}).get("ffprobe", {}).get("status")), "ok", payload)
        self.assertEqual(str(payload.get("tools", {}).get("mediainfo", {}).get("status")), "ok", payload)

    def test_detect_probe_tools_too_old_version(self) -> None:
        with tempfile.TemporaryDirectory(prefix="probe_tools_old_") as td:
            root = Path(td)
            ff = root / "ffprobe.exe"
            ff.write_bytes(b"x")

            def runner(cmd, _timeout):
                txt = " ".join(str(x) for x in cmd).lower()
                if "-version" in txt:
                    return 0, "ffprobe version 3.0", ""
                return 1, "", "unexpected"

            payload = detect_probe_tools(
                settings={"probe_backend": "auto", "ffprobe_path": str(ff), "mediainfo_path": ""},
                state_dir=root,
                runner=runner,
                which_fn=lambda _name: None,
                check_versions=True,
                scan_winget_packages=False,
            )
        self.assertEqual(str(payload.get("tools", {}).get("ffprobe", {}).get("status")), "version_too_old", payload)
        self.assertFalse(bool(payload.get("tools", {}).get("ffprobe", {}).get("compatible")), payload)

    def test_detect_probe_tools_version_unknown_when_output_is_unreadable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="probe_tools_unknown_") as td:
            root = Path(td)
            ff = root / "ffprobe.exe"
            ff.write_bytes(b"x")

            def runner(cmd, _timeout):
                txt = " ".join(str(x) for x in cmd).lower()
                if "-version" in txt:
                    return 0, "ffprobe build custom-unparsable", ""
                return 1, "", "unexpected"

            payload = detect_probe_tools(
                settings={"probe_backend": "auto", "ffprobe_path": str(ff), "mediainfo_path": ""},
                state_dir=root,
                runner=runner,
                which_fn=lambda _name: None,
                check_versions=True,
                scan_winget_packages=False,
            )
        self.assertEqual(str(payload.get("tools", {}).get("ffprobe", {}).get("status")), "version_unknown", payload)
        self.assertTrue(bool(payload.get("tools", {}).get("ffprobe", {}).get("compatible")), payload)

    def test_detect_probe_tools_invalid_executable_when_runner_raises(self) -> None:
        with tempfile.TemporaryDirectory(prefix="probe_tools_invalid_exec_") as td:
            root = Path(td)
            ff = root / "ffprobe.exe"
            ff.write_bytes(b"x")

            def runner(_cmd, _timeout):
                raise TimeoutError("boom")

            payload = detect_probe_tools(
                settings={"probe_backend": "auto", "ffprobe_path": str(ff), "mediainfo_path": ""},
                state_dir=root,
                runner=runner,
                which_fn=lambda _name: None,
                check_versions=True,
                scan_winget_packages=False,
            )
        self.assertEqual(
            str(payload.get("tools", {}).get("ffprobe", {}).get("status")),
            "invalid_executable",
            payload,
        )

    def test_detect_probe_tools_handles_missing_localappdata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="probe_tools_no_localappdata_") as td:
            with mock.patch.dict("os.environ", {"LOCALAPPDATA": ""}, clear=False):
                with _isolate_tools_lookup(td):
                    payload = detect_probe_tools(
                        settings={"probe_backend": "auto", "ffprobe_path": "", "mediainfo_path": ""},
                        state_dir=Path(td),
                        which_fn=lambda _name: None,
                        check_versions=True,
                        scan_winget_packages=True,
                    )
        self.assertEqual(str(payload.get("tools", {}).get("ffprobe", {}).get("status")), "missing", payload)
        self.assertEqual(str(payload.get("tools", {}).get("mediainfo", {}).get("status")), "missing", payload)

    def test_manage_probe_tools_requires_winget(self) -> None:
        with tempfile.TemporaryDirectory(prefix="probe_tools_install_") as td:
            out = manage_probe_tools(
                action="install",
                options={"scope": "user"},
                settings={"probe_backend": "auto"},
                state_dir=Path(td),
                which_fn=lambda _name: None,
            )
        self.assertFalse(out.get("ok"), out)
        self.assertIn("winget", str(out.get("message", "")).lower())

    def test_manage_probe_tools_reconciles_when_tool_is_already_ready(self) -> None:
        with tempfile.TemporaryDirectory(prefix="probe_tools_reconcile_") as td:
            root = Path(td)
            ff = root / "ffprobe.exe"
            ff.write_bytes(b"x")

            def runner(cmd, _timeout):
                txt = " ".join(str(x) for x in cmd).lower()
                if "-version" in txt and "ffprobe" in txt:
                    return 0, "ffprobe version 7.1.1", ""
                if txt.startswith("winget "):
                    return 1, "", "install failed"
                return 1, "", "unexpected"

            out = manage_probe_tools(
                action="install",
                options={"scope": "user", "tools": ["ffprobe"]},
                settings={"probe_backend": "auto", "ffprobe_path": str(ff)},
                state_dir=root,
                runner=runner,
                which_fn=lambda _name: "winget",
            )
        self.assertTrue(out.get("ok"), out)
        results = out.get("results") or []
        self.assertEqual(len(results), 1, out)
        self.assertTrue(results[0].get("ok"), out)
        self.assertTrue(results[0].get("reconciled"), out)

    def test_validate_tool_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="probe_tools_validate_") as td:
            root = Path(td)
            ff = root / "ffprobe.exe"
            ff.write_bytes(b"x")

            def runner(cmd, _timeout):
                if "-version" in " ".join(str(x) for x in cmd).lower():
                    return 0, "ffprobe version 7.0", ""
                return 1, "", "unexpected"

            ok = validate_tool_path(tool_name="ffprobe", tool_path=str(ff), state_dir=root, runner=runner)
            self.assertTrue(ok.get("ok"), ok)

            bad = validate_tool_path(
                tool_name="ffprobe", tool_path=str(root / "missing.exe"), state_dir=root, runner=runner
            )
            self.assertFalse(bad.get("ok"), bad)

    def test_validate_tool_path_rejects_timeout_or_non_executable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="probe_tools_validate_timeout_") as td:
            root = Path(td)
            ff = root / "ffprobe.exe"
            ff.write_bytes(b"x")

            def runner(_cmd, _timeout):
                raise TimeoutError("timeout")

            bad = validate_tool_path(tool_name="ffprobe", tool_path=str(ff), state_dir=root, runner=runner)
            self.assertFalse(bad.get("ok"), bad)
            self.assertIn("Executable invalide", str(bad.get("message") or ""))


class ProbeToolsExtendedStatusTests(unittest.TestCase):
    """VAGUE D : payload etendu detect_probe_tools inclut fpcalc + LPIPS."""

    def test_probe_tools_status_returns_fpcalc(self) -> None:
        """Le payload `tools` contient une cle `fpcalc` avec found/path/version."""
        with tempfile.TemporaryDirectory(prefix="probe_tools_fpcalc_") as td, _isolate_tools_lookup(td):
            payload = detect_probe_tools(
                settings={"probe_backend": "auto", "ffprobe_path": "", "mediainfo_path": ""},
                state_dir=Path(td),
                which_fn=lambda _name: None,
                check_versions=True,
                scan_winget_packages=False,
            )
        tools = payload.get("tools") or {}
        self.assertIn("fpcalc", tools, "Cle 'fpcalc' attendue dans tools")
        fp = tools["fpcalc"]
        # Sans fpcalc bundled (env isole) ni dans PATH, on attend missing.
        self.assertIn("found", fp, fp)
        self.assertIn("path", fp, fp)
        self.assertIn("version", fp, fp)
        self.assertFalse(fp.get("found"), fp)

    def test_probe_tools_status_returns_lpips(self) -> None:
        """Le payload `tools` contient une cle `lpips` avec found/path/size_bytes."""
        with tempfile.TemporaryDirectory(prefix="probe_tools_lpips_") as td, _isolate_tools_lookup(td):
            payload = detect_probe_tools(
                settings={"probe_backend": "auto", "ffprobe_path": "", "mediainfo_path": ""},
                state_dir=Path(td),
                which_fn=lambda _name: None,
                check_versions=True,
                scan_winget_packages=False,
            )
        tools = payload.get("tools") or {}
        self.assertIn("lpips", tools, "Cle 'lpips' attendue dans tools")
        lp = tools["lpips"]
        self.assertIn("found", lp, lp)
        self.assertIn("path", lp, lp)
        self.assertIn("size_bytes", lp, lp)
        # En env isolee (sys.frozen=True, exe -> td vide), pas de modele.
        self.assertFalse(lp.get("found"), lp)
        self.assertEqual(int(lp.get("size_bytes") or 0), 0, lp)

    def test_probe_tools_status_fpcalc_detected_when_bundled(self) -> None:
        """Quand fpcalc est present dans <repo>/assets/tools/, found=True."""
        # On simule un bundle PyInstaller : sys.frozen=True + sys.executable
        # dans un dir qui contient assets/tools/fpcalc.exe.
        with tempfile.TemporaryDirectory(prefix="probe_tools_fpcalc_bundle_") as td:
            root = Path(td)
            tools_dir = root / "assets" / "tools"
            tools_dir.mkdir(parents=True, exist_ok=True)
            fpcalc = tools_dir / "fpcalc.exe"
            fpcalc.write_bytes(b"x")

            def runner(cmd, _timeout):
                if any("fpcalc" in str(x).lower() for x in cmd):
                    return 0, "fpcalc version 1.5.1", ""
                return 1, "", ""

            fake_exec = str(root / "app.exe")
            with mock.patch.multiple(sys, frozen=True, executable=fake_exec, create=True):
                payload = detect_probe_tools(
                    settings={"probe_backend": "auto", "ffprobe_path": "", "mediainfo_path": ""},
                    state_dir=root,
                    runner=runner,
                    which_fn=lambda _name: None,
                    check_versions=True,
                    scan_winget_packages=False,
                )
        fp = (payload.get("tools") or {}).get("fpcalc") or {}
        self.assertTrue(fp.get("found"), fp)
        self.assertEqual(str(fp.get("version") or ""), "1.5.1", fp)
        self.assertEqual(str(fp.get("source") or ""), "bundled", fp)

    def test_probe_tools_status_lpips_detected_when_bundled(self) -> None:
        """Quand lpips_alexnet.onnx est present, found=True + size_bytes>0."""
        with tempfile.TemporaryDirectory(prefix="probe_tools_lpips_bundle_") as td:
            root = Path(td)
            models_dir = root / "assets" / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            model = models_dir / "lpips_alexnet.onnx"
            payload_bytes = b"X" * 1234
            model.write_bytes(payload_bytes)

            fake_exec = str(root / "app.exe")
            with mock.patch.multiple(sys, frozen=True, executable=fake_exec, create=True):
                payload = detect_probe_tools(
                    settings={"probe_backend": "auto", "ffprobe_path": "", "mediainfo_path": ""},
                    state_dir=root,
                    which_fn=lambda _name: None,
                    check_versions=False,
                    scan_winget_packages=False,
                )
        lp = (payload.get("tools") or {}).get("lpips") or {}
        self.assertTrue(lp.get("found"), lp)
        self.assertEqual(int(lp.get("size_bytes") or 0), len(payload_bytes), lp)
        self.assertEqual(str(lp.get("source") or ""), "bundled", lp)


class ParametresUiToolsSectionTests(unittest.TestCase):
    """VAGUE D : verifie que parametres.js contient la nouvelle section outils."""

    def test_parametres_has_tools_section(self) -> None:
        # Lecture brute (no JS engine en CI) : on cherche des marqueurs distincts.
        repo_root = Path(__file__).resolve().parent.parent
        js_path = repo_root / "web" / "dashboard" / "views" / "parametres.js"
        text = js_path.read_text(encoding="utf-8")
        # Section declarative dans PARAMETRES_GROUPS[analyse].
        self.assertIn('id: "outils"', text)
        self.assertIn("Outils externes", text)
        # Field type custom rendu via _renderProbeToolsTable.
        self.assertIn('type: "probe-tools"', text)
        # Endpoints backend cables sur les boutons.
        self.assertIn("runtime/get_probe_tools_status", text)
        self.assertIn("runtime/recheck_probe_tools", text)
        self.assertIn("runtime/auto_install_probe_tools", text)
        # Les 4 outils rendus (table 4 lignes).
        self.assertIn("ffprobe", text)
        self.assertIn("mediainfo", text)
        self.assertIn("fpcalc", text)
        self.assertIn("lpips", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
