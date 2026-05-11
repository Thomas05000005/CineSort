"""Génération de rapports enrichis : HTML single-file et export .nfo Kodi/Jellyfin."""

from __future__ import annotations

import html
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes couleurs tiers qualité
# ---------------------------------------------------------------------------
_TIER_COLORS = {
    "platinum": "#e2e8f0",
    "gold": "#f59e0b",
    "silver": "#94a3b8",
    "bronze": "#ca8a04",
    "reject": "#ef4444",
    # Retro-compat lecture pour les profils/reports anterieurs a la migration 011
    "premium": "#e2e8f0",
    "bon": "#f59e0b",
    "moyen": "#94a3b8",
    "faible": "#ca8a04",
}
_TIER_LABELS = {
    "platinum": "Platinum",
    "gold": "Gold",
    "silver": "Silver",
    "bronze": "Bronze",
    "reject": "Reject",
    # Retro-compat
    "premium": "Platinum",
    "bon": "Gold",
    "moyen": "Silver",
    "faible": "Bronze",
}
_CONFIDENCE_COLORS = {"high": "#22c55e", "med": "#f59e0b", "low": "#ef4444"}

# ---------------------------------------------------------------------------
# HTML — sous-fonctions privées (< 50L chacune)
# ---------------------------------------------------------------------------


