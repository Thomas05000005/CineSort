# -*- coding: utf-8 -*-
"""Lot D (verif totale 2026-07) — Chaine metier 4.6 EXPORTS bout-en-bout.

Chaine verifiee sur bibliotheque VIRTUELLE JETABLE (tempfile.TemporaryDirectory,
fichiers .mkv factices, zero binaire externe requis) :

    scan+plan (run/start_plan) -> decisions (save_validation)
        -> export CSV   (run/export_run_report fmt=csv)
        -> export HTML  (run/export_run_report fmt=html, single-file)
        -> export JSON  (run/export_run_report fmt=json)
        -> export NFO   (run/export_run_nfo dry_run -> reel -> skip -> overwrite)
        -> chemin long ~240 chars (garde MAX_PATH)
        -> contrats consommes par l'UI (web/dashboard/views/logs.js)

Exposition UI (verifiee par lecture croisee, 2026-07-08) :
  - #/logs : boutons JSON/CSV/HTML (logs.js L126-128, data-export) ->
    POST run/export_run_report ; bouton NFO (btnLogExportNfo) ->
    POST run/export_run_nfo {overwrite:false, dry_run:false}.
  - #/parametres : POST library/export_full_library (RGPD, hors perimetre 4.6).
  - Les 3 endpoints facades existent (RunFacade.export_run_report,
    RunFacade.export_run_nfo, LibraryFacade.export_full_library) et sont
    auto-exposes par le dispatcher REST "/api/{facade}/{method}".

BUGS APP CONNUS (constates par cette chaine le 2026-07-08 — REPORTES, pas
corriges ; les tests concernes font pytest.xfail() tant que le bug est present
et redeviendront passants d'eux-memes une fois le bug corrige) :

  [LOTD-EXP-01] CSV : fins de ligne DOUBLEES sur disque (b"\\r\\r\\n").
                report_to_csv_text produit du \\r\\n (csv.writer) mais
                write_run_report_file (dashboard_support.py L1193) ecrit via
                Path.write_text SANS newline="" -> traduction \\n -> \\r\\n de
                l'OS -> \\r\\r\\n -> une ligne vide apres CHAQUE enregistrement
                (Excel affiche des lignes vides, csv.reader rend des rows []).

  [LOTD-EXP-02] UI export CSV/HTML/JSON inutilisable : logs.js _exportRun
                (L192-203) declenche le download uniquement si res.data.content
                existe ; le backend export_run_report renvoie {ok, run_id,
                format, path, rows_total} SANS "content" -> le clic affiche
                toujours la branche erreur ("export_no_data") alors que le
                fichier est ecrit cote serveur dans le run_dir, chemin jamais
                montre a l'utilisateur.

  [LOTD-EXP-03] UI export NFO : logs.js _exportNfo (L206-212) lit
                res.data?.created ; le backend export_nfo_for_run renvoie
                "written" (jamais "created") -> le toast affiche toujours
                "0 NFO crees" meme quand N fichiers sont ecrits.

LIMITES observees (comportements par design, PAS des bugs) :
  - Les guillemets sont IMPOSSIBLES dans les titres exportes : toute entree
    (decision utilisateur OU <title> d'un .nfo source) passe par
    core.windows_safe qui retire < > : " / \\ | ? * (le titre devient un nom de
    fichier). Le film demande 'Amélie, la "belle" (2001)' ressort
    'Amélie, la belle' partout — l'echappement CSV des guillemets est donc
    exerce via le point-virgule (delimiteur CSV, legal NTFS) qui force le
    quoting : titre 'Film; le retour'.
  - Analyse qualite non lancee (aucun binaire ffprobe/mediainfo requis) : les
    colonnes quality_* sont exportees VIDES — la chaine export doit degrader
    proprement, c'est verifie tel quel.
  - Chemin long : la garde est testee a ~240 chars (< MAX_PATH 260). Sur cette
    machine un chemin de 293 chars passe aussi (LongPathsEnabled), mais ce
    n'est pas exige par le test pour rester portable.

Lancer :
  "C:/Users/blanc/projects/CineSort/.venv/Scripts/python.exe" -X utf8 -m pytest \
      tests/test_lotd_chain_exports.py -q
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import pytest

import cinesort.domain.core as core
from tests._helpers import create_file, wait_run_done

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Longueur cible du chemin video "long" (sous MAX_PATH 260 pour rester portable).
_LONG_PATH_TARGET = 240

# Colonnes CSV attendues (contrat report_to_csv_text, dashboard_support.py L1128).
_EXPECTED_CSV_COLUMNS = [
    "run_id",
    "row_id",
    "kind",
    "folder",
    "video",
    "proposed_title",
    "proposed_year",
    "proposed_source",
    "confidence",
    "confidence_label",
    "decision_ok",
    "decision_title",
    "decision_year",
    "quality_status",
    "quality_score",
    "quality_tier",
    "probe_quality",
    "quality_resolution",
    "quality_video_codec",
    "quality_bitrate_kbps",
    "quality_audio_codec",
    "quality_audio_channels",
    "quality_hdr",
    "quality_subscore_video",
    "quality_subscore_audio",
    "quality_subscore_extras",
    "quality_explanation",
    "warning_flags",
    "nfo_present",
    "notes",
]


# ---------------------------------------------------------------------------
# Fixture module : bibliotheque virtuelle + scan+plan + decisions (1 seule fois)
# ---------------------------------------------------------------------------


class _Chain:
    """Contexte partage de la chaine : api, run_id, chemins, rows du plan."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="cinesort_lotd_exports_", ignore_cleanup_errors=True)
        self.base = Path(self.tmp.name)
        self.root = self.base / "root"
        self.state_dir = self.base / "state"
        self.localappdata = self.base / "localappdata"
        for p in (self.root, self.state_dir, self.localappdata):
            p.mkdir(parents=True, exist_ok=True)
        self.api: Any = None
        self.run_id: str = ""
        self.rows: List[Dict[str, Any]] = []
        self.long_video: Path = Path()

    def build_library(self) -> None:
        """3 films factices : accents+virgule, point-virgule, chemin ~240 chars."""
        # Film 1 : accents + virgule (les guillemets sont interdits sur NTFS ;
        # ils sont testes via la decision utilisateur + le .nfo source, et la
        # LIMITE windows_safe est documentee dans le module docstring).
        f1 = self.root / "Amélie, la belle (2001)"
        create_file(f1 / "Amélie, la belle (2001).mkv")
        (f1 / "Amélie, la belle (2001).srt").write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nBonjour\n", encoding="utf-8"
        )
        # .nfo source avec guillemets dans <title> : prouve que meme via nfo la
        # sanitisation windows_safe s'applique (proposed_source == "nfo").
        (f1 / "Amélie, la belle (2001).nfo").write_text(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<movie><title>Amélie, la "belle"</title><year>2001</year></movie>\n',
            encoding="utf-8",
        )

        # Film 2 : point-virgule = delimiteur CSV -> force le quoting a l'export.
        f2 = self.root / "Film; le retour (1999)"
        create_file(f2 / "Film; le retour (1999).mkv")

        # Film 3 : chemin video ~240 chars au total (garde MAX_PATH).
        # len(video) = len(root) + sep + len(name) + sep + len(name) + len(".mkv")
        name_len = max(40, (_LONG_PATH_TARGET - len(str(self.root)) - 6) // 2)
        long_name = "Le.Film.Long." + "X" * max(1, name_len - 24) + ".2020.2160p"
        f3 = self.root / long_name
        self.long_video = f3 / (long_name + ".mkv")
        assert len(str(self.long_video)) <= 259, f"chemin de test > MAX_PATH: {len(str(self.long_video))}"
        create_file(self.long_video)

    def start(self) -> None:
        # LOCALAPPDATA -> tempdir : CineSortApi() calcule default_state_dir()
        # au __init__ ; on garantit qu'AUCUN chemin hors tempdir n'est touche.
        self._env_patch = mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.localappdata)})
        self._env_patch.start()
        self._min_video_patch = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        self._min_video_patch.start()

        from cinesort.ui.api.cinesort_api import CineSortApi

        self.api = CineSortApi()
        settings = {
            "root": str(self.root),
            "state_dir": str(self.state_dir),
            "tmdb_enabled": False,
            "collection_folder_enabled": False,
        }
        saved = self.api.settings.save_settings(settings)
        assert saved.get("ok"), saved

        started = self.api.run.start_plan(settings)
        assert started.get("ok"), started
        self.run_id = started["run_id"]
        status = wait_run_done(self.api, self.run_id, timeout_s=60.0)
        assert status.get("error") is None, status

        plan = self.api.run.get_plan(self.run_id)
        assert plan.get("ok"), plan
        self.rows = plan.get("rows", [])
        assert len(self.rows) == 3, [r.get("proposed_title") for r in self.rows]

        # Decisions : titre avec guillemets envoye volontairement -> la chaine
        # doit le sanitiser (windows_safe) sans casser les exports.
        decisions: Dict[str, Dict[str, Any]] = {}
        for row in self.rows:
            title = row["proposed_title"]
            if "Amélie" in title:
                title = 'Amélie, la "belle"'
            decisions[row["row_id"]] = {"ok": True, "title": title, "year": row["proposed_year"]}
        saved_v = self.api._save_validation_impl(self.run_id, decisions)
        assert saved_v.get("ok"), saved_v

    def stop(self) -> None:
        self._min_video_patch.stop()
        self._env_patch.stop()
        # Le SQLiteStore garde un handle sur state/db/cinesort.sqlite ->
        # ignore_cleanup_errors=True (le fichier vit dans %TEMP%, l'OS purge).
        self.tmp.cleanup()

    def row_by_title_fragment(self, fragment: str) -> Dict[str, Any]:
        for row in self.rows:
            if fragment in row.get("proposed_title", ""):
                return row
        raise AssertionError(f"row introuvable pour fragment {fragment!r} dans {self.rows}")


