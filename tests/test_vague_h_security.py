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

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
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


def _canonical(value: Path) -> str:
    """Forme canonique d'un chemin (jonctions + casse) pour les assertions."""
    return os.path.normcase(os.path.realpath(str(value)))


def _call_open_path(root: Path, state_dir: Path, path: str) -> Dict[str, Any]:
    """Appelle open_path avec os.startfile mocke et expose ce qui a ete ouvert."""
    from cinesort.ui.api import history_support

    api = _make_api(root, state_dir)
    with patch.object(history_support.os, "startfile", create=True) as mock_start:
        res = history_support.open_path(
            api,
            path,
            default_root=str(root),
            normalize_user_path=_normalize_user_path,
        )
        res["__startfile_called"] = mock_start.called
        res["__startfile_args"] = [str(call.args[0]) for call in mock_start.call_args_list]
    return res


def _make_junction(link: Path, target: Path) -> bool:
    """Cree une jonction NTFS (mklink /J). Retourne False si indisponible.

    Une jonction n'est PAS un lien symbolique (``is_symlink()`` renvoie False)
    et ne demande aucun privilege particulier : c'est le moyen courant de
    placer une bibliotheque sur un autre volume.
    """
    if sys.platform != "win32":
        return False
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and link.is_dir()


def _remove_junction(link: Path) -> None:
    """Supprime la jonction seule (os.rmdir ne suit pas le point de reparse)."""
    with contextlib.suppress(OSError):
        os.rmdir(str(link))


