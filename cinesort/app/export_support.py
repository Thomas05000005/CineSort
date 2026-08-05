"""Génération de rapports enrichis : HTML single-file et export .nfo Kodi/Jellyfin."""

from __future__ import annotations

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

from cinesort.infra.state import atomic_write_text, sweep_atomic_tmp_orphans

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes couleurs tiers qualité
# ---------------------------------------------------------------------------
# AUDIT 2026-06-10 : couleurs tier INVARIANTES (memoire user / CLAUDE.md #2),
# source canonique web/shared/tokens.css. L'export HTML est un fichier autonome
# qui ne peut pas charger le CSS de l'app -> duplication CONTROLEE des hex, mais
# avec les bonnes valeurs (avant : #e2e8f0/#f59e0b/#94a3b8/#ca8a04, fausses).
_TIER_COLORS = {
    "platinum": "#E5E4E2",
    "gold": "#FFD700",
    "silver": "#C0C0C0",
    "bronze": "#CD7F32",
    "reject": "#ef4444",  # hors invariant (pas un tier affiche), rouge conserve
    # Retro-compat lecture pour les profils/reports anterieurs a la migration 011
    "premium": "#E5E4E2",
    "bon": "#FFD700",
    "moyen": "#C0C0C0",
    "faible": "#CD7F32",
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

# Identifiants providers — formats acceptes par Kodi et Jellyfin.
# TMDb : entier positif. IMDb : "tt" + 7 a 12 chiffres.
# Un identifiant hors format n'est PAS ecrit : un imdb_id invalide empeche
# Jellyfin de telecharger les jaquettes (jellyfin/jellyfin#7174), ce qui est
# pire qu'un NFO sans identifiant.
_TMDB_ID_RE = re.compile(r"^[1-9][0-9]{0,9}$")
_IMDB_ID_RE = re.compile(r"^tt[0-9]{7,12}$")

# Annee : chiffres ASCII UNIQUEMENT. `int()` accepte les separateurs et les
# signes, donc `int("1_999") == 1999` et `int("+2020") == 2020` — une
# REINTERPRETATION silencieuse de la donnee. Le motif l'interdit.
_YEAR_DIGITS_RE = re.compile(r"^[0-9]+$")
# Bornes de plausibilite : le premier film date de 1888. Hors de cette plage,
# Kodi et Jellyfin ignorent le `<year>` a la lecture, sans rien signaler —
# CineSort doit donc le signaler lui-meme plutot qu'ecrire `<year>-500</year>`.
_MIN_PLAUSIBLE_YEAR = 1870
_MAX_PLAUSIBLE_YEAR = 2200


class _RowDataError(ValueError):
    """Donnee de row inexploitable : la row est ISOLEE et signalee, l'export continue.

    Issue #720 : avant, un `int(year)` non garde sur une seule row (annee "N/A",
    "?"...) faisait remonter un ValueError qui avortait l'export NFO ENTIER.
    """


def _coerce_year(*candidates: Any) -> int:
    """Retourne la premiere annee exploitable parmi `candidates`, ou 0 si toutes sont vides.

    Leve `_RowDataError` si une annee est PRESENTE mais non numerique, ou hors
    de la plage plausible. On ne retombe alors pas sur le candidat suivant :
    une annee de decision fautive doit etre signalee a l'utilisateur, pas
    remplacee en douce par la valeur proposee (un echec ne devient jamais un
    succes silencieux). Meme raison pour le refus de `"1_999"` ou `2020.7` :
    une valeur reinterpretee sans le dire est un succes silencieux deguise.
    """
    for raw in candidates:
        if raw is None:
            continue
        if isinstance(raw, bool):
            # bool est un sous-type de int : `True` donnerait l'annee 1.
            raise _RowDataError(f"annee non numerique ({raw!r})")
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                continue
            if not _YEAR_DIGITS_RE.fullmatch(text):
                raise _RowDataError(f"annee non numerique ({raw!r})")
            value = int(text)
        elif isinstance(raw, float):
            # `is_integer()` couvre aussi nan et inf : ni l'un ni l'autre n'est
            # entier, donc aucun ne passe. Une part decimale serait tronquee.
            if not raw.is_integer():
                raise _RowDataError(f"annee non numerique ({raw!r})")
            value = int(raw)
        elif isinstance(raw, int):
            value = raw
        else:
            raise _RowDataError(f"annee non numerique ({raw!r})")
        if value == 0:
            # 0 / "0" est la sentinelle « annee absente » du payload amont.
            continue
        if not _MIN_PLAUSIBLE_YEAR <= value <= _MAX_PLAUSIBLE_YEAR:
            raise _RowDataError(f"annee hors plage ({raw!r})")
        return value
    return 0


def _clean_provider_id(raw: Any, pattern: re.Pattern[str], label: str) -> str:
    """Normalise un identifiant provider, ou "" s'il est absent ou hors format."""
    text = str(raw if raw is not None else "").strip()
    # 0 / "0" est la valeur sentinelle "absent" du payload amont, pas une erreur.
    if not text or text == "0":
        return ""
    if not pattern.fullmatch(text):
        _logger.warning("export nfo: %s ignore, format invalide (%r)", label, text)
        return ""
    return text


def _resolve_nfo_path(folder: str, video: str) -> Path:
    """Retourne le chemin du .nfo, garanti A L'INTERIEUR du dossier du film.

    Issue #564 (CWE-22) : `video` vient d'un PlanRow qui peut avoir ete altere
    (base modifiee, plan.jsonl importe). Un `..` ou un chemin absolu faisait
    ecrire le .nfo hors du dossier cible. Le containment est verifie sur les
    chemins RESOLUS, ce qui couvre aussi l'echappement par lien symbolique ou
    par jonction NTFS.

    C'est le chemin RESOLU qui est retourne, donc celui sur lequel le
    containment vient d'etre verifie : ecrire sur le chemin brut rouvrirait la
    fenetre qu'on vient de fermer (un composant intermediaire transforme en
    lien entre la verification et l'ecriture).
    """
    base = Path(folder)
    nfo_path = (base / video).with_suffix(".nfo")
    try:
        base_resolved = base.resolve()
        nfo_resolved = nfo_path.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise _RowDataError(f"chemin illisible ({exc})") from None
    if nfo_resolved == base_resolved or not nfo_resolved.is_relative_to(base_resolved):
        raise _RowDataError("chemin .nfo hors du dossier du film")
    return nfo_resolved


def _build_nfo_xml(title: str, year: int, original_title: str = "", tmdb_id: str = "", imdb_id: str = "") -> str:
    """Construit le XML NFO pour un film (format Kodi/Jellyfin).

    Schema verifie sur les deux consommateurs (2026-08-03) :
    - Kodi lit `<uniqueid type="..." default="true">` ; l'ancien `<id>` est
      deprecie. `CVideoInfoTag::ParseNative` ne retient l'identifiant par
      defaut que si un `uniqueid` porte `default="true"` — sinon
      `m_strDefaultUniqueID` reste "unknown" et le scrape perd l'appariement.
      D'ou l'invariant : EXACTEMENT un `uniqueid` porte `default="true"`.
    - Jellyfin (`MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs`) lit le
      meme `<uniqueid>` via son attribut `type` et resout les noms de provider
      sans tenir compte de la casse ; l'attribut `default` lui est indifferent.
    """
    root = ET.Element("movie")

    ET.SubElement(root, "title").text = title
    if original_title and original_title != title:
        ET.SubElement(root, "originaltitle").text = original_title
    if year:
        ET.SubElement(root, "year").text = str(year)

    tmdb = str(tmdb_id or "").strip()
    imdb = str(imdb_id or "").strip()
    if tmdb:
        # TMDb est la source d'identification primaire de CineSort.
        ET.SubElement(root, "uniqueid", {"type": "tmdb", "default": "true"}).text = tmdb
    if imdb:
        # A defaut de TMDb, IMDb endosse le role d'identifiant par defaut.
        imdb_attrs = {"type": "imdb"} if tmdb else {"type": "imdb", "default": "true"}
        ET.SubElement(root, "uniqueid", imdb_attrs).text = imdb

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

        if not folder or not video or not title:
            skipped_no_data += 1
            continue

        # Issues #720 / #564 : une row porteuse d'une donnee fautive est ISOLEE
        # et comptee en erreur — elle n'avorte plus l'export des autres films.
        try:
            year = _coerce_year(row.get("decision_year"), row.get("proposed_year"))
            nfo_path = _resolve_nfo_path(folder, video)
        except _RowDataError as exc:
            errors += 1
            # Coherence avec #427 : la valeur alteree est LOGGEE, jamais
            # renvoyee a l'UI. `Path(folder) / video` reflechissait le chemin
            # brut de la row — chemin absolu compris quand `video` en portait
            # un — c'est-a-dire exactement la valeur qu'on vient de refuser.
            # Seul le dossier du film (la base du containment) repart.
            details.append({"path": folder, "status": f"error: {exc}"})
            _logger.warning("export nfo: row ignoree (%s, video=%r) — %s", title, video, exc)
            continue

        if nfo_path.exists() and not overwrite:
            skipped_existing += 1
            details.append({"path": str(nfo_path), "status": "skipped_existing"})
            continue

        # Issue #612 : sans uniqueid, Jellyfin/Kodi ne peuvent pas relier le
        # film a TMDb/IMDb et re-scrapent tout — le .nfo perd son interet.
        xml_content = _build_nfo_xml(
            title,
            year,
            original_title=str(row.get("original_title") or "").strip(),
            tmdb_id=_clean_provider_id(row.get("tmdb_id"), _TMDB_ID_RE, "tmdb_id"),
            imdb_id=_clean_provider_id(row.get("imdb_id"), _IMDB_ID_RE, "imdb_id"),
        )

        if dry_run:
            written += 1
            details.append({"path": str(nfo_path), "status": "would_write"})
            continue

        try:
            # Fix #822 : `write_text` tronque le .nfo EN PLACE. Coupure secteur
            # ou NAS qui decroche pendant l'ecriture -> l'utilisateur se
            # retrouve avec un .nfo vide/tronque a la place de celui que
            # Jellyfin/Kodi lisait tres bien avant l'export. `mkdir=False` :
            # on n'a AUCUNE raison de recreer le dossier d'un film disparu.
            #
            # Conflit avec #834 (main) : les deux branches ferment la MEME
            # issue #822, main avec un `tmp + fsync + os.replace` ECRIT SUR
            # PLACE, celle-ci en routant vers le helper unique. Le helper
            # SUBSUME la version inline — meme fsync, plus le controle de
            # taille ecrite, le `.tmp` unique (pid/thread/ns/uuid au lieu du
            # seul pid, qui collisionnait entre threads du meme processus), la
            # retentative d'`os.replace` mesuree par #718 et le nettoyage du
            # `.tmp` en `finally`. La mecanique inline de #834 est donc retiree
            # plutot que doublee : deux implementations de la meme garantie
            # divergent au premier reglage.
            atomic_write_text(nfo_path, xml_content, mkdir=False)
            written += 1
            details.append({"path": str(nfo_path), "status": "written"})
            # Le `.tmp` unique n'est JAMAIS reecrase : un export interrompu
            # laisse ici un residu DEFINITIF, dans le dossier du film, a cote
            # du .mkv — visible par l'utilisateur et scanne par Jellyfin/Kodi.
            # On balaie les orphelins de CE .nfo (et d'aucun autre fichier du
            # dossier) a chaque export reussi : la borne « au plus un residu »
            # qu'offrait l'ancien `.tmp` fixe est ainsi retablie.
            sweep_atomic_tmp_orphans(nfo_path.parent, target_name=nfo_path.name)
        except (OSError, PermissionError) as exc:
            # Le nettoyage du `.tmp` que #834 faisait ici est desormais dans le
            # `finally` d'`atomic_write_bytes` : il s'execute sur TOUS les
            # chemins de sortie, y compris l'echec du controle de taille.
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
