#!/usr/bin/env python3
"""Genere un rapport HTML navigable a partir des screenshots du catalogue visuel.

Usage :
    python tests/e2e/generate_visual_report.py
    python tests/e2e/generate_visual_report.py --input shots/ --output report.html
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

_DEFAULT_INPUT = "tests/e2e/screenshots/catalog"
_DEFAULT_OUTPUT = "tests/e2e/visual_report.html"

_VIEWPORT_ORDER = ["desktop", "tablet", "mobile"]
_VIEW_ORDER = ["login", "status", "library", "runs", "review", "jellyfin", "logs"]


def _encode_image(path: Path) -> str:
    """Encode une image en base64 data URI."""
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _group_screenshots(input_dir: Path) -> dict:
    """Groupe les screenshots par viewport puis par vue/etat."""
    groups: dict = {vp: {} for vp in _VIEWPORT_ORDER}
    for png in sorted(input_dir.glob("*.png")):
        name = png.stem  # ex: desktop_library_modal_avengers
        parts = name.split("_", 1)
        if len(parts) < 2:
            continue
        vp = parts[0]
        label = parts[1]
        if vp in groups:
            groups[vp][label] = png
    return groups


def _build_html(groups: dict, ui_report: str) -> str:
    """Construit le HTML single-file avec toutes les images en base64."""
    nav_items = []
    sections = []
    img_count = 0

    # Section problemes detectes
    if ui_report.strip():
        sections.append(f'<section id="issues"><h2>Problemes detectes</h2><pre>{ui_report}</pre></section>')
        nav_items.append('<a href="#issues">Problemes</a>')

    # Sections par viewport
    for vp in _VIEWPORT_ORDER:
        items = groups.get(vp, {})
        if not items:
            continue
        section_id = f"vp-{vp}"
        nav_items.append(f'<a href="#{section_id}">{vp.capitalize()} ({len(items)})</a>')

        cards = []
        for label, path in sorted(items.items()):
            data_uri = _encode_image(path)
            img_count += 1
            human_label = label.replace("_", " ").title()
            cards.append(f'''
                <div class="card">
                    <img src="{data_uri}" alt="{human_label}" loading="lazy"
                         onclick="this.classList.toggle('zoomed')" />
                    <p>{human_label}</p>
                </div>''')

        sections.append(f'''
            <section id="{section_id}">
                <h2>{vp.capitalize()} ({len(items)} captures)</h2>
                <div class="grid">{"".join(cards)}</div>
            </section>''')

    # Comparaison cote a cote desktop vs mobile
    desktop = groups.get("desktop", {})
    mobile = groups.get("mobile", {})
    common = sorted(set(desktop.keys()) & set(mobile.keys()))
    if common:
        compare_cards = []
        for label in common[:8]:
            d_uri = _encode_image(desktop[label])
            m_uri = _encode_image(mobile[label])
            human = label.replace("_", " ").title()
            compare_cards.append(f'''
                <div class="compare-pair">
                    <div><img src="{d_uri}" alt="Desktop {human}" onclick="this.classList.toggle('zoomed')" /><p>Desktop</p></div>
                    <div><img src="{m_uri}" alt="Mobile {human}" onclick="this.classList.toggle('zoomed')" /><p>Mobile</p></div>
                </div>''')
        nav_items.append('<a href="#compare">Comparaison</a>')
        sections.append(f"""
            <section id="compare">
                <h2>Desktop vs Mobile</h2>
                {"".join(compare_cards)}
            </section>""")

    nav_html = "\n".join(f"<li>{a}</li>" for a in nav_items)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>CineSort — Catalogue visuel dashboard</title>
<style>
:root {{ --bg: #06090F; --surface: #0C1219; --accent: #60A5FA; --text: #E8ECF1; --muted: #8B97AB; --border: #1E293B; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ background: var(--bg); color: var(--text); font-family: "Segoe UI", system-ui, sans-serif; display: flex; min-height: 100vh; }}
nav {{ width: 220px; background: var(--surface); border-right: 1px solid var(--border); padding: 20px; position: fixed; height: 100vh; overflow-y: auto; }}
nav h1 {{ font-size: 16px; color: var(--accent); margin-bottom: 16px; }}
nav ul {{ list-style: none; }}
nav li {{ margin-bottom: 8px; }}
nav a {{ color: var(--muted); text-decoration: none; font-size: 14px; }}
nav a:hover {{ color: var(--accent); }}
main {{ margin-left: 220px; padding: 32px; flex: 1; }}
section {{ margin-bottom: 48px; }}
h2 {{ color: var(--accent); font-size: 20px; margin-bottom: 16px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
pre {{ background: var(--surface); padding: 16px; border-radius: 8px; font-size: 13px; overflow-x: auto; color: var(--muted); white-space: pre-wrap; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 16px; }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
.card img {{ width: 100%; cursor: pointer; transition: transform 0.2s; }}
.card img.zoomed {{ position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; object-fit: contain; z-index: 1000; background: rgba(0,0,0,0.9); border-radius: 0; }}
.card p {{ padding: 8px 12px; font-size: 13px; color: var(--muted); }}
.compare-pair {{ display: flex; gap: 16px; margin-bottom: 24px; }}
.compare-pair > div {{ flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }}
.compare-pair img {{ width: 100%; cursor: pointer; }}
.compare-pair img.zoomed {{ position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; object-fit: contain; z-index: 1000; background: rgba(0,0,0,0.9); }}
.compare-pair p {{ text-align: center; padding: 6px; font-size: 12px; color: var(--muted); }}
footer {{ text-align: center; color: var(--muted); font-size: 12px; padding: 32px; }}
@media (max-width: 768px) {{ nav {{ display: none; }} main {{ margin-left: 0; }} .grid {{ grid-template-columns: 1fr; }} .compare-pair {{ flex-direction: column; }} }}
</style>
</head>
<body>
<nav>
    <h1>CineSort Dashboard</h1>
    <ul>{nav_html}</ul>
    <p style="margin-top:24px;font-size:12px;color:var(--muted)">{img_count} captures</p>
</nav>
<main>
    <h1 style="margin-bottom:24px">Catalogue visuel — Dashboard CineSort</h1>
    {"".join(sections)}
    <footer>Genere automatiquement par generate_visual_report.py</footer>
</main>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Genere le rapport HTML visuel")
    parser.add_argument("--input", default=_DEFAULT_INPUT, help="Dossier screenshots")
    parser.add_argument("--output", default=_DEFAULT_OUTPUT, help="Fichier HTML de sortie")
    args = parser.parse_args()

    input_dir = Path(args.input)
    if not input_dir.exists():
        print(f"[report] Dossier introuvable : {input_dir}")
        return 1

    pngs = list(input_dir.glob("*.png"))
    if not pngs:
        print(f"[report] Aucun screenshot dans {input_dir}")
        return 1

    groups = _group_screenshots(input_dir)

    # Charger ui_report.md si disponible
    ui_report_path = Path(__file__).resolve().parent / "ui_report.md"
    ui_report = ui_report_path.read_text(encoding="utf-8") if ui_report_path.exists() else ""

    html = _build_html(groups, ui_report)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    total = sum(len(v) for v in groups.values())
    print(f"[report] {total} images encodees dans {output_path} ({output_path.stat().st_size // 1024} Ko)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