@pytest.fixture(scope="module")
def chain() -> Any:
    ctx = _Chain()
    ctx.build_library()
    ctx.start()
    yield ctx
    ctx.stop()


# ---------------------------------------------------------------------------
# 0. Endpoints facades exposes a l'UI
# ---------------------------------------------------------------------------


def test_facade_endpoints_exist(chain: _Chain) -> None:
    """Les 3 endpoints d'export consommes par l'UI existent sur les facades.

    Le dispatcher REST expose automatiquement /api/{facade}/{method} pour toute
    methode publique de facade (cinesort/infra/rest_server.py, pass 2) — la
    presence de la methode sur la facade == la presence de l'endpoint.
    """
    assert callable(getattr(chain.api.run, "export_run_report", None))
    assert callable(getattr(chain.api.run, "export_run_nfo", None))
    assert callable(getattr(chain.api.library, "export_full_library", None))


# ---------------------------------------------------------------------------
# 1. Export CSV
# ---------------------------------------------------------------------------


def _export_csv_raw(chain: _Chain) -> bytes:
    res = chain.api.run.export_run_report(chain.run_id, "csv")
    assert res.get("ok"), res
    assert res.get("format") == "csv"
    assert int(res.get("rows_total") or 0) == 3, res
    path = Path(res["path"])
    assert path.exists() and path.stat().st_size > 0
    assert str(path).startswith(str(chain.base)), "export ecrit hors tempdir !"
    return path.read_bytes()