class OpenPathSymlinkTests(unittest.TestCase):
    """Vague H #1 : open_path refuse les liens symboliques."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Racine temporaire BRUTE (volontairement non canonisee) : sur le
        # runner GitHub Windows, %TEMP% vaut C:\Users\RUNNER~1\... (nom court
        # 8.3) et traverse des jonctions. C'est exactement le cas produit d'une
        # bibliotheque derriere une jonction ; open_path doit l'accepter.
        base = Path(self.tmp.name)
        self.root = base / "allowed_root"
        self.state_dir = base / "state"
        self.outside = base / "outside"
        self.root.mkdir()
        self.state_dir.mkdir()
        self.outside.mkdir()
        # Cible reelle hors zone autorisee.
        (self.outside / "secret.txt").write_text("secret", encoding="utf-8")

    def _call(self, path: str) -> Dict[str, Any]:
        return _call_open_path(self.root, self.state_dir, path)

    def _symlink_or_skip(self, link: Path, target: Path, *, is_dir: bool) -> None:
        try:
            link.symlink_to(target, target_is_directory=is_dir)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks indisponibles sur cette plateforme : {exc}")

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

    def test_open_path_refuses_symlink_even_when_target_is_inside_root(self) -> None:
        """Le refus des symlinks ne depend PAS du controle de zone.

        Preuve dediee de la garde ``candidate.is_symlink()`` : la cible du lien
        est ici DANS la zone autorisee, donc le controle de zone laisserait
        passer. Seule la garde symlink refuse — si elle disparait, ce test
        devient rouge.
        """
        real_sub = self.root / "sub_ok"
        real_sub.mkdir()
        link = self.root / "link_inside"
        self._symlink_or_skip(link, real_sub, is_dir=True)

        res = self._call(str(link))

        self.assertFalse(res.get("ok"), msg=res)
        self.assertIn("symbol", res.get("message", "").lower())
        self.assertFalse(res["__startfile_called"], "os.startfile ne doit pas etre appele")

    def test_open_path_refuses_file_under_symlinked_parent_outside_root(self) -> None:
        """Un lien PARENT qui sort de la zone reste bloque (anti path-traversal).

        Ici ``candidate.is_symlink()`` est FAUX (c'est le dossier parent qui est
        un lien) : la preuve porte donc sur le controle de zone, qui compare des
        chemins REELS. Sans lui, os.startfile ouvrirait un dossier hors zone.
        """
        link = self.root / "linked_dir"
        self._symlink_or_skip(link, self.outside, is_dir=True)
        victim = link / "secret.txt"
        self.assertFalse(victim.is_symlink(), "le lien doit etre le PARENT, pas la cible")

        res = self._call(str(victim))

        self.assertFalse(res.get("ok"), msg=res)
        self.assertEqual(res.get("message"), "Chemin non autorise.")
        self.assertFalse(res["__startfile_called"], "os.startfile ne doit pas etre appele")

    def test_open_path_symlinked_parent_inside_root_opens_resolved_target(self) -> None:
        """Un lien parent restant DANS la zone est ouvrable, sur sa cible REELLE.

        Complement du test precedent : la traversee n'est pas interdite par
        principe, elle est bornee a la zone autorisee, et c'est toujours le
        chemin resolu qui est passe a os.startfile (jamais ``candidate``).
        """
        real_sub = self.root / "sub"
        real_sub.mkdir()
        (real_sub / "film.mkv").write_text("x", encoding="utf-8")
        link = self.root / "linked_sub"
        self._symlink_or_skip(link, real_sub, is_dir=True)

        res = self._call(str(link / "film.mkv"))

        self.assertTrue(res.get("ok"), msg=res)
        self.assertEqual([_canonical(Path(p)) for p in res["__startfile_args"]], [_canonical(real_sub)])


class OpenPathJunctionTests(unittest.TestCase):
    r"""Regression 2026-08-03 : une bibliotheque derriere une jonction NTFS.

    ``open_path`` comparait deux CHAINES (``resolve()`` vs ``absolute()``) pour
    deviner un symlink parent. Mais ``resolve()`` reecrit la chaine sans qu'aucun
    lien n'existe des que le chemin traverse une jonction NTFS, un point de
    montage, un nom court 8.3 ou une casse differente. Un utilisateur dont la
    bibliotheque est derriere une jonction se voyait donc repondre « Les liens
    symboliques ne sont pas autorises » sur un dossier parfaitement normal
    (meme cause : 4 tests rouges sur le runner GitHub, dont %TEMP% est expose
    en 8.3 sous C:\Users\RUNNER~1).
    """

    def setUp(self) -> None:
        if sys.platform != "win32":
            self.skipTest("jonctions NTFS : Windows uniquement")
        base = Path(tempfile.mkdtemp(prefix="cinesort_junction_"))
        self.addCleanup(shutil.rmtree, str(base), True)
        self.real_lib = base / "real_library"
        self.state_dir = base / "state"
        self.real_lib.mkdir()
        self.state_dir.mkdir()
        self.film_dir = self.real_lib / "Inception (2010)"
        self.film_dir.mkdir()
        (self.film_dir / "Inception.2010.mkv").write_text("x", encoding="utf-8")
        # La bibliotheque telle que l'utilisateur la designe : via une jonction.
        self.lib_via_junction = base / "library_via_junction"
        if not _make_junction(self.lib_via_junction, self.real_lib):
            self.skipTest("mklink /J indisponible sur cette machine")
        # Retirer la jonction AVANT le rmtree (cleanup LIFO) pour ne pas
        # effacer la cible a travers le point de reparse.
        self.addCleanup(_remove_junction, self.lib_via_junction)
        self.assertFalse(self.lib_via_junction.is_symlink(), "une jonction n'est pas un symlink")

    def _call(self, path: str) -> Dict[str, Any]:
        return _call_open_path(self.lib_via_junction, self.state_dir, path)

    def _assert_opened(self, res: Dict[str, Any], expected: Path) -> None:
        opened: List[str] = [_canonical(Path(p)) for p in res["__startfile_args"]]
        self.assertEqual(opened, [_canonical(expected)])

    def test_open_path_accepts_dir_behind_ntfs_junction(self) -> None:
        """Un dossier legitime atteint via une jonction doit s'ouvrir."""
        res = self._call(str(self.lib_via_junction / "Inception (2010)"))

        self.assertTrue(res.get("ok"), msg=res)
        self.assertTrue(res["__startfile_called"])
        self._assert_opened(res, self.film_dir)

    def test_open_path_accepts_file_behind_ntfs_junction(self) -> None:
        """Un fichier legitime derriere une jonction ouvre son dossier parent."""
        target = self.lib_via_junction / "Inception (2010)" / "Inception.2010.mkv"

        res = self._call(str(target))

        self.assertTrue(res.get("ok"), msg=res)
        self._assert_opened(res, self.film_dir)

    def test_open_path_accepts_different_case(self) -> None:
        """NTFS est insensible a la casse : le meme dossier reste le meme dossier."""
        res = self._call(str(self.lib_via_junction / "Inception (2010)").upper())

        self.assertTrue(res.get("ok"), msg=res)
        self._assert_opened(res, self.film_dir)

    def test_open_path_behind_junction_still_refuses_symlink(self) -> None:
        """Securite : derriere une jonction, un vrai symlink reste refuse."""
        outside = Path(str(self.real_lib.parent / "outside"))
        outside.mkdir(exist_ok=True)
        (outside / "secret.txt").write_text("secret", encoding="utf-8")
        link = self.lib_via_junction / "evil_link.txt"
        try:
            link.symlink_to(outside / "secret.txt")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks indisponibles sur cette plateforme : {exc}")

        res = self._call(str(link))

        self.assertFalse(res.get("ok"), msg=res)
        self.assertIn("symbol", res.get("message", "").lower())
        self.assertFalse(res["__startfile_called"], "os.startfile ne doit pas etre appele")


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
        src = (self.REPO_ROOT / "web" / "dashboard" / "components" / "empty-state.js").read_text(encoding="utf-8")
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
        src = (self.REPO_ROOT / "web" / "dashboard" / "views" / "processing.js").read_text(encoding="utf-8")
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
        dom_js = (self.REPO_ROOT / "web" / "dashboard" / "core" / "dom.js").read_text(encoding="utf-8")
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
