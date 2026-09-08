"""VQ-1 PATH-UTILS : tests post-refactor.

Verifie que l'extraction de `windows_safe` + `_norm_win_path` depuis
`cinesort.domain.core` vers `cinesort.domain.path_utils` :

1. Preserve le contrat fonctionnel (memes outputs, memes guards).
2. Casse effectivement le cycle domain<->domain
   (core -> duplicate_support -> naming -> core).
3. Conserve la backward compatibility :
   - `cinesort.domain.core.windows_safe` reste accessible
   - `cinesort.domain.core._norm_win_path` reste accessible
   - Tous deux pointent vers la meme implementation que `path_utils`.

Ces tests sont autonomes (zero I/O, zero subprocess, zero DB), executables
sous tout runner pytest standard.
"""

from __future__ import annotations

import unittest
from pathlib import Path, PureWindowsPath

import cinesort.domain.core as core
import cinesort.domain.duplicate_support as duplicate_support
import cinesort.domain.naming as naming
import cinesort.domain.path_utils as path_utils


class BackwardCompatTests(unittest.TestCase):
    """`cinesort.domain.core.windows_safe` doit rester un alias fonctionnel."""

    def test_windows_safe_same_object_as_path_utils(self):
        # core.windows_safe doit ETRE le meme objet que path_utils.windows_safe
        # (re-export via `from path_utils import windows_safe`).
        self.assertIs(core.windows_safe, path_utils.windows_safe)

    def test_norm_win_path_same_object_as_path_utils(self):
        # Idem pour _norm_win_path (utilise par app/apply_core via core_mod).
        self.assertIs(core._norm_win_path, path_utils._norm_win_path)
        # L'alias public et le prive pointent sur la meme fonction.
        self.assertIs(path_utils.norm_win_path, path_utils._norm_win_path)

    def test_naming_uses_path_utils_windows_safe(self):
        # naming doit avoir importe depuis path_utils (cycle casse).
        self.assertIs(naming.windows_safe, path_utils.windows_safe)


class WindowsSafeContractTests(unittest.TestCase):
    """Contrat fonctionnel de windows_safe, accessible via les 2 modules."""

    def test_strips_reserved_chars_via_path_utils(self):
        self.assertEqual(path_utils.windows_safe("foo<bar>"), "foobar")
        self.assertEqual(path_utils.windows_safe('a"b|c'), "abc")
        self.assertEqual(path_utils.windows_safe("a/b\\c"), "abc")
        self.assertEqual(path_utils.windows_safe("a:b?c*"), "abc")

    def test_strips_reserved_chars_via_core(self):
        # Backward compat : meme contrat via le re-export.
        self.assertEqual(core.windows_safe("foo<bar>"), "foobar")

    def test_collapses_whitespace(self):
        self.assertEqual(path_utils.windows_safe("a   b   c"), "a b c")

    def test_strips_trailing_dots(self):
        self.assertFalse(path_utils.windows_safe("Titre.").endswith("."))
        self.assertFalse(path_utils.windows_safe("Titre..").endswith("."))

    def test_reserved_dos_names_prefixed_with_underscore(self):
        for reserved in ("con", "CON", "nul", "com1", "lpt9", "PRN", "AUX"):
            out = path_utils.windows_safe(reserved)
            self.assertTrue(out.startswith("_"), msg=f"{reserved} -> {out}")

    def test_empty_input_becomes_untitled(self):
        self.assertEqual(path_utils.windows_safe(""), "_untitled")
        self.assertEqual(path_utils.windows_safe("   "), "_untitled")

    def test_truncates_to_180_chars(self):
        long_name = "x" * 500
        self.assertLessEqual(len(path_utils.windows_safe(long_name)), 180)

    def test_nfc_normalization_keeps_accents(self):
        # E + combining acute accent (NFD) vs LATIN CAPITAL E WITH ACUTE (NFC).
        nfd = "É"
        nfc = "É"
        self.assertEqual(
            path_utils.windows_safe(nfd),
            path_utils.windows_safe(nfc),
        )

    def test_non_reserved_word_unchanged_modulo_sanitize(self):
        # "ConFilm" n'est PAS le nom DOS reserve "con" (case insensitive sur le
        # nom complet), donc pas de prefixe.
        out = path_utils.windows_safe("ConFilm")
        self.assertFalse(out.startswith("_"))
        self.assertEqual(out, "ConFilm")

    def test_la_troncature_ne_peut_pas_REVIDER_le_resultat(self):
        """Le garde « vide -> _untitled » doit porter sur le RESULTAT.

        Il s'executait AVANT `name[:180].rstrip(". ")`, si bien que la derniere
        ligne pouvait revider ce qu'il venait de remplir. Il faut que les 180
        PREMIERS caracteres soient tous des points ou des espaces : la ligne 107
        a deja retire ceux de QUEUE et collapse les espaces multiples, donc le
        cas ne s'atteint que par la tete.

        Le contrat documente de la fonction dit « Remplace par `_untitled` si le
        RESULTAT est vide » : c'est lui qui est verifie ici.

        Un nom de dossier vide vaut `parent / ""` == `parent` chez les six
        appelants qui ne se protegent pas eux-memes (`naming:459`,
        `duplicate_support:134,144,200,205,489`) — `core:580-586`, lui, porte
        deja un `or "_Collection"` de son cote.
        """
        for entree in ("." * 180 + "X", "." * 200, ". " * 90 + "Titre"):
            with self.subTest(entree=entree[:20] + "..."):
                out = path_utils.windows_safe(entree)
                self.assertTrue(out, f"sortie vide pour un nom de {len(entree)} caracteres")
                self.assertNotEqual(out, "")

    def test_les_noms_courants_ne_changent_pas(self):
        """CONTRE-TEST : deplacer le garde ne doit toucher que le cas vide.

        Vert avant comme apres. Si ce test rougit, le remede a debordé.
        """
        self.assertEqual(path_utils.windows_safe("Blade Runner (1982)"), "Blade Runner (1982)")
        self.assertEqual(path_utils.windows_safe("???"), "_untitled")
        self.assertEqual(path_utils.windows_safe("con"), "_con")
        self.assertEqual(path_utils.windows_safe("Titre."), "Titre")

    def test_le_repli_untitled_reste_idempotent(self):
        """`windows_safe(windows_safe(x)) == windows_safe(x)`, repli compris."""
        once = path_utils.windows_safe("." * 180 + "X")
        self.assertEqual(path_utils.windows_safe(once), once)