def test_csv_export_columns_encoding_and_escaping(chain: _Chain) -> None:
    raw = _export_csv_raw(chain)

    # Encodage : BOM UTF-8 (utf-8-sig, compat Excel) et decodage strict OK.
    assert raw[:3] == b"\xef\xbb\xbf", "BOM UTF-8 attendu (ecriture utf-8-sig)"
    text = raw.decode("utf-8-sig")  # ne leve pas -> lisible utf-8

    # Parse csv.reader ; delimiteur CONTRAT = ';' (report_to_csv_text).
    parsed = [r for r in csv.reader(io.StringIO(text), delimiter=";") if r]  # [] = lignes vides [LOTD-EXP-01]
    header, data = parsed[0], parsed[1:]

    # Colonnes attendues toutes presentes, sans doublon, run_id en tete.
    assert header[0] == "run_id"
    missing = [c for c in _EXPECTED_CSV_COLUMNS if c not in header]
    assert not missing, f"colonnes manquantes: {missing}"
    assert len(header) == len(set(header)), "colonnes dupliquees"

    # Chaque enregistrement a exactement len(header) champs (quoting correct).
    assert len(data) == 3
    for row in data:
        assert len(row) == len(header), f"row mal echappee: {row[:6]}"

    by_title = {dict(zip(header, r))["proposed_title"]: dict(zip(header, r)) for r in data}

    # Accents + virgule preserves ; guillemets SANITISES par windows_safe
    # (limite documentee) : 'Amélie, la "belle"' -> 'Amélie, la belle',
    # y compris quand le titre vient du .nfo source (proposed_source == nfo).
    amelie = by_title.get("Amélie, la belle")
    assert amelie is not None, list(by_title)
    assert amelie["proposed_source"] == "nfo"
    assert amelie["decision_title"] == "Amélie, la belle"
    assert amelie["decision_year"] == "2001"
    assert '"' not in amelie["decision_title"]

    # Point-virgule (delimiteur) dans titre + nom de fichier : round-trip exact.
    semi = by_title.get("Film; le retour")
    assert semi is not None, list(by_title)
    assert semi["video"] == "Film; le retour (1999).mkv"


