"""A1 audit : detecter la derive des composants JS entre web/ (desktop, scope
global) et web/dashboard/ (SPA, ES modules).

Ces paires partagent une logique commune mais vivent dans deux architectures
JS distinctes. La dedup physique dans web/shared/ requiert un bundler et est
programmee pour le Palier 5 de l'audit. En attendant, ce test sert de
**regression checker** : il echoue si une modification future fait diverger
davantage les paires.

La similarite est calculee en Jaccard sur les lignes normalisees (imports /
exports / commentaires ignores). Chaque seuil reflete l'etat actuel; si vous
re-synchronisez les paires, remontez les seuils en consequence.
"""

from __future__ import annotations

import unittest
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1] / "web"

# (chemin_desktop, chemin_dashboard, seuil_similarite_min_jaccard)
# Les seuils sont fixes au niveau actuel moins une marge de 3-5 pts pour
# tolerer une micro-refactorisation sans alarm. Si la similarite monte apres
# une vraie dedup, remontez le seuil.
_PAIRS = [
    ("components/confetti.js", "dashboard/components/confetti.js", 0.80),
    ("components/auto-tooltip.js", "dashboard/components/auto-tooltip.js", 0.60),
    ("components/skeleton.js", "dashboard/components/skeleton.js", 0.25),
    ("core/router.js", "dashboard/core/router.js", 0.01),
]


_IGNORED_PREFIXES = ("import ", "export ", "from ", "//", "/*", "*")


def _normalize(line: str) -> str:
    """Retire les variations syntactiques qui differencient les 2 frontends."""
    stripped = line.strip()
    # Retirer les mots-cles module-scope pour que les corps de fonction soient comparables
    if stripped.startswith("export function "):
        return "function " + stripped[len("export function ") :]
    if stripped.startswith("export const "):
        return "const " + stripped[len("export const ") :]
    if stripped.startswith("export default "):
        return stripped[len("export default ") :]
    return stripped


def _read_lines(path: Path) -> list[str]:
    """Lignes non-vides, hors imports/exports/commentaires, normalisees."""
    if not path.is_file():
        return []
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            continue
        if any(s.startswith(p) for p in _IGNORED_PREFIXES):
            continue
        out.append(_normalize(s))
    return out


def _similarity(a: list[str], b: list[str]) -> float:
    """Jaccard sur les lignes normalisees (intersection / union)."""
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    union = len(set_a | set_b)
    if not union:
        return 0.0
    return len(set_a & set_b) / union


class WebComponentSyncTests(unittest.TestCase):
    def test_pairs_stay_consolidable(self) -> None:
        failures: list[str] = []
        for desktop_rel, dashboard_rel, threshold in _PAIRS:
            a = _read_lines(_ROOT / desktop_rel)
            b = _read_lines(_ROOT / dashboard_rel)
            self.assertTrue(a, msg=f"fichier vide: {desktop_rel}")
            self.assertTrue(b, msg=f"fichier vide: {dashboard_rel}")
            sim = _similarity(a, b)
            if sim < threshold:
                failures.append(
                    f"{desktop_rel} vs {dashboard_rel}: similarite {sim:.0%} < {threshold:.0%} "
                    f"(derive trop importante — re-synchroniser ou ajuster le seuil)"
                )
        self.assertEqual(failures, [], msg="\n".join(failures))


if __name__ == "__main__":
    unittest.main()
