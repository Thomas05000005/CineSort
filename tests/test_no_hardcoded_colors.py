"""V3-10 — Verifie qu'on n'introduit pas de nouveaux hardcodes couleurs.

Politique :
- Les tier colors (Platinum/Gold/Silver/Bronze/Reject/Unknown) sont invariantes
  cross-themes : on les tolere partout (definitions et usages).
- Les fallbacks `var(--token, #color)` sont legitimes (defense en profondeur)
  et ne sont pas comptes comme hardcodes.
- Les definitions de variables CSS (`--token: #color;`) sont la source des
  tokens, donc tolerees.
- Le reste doit etre minimal (gradient SVG complexes, contrastes #fff/#000).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


# Hardcodes toleres : tier colors (invariantes), severities du design system v5,
# couleurs de marque services tiers, contrastes purs.
ALLOWED_HARDCODES = {
    # Blanc / noir purs (contraste sur surfaces colorees)
    "#FFFFFF",
    "#ffffff",
    "#FFF",
    "#fff",
    "#000000",
    "#000",
    # Tier colors — JS code (Platinum/Gold/Silver/Bronze/Reject)
    # Ces couleurs sont invariantes par design (cf badge.js, library.js, etc.)
    "#A78BFA",
    "#a78bfa",  # Platinum (lavender)
    "#FBBF24",
    "#fbbf24",  # Gold / warning
    "#9CA3AF",
    "#9ca3af",  # Silver
    "#FB923C",
    "#fb923c",  # Bronze / orange accent
    "#EF4444",
    "#ef4444",  # Reject / danger-strong
    "#A7F3D0",
    "#a7f3d0",  # vert clair (delta library)
    "#FCA5A5",
    "#fca5a5",  # rouge clair (delta library)
    # Tier colors — design system v5 (tokens.css)
    "#FFD700",  # tier-platinum-solid (or)
    "#22C55E",  # tier-gold-solid (vert)
    "#3B82F6",
    "#3b82f6",  # tier-silver-solid (bleu) / accent-hover
    "#F59E0B",
    "#f59e0b",  # tier-bronze-solid / gold token
    "#6B7280",
    "#6b7280",  # tier-unknown-solid
    # Tier gradient companion colors (depth-effects, .bg-* gradients)
    "#E4E4E7",
    "#e4e4e7",
    "#A1A1AA",
    "#a1a1aa",  # tier-platinum legacy
    "#C0C0CC",
    "#c0c0cc",
    "#8B8B96",
    "#8b8b96",  # tier-silver legacy
    "#CD7F32",
    "#cd7f32",
    "#8B4513",
    "#8b4513",  # tier-bronze legacy
    "#D4A017",
    "#d4a017",  # platinum gradient end
    "#16A34A",
    "#16a34a",  # gold gradient end
    "#2563EB",
    "#2563eb",  # silver gradient end
    "#D97706",
    "#d97706",  # bronze gradient end
    "#B91C1C",
    "#b91c1c",  # reject gradient end
    # Severity colors invariantes (design system)
    "#34D399",
    "#34d399",  # success
    "#F87171",
    "#f87171",  # danger
    "#60A5FA",
    "#60a5fa",  # accent / info bleu
    "#38BDF8",
    "#38bdf8",  # info cyan
    "#DC2626",
    "#dc2626",  # critical
    "#22D3EE",
    "#22d3ee",  # cyan accent (root-level)
    "#A855F7",
    "#a855f7",  # purple (saga)
    # Couleurs de marque (services tiers — ne doivent pas changer)
    "#00A4DC",  # Jellyfin
    "#282A2D",
    "#EBAF00",  # Plex
    "#FFC230",  # Emby
    "#01B4E4",  # TMDb
    # Surface dashboard tokens (definitions :root)
    "#06090F",
    "#0C1219",
    "#131B27",
    "#1A2435",
    "#06090f",
    "#0c1219",
    "#131b27",
    "#1a2435",
    # Text dashboard tokens
    "#E8ECF1",
    "#8B97AB",
    "#4A5568",
    "#6B7A95",
    "#e8ecf1",
    "#8b97ab",
    "#4a5568",
    "#6b7a95",
    # Accents / contrast
    "#1a0b33",  # contraste sur lavender CTA legacy
    "#4DA3FF",
    "#4da3ff",  # accent fallback about modal legacy
    "#9aa0a6",  # text-muted fallback about modal
    "#2ECC71",  # privacy badge about modal
    "#818CF8",
    "#818cf8",  # accent companion gradients
    "#93C5FD",
    "#93c5fd",  # accent light gradient
    "#6EE7B7",
    "#6ee7b7",  # success light gradient
    "#FCD34D",
    "#fcd34d",  # warning light gradient
    # Light theme fallback values (legacy web/styles.css :root[data-theme=light])
    "#F4F6FA",
    "#FFFFFF",
    "#EEF2F7",
    "#E4E9F0",
    "#102033",
    "#5C6F86",
    "#70839B",
    "#2563EB",
    "#0284C7",
    "#059669",
    "#D97706",
}

# Patterns pour ignorer les hardcodes legitimes :
# - Definitions de variables CSS : `--xxx: #color;` ou `--xxx-rgb: ...`
VAR_DEF_PATTERN = re.compile(r"--[\w-]+\s*:")
# - Fallbacks dans var() : `var(--token, #color)` ou imbrique
VAR_FALLBACK_PATTERN = re.compile(r"var\([^)]*#[0-9a-fA-F]{3,8}[^)]*\)")
# - Pattern hex
HEX_PATTERN = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Retourne [(line_no, hardcode, line_excerpt), ...] pour les hardcodes
    non toleres (hors definitions de tokens et fallbacks var())."""
    violations: list[tuple[int, str, str]] = []
    if not path.exists():
        return violations
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        # Skip commentaires obvious
        if stripped.startswith(("//", "*", "#", "/*")):
            continue
        # Skip si la ligne est une definition de variable CSS
        if VAR_DEF_PATTERN.search(line):
            continue
        # Retirer les fallbacks `var(--x, #color)` avant de scanner
        line_clean = VAR_FALLBACK_PATTERN.sub("", line)
        for match in HEX_PATTERN.findall(line_clean):
            if match not in ALLOWED_HARDCODES:
                violations.append((i, match, stripped[:120]))
    return violations