def test_csv_no_blank_lines_between_records(chain: _Chain) -> None:
    """xfail tant que [LOTD-EXP-01] est present : write_run_report_file ecrit le
    texte csv (\\r\\n) via Path.write_text sans newline="" -> \\r\\r\\n sur
    disque, une ligne vide apres chaque enregistrement."""
    raw = _export_csv_raw(chain)
    doubled = raw.count(b"\r\r\n")
    if doubled:
        pytest.xfail(
            "[LOTD-EXP-01] CSV: fins de ligne doublees \\r\\r\\n sur disque "
            f"({doubled} occurrences) — dashboard_support.write_run_report_file "
            'ecrit report_to_csv_text() via write_text sans newline="".'
        )
    text = raw.decode("utf-8-sig")
    blank = [i for i, line in enumerate(text.splitlines()) if not line.strip()]
    assert not blank, f"lignes vides dans le CSV aux index {blank}"


# ---------------------------------------------------------------------------
# 2. Rapport HTML single-file
# ---------------------------------------------------------------------------


def test_html_report_single_file(chain: _Chain) -> None:
    res = chain.api.run.export_run_report(chain.run_id, "html")
    assert res.get("ok"), res
    path = Path(res["path"])
    assert path.exists() and path.stat().st_size > 0
    assert str(path).startswith(str(chain.base)), "export ecrit hors tempdir !"
    html_text = path.read_text(encoding="utf-8")

    # Self-contained : AUCUNE reference externe.
    assert "<script src" not in html_text
    assert "<link" not in html_text
    assert "@import" not in html_text
    externals = re.findall(r"""(?:src|href)\s*=\s*["'](?:https?:)?//[^"']+""", html_text)
    # xmlns="http://www.w3.org/2000/svg" est un namespace, pas une ressource.
    externals = [e for e in externals if "www.w3.org" not in e]
    assert not externals, f"references externes trouvees: {externals}"
    assert re.search(r"""url\(\s*["']?(?:https?:)?//""", html_text) is None

    # Contenu : les 3 films, run_id, echappement HTML des accents preserves.
    assert chain.run_id in html_text
    assert "Amélie, la belle" in html_text
    assert "Film; le retour" in html_text
    assert html_text.lstrip().startswith("<!DOCTYPE html>")


# ---------------------------------------------------------------------------
# 3. Export NFO : dry-run -> reel -> skip -> overwrite
# ---------------------------------------------------------------------------


