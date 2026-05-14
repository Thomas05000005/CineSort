"""Property-based tests pour cinesort.domain.naming (issue #87).

Utilise hypothesis pour generer des inputs aleatoires et valider des
proprietes invariantes (pas des cas precis hardcoded).

Si hypothesis n'est pas installe (env local minimal), le module entier
est skip — pas de failure import. La CI a hypothesis dans requirements-dev.txt.
"""

from __future__ import annotations

import unittest

try:
    from hypothesis import HealthCheck, given, settings, strategies as st

    HYPOTHESIS_AVAILABLE = True
except ImportError:  # pragma: no cover — local minimal env
    HYPOTHESIS_AVAILABLE = False

    # Stubs no-op pour que les decorateurs @given/@settings n'echouent pas
    # a l'import du module quand hypothesis est absent. Les classes elles-memes
    # sont skip via @unittest.skipUnless.
    def given(*_args, **_kwargs):
        def _decorator(fn):
            return fn

        return _decorator

    def settings(*_args, **_kwargs):
        def _decorator(fn):
            return fn

        return _decorator

    class _StubStrategy:
        """Strategy stub qui supporte .filter()/.map()/etc. en no-op."""

        def __getattr__(self, _name):
            # Toute methode (filter, map, ...) retourne self pour chainage
            return lambda *_a, **_kw: self

    class _StStub:
        """Stub pour hypothesis.strategies — retourne _StubStrategy partout."""

        def __getattr__(self, _name):
            def _factory(*_a, **_kw):
                return _StubStrategy()

            return _factory

    st = _StStub()

    class HealthCheck:
        too_slow = None


from cinesort.domain.core import windows_safe
from cinesort.domain.naming import (
    build_naming_context,
    format_movie_folder,
    validate_template,
)


@unittest.skipUnless(HYPOTHESIS_AVAILABLE, "hypothesis not installed")
class WindowsSafeProperties(unittest.TestCase):
    """Proprietes invariantes de windows_safe."""

    @settings(max_examples=200, deadline=500)
    @given(st.text(min_size=1, max_size=300))
    def test_output_never_contains_forbidden_chars(self, name: str) -> None:
        """Quel que soit le nom d'entree, la sortie ne contient pas <>:\"/\\|?*."""
        out = windows_safe(name)
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, out)

    @settings(max_examples=100, deadline=500)
    @given(st.text(min_size=1, max_size=300))
    def test_output_length_capped_at_180(self, name: str) -> None:
        """windows_safe coupe a 180 chars max."""
        out = windows_safe(name)
        self.assertLessEqual(len(out), 180)

    @settings(max_examples=100, deadline=500)
    @given(st.text(min_size=1, max_size=200))
    def test_idempotent(self, name: str) -> None:
        """windows_safe(windows_safe(x)) == windows_safe(x)."""
        once = windows_safe(name)
        twice = windows_safe(once)
        self.assertEqual(once, twice)

    @settings(max_examples=100, deadline=500)
    @given(st.text(min_size=1, max_size=100))
    def test_output_never_empty(self, name: str) -> None:
        """Meme avec n'importe quel input, l'output n'est jamais vide (fallback _untitled)."""
        out = windows_safe(name)
        self.assertGreater(len(out), 0)


@unittest.skipUnless(HYPOTHESIS_AVAILABLE, "hypothesis not installed")
class FormatMovieFolderProperties(unittest.TestCase):
    """Proprietes invariantes de format_movie_folder."""

    @settings(max_examples=100, deadline=500, suppress_health_check=[HealthCheck.too_slow])
    @given(
        title=st.text(min_size=1, max_size=80).filter(lambda s: s.strip()),
        year=st.integers(min_value=1900, max_value=2099),
    )
    def test_output_contains_no_forbidden_chars(self, title: str, year: int) -> None:
        """Output ne contient jamais de chars Windows-interdits."""
        ctx = build_naming_context(title=title, year=year)
        out = format_movie_folder("{title} ({year})", ctx)
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, out)

    @settings(max_examples=100, deadline=500, suppress_health_check=[HealthCheck.too_slow])
    @given(
        title=st.text(min_size=1, max_size=80).filter(lambda s: s.strip()),
        year=st.integers(min_value=1900, max_value=2099),
    )
    def test_output_length_under_180(self, title: str, year: int) -> None:
        """Output respecte la limite Windows segment 180."""
        ctx = build_naming_context(title=title, year=year)
        out = format_movie_folder("{title} ({year})", ctx)
        self.assertLessEqual(len(out), 180)

    @settings(max_examples=50, deadline=500, suppress_health_check=[HealthCheck.too_slow])
    @given(
        title=st.text(min_size=1, max_size=80).filter(lambda s: s.strip()),
        year=st.integers(min_value=1900, max_value=2099),
    )
    def test_output_never_empty(self, title: str, year: int) -> None:
        ctx = build_naming_context(title=title, year=year)
        out = format_movie_folder("{title} ({year})", ctx)
        self.assertGreater(len(out), 0)


@unittest.skipUnless(HYPOTHESIS_AVAILABLE, "hypothesis not installed")
class ValidateTemplateProperties(unittest.TestCase):
    """Proprietes invariantes de validate_template."""

    @settings(max_examples=100, deadline=500)
    @given(st.text(min_size=0, max_size=200))
    def test_returns_tuple_bool_list(self, template: str) -> None:
        """Quel que soit l'input, retour (bool, list[str])."""
        ok, errors = validate_template(template)
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(errors, list)
        # Si invalid, au moins 1 message d'erreur ; si valid, 0
        if ok:
            self.assertEqual(errors, [])
        else:
            self.assertGreater(len(errors), 0)

    @settings(max_examples=50, deadline=500)
    @given(st.text(min_size=0, max_size=10))
    def test_empty_or_whitespace_is_invalid(self, template: str) -> None:
        """Template vide ou whitespace-only doit etre invalide."""
        # Restreindre aux espaces/whitespace
        whitespace_only = template.strip() == ""
        if whitespace_only:
            ok, _errors = validate_template(template)
            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