def _html_head(run_meta: Dict[str, Any]) -> str:
    """Construit l'en-tête HTML du rapport (DOCTYPE, styles, titre, métadonnées run)."""
    run_id = html.escape(str(run_meta.get("run_id", "")))
    generated = html.escape(str(run_meta.get("generated_at", "")))
    root = html.escape(str(run_meta.get("root", "")))
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rapport CineSort — {run_id}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;padding:32px;line-height:1.5}}
h1{{font-size:22px;font-weight:600;margin-bottom:4px}} h2{{font-size:16px;font-weight:600;margin:28px 0 12px;border-bottom:1px solid #334155;padding-bottom:6px}}
.meta{{font-size:13px;color:#94a3b8;margin-bottom:24px}}
.cards{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:16px 20px;min-width:150px;flex:1}}
.card .val{{font-size:28px;font-weight:700}} .card .lbl{{font-size:12px;color:#94a3b8;margin-top:2px}}
.chart-wrap{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:20px;margin-bottom:24px}}
table{{width:100%;border-collapse:collapse;font-size:12px}} th{{text-align:left;padding:8px 6px;background:#1e293b;color:#94a3b8;border-bottom:1px solid #334155;position:sticky;top:0}}
td{{padding:6px;border-bottom:1px solid #1e293b}} tr:hover td{{background:rgba(96,165,250,.06)}}
.pill{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;color:#fff}}
.footer{{margin-top:32px;font-size:11px;color:#475569;text-align:center}}
</style>
</head>
<body>
<h1>Rapport CineSort</h1>
<div class="meta">Run <b>{run_id}</b> &mdash; {generated} &mdash; {root}</div>
"""


def _html_stats_cards(counts: Dict[str, Any]) -> str:
    total = counts.get("rows_total", 0)
    ok = counts.get("validated_ok", 0)
    q_reports = counts.get("quality_reports", 0)
    tiers = counts.get("quality_tiers", {})
    # Retro-compat : accepter la clef ancienne "premium" si les nouvelles donnees
    # sont encore en cours de migration.
    platinum = tiers.get("platinum", tiers.get("premium", 0))
    return f"""<div class="cards">
<div class="card"><div class="val">{total}</div><div class="lbl">Films analysés</div></div>
<div class="card"><div class="val">{ok}</div><div class="lbl">Validés OK</div></div>
<div class="card"><div class="val">{q_reports}</div><div class="lbl">Qualité analysée</div></div>
<div class="card"><div class="val">{platinum}</div><div class="lbl">Platinum</div></div>
</div>
"""


def _html_chart_svg(counts: Dict[str, Any]) -> str:
    """Rend la distribution qualité (tiers) en barres SVG inline."""
    tiers = counts.get("quality_tiers", {})
    total = sum(tiers.values()) or 1
    bars: list[str] = []
    y = 0
    bar_h = 32
    gap = 6
    for key in ("platinum", "gold", "silver", "bronze", "reject"):
        # Retro-compat : si la clef moderne n'existe pas, retomber sur l'ancienne.
        legacy_map = {"platinum": "premium", "gold": "bon", "silver": "moyen", "bronze": "faible"}
        count = tiers.get(key, tiers.get(legacy_map.get(key, key), 0))
        pct = count / total * 100
        w = max(pct, 0.5)
        color = _TIER_COLORS.get(key, "#64748b")
        label = _TIER_LABELS.get(key, key)
        bars.append(
            f'<rect x="100" y="{y}" width="{w * 3.5}" height="{bar_h}" rx="4" fill="{color}" />'
            f'<text x="90" y="{y + 21}" text-anchor="end" fill="#e2e8f0" font-size="13">{label}</text>'
            f'<text x="{105 + w * 3.5}" y="{y + 21}" fill="#94a3b8" font-size="12">{count} ({pct:.0f}%)</text>'
        )
        y += bar_h + gap
    svg_h = y or 40
    return f"""<div class="chart-wrap">
<h2 style="margin-top:0;border:none;padding:0">Distribution qualité</h2>
<svg width="100%" height="{svg_h}" viewBox="0 0 550 {svg_h}" xmlns="http://www.w3.org/2000/svg">
{"".join(bars)}
</svg>
</div>
"""


def _html_table(rows: List[Dict[str, Any]]) -> str:
    """Rend la table HTML détaillée des films (titre, qualité, codecs, alertes)."""
    header_cols = [
        ("Film", "proposed_title"),
        ("Année", "proposed_year"),
        ("Source", "proposed_source"),
        ("Confiance", "confidence_label"),
        ("Score", "quality_score"),
        ("Tier", "quality_tier"),
        ("Résolution", "quality_resolution"),
        ("Codec V", "quality_video_codec"),
        ("Bitrate", "quality_bitrate_kbps"),
        ("Audio", "quality_audio_codec"),
        ("Ch.", "quality_audio_channels"),
        ("HDR", "quality_hdr"),
        ("Avert.", "warning_flags"),
    ]
    ths = "".join(f"<th>{html.escape(lbl)}</th>" for lbl, _ in header_cols)
    trs: list[str] = []
    for row in rows:
        cells: list[str] = []
        for _lbl, key in header_cols:
            val = row.get(key, "")
            if key == "quality_tier" and val:
                color = _TIER_COLORS.get(val, "#64748b")
                display = _TIER_LABELS.get(val, val)
                cells.append(f'<td><span class="pill" style="background:{color}">{html.escape(display)}</span></td>')
            elif key == "confidence_label" and val:
                color = _CONFIDENCE_COLORS.get(val, "#64748b")
                cells.append(f'<td><span class="pill" style="background:{color}">{html.escape(str(val))}</span></td>')
            elif key == "quality_bitrate_kbps" and val:
                cells.append(f"<td>{int(val):,} kbps</td>")
            elif key == "quality_audio_channels" and val:
                cells.append(f"<td>{val}</td>")
            elif key == "warning_flags" and val:
                cells.append(f"<td>{html.escape(str(val).replace('|', ', '))}</td>")
            else:
                cells.append(f"<td>{html.escape(str(val))}</td>")
        trs.append(f"<tr>{''.join(cells)}</tr>")
    return f"""<h2>Détail des films ({len(rows)})</h2>
<div style="overflow-x:auto"><table><thead><tr>{ths}</tr></thead><tbody>
{"".join(trs)}
</tbody></table></div>
"""


def _html_footer() -> str:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    return f"""<div class="footer">Généré par CineSort &mdash; {ts}</div>
</body></html>"""


# ---------------------------------------------------------------------------
# API publique — HTML
# ---------------------------------------------------------------------------


def export_html_report(report: Dict[str, Any]) -> str:
    """Génère un rapport HTML single-file complet à partir du report payload."""
    run_meta = {
        "run_id": report.get("run_id", ""),
        "generated_at": report.get("generated_at", ""),
        "root": (report.get("run") or {}).get("root", ""),
    }
    counts = report.get("counts") or {}
    rows = report.get("rows") or []

    parts = [
        _html_head(run_meta),
        _html_stats_cards(counts),
        _html_chart_svg(counts),
        _html_table(rows),
        _html_footer(),
    ]
    _logger.info("export: HTML genere (%d films)", len(rows))
    return "".join(parts)


# ---------------------------------------------------------------------------
# API publique — NFO export
# ---------------------------------------------------------------------------

_NFO_XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


def _build_nfo_xml(title: str, year: int, original_title: str = "", tmdb_id: str = "", imdb_id: str = "") -> str:
    """Construit le XML NFO pour un film (format Kodi/Jellyfin)."""
    root = ET.Element("movie")

    ET.SubElement(root, "title").text = title
    if original_title and original_title != title:
        ET.SubElement(root, "originaltitle").text = original_title
    if year:
        ET.SubElement(root, "year").text = str(year)
    if tmdb_id:
        uid = ET.SubElement(root, "uniqueid", type="tmdb", default="true")
        uid.text = str(tmdb_id)
    if imdb_id:
        uid = ET.SubElement(root, "uniqueid", type="imdb")
        uid.text = str(imdb_id)

    ET.indent(root, space="  ")
    return _NFO_XML_HEADER + ET.tostring(root, encoding="unicode") + "\n"


def export_nfo_for_run(
    rows: List[Dict[str, Any]],
    *,
    overwrite: bool = False,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Génère des fichiers .nfo pour chaque film du run.

    Retourne {ok, written, skipped_existing, skipped_no_data, errors, details[]}.
    """
    written = 0
    skipped_existing = 0
    skipped_no_data = 0
    errors = 0
    details: List[Dict[str, str]] = []

    for row in rows:
        folder = str(row.get("folder") or "").strip()
        video = str(row.get("video") or "").strip()
        title = str(row.get("decision_title") or row.get("proposed_title") or "").strip()
        year = int(row.get("decision_year") or row.get("proposed_year") or 0)

        if not folder or not video or not title:
            skipped_no_data += 1
            continue

        video_path = Path(folder) / video
        nfo_path = video_path.with_suffix(".nfo")

        if nfo_path.exists() and not overwrite:
            skipped_existing += 1
            details.append({"path": str(nfo_path), "status": "skipped_existing"})
            continue

        xml_content = _build_nfo_xml(title, year)

        if dry_run:
            written += 1
            details.append({"path": str(nfo_path), "status": "would_write"})
            continue

        try:
            nfo_path.write_text(xml_content, encoding="utf-8")
            written += 1
            details.append({"path": str(nfo_path), "status": "written"})
        except (OSError, PermissionError) as exc:
            errors += 1
            details.append({"path": str(nfo_path), "status": f"error: {exc}"})

    return {
        "ok": True,
        "dry_run": dry_run,
        "written": written,
        "skipped_existing": skipped_existing,
        "skipped_no_data": skipped_no_data,
        "errors": errors,
        "details": details,
    }