def test_nfo_dry_run_then_real_then_skip_then_overwrite(chain: _Chain) -> None:
    root = chain.root
    # Etat initial : seul le .nfo SOURCE d'Amelie existe (cree par la fixture).
    pre_existing = sorted(p for p in root.rglob("*.nfo"))
    assert len(pre_existing) == 1 and "Amélie" in str(pre_existing[0])

    # (a) dry-run : compte les ecritures SANS toucher le disque. Le .nfo
    # pre-existant d'Amelie doit etre skippe (overwrite=False).
    dry = chain.api.run.export_run_nfo(chain.run_id, overwrite=False, dry_run=True)
    assert dry.get("ok") and dry.get("dry_run") is True, dry
    assert dry.get("written") == 2, dry
    assert dry.get("skipped_existing") == 1, dry
    assert dry.get("errors") == 0, dry
    assert sorted(p for p in root.rglob("*.nfo")) == pre_existing, "dry_run a ecrit sur disque !"

    # (b) reel : 2 nouveaux .nfo, XML valides, titres/annees corrects.
    real = chain.api.run.export_run_nfo(chain.run_id, overwrite=False, dry_run=False)
    assert real.get("ok") and real.get("dry_run") is False, real
    assert real.get("written") == 2 and real.get("errors") == 0, real
    nfo_files = sorted(root.rglob("*.nfo"))
    assert len(nfo_files) == 3
    titles = {}
    for nfo in nfo_files:
        tree = ET.parse(nfo)  # leve ParseError si XML invalide
        movie = tree.getroot()
        assert movie.tag == "movie"
        titles[movie.findtext("title")] = movie.findtext("year")
    assert titles.get("Film; le retour") == "1999"

    # (c) skip : relance sans overwrite -> 3 skips, 0 ecriture, mtimes intacts.
    mtimes = {p: p.stat().st_mtime_ns for p in nfo_files}
    skip = chain.api.run.export_run_nfo(chain.run_id, overwrite=False, dry_run=False)
    assert skip.get("written") == 0 and skip.get("skipped_existing") == 3, skip
    assert {p: p.stat().st_mtime_ns for p in nfo_files} == mtimes, "skip a reecrit un fichier"

    # (d) overwrite : 3 ecritures ; le .nfo SOURCE d'Amelie est REMPLACE par la
    # version generee (titre sanitise sans guillemets), XML valide.
    over = chain.api.run.export_run_nfo(chain.run_id, overwrite=True, dry_run=False)
    assert over.get("written") == 3 and over.get("skipped_existing") == 0, over
    amelie_nfo = pre_existing[0]
    generated = ET.parse(amelie_nfo).getroot()
    assert generated.findtext("title") == "Amélie, la belle"
    assert generated.findtext("year") == "2001"


# ---------------------------------------------------------------------------
# 4. Chemin long (~240 chars) : la chaine export ne crashe pas
# ---------------------------------------------------------------------------


def test_long_path_240_chars_exports_do_not_crash(chain: _Chain) -> None:
    video = chain.long_video
    assert _LONG_PATH_TARGET - 30 <= len(str(video)) <= 259, len(str(video))

    # Le film long est bien dans le plan.
    long_row = next((r for r in chain.rows if r["video"] == video.name), None)
    assert long_row is not None, [r["video"] for r in chain.rows]

    # CSV + HTML : pas de crash, la row longue est presente.
    raw = _export_csv_raw(chain)
    assert video.name.encode("utf-8") in raw
    html_res = chain.api.run.export_run_report(chain.run_id, "html")
    assert html_res.get("ok"), html_res

    # NFO : le fichier long est ecrit (chemin .nfo ~meme longueur) et parseable.
    over = chain.api.run.export_run_nfo(chain.run_id, overwrite=True, dry_run=False)
    assert over.get("errors") == 0, over
    long_nfo = video.with_suffix(".nfo")
    assert long_nfo.exists(), f"nfo long absent: {long_nfo}"
    assert ET.parse(long_nfo).getroot().findtext("year") == "2020"


