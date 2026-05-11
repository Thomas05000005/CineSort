"""Tests rapport par email — item 9.16.

Couvre :
- Construction email : sujet, corps, MIME
- SMTP mock : connexion, starttls, login, sendmail
- Envoi reussi/echoue
- Guards : email_enabled, email_on_scan/apply
- Settings defaults et round-trip
- Endpoint test_email_report existe
- UI : section email dans settings.js
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.app.email_report import (
    _build_subject,
    _build_body,
    send_email_report,
    dispatch_email,
)


# ---------------------------------------------------------------------------
# Construction email (3 tests)
# ---------------------------------------------------------------------------


class EmailBuildTests(unittest.TestCase):
    """Tests de la construction du sujet et du corps."""

    def test_subject_post_scan(self) -> None:
        s = _build_subject("post_scan", {"data": {"rows": 42}})
        self.assertIn("42", s)
        self.assertIn("Scan", s)

    def test_subject_post_apply(self) -> None:
        s = _build_subject("post_apply", {"data": {"renames": 10}})
        self.assertIn("10", s)
        self.assertIn("Apply", s)

    def test_body_contains_summary(self) -> None:
        body = _build_body(
            "post_scan",
            {
                "run_id": "run1",
                "ts": 1.0,
                "data": {"rows": 42, "folders_scanned": 100, "roots": ["D:/Films"]},
            },
        )
        self.assertIn("42", body)
        self.assertIn("100", body)
        self.assertIn("D:/Films", body)
        self.assertIn("run1", body)

    def test_body_post_apply(self) -> None:
        body = _build_body(
            "post_apply",
            {
                "run_id": "run2",
                "ts": 1.0,
                "data": {"renames": 5, "moves": 2, "errors": 0},
            },
        )
        self.assertIn("Renommes", body)
        self.assertIn("5", body)


# ---------------------------------------------------------------------------
# SMTP mock (4 tests)
# ---------------------------------------------------------------------------


class SmtpSendTests(unittest.TestCase):
    """Tests d'envoi avec SMTP mocke."""

    def _base_settings(self) -> dict:
        return {
            "email_smtp_host": "smtp.test.com",
            "email_smtp_port": 587,
            "email_smtp_user": "user@test.com",
            "email_smtp_password": "pass",
            "email_smtp_tls": True,
            "email_to": "dest@test.com",
        }

    @mock.patch("cinesort.app.email_report.smtplib.SMTP")
    def test_send_success(self, mock_smtp_cls) -> None:
        """Envoi reussi → True, sendmail appele."""
        mock_smtp = mock.MagicMock()
        mock_smtp_cls.return_value = mock_smtp
        ok = send_email_report(self._base_settings(), "post_scan", {"run_id": "r1", "ts": 1, "data": {"rows": 5}})
        self.assertTrue(ok)
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("user@test.com", "pass")
        mock_smtp.sendmail.assert_called_once()
        mock_smtp.quit.assert_called_once()

    @mock.patch("cinesort.app.email_report.smtplib.SMTP")
    def test_send_failure_no_crash(self, mock_smtp_cls) -> None:
        """Envoi echoue → False, pas de crash."""
        import smtplib

        mock_smtp_cls.side_effect = smtplib.SMTPException("fail")
        ok = send_email_report(self._base_settings(), "post_scan", {"run_id": "r1", "ts": 1, "data": {}})
        self.assertFalse(ok)

    def test_missing_host_returns_false(self) -> None:
        """Host manquant → False."""
        s = self._base_settings()
        s["email_smtp_host"] = ""
        ok = send_email_report(s, "post_scan", {"run_id": "r1", "ts": 1, "data": {}})
        self.assertFalse(ok)

    @mock.patch("cinesort.app.email_report.smtplib.SMTP_SSL")
    def test_port_465_uses_ssl(self, mock_ssl_cls) -> None:
        """Port 465 → SMTP_SSL."""
        mock_smtp = mock.MagicMock()
        mock_ssl_cls.return_value = mock_smtp
        s = self._base_settings()
        s["email_smtp_port"] = 465
        ok = send_email_report(s, "post_scan", {"run_id": "r1", "ts": 1, "data": {}})
        self.assertTrue(ok)
        mock_ssl_cls.assert_called_once()


# ---------------------------------------------------------------------------
# Guards (2 tests)
# ---------------------------------------------------------------------------


class DispatchGuardTests(unittest.TestCase):
    """Tests des guards dispatch_email."""

    @mock.patch("cinesort.app.email_report.send_email_report")
    def test_disabled_no_send(self, mock_send) -> None:
        """email_enabled=False → pas d'envoi."""
        dispatch_email({"email_enabled": False}, "post_scan", {"run_id": "r1", "ts": 1, "data": {}})
        mock_send.assert_not_called()

    @mock.patch("cinesort.app.email_report.send_email_report")
    def test_on_scan_disabled_no_send(self, mock_send) -> None:
        """email_on_scan=False → pas d'envoi pour post_scan."""
        dispatch_email(
            {"email_enabled": True, "email_on_scan": False}, "post_scan", {"run_id": "r1", "ts": 1, "data": {}}
        )
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Settings (2 tests)
# ---------------------------------------------------------------------------


class EmailSettingsTests(unittest.TestCase):
    """Tests des settings email."""

    def test_defaults(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        s = api.get_settings()
        self.assertFalse(s.get("email_enabled"))
        self.assertEqual(s.get("email_smtp_port"), 587)
        self.assertTrue(s.get("email_smtp_tls"))
        self.assertTrue(s.get("email_on_scan"))
        self.assertTrue(s.get("email_on_apply"))

    def test_round_trip(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="cinesort_email_s_")
        try:
            root = Path(tmp) / "root"
            sd = Path(tmp) / "state"
            root.mkdir()
            sd.mkdir()
            api = backend.CineSortApi()
            api.save_settings(
                {
                    "root": str(root),
                    "state_dir": str(sd),
                    "tmdb_enabled": False,
                    "email_enabled": True,
                    "email_smtp_host": "smtp.x.com",
                    "email_smtp_port": 465,
                    "email_to": "a@b.c",
                }
            )
            s = api.get_settings()
            self.assertTrue(s["email_enabled"])
            self.assertEqual(s["email_smtp_host"], "smtp.x.com")
            self.assertEqual(s["email_smtp_port"], 465)
            self.assertEqual(s["email_to"], "a@b.c")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Endpoint + UI (2 tests)
# ---------------------------------------------------------------------------


class EmailEndpointAndUiTests(unittest.TestCase):
    """Tests endpoint et presence UI."""

    def test_endpoint_exists(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api, "test_email_report"))
        self.assertTrue(callable(api.test_email_report))

    def test_ui_section_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings_js = (root / "web" / "views" / "settings.js").read_text(encoding="utf-8")
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("email_enabled", settings_js)
        self.assertIn("email_smtp_host", settings_js)
        self.assertIn("email_to", settings_js)
        self.assertIn("ckEmailEnabled", html)
        self.assertIn("inEmailSmtpHost", html)
        self.assertIn("inEmailTo", html)


if __name__ == "__main__":
    unittest.main()
