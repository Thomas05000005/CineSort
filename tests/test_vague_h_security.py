"""Tests Vague H (v1.5.3) - corrections de securite XSS et path traversal.

Fix audit 2026-05-25 (v1.5.3) Vague H.

Couvre deux corrections :

1. ``cinesort.ui.api.history_support.open_path`` refuse les symlinks pour
   eviter une traversee de chemin (le code ouvrait ``candidate`` non-resolu
   alors que la verification d'autorisation portait sur ``resolved_path``).

2. ``web/dashboard/components/empty-state.js::buildEmptyState`` echappe tous
   ses parametres via ``escapeHtml`` (sanity check statique, le composant
   etant ES module sans infra de test JS dans ce repo).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# FIX 1 - open_path : refus des symlinks
# ---------------------------------------------------------------------------


def _make_api(root: Path, state_dir: Path) -> MagicMock:
    api = MagicMock()
    api.settings.get_settings.return_value = {
        "root": str(root),
        "state_dir": str(state_dir),
    }
    return api


def _normalize_user_path(value: Any, default: Path) -> Path:
    if value is None or value == "":
        return Path(default)
    return Path(str(value))


class OpenPathSymlinkTests(unittest.TestCase):
    """Vague H #1 : open_path refuse les liens symboliques."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "allowed_root"
        self.state_dir = Path(self.tmp.name) / "state"
        self.outside = Path(self.tmp.name) / "outside"
        self.root.mkdir()
        self.state_dir.mkdir()
        self.outside.mkdir()
        # Cible reelle hors zone autorisee.
        (self.outside / "secret.txt").write_text("secret", encoding="utf-8")

    def _call(self, path: str) -> Dict[str, Any]:
        from cinesort.ui.api import history_support

        api = _make_api(self.root, self.state_dir)
        with patch.object(history_support.os, "startfile", create=True) as mock_start:
            res = history_support.open_path(
                api,
                path,
                default_root=str(self.root),
                normalize_user_path=_normalize_user_path,
            )
            res["__startfile_called"] = mock_start.called
        return res

    def test_open_path_refuses_symlink_file(self) -> None:
        """Un symlink fichier place dans la zone autorisee doit etre refuse."""
        link = self.root / "evil_link.txt"
        try:
            link.symlink_to(self.outside / "secret.txt")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks indisponibles sur cette plateforme : {exc}")
            return

        res = self._call(str(link))

        self.assertFalse(res.get("ok"))
        self.assertIn("symbol", res.get("message", "").lower())
        self.assertFalse(res["__startfile_called"], "os.startfile ne doit pas etre appele")

    def test_open_path_refuses_symlink_dir(self) -> None:
        """Un symlink dossier place dans la zone autorisee doit etre refuse."""
        link = self.root / "evil_dir"
        try:
            link.symlink_to(self.outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks indisponibles sur cette plateforme : {exc}")
            return

        res = self._call(str(link))

        self.assertFalse(res.get("ok"))
        self.assertFalse(res["__startfile_called"])

    def test_open_path_accepts_regular_path_in_root(self) -> None:
        """Sanity : un fichier reel dans la zone autorisee continue de marcher."""
        real = self.root / "legit.txt"
        real.write_text("ok", encoding="utf-8")

        res = self._call(str(real))

        self.assertTrue(res.get("ok"), msg=res)
        self.assertTrue(res["__startfile_called"])

    def test_open_path_rejects_outside_root(self) -> None:
        """Sanity : un chemin hors zone autorisee est refuse (non-regression)."""
        real = self.outside / "secret.txt"

        res = self._call(str(real))

        self.assertFalse(res.get("ok"))
        self.assertFalse(res["__startfile_called"])


# ---------------------------------------------------------------------------
# FIX 2 - buildEmptyState : escapeHtml sur tous les champs (sanity statique)
# ---------------------------------------------------------------------------


class BuildEmptyStateEscapeTests(unittest.TestCase):
    """Vague H #2 : sanity statique JS, faute d'infra de test JS dans ce repo.

    On verifie que ``buildEmptyState`` echappe explicitement chaque champ
    user-facing via ``escapeHtml``, et que ``processing.js`` ne re-echappe
    plus le message (eviter le double-echappement).
    """

    REPO_ROOT = Path(__file__).resolve().parent.parent

    def test_buildEmptyState_escapes_all_user_fields(self) -> None:
        src = (self.REPO_ROOT / "web" / "dashboard" / "components" / "empty-state.js").read_text(
            encoding="utf-8"
        )
        # Import explicite de escapeHtml depuis le helper centralise.
        self.assertIn('import { escapeHtml } from "../core/dom.js"', src)
        # Champs user-facing : title, message, ctaLabel doivent etre echappes.
        for field in ("title", "message", "ctaLabel", "ctaRoute", "testId"):
            self.assertIn(
                f"escapeHtml({field})",
                src,
                msg=f"buildEmptyState doit echapper le champ {field!r}",
            )

    def test_processing_view_does_not_double_escape(self) -> None:
        src = (self.REPO_ROOT / "web" / "dashboard" / "views" / "processing.js").read_text(
            encoding="utf-8"
        )
        # Ligne fixee : message ne doit plus etre pre-echappe car
        # buildEmptyState le fait deja.
        self.assertNotIn("message: _esc(msg)", src)
        # Le commentaire Vague H doit etre present pour traceabilite.
        self.assertIn("Vague H", src)

    def test_escapeHtml_handles_script_tag(self) -> None:
        """Sanity : la fonction escapeHtml exportee echappe bien <script>.

        On parse la regex de remplacement pour confirmer le comportement
        (faute d'environnement JS, on imite la logique).
        """
        dom_js = (self.REPO_ROOT / "web" / "dashboard" / "core" / "dom.js").read_text(
            encoding="utf-8"
        )
        # Verifie que les 5 remplacements XSS-safe sont presents.
        for entity in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
            self.assertIn(entity, dom_js, msg=f"escapeHtml doit produire {entity}")


# ---------------------------------------------------------------------------
# Compat : permettre `python -m unittest tests.test_vague_h_security`
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Si lance directement, garantir que le repo root est sur sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    unittest.main()