# ---------------------------------------------------------------------------
# 5. Export JSON (meme endpoint) + chemins negatifs
# ---------------------------------------------------------------------------


def test_json_export_and_negative_paths(chain: _Chain) -> None:
    res = chain.api.run.export_run_report(chain.run_id, "json")
    assert res.get("ok"), res
    payload = json.loads(Path(res["path"]).read_text(encoding="utf-8"))
    assert payload.get("schema") == "run_report_v1"
    assert payload.get("counts", {}).get("rows_total") == 3

    bad_fmt = chain.api.run.export_run_report(chain.run_id, "pdf")
    assert bad_fmt.get("ok") is False and "Format invalide" in str(bad_fmt.get("message"))
    bad_run = chain.api.run.export_run_report("zzz_not_a_run", "csv")
    assert bad_run.get("ok") is False
    bad_nfo = chain.api.run.export_run_nfo("zzz_not_a_run")
    assert bad_nfo.get("ok") is False


# ---------------------------------------------------------------------------
# 6. Contrats BACKEND des exports (Phase 5 : la vue morte /logs qui portait les
#    boutons d'export a ete supprimee ; on verrouille le contrat backend durable
#    qui rendait ces boutons fonctionnels — reutilisable par tout futur point UI).
# ---------------------------------------------------------------------------


def test_report_export_returns_content(chain: _Chain) -> None:
    """[LOTD-EXP-02] backend : export_run_report expose "content" (texte exact du
    fichier) pour permettre un download cote UI. Son absence rendait tout bouton
    d'export inutilisable (branche "export_no_data")."""
    res = chain.api.run.export_run_report(chain.run_id, "csv")
    assert res.get("ok"), res
    assert "content" in res, f"export_run_report doit exposer 'content' : {sorted(res.keys())}"
    assert isinstance(res["content"], str) and res["content"]


def test_nfo_export_returns_written_count(chain: _Chain) -> None:
    """[LOTD-EXP-03] backend : export_run_nfo expose "written" (l'UI morte lisait
    "created" -> toast toujours "0 NFO crees")."""
    res = chain.api.run.export_run_nfo(chain.run_id, overwrite=False, dry_run=True)
    assert res.get("ok"), res
    assert "written" in res, f"export_run_nfo doit exposer 'written' : {sorted(res.keys())}"


# ---------------------------------------------------------------------------
# 7. [LOTD-EXP-04] Le "content" renvoye a l'UI == octets exacts du disque (CRLF)
# ---------------------------------------------------------------------------


def test_csv_export_content_bytes_match_disk_and_keep_crlf(chain: _Chain) -> None:
    """Regression [LOTD-EXP-04] : le CSV telecharge par l'UI (Blob, res.data.
    content) doit refleter octet-pour-octet le fichier ecrit sur disque, CRLF
    inclus. Le backend (dashboard_support.export_run_report) relit le fichier
    avec newline="" ; sans ce kwarg la traduction universal-newlines retraduit
    les \\r\\n du CSV (fix EXP-01) en \\n -> le download reperd le fix."""
    res = chain.api.run.export_run_report(chain.run_id, "csv")
    assert res.get("ok"), res
    content = res.get("content")
    assert isinstance(content, str) and content, res

    disk_bytes = Path(res["path"]).read_bytes()
    # content relu en utf-8 strict (BOM conserve en tete) : re-encode == disque.
    assert content.encode("utf-8") == disk_bytes, "content != octets disque (CRLF perdus ?)"

    # Les CRLF du CSV survivent dans le content, sans doublement (\\r\\r\\n).
    assert "\r\n" in content, "CRLF absents du content (universal-newlines a la lecture ?)"
    assert "\r\r\n" not in content, "CRLF doubles dans le content"
    # Le disque lui-meme reste propre (garde EXP-01 cote fichier).
    assert disk_bytes.count(b"\r\r\n") == 0, "\\r\\r\\n sur disque (regression EXP-01)"