class HardcodedColorsTests(unittest.TestCase):
    @property
    def repo_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    def test_dashboard_styles_minimal_hardcodes(self):
        """dashboard/styles.css : peu de hardcodes residuels acceptables."""
        path = self.repo_root / "web" / "dashboard" / "styles.css"
        violations = _scan_file(path)
        # Tolerance : moins de 5 hardcodes (cas legitimes type contrastes)
        self.assertLessEqual(
            len(violations), 5, f"{len(violations)} hardcodes restants dans {path.name} : {violations[:5]}"
        )

    def test_dashboard_views_no_inline_hardcodes(self):
        """Vues dashboard : tier colors invariantes tolerees, autres limitees."""
        views_dir = self.repo_root / "web" / "dashboard" / "views"
        for view in views_dir.rglob("*.js"):
            violations = _scan_file(view)
            # Tolerance par vue : 8 max (charts SVG complexes, badges multi-couleurs)
            self.assertLessEqual(
                len(violations), 8, f"{view.name} : {len(violations)} hardcodes residuels : {violations[:5]}"
            )

    def test_no_inline_hardcodes_in_components(self):
        """Composants partages : tres peu de hardcodes (sparkline, badge)."""
        comp_dir = self.repo_root / "web" / "dashboard" / "components"
        for comp in comp_dir.rglob("*.js"):
            violations = _scan_file(comp)
            self.assertLessEqual(
                len(violations), 5, f"{comp.name} : {len(violations)} hardcodes residuels : {violations[:5]}"
            )


if __name__ == "__main__":
    unittest.main()
