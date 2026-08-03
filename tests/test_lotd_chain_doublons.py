"""Lot D — chaine metier 4.3 DOUBLONS verifiee BOUT-EN-BOUT (verif/totale-2026-07).

Chaine couverte (biblio virtuelle jetable, 2 roots, CineSortApi direct, aucun port) :

  1. Scan multi-roots (start_plan avec roots=[A, B], tmdb off, probe off).
  2. check_duplicates : le VRAI doublon cross-root (meme titre+annee, qualites
     differentes via noms 1080p/720p et tailles differentes) est groupe par
     IDENTITE titre+annee avec scope='cross_root'.
  3. Le QUASI-doublon (titre proche : "Le Grand Voyageur" vs "Le Grand Voyage",
     meme annee) n'est groupe dans AUCUN groupe.
  4. Decision "Garder A" : mark_duplicate_winner persiste la decision
     (table duplicate_decisions) ; elle est RELUE par un nouveau check_duplicates
     (annotations winner_decided/winner_row_id, cf fix R8-057).
  5. apply (dry puis reel) : le loser est DEPLACE (pas supprime) vers le bucket
     _review/_duplicates_user_decided/ ; compteur dedie
     duplicates_user_decided_moved_count == 1 (cf fix R8-018), contenu intact.
     NB constate : le bucket reel est <state_dir>/runs/tri_films_<run>/_review/,
     alors que la doc/les docstrings parlent de <root>/_review/ (divergence doc).
  6. undo_last_apply reel : le loser est RESTAURE a son emplacement d'origine,
     contenu bit-a-bit identique.

Gardes nominatives (bugs d'app REPORTES, pas corriges ; les tests concernes
font pytest.xfail() tant que le bug est present et redeviendront passants
d'eux-memes une fois le bug corrige) :

  [R8-028] files_identical_quick (cinesort/app/apply_core.py) compare taille +
    sha1_quick(8 premiers Mo + 8 derniers Mo). Deux fichiers > 16 Mo qui ne
    different QU'AU MILIEU sont declares identiques -> un "doublon identique"
    peut etre fusionne/ecarte a tort. Le test construit les 2 fichiers (~34 Mo
    au total, tempdir).

  [LOTD-DUP-BUCKET-VIEWER] l'apply route les losers vers
    <state_dir>/runs/tri_films_<run>/_review/_duplicates_user_decided/
    (apply_support.py:1540 run_review_root=run_paths.run_dir/"_review"),
    alors que le viewer quarantaine (list_quarantine_bucket ->
    quarantine_ttl.review_root = cfg.root/"_review") et les docstrings
    (run_flow_support.py:1633, run_facade.py:306) pointent <root>/_review/.
    Consequence : le loser est bien recuperable sur disque mais INVISIBLE
    dans le viewer quarantaine de l'UI.

  [LOTD-DUP-TITLE-YEAR] clean_title_guess (cinesort/domain/core.py) garde
    l'annee dans le titre quand elle est suivie d'un tag qualite
    ('Le.Grand.Voyage.2005.720p' -> 'Le Grand Voyage 2005') mais la retire
    quand elle est en fin de nom ('Le.Grand.Voyage.2005' -> 'Le Grand
    Voyage'). Sans NFO/TMDb, deux copies du MEME film (meme annee detectee)
    obtiennent alors deux identites titre+annee differentes ->
    check_duplicates ne les groupe PAS (total_groups=0) et le dossier cible
    devient redondant ('Le Grand Voyage 2005 (2005)').

LIMITES explicites (pas de simulation) :
  - ffprobe/mediainfo absents de l'env de test : probe_backend='none'. La
    branche 'comparison' (scores qualite A/B dans les groupes) exige des
    quality_reports issus d'un probe reel -> NON exercee ici (les groupes
    restent valides sans 'comparison').
  - check_duplicates_fusion (Chromaprint/videohash) exige ffmpeg + flag
    CINESORT_FUSION_DOUBLONS -> hors perimetre.

Lancer :
  "C:/Users/blanc/projects/CineSort/.venv/Scripts/python.exe" -X utf8 -m pytest \
      tests/test_lotd_chain_doublons.py -q
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

import cinesort.domain.core as core
from cinesort.app.apply_core import files_identical_quick
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import wait_run_done as _wait_done

_MB = 1024 * 1024

# Identite du VRAI doublon cross-root (titre + annee identiques, qualites differentes).
_DUP_TITLE = "Le Grand Voyage"
_DUP_YEAR = 2005
_WINNER_DIR = "Le.Grand.Voyage.2005.1080p"  # root A — gagnant (plus gros, "1080p")
_LOSER_DIR = "Le.Grand.Voyage.2005.720p"  # root B — perdant (plus petit, "720p")
# QUASI-doublon : titre PROCHE mais different -> ne doit PAS etre groupe.
_QUASI_DIR = "Le.Grand.Voyageur.2005.1080p"

_WINNER_BYTES = 96 * 1024  # tailles differentes = qualites differentes simulees
_LOSER_BYTES = 48 * 1024
_QUASI_BYTES = 64 * 1024


def _mk_movie(folder: Path, name: str, size: int, pattern: bytes) -> Path:
    """Cree un faux .mkv (bytes arbitraires) + un sidecar .srt dans `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / f"{name}.mkv"
    video.write_bytes(pattern * (size // len(pattern) + 1))
    (folder / f"{name}.fr.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nBonjour\n", encoding="utf-8")
    return video


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(_MB), b""):
            h.update(block)
    return h.hexdigest()


class LotDChainDoublonsTests(unittest.TestCase):
    """Chaine 4.3 doublons bout-en-bout sur bibliotheque VIRTUELLE JETABLE."""

    def setUp(self) -> None:
        # ignore_cleanup_errors : sous Windows, la SQLite du state_dir peut rester
        # ouverte par l'API a l'instant du cleanup (WinError 32) — tolere, le
        # dossier temp est purge par l'OS.
        self._tmpdir = tempfile.TemporaryDirectory(prefix="cinesort_lotd_dup_", ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        base = Path(self._tmpdir.name)
        self.root_a = base / "rootA"
        self.root_b = base / "rootB"
        self.state_dir = base / "state"
        for d in (self.root_a, self.root_b, self.state_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Fichiers factices legers (pattern proven : test_backend_flow.py).
        patch_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        patch_min.start()
        self.addCleanup(patch_min.stop)

        # Biblio virtuelle : doublon VRAI cross-root + quasi-doublon (root A).
        self.winner_video = _mk_movie(self.root_a / _WINNER_DIR, _WINNER_DIR, _WINNER_BYTES, b"W1080")
        self.loser_video = _mk_movie(self.root_b / _LOSER_DIR, _LOSER_DIR, _LOSER_BYTES, b"L0720")
        _mk_movie(self.root_a / _QUASI_DIR, _QUASI_DIR, _QUASI_BYTES, b"QUASI")
        # .nfo minimal IDENTIQUE sur les 2 copies : identite titre+annee partagee.
        # (Constat Lot D : sans nfo, le parser de nom garde l'annee dans le titre
        # -> "Le Grand Voyage 2005" ; l'identite reste groupable mais le titre est
        # pollue. Avec nfo, source NFO -> titre propre "Le Grand Voyage".)
        nfo_xml = f"<movie><title>{_DUP_TITLE}</title><year>{_DUP_YEAR}</year></movie>"
        (self.root_a / _WINNER_DIR / f"{_WINNER_DIR}.nfo").write_text(nfo_xml, encoding="utf-8")
        (self.root_b / _LOSER_DIR / f"{_LOSER_DIR}.nfo").write_text(nfo_xml, encoding="utf-8")
        self.loser_sha_before = _sha256(self.loser_video)

        self.api = CineSortApi()
        # Isolation totale : settings/etat dans le tempdir, jamais le state réel.
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Chaine complete (etapes sequentielles dans UN test : l'apply/undo
    # mutent le FS, l'ordre est significatif).
    # ------------------------------------------------------------------
    def test_chain_doublons_bout_en_bout(self) -> None:
        api = self.api

        # --- 1. Scan multi-roots ------------------------------------------------
        start = api.run.start_plan(
            {
                "roots": [str(self.root_a), str(self.root_b)],
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": False,
                "probe_backend": "none",  # binaires externes absents : degrade proprement
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]
        status = _wait_done(api, run_id, timeout_s=30.0)
        self.assertIsNone(status.get("error"), status)

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows") or []
        self.assertEqual(len(rows), 3, [r.get("folder") for r in rows])

        def _row_for(token: str) -> dict:
            matches = [r for r in rows if token in str(r.get("folder") or "")]
            self.assertEqual(len(matches), 1, f"row unique attendue pour {token}: {matches}")
            return matches[0]

        winner_row = _row_for(_WINNER_DIR)
        loser_row = _row_for(_LOSER_DIR)
        quasi_row = _row_for(_QUASI_DIR)
        self.assertNotEqual(winner_row["row_id"], loser_row["row_id"])
        # source_root multi-roots bien propage (fix R8-027 adjacent).
        self.assertTrue(str(winner_row.get("source_root") or ""), winner_row)
        self.assertTrue(str(loser_row.get("source_root") or ""), loser_row)
        self.assertNotEqual(winner_row["source_root"], loser_row["source_root"])

        # --- 2. Decisions approuvees, persistees et relues ----------------------
        decisions = {r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]} for r in rows}
        sv = api.run.save_validation(run_id, decisions)
        self.assertTrue(sv.get("ok"), sv)
        lv = api.run.load_validation(run_id)
        self.assertTrue(lv.get("ok"), lv)
        relues = lv.get("decisions") or {}
        for rid in decisions:
            self.assertTrue((relues.get(rid) or {}).get("ok"), f"decision {rid} non relue: {relues.get(rid)}")

        # --- 3. check_duplicates : groupement par identite titre+annee ----------
        dup = api.run.check_duplicates(run_id, decisions)
        self.assertTrue(dup.get("ok"), dup)
        groups = dup.get("groups") or []
        self.assertEqual(int(dup.get("total_groups") or 0), 1, dup)
        group = groups[0]
        self.assertEqual(int(group.get("year") or 0), _DUP_YEAR, group)
        self.assertEqual(str(group.get("title") or "").lower(), _DUP_TITLE.lower(), group)
        group_row_ids = {str(r.get("row_id") or "") for r in (group.get("rows") or [])}
        self.assertEqual(group_row_ids, {winner_row["row_id"], loser_row["row_id"]}, group)
        # Doublon cross-root : le scope doit l'etiqueter comme tel.
        self.assertEqual(str(group.get("scope") or ""), "cross_root", group)

        # Le quasi-doublon n'apparait dans AUCUN groupe.
        all_grouped_ids = {str(r.get("row_id") or "") for g in groups for r in (g.get("rows") or [])}
        self.assertNotIn(quasi_row["row_id"], all_grouped_ids, groups)

        # --- 4. Decision "Garder A" persistee + relue (R8-057) -------------------
        group_key = f"{str(group.get('title') or '').strip().lower()}|{group.get('year')}"
        marked = api.run.mark_duplicate_winner(run_id, group_key, winner_row["row_id"])
        self.assertTrue(marked.get("ok"), marked)
        self.assertEqual(marked.get("winner_row_id"), winner_row["row_id"], marked)
        self.assertEqual(list(marked.get("losers") or []), [loser_row["row_id"]], marked)

        dup2 = api.run.check_duplicates(run_id, decisions)
        self.assertTrue(dup2.get("ok"), dup2)
        group2 = (dup2.get("groups") or [])[0]
        self.assertTrue(group2.get("winner_decided"), f"R8-057 : decision non relue au refresh: {group2}")
        self.assertEqual(str(group2.get("winner_row_id") or ""), winner_row["row_id"], group2)

        # --- 5a. apply DRY : compteur annonce, FS intact -------------------------
        dry = api.run.apply(run_id, decisions, True, False)
        self.assertTrue(dry.get("ok"), dry)
        dry_result = dry["result"]
        self.assertEqual(int(dry_result.get("errors") or 0), 0, dry_result)
        self.assertEqual(int(dry_result.get("duplicates_user_decided_moved_count") or 0), 1, dry_result)
        self.assertTrue(self.loser_video.exists(), "dry-run ne doit RIEN deplacer")
        self.assertTrue(self.winner_video.exists(), "dry-run ne doit RIEN deplacer")

        # --- 5b. apply REEL : loser deplace vers le bucket (PAS supprime) --------
        real = api.run.apply(run_id, decisions, False, False)
        self.assertTrue(real.get("ok"), real)
        result = real["result"]
        self.assertEqual(int(result.get("errors") or 0), 0, result)
        self.assertEqual(
            int(result.get("duplicates_user_decided_moved_count") or 0),
            1,
            f"compteur dedie R8-018 attendu==1: {result}",
        )
        # R8-018 : le loser ne doit PAS etre compte en 'duplicates identiques'.
        self.assertEqual(int(result.get("duplicates_identical_moved_count") or 0), 0, result)
        # 2 dossiers approuves restants (winner + quasi) renommes "Titre (Annee)".
        self.assertGreaterEqual(int(result.get("moves") or 0) + int(result.get("renames") or 0), 1, result)

        # Loser retire de sa racine d'origine...
        self.assertFalse((self.root_b / _LOSER_DIR).exists(), "loser encore dans root B apres apply")
        # ... et DEPLACE (pas supprime) dans le bucket _duplicates_user_decided.
        # Constat runtime : bucket = <state_dir>/runs/tri_films_<run>/_review/...
        # (la doc parle de <root>/_review/ — divergence doc, cf docstring module).
        bucket_candidates = [
            self.state_dir / "runs" / f"tri_films_{run_id}" / "_review" / "_duplicates_user_decided",
            self.root_b / "_review" / "_duplicates_user_decided",
            self.root_a / "_review" / "_duplicates_user_decided",
        ]
        moved_videos = [p for bucket in bucket_candidates if bucket.is_dir() for p in bucket.rglob(f"{_LOSER_DIR}.mkv")]
        self.assertEqual(
            len(moved_videos),
            1,
            f"video du loser attendue UNE fois dans un bucket _duplicates_user_decided, "
            f"trouvee: {moved_videos} (buckets scannes: {bucket_candidates})",
        )
        moved_video = moved_videos[0]
        self.assertEqual(_sha256(moved_video), self.loser_sha_before, "contenu du loser altere par le move")
        # Le winner, lui, a ete range normalement dans SA racine.
        winner_final = self.root_a / f"{_DUP_TITLE} ({_DUP_YEAR})"
        self.assertTrue(winner_final.is_dir(), f"dossier winner attendu: {winner_final}")
        self.assertTrue(list(winner_final.glob("*.mkv")), f"video winner absente de {winner_final}")

        # --- 6. UNDO reel : loser restaure a l'identique --------------------------
        undo = api.run.undo_last_apply(run_id, dry_run=False)
        self.assertTrue(undo.get("ok"), undo)
        restored = self.root_b / _LOSER_DIR / f"{_LOSER_DIR}.mkv"
        self.assertTrue(restored.exists(), f"loser non restaure par undo: {restored}")
        self.assertEqual(_sha256(restored), self.loser_sha_before, "contenu du loser altere par undo")
        self.assertFalse(moved_video.exists(), "loser toujours present dans le bucket apres undo")


class LotDDupBucketViewerGuardTests(unittest.TestCase):
    """Garde nominative [LOTD-DUP-BUCKET-VIEWER] (constate par cette chaine Lot D).

    Apres un apply avec decision doublon, le loser part dans
    <state_dir>/runs/tri_films_<run>/_review/_duplicates_user_decided/ mais le
    viewer quarantaine (api.run.list_quarantine_bucket) ne scanne que
    <root>/_review/ -> le loser est invisible pour l'utilisateur.

    xfail dynamique tant que la divergence est presente ; redeviendra passant
    quand le viewer verra le bucket reellement utilise par l'apply.
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="cinesort_lotd_viewer_", ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        base = Path(self._tmpdir.name)
        self.root = base / "root"
        self.state_dir = base / "state"
        self.root.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)

        patch_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        patch_min.start()
        self.addCleanup(patch_min.stop)

        # Doublon SAME-ROOT (suffit pour le bucket) : 2 copies, identite nfo commune.
        nfo_xml = f"<movie><title>{_DUP_TITLE}</title><year>{_DUP_YEAR}</year></movie>"
        for name, size, pat in ((_WINNER_DIR, _WINNER_BYTES, b"W"), (_LOSER_DIR, _LOSER_BYTES, b"L")):
            _mk_movie(self.root / name, name, size, pat)
            (self.root / name / f"{name}.nfo").write_text(nfo_xml, encoding="utf-8")

        self.api = CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def test_loser_visible_dans_viewer_quarantaine(self) -> None:
        api = self.api
        # settings persistes dans NOTRE state_dir tempdir (le viewer lit root
        # depuis les settings sauvegardes, pas depuis le run).
        saved = api.settings.save_settings(
            {
                "root": str(self.root),
                "roots": [str(self.root)],
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": False,
                "probe_backend": "none",
            }
        )
        self.assertTrue(saved.get("ok"), saved)

        start = api.run.start_plan(
            {
                "roots": [str(self.root)],
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": False,
                "probe_backend": "none",
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]
        _wait_done(api, run_id, timeout_s=30.0)

        rows = (api.run.get_plan(run_id) or {}).get("rows") or []
        self.assertEqual(len(rows), 2, rows)
        decisions = {r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]} for r in rows}
        winner_row = next(r for r in rows if _WINNER_DIR in str(r.get("folder") or ""))
        next(r for r in rows if _LOSER_DIR in str(r.get("folder") or ""))

        dup = api.run.check_duplicates(run_id, decisions)
        self.assertTrue(dup.get("ok"), dup)
        self.assertEqual(int(dup.get("total_groups") or 0), 1, dup)
        group = (dup.get("groups") or [])[0]
        group_key = f"{str(group.get('title') or '').strip().lower()}|{group.get('year')}"
        marked = api.run.mark_duplicate_winner(run_id, group_key, winner_row["row_id"])
        self.assertTrue(marked.get("ok"), marked)

        real = api.run.apply(run_id, decisions, False, False)
        self.assertTrue(real.get("ok"), real)
        self.assertEqual(int(real["result"].get("duplicates_user_decided_moved_count") or 0), 1, real["result"])
        self.assertFalse((self.root / _LOSER_DIR).exists(), "loser non deplace par apply")

        viewer = api.run.list_quarantine_bucket()
        self.assertTrue(viewer.get("ok"), viewer)
        listed = " | ".join(str(f.get("path") or f.get("rel") or f) for f in (viewer.get("files") or []))
        loser_token = f"{_LOSER_DIR}.mkv"
        if loser_token not in listed:
            pytest.xfail(
                "[LOTD-DUP-BUCKET-VIEWER] le loser a bien ete deplace par apply vers "
                "<state_dir>/runs/tri_films_<run>/_review/_duplicates_user_decided/ "
                "(apply_support.py:1540) mais list_quarantine_bucket ne scanne que "
                "<root>/_review (quarantine_ttl.review_root) -> "
                f"viewer files_count={viewer.get('files_count')}, review_root={viewer.get('review_root')} : "
                "le loser est invisible dans l'UI quarantaine (docstrings run_flow_support.py:1633 "
                "et run_facade.py:306 promettent <root>/_review)."
            )
        self.assertIn(loser_token, listed, "bug corrige : le viewer doit lister le loser")


class LotDDupTitleYearIdentityGuardTests(unittest.TestCase):
    """Garde nominative [LOTD-DUP-TITLE-YEAR] (constate par cette chaine Lot D).

    Meme film, meme annee detectee, 2 roots — mais un seul des 2 dossiers porte
    un tag qualite APRES l'annee. clean_title_guess garde alors l'annee dans le
    titre d'un cote seulement -> identites titre+annee differentes ->
    check_duplicates rate un VRAI doublon cross-root.

    xfail dynamique tant que le bug est present ; redeviendra passant quand le
    parsing du titre sera coherent (annee retiree dans les 2 cas).
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="cinesort_lotd_titleyear_", ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        base = Path(self._tmpdir.name)
        self.root_a = base / "rootA"
        self.root_b = base / "rootB"
        self.state_dir = base / "state"
        for d in (self.root_a, self.root_b, self.state_dir):
            d.mkdir(parents=True)

        patch_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        patch_min.start()
        self.addCleanup(patch_min.stop)

        # PAS de nfo : la seule source d'identite est le nom (cas offline courant).
        _mk_movie(self.root_a / "Le.Grand.Voyage.2005", "Le.Grand.Voyage.2005", _WINNER_BYTES, b"A")
        _mk_movie(self.root_b / _LOSER_DIR, _LOSER_DIR, _LOSER_BYTES, b"B")

        self.api = CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def test_meme_film_annee_taggee_doit_etre_groupe(self) -> None:
        api = self.api
        start = api.run.start_plan(
            {
                "roots": [str(self.root_a), str(self.root_b)],
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": False,
                "probe_backend": "none",
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]
        _wait_done(api, run_id, timeout_s=30.0)

        rows = (api.run.get_plan(run_id) or {}).get("rows") or []
        self.assertEqual(len(rows), 2, rows)
        # Les 2 copies partagent la meme annee detectee : l'identite DEVRAIT matcher.
        years = {int(r.get("proposed_year") or 0) for r in rows}
        self.assertEqual(years, {_DUP_YEAR}, rows)
        titles = {str(r.get("proposed_title") or "") for r in rows}

        decisions = {r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]} for r in rows}
        dup = api.run.check_duplicates(run_id, decisions)
        self.assertTrue(dup.get("ok"), dup)
        if int(dup.get("total_groups") or 0) == 0 and len(titles) > 1:
            pytest.xfail(
                "[LOTD-DUP-TITLE-YEAR] meme film / meme annee (2005) dans 2 roots mais "
                f"titres proposes divergents {sorted(titles)!r} : clean_title_guess garde "
                "l'annee dans le titre quand elle est suivie d'un tag qualite -> identites "
                "titre+annee differentes -> check_duplicates total_groups=0 (vrai doublon "
                "cross-root RATE, et cible redondante 'Titre 2005 (2005)')."
            )
        self.assertEqual(int(dup.get("total_groups") or 0), 1, dup)


class R8028FilesIdenticalQuickGuardTests(unittest.TestCase):
    """Garde nominative R8-028 : angle mort 'milieu du fichier' de files_identical_quick.

    files_identical_quick (chaine doublons : detection 'doublons identiques' et
    fusions sans blocage) hash uniquement les 8 premiers + 8 derniers Mo des
    fichiers >= 16 Mo. Deux fichiers de meme taille qui ne different qu'au
    milieu sont donc declares IDENTIQUES -> risque de fusion/ecart a tort.

    xfail dynamique tant que le bug est present ; le test redeviendra passant
    de lui-meme quand files_identical_quick couvrira le milieu du fichier.
    """

    def test_r8_028_middle_of_file_blind_spot(self) -> None:
        head = b"A" * (8 * _MB)
        tail = b"Z" * (8 * _MB)
        with tempfile.TemporaryDirectory(prefix="cinesort_lotd_r8028_") as tmp:
            base = Path(tmp)
            file_a = base / "a_17mb.mkv"
            file_b = base / "b_17mb.mkv"
            # ~17 Mo chacun (~34 Mo au total) : memes 8 premiers et 8 derniers Mo,
            # SEUL le Mo du milieu differe.
            file_a.write_bytes(head + (b"M" * _MB) + tail)
            file_b.write_bytes(head + (b"N" * _MB) + tail)

            self.assertEqual(file_a.stat().st_size, file_b.stat().st_size)
            self.assertNotEqual(_sha256(file_a), _sha256(file_b), "pre-condition : contenus differents")

            identical = files_identical_quick(file_a, file_b)
            if identical:
                pytest.xfail(
                    "[R8-028] files_identical_quick (cinesort/app/apply_core.py:340, via "
                    "sha1_quick L267 : 8 premiers + 8 derniers Mo seulement) declare "
                    "IDENTIQUES deux fichiers >16 Mo qui ne different qu'au milieu -> "
                    "un vrai doublon 'different' peut etre fusionne/ecarte a tort."
                )
            self.assertFalse(identical, "bug R8-028 corrige : garde redevenue passante")


if __name__ == "__main__":
    unittest.main(verbosity=2)