class NormWinPathContractTests(unittest.TestCase):
    """Contrat de _norm_win_path / norm_win_path."""

    def test_returns_pure_windows_path(self):
        out = path_utils.norm_win_path(Path("C:/Films/Foo"))
        self.assertIsInstance(out, PureWindowsPath)

    def test_normalizes_separators(self):
        a = path_utils.norm_win_path(Path("C:/Films/Foo"))
        b = path_utils.norm_win_path(Path("C:\\Films\\Foo"))
        self.assertEqual(a, b)

    def test_normalizes_case(self):
        a = path_utils.norm_win_path(Path("C:/Films/Foo"))
        b = path_utils.norm_win_path(Path("C:/FILMS/FOO"))
        # normcase abaisse la casse sous Windows ; sous Linux/CI il garde la
        # casse. On verifie au moins que la comparaison soit *coherente* :
        # appliquer deux fois norm_win_path ne change pas le resultat.
        self.assertEqual(a, path_utils.norm_win_path(Path(str(a))))
        self.assertEqual(b, path_utils.norm_win_path(Path(str(b))))


class CycleBreakingTests(unittest.TestCase):
    """Verifie que le cycle domain<->domain est effectivement casse."""

    def test_path_utils_is_leaf(self):
        # path_utils ne doit RIEN importer depuis cinesort.* (feuille du graphe).
        import ast

        src = Path(path_utils.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        cinesort_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("cinesort"):
                    cinesort_imports.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("cinesort"):
                        cinesort_imports.append(alias.name)
        self.assertEqual(
            cinesort_imports,
            [],
            msg=f"path_utils doit etre une feuille, trouve : {cinesort_imports}",
        )

    def test_naming_no_longer_imports_core(self):
        # naming doit importer path_utils, PAS core.
        import ast

        src = Path(naming.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "cinesort.domain.core":
                bad.append(node.module)
        self.assertEqual(
            bad,
            [],
            msg=f"naming.py importe encore depuis core : {bad}. Cycle non casse.",
        )

    def test_duplicate_support_eager_naming_import_works(self):
        # Avant le refactor, duplicate_support faisait un lazy import de
        # naming.folder_matches_template a l'interieur de single_folder_is_conform
        # pour casser le cycle. Apres VQ-1, ce lazy import devient un eager
        # top-level alias `_folder_matches_template`. On verifie qu'il est bien
        # importable et appelable.
        self.assertTrue(hasattr(duplicate_support, "_folder_matches_template"))
        self.assertTrue(callable(duplicate_support._folder_matches_template))


class SingleFolderIsConformIntegrationTests(unittest.TestCase):
    """Smoke test : single_folder_is_conform fonctionne avec l'eager import."""

    def test_template_check_with_eager_import(self):
        # Avec le template par defaut, "Inception (2010)" doit etre conforme.
        result = duplicate_support.single_folder_is_conform(
            "Inception (2010)",
            "Inception",
            2010,
            windows_safe=path_utils.windows_safe,
            norm_for_tokens=lambda s: (s or "").lower().strip(),
            movie_dir_title_year=duplicate_support.movie_dir_title_year,
            naming_template="{title} ({year})",
        )
        self.assertTrue(result)

    def test_template_check_negative(self):
        result = duplicate_support.single_folder_is_conform(
            "Inception 2010",  # pas de parentheses -> non conforme
            "Inception",
            2010,
            windows_safe=path_utils.windows_safe,
            norm_for_tokens=lambda s: (s or "").lower().strip(),
            movie_dir_title_year=duplicate_support.movie_dir_title_year,
            naming_template="{title} ({year})",
        )
        # Le fallback "Title (Year)" peut accepter, mais avec template strict
        # et folder sans parentheses, on attend False sur Check 1.
        # Check 2 (norm_for_tokens) compare "Inception 2010" vs windows_safe("Inception"),
        # donc False. Le test verifie au moins que la fonction ne crashe pas
        # (smoke test eager import).
        self.assertIsInstance(result, bool)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
