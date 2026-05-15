"""Script one-shot pour issue #86 (PR 1) : remplacer les monkey-patches
`core.MIN_VIDEO_BYTES = 1` par `mock.patch.object` + `addCleanup`.

Pattern detecte (unittest.TestCase setUp/tearDown) :

    def setUp(self):
        ...
        self._min_video_bytes = core.MIN_VIDEO_BYTES
        core.MIN_VIDEO_BYTES = 1

    def tearDown(self):
        core.MIN_VIDEO_BYTES = self._min_video_bytes
        ...

Pattern apres migration :

    def setUp(self):
        ...
        # Issue #86 : mock.patch.object pour auto-restore safe meme si exception
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self):
        ...

Le tearDown perd la ligne `core.MIN_VIDEO_BYTES = self._...`.

Usage :
    python scripts/migrate_monkeypatch_86.py            # dry-run
    python scripts/migrate_monkeypatch_86.py --apply    # applique
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


# Pattern setUp : 2 lignes
# (indentation) self._<name> = core.MIN_VIDEO_BYTES
# (indentation) core.MIN_VIDEO_BYTES = <value>
_SETUP_PATTERN = re.compile(
    r"^(?P<indent>[ \t]+)self\._(?P<name>[a-z_]+)\s*=\s*core\.MIN_VIDEO_BYTES\s*\n"
    r"(?P=indent)core\.MIN_VIDEO_BYTES\s*=\s*(?P<value>\d+)\s*\n",
    flags=re.MULTILINE,
)

# Pattern tearDown : 1 ligne
# (indentation) core.MIN_VIDEO_BYTES = self._<name>
_TEARDOWN_PATTERN = re.compile(
    r"^[ \t]+core\.MIN_VIDEO_BYTES\s*=\s*self\._[a-z_]+\s*\n",
    flags=re.MULTILINE,
)


def migrate_file(path: Path, apply: bool) -> int:
    """Retourne le nombre de patterns remplaces."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0

    original = content
    setup_count = 0
    teardown_count = 0

    def _replace_setup(m: re.Match[str]) -> str:
        nonlocal setup_count
        setup_count += 1
        indent = m.group("indent")
        value = m.group("value")
        return (
            f"{indent}# Issue #86 : mock.patch.object pour auto-restore safe meme si exception\n"
            f'{indent}_p_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", {value})\n'
            f"{indent}_p_min_video.start()\n"
            f"{indent}self.addCleanup(_p_min_video.stop)\n"
        )

    content = _SETUP_PATTERN.sub(_replace_setup, content)

    # Pour le tearDown : on supprime la ligne (le cleanup est gere par addCleanup)
    new_content, teardown_count = _TEARDOWN_PATTERN.subn("", content)

    if setup_count > 0 or teardown_count > 0:
        # Verifier que `from unittest import mock` (ou equivalent) existe
        if "from unittest import mock" not in new_content and "from unittest.mock" not in new_content:
            # Ajouter `from unittest import mock` apres les autres imports unittest
            import_pat = re.compile(r"^import unittest\s*$", re.MULTILINE)
            m = import_pat.search(new_content)
            if m:
                insert_pos = m.end()
                new_content = new_content[:insert_pos] + "\nfrom unittest import mock" + new_content[insert_pos:]

        if apply:
            path.write_text(new_content, encoding="utf-8")

    return setup_count + teardown_count


def main() -> int:
    apply = "--apply" in sys.argv
    files = sorted(Path("tests").rglob("*.py"))

    print(f"Mode : {'APPLY' if apply else 'DRY-RUN'}")
    total = 0
    for path in files:
        n = migrate_file(path, apply)
        if n > 0:
            print(f"  [{n}x]  {path}")
            total += n

    print(f"\nTotal : {total} patterns migres (setup + teardown)")
    if not apply:
        print("(dry-run : aucun fichier modifie. Relancer avec --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
